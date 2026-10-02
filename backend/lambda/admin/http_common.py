"""Admin API: http common."""

from __future__ import annotations

import base64
import binascii
import json
import os
import time
from datetime import datetime
from typing import Any

import runtime
from botocore.exceptions import ClientError
from runtime import ADMIN_GROUP, logger


def _json_response(
    status_code: int, payload: dict[str, Any] | list[Any] | str
) -> dict[str, Any]:
    body = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": body,
    }


def not_found() -> dict[str, Any]:
    return _json_response(404, {"message": "Not found"})


def method_not_allowed() -> dict[str, Any]:
    return _json_response(405, {"message": "Method not allowed"})


def _parse_json_body(event: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _claims(event: dict[str, Any]) -> dict[str, Any]:
    return (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )


def _public_authorizer_context(event: dict[str, Any]) -> dict[str, Any]:
    """Opaque context from the public API Lambda authorizer (simple response).

    API Gateway HTTP API places a Lambda authorizer's ``context`` under
    ``requestContext.authorizer.lambda``. That map holds the key id, scopes and
    write flag — never the raw key. Returns ``{}`` when the request was not
    authorized by that authorizer (e.g. Cognito JWT routes).

    The identifier avoids ``api_key`` so CodeQL does not treat the return value
    as credential material (``py/weak-sensitive-data-hashing``).
    """
    ctx = event.get("requestContext", {}).get("authorizer", {}).get("lambda")
    return ctx if isinstance(ctx, dict) else {}


def _groups_include_admin(claims: dict[str, Any]) -> bool:
    raw = claims.get("cognito:groups")
    if raw is None:
        return False
    if isinstance(raw, list):
        return ADMIN_GROUP in raw
    # API Gateway HTTP API JWT authorizer flattens array claims using Java-style
    # toString(), e.g. ["admin"] -> "[admin]" and ["viewer","admin"] -> "[viewer, admin]".
    # Strip the surrounding brackets before splitting on commas so we accept
    # both the bracketed form (HttpApi authorizer) and a plain comma-separated
    # string (REST API or local-decoded claims).
    s = str(raw).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return ADMIN_GROUP in parts


def _require_admin(event: dict[str, Any]) -> dict[str, Any] | None:
    claims = _claims(event)
    if not _groups_include_admin(claims):
        return None
    return claims


def _route(event: dict[str, Any]) -> tuple[str, str]:
    http = event.get("requestContext", {}).get("http", {})
    return http.get("method", ""), http.get("path", "")


def _request_id(event: dict[str, Any]) -> str:
    return (
        event.get("requestContext", {})
        .get("requestId", "")
        or event.get("requestContext", {})
        .get("http", {})
        .get("requestId", "")
        or "unknown"
    )


def _audit(user_sub: str | None, action: str, target: str, event: dict[str, Any]) -> None:
    if not user_sub:
        return
    try:
        table = runtime._ddb.Table(os.environ["AUDIT_LOG_TABLE_NAME"])
        ts = int(time.time() * 1000)
        table.put_item(
            Item={
                "pk": f"USER#{user_sub}",
                "sk": f"{ts}#{action}",
                "target": target,
                "requestId": _request_id(event),
            }
        )
    except ClientError as exc:
        _log_event(
            "warning",
            tag="audit_write_failed",
            action=action,
            error=exc.response.get("Error", {}).get("Code", "ClientError"),
        )


def _log_event(level: str, **fields: Any) -> None:
    """Emit a single-line JSON log row.

    All non-`tag` fields are PII-safe scalars (sub, content type, S3 key,
    sizes, error codes, request id). Used by the asset upload + statement
    parse endpoints so a future "the upload silently failed" report can be
    diagnosed from CloudWatch alone, without needing the user's browser.
    """
    payload = {k: v for k, v in fields.items() if v is not None}
    line = json.dumps(payload, default=str)
    if level == "warning":
        logger.warning(line)
    elif level == "error":
        logger.error(line)
    else:
        logger.info(line)


def _decode_cursor(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        pad = "=" * ((4 - len(raw) % 4) % 4)
        blob = base64.urlsafe_b64decode(raw + pad)
        return json.loads(blob.decode("utf-8"))
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _utc_iso_z(dt: datetime) -> str:
    """Format an aware or naive datetime as UTC with millisecond precision."""
    from timeutil import format_iso_millis

    return format_iso_millis(dt)


def utc_now() -> datetime:
    from timeutil import utc_now as _utc_now

    return _utc_now()


def now_iso() -> str:
    from timeutil import now_iso as _now_iso

    return _now_iso()


def parse_iso(value: Any) -> datetime | None:
    from timeutil import parse_iso as _parse_iso

    return _parse_iso(value)


def parse_iso_strict(value: str) -> datetime:
    from timeutil import parse_iso_strict as _parse_iso_strict

    return _parse_iso_strict(value)


def _encode_cursor(key: dict[str, Any]) -> str:
    raw = json.dumps(key, separators=(",", ":"), default=str).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


