"""Route an inbound Meta message. Organisation threads never get an automatic reply."""

from __future__ import annotations

from typing import Any

import board_prospects
import board_store
import board_triage

_CATALOG_SEAT = "content-marketer"


def on_message(table: Any, settings: dict[str, Any], thread: dict[str, Any], message: dict[str, Any]) -> dict[str, Any] | None:
    prospect = _match_prospect(table, thread, message)
    if prospect:
        _mark_replied(table, prospect)
        thread = {**thread, "prospectId": str(prospect.get("prospectId") or "")}
        board_store.put_meta_thread(table, thread)
        return _catalog_task(table, settings, thread, prospect)
    return route_unmatched(table, settings, thread, message)


def route_unmatched(table: Any, settings: dict[str, Any], thread: dict[str, Any], message: dict[str, Any]) -> dict[str, Any] | None:
    if not board_triage.board_staff.enabled(settings):
        return None
    text = str(message.get("textMasked") or message.get("text") or thread.get("lastTextMasked") or "")
    channel = str(message.get("channel") or thread.get("channel") or "meta")
    classified = board_triage.classify_text(table, settings, text, channel=channel, sender=str(message.get("senderId") or ""))
    assignee, sla = board_triage._route_meta(thread, message, classified)
    brief = board_triage.render_event_brief("meta", thread, message, classified)
    op = "meta_reply_whatsapp" if channel == "whatsapp" else "meta_reply_dm"
    if str(thread.get("kind") or message.get("kind") or "") == "comment":
        op = "meta_reply_comment"
    return board_triage._open_or_append(
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
            "commentId": str(message.get("messageId") or ""),
            "message": "",
            "reason": "escalation acknowledgement",
        },
        text=text,
        reply_op=op,
    )


def _match_prospect(table: Any, thread: dict[str, Any], message: dict[str, Any]) -> dict[str, Any] | None:
    phone = str(thread.get("phone") or "")
    if str(thread.get("channel") or message.get("channel") or "") == "whatsapp":
        phone = phone or str(thread.get("senderId") or message.get("senderId") or "")
    want = board_prospects.e164_phone(phone)
    sender = str(thread.get("senderId") or "")
    if not want and not sender:
        return None
    for prospect in board_store.list_prospects(table, limit=200):
        if want and board_prospects.e164_phone(str(prospect.get("phone") or "")) == want:
            return prospect
        if sender and sender in {str(prospect.get("pageSenderId") or ""), str(prospect.get("instagramId") or "")}:
            return prospect
    return None


def _mark_replied(table: Any, prospect: dict[str, Any]) -> None:
    if prospect.get("stage") == "replied" and prospect.get("repliedAt"):
        return
    prospect["stage"] = "replied"
    prospect["repliedAt"] = board_store.now_iso()
    prospect["updatedAt"] = prospect["repliedAt"]
    board_store.put_prospect(table, prospect)


def _catalog_task(table: Any, settings: dict[str, Any], thread: dict[str, Any], prospect: dict[str, Any]) -> dict[str, Any] | None:
    """One catalog task. No acknowledgement: the owner replies by hand."""
    import board_staff

    event_id = str(thread.get("threadId") or "")
    existing = board_triage.find_open_event_task(table, "meta-catalog", event_id)
    if existing:
        return existing
    roster = board_staff.seats_by_id(table, settings)
    assignee = _CATALOG_SEAT if (roster.get(_CATALOG_SEAT) or {}).get("isActive") else "cmo"
    name = str(prospect.get("name") or "the organisation")
    return board_staff.create_task(
        table,
        settings,
        assignee=assignee,
        origin="event",
        brief=f"Put the schedule from {name} into the catalog. Thread {event_id}.",
        deliverable_type="messages",
        sla_hours=24,
        event_ref={"kind": "meta-catalog", "id": event_id, "channel": str(thread.get("channel") or "whatsapp")},
        created_by="triage:meta-catalog",
        status="queued",
    )
