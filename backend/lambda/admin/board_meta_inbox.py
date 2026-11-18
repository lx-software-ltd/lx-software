"""Read a Meta thread the way mail is read: full text in the store, aliases for staff and keys."""

from __future__ import annotations

import hashlib
import re
from typing import Any

import board_meta
import board_meta_store
import board_pii
import board_policy
import board_store
from contract_constants import BOARD_TOOLS_CONTRACT
from http_common import _log_event

_LIMITS = BOARD_TOOLS_CONTRACT["limits"]
_LIST_MAX = int(_LIMITS["metaThreadListMax"])
_MSG_MAX = int(_LIMITS["metaThreadMessagesMax"])


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
    shown = _public_thread(thread, pseud)
    messages = [_public_message(row, pseud, sender=shown["displayName"]) for row in _messages(ctx.table, thread_id)]
    pseud.save()
    return {"thread": shown, "messages": messages, "count": len(messages)}


def op_list_dms(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    return op_list_threads(ctx, {**args, "channel": "page"})


def op_list_whatsapp(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    return op_list_threads(ctx, {**args, "channel": "whatsapp"})


def record_outbound(ctx: Any, args: dict[str, Any], sent: dict[str, Any]) -> None:
    """Store a reply that an approval just sent, so the thread shows both directions."""
    if not sent.get("ok"):
        return
    thread = _sent_thread(ctx.table, args, sent)
    if not thread:
        return
    # A reply addressed by number can be the first row of its thread.
    number = board_meta._phone_digits(str(sent.get("to") or ""))
    writer = board_meta_store.Writer(ctx.table)
    writer.add(
        {
            "_threadId": thread["threadId"],
            "channel": thread.get("channel") or ("whatsapp" if number else "page"),
            "senderId": thread.get("senderId") or number or str(sent.get("recipientId") or ""),
            "phone": thread.get("phone") or number,
            "messageId": str(sent.get("messageId") or sent.get("commentId") or board_store.new_id()),
            "text": str(args.get("message") or args.get("template") or ""),
            "direction": "out",
            "source": "board",
        }
    )
    writer.flush()


def _sent_thread(table: Any, args: dict[str, Any], sent: dict[str, Any]) -> dict[str, Any] | None:
    thread_id = str(sent.get("threadId") or args.get("threadId") or "")
    if thread_id:
        return board_store.get_meta_thread(table, thread_id) or {"threadId": thread_id}
    comment = str(args.get("commentId") or "")
    for channel in ("page", "instagram") if comment else ():
        found = board_store.get_meta_thread(table, board_meta.thread_id_for(channel, f"comment:{comment}"))
        if found:
            return found
    return None


def organisation_hold(table: Any, args: dict[str, Any]) -> str | None:
    """A reply addressed by number or recipient id, not by thread, is held for an organisation too."""
    if str(args.get("threadId") or "").strip():
        return None
    ids = []
    if str(args.get("to") or "").strip():
        ids.append(board_meta.whatsapp_thread_id(str(args.get("to"))))
    recipient = str(args.get("recipientId") or "").strip()
    if recipient:
        ids.extend(board_meta.thread_id_for(channel, recipient) for channel in ("page", "instagram"))
    for thread_id in ids:
        thread = board_store.get_meta_thread(table, thread_id)
        if thread and str(thread.get("prospectId") or ""):
            return board_policy.ORGANISATION_REPLY_REASON
    return None


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


def media_ref(message_id: str, index: int) -> str:
    """URL-safe handle for one attachment. Message ids hold characters a path cannot carry."""
    return f"{hashlib.sha256(str(message_id).encode()).hexdigest()[:16]}-{index}"


def find_media(table: Any, thread_id: str, ref: str) -> tuple[dict[str, Any], int] | None:
    for row in board_store.list_meta_messages(table, thread_id):
        attachments = row.get("attachments") or []
        for index in range(len(attachments)):
            if media_ref(str(row.get("messageId") or ""), index) == ref and isinstance(attachments[index], dict):
                return row, index
    return None


def mark_read(table: Any, thread_id: str) -> dict[str, Any] | None:
    thread = board_store.get_meta_thread(table, thread_id)
    if not thread:
        return None
    thread["unread"] = False
    thread["unreadCount"] = 0
    thread["lastReadAt"] = board_store.now_iso()
    board_store.put_meta_thread(table, thread)
    return _owner_thread(thread)


def mask_public(body: dict[str, Any], rest: list[str]) -> tuple[dict[str, Any], bool]:
    """Mask a key read. Names, numbers, account ids and media are refused without the pii scope."""
    if "media" in rest:
        return {"message": "forbidden", "reason": "scope"}, True
    if isinstance(body.get("threads"), list):
        body["threads"] = [_mask_owner_thread(row) for row in body["threads"]]
    if isinstance(body.get("thread"), dict):
        body["thread"] = _mask_owner_thread(body["thread"])
    if isinstance(body.get("messages"), list):
        body["messages"] = [_mask_owner_message(row) for row in body["messages"]]
    if isinstance(body.get("whatsapp"), dict):
        body["whatsapp"] = {k: v for k, v in body["whatsapp"].items() if k not in _ACCOUNT_FIELDS}
    return body, False


_LONG_NUMBER = re.compile(r"(?<!\d)\d{8,15}(?!\d)")
_ACCOUNT_FIELDS = frozenset({"phoneNumberId", "wabaId", "displayPhoneNumber", "verifiedName"})


def _regex_mask(text: str) -> str:
    masked = board_pii.EMAIL_RE.sub("contact#hidden", board_pii.PHONE_RE.sub("phone#hidden", str(text or "")))
    return _LONG_NUMBER.sub("phone#hidden", masked)


def _hidden(value: Any, placeholder: str) -> str:
    return placeholder if str(value or "").strip() else ""


def status(table: Any) -> dict[str, Any]:
    import board_meta_whatsapp

    summary = board_meta.status_summary(table)
    summary["lastDelivery"] = {
        channel: ((board_store.get_cache(table, f"meta:webhook:{channel}") or {}).get("payload") or {}).get("at")
        for channel in ("page", "instagram", "whatsapp")
    }
    summary["whatsapp"] = board_meta_whatsapp.status(table)
    return summary


def handle_after_ingest(event: dict[str, Any]) -> dict[str, Any]:
    if not board_store.event_targets_this_board(event):
        return {}
    import board_meta_triage

    table = board_store.records_table()
    settings = board_store.load_settings(table)
    index = board_meta_triage.ProspectIndex(table)
    for item in event.get("items") or []:
        if not isinstance(item, dict):
            continue
        # One bad message must not stop the rest of the delivery.
        try:
            _after_one(table, settings, index, item)
        except Exception as exc:
            _log_event("warning", tag="board_meta_after_ingest_failed", threadId=str(item.get("threadId") or ""), error=str(exc)[:300])
    return {}


def _after_one(table: Any, settings: dict[str, Any], index: Any, item: dict[str, Any]) -> None:
    import board_meta_attachments
    import board_meta_profile
    import board_meta_triage

    thread = board_store.get_meta_thread(table, str(item.get("threadId") or ""))
    if not thread:
        return
    message = _find_message(table, thread["threadId"], str(item.get("messageId") or ""))
    if not message:
        return
    thread = board_meta_profile.fill_name(table, thread)
    if message.get("direction") != "out":
        board_meta_triage.on_message(table, settings, thread, message, index=index, route_customers=item.get("mode") == "live")
    if message.get("source") != "history":
        board_meta_attachments.fetch_pending(table, message)


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


def _alias(thread: dict[str, Any], pseud: Any) -> str:
    """Staff never see a contact's name. A WhatsApp sender shares the alias its number has in text."""
    sender = str(thread.get("senderId") or "")
    if not sender:
        return "contact"
    if thread.get("channel") == "whatsapp":
        return pseud.alias_for("phone", f"+{sender}")
    # "fb" is the namespace Page comment senders already use, so one person keeps one alias.
    namespace = "ig" if thread.get("channel") == "instagram" else "fb"
    return pseud.alias_for_external(namespace, sender, display=str(thread.get("displayName") or ""))


def _public_thread(thread: dict[str, Any], pseud: Any) -> dict[str, Any]:
    return {
        "threadId": thread.get("threadId"),
        "channel": thread.get("channel"),
        "kind": thread.get("kind") or "message",
        "displayName": _alias(thread, pseud),
        "lastText": pseud.mask_text(_text(thread)),
        "lastTextMasked": pseud.mask_text(_text(thread)),
        "inWindow": board_meta._in_window(thread),
        "lastDirection": thread.get("lastDirection") or "in",
        "lastMessageAt": thread.get("lastMessageAt"),
        "unread": bool(thread.get("unread")),
        "messageCount": int(thread.get("messageCount") or 0),
        "prospectId": thread.get("prospectId") or "",
    }


def _public_message(row: dict[str, Any], pseud: Any, *, sender: str = "") -> dict[str, Any]:
    return {
        "messageId": row.get("messageId"),
        "receivedAt": row.get("receivedAt"),
        "direction": row.get("direction") or "in",
        "text": pseud.mask_text(_text(row)),
        "senderName": sender if (row.get("direction") or "in") == "in" else "",
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
    return shown


def _owner_message(row: dict[str, Any]) -> dict[str, Any]:
    shown = _public_message(row, _plain())
    shown["text"] = _text(row)
    shown["senderName"] = str(row.get("senderName") or "")
    for index, item in enumerate(shown["attachments"]):
        item["ref"] = media_ref(str(row.get("messageId") or ""), index)
    return shown


def _mask_owner_thread(thread: dict[str, Any]) -> dict[str, Any]:
    out = dict(thread)
    out["displayName"] = _hidden(thread.get("displayName"), "contact#hidden")
    out["phone"] = _hidden(thread.get("phone"), "phone#hidden")
    out["handle"] = _hidden(thread.get("handle"), "contact#hidden")
    out["lastText"] = _regex_mask(str(thread.get("lastText") or ""))
    out["lastTextMasked"] = _regex_mask(str(thread.get("lastTextMasked") or thread.get("lastText") or ""))
    return out


def _mask_owner_message(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["text"] = _regex_mask(str(row.get("text") or ""))
    out["senderName"] = _hidden(row.get("senderName"), "contact#hidden")
    out["attachments"] = [{k: v for k, v in item.items() if k != "ref"} for item in row.get("attachments") or [] if isinstance(item, dict)]
    return out


class _plain:
    """Stand-in that leaves owner text unchanged. Not a pseudonymizer."""

    def mask_text(self, text: str) -> str:
        return text

    def alias_for(self, _kind: str, value: str) -> str:
        return value

    def alias_for_external(self, _namespace: str, external_id: str, *, display: str = "") -> str:
        return display or external_id


def _limit(raw: Any, ceiling: int) -> int:
    try:
        value = int(raw or ceiling)
    except (TypeError, ValueError):
        value = ceiling
    return max(1, min(value, ceiling))
