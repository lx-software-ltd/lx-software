"""Tool operations for the board family."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import board_actions
import board_store
from board_tools_core import (
    REASON_PARAM,
    ToolContext,
    ToolOp,
    _int_param,
    _obj,
    _short,
    _str_param,
    _summ,
)
from contract_constants import (
    BOARD_ACTION_EFFORTS,
    BOARD_ACTION_PRIORITIES,
    BOARD_ACTION_STATUSES,
)
from http_common import _utc_iso_z


def _board_list_actions(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    status = str(args.get("status") or "open").lower()
    persona = str(args.get("persona") or "").lower()
    items = board_store.list_actions(ctx.table)
    if status != "all":
        items = [a for a in items if a.get("status") == status]
    if persona:
        items = [a for a in items if a.get("persona") == persona]
    items.sort(key=board_actions._sort_key)
    return {
        "count": len(items),
        "items": [
            {
                "actionId": a.get("actionId"),
                "title": a.get("title"),
                "detail": str(a.get("detail") or "")[:300],
                "persona": a.get("persona"),
                "priority": a.get("priority"),
                "effort": a.get("effort"),
                "status": a.get("status"),
                "dueAt": a.get("dueAt"),
                "note": str(a.get("note") or "")[:300],
                "meetingId": a.get("meetingId"),
                "createdAt": a.get("createdAt"),
            }
            for a in items[:40]
        ],
    }

def _board_list_meetings(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        limit = min(max(1, int(args.get("limit") or 10)), 20)
    except (TypeError, ValueError):
        limit = 10
    out = []
    for m in board_store.list_meetings(ctx.table, limit=limit):
        minutes = m.get("minutes") if isinstance(m.get("minutes"), dict) else {}
        out.append(
            {
                "meetingId": m.get("meetingId"),
                "status": m.get("status"),
                "mode": m.get("mode"),
                "topic": m.get("topic") or "",
                "chair": m.get("chair"),
                "createdAt": m.get("createdAt"),
                "headline": minutes.get("headline") or "",
                "actionCount": len(minutes.get("actions") or []),
            }
        )
    return {"items": out}

def _board_get_minutes(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    meeting_id = str(args.get("meetingId") or "").strip()
    doc = None
    if meeting_id:
        doc = board_store.get_meeting(ctx.table, meeting_id)
    else:
        for m in board_store.list_meetings(ctx.table, limit=10):
            if m.get("status") == "succeeded" and isinstance(m.get("minutes"), dict):
                doc = m
                break
    if not doc:
        return {"error": "No minutes found" + (f" for meeting {meeting_id}" if meeting_id else "")}
    minutes = doc.get("minutes") if isinstance(doc.get("minutes"), dict) else None
    if not minutes:
        return {"error": f"Meeting {doc.get('meetingId')} has no minutes (status {doc.get('status')})"}
    return {
        "meetingId": doc.get("meetingId"),
        "createdAt": doc.get("createdAt"),
        "mode": doc.get("mode"),
        "topic": doc.get("topic") or "",
        "minutes": minutes,
    }

def _board_search_decisions(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    query = " ".join(str(args.get("query") or "").lower().split())
    entries = board_store.load_decision_log(ctx.table)
    words = [w for w in query.split() if w]
    if words:
        entries = [e for e in entries if all(w in str(e.get("text") or "").lower() for w in words)]
    return {"count": len(entries), "items": entries[-30:]}

def _board_add_action(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    title = " ".join(str(args.get("title") or "").split())[:120]
    if not title:
        return {"error": "title is required"}
    open_actions = [a for a in board_store.list_actions(ctx.table) if a.get("status") == "open"]
    match = board_actions.find_similar_open_action(title, open_actions)
    if match is not None:
        return {
            "ok": False,
            "duplicateOf": match.get("actionId"),
            "message": f"An open action already covers this: '{match.get('title')}' (id {match.get('actionId')}).",
        }
    priority = str(args.get("priority") or "next").lower()
    if priority not in BOARD_ACTION_PRIORITIES:
        priority = "next"
    effort = str(args.get("effort") or "M").upper()[:1]
    if effort not in BOARD_ACTION_EFFORTS:
        effort = "M"
    due_at = None
    try:
        due_days = int(args.get("dueInDays")) if args.get("dueInDays") is not None else None
    except (TypeError, ValueError):
        due_days = None
    now = datetime.now(timezone.utc)
    if due_days is not None and due_days > 0:
        due_at = _utc_iso_z(now + timedelta(days=min(due_days, 180)))
    doc = {
        "actionId": board_store.new_id(),
        "title": title,
        "detail": str(args.get("detail") or "").strip()[:800],
        "persona": ctx.persona_id,
        "priority": priority,
        "effort": effort,
        "metric": str(args.get("metric") or "").strip()[:300],
        "dependsOn": [],
        "status": "open",
        "note": "",
        "meetingId": ctx.meeting_id or "",
        "source": "tool" if ctx.actor == "persona" else "approval",
        "reaffirmedByMeetingIds": [],
        "dueAt": due_at,
        "createdAt": _utc_iso_z(now),
        "updatedAt": _utc_iso_z(now),
    }
    board_store.put_action(ctx.table, doc)
    return {"ok": True, "actionId": doc["actionId"], "title": title, "priority": priority}

def _board_update_action(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    action_id = str(args.get("actionId") or "").strip()
    doc = board_store.get_action(ctx.table, action_id) if action_id else None
    if not doc:
        return {"error": f"Action {action_id or '(missing id)'} not found"}
    if ctx.actor == "persona" and str(doc.get("persona") or "") != ctx.persona_id:
        return {"error": "You may only update actions you own; ask the owner to change others."}
    changed = False
    status = args.get("status")
    if isinstance(status, str) and status:
        if status not in BOARD_ACTION_STATUSES:
            return {"error": "status must be open, done or dismissed"}
        if status != doc.get("status"):
            doc["status"] = status
            doc["statusChangedAt"] = board_store.now_iso()
            changed = True
    priority = args.get("priority")
    if isinstance(priority, str) and priority:
        if priority not in BOARD_ACTION_PRIORITIES:
            return {"error": f"priority must be one of {', '.join(sorted(BOARD_ACTION_PRIORITIES))}"}
        if priority != doc.get("priority"):
            doc["priority"] = priority
            changed = True
    if args.get("dueInDays") is not None:
        try:
            due_days = int(args.get("dueInDays"))
        except (TypeError, ValueError):
            return {"error": "dueInDays must be a whole number of days"}
        # 0 clears the due date; otherwise re-anchor from today.
        doc["dueAt"] = _utc_iso_z(datetime.now(timezone.utc) + timedelta(days=min(due_days, 180))) if due_days > 0 else None
        changed = True
    note = args.get("note")
    if isinstance(note, str) and note.strip():
        stamp = f"[{ctx.display_name or ctx.persona_id}] {note.strip()[:600]}"
        existing = str(doc.get("note") or "").strip()
        doc["note"] = (existing + "\n" + stamp).strip()[:2000]
        changed = True
    if not changed:
        return {"ok": False, "message": "Nothing to change; pass status, priority, dueInDays and/or note."}
    doc["updatedAt"] = board_store.now_iso()
    doc["updatedBy"] = f"{ctx.actor}:{ctx.persona_id}"
    board_store.put_action(ctx.table, doc)
    return {
        "ok": True,
        "actionId": action_id,
        "status": doc.get("status"),
        "priority": doc.get("priority"),
        "dueAt": doc.get("dueAt"),
        "note": doc.get("note"),
    }

def _summ_update_action(args: dict[str, Any]) -> str:
    parts = []
    if args.get("status"):
        parts.append(f"status → {args['status']}")
    if args.get("priority"):
        parts.append(f"priority → {args['priority']}")
    if args.get("dueInDays") is not None:
        parts.append("due date cleared" if not args["dueInDays"] else f"due in {args['dueInDays']}d")
    if args.get("note"):
        parts.append("added a note")
    return f"Update action {_short(args.get('actionId'), 12)}: {', '.join(parts) or 'no change'}"

def ops() -> list[ToolOp]:
    return [
        ToolOp(
            name="board_list_actions",
            tool_id="board",
            kind="read",
            description="List the founder's action items with ids, owners, priorities and status.",
            parameters=_obj(
                {
                    "status": _str_param("open (default), done, dismissed or all.", enum=["open", "done", "dismissed", "all"]),
                    "persona": _str_param("Optional owner persona id (ceo, cfo, ...).", max_len=10),
                }
            ),
            run=_board_list_actions,
            summarize=_summ("Listed {status} actions"),
        ),
        ToolOp(
            name="board_list_meetings",
            tool_id="board",
            kind="read",
            description="List recent board meetings with their headlines.",
            parameters=_obj({"limit": _int_param("Max meetings (1-20).", maximum=20)}),
            run=_board_list_meetings,
            summarize=_summ("Listed recent meetings"),
        ),
        ToolOp(
            name="board_get_minutes",
            tool_id="board",
            kind="read",
            description="Read the full minutes of a meeting (latest successful meeting when meetingId is omitted).",
            parameters=_obj({"meetingId": _str_param("Optional meeting id.", max_len=64)}),
            run=_board_get_minutes,
            summarize=_summ("Read meeting minutes"),
        ),
        ToolOp(
            name="board_search_decisions",
            tool_id="board",
            kind="read",
            description="Search the board's decision log by keywords.",
            parameters=_obj({"query": _str_param("Keywords; all must match.", max_len=200)}),
            run=_board_search_decisions,
            summarize=_summ("Searched decisions for '{query}'"),
        ),
        ToolOp(
            name="board_add_action",
            tool_id="board",
            kind="write",
            description="Add one action item for the founder, owned by you. Check board_list_actions first; duplicates are rejected.",
            parameters=_obj(
                {
                    "title": _str_param("Imperative, <= 100 chars.", max_len=120),
                    "detail": _str_param("What done looks like.", max_len=800),
                    "priority": _str_param("now, next or later.", enum=list(BOARD_ACTION_PRIORITIES)),
                    "effort": _str_param("S, M or L.", enum=sorted(BOARD_ACTION_EFFORTS)),
                    "dueInDays": _int_param("Days until due (1-180).", maximum=180),
                    "metric": _str_param("How we know it worked.", max_len=300),
                    "reason": REASON_PARAM,
                },
                ["title", "detail", "priority", "reason"],
            ),
            run=_board_add_action,
            summarize=_summ("Add action: {title}"),
        ),
        ToolOp(
            name="board_update_action",
            tool_id="board",
            kind="write",
            description="Change the status, priority or due date of, or append a note to, an action item you own.",
            parameters=_obj(
                {
                    "actionId": _str_param("Action id from board_list_actions.", max_len=64),
                    "status": _str_param("open, done or dismissed.", enum=sorted(BOARD_ACTION_STATUSES)),
                    "priority": _str_param("Re-prioritise: now, next or later.", enum=sorted(BOARD_ACTION_PRIORITIES)),
                    "dueInDays": _int_param("New due date as days from today (0 clears it, max 180).", minimum=0, maximum=180),
                    "note": _str_param("Note to append.", max_len=600),
                    "reason": REASON_PARAM,
                },
                ["actionId", "reason"],
            ),
            run=_board_update_action,
            summarize=_summ_update_action,
        ),
    ]
