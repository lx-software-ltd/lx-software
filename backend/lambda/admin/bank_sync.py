"""Admin API: Enable Banking account sync.

Links open-banking (PSD2) bank accounts through the Enable Banking API
(https://enablebanking.com) and refreshes `recordedValue` on the finance
accounts sheet from live bank balances.

Authentication to Enable Banking uses an RS256 JWT whose signing key lives
in AWS KMS (asymmetric RSA_2048 SIGN_VERIFY key, never exported). The
matching public key is registered with Enable Banking when creating the
application (``aws kms get-public-key``; see docs/deployment/admin-website.md);
the resulting application id becomes the JWT `kid`.

State in the records table:
- ``pk=BANKSYNC#state, sk=STATE``: sessions, account→record mappings and
  the last sync report.
- ``pk=BANKSYNC#auth#{state}, sk=META``: pending authorization state token
  (CSRF guard for the bank redirect), expired via the table's TTL attribute.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

import boto3

import runtime
from ddb_convert import _from_ddb_nested, _to_ddb_nested
from finance_store import (
    _finance_sheet_ddb_key,
    _load_accounts_records,
    _merge_accounts_last_updated,
)
from http_common import _audit, _json_response, _log_event, _parse_json_body

EB_DEFAULT_API_ORIGIN = "https://api.enablebanking.com"
EB_JWT_TTL_SECONDS = 3600
EB_HTTP_TIMEOUT_SECONDS = 25
# UK banks cap PSD2 consents at 90 days; the EB aspsps metadata carries the
# per-bank maximum which we additionally respect below.
EB_MAX_CONSENT_SECONDS = 180 * 24 * 3600
EB_AUTH_STATE_TTL_SECONDS = 3600

BANK_SYNC_STATE_KEY = {"pk": "BANKSYNC#state", "sk": "STATE"}
BANKING_CALLBACK_PATH = "/banking/callback"

MAX_BANK_SESSIONS = 10
MAX_BANK_MAPPINGS = 50

# Booked/settled balances first, then expected, then available/interim.
BALANCE_TYPE_PREFERENCE = ("CLBD", "XPCD", "CLAV", "ITAV", "VALU", "OTHR")

_jwt_cache: dict[str, Any] = {"token": None, "expires": 0.0, "app_id": None}


class BankSyncError(Exception):
    """Client error (maps to HTTP 400)."""


class BankSyncUpstreamError(Exception):
    """Enable Banking API failure (maps to HTTP 502)."""


def _eb_api_origin() -> str:
    return os.environ.get("ENABLE_BANKING_API_ORIGIN") or EB_DEFAULT_API_ORIGIN


def _eb_app_id() -> str:
    return (os.environ.get("ENABLE_BANKING_APP_ID") or "").strip()


def _eb_kms_key_id() -> str:
    return (os.environ.get("ENABLE_BANKING_KMS_KEY_ID") or "").strip()


def bank_sync_enabled() -> bool:
    return bool(_eb_app_id() and _eb_kms_key_id())


def _kms_client() -> Any:
    if runtime._kms is None:
        runtime._kms = boto3.client("kms")
    return runtime._kms


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _build_eb_jwt(now_epoch: int | None = None) -> str:
    """RS256 JWT for Enable Banking, signed via KMS (RSASSA_PKCS1_V1_5_SHA_256)."""
    now = int(now_epoch if now_epoch is not None else time.time())
    header = {"typ": "JWT", "alg": "RS256", "kid": _eb_app_id()}
    payload = {
        "iss": "enablebanking.com",
        "aud": "api.enablebanking.com",
        "iat": now,
        "exp": now + EB_JWT_TTL_SECONDS,
    }
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    )
    out = _kms_client().sign(
        KeyId=_eb_kms_key_id(),
        Message=signing_input.encode("ascii"),
        MessageType="RAW",
        SigningAlgorithm="RSASSA_PKCS1_V1_5_SHA_256",
    )
    return signing_input + "." + _b64url(out["Signature"])


def _eb_jwt() -> str:
    """Cached JWT; re-signed via KMS when close to expiry or app id changes."""
    now = time.time()
    if (
        _jwt_cache["token"]
        and _jwt_cache["app_id"] == _eb_app_id()
        and now < float(_jwt_cache["expires"]) - 120
    ):
        return str(_jwt_cache["token"])
    token = _build_eb_jwt()
    _jwt_cache["token"] = token
    _jwt_cache["expires"] = now + EB_JWT_TTL_SECONDS
    _jwt_cache["app_id"] = _eb_app_id()
    return token


def _eb_request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
) -> dict[str, Any]:
    url = f"{_eb_api_origin()}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    data = None
    headers = {
        "Authorization": f"Bearer {_eb_jwt()}",
        "Accept": "application/json",
        "User-Agent": "lxsoftware-admin-api/1.0",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=EB_HTTP_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        message = f"Enable Banking HTTP {exc.code}"
        try:
            parsed = json.loads(detail)
            if isinstance(parsed, dict) and isinstance(parsed.get("message"), str):
                message = f"{message}: {parsed['message'][:200]}"
        except json.JSONDecodeError:
            pass
        _log_event(
            "warning",
            tag="bank_sync_upstream_http_error",
            method=method,
            path=path,
            status=exc.code,
            detail=detail,
        )
        raise BankSyncUpstreamError(message) from exc
    except urllib.error.URLError as exc:
        _log_event(
            "warning",
            tag="bank_sync_upstream_unreachable",
            method=method,
            path=path,
            err=str(exc)[:200],
        )
        raise BankSyncUpstreamError("Enable Banking unreachable") from exc
    try:
        parsed_body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BankSyncUpstreamError("Enable Banking returned invalid JSON") from exc
    if not isinstance(parsed_body, dict):
        raise BankSyncUpstreamError("Enable Banking returned unexpected payload")
    return parsed_body


# ---------------------------------------------------------------------------
# State storage
# ---------------------------------------------------------------------------


def _sanitize_bank_account(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    uid = raw.get("uid")
    if not isinstance(uid, str) or not uid.strip():
        return None
    out: dict[str, Any] = {"uid": uid.strip()}
    for key in ("name", "identifier", "currency", "product"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()[:200]
    return out


def _sanitize_bank_session(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    sid = raw.get("sessionId")
    bank = raw.get("bankName")
    country = raw.get("bankCountry")
    if not (isinstance(sid, str) and sid.strip()):
        return None
    if not (isinstance(bank, str) and bank.strip()):
        return None
    if not (isinstance(country, str) and country.strip()):
        return None
    out: dict[str, Any] = {
        "sessionId": sid.strip(),
        "bankName": bank.strip()[:100],
        "bankCountry": country.strip()[:2].upper(),
    }
    for key in ("validUntil", "createdAt"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()[:40]
    accounts_raw = raw.get("accounts")
    accounts: list[dict[str, Any]] = []
    if isinstance(accounts_raw, list):
        for acc in accounts_raw:
            sanitized = _sanitize_bank_account(acc)
            if sanitized is not None:
                accounts.append(sanitized)
    out["accounts"] = accounts
    return out


def _sanitize_bank_mapping(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    uid = raw.get("accountUid")
    rec = raw.get("accountRecordId")
    if not (isinstance(uid, str) and uid.strip()):
        return None
    if not (isinstance(rec, str) and rec.strip()):
        return None
    return {"accountUid": uid.strip(), "accountRecordId": rec.strip()}


def _load_bank_sync_state(table: Any) -> dict[str, Any]:
    raw = table.get_item(Key=BANK_SYNC_STATE_KEY)
    item = raw.get("Item")
    doc = _from_ddb_nested(item) if item else {}
    sessions: list[dict[str, Any]] = []
    if isinstance(doc.get("sessions"), list):
        for s in doc["sessions"]:
            sanitized = _sanitize_bank_session(s)
            if sanitized is not None:
                sessions.append(sanitized)
    mappings: list[dict[str, Any]] = []
    if isinstance(doc.get("mappings"), list):
        for m in doc["mappings"]:
            sanitized_m = _sanitize_bank_mapping(m)
            if sanitized_m is not None:
                mappings.append(sanitized_m)
    last_sync = doc.get("lastSync")
    if not isinstance(last_sync, dict):
        last_sync = None
    return {"sessions": sessions, "mappings": mappings, "lastSync": last_sync}


def _save_bank_sync_state(table: Any, state: dict[str, Any]) -> None:
    item = {**BANK_SYNC_STATE_KEY, **_to_ddb_nested(state)}
    table.put_item(Item=item)


def _auth_state_key(state_token: str) -> dict[str, str]:
    return {"pk": f"BANKSYNC#auth#{state_token}", "sk": "META"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Redirect URL allowlist
# ---------------------------------------------------------------------------


def _allowed_redirect_urls() -> list[str]:
    origins: list[str] = []
    admin_origin = (os.environ.get("ADMIN_WEB_ORIGIN") or "").strip().rstrip("/")
    if admin_origin:
        origins.append(admin_origin)
    # Vite dev server, for local testing (also register it with Enable Banking).
    origins.append("http://localhost:5173")
    return [f"{origin}{BANKING_CALLBACK_PATH}" for origin in origins]


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


def _disabled_response() -> dict[str, Any]:
    return _json_response(
        400,
        {
            "message": (
                "Bank sync is not configured. Deploy the stack with the "
                "EnableBankingAppId parameter set (register the application "
                "with the stack's Enable Banking KMS public key first)."
            )
        },
    )


def handle_banking_get(event: dict[str, Any]) -> dict[str, Any]:
    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
    state = _load_bank_sync_state(table)
    return _json_response(
        200,
        {
            "enabled": bank_sync_enabled(),
            "callbackPath": BANKING_CALLBACK_PATH,
            "sessions": state["sessions"],
            "mappings": state["mappings"],
            "lastSync": state["lastSync"],
        },
    )


def handle_banking_banks(event: dict[str, Any]) -> dict[str, Any]:
    if not bank_sync_enabled():
        return _disabled_response()
    params = event.get("queryStringParameters") or {}
    country = str(params.get("country") or "").strip().upper()
    if len(country) != 2 or not country.isalpha():
        return _json_response(
            400, {"message": "country must be a 2-letter ISO code"}
        )
    try:
        data = _eb_request(
            "GET", "/aspsps", query={"country": country, "psu_type": "personal"}
        )
    except BankSyncUpstreamError as exc:
        return _json_response(502, {"message": str(exc)})
    banks = []
    for aspsp in data.get("aspsps") or []:
        if not isinstance(aspsp, dict):
            continue
        name = aspsp.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        banks.append(
            {
                "name": name,
                "country": aspsp.get("country") or country,
                "logo": aspsp.get("logo"),
                "beta": bool(aspsp.get("beta")),
                "maximumConsentValidity": aspsp.get("maximum_consent_validity"),
            }
        )
    return _json_response(200, {"banks": banks})


def _consent_valid_until(maximum_consent_validity: Any) -> str:
    seconds = EB_MAX_CONSENT_SECONDS
    if isinstance(maximum_consent_validity, (int, float)) and not isinstance(
        maximum_consent_validity, bool
    ):
        candidate = int(maximum_consent_validity)
        if candidate > 0:
            seconds = min(seconds, candidate)
    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return until.strftime("%Y-%m-%dT%H:%M:%SZ")


def handle_banking_auth_start(
    event: dict[str, Any], user_sub: str | None
) -> dict[str, Any]:
    if not bank_sync_enabled():
        return _disabled_response()
    body = _parse_json_body(event)
    bank_name = body.get("bankName")
    country = str(body.get("country") or "").strip().upper()
    redirect_url = str(body.get("redirectUrl") or "").strip()
    if not isinstance(bank_name, str) or not bank_name.strip():
        return _json_response(400, {"message": "bankName is required"})
    if len(country) != 2 or not country.isalpha():
        return _json_response(
            400, {"message": "country must be a 2-letter ISO code"}
        )
    allowed = _allowed_redirect_urls()
    if redirect_url not in allowed:
        return _json_response(
            400,
            {"message": f"redirectUrl must be one of: {', '.join(allowed)}"},
        )
    try:
        aspsps = _eb_request(
            "GET", "/aspsps", query={"country": country, "psu_type": "personal"}
        )
    except BankSyncUpstreamError as exc:
        return _json_response(502, {"message": str(exc)})
    matched: dict[str, Any] | None = None
    for aspsp in aspsps.get("aspsps") or []:
        if isinstance(aspsp, dict) and aspsp.get("name") == bank_name.strip():
            matched = aspsp
            break
    if matched is None:
        return _json_response(
            400,
            {"message": f"Unknown bank {bank_name.strip()!r} for country {country}"},
        )
    state_token = str(uuid.uuid4())
    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
    table.put_item(
        Item={
            **_auth_state_key(state_token),
            "bankName": bank_name.strip(),
            "bankCountry": country,
            "redirectUrl": redirect_url,
            "createdAt": _utc_now_iso(),
            "expiresAt": int(time.time()) + EB_AUTH_STATE_TTL_SECONDS,
        }
    )
    try:
        started = _eb_request(
            "POST",
            "/auth",
            body={
                "access": {
                    "valid_until": _consent_valid_until(
                        matched.get("maximum_consent_validity")
                    )
                },
                "aspsp": {"name": bank_name.strip(), "country": country},
                "state": state_token,
                "redirect_url": redirect_url,
                "psu_type": "personal",
            },
        )
    except BankSyncUpstreamError as exc:
        return _json_response(502, {"message": str(exc)})
    url = started.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        return _json_response(
            502, {"message": "Enable Banking did not return an authorization URL"}
        )
    _audit(user_sub, "BANKING_AUTH_START", f"{country}:{bank_name.strip()}", event)
    _log_event(
        "info",
        tag="bank_sync_auth_started",
        bank=bank_name.strip(),
        country=country,
        state=state_token,
    )
    return _json_response(200, {"url": url, "state": state_token})


def _summarize_session_accounts(raw_accounts: Any) -> list[dict[str, Any]]:
    accounts: list[dict[str, Any]] = []
    if not isinstance(raw_accounts, list):
        return accounts
    for acc in raw_accounts:
        if not isinstance(acc, dict):
            continue
        uid = acc.get("uid")
        if not isinstance(uid, str) or not uid.strip():
            continue
        identifier = ""
        account_id = acc.get("account_id")
        if isinstance(account_id, dict):
            iban = account_id.get("iban")
            if isinstance(iban, str) and iban.strip():
                identifier = iban.strip()
        if not identifier:
            for aid in acc.get("all_account_ids") or []:
                if isinstance(aid, dict):
                    ident = aid.get("identification")
                    if isinstance(ident, str) and ident.strip():
                        identifier = ident.strip()
                        break
        entry: dict[str, Any] = {"uid": uid.strip()}
        if identifier:
            entry["identifier"] = identifier[:200]
        for src_key, dst_key in (("name", "name"), ("product", "product"), ("currency", "currency")):
            val = acc.get(src_key)
            if isinstance(val, str) and val.strip():
                entry[dst_key] = val.strip()[:200]
        accounts.append(entry)
    return accounts


def handle_banking_auth_complete(
    event: dict[str, Any], user_sub: str | None
) -> dict[str, Any]:
    if not bank_sync_enabled():
        return _disabled_response()
    body = _parse_json_body(event)
    code = body.get("code")
    state_token = body.get("state")
    if not isinstance(code, str) or not code.strip():
        return _json_response(400, {"message": "code is required"})
    if not isinstance(state_token, str) or not state_token.strip():
        return _json_response(400, {"message": "state is required"})
    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
    key = _auth_state_key(state_token.strip())
    pending_raw = table.get_item(Key=key).get("Item")
    if not pending_raw:
        return _json_response(
            400,
            {"message": "Unknown or expired authorization state; restart the bank link"},
        )
    pending = _from_ddb_nested(pending_raw)
    expires_at = pending.get("expiresAt")
    if isinstance(expires_at, (int, float)) and time.time() > float(expires_at):
        table.delete_item(Key=key)
        return _json_response(
            400,
            {"message": "Authorization state expired; restart the bank link"},
        )
    try:
        session = _eb_request("POST", "/sessions", body={"code": code.strip()})
    except BankSyncUpstreamError as exc:
        return _json_response(502, {"message": str(exc)})
    table.delete_item(Key=key)
    session_id = session.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return _json_response(
            502, {"message": "Enable Banking did not return a session id"}
        )
    aspsp = session.get("aspsp") if isinstance(session.get("aspsp"), dict) else {}
    access = session.get("access") if isinstance(session.get("access"), dict) else {}
    stored_session: dict[str, Any] = {
        "sessionId": session_id.strip(),
        "bankName": str(aspsp.get("name") or pending.get("bankName") or "")[:100],
        "bankCountry": str(
            aspsp.get("country") or pending.get("bankCountry") or ""
        )[:2].upper(),
        "createdAt": _utc_now_iso(),
        "accounts": _summarize_session_accounts(session.get("accounts")),
    }
    valid_until = access.get("valid_until")
    if isinstance(valid_until, str) and valid_until.strip():
        stored_session["validUntil"] = valid_until.strip()[:40]
    state = _load_bank_sync_state(table)
    sessions = [
        s for s in state["sessions"] if s["sessionId"] != stored_session["sessionId"]
    ]
    sessions.append(stored_session)
    if len(sessions) > MAX_BANK_SESSIONS:
        return _json_response(
            400, {"message": f"At most {MAX_BANK_SESSIONS} bank connections allowed"}
        )
    state["sessions"] = sessions
    _save_bank_sync_state(table, state)
    _audit(user_sub, "BANKING_SESSION_CREATE", stored_session["sessionId"], event)
    _log_event(
        "info",
        tag="bank_sync_session_created",
        session_id=stored_session["sessionId"],
        bank=stored_session["bankName"],
        account_count=len(stored_session["accounts"]),
    )
    return _json_response(200, {"session": stored_session})


def handle_banking_session_delete(
    event: dict[str, Any], user_sub: str | None, session_id: str
) -> dict[str, Any]:
    if not session_id.strip():
        return _json_response(404, {"message": "Not found"})
    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
    state = _load_bank_sync_state(table)
    remaining = [s for s in state["sessions"] if s["sessionId"] != session_id]
    if len(remaining) == len(state["sessions"]):
        return _json_response(404, {"message": "Session not found"})
    removed = next(
        s for s in state["sessions"] if s["sessionId"] == session_id
    )
    removed_uids = {a["uid"] for a in removed.get("accounts", [])}
    state["sessions"] = remaining
    state["mappings"] = [
        m for m in state["mappings"] if m["accountUid"] not in removed_uids
    ]
    if bank_sync_enabled():
        # Best effort: close the bank consent too. Local state is already
        # authoritative for sync, so upstream failures are only logged.
        try:
            _eb_request("DELETE", f"/sessions/{quote(session_id, safe='')}")
        except BankSyncUpstreamError as exc:
            _log_event(
                "warning",
                tag="bank_sync_session_delete_upstream_failed",
                session_id=session_id,
                err=str(exc)[:200],
            )
    _save_bank_sync_state(table, state)
    _audit(user_sub, "BANKING_SESSION_DELETE", session_id, event)
    return _json_response(200, {"sessions": state["sessions"], "mappings": state["mappings"]})


def handle_banking_mappings_put(
    event: dict[str, Any], user_sub: str | None
) -> dict[str, Any]:
    body = _parse_json_body(event)
    raw = body.get("mappings")
    if not isinstance(raw, list):
        return _json_response(400, {"message": "mappings must be an array"})
    if len(raw) > MAX_BANK_MAPPINGS:
        return _json_response(
            400, {"message": f"At most {MAX_BANK_MAPPINGS} mappings allowed"}
        )
    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
    state = _load_bank_sync_state(table)
    known_uids = {
        a["uid"] for s in state["sessions"] for a in s.get("accounts", [])
    }
    account_record_ids = {r["id"] for r in _load_accounts_records(table)}
    mappings: list[dict[str, Any]] = []
    seen_uids: set[str] = set()
    seen_records: set[str] = set()
    for i, entry in enumerate(raw):
        mapping = _sanitize_bank_mapping(entry)
        if mapping is None:
            return _json_response(
                400,
                {"message": f"mappings[{i}] must have accountUid and accountRecordId"},
            )
        if mapping["accountUid"] not in known_uids:
            return _json_response(
                400,
                {"message": f"mappings[{i}].accountUid is not a linked bank account"},
            )
        if mapping["accountRecordId"] not in account_record_ids:
            return _json_response(
                400,
                {
                    "message": (
                        f"mappings[{i}].accountRecordId does not match an "
                        "accounts-sheet record"
                    )
                },
            )
        if mapping["accountUid"] in seen_uids:
            return _json_response(
                400, {"message": f"mappings[{i}].accountUid is duplicated"}
            )
        if mapping["accountRecordId"] in seen_records:
            return _json_response(
                400, {"message": f"mappings[{i}].accountRecordId is duplicated"}
            )
        seen_uids.add(mapping["accountUid"])
        seen_records.add(mapping["accountRecordId"])
        mappings.append(mapping)
    state["mappings"] = mappings
    _save_bank_sync_state(table, state)
    _audit(user_sub, "BANKING_MAPPINGS_PUT", str(len(mappings)), event)
    return _json_response(200, {"mappings": mappings})


def _pick_balance(balances: Any) -> dict[str, Any] | None:
    if not isinstance(balances, list):
        return None
    usable: list[dict[str, Any]] = []
    for bal in balances:
        if not isinstance(bal, dict):
            continue
        amount_obj = bal.get("balance_amount")
        if not isinstance(amount_obj, dict):
            continue
        try:
            amount = float(str(amount_obj.get("amount")))
        except (TypeError, ValueError):
            continue
        if amount != amount or abs(amount) > 1e15:
            continue
        usable.append(
            {
                "amount": amount,
                "currency": str(amount_obj.get("currency") or "").upper(),
                "balanceType": str(bal.get("balance_type") or ""),
            }
        )
    if not usable:
        return None
    for preferred in BALANCE_TYPE_PREFERENCE:
        for bal in usable:
            if bal["balanceType"] == preferred:
                return bal
    return usable[0]


def run_bank_sync(table: Any) -> dict[str, Any]:
    """Refresh mapped accounts-sheet records from live bank balances.

    Returns the sync report that is also persisted as ``lastSync``.
    """
    state = _load_bank_sync_state(table)
    account_by_uid: dict[str, dict[str, Any]] = {}
    for session in state["sessions"]:
        for acc in session.get("accounts", []):
            account_by_uid[acc["uid"]] = acc
    existing_records = _load_accounts_records(table)
    records_by_id = {r["id"]: r for r in existing_records}
    results: list[dict[str, Any]] = []
    updated_values: dict[str, float] = {}
    for mapping in state["mappings"]:
        uid = mapping["accountUid"]
        record_id = mapping["accountRecordId"]
        result: dict[str, Any] = {"accountUid": uid, "accountRecordId": record_id}
        record = records_by_id.get(record_id)
        if record is None:
            result.update(status="error", message="Accounts-sheet record not found")
            results.append(result)
            continue
        if uid not in account_by_uid:
            result.update(status="error", message="Bank account no longer linked")
            results.append(result)
            continue
        try:
            data = _eb_request(
                "GET", f"/accounts/{quote(uid, safe='')}/balances"
            )
        except BankSyncUpstreamError as exc:
            result.update(status="error", message=str(exc)[:300])
            results.append(result)
            continue
        balance = _pick_balance(data.get("balances"))
        if balance is None:
            result.update(status="error", message="No usable balance returned")
            results.append(result)
            continue
        record_currency = str(record.get("currency") or "").upper()
        if balance["currency"] and balance["currency"] != record_currency:
            result.update(
                status="error",
                message=(
                    f"Balance currency {balance['currency']} does not match "
                    f"record currency {record_currency}"
                ),
            )
            results.append(result)
            continue
        updated_values[record_id] = balance["amount"]
        result.update(
            status="ok",
            balance=balance["amount"],
            currency=balance["currency"] or record_currency,
            balanceType=balance["balanceType"],
        )
        results.append(result)
    if updated_values:
        new_records: list[dict[str, Any]] = []
        for record in existing_records:
            updated = dict(record)
            if record["id"] in updated_values:
                updated["recordedValue"] = updated_values[record["id"]]
            updated.pop("lastUpdated", None)
            new_records.append(updated)
        merged = _merge_accounts_last_updated(new_records, existing_records)
        doc = {"records": merged}
        table.put_item(
            Item={**_finance_sheet_ddb_key("accounts"), **_to_ddb_nested(doc)}
        )
    report = {"at": _utc_now_iso(), "results": results}
    state["lastSync"] = report
    _save_bank_sync_state(table, state)
    _log_event(
        "info",
        tag="bank_sync_completed",
        total=len(results),
        ok=sum(1 for r in results if r.get("status") == "ok"),
        errors=sum(1 for r in results if r.get("status") == "error"),
    )
    return report


def handle_banking_sync_post(
    event: dict[str, Any], user_sub: str | None
) -> dict[str, Any]:
    if not bank_sync_enabled():
        return _disabled_response()
    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
    report = run_bank_sync(table)
    _audit(user_sub, "BANKING_SYNC", str(len(report["results"])), event)
    return _json_response(200, report)


def handle_bank_sync_worker(event: dict[str, Any]) -> None:
    """Entry point for the scheduled (EventBridge) daily sync."""
    if not bank_sync_enabled():
        _log_event("info", tag="bank_sync_skipped", reason="not_configured")
        return
    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
    try:
        run_bank_sync(table)
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        _log_event("error", tag="bank_sync_worker_failed", err=str(exc)[:400])
