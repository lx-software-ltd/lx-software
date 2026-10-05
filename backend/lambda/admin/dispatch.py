"""Admin API: dispatch."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs

import bank_sync as bank_sync_mod
import board_cache as board_cache_mod
import board_chat as board_chat_mod
import board_intel as board_intel_mod
import board_meeting as board_meeting_mod
import board_public_api as board_public_api_mod
import board_receivables as board_receivables_mod
import board_review as board_review_mod
import board_staff as board_staff_mod
import board_store
import evolvesprouts_finance as evolvesprouts_finance_mod
import parse_jobs as parse_jobs_mod
import runtime
from assets import (
    _asset_delete_response,
    _asset_download_presigned_response,
    _assets_list_response,
    _is_allowed_upload_content_type,
)
from board_routes import handle_board_route
from board_store import BOARD_PK_PREFIX
from botocore.exceptions import ClientError
from contract_constants import (
    EXPENSE_RECORD_CATEGORIES,
    FINANCE_HOUSE_KEYS,
    FINANCE_STATEMENT_BOOK_KEYS,
    FINANCE_STATEMENT_OWNER_KEYS,
    INCOME_RECORD_CATEGORIES,
    MIRRORED_STATEMENT_BOOK_KEYS,
    STATEMENT_BOOK_LABELS,
)
from ddb_convert import _from_ddb, _from_ddb_nested, _to_ddb, _to_ddb_nested
from finance_store import (
    MirroredBookError,
    _allocated_expense_ids_for_allocations,
    _build_allocation_records_for_response,
    _enrich_scan_items_asset_meta,
    _finance_ddb_key,
    _finance_owner_ddb_key,
    _load_accounts_records,
    _load_allocation_stored_records,
    _load_existing_expense_income_allocation_percentages,
    _load_finance_expenses_ledger_with_allocation,
    _load_finance_house,
    _load_finance_owner,
    _load_finance_sheet,
    _load_investment_records,
    _load_liabilities_records,
    _load_pension_records,
    _load_savings_records,
    _merge_accounts_last_updated,
    _merge_allocation_stored_last_updated,
    _merge_investment_last_updated,
    _merge_liabilities_last_updated,
    _merge_pension_last_updated,
    _normalize_accounts_sheet_payload,
    _normalize_allocations_sheet_payload,
    _normalize_finance_payload,
    _normalize_investment_sheet_payload,
    _normalize_ledger_sheet_payload,
    _normalize_liabilities_sheet_payload,
    _normalize_pension_sheet_payload,
    _normalize_savings_sheet_payload,
    _path_finance_house,
    _sanitize_expense_income_allocation_percentages,
    _validate_record_pk,
    put_finance_sheet,
)
from http_common import (
    _audit,
    _claims,
    _decode_cursor,
    _encode_cursor,
    _json_response,
    _log_event,
    _parse_json_body,
    _public_authorizer_context,
    _request_id,
    _require_admin,
    _route,
    _utc_iso_z,
    not_found,
)
from openrouter_usage import USAGE_PK_PREFIX, handle_usage_get
from parse_jobs import (
    _finalize_stuck_processing_job,
    _parse_job_key,
    _parse_job_public_doc,
    _path_finance_parse_job,
    _path_statement_book_parse_job,
    enqueue_parse_statement_async_job,
)
from parse_statement import (
    _path_finance_house_for_parse,
    _statement_basename_already_imported,
)
from proxies import _proxy_finance_quotes, _proxy_fx_v2_rates
from router import Route, route_matches
from runtime import PARSE_JOB_PK_PREFIX, RECORD_PK_PREFIX

# API-key mirrors of the admin endpoints, served under /public/* and
# authenticated by the Lambda authorizer instead of Cognito. Finance and
# records stay GET-only. Board GETs and (when the key has allowWrite plus
# PublicApiWritesEnabled) PUT/POST/DELETE are mirrored under
# ``PUBLIC_BOARD_PREFIX``. Assets and parse-job endpoints are excluded.
PUBLIC_READ_PATHS = frozenset(
    {
        "/public/finance",
        "/public/finance/quotes",
        "/public/records",
        "/public/fx/v2/rates",
    }
)
PUBLIC_BOARD_PREFIX = "/public/siu-tin-dei/board"


def _is_public_path(path: str) -> bool:
    if path in PUBLIC_READ_PATHS:
        return True
    return path == PUBLIC_BOARD_PREFIX or path.startswith(PUBLIC_BOARD_PREFIX + "/")


def _is_public_board_write_path(path: str) -> bool:
    return path.startswith(PUBLIC_BOARD_PREFIX + "/")

STATEMENT_BOOK_DISPLAY_LABEL = STATEMENT_BOOK_LABELS

# One module per mirrored book. Each exposes load_summary(table) and sync(table).
_STATEMENT_BOOK_MIRRORS = {
    evolvesprouts_finance_mod.BOOK: evolvesprouts_finance_mod,
}


def _statement_book_slug(book_key: str) -> str:
    out: list[str] = []
    for ch in book_key:
        if ch.isupper():
            out.append("-")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out)


def _match_statement_book_path(path: str) -> tuple[str, str] | None:
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    slug = parts[0]
    for key in FINANCE_STATEMENT_BOOK_KEYS:
        if _statement_book_slug(key) == slug:
            return key, slug
    return None


def _records_get_response(event: dict[str, Any]) -> dict[str, Any]:
    qs = event.get("rawQueryString") or ""
    cursor_raw = parse_qs(qs).get("cursor", [""])[0]
    start_key = _decode_cursor(cursor_raw)
    table = board_store.records_table()
    # Executive Board rows, OpenRouter usage ledgers, and parse-job META
    # never leave via the generic record browser or its public API-key mirror.
    kwargs: dict[str, Any] = {
        "Limit": 50,
        "FilterExpression": (
            "NOT begins_with(pk, :board) AND NOT begins_with(pk, :openrouter) "
            "AND NOT begins_with(pk, :parsejob) AND NOT begins_with(pk, :linkedin)"
        ),
        "ExpressionAttributeValues": {
            ":board": BOARD_PK_PREFIX,
            ":openrouter": USAGE_PK_PREFIX,
            ":parsejob": PARSE_JOB_PK_PREFIX,
            ":linkedin": "LINKEDIN#",
        },
    }
    if start_key:
        kwargs["ExclusiveStartKey"] = start_key
    result = table.scan(**kwargs)
    items = [_from_ddb(i) for i in result.get("Items", [])]
    bucket = os.environ.get("ASSETS_BUCKET_NAME") or ""
    items = _enrich_scan_items_asset_meta(items, table=table, bucket=bucket)
    last = result.get("LastEvaluatedKey")
    next_cursor = _encode_cursor(last) if last else None
    return _json_response(200, {"items": items, "nextCursor": next_cursor})


def _finance_get_response() -> dict[str, Any]:
    table = board_store.records_table()
    exp_rows, exp_pct = _load_finance_expenses_ledger_with_allocation(table)
    alloc_stored = _load_allocation_stored_records(table)
    income_rows = _load_finance_sheet(table, "income", INCOME_RECORD_CATEGORIES)
    allocation_records = _build_allocation_records_for_response(
        exp_rows, alloc_stored, income_rows, exp_pct
    )
    return _json_response(
        200,
        {
            "hillmarton": _load_finance_house(table, "hillmarton"),
            "morrison": _load_finance_house(table, "morrison"),
            "incomeRecords": income_rows,
            "expenseRecords": exp_rows,
            "expenseIncomeAllocationPercents": exp_pct,
            "investmentRecords": _load_investment_records(table),
            "savingsRecords": _load_savings_records(table),
            "pensionRecords": _load_pension_records(table),
            "accountRecords": _load_accounts_records(table),
            "liabilityRecords": _load_liabilities_records(table),
            "allocationRecords": allocation_records,
        },
    )


def _handle_public(
    event: dict[str, Any], method: str, path: str
) -> dict[str, Any]:
    """Serve /public/* routes for API key principals.

    API Gateway already enforced the key via the Lambda authorizer; the
    context check here is defense in depth against direct Lambda invocation
    or a route being wired to the wrong authorizer. Writes need allowWrite
    on the key, PublicApiWritesEnabled, and a board path that is not
    owner-only (settings, boundaries, tools, approvals, promote, selftest,
    chat delete, meeting/task cancel, staff tick, ramp pause).
    """
    key_ctx = _public_authorizer_context(event)
    key_id = key_ctx.get("keyId")
    scopes = board_public_api_mod.scopes_from_key_context(key_ctx)
    if not key_id or not scopes:
        _log_event(
            "warning",
            tag="public_api_denied",
            reason="missing_key_context",
            method=method,
            path=path,
            request_id=_request_id(event),
        )
        return _json_response(401, {"message": "Unauthorized"})

    is_write = method in board_public_api_mod.WRITE_METHODS
    if is_write:
        deny_reason = (
            "not_allowlisted"
            if not _is_public_board_write_path(path)
            else board_public_api_mod.write_deny_reason(method, path, key_ctx, scopes)
        )
        if deny_reason:
            _log_event(
                "warning",
                tag="public_api_denied",
                reason=deny_reason,
                key_id=key_id,
                method=method,
                path=path,
                path_class=board_public_api_mod.path_class(path),
                request_id=_request_id(event),
            )
            # Authenticated keys already passed the authorizer. Return 403 with
            # the deny reason so a write key can tell writes_disabled /
            # key_read_only / owner_only from a missing route. Unknown keys
            # never reach here (API Gateway 401/403).
            return _json_response(403, {"message": "Forbidden", "reason": deny_reason})
    elif method != "GET" or not _is_public_path(path):
        _log_event(
            "warning",
            tag="public_api_denied",
            reason="not_allowlisted",
            key_id=key_id,
            method=method,
            path=path,
            request_id=_request_id(event),
        )
        return not_found()
    elif not board_public_api_mod.path_allowed(path, scopes):
        _log_event(
            "warning",
            tag="public_api_denied",
            reason="scope",
            key_id=key_id,
            path=path,
            path_class=board_public_api_mod.path_class(path),
            request_id=_request_id(event),
        )
        return not_found()

    path_cls = board_public_api_mod.path_class(path)
    _log_event(
        "info",
        tag="public_api_write" if is_write else "public_api_access",
        key_id=key_id,
        method=method,
        path=path,
        path_class=path_cls,
        request_id=_request_id(event),
    )

    if path == PUBLIC_BOARD_PREFIX or path.startswith(PUBLIC_BOARD_PREFIX + "/"):
        board_path = path[len("/public") :]
        actor = f"apikey:{key_id}" if is_write else None
        board_response = handle_board_route(event, method, board_path, actor)
        if board_response is None:
            return not_found()
        board_response = board_public_api_mod.redact_board_response(path, board_response, scopes)
        board_public_api_mod.notify_key_use(
            event,
            key_ctx=key_ctx,
            path=path,
            method=method,
            kind="write" if is_write else "allowed",
            path_cls=path_cls,
        )
        return board_response
    if path == "/public/finance":
        response = _finance_get_response()
    elif path == "/public/finance/quotes":
        response = _proxy_finance_quotes(
            event.get("queryStringParameters"),
            _request_id(event),
        )
    elif path == "/public/fx/v2/rates":
        response = _proxy_fx_v2_rates(
            event.get("queryStringParameters"),
            _request_id(event),
        )
    else:
        response = _records_get_response(event)
    board_public_api_mod.notify_key_use(
        event, key_ctx=key_ctx, path=path, method=method, path_cls=path_cls
    )
    return response


def _ses_record_route(record: dict[str, Any]) -> str:
    body_raw = record.get("body") or ""
    try:
        body = json.loads(body_raw) if isinstance(body_raw, str) else body_raw
    except json.JSONDecodeError:
        return "outreach"
    if isinstance(body, dict) and body.get("Type") == "Notification" and body.get("Message"):
        try:
            body = json.loads(str(body["Message"]))
        except json.JSONDecodeError:
            return "outreach"
    if not isinstance(body, dict):
        return "outreach"
    tags = (body.get("mail") or {}).get("tags") or {}
    raw_cs = tags.get("ses:configuration-set") or tags.get("ses:configurationSet") or ""
    config = str(raw_cs[0] if isinstance(raw_cs, list) and raw_cs else raw_cs or "").lower()
    if "newsletter" in config or tags.get("issueId") or tags.get("issueid"):
        return "newsletter"
    return "outreach"


def _match_finance_house_put(method: str, path: str) -> bool:
    return method == "PUT" and path.startswith("/finance/") and not path.endswith("/parse-statement")

def _match_finance_parse_job(method: str, path: str) -> bool:
    return method == "GET" and "/parse-statement/jobs/" in path

def _match_finance_parse_post(method: str, path: str) -> bool:
    return (
        method == "POST"
        and path.startswith("/finance/")
        and path.endswith("/parse-statement")
        and "/parse-statement/jobs/" not in path
    )

def _internal_parse_statement_async(event):
    parse_jobs_mod._handle_parse_statement_async_worker(event)
    return {}

def _internal_bank_sync(event):
    bank_sync_mod.handle_bank_sync_worker(event)
    return {}

def _internal_board_chat(event):
    board_chat_mod.run_chat_worker(event)
    return {}

def _internal_board_meeting(event):
    if event.get("meetingId"):
        board_meeting_mod.run_meeting_phase(event)
    else:
        board_meeting_mod.handle_schedule_trigger(event)
    return {}

def _internal_board_cache_refresh(event):
    board_cache_mod.handle_schedule_trigger(event)
    return {}

def _internal_board_staff_step(event):
    board_staff_mod.run_step(event)
    return {}

def _internal_board_staff_review(event):
    board_staff_mod.run_review(event)
    return {}

def _internal_board_staff_tick(event):
    return board_staff_mod.handle_tick(event)

def _internal_board_triage_ack(event):
    import board_triage as board_triage_mod

    board_triage_mod.run_ack(event)
    return {}

def _internal_board_review_compile(event):
    return board_review_mod.handle_compile(event)

def _internal_board_review_send(event):
    return board_review_mod.handle_send(event)

def _internal_board_intel_crawl(event):
    return board_intel_mod.handle_crawl(event)

def _internal_board_intel_weekly(event):
    return board_intel_mod.handle_weekly(event)

def _internal_board_catalog_discovery(event):
    import board_catalog_discovery as board_catalog_discovery_mod

    return board_catalog_discovery_mod.handle_tick(event)

def _internal_board_catalog_bulk(event):
    import board_catalog_bulk as board_catalog_bulk_mod

    return board_catalog_bulk_mod.handle_job(event)

def _internal_board_targets(event):
    import board_targets as board_targets_mod

    return board_targets_mod.handle_check(event)

def _internal_board_content_plan(event):
    import board_content as board_content_mod

    return board_content_mod.handle_plan(event)

def _internal_board_content_readout(event):
    import board_content as board_content_mod

    return board_content_mod.handle_readout(event)

def _internal_board_receivables_mirror(event):
    board_receivables_mod.handle_mirror_trigger(event)
    return {}

def _internal_evolvesprouts_finance_mirror(event):
    return evolvesprouts_finance_mod.handle_mirror_trigger(event)

def _internal_board_dunning(event):
    board_receivables_mod.handle_dunning_trigger(event)
    return {}

def _internal_public_api_key_notify(event):
    return board_public_api_mod.handle_internal_notify(event)

def _internal_openrouter_usage_pull(event):
    import openrouter_usage_pull as openrouter_usage_pull_mod

    return openrouter_usage_pull_mod.handle_pull(event)

def _handle_sqs_batch(event):
    records = event.get("Records") if isinstance(event, dict) else None
    if not (isinstance(records, list) and records and records[0].get("eventSource") == "aws:sqs"):
        return None
    import board_newsletter as board_newsletter_mod
    import board_outreach as board_outreach_mod

    failures: list[dict[str, str]] = []
    outreach_n = 0
    newsletter_n = 0
    for record in records:
        try:
            route = _ses_record_route(record)
            if route == "newsletter":
                result = board_newsletter_mod.handle_ses_events([record])
                newsletter_n += int((result or {}).get("handled") or 0)
            else:
                result = board_outreach_mod.handle_ses_events([record])
                outreach_n += int((result or {}).get("handled") or 0)
        except Exception as exc:
            _log_event(
                "error",
                tag="ses_batch_record_failed",
                messageId=str(record.get("messageId") or record.get("messageID") or ""),
                error=str(exc)[:300],
            )
            mid = str(record.get("messageId") or record.get("messageID") or "")
            if mid:
                failures.append({"itemIdentifier": mid})
    return {
        "ok": True,
        "outreach": {"handled": outreach_n},
        "newsletter": {"handled": newsletter_n},
        "batchItemFailures": failures,
    }


def _http_meta_webhook(event, method, path, user_sub, admin_claims):
    import board_meta as board_meta_mod

    return board_meta_mod.handle_http(event, method)

def _http_outreach_unsubscribe(event, method, path, user_sub, admin_claims):
    import board_outreach as board_outreach_mod

    token = path[len("/public/outreach/unsubscribe/") :]
    return board_outreach_mod.handle_unsubscribe(event, method, token)

def _http_newsletter_subscribe(event, method, path, user_sub, admin_claims):
    import board_newsletter as board_newsletter_mod

    return board_newsletter_mod.handle_subscribe(event)

def _http_newsletter_confirm(event, method, path, user_sub, admin_claims):
    import board_newsletter as board_newsletter_mod

    token = path[len("/public/newsletter/confirm/") :]
    return board_newsletter_mod.handle_confirm(event, token)

def _http_newsletter_unsubscribe(event, method, path, user_sub, admin_claims):
    import board_newsletter as board_newsletter_mod

    token = path[len("/public/newsletter/unsubscribe/") :]
    return board_newsletter_mod.handle_unsubscribe(event, method, token)

def _http_health(event, method, path, user_sub, admin_claims):
    return _json_response(200, {"status": "ok"})

def _http_public_api(event, method, path, user_sub, admin_claims):
    return _handle_public(event, method, path)

def _http_me(event, method, path, user_sub, admin_claims):
    return _json_response(
        200,
        {
            "sub": admin_claims.get("sub"),
            "email": admin_claims.get("email"),
            "cognito_username": admin_claims.get("cognito:username"),
        },
    )

def _http_openrouter_usage(event, method, path, user_sub, admin_claims):
    return handle_usage_get(event)

def _http_aws_usage(event, method, path, user_sub, admin_claims):
    from aws_billing import handle_usage_get as handle_aws_usage_get

    return handle_aws_usage_get(event)

def _http_aws_usage_pdf(event, method, path, user_sub, admin_claims):
    from aws_billing import handle_usage_pdf as handle_aws_usage_pdf

    return handle_aws_usage_pdf(event)

def _http_fx_rates(event, method, path, user_sub, admin_claims):
    return _proxy_fx_v2_rates(
        event.get("queryStringParameters"),
        _request_id(event),
    )

def _http_finance_quotes(event, method, path, user_sub, admin_claims):
    return _proxy_finance_quotes(
        event.get("queryStringParameters"),
        _request_id(event),
    )

def _http_banking(event, method, path, user_sub, admin_claims):
    return bank_sync_mod.handle_banking_get(event)

def _http_banking_banks(event, method, path, user_sub, admin_claims):
    return bank_sync_mod.handle_banking_banks(event)

def _http_banking_auth(event, method, path, user_sub, admin_claims):
    return bank_sync_mod.handle_banking_auth_start(event, user_sub)

def _http_banking_sessions(event, method, path, user_sub, admin_claims):
    return bank_sync_mod.handle_banking_auth_complete(event, user_sub)

def _http_banking_session_delete(event, method, path, user_sub, admin_claims):
    session_id = path[len("/banking/sessions/"):]
    return bank_sync_mod.handle_banking_session_delete(
        event, user_sub, session_id
    )

def _http_banking_mappings(event, method, path, user_sub, admin_claims):
    return bank_sync_mod.handle_banking_mappings_put(event, user_sub)

def _http_banking_sync(event, method, path, user_sub, admin_claims):
    return bank_sync_mod.handle_banking_sync_post(event, user_sub)

def _http_asset_upload_url(event, method, path, user_sub, admin_claims):
    body = _parse_json_body(event)
    filename = body.get("filename")
    content_type = body.get("contentType")
    if not filename or not content_type:
        return _json_response(
            400, {"message": "filename and contentType are required"}
        )
    if not _is_allowed_upload_content_type(str(content_type)):
        _log_event(
            "warning",
            tag="asset_upload_url_rejected",
            reason="unsupported_content_type",
            sub=user_sub,
            content_type_raw=str(content_type)[:128],
            request_id=_request_id(event),
        )
        return _json_response(
            400,
            {
                "message": (
                    "contentType must be image/* or application/pdf"
                )
            },
        )
    if not user_sub:
        return _json_response(400, {"message": "Missing sub claim"})
    safe_name = os.path.basename(str(filename))
    object_key = f"uploads/{user_sub}/{uuid.uuid4().hex}/{safe_name}"
    bucket = os.environ["ASSETS_BUCKET_NAME"]
    max_bytes = int(os.environ.get("ASSET_MAX_BYTES", str(20 * 1024 * 1024)))
    normalized_ct = str(content_type).strip().lower()
    if normalized_ct == "application/pdf":
        content_type_condition = ["eq", "$Content-Type", "application/pdf"]
    else:
        content_type_condition = ["starts-with", "$Content-Type", "image/"]
    conditions = [
        ["content-length-range", 1, max_bytes],
        content_type_condition,
        ["eq", "$key", object_key],
    ]
    # NOTE: the form field carries the *raw* client-supplied casing while
    # the explicit `eq` condition is hardcoded lowercase. S3 evaluates
    # `eq` case-sensitively, so a non-canonical client casing (e.g.
    # "Application/PDF") will result in the browser POST being rejected
    # with HTTP 403 / `<Code>AccessDenied</Code>` even though
    # /assets/upload-url returned 200. Logged below so CloudWatch can
    # show the gap without having to reproduce in a browser.
    fields = {"Content-Type": str(content_type), "key": object_key}
    post = runtime._s3.generate_presigned_post(
        Bucket=bucket,
        Key=object_key,
        Fields=fields,
        Conditions=conditions,
        ExpiresIn=300,
    )
    _log_event(
        "info",
        tag="asset_upload_url_issued",
        sub=user_sub,
        key=object_key,
        content_type_raw=str(content_type)[:128],
        content_type_normalized=normalized_ct[:128],
        content_type_matches_policy=(
            str(content_type) == normalized_ct
            if normalized_ct == "application/pdf"
            else str(content_type).lower().startswith("image/")
        ),
        policy_content_type_rule=" ".join(str(part) for part in content_type_condition),
        max_bytes=max_bytes,
        expires_in_seconds=300,
        request_id=_request_id(event),
    )
    _audit(user_sub, "ASSET_UPLOAD_URL", object_key, event)
    return _json_response(200, {"upload": post, "key": object_key})

def _http_asset_confirm(event, method, path, user_sub, admin_claims):
    body = _parse_json_body(event)
    key = body.get("key")
    if key is None:
        return _json_response(400, {"message": "key is required"})
    if not user_sub:
        return _json_response(400, {"message": "Missing sub claim"})
    house_raw = body.get("house")
    house_val: str | None = None
    if house_raw is not None:
        if (
            not isinstance(house_raw, str)
            or house_raw not in FINANCE_STATEMENT_OWNER_KEYS
        ):
            owners = ", ".join(sorted(FINANCE_STATEMENT_OWNER_KEYS))
            return _json_response(
                400,
                {"message": f"house must be {owners} when provided"},
            )
        house_val = house_raw
    prefix = f"uploads/{user_sub}/"
    if not str(key).startswith(prefix):
        _log_event(
            "warning",
            tag="asset_confirm_rejected",
            reason="prefix_mismatch",
            sub=user_sub,
            key=str(key)[:512],
            request_id=_request_id(event),
        )
        return _json_response(400, {"message": "Invalid key for this user"})
    bucket = os.environ["ASSETS_BUCKET_NAME"]
    try:
        head = runtime._s3.head_object(Bucket=bucket, Key=str(key))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            _log_event(
                "warning",
                tag="asset_confirm_not_in_bucket",
                sub=user_sub,
                key=str(key)[:512],
                s3_error_code=code,
                request_id=_request_id(event),
            )
            return _json_response(400, {"message": "Object not found in bucket"})
        raise
    size = int(head["ContentLength"])
    etag = head.get("ETag", "").strip('"')
    last_mod = head.get("LastModified")
    if isinstance(last_mod, datetime):
        uploaded_at = _utc_iso_z(last_mod)
    else:
        uploaded_at = _utc_iso_z(datetime.now(timezone.utc))
    file_name = os.path.basename(str(key))
    table = board_store.records_table()
    ddb_key = {"pk": f"ASSET#{key}", "sk": "META"}
    item: dict[str, Any] = {
        **ddb_key,
        "size": size,
        "s3Etag": etag,
        "ownerSub": user_sub,
        "clientSha256": body.get("sha256"),
        "clientReportedSize": body.get("size"),
        "note": "size and s3Etag are from S3 head_object; client fields are informational only",
        "uploadedAt": uploaded_at,
        "fileName": file_name,
    }
    if house_val is not None:
        item["house"] = house_val
    table.put_item(Item=_to_ddb(item))
    _log_event(
        "info",
        tag="asset_confirm_ok",
        sub=user_sub,
        key=str(key)[:512],
        size_bytes=size,
        client_reported_size=body.get("size"),
        has_client_sha256=bool(body.get("sha256")),
        request_id=_request_id(event),
    )
    _audit(user_sub, "ASSET_CONFIRM", str(key), event)
    return _json_response(201, {"item": _from_ddb(item)})

def _http_assets_list(event, method, path, user_sub, admin_claims):
    return _assets_list_response(event)

def _http_asset_download_get(event, method, path, user_sub, admin_claims):
    qs = event.get("rawQueryString") or ""
    key_param = parse_qs(qs).get("key", [""])[0]
    return _asset_download_presigned_response(event, user_sub, key_param)

def _http_asset_download_post(event, method, path, user_sub, admin_claims):
    body = _parse_json_body(event)
    return _asset_download_presigned_response(event, user_sub, body.get("key"))

def _http_asset_delete(event, method, path, user_sub, admin_claims):
    body = _parse_json_body(event)
    return _asset_delete_response(event, user_sub, body.get("key"))

def _http_records_get(event, method, path, user_sub, admin_claims):
    return _records_get_response(event)

def _http_records_create(event, method, path, user_sub, admin_claims):
    body = _parse_json_body(event)
    pk = body.get("pk")
    sk = body.get("sk")
    if not pk or not sk:
        return _json_response(400, {"message": "pk and sk are required"})
    if not _validate_record_pk(str(pk)):
        return _json_response(
            400,
            {"message": f"pk must start with {RECORD_PK_PREFIX} for creates"},
        )
    data = body.get("data")
    table = board_store.records_table()
    item: dict[str, Any] = {"pk": pk, "sk": sk}
    if isinstance(data, dict):
        for k, v in data.items():
            if k in ("pk", "sk"):
                continue
            item[k] = v
    try:
        table.put_item(
            Item=_to_ddb(item),
            ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
        )
    except ClientError as exc:
        if (
            exc.response.get("Error", {}).get("Code")
            == "ConditionalCheckFailedException"
        ):
            return _json_response(409, {"message": "Record already exists"})
        raise
    _audit(user_sub, "RECORD_CREATE", f"{pk}|{sk}", event)
    return _json_response(201, {"item": _from_ddb(item)})

def _http_records_update(event, method, path, user_sub, admin_claims):
    body = _parse_json_body(event)
    pk = body.get("pk")
    sk = body.get("sk")
    if not pk or not sk:
        return _json_response(400, {"message": "pk and sk are required"})
    if not _validate_record_pk(str(pk)):
        return _json_response(
            400,
            {"message": f"pk must start with {RECORD_PK_PREFIX}"},
        )
    data = body.get("data")
    table = board_store.records_table()
    item: dict[str, Any] = {"pk": pk, "sk": sk}
    if isinstance(data, dict):
        for k, v in data.items():
            if k in ("pk", "sk"):
                continue
            item[k] = v
    try:
        table.put_item(
            Item=_to_ddb(item),
            ConditionExpression="attribute_exists(pk) AND attribute_exists(sk)",
        )
    except ClientError as exc:
        if (
            exc.response.get("Error", {}).get("Code")
            == "ConditionalCheckFailedException"
        ):
            return _json_response(404, {"message": "Record not found for update"})
        raise
    _audit(user_sub, "RECORD_UPDATE", f"{pk}|{sk}", event)
    return _json_response(200, {"item": _from_ddb(item)})

def _http_finance_get(event, method, path, user_sub, admin_claims):
    return _finance_get_response()

def _http_finance_ledger_put(event, method, path, user_sub, admin_claims):
    sheet_routes: dict[str, tuple[str, frozenset[str], str]] = {
        "/finance/income": ("income", INCOME_RECORD_CATEGORIES, "incomeRecords"),
        "/finance/expenses": (
            "expenses",
            EXPENSE_RECORD_CATEGORIES,
            "expenseRecords",
        ),
    }
    sheet_slug, cats, body_key = sheet_routes[path]
    body = _parse_json_body(event)
    try:
        normalized = _normalize_ledger_sheet_payload(
            body, body_key=body_key, categories=cats
        )
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    table = board_store.records_table()
    if sheet_slug == "expenses":
        existing_perc = _load_existing_expense_income_allocation_percentages(table)
        if isinstance(body.get("expenseIncomeAllocationPercents"), dict):
            patched_perc = _sanitize_expense_income_allocation_percentages(
                body["expenseIncomeAllocationPercents"]
            )
        else:
            patched_perc = existing_perc
        extra = {"expenseIncomeAllocationPercents": patched_perc}
    else:
        extra = None
    put_finance_sheet(table, sheet_slug, normalized, extra)
    _audit(user_sub, "FINANCE_PUT", sheet_slug, event)
    if sheet_slug == "expenses":
        return _json_response(
            200,
            {
                body_key: normalized,
                "expenseIncomeAllocationPercents": patched_perc,
            },
        )
    return _json_response(200, {body_key: normalized})

def _http_finance_investments_put(event, method, path, user_sub, admin_claims):
    body = _parse_json_body(event)
    try:
        normalized = _normalize_investment_sheet_payload(body)
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    table = board_store.records_table()
    existing = _load_investment_records(table)
    merged = _merge_investment_last_updated(normalized, existing)
    put_finance_sheet(table, "investments", merged)
    _audit(user_sub, "FINANCE_PUT", "investments", event)
    return _json_response(200, {"investmentRecords": merged})

def _http_finance_savings_put(event, method, path, user_sub, admin_claims):
    body = _parse_json_body(event)
    try:
        normalized = _normalize_savings_sheet_payload(body)
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    table = board_store.records_table()
    put_finance_sheet(table, "savings", normalized)
    _audit(user_sub, "FINANCE_PUT", "savings", event)
    return _json_response(200, {"savingsRecords": normalized})

def _http_finance_pension_put(event, method, path, user_sub, admin_claims):
    body = _parse_json_body(event)
    try:
        normalized = _normalize_pension_sheet_payload(body)
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    table = board_store.records_table()
    existing = _load_pension_records(table)
    merged = _merge_pension_last_updated(normalized, existing)
    put_finance_sheet(table, "pension", merged)
    _audit(user_sub, "FINANCE_PUT", "pension", event)
    return _json_response(200, {"pensionRecords": merged})

def _http_finance_accounts_put(event, method, path, user_sub, admin_claims):
    body = _parse_json_body(event)
    try:
        normalized = _normalize_accounts_sheet_payload(body)
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    table = board_store.records_table()
    existing = _load_accounts_records(table)
    merged = _merge_accounts_last_updated(normalized, existing)
    put_finance_sheet(table, "accounts", merged)
    _audit(user_sub, "FINANCE_PUT", "accounts", event)
    return _json_response(200, {"accountRecords": merged})

def _http_finance_liabilities_put(event, method, path, user_sub, admin_claims):
    body = _parse_json_body(event)
    try:
        normalized = _normalize_liabilities_sheet_payload(body)
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    table = board_store.records_table()
    existing = _load_liabilities_records(table)
    merged = _merge_liabilities_last_updated(normalized, existing)
    put_finance_sheet(table, "liabilities", merged)
    _audit(user_sub, "FINANCE_PUT", "liabilities", event)
    return _json_response(200, {"liabilityRecords": merged})

def _http_finance_allocations_put(event, method, path, user_sub, admin_claims):
    body = _parse_json_body(event)
    table = board_store.records_table()
    allocated_ids = _allocated_expense_ids_for_allocations(table)
    try:
        normalized = _normalize_allocations_sheet_payload(body, allocated_ids)
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    existing = _load_allocation_stored_records(table)
    merged_stored = _merge_allocation_stored_last_updated(normalized, existing)
    put_finance_sheet(table, "allocations", merged_stored)
    _audit(user_sub, "FINANCE_PUT", "allocations", event)
    exp_rows, exp_pct = _load_finance_expenses_ledger_with_allocation(table)
    inc_rows = _load_finance_sheet(table, "income", INCOME_RECORD_CATEGORIES)
    allocation_response = _build_allocation_records_for_response(
        exp_rows, merged_stored, inc_rows, exp_pct
    )
    return _json_response(200, {"allocationRecords": allocation_response})

def _http_board(event, method, path, user_sub, admin_claims):
    return handle_board_route(event, method, path, user_sub)

def _http_statement_book(event, method, path, user_sub, admin_claims):
    book_match = _match_statement_book_path(path)
    if book_match:
        book_key, slug = book_match
        book_label = STATEMENT_BOOK_DISPLAY_LABEL.get(book_key, book_key)
        mirrored = book_key in MIRRORED_STATEMENT_BOOK_KEYS

        mirror = _STATEMENT_BOOK_MIRRORS.get(book_key) if mirrored else None
        if mirrored and mirror is None and path in (f"/{slug}/summary", f"/{slug}/sync"):
            return not_found()

        if mirror is not None and method == "GET" and path == f"/{slug}/summary":
            table = board_store.records_table()
            return _json_response(200, mirror.load_summary(table))

        if mirror is not None and method == "POST" and path == f"/{slug}/sync":
            table = board_store.records_table()
            try:
                result = mirror.queue_sync(table)
            except MirroredBookError as exc:
                return _json_response(502, {"message": str(exc)})
            return _json_response(200, result)

        if mirrored and method == "PUT":
            return _json_response(
                403,
                {"message": f"{book_label} records come from the product database and cannot be edited here."},
            )

        if mirrored and method == "POST" and path == f"/{slug}/parse-statement":
            return _json_response(
                403,
                {"message": f"{book_label} records come from the product database and cannot be edited here."},
            )

        if method == "GET" and path == f"/{slug}":
            table = board_store.records_table()
            return _json_response(200, {"data": _load_finance_owner(table, book_key)})

        if method == "PUT" and path == f"/{slug}":
            body = _parse_json_body(event)
            if not isinstance(body, dict):
                body = {}
            body = {**body, "defaultCurrency": "HKD"}
            if not isinstance(body.get("float"), dict):
                body["float"] = {"amount": 0, "currency": "HKD"}
            try:
                normalized = _normalize_finance_payload(body)
            except ValueError as exc:
                return _json_response(400, {"message": str(exc)})
            for i, ln in enumerate(normalized.get("lines") or []):
                if ln.get("type") == "mortgage":
                    return _json_response(
                        400,
                        {"message": f"lines[{i}].type must be income or expenditure"},
                    )
            table = board_store.records_table()
            ddb_item = {
                **_finance_owner_ddb_key(book_key),
                **_to_ddb_nested(normalized),
            }
            table.put_item(Item=ddb_item)
            _audit(user_sub, "FINANCE_PUT", book_key, event)
            return _json_response(200, {"data": normalized})

        if method == "GET" and path.startswith(f"/{slug}/parse-statement/jobs/"):
            job_id = _path_statement_book_parse_job(event, path, slug)
            if not job_id:
                return not_found()
            if not user_sub:
                return _json_response(400, {"message": "Missing sub claim"})
            table = board_store.records_table()
            raw = table.get_item(Key=_parse_job_key(job_id))
            item = raw.get("Item")
            if not item:
                return _json_response(404, {"message": "Job not found"})
            doc = _from_ddb_nested(item)
            if doc.get("ownerSub") != user_sub:
                return _json_response(403, {"message": "Forbidden"})
            if doc.get("house") != book_key:
                return _json_response(400, {"message": "Book does not match job"})
            doc = _finalize_stuck_processing_job(table, _parse_job_key(job_id), doc)
            return _json_response(200, _parse_job_public_doc(doc))

        if method == "POST" and path == f"/{slug}/parse-statement":
            if not user_sub:
                return _json_response(400, {"message": "Missing sub claim"})
            body = _parse_json_body(event)
            key = body.get("key")
            if not isinstance(key, str) or not key.strip():
                return _json_response(400, {"message": "key is required"})
            prefix = f"uploads/{user_sub}/"
            if not key.startswith(prefix):
                return _json_response(400, {"message": "Invalid key for this user"})
            line_type_only = body.get("lineTypeOnly")
            if line_type_only not in ("income", "expenditure"):
                return _json_response(
                    400,
                    {"message": "lineTypeOnly must be income or expenditure"},
                )
            table = board_store.records_table()
            book_data = _load_finance_owner(table, book_key)
            file_name = os.path.basename(key)
            if _statement_basename_already_imported(book_data, file_name):
                return _json_response(
                    409,
                    {
                        "message": (
                            f"A statement file named {file_name!r} was already imported "
                            f"for {book_label}. Remove its imported lines or rename the "
                            "file, then try again."
                        )
                    },
                )
            try:
                job_id = enqueue_parse_statement_async_job(
                    house=book_key,
                    s3_keys=[key],
                    owner_sub=user_sub,
                    api_request_id=_request_id(event),
                    source="api",
                    line_type_only=line_type_only,
                )
            except Exception as exc:
                _log_event(
                    "error",
                    tag="parse_job_enqueue_failed",
                    err=str(exc)[:400],
                    request_id=_request_id(event),
                )
                return _json_response(
                    502,
                    {"message": "Could not start statement parse job"},
                )
            _log_event(
                "info",
                tag="parse_job_enqueued",
                sub=user_sub,
                house=book_key,
                job_id=job_id,
                request_id=_request_id(event),
            )
            return _json_response(202, {"jobId": job_id, "status": "pending"})
    return None

def _http_finance_house_put(event, method, path, user_sub, admin_claims):
    house = _path_finance_house(event, path)
    if not house or house not in FINANCE_HOUSE_KEYS:
        return _json_response(
            400,
            {"message": "house must be hillmarton or morrison"},
        )
    body = _parse_json_body(event)
    try:
        normalized = _normalize_finance_payload(body)
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    table = board_store.records_table()
    ddb_item = {**_finance_ddb_key(house), **_to_ddb_nested(normalized)}
    table.put_item(Item=ddb_item)
    _audit(user_sub, "FINANCE_PUT", house, event)
    return _json_response(200, {"data": normalized})

def _http_finance_parse_job(event, method, path, user_sub, admin_claims):
    house_j, job_id = _path_finance_parse_job(event, path)
    if not house_j or house_j not in FINANCE_HOUSE_KEYS or not job_id:
        return not_found()
    if not user_sub:
        return _json_response(400, {"message": "Missing sub claim"})
    table = board_store.records_table()
    raw = table.get_item(Key=_parse_job_key(job_id))
    item = raw.get("Item")
    if not item:
        return _json_response(404, {"message": "Job not found"})
    doc = _from_ddb_nested(item)
    if doc.get("ownerSub") != user_sub:
        return _json_response(403, {"message": "Forbidden"})
    if doc.get("house") != house_j:
        return _json_response(400, {"message": "House does not match job"})
    doc = _finalize_stuck_processing_job(table, _parse_job_key(job_id), doc)
    return _json_response(200, _parse_job_public_doc(doc))

def _http_finance_parse_post(event, method, path, user_sub, admin_claims):
    house = _path_finance_house_for_parse(event, path)
    if not house or house not in FINANCE_HOUSE_KEYS:
        return _json_response(
            400,
            {"message": "house must be hillmarton or morrison"},
        )
    if not user_sub:
        return _json_response(400, {"message": "Missing sub claim"})
    body = _parse_json_body(event)
    key = body.get("key")
    if not isinstance(key, str) or not key.strip():
        return _json_response(400, {"message": "key is required"})
    prefix = f"uploads/{user_sub}/"
    if not key.startswith(prefix):
        return _json_response(400, {"message": "Invalid key for this user"})
    table = board_store.records_table()
    house_data = _load_finance_house(table, house)
    file_name = os.path.basename(key)
    if _statement_basename_already_imported(house_data, file_name):
        return _json_response(
            409,
            {
                "message": (
                    f"A statement file named {file_name!r} was already imported for this house. "
                    "Remove its imported lines or rename the file, then try again."
                )
            },
        )
    mortgage_only = body.get("mortgageOnly") is True
    try:
        job_id = enqueue_parse_statement_async_job(
            house=house,
            s3_keys=[key],
            owner_sub=user_sub,
            api_request_id=_request_id(event),
            source="api",
            mortgage_only=mortgage_only,
        )
    except Exception as exc:
        _log_event(
            "error",
            tag="parse_job_enqueue_failed",
            err=str(exc)[:400],
            request_id=_request_id(event),
        )
        return _json_response(
            502,
            {"message": "Could not start statement parse job"},
        )
    _log_event(
        "info",
        tag="parse_job_enqueued",
        sub=user_sub,
        house=house,
        job_id=job_id,
        request_id=_request_id(event),
    )
    return _json_response(202, {"jobId": job_id, "status": "pending"})

def _http_linkedin(event, method, path, user_sub, admin_claims):
    del admin_claims
    import linkedin

    return linkedin.handle_http(event, method, path, user_sub)


def _internal_linkedin_generate(event):
    import linkedin

    return linkedin.handle_generate(event)


def _internal_linkedin_weekly_plan(event):
    import linkedin

    return linkedin.handle_weekly_plan(event)


def _internal_linkedin_publish_due(event):
    import linkedin

    return linkedin.handle_publish_due(event)


def _internal_linkedin_image(event):
    import linkedin

    return linkedin.handle_post_image(event)


def _internal_linkedin_character(event):
    import linkedin

    return linkedin.handle_character_draw(event)


def _match_linkedin(method: str, path: str) -> bool:
    del method
    return path == "/lx-software/linkedin" or path.startswith("/lx-software/linkedin/")


EARLY_INTERNAL = {
    'parse_statement_async': _internal_parse_statement_async,
    'bank_sync': _internal_bank_sync,
    'board_chat': _internal_board_chat,
    'board_meeting': _internal_board_meeting,
    'board_cache_refresh': _internal_board_cache_refresh,
    'board_staff_step': _internal_board_staff_step,
    'board_staff_review': _internal_board_staff_review,
    'board_staff_tick': _internal_board_staff_tick,
    'board_triage_ack': _internal_board_triage_ack,
    'board_review_compile': _internal_board_review_compile,
    'board_review_send': _internal_board_review_send,
    'board_intel_crawl': _internal_board_intel_crawl,
    'board_intel_weekly': _internal_board_intel_weekly,
    'board_catalog_discovery': _internal_board_catalog_discovery,
    'board_catalog_bulk': _internal_board_catalog_bulk,
    'board_targets': _internal_board_targets,
    'board_content_plan': _internal_board_content_plan,
    'board_content_readout': _internal_board_content_readout,
    'linkedin_generate': _internal_linkedin_generate,
    'linkedin_weekly_plan': _internal_linkedin_weekly_plan,
    'linkedin_publish_due': _internal_linkedin_publish_due,
    'linkedin_image': _internal_linkedin_image,
    'linkedin_character': _internal_linkedin_character,
}

LATE_INTERNAL = {
    'board_receivables_mirror': _internal_board_receivables_mirror,
    'evolvesprouts_finance_mirror': _internal_evolvesprouts_finance_mirror,
    'board_dunning': _internal_board_dunning,
    'public_api_key_notify': _internal_public_api_key_notify,
    'openrouter_usage_pull': _internal_openrouter_usage_pull,
}

HTTP_ROUTES = [
    Route('*', '/webhooks/meta', _http_meta_webhook, 'none', kind='exact', match=None),
    Route('*', '/webhooks/meta/siutindei', _http_meta_webhook, 'none', kind='exact', match=None),
    Route('*', '/public/outreach/unsubscribe/', _http_outreach_unsubscribe, 'none', kind='prefix', match=None),
    Route('POST', '/public/newsletter/subscribe', _http_newsletter_subscribe, 'none', kind='exact', match=None),
    Route('*', '/public/newsletter/confirm/', _http_newsletter_confirm, 'none', kind='prefix', match=None),
    Route('*', '/public/newsletter/unsubscribe/', _http_newsletter_unsubscribe, 'none', kind='prefix', match=None),
    Route('GET', '/health', _http_health, 'none', kind='exact', match=None),
    Route('*', '/public', _http_public_api, 'public', kind='public', match=None),
    Route('GET', '/me', _http_me, 'admin', kind='exact', match=None),
    Route('GET', '/openrouter/usage', _http_openrouter_usage, 'admin', kind='exact', match=None),
    Route('GET', '/aws/usage', _http_aws_usage, 'admin', kind='exact', match=None),
    Route('GET', '/aws/usage.pdf', _http_aws_usage_pdf, 'admin', kind='exact', match=None),
    Route('GET', '/fx/v2/rates', _http_fx_rates, 'admin', kind='exact', match=None),
    Route('GET', '/finance/quotes', _http_finance_quotes, 'admin', kind='exact', match=None),
    Route('*', '/lx-software/linkedin', _http_linkedin, 'admin', kind='custom', match=_match_linkedin),
    Route('GET', '/banking', _http_banking, 'admin', kind='exact', match=None),
    Route('GET', '/banking/banks', _http_banking_banks, 'admin', kind='exact', match=None),
    Route('POST', '/banking/auth', _http_banking_auth, 'admin', kind='exact', match=None),
    Route('POST', '/banking/sessions', _http_banking_sessions, 'admin', kind='exact', match=None),
    Route('DELETE', '/banking/sessions/', _http_banking_session_delete, 'admin', kind='prefix', match=None),
    Route('PUT', '/banking/mappings', _http_banking_mappings, 'admin', kind='exact', match=None),
    Route('POST', '/banking/sync', _http_banking_sync, 'admin', kind='exact', match=None),
    Route('POST', '/assets/upload-url', _http_asset_upload_url, 'admin', kind='exact', match=None),
    Route('POST', '/assets/confirm', _http_asset_confirm, 'admin', kind='exact', match=None),
    Route('GET', '/assets', _http_assets_list, 'admin', kind='exact', match=None),
    Route('GET', '/assets/download-url', _http_asset_download_get, 'admin', kind='exact', match=None),
    Route('POST', '/assets/download-url', _http_asset_download_post, 'admin', kind='exact', match=None),
    Route('POST', '/assets/delete', _http_asset_delete, 'admin', kind='exact', match=None),
    Route('GET', '/records', _http_records_get, 'admin', kind='exact', match=None),
    Route('POST', '/records', _http_records_create, 'admin', kind='exact', match=None),
    Route('PUT', '/records', _http_records_update, 'admin', kind='exact', match=None),
    Route('GET', '/finance', _http_finance_get, 'admin', kind='exact', match=None),
    Route('PUT', '/finance/income', _http_finance_ledger_put, 'admin', kind='exact', match=None),
    Route('PUT', '/finance/expenses', _http_finance_ledger_put, 'admin', kind='exact', match=None),
    Route('PUT', '/finance/investments', _http_finance_investments_put, 'admin', kind='exact', match=None),
    Route('PUT', '/finance/savings', _http_finance_savings_put, 'admin', kind='exact', match=None),
    Route('PUT', '/finance/pension', _http_finance_pension_put, 'admin', kind='exact', match=None),
    Route('PUT', '/finance/accounts', _http_finance_accounts_put, 'admin', kind='exact', match=None),
    Route('PUT', '/finance/liabilities', _http_finance_liabilities_put, 'admin', kind='exact', match=None),
    Route('PUT', '/finance/allocations', _http_finance_allocations_put, 'admin', kind='exact', match=None),
    Route('*', '', _http_board, 'admin', kind='any', match=None),
    Route('*', '', _http_statement_book, 'admin', kind='any', match=None),
    Route('PUT', '/finance/', _http_finance_house_put, 'admin', kind='custom', match=_match_finance_house_put),
    Route('GET', '/parse-statement/jobs/', _http_finance_parse_job, 'admin', kind='custom', match=_match_finance_parse_job),
    Route('POST', '/parse-statement', _http_finance_parse_post, 'admin', kind='custom', match=_match_finance_parse_post),
]


def _dispatch_http(event):
    method, path = _route(event)
    for route in HTTP_ROUTES:
        if route.auth != "none":
            continue
        if not route_matches(route, method, path):
            continue
        return route.handler(event, method, path, None, None)
    for route in HTTP_ROUTES:
        if route.auth != "public":
            continue
        if route_matches(route, method, path):
            return route.handler(event, method, path, None, None)
    admin_claims = _require_admin(event)
    if admin_claims is None:
        if not _claims(event):
            _log_event("info", tag="admin_auth_denied", reason="missing_claims")
            return _json_response(401, {"message": "Unauthorized"})
        _log_event("info", tag="admin_auth_denied", reason="not_in_admin_group")
        return _json_response(403, {"message": "Forbidden: admin group required"})
    user_sub = admin_claims.get("sub")
    for route in HTTP_ROUTES:
        if route.auth != "admin":
            continue
        if not route_matches(route, method, path):
            continue
        result = route.handler(event, method, path, user_sub, admin_claims)
        if result is None:
            continue
        return result
    return not_found()


def lambda_handler(event, context):
    if isinstance(event, dict):
        early = EARLY_INTERNAL.get(event.get("internal"))
        if early is not None:
            return early(event)
    sqs = _handle_sqs_batch(event)
    if sqs is not None:
        return sqs
    if isinstance(event, dict):
        late = LATE_INTERNAL.get(event.get("internal"))
        if late is not None:
            return late(event)
    return _dispatch_http(event)
