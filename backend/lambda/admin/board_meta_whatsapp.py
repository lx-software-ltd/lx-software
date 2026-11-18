"""Connect the business's own WhatsApp Business app number (coexistence) and import history once."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import board_meta
import board_store
from http_common import _log_event

_STATE = "meta:whatsapp"
_SYNC = "meta:wa-sync"


def status(table: Any) -> dict[str, Any]:
    state = _load(table)
    sync = (board_store.get_cache(table, _SYNC) or {}).get("payload") or {}
    history = (board_store.get_cache(table, "meta:wa-history") or {}).get("payload") or {}
    disconnected = (board_store.get_cache(table, "meta:whatsapp-disconnected") or {}).get("payload") or {}
    return {
        "phoneNumberId": state.get("phoneNumberId") or board_meta.wa_phone_id(),
        "wabaId": state.get("wabaId") or board_meta.waba_id(),
        "connected": bool(state.get("phoneNumberId") or board_meta.wa_phone_id()),
        "sync": sync,
        "historyDeclined": bool(history.get("declined")),
        "disconnectedAt": disconnected.get("at") or "",
    }


def connect(table: Any, body: dict[str, Any]) -> dict[str, Any]:
    """Record the ids from Embedded Signup and subscribe this app to that account.

    Does not register the phone number. Registration would move it off the WhatsApp Business app.
    """
    phone = str(body.get("phoneNumberId") or "").strip()
    waba = str(body.get("wabaId") or "").strip()
    if not phone.isdigit() or not waba.isdigit():
        raise board_meta.MetaError("phoneNumberId and wabaId are required")
    subscribed = board_meta.graph("POST", f"{waba}/subscribed_apps")
    state = {"phoneNumberId": phone, "wabaId": waba, "connectedAt": board_store.now_iso()}
    board_store.put_cache(table, _STATE, state, ttl_seconds=365 * 86400)
    _log_event("info", tag="board_meta_whatsapp_connected", wabaId=waba)
    return {"ok": True, "subscribed": bool(subscribed.get("success", True)), **status(table)}


def sync_history(table: Any) -> dict[str, Any]:
    """One-shot contact sync, then history. A second call is refused."""
    prior = (board_store.get_cache(table, _SYNC) or {}).get("payload") or {}
    if prior.get("startedAt"):
        raise board_meta.MetaError("WhatsApp history sync already ran for this connection")
    phone = str(_load(table).get("phoneNumberId") or board_meta.wa_phone_id() or "")
    if not phone:
        raise board_meta.MetaError("WhatsApp is not connected")
    contacts = _smb(phone, "smb_app_state_sync")
    history = _smb(phone, "history")
    record = {"startedAt": board_store.now_iso(), "contacts": contacts, "history": history}
    board_store.put_cache(table, _SYNC, record, ttl_seconds=365 * 86400)
    return {"ok": True, **record}


def stored_phone_id(table: Any) -> str:
    return str(_load(table).get("phoneNumberId") or "")


def stored_waba_id(table: Any) -> str:
    return str(_load(table).get("wabaId") or "")


def phone_link(number: str, text: str) -> str:
    digits = board_meta._phone_digits(number)
    if not digits:
        return ""
    return f"https://wa.me/{digits}?text={quote(text[:1000])}"


def approval_extra(ctx: Any, args: dict[str, Any]) -> dict[str, str]:
    thread_id = str(args.get("threadId") or "")
    thread = board_store.get_meta_thread(ctx.table, thread_id) if thread_id else None
    number = str((thread or {}).get("phone") or (thread or {}).get("senderId") or args.get("to") or "")
    text = str(args.get("message") or "")
    link = phone_link(number, text)
    return {"phoneLink": link} if link else {}


def _smb(phone: str, sync_type: str) -> dict[str, Any]:
    data = board_meta.graph(
        "POST",
        f"{phone}/smb_app_data",
        body={"messaging_product": "whatsapp", "sync_type": sync_type},
    )
    return {"syncType": sync_type, "ok": True, "id": data.get("id") or data.get("request_id") or ""}


def _load(table: Any) -> dict[str, Any]:
    cached = board_store.get_cache(table, _STATE) or {}
    payload = cached.get("payload")
    return payload if isinstance(payload, dict) else {}
