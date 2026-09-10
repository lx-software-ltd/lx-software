"""Executive Board: action items handed to the founder."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import board_store
from contract_constants import BOARD_ACTION_STATUSES, BOARD_MAX_ACTION_NOTE_LEN
from http_common import _audit, _json_response, _parse_json_body, _utc_iso_z

_WORD_RE = re.compile(r"[a-z0-9]+")
SIMILARITY_THRESHOLD = 0.8


def handle_actions_get(event: dict[str, Any]) -> dict[str, Any]:
    from urllib.parse import parse_qs

    table = board_store.records_table()
    qs = parse_qs(event.get("rawQueryString") or "")
    status = (qs.get("status") or [""])[0].strip().lower()
    persona = (qs.get("persona") or [""])[0].strip().lower()
    meeting_id = (qs.get("meetingId") or [""])[0].strip()
    items = board_store.list_actions(table)
    if status and status in BOARD_ACTION_STATUSES:
        items = [a for a in items if a.get("status") == status]
    if persona:
        items = [a for a in items if a.get("persona") == persona]
    if meeting_id:
        items = [a for a in items if a.get("meetingId") == meeting_id]
    items.sort(key=_sort_key)
    return _json_response(200, {"actions": items})


def handle_action_put(event: dict[str, Any], action_id: str, user_sub: str | None) -> dict[str, Any]:
    table = board_store.records_table()
    doc = board_store.get_action(table, action_id)
    if not doc:
        return _json_response(404, {"message": "Action not found"})
    body = _parse_json_body(event)
    changed = False
    status = body.get("status")
    if status is not None:
        if not isinstance(status, str) or status not in BOARD_ACTION_STATUSES:
            return _json_response(400, {"message": "status must be open, done or dismissed"})
        if status != doc.get("status"):
            doc["status"] = status
            doc["statusChangedAt"] = board_store.now_iso()
            changed = True
    note = body.get("note")
    if note is not None:
        if not isinstance(note, str):
            return _json_response(400, {"message": "note must be a string"})
        if len(note) > BOARD_MAX_ACTION_NOTE_LEN:
            return _json_response(
                400, {"message": f"note must be at most {BOARD_MAX_ACTION_NOTE_LEN} characters"}
            )
        doc["note"] = note.strip()
        changed = True
    if changed:
        doc["updatedAt"] = board_store.now_iso()
        doc["updatedBySub"] = user_sub or ""
        board_store.put_action(table, doc)
        _audit(user_sub, "BOARD_ACTION_UPDATE", action_id, event)
    return _json_response(200, {"action": doc})


def create_actions_from_minutes(
    table: Any, *, minutes: dict[str, Any], meeting_id: str
) -> tuple[list[str], list[str]]:
    """Persist minutes actions, skipping ones that duplicate an open action.

    Returns ``(created_ids, reaffirmed_ids)``.
    """
    existing = board_store.list_actions(table)
    open_actions = [a for a in existing if a.get("status") == "open"]
    open_by_id = {str(a.get("actionId")): a for a in open_actions}
    created: list[str] = []
    reaffirmed: list[str] = []
    now = datetime.now(timezone.utc)
    seen_titles: list[str] = []
    for proposal in minutes.get("actions") or []:
        if not isinstance(proposal, dict):
            continue
        title = str(proposal.get("title") or "").strip()
        if not title:
            continue
        existing_id = proposal.get("existingActionId")
        if isinstance(existing_id, str) and existing_id in open_by_id:
            _reaffirm(table, open_by_id[existing_id], meeting_id, proposal)
            reaffirmed.append(existing_id)
            continue
        match = find_similar_open_action(title, open_actions)
        if match is not None:
            _reaffirm(table, match, meeting_id, proposal)
            reaffirmed.append(str(match.get("actionId")))
            continue
        if any(similarity(title, t) >= SIMILARITY_THRESHOLD for t in seen_titles):
            continue
        seen_titles.append(title)
        due_days = proposal.get("dueInDays")
        due_at = (
            _utc_iso_z(now + timedelta(days=int(due_days)))
            if isinstance(due_days, int) and due_days > 0
            else None
        )
        doc = {
            "actionId": board_store.new_id(),
            "title": title[:120],
            "detail": str(proposal.get("detail") or "")[:800],
            "persona": str(proposal.get("persona") or ""),
            "assignee": str(proposal.get("assignee") or ""),
            "priority": str(proposal.get("priority") or "next"),
            "effort": str(proposal.get("effort") or "M"),
            "metric": str(proposal.get("metric") or "")[:300],
            "dependsOn": list(proposal.get("dependsOn") or [])[:5],
            "status": "open",
            "note": "",
            "meetingId": meeting_id,
            "reaffirmedByMeetingIds": [],
            "dueAt": due_at,
            "createdAt": _utc_iso_z(now),
            "updatedAt": _utc_iso_z(now),
        }
        board_store.put_action(table, doc)
        created.append(doc["actionId"])
    return created, reaffirmed


def _reaffirm(table: Any, action: dict[str, Any], meeting_id: str, proposal: dict[str, Any]) -> None:
    ids = list(action.get("reaffirmedByMeetingIds") or [])
    if meeting_id not in ids:
        ids.append(meeting_id)
    updated = {**action, "reaffirmedByMeetingIds": ids[-20:], "updatedAt": board_store.now_iso()}
    priority = proposal.get("priority")
    if priority in ("now", "next", "later"):
        updated["priority"] = priority
    board_store.put_action(table, updated)


def normalize_title(title: str) -> str:
    return " ".join(_WORD_RE.findall(str(title or "").lower()))


def similarity(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    sa, sb = set(na.split()), set(nb.split())
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


def find_similar_open_action(title: str, open_actions: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = 0.0
    for a in open_actions:
        score = similarity(title, str(a.get("title") or ""))
        if score >= SIMILARITY_THRESHOLD and score > best_score:
            best, best_score = a, score
    return best


def _sort_key(a: dict[str, Any]) -> tuple[int, int, str]:
    status_rank = {"open": 0, "done": 1, "dismissed": 2}.get(str(a.get("status")), 3)
    priority_rank = {"now": 0, "next": 1, "later": 2}.get(str(a.get("priority")), 3)
    return (status_rank, priority_rank, str(a.get("createdAt") or ""))
