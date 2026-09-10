"""Create staff tasks from inbound mail, Meta events and store reviews."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from typing import Any

import board_budget
import board_hk
import board_mail
import board_personas
import board_policy
import board_staff
import board_store
import board_templates
import board_tools
from http_common import _log_event

AUDIENCES = ("parent", "provider", "vendor", "unknown")
INTENTS = ("question", "booking", "complaint", "billing", "partnership", "spam", "other")
OPEN_TASK_STATUSES = ("queued", "running", "review", "returned", "needs_owner")
FINANCE_LOCAL_PARTS = frozenset({"finance", "billing"})
LATIN_WORD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 '\-]{0,80}$")


def on_mail_ingested(
    table: Any,
    settings: dict[str, Any],
    thread: dict[str, Any],
    message: dict[str, Any],
    *,
    deadline: float | None = None,
) -> dict[str, Any] | None:
    if not board_staff.enabled(settings):
        return None
    if str(message.get("direction") or "") not in ("in", "inbound"):
        return None
    if message.get("skipTriage") or message.get("bulk"):
        return None
    sender = str((message.get("from") or {}).get("address") or message.get("from") or "")
    if sender and board_mail._is_own(sender):  # noqa: SLF001 - same-domain outbound copies
        return None
    text = str(message.get("text") or thread.get("snippet") or "")
    classified = classify_text(table, settings, text, channel="mail", sender=sender, deadline=deadline)
    thread["intent"] = classified.get("intent")
    thread["audience"] = classified.get("audience")
    board_store.put_mail_thread(table, thread)
    assignee, sla = _route_mail(thread, message, classified)
    brief = render_event_brief("mail", thread, message, classified)
    return _open_or_append(
        table,
        settings,
        kind="mail",
        event_id=str(thread.get("threadId") or message.get("threadId") or ""),
        assignee=assignee,
        brief=brief,
        sla_hours=sla,
        escalate=bool(classified.get("escalate")),
        channel="mail",
        reply_args={"threadId": str(thread.get("threadId") or ""), "body": "", "reason": "escalation acknowledgement"},
        text=text,
    )


def on_meta_event(table: Any, settings: dict[str, Any], thread: dict[str, Any], msg: dict[str, Any]) -> dict[str, Any] | None:
    if not board_staff.enabled(settings):
        return None
    text = str(msg.get("text") or thread.get("lastTextMasked") or "")
    channel = str(msg.get("channel") or thread.get("channel") or "meta")
    classified = classify_text(table, settings, text, channel=channel, sender=str(msg.get("senderId") or ""))
    assignee, sla = _route_meta(thread, msg, classified)
    brief = render_event_brief("meta", thread, msg, classified)
    op = "meta_reply_whatsapp" if channel == "whatsapp" else "meta_reply_dm"
    if str(thread.get("kind") or msg.get("kind") or "") == "comment":
        op = "meta_reply_comment"
    return _open_or_append(
        table,
        settings,
        kind="meta",
        event_id=str(thread.get("threadId") or ""),
        assignee=assignee,
        brief=brief,
        sla_hours=sla,
        escalate=bool(classified.get("escalate")),
        channel=channel,
        reply_args={
            "threadId": str(thread.get("threadId") or ""),
            "commentId": str(msg.get("messageId") or ""),
            "message": "",
            "reason": "escalation acknowledgement",
        },
        text=text,
        reply_op=op,
    )


def on_store_reviews(table: Any, settings: dict[str, Any], new_reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not board_staff.enabled(settings) or not new_reviews:
        return []
    created: list[dict[str, Any]] = []
    for review in new_reviews:
        review_id = str(review.get("reviewId") or review.get("id") or "")
        if not review_id:
            continue
        text = str(review.get("text") or review.get("body") or review.get("title") or "")
        classified = classify_text(table, settings, text, channel="stores", sender="")
        brief = render_event_brief("review", review, review, classified)
        task = _open_or_append(
            table,
            settings,
            kind="review",
            event_id=review_id,
            assignee="community-manager",
            brief=brief,
            sla_hours=24,
            escalate=bool(classified.get("escalate")),
            channel="stores",
            reply_args={
                "store": str(review.get("store") or "apple"),
                "reviewId": review_id,
                "message": "",
                "reason": "escalation acknowledgement",
            },
            text=text,
            reply_op="stores_reply_review",
        )
        if task:
            created.append(task)
    return created


def classify_text(
    table: Any,
    settings: dict[str, Any],
    text: str,
    *,
    channel: str,
    sender: str = "",
    deadline: float | None = None,
) -> dict[str, Any]:
    keywords = ((settings.get("boundaries") or {}).get("escalation") or {}).get("keywords") or []
    escalate, reason = _keyword_hit(text, keywords)
    audience = "unknown"
    if sender and _prospect_for_sender(table, sender):
        audience = "provider"
    digest = hashlib.sha256(f"{channel}\n{text}".encode("utf-8")).hexdigest()[:32]
    cached = board_store.get_cache(table, f"triage:{digest}")
    if cached and isinstance(cached.get("payload"), dict):
        payload = dict(cached["payload"])
        if escalate:
            payload["escalate"] = True
            payload["reason"] = reason or payload.get("reason") or "keyword"
        return payload
    if escalate and audience != "unknown":
        return {"audience": audience, "intent": "complaint", "escalate": True, "reason": reason}
    if escalate:
        return {"audience": audience or "unknown", "intent": "complaint", "escalate": True, "reason": reason}
    if audience == "unknown" and _seconds_left(deadline) >= 20:
        try:
            model = board_budget.model_for("standup", settings)
            completion = board_budget.board_completion(
                table=table,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Classify the inbound message. Reply with JSON only: "
                            '{"audience":"parent|provider|vendor|unknown","intent":'
                            '"question|booking|complaint|billing|partnership|spam|other",'
                            '"escalate":false,"reason":""}'
                        ),
                    },
                    {"role": "user", "content": text[:4000] or "(empty)"},
                ],
                model=model,
                timeout=12,
                json_mode=True,
                temperature=0,
                max_tokens=200,
                tag="board_triage",
            )
            parsed = json.loads(completion.text or "{}")
            if parsed.get("audience") in AUDIENCES:
                audience = parsed["audience"]
            intent = parsed.get("intent") if parsed.get("intent") in INTENTS else "other"
            if parsed.get("escalate"):
                escalate = True
                reason = str(parsed.get("reason") or reason or "model")
            result = {"audience": audience, "intent": intent, "escalate": escalate, "reason": reason}
            board_store.put_cache(table, f"triage:{digest}", result, ttl_seconds=7 * 86400)
            return result
        except Exception as exc:
            _log_event("warning", tag="board_triage_classify_failed", error=str(exc)[:200])
            return {"audience": "unknown", "intent": "other", "escalate": True, "reason": "classifier failed"}
    if audience == "unknown" and _seconds_left(deadline) < 20:
        escalate = True
        reason = reason or "no time to classify"
    return {"audience": audience, "intent": "other", "escalate": escalate, "reason": reason}


def render_event_brief(kind: str, source: dict[str, Any], message: dict[str, Any], classified: dict[str, Any]) -> str:
    if kind == "mail":
        subject = str(source.get("subject") or message.get("subject") or "(no subject)")
        return f"Reply to inbound email «{subject}». Audience={classified.get('audience')}; intent={classified.get('intent')}."
    if kind == "review":
        stars = source.get("rating") or source.get("stars") or ""
        return f"Reply to a {stars}-star store review. Intent={classified.get('intent')}."
    channel = str(message.get("channel") or source.get("channel") or "meta")
    return f"Reply to inbound {channel} message. Audience={classified.get('audience')}; intent={classified.get('intent')}."


def _keyword_hit(text: str, keywords: list[Any]) -> tuple[bool, str]:
    blob = text or ""
    lower = blob.lower()
    for raw in keywords:
        word = str(raw or "").strip()
        if not word:
            continue
        if any("\u4e00" <= ch <= "\u9fff" for ch in word):
            if word in blob:
                return True, f"keyword:{word}"
            continue
        if LATIN_WORD_RE.match(word):
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", lower, re.I):
                return True, f"keyword:{word}"
        elif word.lower() in lower:
            return True, f"keyword:{word}"
    return False, ""


def _prospect_for_sender(table: Any, sender: str) -> dict[str, Any] | None:
    addr = sender.strip().lower()
    if not addr:
        return None
    pid = board_store.get_prospect_by_dedupe(table, addr)
    if not pid and "@" in addr:
        pid = board_store.get_prospect_by_dedupe(table, addr.split("@", 1)[1])
    if not pid:
        return None
    return board_store.get_prospect(table, pid)


def _route_mail(thread: dict[str, Any], message: dict[str, Any], classified: dict[str, Any]) -> tuple[str, int]:
    mailbox = str(thread.get("mailbox") or message.get("mailbox") or "").lower()
    local = mailbox.split("@", 1)[0]
    if local in FINANCE_LOCAL_PARTS:
        return "accountant", _sla_mail()
    if classified.get("intent") == "spam":
        return "security-analyst", _sla_mail()
    if classified.get("audience") == "provider":
        return "provider-success", _sla_mail()
    return "support", _sla_mail()


def _route_meta(thread: dict[str, Any], msg: dict[str, Any], classified: dict[str, Any]) -> tuple[str, int]:
    channel = str(msg.get("channel") or thread.get("channel") or "")
    kind = str(msg.get("kind") or thread.get("kind") or "")
    if kind == "lead" or classified.get("intent") == "partnership":
        return "provider-success", 2
    if channel == "whatsapp":
        return "support", 2
    return "community-manager", 2


def _sla_mail() -> int:
    local = board_hk.as_hkt(datetime.now(timezone.utc))
    if local.weekday() < 5 and 9 <= local.hour < 18:
        return 4
    return 12


def _seconds_left(deadline: float | None) -> float:
    if not deadline:
        return 60.0
    return max(0.0, deadline - time.monotonic())


def _open_or_append(
    table: Any,
    settings: dict[str, Any],
    *,
    kind: str,
    event_id: str,
    assignee: str,
    brief: str,
    sla_hours: int,
    escalate: bool,
    channel: str,
    reply_args: dict[str, Any],
    text: str,
    reply_op: str = "mail_reply",
) -> dict[str, Any] | None:
    if not event_id:
        return None
    existing = find_open_event_task(table, kind, event_id)
    if existing:
        board_staff.append_event_note(table, existing, f"NEW MESSAGE: {text[:800]}")
        return existing
    roster = board_staff.seats_by_id(table, settings)
    seat = roster.get(assignee) or {}
    if assignee not in roster or not seat.get("isActive"):
        escalate = True
        assignee = "support" if (roster.get("support") or {}).get("isActive") else "coo"
    status = "needs_owner" if escalate else "queued"
    task = board_staff.create_task(
        table,
        settings,
        assignee=assignee,
        origin="event",
        brief=brief,
        deliverable_type="messages",
        sla_hours=sla_hours,
        event_ref={"kind": kind, "id": event_id, "channel": channel},
        created_by=f"triage:{kind}",
        status=status,
    )
    if escalate:
        _send_ack(table, settings, task, reply_op, reply_args, text)
        try:
            import board_breakers

            board_breakers.note_escalation_after_reply(
                table,
                channel=channel,
                thread_id=str((reply_args or {}).get("threadId") or (reply_args or {}).get("reviewId") or event_id),
            )
        except Exception as exc:
            _log_event("warning", tag="board_breaker_channel_failed", error=str(exc)[:200])
    return task


def find_open_event_task(table: Any, kind: str, event_id: str) -> dict[str, Any] | None:
    for status in OPEN_TASK_STATUSES:
        for task in board_store.list_tasks(table, status):
            ref = task.get("eventRef") or {}
            if ref.get("kind") == kind and str(ref.get("id") or "") == event_id:
                return task
    return None


def _send_ack(
    table: Any,
    settings: dict[str, Any],
    task: dict[str, Any],
    op_name: str,
    args: dict[str, Any],
    text: str,
) -> None:
    op = board_tools.REGISTRY.get(op_name)
    if op is None:
        return
    lang = board_templates.pick_lang(text)
    body = board_templates.render("ack_escalation", lang)
    payload = dict(args)
    if "body" in payload:
        payload["body"] = body
    if "message" in payload:
        payload["message"] = body
    payload["templateId"] = "ack_escalation"
    payload.setdefault("reason", "escalation acknowledgement")
    manager = str(task.get("managerId") or "coo")
    display = next((p.get("shortName") or manager for p in board_personas.effective_roster({}) if p["id"] == manager), manager)
    ctx = board_tools.ToolContext(
        table=table,
        settings=settings,
        persona_id=manager,
        display_name=str(display),
        kind="task",
        actor="persona",
        task_id=str(task.get("taskId") or ""),
        seat_id=str(task.get("assignee") or ""),
    )
    try:
        board_tools.execute_call(ctx, op, payload)
    except Exception as exc:
        _log_event("warning", tag="board_triage_ack_failed", error=str(exc)[:200], op=op_name)
