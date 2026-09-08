"""Admin API: parse statement."""

from __future__ import annotations

import os
import uuid
from typing import Any

from botocore.exceptions import ClientError

import runtime
import openrouter_usage
from admin_runtime import _get_secretsmanager_client
from contract_constants import (
    DEFAULT_FINANCE_CURRENCY,
    FINANCE_LINE_TYPES,
    MAX_SOURCE_ASSET_KEYS_PER_LINE,
)
from ddb_convert import _to_ddb_nested
from finance_store import (
    _finance_owner_ddb_key,
    _line_source_asset_keys_raw,
    _load_finance_owner,
    _normalize_finance_payload,
    _persist_asset_meta_after_parse,
)
from http_common import _audit, _log_event
from openrouter_client import SERVICE_STATEMENT_PARSER, add_usage


class _ParseStatementError(Exception):
    """User-facing error for the /finance/{house}/parse-statement endpoint."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _path_finance_house_for_parse(event: dict[str, Any], path: str) -> str | None:
    """Pull the {house} segment out of /finance/{house}/parse-statement."""
    pp = (event.get("pathParameters") or {}).get("house")
    if isinstance(pp, str) and pp.strip():
        return pp.strip().lower()
    parts = [p for p in path.split("/") if p]
    if len(parts) == 3 and parts[0] == "finance" and parts[2] == "parse-statement":
        return parts[1].lower()
    return None


def _resolve_parse_line_type_filter(
    *,
    mortgage_only: bool,
    line_type_only: str | None,
) -> str | None:
    """Return the line type to keep, or None to keep every extracted row."""
    if mortgage_only:
        return "mortgage"
    if isinstance(line_type_only, str) and line_type_only.strip():
        t = line_type_only.strip().lower()
        if t in FINANCE_LINE_TYPES:
            return t
    return None


def _statement_basename_already_imported(
    house_data: dict[str, Any], basename: str
) -> bool:
    """True if any finance line references an asset with this exact filename."""
    for ln in house_data.get("lines") or []:
        if not isinstance(ln, dict):
            continue
        for key in _line_source_asset_keys_raw(ln):
            if os.path.basename(key) == basename:
                return True
    return False


def execute_parse_statement(
    *,
    house: str,
    s3_keys: list[str],
    user_sub: str | None,
    request_id: str,
    event: dict[str, Any],
    mortgage_only: bool = False,
    line_type_only: str | None = None,
) -> dict[str, Any]:
    """Run OpenRouter on one or more assets and append parsed lines.

    Each new line gets ``sourceAssetKeys`` set to the full ordered list of
    ``s3_keys`` (same idea as attaching every PDF from one import to every
    extracted line in the admin UI). Used by the HTTP API and inbound-email.

    When ``mortgage_only`` is true, only parsed lines with ``type`` ``mortgage``
    are appended; all other extracted rows are discarded. ``line_type_only``
    does the same for any finance line type (used by Siu Tin Dei tabs).

    Raises ``_ParseStatementError`` on user-facing failures.

    Returns a dict with ``data``, ``addedLines``, ``sourceAssetKeys``, and
    legacy ``sourceAssetKey`` (first key).
    """
    keys_ordered: list[str] = []
    seen: set[str] = set()
    for k in s3_keys:
        if not isinstance(k, str) or not k.strip():
            continue
        kk = k.strip()
        if kk not in seen:
            seen.add(kk)
            keys_ordered.append(kk)
    if not keys_ordered:
        raise _ParseStatementError(400, "At least one S3 key is required")
    if len(keys_ordered) > MAX_SOURCE_ASSET_KEYS_PER_LINE:
        raise _ParseStatementError(
            400,
            f"At most {MAX_SOURCE_ASSET_KEYS_PER_LINE} statement files per import",
        )

    bucket = os.environ["ASSETS_BUCKET_NAME"]
    _log_event(
        "info",
        tag="parse_statement_start",
        sub=user_sub,
        house=house,
        key=",".join(keys_ordered)[:512],
        request_id=request_id,
        mortgage_only=mortgage_only,
        line_type_only=line_type_only,
    )

    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
    house_data = _load_finance_owner(table, house)

    file_meta: list[tuple[str, str, dict[str, Any]]] = []
    for s3_key in keys_ordered:
        try:
            head = runtime._s3.head_object(Bucket=bucket, Key=s3_key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                _log_event(
                    "warning",
                    tag="parse_statement_not_in_bucket",
                    sub=user_sub,
                    house=house,
                    key=s3_key[:512],
                    s3_error_code=code,
                    request_id=request_id,
                )
                raise _ParseStatementError(400, "Object not found in bucket") from exc
            raise
        file_name = os.path.basename(s3_key)
        if _statement_basename_already_imported(house_data, file_name):
            _log_event(
                "info",
                tag="parse_statement_duplicate_basename",
                sub=user_sub,
                house=house,
                basename=file_name[:256],
                request_id=request_id,
            )
            raise _ParseStatementError(
                409,
                f"A statement file named {file_name!r} was already imported for this house. "
                "Remove its imported lines or rename the file, then try again.",
            )
        file_meta.append((s3_key, file_name, head))

    default_currency = house_data.get("defaultCurrency", DEFAULT_FINANCE_CURRENCY)

    # Lazy-import the parser so unit tests can stub urllib without paying
    # the import cost on unrelated routes.
    from openrouter_statement_parser import parse_statement_from_asset

    all_parsed_raw_lines: list[dict[str, Any]] = []
    parse_usage = add_usage(None, None)
    parse_calls = 0
    for s3_key, file_name, head in file_meta:
        content_type = head.get("ContentType") or ""
        object_size = int(head.get("ContentLength") or 0)
        _log_event(
            "info",
            tag="parse_statement_object_loaded",
            sub=user_sub,
            house=house,
            key=s3_key[:512],
            object_content_type=content_type[:128],
            object_size_bytes=object_size,
            default_currency=default_currency,
            request_id=request_id,
        )
        try:
            parsed = parse_statement_from_asset(
                s3_client=runtime._s3,
                secrets_client=_get_secretsmanager_client(),
                bucket=bucket,
                s3_key=s3_key,
                file_name=file_name,
                content_type=content_type,
                default_currency=default_currency,
                owner=house,
            )
            parse_usage = add_usage(parse_usage, parsed.get("usage"))
            parse_calls += 1
        except RuntimeError as exc:
            _log_event(
                "warning",
                tag="parse_statement_failed",
                sub=user_sub,
                house=house,
                key=s3_key[:512],
                error=str(exc)[:500],
                request_id=request_id,
            )
            raise _ParseStatementError(502, f"Statement parser failed: {exc}") from exc
        for raw_line in parsed.get("lines") or []:
            if isinstance(raw_line, dict):
                all_parsed_raw_lines.append(raw_line)

    type_filter = _resolve_parse_line_type_filter(
        mortgage_only=mortgage_only,
        line_type_only=line_type_only,
    )
    if type_filter:
        all_parsed_raw_lines = [
            ln
            for ln in all_parsed_raw_lines
            if isinstance(ln, dict)
            and str(ln.get("type", "")).strip().lower() == type_filter
        ]

    new_lines: list[dict[str, Any]] = []
    for raw_line in all_parsed_raw_lines:
        nl = {
            **raw_line,
            "id": uuid.uuid4().hex,
            "sourceAssetKeys": list(keys_ordered),
        }
        nl.pop("sourceAssetKey", None)
        new_lines.append(nl)
    _log_event(
        "info",
        tag="parse_statement_extracted",
        sub=user_sub,
        house=house,
        key=",".join(keys_ordered)[:512],
        added_lines=len(new_lines),
        existing_lines=len(house_data.get("lines", []) or []),
        cost_usd=(parse_usage or {}).get("cost"),
        request_id=request_id,
    )
    try:
        if parse_calls:
            openrouter_usage.add_usage_day(
                table,
                service=SERVICE_STATEMENT_PARSER,
                owner=house,
                usage=parse_usage,
                calls=parse_calls,
            )
    except Exception as exc:  # pragma: no cover - accounting must not break import
        _log_event(
            "warning",
            tag="openrouter_usage_record_failed",
            house=house,
            error=str(exc)[:200],
            request_id=request_id,
        )

    merged_payload = {
        "defaultCurrency": house_data.get("defaultCurrency", DEFAULT_FINANCE_CURRENCY),
        "float": house_data.get(
            "float",
            {"amount": 0, "currency": DEFAULT_FINANCE_CURRENCY},
        ),
        "lines": list(house_data.get("lines", [])) + new_lines,
    }

    try:
        normalized = _normalize_finance_payload(merged_payload)
    except ValueError as exc:
        raise _ParseStatementError(
            500, f"Parsed lines failed validation: {exc}"
        ) from exc

    ddb_item = {**_finance_owner_ddb_key(house), **_to_ddb_nested(normalized)}
    table.put_item(Item=ddb_item)
    for s3_key, file_name, head in file_meta:
        _persist_asset_meta_after_parse(
            table=table,
            s3_key=s3_key,
            house=house,
            head=head,
            file_name=file_name,
            request_id=request_id,
            owner_sub=user_sub,
        )
    audit_event = {
        **event,
        "requestContext": {
            **event.get("requestContext", {}),
            "requestId": request_id,
            "http": {
                **(event.get("requestContext") or {}).get("http", {}),
                "requestId": request_id,
            },
        },
    }
    audit_target = f"{house}|{','.join(keys_ordered)}"[:1024]
    _audit(user_sub, "FINANCE_PARSE_STATEMENT", audit_target, audit_event)

    return {
        "data": normalized,
        "addedLines": len(new_lines),
        "sourceAssetKeys": list(keys_ordered),
        "sourceAssetKey": keys_ordered[0],
        "usage": {**parse_usage, "calls": parse_calls},
    }
