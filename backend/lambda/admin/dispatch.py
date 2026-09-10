"""Admin API: dispatch."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs

from botocore.exceptions import ClientError

import bank_sync as bank_sync_mod
import board_cache as board_cache_mod
import board_chat as board_chat_mod
import board_meeting as board_meeting_mod
import board_receivables as board_receivables_mod
import board_review as board_review_mod
import board_staff as board_staff_mod
import parse_jobs as parse_jobs_mod
import runtime
from board_routes import handle_board_route
from board_store import BOARD_PK_PREFIX
from contract_constants import (
    EXPENSE_RECORD_CATEGORIES,
    FINANCE_HOUSE_KEYS,
    FINANCE_STATEMENT_BOOK_KEYS,
    FINANCE_STATEMENT_OWNER_KEYS,
    INCOME_RECORD_CATEGORIES,
)
from assets import (
    _asset_delete_response,
    _asset_download_presigned_response,
    _is_allowed_upload_content_type,
)
from ddb_convert import _from_ddb, _from_ddb_nested, _to_ddb, _to_ddb_nested
from finance_store import (
    _allocated_expense_ids_for_allocations,
    _build_allocation_records_for_response,
    _finance_ddb_key,
    _finance_owner_ddb_key,
    _finance_sheet_ddb_key,
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
    _enrich_scan_items_asset_meta,
)
from http_common import (
    _api_key_auth_context,
    _audit,
    _claims,
    _decode_cursor,
    _encode_cursor,
    _json_response,
    _log_event,
    _parse_json_body,
    _require_admin,
    _request_id,
    _route,
    _utc_iso_z,
)
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
from runtime import RECORD_PK_PREFIX, logger


# Read-only mirrors of the admin GET endpoints, served under /public/* and
# authenticated by the API key Lambda authorizer instead of Cognito. Assets
# and parse-job endpoints are deliberately excluded (they presign S3 access
# to bank statements / are owner-scoped).
PUBLIC_READ_PATHS = frozenset(
    {
        "/public/finance",
        "/public/finance/quotes",
        "/public/records",
        "/public/fx/v2/rates",
    }
)

STATEMENT_BOOK_DISPLAY_LABEL = {
    "siuTinDei": "Siu Tin Dei",
    "lxSoftware": "LX Software",
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
    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
    # Executive Board rows (strategy discussions, chats) never leave via the
    # generic record browser or its public API-key mirror.
    kwargs: dict[str, Any] = {
        "Limit": 50,
        "FilterExpression": "NOT begins_with(pk, :board)",
        "ExpressionAttributeValues": {":board": BOARD_PK_PREFIX},
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
    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
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


def _handle_public_read(
    event: dict[str, Any], method: str, path: str
) -> dict[str, Any]:
    """Serve /public/* routes for API key principals (read-only, GET only).

    API Gateway already enforced the key via the Lambda authorizer; the
    context check here is defense in depth against direct Lambda invocation
    or a route being wired to the wrong authorizer.
    """
    key_ctx = _api_key_auth_context(event)
    key_id = key_ctx.get("keyId")
    if not key_id or key_ctx.get("scope") != "read":
        _log_event(
            "warning",
            tag="public_api_denied",
            reason="missing_key_context",
            method=method,
            path=path,
            request_id=_request_id(event),
        )
        return _json_response(401, {"message": "Unauthorized"})

    if method != "GET" or path not in PUBLIC_READ_PATHS:
        _log_event(
            "warning",
            tag="public_api_denied",
            reason="not_allowlisted",
            key_id=key_id,
            method=method,
            path=path,
            request_id=_request_id(event),
        )
        return _json_response(404, {"message": "Not found"})

    _log_event(
        "info",
        tag="public_api_access",
        key_id=key_id,
        path=path,
        request_id=_request_id(event),
    )

    if path == "/public/finance":
        return _finance_get_response()
    if path == "/public/finance/quotes":
        return _proxy_finance_quotes(
            event.get("queryStringParameters"),
            _request_id(event),
        )
    if path == "/public/fx/v2/rates":
        return _proxy_fx_v2_rates(
            event.get("queryStringParameters"),
            _request_id(event),
        )
    return _records_get_response(event)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    if isinstance(event, dict) and event.get("internal") == "parse_statement_async":
        parse_jobs_mod._handle_parse_statement_async_worker(event)
        return {}

    if isinstance(event, dict) and event.get("internal") == "bank_sync":
        bank_sync_mod.handle_bank_sync_worker(event)
        return {}

    if isinstance(event, dict) and event.get("internal") == "board_chat":
        board_chat_mod.run_chat_worker(event)
        return {}

    if isinstance(event, dict) and event.get("internal") == "board_meeting":
        if event.get("meetingId"):
            board_meeting_mod.run_meeting_phase(event)
        else:
            board_meeting_mod.handle_schedule_trigger(event)
        return {}

    if isinstance(event, dict) and event.get("internal") == "board_cache_refresh":
        board_cache_mod.handle_schedule_trigger(event)
        return {}

    if isinstance(event, dict) and event.get("internal") == "board_staff_step":
        board_staff_mod.run_step(event)
        return {}

    if isinstance(event, dict) and event.get("internal") == "board_staff_review":
        board_staff_mod.run_review(event)
        return {}

    if isinstance(event, dict) and event.get("internal") == "board_staff_tick":
        return board_staff_mod.handle_tick(event)

    if isinstance(event, dict) and event.get("internal") == "board_review_compile":
        return board_review_mod.handle_compile(event)

    if isinstance(event, dict) and event.get("internal") == "board_review_send":
        return board_review_mod.handle_send(event)

    if isinstance(event, dict) and event.get("internal") == "board_receivables_mirror":
        board_receivables_mod.handle_mirror_trigger(event)
        return {}

    if isinstance(event, dict) and event.get("internal") == "board_dunning":
        board_receivables_mod.handle_dunning_trigger(event)
        return {}

    method, path = _route(event)

    if path in {"/webhooks/meta", "/webhooks/meta/siutindei"}:
        import board_meta as board_meta_mod

        return board_meta_mod.handle_http(event, method)

    if method == "GET" and path == "/health":
        return _json_response(200, {"status": "ok"})

    if path == "/public" or path.startswith("/public/"):
        return _handle_public_read(event, method, path)

    admin_claims = _require_admin(event)
    if admin_claims is None:
        claims = _claims(event)
        if not claims:
            logger.info(
                json.dumps(
                    {
                        "tag": "admin_auth_denied",
                        "reason": "missing_claims",
                        "method": method,
                        "path": path,
                        "request_id": _request_id(event),
                    }
                )
            )
            return _json_response(401, {"message": "Unauthorized"})
        logger.info(
            json.dumps(
                {
                    "tag": "admin_auth_denied",
                    "reason": "not_in_admin_group",
                    "method": method,
                    "path": path,
                    "request_id": _request_id(event),
                    "sub": claims.get("sub"),
                    "email": claims.get("email"),
                    "cognito_username": claims.get("cognito:username"),
                    "cognito_groups": claims.get("cognito:groups"),
                    "token_use": claims.get("token_use"),
                    "iss": claims.get("iss"),
                    "aud": claims.get("aud"),
                }
            )
        )
        return _json_response(403, {"message": "Forbidden: admin group required"})

    user_sub = admin_claims.get("sub")

    if method == "GET" and path == "/me":
        return _json_response(
            200,
            {
                "sub": admin_claims.get("sub"),
                "email": admin_claims.get("email"),
                "cognito_username": admin_claims.get("cognito:username"),
            },
        )

    if method == "GET" and path == "/fx/v2/rates":
        return _proxy_fx_v2_rates(
            event.get("queryStringParameters"),
            _request_id(event),
        )

    if method == "GET" and path == "/finance/quotes":
        return _proxy_finance_quotes(
            event.get("queryStringParameters"),
            _request_id(event),
        )

    if method == "GET" and path == "/banking":
        return bank_sync_mod.handle_banking_get(event)

    if method == "GET" and path == "/banking/banks":
        return bank_sync_mod.handle_banking_banks(event)

    if method == "POST" and path == "/banking/auth":
        return bank_sync_mod.handle_banking_auth_start(event, user_sub)

    if method == "POST" and path == "/banking/sessions":
        return bank_sync_mod.handle_banking_auth_complete(event, user_sub)

    if method == "DELETE" and path.startswith("/banking/sessions/"):
        session_id = path[len("/banking/sessions/"):]
        return bank_sync_mod.handle_banking_session_delete(
            event, user_sub, session_id
        )

    if method == "PUT" and path == "/banking/mappings":
        return bank_sync_mod.handle_banking_mappings_put(event, user_sub)

    if method == "POST" and path == "/banking/sync":
        return bank_sync_mod.handle_banking_sync_post(event, user_sub)

    if method == "POST" and path == "/assets/upload-url":
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

    if method == "POST" and path == "/assets/confirm":
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
        table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
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

    if method == "GET" and path == "/assets/download-url":
        qs = event.get("rawQueryString") or ""
        key_param = parse_qs(qs).get("key", [""])[0]
        return _asset_download_presigned_response(event, user_sub, key_param)

    if method == "POST" and path == "/assets/download-url":
        body = _parse_json_body(event)
        return _asset_download_presigned_response(event, user_sub, body.get("key"))

    if method == "POST" and path == "/assets/delete":
        body = _parse_json_body(event)
        return _asset_delete_response(event, user_sub, body.get("key"))

    if method == "GET" and path == "/records":
        return _records_get_response(event)

    if method == "POST" and path == "/records":
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
        table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
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

    if method == "PUT" and path == "/records":
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
        table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
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

    if method == "GET" and path == "/finance":
        return _finance_get_response()

    if method == "PUT" and path in ("/finance/income", "/finance/expenses"):
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
        table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
        if sheet_slug == "expenses":
            existing_perc = _load_existing_expense_income_allocation_percentages(table)
            if isinstance(body.get("expenseIncomeAllocationPercents"), dict):
                patched_perc = _sanitize_expense_income_allocation_percentages(
                    body["expenseIncomeAllocationPercents"]
                )
            else:
                patched_perc = existing_perc
            doc = {
                "records": normalized,
                "expenseIncomeAllocationPercents": patched_perc,
            }
        else:
            doc = {"records": normalized}
        ddb_item = {**_finance_sheet_ddb_key(sheet_slug), **_to_ddb_nested(doc)}
        table.put_item(Item=ddb_item)
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

    if method == "PUT" and path == "/finance/investments":
        body = _parse_json_body(event)
        try:
            normalized = _normalize_investment_sheet_payload(body)
        except ValueError as exc:
            return _json_response(400, {"message": str(exc)})
        table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
        existing = _load_investment_records(table)
        merged = _merge_investment_last_updated(normalized, existing)
        doc = {"records": merged}
        ddb_item = {**_finance_sheet_ddb_key("investments"), **_to_ddb_nested(doc)}
        table.put_item(Item=ddb_item)
        _audit(user_sub, "FINANCE_PUT", "investments", event)
        return _json_response(200, {"investmentRecords": merged})

    if method == "PUT" and path == "/finance/savings":
        body = _parse_json_body(event)
        try:
            normalized = _normalize_savings_sheet_payload(body)
        except ValueError as exc:
            return _json_response(400, {"message": str(exc)})
        table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
        doc = {"records": normalized}
        ddb_item = {**_finance_sheet_ddb_key("savings"), **_to_ddb_nested(doc)}
        table.put_item(Item=ddb_item)
        _audit(user_sub, "FINANCE_PUT", "savings", event)
        return _json_response(200, {"savingsRecords": normalized})

    if method == "PUT" and path == "/finance/pension":
        body = _parse_json_body(event)
        try:
            normalized = _normalize_pension_sheet_payload(body)
        except ValueError as exc:
            return _json_response(400, {"message": str(exc)})
        table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
        existing = _load_pension_records(table)
        merged = _merge_pension_last_updated(normalized, existing)
        doc = {"records": merged}
        ddb_item = {**_finance_sheet_ddb_key("pension"), **_to_ddb_nested(doc)}
        table.put_item(Item=ddb_item)
        _audit(user_sub, "FINANCE_PUT", "pension", event)
        return _json_response(200, {"pensionRecords": merged})

    if method == "PUT" and path == "/finance/accounts":
        body = _parse_json_body(event)
        try:
            normalized = _normalize_accounts_sheet_payload(body)
        except ValueError as exc:
            return _json_response(400, {"message": str(exc)})
        table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
        existing = _load_accounts_records(table)
        merged = _merge_accounts_last_updated(normalized, existing)
        doc = {"records": merged}
        ddb_item = {**_finance_sheet_ddb_key("accounts"), **_to_ddb_nested(doc)}
        table.put_item(Item=ddb_item)
        _audit(user_sub, "FINANCE_PUT", "accounts", event)
        return _json_response(200, {"accountRecords": merged})

    if method == "PUT" and path == "/finance/liabilities":
        body = _parse_json_body(event)
        try:
            normalized = _normalize_liabilities_sheet_payload(body)
        except ValueError as exc:
            return _json_response(400, {"message": str(exc)})
        table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
        existing = _load_liabilities_records(table)
        merged = _merge_liabilities_last_updated(normalized, existing)
        doc = {"records": merged}
        ddb_item = {**_finance_sheet_ddb_key("liabilities"), **_to_ddb_nested(doc)}
        table.put_item(Item=ddb_item)
        _audit(user_sub, "FINANCE_PUT", "liabilities", event)
        return _json_response(200, {"liabilityRecords": merged})

    if method == "PUT" and path == "/finance/allocations":
        body = _parse_json_body(event)
        table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
        allocated_ids = _allocated_expense_ids_for_allocations(table)
        try:
            normalized = _normalize_allocations_sheet_payload(body, allocated_ids)
        except ValueError as exc:
            return _json_response(400, {"message": str(exc)})
        existing = _load_allocation_stored_records(table)
        merged_stored = _merge_allocation_stored_last_updated(normalized, existing)
        doc = {"records": merged_stored}
        ddb_item = {**_finance_sheet_ddb_key("allocations"), **_to_ddb_nested(doc)}
        table.put_item(Item=ddb_item)
        _audit(user_sub, "FINANCE_PUT", "allocations", event)
        exp_rows, exp_pct = _load_finance_expenses_ledger_with_allocation(table)
        inc_rows = _load_finance_sheet(table, "income", INCOME_RECORD_CATEGORIES)
        allocation_response = _build_allocation_records_for_response(
            exp_rows, merged_stored, inc_rows, exp_pct
        )
        return _json_response(200, {"allocationRecords": allocation_response})

    board_response = handle_board_route(event, method, path, user_sub)
    if board_response is not None:
        return board_response

    book_match = _match_statement_book_path(path)
    if book_match:
        book_key, slug = book_match
        book_label = STATEMENT_BOOK_DISPLAY_LABEL.get(book_key, book_key)

        if method == "GET" and path == f"/{slug}":
            table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
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
            table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
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
                return _json_response(404, {"message": "Not found"})
            if not user_sub:
                return _json_response(400, {"message": "Missing sub claim"})
            table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
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
            table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
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

    if method == "PUT" and path.startswith("/finance/") and not path.endswith(
        "/parse-statement"
    ):
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
        table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
        ddb_item = {**_finance_ddb_key(house), **_to_ddb_nested(normalized)}
        table.put_item(Item=ddb_item)
        _audit(user_sub, "FINANCE_PUT", house, event)
        return _json_response(200, {"data": normalized})

    if method == "GET" and "/parse-statement/jobs/" in path:
        house_j, job_id = _path_finance_parse_job(event, path)
        if not house_j or house_j not in FINANCE_HOUSE_KEYS or not job_id:
            return _json_response(404, {"message": "Not found"})
        if not user_sub:
            return _json_response(400, {"message": "Missing sub claim"})
        table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
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

    if (
        method == "POST"
        and path.startswith("/finance/")
        and path.endswith("/parse-statement")
        and "/parse-statement/jobs/" not in path
    ):
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
        table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
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


    return _json_response(404, {"message": "Not found"})

