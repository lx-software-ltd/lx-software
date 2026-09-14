"""HTTP API Lambda authorizer for the public API key routes.

Validates the ``x-api-key`` header against hashed key records stored in the
records DynamoDB table (``pk = APIKEY#<scrypt-hex>``, ``sk = META``). Only
the scrypt digest of a key is ever persisted or logged (see
``api_key_hash.py`` for the digest rationale); the plaintext key is shown
once at mint time (see ``scripts/manage-public-api-keys.py``).

Returns the API Gateway v2 "simple" authorizer response. The authorizer
result is cached by API Gateway keyed on ``x-api-key`` + source IP (not
method), so this function never denies based on HTTP method — a POST deny
would poison GETs for 60s. Write methods are enforced in
``board_public_api.write_allowed`` using the forwarded ``write`` flag.
Revocation takes up to the configured TTL (60s).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

from api_key_hash import hash_api_key
from api_key_scopes import (
    LEGACY_READ_SCOPE,
    ip_allowed,
    key_allows_write,
    normalize_scopes,
    parse_cidrs,
    scopes_csv,
    source_ip_from_event,
)

API_KEY_PK_PREFIX = "APIKEY#"
MAX_API_KEY_LEN = 256
LAST_USED_MIN_INTERVAL = timedelta(seconds=60)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_ddb = boto3.resource("dynamodb")
_lambda = None


def _lambda_client() -> Any:
    global _lambda
    if _lambda is None:
        _lambda = boto3.client("lambda")
    return _lambda


def _deny() -> dict[str, Any]:
    return {"isAuthorized": False}


def _log(level: str, **fields: Any) -> None:
    line = json.dumps({k: v for k, v in fields.items() if v is not None}, default=str)
    if level == "warning":
        logger.warning(line)
    else:
        logger.info(line)


def _extract_api_key(event: dict[str, Any]) -> str | None:
    # HTTP API payload 2.0 lower-cases all header names.
    headers = event.get("headers") or {}
    raw = headers.get("x-api-key")
    if not isinstance(raw, str):
        return None
    key = raw.strip()
    if not key or len(key) > MAX_API_KEY_LEN:
        return None
    return key


def _is_expired(expires_at: Any, now: datetime) -> bool:
    """True when ``expiresAt`` holds an ISO date/datetime in the past.

    An unparseable value fails closed (treated as expired) so a corrupted
    record can never grant indefinite access.
    """
    if expires_at in (None, ""):
        return False
    try:
        parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed <= now


def _should_touch_last_used(item: dict[str, Any], now: datetime) -> bool:
    raw = item.get("lastUsedAt")
    if not raw:
        return True
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return now - parsed >= LAST_USED_MIN_INTERVAL


def _touch_last_used(table: Any, item: dict[str, Any], source_ip: str, now: datetime) -> None:
    if not _should_touch_last_used(item, now):
        return
    try:
        table.update_item(
            Key={"pk": item["pk"], "sk": item.get("sk") or "META"},
            UpdateExpression="SET lastUsedAt = :t, lastSourceIp = :ip",
            ExpressionAttributeValues={":t": now.isoformat(), ":ip": source_ip or "unknown"},
        )
    except Exception as exc:
        _log("warning", tag="public_api_key_last_used_failed", error=str(exc)[:200], key_id=item.get("keyId"))


def _enqueue_denied_notify(item: dict[str, Any], reason: str, source_ip: str, request_id: Any) -> None:
    fn_name = (os.environ.get("ADMIN_API_FUNCTION_NAME") or "").strip()
    if not fn_name:
        return
    payload = {
        "internal": "public_api_key_notify",
        "kind": "denied",
        "keyId": item.get("keyId"),
        "label": item.get("label"),
        "scopes": normalize_scopes(item),
        "reason": reason,
        "sourceIp": source_ip,
        "path": "",
        "pathClass": "denied",
        "method": "",
        "requestContext": {"requestId": request_id, "http": {"sourceIp": source_ip}},
    }
    try:
        _lambda_client().invoke(
            FunctionName=fn_name,
            InvocationType="Event",
            Payload=json.dumps(payload).encode("utf-8"),
        )
    except Exception as exc:
        _log("warning", tag="public_api_denied_notify_enqueue_failed", error=str(exc)[:200], key_id=item.get("keyId"))


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    key = _extract_api_key(event)
    request_id = (event.get("requestContext") or {}).get("requestId")
    source_ip = source_ip_from_event(event)
    if key is None:
        _log("info", tag="public_api_key_denied", reason="missing_key", request_id=request_id, source_ip=source_ip)
        return _deny()

    digest = hash_api_key(key)
    digest_prefix = digest[:8]

    table = _ddb.Table(os.environ["RECORDS_TABLE_NAME"])
    try:
        res = table.get_item(Key={"pk": f"{API_KEY_PK_PREFIX}{digest}", "sk": "META"})
    except ClientError as exc:
        _log(
            "warning",
            tag="public_api_key_denied",
            reason="ddb_error",
            error_code=exc.response.get("Error", {}).get("Code"),
            digest_prefix=digest_prefix,
            request_id=request_id,
            source_ip=source_ip,
        )
        return _deny()

    item = res.get("Item")
    if not item:
        _log(
            "info",
            tag="public_api_key_denied",
            reason="unknown_key",
            digest_prefix=digest_prefix,
            request_id=request_id,
            source_ip=source_ip,
        )
        return _deny()

    key_id = item.get("keyId")
    now = datetime.now(timezone.utc)
    if item.get("revoked"):
        _log("info", tag="public_api_key_denied", reason="revoked", key_id=key_id, request_id=request_id, source_ip=source_ip)
        _enqueue_denied_notify(item, "revoked", source_ip, request_id)
        return _deny()

    if _is_expired(item.get("expiresAt"), now):
        _log("info", tag="public_api_key_denied", reason="expired", key_id=key_id, request_id=request_id, source_ip=source_ip)
        _enqueue_denied_notify(item, "expired", source_ip, request_id)
        return _deny()

    scopes = normalize_scopes(item)
    if not scopes:
        _log("info", tag="public_api_key_denied", reason="bad_scope", key_id=key_id, request_id=request_id, source_ip=source_ip)
        return _deny()

    cidrs = parse_cidrs(item.get("allowedCidrs"))
    if not ip_allowed(source_ip, cidrs):
        _log("info", tag="public_api_key_denied", reason="cidr", key_id=key_id, request_id=request_id, source_ip=source_ip)
        _enqueue_denied_notify(item, "cidr", source_ip, request_id)
        return _deny()

    _touch_last_used(table, item, source_ip, now)
    write_flag = "1" if key_allows_write(item) else "0"
    _log(
        "info",
        tag="public_api_key_allowed",
        key_id=key_id,
        request_id=request_id,
        source_ip=source_ip,
        write=write_flag,
    )
    return {
        "isAuthorized": True,
        "context": {
            "keyId": str(key_id or ""),
            "label": str(item.get("label") or ""),
            "scope": LEGACY_READ_SCOPE,
            "scopes": scopes_csv(scopes),
            "write": write_flag,
        },
    }
