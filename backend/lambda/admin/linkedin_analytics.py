"""LinkedIn Community Management connection for profile post impressions.

The analytics app cannot share a product list with the posting app, so this
connection has its own token. It asks only for member post statistics and the
basic profile. Tokens stay in the records table and are never returned.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import board_store
import linkedin_api
import linkedin_metrics
import linkedin_store
from http_common import _audit, _json_response, _parse_json_body
from linkedin_api import LinkedInApiError
from linkedin_store import HKT, LinkedInError

ANALYTICS_SCOPES = "r_member_postAnalytics r_basicprofile"
CALLS_PER_DAY = 80
_SK = "ANALYTICS"
_credentials_cache: dict[str, Any] = {"at": 0.0, "status": ""}


def reset_credentials_cache_for_tests() -> None:
    _credentials_cache["at"] = 0.0
    _credentials_cache["status"] = ""


def load_credentials() -> tuple[str, str]:
    """Return ``(client_id, client_secret)`` for the analytics app."""
    secret_id = (os.environ.get(linkedin_api.SECRET_ID_ENV) or "").strip()
    if not secret_id:
        raise LinkedInApiError("LinkedIn analytics credentials are not configured.", counts_attempt=False)
    from admin_runtime import _get_secretsmanager_client
    from secret_store import read_secret_raw

    raw = read_secret_raw(_get_secretsmanager_client(), secret_id, what="LinkedIn analytics app")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LinkedInApiError("LinkedIn analytics secret is not JSON.", counts_attempt=False) from exc
    if not isinstance(parsed, dict):
        raise LinkedInApiError("LinkedIn analytics secret is not JSON.", counts_attempt=False)
    client_id = str(parsed.get("analyticsClientId") or "").strip()
    client_secret = str(parsed.get("analyticsClientSecret") or "").strip()
    if not client_id or client_id == "replace-me" or not client_secret:
        raise LinkedInApiError("LinkedIn analytics credentials are not configured.", counts_attempt=False)
    return client_id, client_secret


def credentials_status() -> str:
    """``ready``, ``missing``, or ``unreadable``. Cached for a minute."""
    now = time.monotonic()
    if _credentials_cache["status"] and now - float(_credentials_cache["at"]) < 60:
        return str(_credentials_cache["status"])
    status = "ready"
    try:
        load_credentials()
    except LinkedInApiError as exc:
        status = "missing" if "not configured" in str(exc) else "unreadable"
    except Exception:  # noqa: BLE001 — overview must load when Secrets Manager fails
        status = "unreadable"
    _credentials_cache["at"] = now
    _credentials_cache["status"] = status
    return status


def load_connection(table: Any) -> dict[str, Any]:
    stored = linkedin_store._load_sk(table, _SK)
    return stored if stored.get("accessToken") else {}


def save_connection(table: Any, doc: dict[str, Any]) -> None:
    linkedin_store._put(
        table,
        {
            **linkedin_store._state_key(_SK),
            **{key: value for key, value in doc.items() if key not in {"pk", "sk"}},
            "updatedAt": board_store.now_iso(),
        },
    )


def clear_connection(table: Any) -> None:
    linkedin_store._put(table, {**linkedin_store._state_key(_SK), "updatedAt": board_store.now_iso()})


def public_status(doc: dict[str, Any]) -> dict[str, Any]:
    connected = bool(doc.get("accessToken"))
    status = "ready" if connected else credentials_status()
    return {
        "status": "connected" if connected else "not_connected",
        "memberName": str(doc.get("memberName") or "") if connected else "",
        "tokenExpiresAt": str(doc.get("tokenExpiresAt") or "") if connected else "",
        "appConfigured": status == "ready",
        "appStatus": status,
    }


def owns_state(table: Any, state: str) -> bool:
    row = linkedin_store._get(table, f"LINKEDIN#oauth#{state}")
    return bool(row and row.get("analyticsApp"))


def authorize_url(*, client_id: str, redirect: str, state: str) -> str:
    from urllib.parse import urlencode

    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect,
            "state": state,
            "scope": ANALYTICS_SCOPES,
        }
    )
    return f"{linkedin_api.AUTH_URL}?{query}"


def _conflict(exc: BaseException) -> bool:
    """True when a conditional write lost a race. Test stubs replace ``ClientError``."""
    response = getattr(exc, "response", None)
    error = response.get("Error") if isinstance(response, dict) else None
    return isinstance(error, dict) and error.get("Code") == "ConditionalCheckFailedException"


def _put_if(table: Any, doc: dict[str, Any], condition: str, values: dict[str, Any]) -> None:
    """Write the analytics row only when ``condition`` still matches the stored one."""
    from ddb_convert import _to_ddb_nested

    item = {
        **linkedin_store._state_key(_SK),
        **{key: value for key, value in doc.items() if key not in {"pk", "sk"}},
        "updatedAt": board_store.now_iso(),
    }
    table.put_item(
        Item=_to_ddb_nested(item),
        ConditionExpression=condition,
        ExpressionAttributeValues=values,
    )


def take_call(table: Any, connection: dict[str, Any]) -> bool:
    """Count one analytics call. The write touches only the counter on the live row."""
    today = datetime.now(timezone.utc).date().isoformat()
    for _attempt in range(4):
        current = load_connection(table)
        token = str(current.get("accessToken") or "")
        if not token:
            return False
        day = str(current.get("callsOn") or "")
        used = int(current.get("calls") or 0)
        if day != today:
            try:
                _put_if(
                    table,
                    {**current, "callsOn": today, "calls": 1},
                    "attribute_exists(accessToken) AND accessToken = :token AND callsOn <> :day",
                    {":token": token, ":day": today},
                )
            except Exception as exc:  # noqa: BLE001 — stubbed ClientError is not one class
                if not _conflict(exc):
                    raise
                continue
            connection["accessToken"] = token
            connection["callsOn"] = today
            connection["calls"] = 1
            return True
        if used >= CALLS_PER_DAY:
            connection["accessToken"] = token
            connection["callsOn"] = day
            connection["calls"] = used
            return False
        try:
            _put_if(
                table,
                {**current, "calls": used + 1},
                "attribute_exists(accessToken) AND accessToken = :token AND callsOn = :day AND calls = :prev",
                {":token": token, ":day": today, ":prev": used},
            )
        except Exception as exc:  # noqa: BLE001 — stubbed ClientError is not one class
            if not _conflict(exc):
                raise
            continue
        connection["accessToken"] = token
        connection["callsOn"] = today
        connection["calls"] = used + 1
        return True
    return False


def _remember_token(table: Any, connection: dict[str, Any], previous: str, token: dict[str, Any]) -> str:
    access = str(token.get("access_token") or "")
    if not access:
        raise LinkedInApiError("Reconnect LinkedIn analytics. The access token expired.", counts_attempt=False)
    expiry = _token_expiry(token)
    refresh = str(token.get("refresh_token") or connection.get("refreshToken") or "")
    for _attempt in range(4):
        current = load_connection(table)
        if str(current.get("accessToken") or "") != previous:
            stored = linkedin_store._parse_slot(str(current.get("tokenExpiresAt") or ""))
            if current and stored is not None and stored > datetime.now(HKT) + timedelta(minutes=2):
                connection.update(current)
                return str(current["accessToken"])
            raise LinkedInApiError("Reconnect LinkedIn analytics. The access token expired.", counts_attempt=False)
        try:
            _put_if(
                table,
                {**current, "accessToken": access, "refreshToken": refresh, "tokenExpiresAt": expiry},
                "attribute_exists(accessToken) AND accessToken = :token",
                {":token": previous},
            )
        except Exception as exc:  # noqa: BLE001 — stubbed ClientError is not one class
            if not _conflict(exc):
                raise
            continue
        connection["accessToken"] = access
        connection["refreshToken"] = refresh
        connection["tokenExpiresAt"] = expiry
        return access
    raise LinkedInApiError("Reconnect LinkedIn analytics. The access token expired.", counts_attempt=False)


def access_token(table: Any, connection: dict[str, Any]) -> str:
    expires = linkedin_store._parse_slot(str(connection.get("tokenExpiresAt") or ""))
    if expires is not None and expires > datetime.now(HKT) + timedelta(minutes=2):
        return str(connection["accessToken"])
    refresh = str(connection.get("refreshToken") or "")
    if not refresh:
        raise LinkedInApiError("Reconnect LinkedIn analytics. The access token expired.", counts_attempt=False)
    if not take_call(table, connection):
        raise LinkedInApiError("Reconnect LinkedIn analytics. The access token expired.", counts_attempt=False)
    previous = str(connection.get("accessToken") or "")
    client_id, client_secret = load_credentials()
    try:
        token = linkedin_api.refresh_access_token(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh,
        )
    except LinkedInApiError as exc:
        raise LinkedInApiError("Reconnect LinkedIn analytics. The access token expired.", counts_attempt=False) from exc
    return _remember_token(table, connection, previous, token)


def handle_http(event: dict[str, Any], method: str, parts: list[str], user_sub: str | None) -> dict[str, Any]:
    if parts == ["analytics", "connect"] and method == "POST":
        return _connect(event, user_sub)
    if parts == ["analytics", "disconnect"] and method == "POST":
        return _disconnect(event, user_sub)
    return _json_response(404, {"message": "Not found"})


def exchange_if_ours(event: dict[str, Any], user_sub: str | None) -> dict[str, Any] | None:
    """Exchange a callback that this app started. ``None`` leaves it to posting."""
    body = _parse_json_body(event)
    state = str(body.get("state") or "").strip()
    if not state or not owns_state(board_store.records_table(), state):
        return None
    return _exchange(event, user_sub)


def _require_enabled():
    if linkedin_store.feature_enabled():
        return None
    return _json_response(403, {"message": "LinkedIn is turned off.", "reason": "linkedin_disabled"})


def _origin() -> str:
    return (os.environ.get("ADMIN_WEB_ORIGIN") or "https://admin.lx-software.com").rstrip("/")


def _token_expiry(token: dict[str, Any]) -> str:
    from timeutil import format_iso_millis

    try:
        seconds = int(token.get("expires_in") or 0)
    except (TypeError, ValueError):
        seconds = 0
    if seconds <= 0:
        seconds = 60 * 24 * 3600
    return format_iso_millis(datetime.now(HKT) + timedelta(seconds=seconds))


def _connect(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    try:
        client_id, _secret = load_credentials()
    except LinkedInApiError as exc:
        return _json_response(503, {"message": str(exc)})
    state = secrets.token_urlsafe(18)
    table = board_store.records_table()
    linkedin_store.save_oauth_state(table, state, user_sub or "", analytics_app=True)
    url = authorize_url(
        client_id=client_id,
        redirect=linkedin_api.redirect_uri(_origin()),
        state=state,
    )
    _audit(user_sub, "LINKEDIN_ANALYTICS", "connect", event)
    return _json_response(200, {"url": url})


def _exchange(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    body = _parse_json_body(event)
    code = str(body.get("code") or "").strip()
    state = str(body.get("state") or "").strip()
    if not code or not state:
        return _json_response(400, {"message": "code and state are required"})
    table = board_store.records_table()
    try:
        owner, _pages, _flag = linkedin_store.consume_oauth_state(table, state)
        if owner and user_sub and owner != user_sub:
            raise LinkedInError("That LinkedIn sign-in belongs to another session.")
        client_id, client_secret = load_credentials()
        token = linkedin_api.exchange_code(
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            redirect=linkedin_api.redirect_uri(_origin()),
        )
        access = str(token.get("access_token") or "")
        if not access:
            raise LinkedInApiError("LinkedIn did not return an access token.")
        profile = linkedin_api.basic_profile(access)
        save_connection(
            table,
            {
                "accessToken": access,
                "refreshToken": str(token.get("refresh_token") or ""),
                "tokenExpiresAt": _token_expiry(token),
                "memberId": profile["memberId"],
                "memberName": profile["memberName"],
                "connectedAt": board_store.now_iso(),
                "callsOn": datetime.now(timezone.utc).date().isoformat(),
                "calls": 1,
            },
        )
    except (LinkedInError, LinkedInApiError) as exc:
        return _json_response(400, {"message": str(exc)})
    _audit(user_sub, "LINKEDIN_ANALYTICS", "exchange", event)
    linkedin_metrics.queue_backfill(True)
    return _json_response(200, {"analytics": public_status(load_connection(table))})


def _disconnect(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    clear_connection(board_store.records_table())
    _audit(user_sub, "LINKEDIN_ANALYTICS", "disconnect", event)
    return _json_response(200, {"analytics": public_status({})})
