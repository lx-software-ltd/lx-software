"""Route an inbound Meta message. Organisation threads never get an automatic reply."""

from __future__ import annotations

from typing import Any

import board_prospects
import board_store
import board_triage
from contract_constants import BOARD_STAFF_PROSPECT_STAGES

_CATALOG_SEAT = "content-marketer"
_PAGE = 200
_NAME_MIN = 5
_STAGE_ORDER = ("listed", "onboarding", "replied", "contacted", "qualified", "parked", "unresponsive", "discovered", "declined", "suppressed")
_BEFORE_REPLIED = frozenset({"discovered", "qualified", "parked", "contacted", "unresponsive"})
_NO_TASK = frozenset({"declined", "suppressed"})


def on_message(
    table: Any,
    settings: dict[str, Any],
    thread: dict[str, Any],
    message: dict[str, Any],
    *,
    index: ProspectIndex | None = None,
    route_customers: bool = True,
) -> dict[str, Any] | None:
    """``route_customers`` is False for imported history: it is linked to an organisation and nothing else."""
    prospect = (index or ProspectIndex(table)).match(thread)
    if not prospect:
        return route_unmatched(table, settings, thread, message) if route_customers else None
    prospect = _mark_replied(table, prospect)
    prospect_id = str(prospect.get("prospectId") or "")
    if str(thread.get("prospectId") or "") != prospect_id:
        thread = {**(board_store.get_meta_thread(table, str(thread.get("threadId") or "")) or thread), "prospectId": prospect_id}
        board_store.put_meta_thread(table, thread)
    return _catalog_task(table, settings, thread, prospect, message)


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


class ProspectIndex:
    """Every prospect, read once per delivery, keyed by phone number and by name."""

    def __init__(self, table: Any) -> None:
        self.table = table
        self._phones: dict[str, dict[str, Any]] | None = None
        self._names: dict[str, dict[str, Any]] = {}

    def match(self, thread: dict[str, Any]) -> dict[str, Any] | None:
        if self._phones is None:
            self._load()
        phone = str(thread.get("phone") or "")
        if not phone and thread.get("channel") == "whatsapp":
            phone = str(thread.get("senderId") or "")
        found = (self._phones or {}).get(board_prospects.e164_phone(phone)) if phone else None
        # Page and Instagram senders carry no phone number. An exact name is the only link.
        return found or self._names.get(_name_key(str(thread.get("displayName") or "")))

    def _load(self) -> None:
        self._phones = {}
        for stage in sorted(BOARD_STAFF_PROSPECT_STAGES, key=_stage_rank):
            cursor: str | None = None
            while True:
                rows, cursor = board_store.list_prospects_page(self.table, stage, limit=_PAGE, cursor=cursor)
                for prospect in rows:
                    phone = board_prospects.e164_phone(str(prospect.get("phone") or ""))
                    if phone:
                        self._phones.setdefault(phone, prospect)
                    name = _name_key(str(prospect.get("name") or ""))
                    if name:
                        self._names.setdefault(name, prospect)
                if not cursor:
                    break


def _stage_rank(stage: str) -> int:
    """When two prospects share a number, the one further along wins."""
    return _STAGE_ORDER.index(stage) if stage in _STAGE_ORDER else len(_STAGE_ORDER)


def _name_key(name: str) -> str:
    key = "".join(ch for ch in name.casefold() if ch.isalnum())
    return key if len(key) >= _NAME_MIN else ""


def _mark_replied(table: Any, prospect: dict[str, Any]) -> dict[str, Any]:
    """Move forward to ``replied``. A prospect already past it, declined or suppressed keeps its stage."""
    current = board_store.get_prospect(table, str(prospect.get("prospectId") or "")) or prospect
    if current.get("stage") not in _BEFORE_REPLIED:
        return current
    current["stage"] = "replied"
    current["repliedAt"] = board_store.now_iso()
    current["updatedAt"] = current["repliedAt"]
    board_store.put_prospect(table, current)
    return current


def _catalog_task(table: Any, settings: dict[str, Any], thread: dict[str, Any], prospect: dict[str, Any], message: dict[str, Any]) -> dict[str, Any] | None:
    """One catalog task. No acknowledgement: the owner replies by hand."""
    import board_staff

    if not board_staff.enabled(settings) or prospect.get("stage") in _NO_TASK:
        return None
    event_id = str(thread.get("threadId") or "")
    existing = board_triage.find_open_event_task(table, "meta-catalog", event_id)
    if existing:
        note = str(message.get("textMasked") or "")[:800] or "(no text)"
        if message.get("attachments"):
            note += f" [{len(message['attachments'])} attachment(s)]"
        return board_staff.append_event_note(table, existing, f"NEW MESSAGE: {note}")
    roster = board_staff.seats_by_id(table, settings)
    assignee = _CATALOG_SEAT if (roster.get(_CATALOG_SEAT) or {}).get("isActive") else "cmo"
    name = str(prospect.get("name") or "the organisation")
    return board_staff.create_task(
        table,
        settings,
        assignee=assignee,
        origin="event",
        brief=f"Put the schedule from {name} into the catalog. Read thread {event_id} with meta_get_thread.",
        deliverable_type="json",
        sla_hours=24,
        event_ref={"kind": "meta-catalog", "id": event_id, "channel": str(thread.get("channel") or "whatsapp")},
        created_by="triage:meta-catalog",
        status="queued",
    )
