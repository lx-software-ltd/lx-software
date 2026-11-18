"""Parse Meta webhooks into stored threads. No Graph call and no model call."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import board_meta
import board_meta_store
import board_store
from contract_constants import BOARD_KEY, BOARD_TOOLS_CONTRACT
from http_common import _log_event, _utc_iso_z

_LIMITS = BOARD_TOOLS_CONTRACT["limits"]
_TEXT_MAX = int(_LIMITS["metaMessageTextMax"])
_MEDIA_MAX = int(_LIMITS["metaMediaPerMessageMax"])
_MEDIA_TYPES = frozenset({"image", "audio", "video", "file", "reel", "ig_reel", "sticker", "document"})
_FOLLOW_UP_BATCH = 100
_HISTORY_DECLINED = "2593109"


def ingest_webhook(table: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Store one delivery and return. Triage, names and media run on the async follow-up."""
    obj = str(payload.get("object") or "")
    stored = 0
    duplicates = 0
    live: list[dict[str, str]] = []
    imported: dict[str, dict[str, str]] = {}
    channels: set[str] = set()
    writer = board_meta_store.Writer(table)
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        channel = "whatsapp" if obj == "whatsapp_business_account" else ("instagram" if obj == "instagram" else "page")
        for msg in iter_inbound(entry, channel=channel):
            if msg.get("historyDeclined"):
                board_store.put_cache(table, "meta:wa-history", {"declined": True}, ttl_seconds=90 * 86400)
                continue
            if msg.get("skip_empty"):
                writer.remember_name(str(msg.get("phone") or ""), str(msg.get("senderName") or ""))
                continue
            if not writer.add(msg):
                duplicates += 1
                continue
            stored += 1
            channels.add(str(msg.get("channel") or channel))
            item = {"threadId": str(msg.get("_threadId") or ""), "messageId": str(msg.get("messageId") or ""), "mode": "live" if msg.get("_live") else "link"}
            if msg.get("_live") or (msg.get("direction") == "out" and msg.get("source") != "history"):
                live.append(item)
            elif msg.get("direction") == "in":
                # History is not triaged. One row per thread is enough to link an organisation.
                imported[item["threadId"]] = item
        _note_account(table, entry)
    writer.flush()
    for channel in sorted(channels):
        _mark_delivery(table, channel)
    follow_up(live + list(imported.values()))
    _log_event("info", tag="board_meta_ingested", stored=stored, duplicates=duplicates, object=obj)
    return {"stored": stored, "duplicates": duplicates}


def iter_inbound(entry: dict[str, Any], *, channel: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    owner = str(entry.get("id") or "")
    for item in entry.get("messaging") or entry.get("standby") or []:
        parsed = _messaging_item(item, channel=channel, owner=owner, entry=entry)
        if parsed:
            out.append(parsed)
    for change in entry.get("changes") or []:
        if isinstance(change, dict):
            out.extend(_change(change, channel=channel))
    return out


def _messaging_item(item: Any, *, channel: str, owner: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    message = item.get("message") or {}
    if not isinstance(message, dict) or not message:
        return None
    sender = _sender_id(item.get("sender")) or _sender_id(item.get("from"))
    recipient = _sender_id(item.get("recipient"))
    outbound = bool(message.get("is_echo")) or bool(sender and owner and sender == owner)
    customer = recipient if outbound else sender
    text = str(message.get("text") or message.get("body") or "")
    ts = item.get("timestamp") or entry.get("time") or int(time.time() * 1000)
    return _row(
        channel=channel,
        thread_key=str(customer or sender or message.get("mid") or board_store.new_id()),
        sender_id=str(customer or sender),
        message_id=str(message.get("mid") or message.get("id") or board_store.new_id()),
        text=text,
        timestamp=_int_or(ts, int(time.time() * 1000)),
        direction="out" if outbound else "in",
        source="echo" if outbound else "webhook",
        attachments=_attachments(message.get("attachments")),
        sender_name="" if outbound else _sender_name(item.get("sender")),
    )


def _change(change: dict[str, Any], *, channel: str) -> list[dict[str, Any]]:
    value = change.get("value") or {}
    if not isinstance(value, dict):
        return []
    field = str(change.get("field") or "")
    if field in ("messages", "whatsapp_business_account"):
        return _whatsapp_messages(value, source="webhook", direction="in")
    if field == "smb_message_echoes":
        return _whatsapp_messages(value, source="echo", direction="out", key="message_echoes")
    if field == "history":
        if _declined(value):
            return [_row(channel="whatsapp", thread_key="", sender_id="", message_id="", text="", timestamp=0, direction="in", source="history", attachments=[], historyDeclined=True)]
        return _history(value)
    if field == "smb_app_state_sync":
        return _contacts(value)
    if field in ("comments", "feed"):
        comment = _comment(value, channel=channel)
        return [comment] if comment else []
    return []


def _whatsapp_messages(value: dict[str, Any], *, source: str, direction: str, key: str = "messages") -> list[dict[str, Any]]:
    contacts = value.get("contacts") or []
    contact = contacts[0] if contacts and isinstance(contacts[0], dict) else {}
    fallback = board_meta._phone_digits(str(contact.get("wa_id") or ""))
    name = str(((contact.get("profile") or {}) if isinstance(contact.get("profile"), dict) else {}).get("name") or "")
    out: list[dict[str, Any]] = []
    for raw in value.get(key) or value.get("messages") or []:
        if not isinstance(raw, dict):
            continue
        customer = board_meta._phone_digits(str(raw.get("from") or raw.get("to") or fallback or ""))
        if direction == "out":
            customer = board_meta._phone_digits(str(raw.get("to") or fallback or raw.get("from") or ""))
        text, attachments = _wa_body(raw)
        out.append(
            _row(
                channel="whatsapp",
                thread_key=customer or str(raw.get("id") or board_store.new_id()),
                sender_id=customer,
                message_id=str(raw.get("id") or board_store.new_id()),
                text=text,
                timestamp=_int_or(raw.get("timestamp"), int(time.time())),
                direction=direction,
                source=source,
                attachments=attachments,
                sender_name=name,
                phone=customer,
            )
        )
    return out


def _wa_body(raw: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    kind = str(raw.get("type") or "text")
    if kind == "text":
        return str((raw.get("text") or {}).get("body") or ""), []
    block = raw.get(kind) if isinstance(raw.get(kind), dict) else {}
    caption = str(block.get("caption") or block.get("filename") or "")
    if kind == "location":
        return f"{block.get('latitude')},{block.get('longitude')}".strip(","), []
    if kind == "contacts":
        names = [str((c.get("name") or {}).get("formatted_name") or "") for c in raw.get("contacts") or [] if isinstance(c, dict)]
        return ", ".join(n for n in names if n), []
    if kind in ("reaction",):
        return str((raw.get("reaction") or {}).get("emoji") or ""), []
    media_id = str(block.get("id") or "")
    attachments = []
    if media_id or kind in _MEDIA_TYPES:
        attachments.append({"kind": kind, "mime": str(block.get("mime_type") or ""), "mediaId": media_id, "name": caption})
    return caption or kind, attachments[:_MEDIA_MAX]


def _history(value: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for chunk in value.get("history") or []:
        if not isinstance(chunk, dict):
            continue
        for thread in chunk.get("threads") or []:
            if not isinstance(thread, dict):
                continue
            phone = board_meta._phone_digits(str(thread.get("id") or ""))
            for raw in thread.get("messages") or []:
                if not isinstance(raw, dict):
                    continue
                text, attachments = _wa_body(raw)
                sender = board_meta._phone_digits(str(raw.get("from") or ""))
                direction = "out" if phone and sender and sender != phone else "in"
                out.append(
                    _row(
                        channel="whatsapp",
                        thread_key=phone or sender or str(raw.get("id") or board_store.new_id()),
                        sender_id=phone or sender,
                        message_id=str(raw.get("id") or board_store.new_id()),
                        text=text,
                        timestamp=_int_or(raw.get("timestamp"), int(time.time())),
                        direction=direction,
                        source="history",
                        attachments=attachments,
                        phone=phone,
                    )
                )
    return out


def _contacts(value: dict[str, Any]) -> list[dict[str, Any]]:
    """Contact rows carry a name. They are stored as empty inbound notes only when a phone is present."""
    out: list[dict[str, Any]] = []
    for row in value.get("state_sync") or value.get("contacts") or []:
        if not isinstance(row, dict):
            continue
        contact = row.get("contact") if isinstance(row.get("contact"), dict) else row
        phone = board_meta._phone_digits(str(contact.get("phone_number") or contact.get("wa_id") or ""))
        name = str(((contact.get("profile") or {}) if isinstance(contact.get("profile"), dict) else {}).get("name") or contact.get("full_name") or "")
        if not phone or not name:
            continue
        out.append(
            _row(
                channel="whatsapp",
                thread_key=phone,
                sender_id=phone,
                message_id=f"contact:{phone}:{name}"[:80],
                text="",
                timestamp=int(time.time()),
                direction="in",
                source="webhook",
                attachments=[],
                sender_name=name,
                phone=phone,
                skip_empty=True,
            )
        )
    return [row for row in out if row.get("senderName")]


def _comment(value: dict[str, Any], *, channel: str) -> dict[str, Any] | None:
    item = str(value.get("item") or "")
    if item and item not in ("comment",):
        return None
    comment = value.get("comment") if isinstance(value.get("comment"), dict) else value
    if not isinstance(comment, dict):
        return None
    cid = str(value.get("comment_id") or comment.get("id") or "")
    text = str(comment.get("message") or comment.get("text") or value.get("message") or "")
    if not cid and not text:
        return None
    if not cid:
        cid = board_store.new_id()
    return _row(
        channel="instagram" if channel == "instagram" else "page",
        thread_key=f"comment:{cid}",
        sender_id=_sender_id(comment.get("from") or value.get("from")),
        message_id=cid,
        text=text,
        timestamp=_int_or(comment.get("created_time") or value.get("created_time"), int(time.time() * 1000)),
        direction="in",
        source="webhook",
        attachments=[],
        kind="comment",
        reply_to=str(value.get("parent_id") or value.get("post_id") or ""),
    )


def _row(**fields: Any) -> dict[str, Any]:
    fields["text"] = str(fields.get("text") or "")[:_TEXT_MAX]
    fields["attachments"] = list(fields.get("attachments") or [])[:_MEDIA_MAX]
    for src, dst in (
        ("thread_key", "threadKey"),
        ("sender_id", "senderId"),
        ("message_id", "messageId"),
        ("sender_name", "senderName"),
        ("reply_to", "replyTo"),
    ):
        if dst not in fields:
            fields[dst] = fields.get(src)
    if "timestampMs" not in fields:
        fields["timestampMs"] = fields.get("timestamp")
    return fields


def _attachments(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        if kind not in _MEDIA_TYPES and not payload.get("url"):
            continue
        out.append({"kind": kind or "file", "url": str(payload.get("url") or ""), "mime": str(payload.get("mime_type") or "")})
        if len(out) >= _MEDIA_MAX:
            break
    return out


def _mark_delivery(table: Any, channel: str) -> None:
    if not channel:
        return
    board_store.put_cache(table, f"meta:webhook:{channel}", {"at": _utc_iso_z(datetime.now(timezone.utc))}, ttl_seconds=90 * 86400)


def _note_account(table: Any, entry: dict[str, Any]) -> None:
    for change in entry.get("changes") or []:
        if not isinstance(change, dict) or change.get("field") != "account_update":
            continue
        value = change.get("value") if isinstance(change.get("value"), dict) else {}
        if str(value.get("event") or "") == "PARTNER_REMOVED":
            board_store.put_cache(table, "meta:whatsapp-disconnected", {"at": _utc_iso_z(datetime.now(timezone.utc)), "event": "PARTNER_REMOVED"}, ttl_seconds=90 * 86400)
        if _declined(value):
            board_store.put_cache(table, "meta:wa-history", {"declined": True}, ttl_seconds=90 * 86400)


def follow_up(items: list[dict[str, str]]) -> None:
    import board_async
    import board_meta_inbox

    for start in range(0, len(items), _FOLLOW_UP_BATCH):
        try:
            board_async.invoke_async(
                {"internal": "board_meta_after_ingest", "boardKey": BOARD_KEY, "items": items[start : start + _FOLLOW_UP_BATCH]},
                fallback=board_meta_inbox.handle_after_ingest,
            )
        except Exception as exc:
            _log_event("warning", tag="board_meta_follow_up_failed", error=str(exc)[:200])


def _declined(value: Any, depth: int = 0) -> bool:
    """The business refused to share history. Meta has reported the code at more than one level."""
    if depth > 4:
        return False
    if isinstance(value, dict):
        if str(value.get("code") or "") == _HISTORY_DECLINED:
            return True
        return any(_declined(item, depth + 1) for item in value.values())
    if isinstance(value, list):
        return any(_declined(item, depth + 1) for item in value)
    return False


def _sender_id(raw: Any) -> str:
    if isinstance(raw, dict):
        return str(raw.get("id") or "")
    return str(raw or "")


def _sender_name(raw: Any) -> str:
    if isinstance(raw, dict):
        return str(raw.get("name") or "")[:120]
    return ""


def _int_or(raw: Any, default: int) -> int:
    text = str(raw or "").strip()
    return int(text) if text.isdigit() else default
