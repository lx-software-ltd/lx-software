"""Read a Meta thread the way mail is read: full text in the store, aliases for staff."""

from __future__ import annotations

import re
from typing import Any

import board_meta
import board_pii
import board_store
from contract_constants import BOARD_TOOLS_CONTRACT
from http_common import _log_event

_LIMITS = BOARD_TOOLS_CONTRACT["limits"]
_LIST_MAX = int(_LIMITS["metaThreadListMax"])
_MSG_MAX = int(_LIMITS["metaThreadMessagesMax"])
_BACKFILL = int(_LIMITS["metaBackfillThreadsPerRun"])


def digest_for_context(table: Any) -> dict[str, Any]:
    threads = board_store.list_meta_threads(table)
    unread = [t for t in threads if t.get("unread")]
    def count(channel: str) -> int:
        return sum(1 for t in unread if t.get("channel") == channel)
    return {
        "unread": len(unread),
        "threads": len(threads),
        "whatsappThreads": sum(1 for t in threads if t.get("channel") == "whatsapp"),
        "pageUnread": count("page"),
        "instagramUnread": count("instagram"),
        "whatsappUnread": count("whatsapp"),
    }


def op_list_threads(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    channel = str(args.get("channel") or "all")
    unread_only = bool(args.get("unreadOnly"))
    limit = _limit(args.get("limit"), _LIST_MAX)
    pseud = board_pii.Pseudonymizer(ctx.table)
    rows = []
    for thread in board_store.list_meta_threads(ctx.table):
        if channel != "all" and thread.get("channel") != channel:
            continue
        if unread_only and not thread.get("unread"):
            continue
        rows.append(_public_thread(thread, pseud))
        if len(rows) >= limit:
            break
    pseud.save()
    return {"threads": rows, "count": len(rows)}


def op_get_thread(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    thread_id = str(args.get("threadId") or "").strip()
    thread = board_store.get_meta_thread(ctx.table, thread_id) if thread_id else None
    if not thread:
        raise board_meta.MetaError("thread not found")
    pseud = board_pii.Pseudonymizer(ctx.table)
    messages = [_public_message(row, pseud) for row in _messages(ctx.table, thread_id)]
    pseud.save()
    return {"thread": _public_thread(thread, pseud), "messages": messages, "count": len(messages)}


def op_list_dms(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    return op_list_threads(ctx, {**args, "channel": "page"})


def op_list_whatsapp(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    return op_list_threads(ctx, {**args, "channel": "whatsapp"})


def record_outbound(ctx: Any, args: dict[str, Any], sent: dict[str, Any]) -> None:
    """Store a reply that an approval just sent, so the thread shows both directions."""
    thread_id = str(sent.get("threadId") or args.get("threadId") or "")
    if not thread_id or not sent.get("ok"):
        return
    thread = board_store.get_meta_thread(ctx.table, thread_id) or {"threadId": thread_id}
    text = str(args.get("message") or "")
    received = board_store.now_iso()
    message_id = str(sent.get("messageId") or board_store.new_id())
    fresh = board_store.put_meta_message_if_new(
        ctx.table,
        {
            "threadId": thread_id,
            "messageId": message_id,
            "receivedAt": received,
            "direction": "out",
            "text": text[: int(_LIMITS["metaMessageTextMax"])],
            "textMasked": text[:240],
            "channel": thread.get("channel"),
            "source": "board",
            "attachments": [],
        },
    )
    if not fresh:
        return
    board_store.put_meta_thread(
        ctx.table,
        {**thread, "lastMessageAt": received, "lastOutboundAt": received, "lastDirection": "out", "messageCount": int(thread.get("messageCount") or 0) + 1},
    )


def list_for_owner(table: Any, *, channel: str = "all", unread_only: bool = False) -> dict[str, Any]:
    rows = []
    for thread in board_store.list_meta_threads(table):
        if channel != "all" and thread.get("channel") != channel:
            continue
        if unread_only and not thread.get("unread"):
            continue
        rows.append(_owner_thread(thread))
        if len(rows) >= _LIST_MAX:
            break
    return {"threads": rows, "count": len(rows), "unreadCount": digest_for_context(table)["unread"]}


def thread_for_owner(table: Any, thread_id: str) -> dict[str, Any] | None:
    thread = board_store.get_meta_thread(table, thread_id)
    if not thread:
        return None
    messages = [_owner_message(row) for row in _messages(table, thread_id)]
    return {"thread": _owner_thread(thread), "messages": messages}


def mark_read(table: Any, thread_id: str) -> dict[str, Any] | None:
    thread = board_store.get_meta_thread(table, thread_id)
    if not thread:
        return None
    thread["unread"] = False
    thread["unreadCount"] = 0
    board_store.put_meta_thread(table, thread)
    return _owner_thread(thread)


def mask_public(body: dict[str, Any], rest: list[str]) -> tuple[dict[str, Any], bool]:
    """Mask a key read. Media bytes are refused without the pii scope."""
    if "media" in rest:
        return {"message": "forbidden", "reason": "scope"}, True
    mask = _regex_mask
    if isinstance(body.get("threads"), list):
        body["threads"] = [_mask_owner_thread(row, mask) for row in body["threads"]]
    if isinstance(body.get("thread"), dict):
        body["thread"] = _mask_owner_thread(body["thread"], mask)
    if isinstance(body.get("messages"), list):
        body["messages"] = [_mask_owner_message(row, mask) for row in body["messages"]]
    return body, False


_LONG_NUMBER = re.compile(r"(?<!\d)\d{8,15}(?!\d)")


def _regex_mask(text: str) -> str:
    masked = board_pii.EMAIL_RE.sub("contact#hidden", board_pii.PHONE_RE.sub("phone#hidden", str(text or "")))
    return _LONG_NUMBER.sub("phone#hidden", masked)


def status(table: Any) -> dict[str, Any]:
    import board_meta_whatsapp

    summary = board_meta.status_summary(table)
    summary["lastDelivery"] = {
        channel: ((board_store.get_cache(table, f"meta:webhook:{channel}") or {}).get("payload") or {}).get("at")
        for channel in ("page", "instagram", "whatsapp")
    }
    summary["whatsapp"] = board_meta_whatsapp.status(table)
    return summary


def backfill(table: Any) -> dict[str, Any]:
    """Pull the newest Page and Instagram conversations. WhatsApp has no equivalent read."""
    if not board_meta.page_id():
        return {"skipped": "no page"}
    inserted = 0
    for platform, channel in (("messenger", "page"), ("instagram", "instagram")):
        try:
            rows = board_meta.graph_pages(
                "GET",
                f"{board_meta.page_id()}/conversations",
                {"platform": platform, "fields": "id,updated_time,messages.limit(20){id,message,from,created_time}"},
                limit=_BACKFILL,
            )
        except board_meta.MetaError as exc:
            _log_event("warning", tag="board_meta_backfill_failed", channel=channel, error=str(exc)[:200])
            continue
        inserted += _insert_conversations(table, rows, channel=channel)
    return {"inserted": inserted}


def handle_after_ingest(event: dict[str, Any]) -> dict[str, Any]:
    if not board_store.event_targets_this_board(event):
        return {}
    table = board_store.records_table()
    try:
        import board_meta_triage

        settings = board_store.load_settings(table)
        for item in event.get("items") or []:
            if not isinstance(item, dict):
                continue
            thread = board_store.get_meta_thread(table, str(item.get("threadId") or ""))
            if not thread:
                continue
            message = _find_message(table, thread["threadId"], str(item.get("messageId") or ""))
            if message and message.get("direction") != "out":
                board_meta_triage.on_message(table, settings, thread, message)
            if message:
                import board_meta_attachments

                board_meta_attachments.fetch_pending(table, thread, message)
    except Exception as exc:
        _log_event("warning", tag="board_meta_after_ingest_failed", error=str(exc)[:300])
    return {}


def _insert_conversations(table: Any, rows: list[dict[str, Any]], *, channel: str) -> int:
    import board_meta_ingest

    inserted = 0
    pseud = board_pii.Pseudonymizer(table)
    for row in rows[:_BACKFILL]:
        messages = ((row.get("messages") or {}).get("data") or []) if isinstance(row.get("messages"), dict) else []
        for raw in messages:
            if not isinstance(raw, dict):
                continue
            sender = str(((raw.get("from") or {}) if isinstance(raw.get("from"), dict) else {}).get("id") or "")
            msg = {
                "channel": channel,
                "threadKey": sender or str(row.get("id") or ""),
                "senderId": sender,
                "messageId": str(raw.get("id") or ""),
                "text": str(raw.get("message") or ""),
                "timestampMs": 0,
                "direction": "in",
                "source": "backfill",
                "attachments": [],
            }
            if msg["messageId"] and board_meta_ingest._store(table, pseud, msg, received_at=str(raw.get("created_time") or board_store.now_iso())):
                inserted += 1
    pseud.save()
    return inserted


def _messages(table: Any, thread_id: str) -> list[dict[str, Any]]:
    rows = board_store.list_meta_messages(table, thread_id)
    rows.sort(key=lambda row: str(row.get("receivedAt") or ""))
    return rows[-_MSG_MAX:]


def _find_message(table: Any, thread_id: str, message_id: str) -> dict[str, Any] | None:
    for row in board_store.list_meta_messages(table, thread_id):
        if str(row.get("messageId") or "") == message_id:
            return row
    return None


def _text(row: dict[str, Any]) -> str:
    if row.get("text"):
        return str(row.get("text"))
    return str(row.get("textMasked") or row.get("lastTextMasked") or "")


def _public_thread(thread: dict[str, Any], pseud: board_pii.Pseudonymizer) -> dict[str, Any]:
    return {
        "threadId": thread.get("threadId"),
        "channel": thread.get("channel"),
        "kind": thread.get("kind") or "message",
        "displayName": pseud.mask_text(str(thread.get("displayName") or "")) or "contact",
        "lastText": pseud.mask_text(_text(thread)),
        "lastTextMasked": pseud.mask_text(_text(thread)),
        "inWindow": board_meta._in_window(thread),
        "lastDirection": thread.get("lastDirection") or "in",
        "lastMessageAt": thread.get("lastMessageAt"),
        "unread": bool(thread.get("unread")),
        "messageCount": int(thread.get("messageCount") or 0),
        "prospectId": thread.get("prospectId") or "",
    }


def _public_message(row: dict[str, Any], pseud: board_pii.Pseudonymizer) -> dict[str, Any]:
    return {
        "messageId": row.get("messageId"),
        "receivedAt": row.get("receivedAt"),
        "direction": row.get("direction") or "in",
        "text": pseud.mask_text(_text(row)),
        "senderName": pseud.mask_text(str(row.get("senderName") or "")),
        "source": row.get("source") or "webhook",
        "attachments": [_attachment_public(item) for item in row.get("attachments") or [] if isinstance(item, dict)],
    }


def _attachment_public(item: dict[str, Any]) -> dict[str, Any]:
    return {"kind": item.get("kind") or "file", "mime": item.get("mime") or "", "name": item.get("name") or "", "stored": bool(item.get("key"))}


def _owner_thread(thread: dict[str, Any]) -> dict[str, Any]:
    shown = _public_thread(thread, _plain())
    shown["displayName"] = str(thread.get("displayName") or "")
    shown["phone"] = str(thread.get("phone") or "")
    shown["handle"] = str(thread.get("handle") or "")
    shown["lastText"] = _text(thread)
    shown["prospectId"] = thread.get("prospectId") or ""
    return shown


def _owner_message(row: dict[str, Any]) -> dict[str, Any]:
    shown = _public_message(row, _plain())
    shown["text"] = _text(row)
    shown["senderName"] = str(row.get("senderName") or "")
    return shown


def _mask_owner_thread(thread: dict[str, Any], mask: Any) -> dict[str, Any]:
    out = dict(thread)
    out["displayName"] = mask(str(thread.get("displayName") or ""))
    out["phone"] = mask(str(thread.get("phone") or ""))
    out["handle"] = mask(str(thread.get("handle") or ""))
    out["lastText"] = mask(str(thread.get("lastText") or ""))
    out["lastTextMasked"] = mask(str(thread.get("lastTextMasked") or thread.get("lastText") or ""))
    return out


def _mask_owner_message(row: dict[str, Any], mask: Any) -> dict[str, Any]:
    out = dict(row)
    out["text"] = mask(str(row.get("text") or ""))
    out["senderName"] = mask(str(row.get("senderName") or ""))
    out.pop("url", None)
    return out


class _plain:
    """Stand-in that leaves owner text unchanged. Not a pseudonymizer."""

    def mask_text(self, text: str) -> str:
        return text


def _limit(raw: Any, ceiling: int) -> int:
    try:
        value = int(raw or ceiling)
    except (TypeError, ValueError):
        value = ceiling
    return max(1, min(value, ceiling))
