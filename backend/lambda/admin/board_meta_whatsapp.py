"""Connect the business's own WhatsApp Business app number (coexistence) and import history once."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import board_meta
import board_meta_store
import board_store
from http_common import _log_event

_STATE = "meta:whatsapp"
_SYNC = "meta:wa-sync"
_KEEP_SECONDS = 3650 * 86400
_LOCK_SECONDS = 300
_STEPS = (("contacts", "smb_app_state_sync"), ("history", "history"))
_NUMBER_FIELDS = "id,display_phone_number,verified_name"
_COEXISTENCE_FIELDS = ",is_on_biz_app,platform_type"
_HISTORY_DECLINED = "2593109"


def status(table: Any) -> dict[str, Any]:
    state = _load(table)
    sync = (board_store.get_cache(table, _SYNC) or {}).get("payload") or {}
    history = (board_store.get_cache(table, "meta:wa-history") or {}).get("payload") or {}
    disconnected = (board_store.get_cache(table, "meta:whatsapp-disconnected") or {}).get("payload") or {}
    return {
        "phoneNumberId": state.get("phoneNumberId") or board_meta.wa_phone_id(),
        "wabaId": state.get("wabaId") or board_meta.waba_id(),
        # Only a number Meta confirmed through connect() counts. An id in the environment does not.
        "connected": bool(state.get("connectedAt")),
        "displayPhoneNumber": state.get("displayPhoneNumber") or "",
        "verifiedName": state.get("verifiedName") or "",
        "onBusinessApp": state.get("onBusinessApp"),
        "sync": {**sync, "done": _done(sync)},
        "historyDeclined": bool(history.get("declined")),
        "disconnectedAt": disconnected.get("at") or "",
    }


def connect(table: Any, body: dict[str, Any]) -> dict[str, Any]:
    """Check the number with Meta, subscribe this app to its account, then record the ids.

    Does not register the phone number. Registration would move it off the WhatsApp Business app.
    """
    phone = str(body.get("phoneNumberId") or "").strip()
    waba = str(body.get("wabaId") or "").strip()
    if not phone.isdigit() or not waba.isdigit():
        raise board_meta.MetaError("phoneNumberId and wabaId are required", status=400)
    number = _number(waba, phone)
    subscribed = board_meta.graph("POST", f"{waba}/subscribed_apps")
    state = {
        "phoneNumberId": phone,
        "wabaId": waba,
        "connectedAt": board_store.now_iso(),
        "displayPhoneNumber": str(number.get("display_phone_number") or ""),
        "verifiedName": str(number.get("verified_name") or ""),
        "onBusinessApp": number.get("is_on_biz_app") if isinstance(number.get("is_on_biz_app"), bool) else None,
        "platformType": str(number.get("platform_type") or ""),
    }
    board_store.put_cache(table, _STATE, state, ttl_seconds=_KEEP_SECONDS)
    _log_event("info", tag="board_meta_whatsapp_connected", wabaId=waba, onBusinessApp=state["onBusinessApp"])
    return {"ok": True, "subscribed": bool(subscribed.get("success", True)), **status(table)}


def sync_history(table: Any) -> dict[str, Any]:
    """Contact sync, then history. A step Meta accepted is never sent again."""
    record = dict((board_store.get_cache(table, _SYNC) or {}).get("payload") or {})
    if _done(record):
        raise board_meta.MetaError("WhatsApp history sync already ran for this connection", status=409)
    phone = str(_load(table).get("phoneNumberId") or "")
    if not phone:
        raise board_meta.MetaError("WhatsApp is not connected", status=400)
    # Two clicks must not send the one-shot request twice.
    lock = f"LOCK#{int(time.time()) // _LOCK_SECONDS}"
    if not board_meta_store.claim(table, "meta#wa-sync", lock):
        raise board_meta.MetaError("WhatsApp history sync is already running", status=409)
    try:
        return _run_steps(table, phone, record)
    finally:
        table.delete_item(Key={"pk": board_store.board_pk("meta#wa-sync"), "sk": lock})


def _run_steps(table: Any, phone: str, record: dict[str, Any]) -> dict[str, Any]:
    record.setdefault("startedAt", board_store.now_iso())
    for name, sync_type in _STEPS:
        if (record.get(name) or {}).get("ok"):
            continue
        try:
            record[name] = _smb(phone, sync_type)
        except board_meta.MetaError as exc:
            record[name] = {"syncType": sync_type, "ok": False, "error": str(exc)[:300]}
            board_store.put_cache(table, _SYNC, record, ttl_seconds=_KEEP_SECONDS)
            if _HISTORY_DECLINED in str(exc):
                board_store.put_cache(table, "meta:wa-history", {"declined": True}, ttl_seconds=90 * 86400)
            raise
        board_store.put_cache(table, _SYNC, record, ttl_seconds=_KEEP_SECONDS)
    return {"ok": True, **record, "done": True}


def phone_link(number: str, text: str) -> str:
    digits = board_meta._phone_digits(number)
    if not digits:
        return ""
    return f"https://wa.me/{digits}?text={quote(text[:1000])}"


def _number(waba: str, phone: str) -> dict[str, Any]:
    """The phone number as Meta lists it under the account. Raises when it is not there."""
    try:
        rows = board_meta.graph_pages("GET", f"{waba}/phone_numbers", {"fields": _NUMBER_FIELDS + _COEXISTENCE_FIELDS}, limit=50)
    except board_meta.MetaError as exc:
        if "nonexisting field" not in str(exc):
            raise
        rows = board_meta.graph_pages("GET", f"{waba}/phone_numbers", {"fields": _NUMBER_FIELDS}, limit=50)
    for row in rows:
        if str(row.get("id") or "") == phone:
            return row
    raise board_meta.MetaError(f"Meta does not list phone number id {phone} under WhatsApp Business account {waba}", status=400)


def _done(record: dict[str, Any]) -> bool:
    return all((record.get(name) or {}).get("ok") for name, _sync_type in _STEPS)


def _smb(phone: str, sync_type: str) -> dict[str, Any]:
    data = board_meta.graph(
        "POST",
        f"{phone}/smb_app_data",
        body={"messaging_product": "whatsapp", "sync_type": sync_type},
    )
    return {"syncType": sync_type, "ok": True, "id": data.get("request_id") or data.get("id") or ""}


def _load(table: Any) -> dict[str, Any]:
    cached = board_store.get_cache(table, _STATE) or {}
    payload = cached.get("payload")
    return payload if isinstance(payload, dict) else {}
