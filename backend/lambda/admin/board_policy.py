"""Reply-policy checks enforced on write ops (not only in the prompt)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import board_hk
import board_store

REPLY_OPS = frozenset(
    {
        "mail_reply",
        "meta_reply_comment",
        "meta_reply_dm",
        "meta_reply_whatsapp",
        "stores_reply_review",
    }
)

PROMISE_RE = re.compile(
    r"(?i)(\bguarantee\b|we will hold the place|refund\s+(of\s+)?[\$£€]|HK\$\s*\d|退款\s*\d|保證|我们会预留|我們會預留)"
)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\-\s]{7,14}\d)(?!\w)")


def is_quiet_now(settings: dict[str, Any], now: datetime | None = None) -> bool:
    hours = ((settings.get("boundaries") or {}).get("reply") or {}).get("quietHoursHkt") or [22, 8]
    try:
        start, end = int(hours[0]), int(hours[1])
    except (TypeError, ValueError, IndexError):
        start, end = 22, 8
    return board_hk.in_quiet_hours(now or datetime.now(timezone.utc), start, end)


def channel_for_op(op_name: str) -> str:
    if op_name == "mail_reply":
        return "mail"
    if op_name == "meta_reply_whatsapp":
        return "whatsapp"
    if op_name == "stores_reply_review":
        return "stores"
    if op_name.startswith("meta_"):
        return "meta"
    return "mail"


def check_reply(settings: dict[str, Any], ctx: Any, op: Any, args: dict[str, Any], thread: dict[str, Any] | None) -> str | None:
    """Return a reason to downgrade to Approval, or None to continue (including quiet-hour holds)."""
    if op.name not in REPLY_OPS:
        return None
    # Quiet hours: hold to 08:00 rather than refuse (see board_holds.maybe_hold).
    body = str(args.get("body") or args.get("message") or "")
    if PROMISE_RE.search(body):
        return "the draft promises a refund, a guarantee, or to hold a place"
    allowed_contacts = _allowed_contacts(thread, args)
    for match in EMAIL_RE.findall(body):
        if match.lower() not in allowed_contacts:
            return "the draft includes an email address that is not the recipient's"
    for match in PHONE_RE.findall(body):
        compact = re.sub(r"\D", "", match)
        if compact and compact not in allowed_contacts:
            return "the draft includes a phone number that is not the recipient's"
    reply = (settings.get("boundaries") or {}).get("reply") or {}
    sensitive = {str(x) for x in (reply.get("sensitiveTemplatesOnly") or [])}
    intent = str((thread or {}).get("intent") or args.get("intent") or "")
    template_id = str(args.get("templateId") or "")
    if intent in sensitive and not template_id:
        return f"intent '{intent}' may only be sent with an approved template"
    if _thread_over_cap(thread, reply):
        return "this thread has already reached the daily reply limit"
    channel = channel_for_op(op.name)
    if _channel_over_cap(ctx.table, reply, channel):
        return f"the {channel} channel has already reached the daily reply limit"
    return None


def record_reply(table: Any, op_name: str, args: dict[str, Any]) -> None:
    channel = channel_for_op(op_name)
    try:
        board_store.add_external_usage_day(table, f"reply:{channel}")
    except ValueError:
        board_store.add_external_usage_day(table, f"reply{channel[:1].upper()}{channel[1:]}")
    thread_id = str(args.get("threadId") or "")
    if not thread_id or op_name != "mail_reply":
        return
    thread = board_store.get_mail_thread(table, thread_id)
    if not thread:
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if str(thread.get("repliesDate") or "") != today:
        thread["repliesToday"] = 0
        thread["repliesDate"] = today
    thread["repliesToday"] = int(thread.get("repliesToday") or 0) + 1
    board_store.put_mail_thread(table, thread)


def _allowed_contacts(thread: dict[str, Any] | None, args: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for key in ("to", "recipientId", "contact"):
        raw = args.get(key)
        if isinstance(raw, list):
            out.update(str(x).lower() for x in raw if x)
        elif raw:
            out.add(str(raw).lower())
            out.add(re.sub(r"\D", "", str(raw)))
    if thread:
        for key in ("lastFrom", "mailbox"):
            val = str(thread.get(key) or "").lower()
            if val:
                out.add(val)
        for part in thread.get("participants") or []:
            out.add(str(part).lower())
            out.add(re.sub(r"\D", "", str(part)))
    return {x for x in out if x}


def _thread_over_cap(thread: dict[str, Any] | None, reply: dict[str, Any]) -> bool:
    if not thread:
        return False
    cap = int(reply.get("maxMessagesPerThreadPerDay") or 3)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if str(thread.get("repliesDate") or "") != today:
        return False
    return int(thread.get("repliesToday") or 0) >= cap


def _channel_over_cap(table: Any, reply: dict[str, Any], channel: str) -> bool:
    caps = reply.get("maxOutboundPerChannelPerDay") or {}
    try:
        cap = int(caps.get(channel) or 0)
    except (TypeError, ValueError):
        cap = 0
    if cap <= 0:
        return False
    usage = board_store.load_external_usage_day(table)
    used = int(usage.get(f"reply:{channel}") or usage.get(f"reply{channel[:1].upper()}{channel[1:]}") or 0)
    return used >= cap
