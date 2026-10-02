"""Staff help requests and child tasks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import board_async
import board_personas
import board_store
import board_tools
from board_tools_core import ToolContext, allows, effective_level
from contract_constants import (
    BOARD_KEY,
    BOARD_STAFF_MAX_HELP_REQUESTS_PER_TASK,
    BOARD_STAFF_WAITING_EXPIRY_HOURS,
    BOARD_TOOL_IDS,
)
from http_common import _log_event, _utc_iso_z


def _help_finish_blocked(table: Any, task: dict[str, Any], deliverable: str) -> bool:
    """Refuse a 'help is in flight' memo while help is still open or the last ask failed."""
    from board_staff import _HELP_IN_FLIGHT_RE, TERMINAL_STATUSES
    if not _HELP_IN_FLIGHT_RE.search(deliverable or ""):
        return False
    if task.get("blockedOn"):
        return True
    for hid in task.get("helpTaskIds") or []:
        child = board_store.get_task(table, str(hid))
        if child and str(child.get("status") or "") not in TERMINAL_STATUSES:
            return True
    help_calls = [
        call
        for call in board_store.list_tool_calls_for_task(table, str(task.get("taskId") or ""))
        if str(call.get("op") or "") == "task_request_help"
    ]
    if help_calls and str(help_calls[0].get("status") or "") in ("error", "refused"):
        return True
    return False

def _seat_covers_tools(seat: dict[str, Any], tool_ids: list[str]) -> bool:
    levels = seat.get("effectiveLevels") or {}
    return all(str(levels.get(tid) or "off") != "off" for tid in tool_ids)

def _persona_covers_tools(settings: dict[str, Any], persona_id: str, tool_ids: list[str]) -> bool:
    return all(effective_level(settings, tid, persona_id) != "off" for tid in tool_ids)

def _normalize_help_tool_ids(raw: Any) -> list[str]:
    from board_staff import _HELP_INTERNAL_TOOLS
    ids: list[str] = []
    items = raw if isinstance(raw, list) else []
    for item in items:
        tid = str(item or "").strip()
        if tid and tid in BOARD_TOOL_IDS and tid not in _HELP_INTERNAL_TOOLS and tid not in ids:
            ids.append(tid)
    return ids

def _remap_help_tool_ids(tool_ids: list[str], need: str) -> list[str]:
    """``web`` is GA4. Page-fetch help must go to ``research`` (or be refused)."""
    from board_staff import _PAGE_FETCH_NEED
    lower = (need or "").lower()
    if not any(token in lower for token in _PAGE_FETCH_NEED):
        return tool_ids
    out: list[str] = []
    for tid in tool_ids:
        mapped = "research" if tid == "web" else tid
        if mapped not in out:
            out.append(mapped)
    return out

def pick_helper(
    table: Any,
    settings: dict[str, Any],
    parent: dict[str, Any],
    tool_ids: list[str],
    suggested: str = "",
) -> tuple[str, str]:
    from board_staff import StaffError, seats
    """Return ``(assignee, assigneeKind)`` for a seat or persona that covers ``tool_ids``."""
    roster = seats(table, settings)
    parent_assignee = str(parent.get("assignee") or "")
    parent_manager = str(parent.get("managerId") or "")
    candidates = [
        seat
        for seat in roster
        if seat.get("isActive")
        and str(seat.get("id")) != parent_assignee
        and _seat_covers_tools(seat, tool_ids)
    ]
    if suggested:
        for seat in candidates:
            if str(seat.get("id")) == suggested:
                return suggested, "seat"
        if board_personas.is_persona_id(suggested) and suggested != parent_assignee:
            if _persona_covers_tools(settings, suggested, tool_ids):
                return suggested, "persona"
    def _score(seat: dict[str, Any]) -> tuple[int, int, int, str]:
        levels = seat.get("effectiveLevels") or {}
        extra = sum(1 for lvl in levels.values() if str(lvl or "off") != "off")
        writes = sum(1 for lvl in levels.values() if str(lvl) in ("propose", "act"))
        same_mgr = 0 if str(seat.get("reportsTo") or "") == parent_manager else 1
        return (same_mgr, extra, writes, str(seat.get("id") or ""))

    if candidates:
        best = min(candidates, key=_score)
        return str(best["id"]), "seat"
    # Last resort: the parent's manager persona at desk tier. Their reviewer
    # is the chair (see ``_reviewer_id``), so they do not accept their own work.
    if (
        parent_manager
        and parent_manager != parent_assignee
        and _persona_covers_tools(settings, parent_manager, tool_ids)
    ):
        return parent_manager, "persona"
    raise StaffError(
        "No active seat has those tools. Finish with confidence low and write unavailable."
    )

def _open_help_child_ids(table: Any, task: dict[str, Any]) -> list[str]:
    from board_staff import TERMINAL_STATUSES
    open_ids: list[str] = []
    for hid in task.get("helpTaskIds") or []:
        child = board_store.get_task(table, str(hid))
        if child and child.get("status") not in TERMINAL_STATUSES:
            open_ids.append(str(hid))
    return open_ids

def _pending_help_approvals(table: Any, task_id: str) -> list[dict[str, Any]]:
    return [
        approval
        for approval in board_store.list_approvals(table)
        if approval.get("status") == "pending"
        and approval.get("op") == "task_request_help"
        and str((approval.get("context") or {}).get("taskId") or "") == task_id
    ]

def prepare_help_request(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from board_staff import _GA4_ASSIGN_ALIASES, StaffError, _brief_has_alias, enabled, seats_by_id
    if not enabled(ctx.settings):
        raise StaffError("Staff is disabled")
    if not ctx.task_id:
        raise StaffError("task_request_help is only available on a running task")
    parent = board_store.get_task(ctx.table, ctx.task_id)
    if not parent:
        raise StaffError("Task not found")
    if parent.get("parentTaskId"):
        raise StaffError("Help tasks cannot request further help. Finish with what you have.")
    if int(parent.get("helpRequests") or 0) >= BOARD_STAFF_MAX_HELP_REQUESTS_PER_TASK:
        raise StaffError("This task already used its one help request. Finish with what you have.")
    if parent.get("status") == "waiting_subtask":
        raise StaffError("A help request is already in flight")
    if parent.get("status") == "waiting_approval" and ctx.actor != "owner":
        raise StaffError("A help request is already in flight")
    pending_help = _pending_help_approvals(ctx.table, str(parent.get("taskId") or ""))
    if _open_help_child_ids(ctx.table, parent) or (pending_help and ctx.actor != "owner"):
        raise StaffError("A help request is already in flight")
    need = " ".join(str(args.get("need") or "").split())
    if not need:
        raise StaffError("need is required")
    if len(need) > 2000:
        raise StaffError("need must be at most 2000 characters")
    tool_ids = _remap_help_tool_ids(_normalize_help_tool_ids(args.get("toolIds")), str(args.get("need") or ""))
    if not tool_ids:
        raise StaffError(
            "toolIds must be one or more board tools you were not offered (for example web or finance). "
            "If nobody has those tools, finish with unavailable."
        )
    roster = seats_by_id(ctx.table, ctx.settings) if ctx.seat_id else None
    offered_tools = {
        op.tool_id
        for op, _ in board_tools.available_ops(
            ctx.settings,
            ctx.persona_id,
            context="task",
            seat_id=ctx.seat_id,
            seats_by_id=roster,
        )
        if op.tool_id != "task"
    }
    # web_* is GA4. Remap a page-fetch ask to research. A need that names GA4
    # (sessions, visitor source, GTM) keeps web so a seat with GA4 can take it.
    asked_web = "web" in _normalize_help_tool_ids(args.get("toolIds"))
    ga4_need = any(_brief_has_alias(need.lower(), alias) for alias in _GA4_ASSIGN_ALIASES)
    if (
        "web" in tool_ids
        and "research" in offered_tools
        and "web" not in offered_tools
        and not ga4_need
    ):
        mapped: list[str] = []
        for tid in tool_ids:
            mapped_id = "research" if tid == "web" else tid
            if mapped_id not in mapped:
                mapped.append(mapped_id)
        tool_ids = mapped
    if all(tid in offered_tools for tid in tool_ids):
        if asked_web and not ga4_need and "research" in offered_tools and "web" not in offered_tools:
            raise StaffError(
                "You already have research. web_* is GA4 only; fetch pages with "
                "research_search and research_fetch_page instead of task_request_help."
            )
        raise StaffError("You already have those tools; call them on this task instead of requesting help")
    suggested = str(args.get("suggestedAssignee") or "").strip()
    assignee, kind = pick_helper(ctx.table, ctx.settings, parent, tool_ids, suggested)
    manager_id = str(parent.get("managerId") or "")
    staff_level = effective_level(ctx.settings, "staff", manager_id)
    if not allows(staff_level, "propose"):
        raise StaffError("Your manager cannot assign staff help. Finish with unavailable.")
    return {
        "parent": parent,
        "need": need,
        "toolIds": tool_ids,
        "assignee": assignee,
        "assigneeKind": kind,
        "staffLevel": staff_level,
    }

def validate_task_request_help(ctx: ToolContext, args: dict[str, Any]) -> str | None:
    from board_staff import StaffError
    try:
        prepare_help_request(ctx, args)
    except StaffError as exc:
        return str(exc)
    return None

def act_guard_task_request_help(ctx: ToolContext, _args: dict[str, Any]) -> str | None:
    from board_staff import StaffError
    try:
        prepared = prepare_help_request(ctx, _args)
    except StaffError:
        return None
    if prepared["staffLevel"] != "act":
        return "staff assign is propose-level for this manager"
    return None

def _help_child_brief(parent: dict[str, Any], need: str, tool_ids: list[str]) -> str:
    excerpt = str(parent.get("brief") or "")[:800]
    return (
        f"{need}\n\n"
        f"Parent task {parent.get('taskId')} assigned to {parent.get('assignee')}: {excerpt}\n"
        f"Use {', '.join(tool_ids)} (or the equivalent offered functions) and write a markdown "
        f"memo the parent can cite as evidence. Call the tools; pass their call ids in evidence."
    )

def _park_waiting_subtask(table: Any, task: dict[str, Any], child_id: str) -> None:
    from board_staff import _align_step_claim, _stamp_parked
    stored = board_store.get_task(table, str(task.get("taskId") or ""))
    if stored is not None and stored.get("status") not in ("running", "waiting_approval"):
        return
    if stored is None and task.get("status") not in ("running", "waiting_approval"):
        return
    help_ids = [str(x) for x in (task.get("helpTaskIds") or []) if x]
    if child_id not in help_ids:
        help_ids.append(child_id)
    task["status"] = "waiting_subtask"
    task["blockedOn"] = [child_id]
    task["helpTaskIds"] = help_ids
    task["helpRequests"] = int(task.get("helpRequests") or 0) + 1
    task["idleSteps"] = 0
    _stamp_parked(task, reason=f"waiting on help task {child_id}", reset_clock=True)
    _align_step_claim(task)
    board_store.put_task(table, task)
    _log_event("info", tag="board_staff_waiting_subtask", taskId=task.get("taskId"), childTaskId=child_id)

def op_task_request_help(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from board_staff import StaffError, _remaining_sla_hours, create_task
    prepared = prepare_help_request(ctx, args)
    parent = board_store.get_task(ctx.table, str(prepared["parent"].get("taskId") or "")) or prepared["parent"]
    if ctx.actor != "owner" and parent.get("status") != "running":
        raise StaffError("Task is not running")
    if ctx.actor == "owner" and parent.get("status") not in ("running", "waiting_approval"):
        raise StaffError("Help request is no longer waiting")
    child = create_task(
        ctx.table,
        ctx.settings,
        assignee=prepared["assignee"],
        origin="task",
        brief=_help_child_brief(parent, prepared["need"], prepared["toolIds"]),
        deliverable_type="markdown",
        sla_hours=_remaining_sla_hours(parent),
        created_by=ctx.seat_id or ctx.persona_id or ctx.owner_sub,
        parent_task_id=str(parent.get("taskId") or ""),
    )
    _park_waiting_subtask(ctx.table, parent, str(child.get("taskId") or ""))
    return {
        "ok": True,
        "childTaskId": child.get("taskId"),
        "assignee": prepared["assignee"],
        "status": "waiting_subtask",
    }

def preview_task_request_help(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any] | None:
    from board_staff import StaffError
    try:
        prepared = prepare_help_request(ctx, args)
    except StaffError:
        return None
    parent = prepared["parent"]
    return {
        "kind": "staff_help",
        "from": parent.get("assignee"),
        "helper": prepared["assignee"],
        "need": prepared["need"],
        "toolIds": prepared["toolIds"],
        "parentTaskId": parent.get("taskId"),
        "parentBrief": str(parent.get("brief") or "")[:200],
    }

def summarize_help_request(
    *, prepared: dict[str, Any] | None = None, args: dict[str, Any] | None = None
) -> str:
    payload = args or {}
    tool_ids = list((prepared or {}).get("toolIds") or _normalize_help_tool_ids(payload.get("toolIds")))
    tools = ", ".join(str(t) for t in tool_ids if t) or "tools"
    helper = str((prepared or {}).get("assignee") or "a helper")
    need = str((prepared or {}).get("need") or payload.get("need") or "")
    return f"Ask {helper} for {tools}: {need[:80]}"

def help_available_line(
    table: Any,
    settings: dict[str, Any],
    task: dict[str, Any],
    *,
    roster: list[dict[str, Any]] | None = None,
) -> str:
    from board_staff import _HELP_INTERNAL_TOOLS, seats
    if task.get("parentTaskId"):
        return ""
    if int(task.get("helpRequests") or 0) >= BOARD_STAFF_MAX_HELP_REQUESTS_PER_TASK:
        return ""
    seats_list = roster if roster is not None else seats(table, settings)
    self_id = str(task.get("assignee") or "")
    self_seat = next((seat for seat in seats_list if str(seat.get("id")) == self_id), None)
    if self_seat:
        self_tools = {
            tid
            for tid, lvl in (self_seat.get("effectiveLevels") or {}).items()
            if str(lvl or "off") != "off" and tid not in _HELP_INTERNAL_TOOLS
        }
    elif board_personas.is_persona_id(self_id):
        self_tools = {
            tid
            for tid in BOARD_TOOL_IDS
            if tid not in _HELP_INTERNAL_TOOLS and effective_level(settings, tid, self_id) != "off"
        }
    else:
        self_tools = set()
    parts: list[str] = []
    for seat in seats_list:
        if not seat.get("isActive") or str(seat.get("id")) == self_id:
            continue
        extras = sorted(
            tid
            for tid, lvl in (seat.get("effectiveLevels") or {}).items()
            if str(lvl or "off") != "off" and tid not in self_tools and tid not in _HELP_INTERNAL_TOOLS
        )
        if extras:
            parts.append(f"{seat.get('id')} ({', '.join(extras)})")
    if not parts:
        return ""
    return (
        "Help available: "
        + "; ".join(parts[:8])
        + ".\nIf the brief needs a tool you were not offered, call task_request_help once "
        "with those tool ids instead of finishing unable to verify."
    )

def _child_evidence_records(table: Any, child: dict[str, Any]) -> list[dict[str, str]]:
    """Call ids the parent can cite from a help child's tool work."""
    child_id = str(child.get("taskId") or "")
    if not child_id:
        return []
    wanted = [str(x) for x in (child.get("evidence") or []) if x]
    calls = board_store.list_tool_calls_for_task(table, child_id)
    by_id = {str(c.get("callId")): c for c in calls if c.get("callId")}
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for cid in wanted:
        if cid in seen:
            continue
        seen.add(cid)
        call = by_id.get(cid) or {}
        records.append(
            {
                "callId": cid,
                "op": str(call.get("op") or ""),
                "summary": str(call.get("summary") or "")[:200],
            }
        )
    for call in calls:
        cid = str(call.get("callId") or "")
        op = str(call.get("op") or "")
        if not cid or cid in seen or op.startswith("task_"):
            continue
        if str(call.get("status") or "ok") not in ("ok", ""):
            continue
        seen.add(cid)
        records.append(
            {
                "callId": cid,
                "op": op,
                "summary": str(call.get("summary") or "")[:200],
            }
        )
    return records

def _help_evidence_block(table: Any, child: dict[str, Any]) -> str:
    from board_staff import read_deliverable
    lines = [
        f"HELP FROM {child.get('assignee')} (task {child.get('taskId')}): "
        f"{child.get('summary') or ''}".strip(),
        "",
        read_deliverable(child, limit=6000),
    ]
    records = _child_evidence_records(table, child)
    if records:
        lines.append("")
        lines.append("Cite these call ids in task_finish evidence:")
        for rec in records:
            extra = f" {rec['summary']}" if rec.get("summary") else ""
            lines.append(f"EVIDENCE: {rec['callId']} ({rec['op']}){extra}".rstrip())
    return "\n".join(line for line in lines if line is not None).strip()

def _resume_parent_after_help(
    table: Any,
    settings: dict[str, Any],
    parent_id: str,
    message: str,
    *,
    child: dict[str, Any] | None = None,
    success: bool = False,
) -> None:
    from board_staff import _align_step_claim, _append_scratchpad, _clear_parked, _scratchpad_key, enabled, run_step
    parent = board_store.get_task(table, parent_id)
    if not parent or parent.get("status") != "waiting_subtask":
        return
    if success and child:
        text = _help_evidence_block(table, child)
    else:
        text = f"HELP: {message}"
    combined = _append_scratchpad(parent, text)
    parent["scratchpadKey"] = _scratchpad_key(parent_id)
    parent["scratchpadChars"] = len(combined)
    parent["status"] = "running"
    _clear_parked(parent)
    parent["updatedAt"] = board_store.now_iso()
    _align_step_claim(parent)
    board_store.put_task(table, parent)
    if enabled(settings):
        board_async.invoke_async(
            {
                "internal": "board_staff_step",
                "boardKey": BOARD_KEY,
                "taskId": parent_id,
                "step": int(parent.get("step") or 0) + 1,
            },
            fallback=run_step,
        )

def _notify_parent_of_child(table: Any, child: dict[str, Any], message: str) -> None:
    parent_id = str(child.get("parentTaskId") or "")
    if not parent_id:
        return
    settings = board_store.load_settings(table)
    _resume_parent_after_help(table, settings, parent_id, message, child=child, success=False)

def _note_parent_child_waiting(table: Any, child: dict[str, Any], message: str, *, reason: str) -> None:
    from board_staff import _append_scratchpad, _scratchpad_key, _stamp_parked
    """Leave the parent parked and tell it a child is waiting on the founder."""
    parent_id = str(child.get("parentTaskId") or "")
    if not parent_id:
        return
    parent = board_store.get_task(table, parent_id)
    if not parent or parent.get("status") != "waiting_subtask":
        return
    combined = _append_scratchpad(parent, message)
    parent["scratchpadKey"] = _scratchpad_key(parent_id)
    parent["scratchpadChars"] = len(combined)
    _stamp_parked(parent, reason=reason, reset_clock=False)
    board_store.put_task(table, parent)

def _help_children_held_for_owner(table: Any, task: dict[str, Any]) -> list[dict[str, Any]]:
    from board_staff import OWNER_HELD_CHILD_STATUSES
    held: list[dict[str, Any]] = []
    for hid in task.get("helpTaskIds") or []:
        child = board_store.get_task(table, str(hid))
        if child and child.get("status") in OWNER_HELD_CHILD_STATUSES:
            held.append(child)
    return held

def _reject_pending_help_approvals(table: Any, task_id: str, note: str) -> None:
    now = board_store.now_iso()
    for approval in _pending_help_approvals(table, task_id):
        approval_id = str(approval.get("approvalId") or "")
        if not approval_id:
            continue
        if not board_store.claim_approval_decision(table, approval_id, status="rejected"):
            continue
        board_store.put_approval(
            table,
            {
                **approval,
                "status": "rejected",
                "note": note[:1000],
                "decidedAt": now,
                "decidedBySub": "system:expiry",
                "updatedAt": now,
            },
        )

def _cancel_open_help_children(table: Any, parent: dict[str, Any], by_sub: str) -> None:
    from board_staff import TERMINAL_STATUSES, cancel_task
    for hid in list(parent.get("helpTaskIds") or []):
        child = board_store.get_task(table, str(hid))
        if not child or child.get("status") in TERMINAL_STATUSES:
            continue
        cancel_task(table, str(hid), by_sub, notify_parent=False)

def _expire_help_wait(table: Any, settings: dict[str, Any], task: dict[str, Any]) -> None:
    from board_staff import _align_step_claim, _append_scratchpad, _clear_parked, _scratchpad_key, enabled, run_step
    status = str(task.get("status") or "")
    if status == "waiting_subtask":
        if _help_children_held_for_owner(table, task):
            return
        _cancel_open_help_children(table, task, "system:expiry")
        _resume_parent_after_help(
            table, settings, str(task.get("taskId") or ""), "help unavailable: no answer"
        )
        return
    if status != "waiting_approval":
        return
    task_id = str(task.get("taskId") or "")
    if not _pending_help_approvals(table, task_id):
        return
    _reject_pending_help_approvals(
        table, task_id, "Help request expired with no founder decision."
    )
    _append_scratchpad(task, "HELP: the help request expired with no founder decision. Finish with what you have.")
    task["scratchpadKey"] = _scratchpad_key(task_id)
    task["helpRequests"] = int(task.get("helpRequests") or 0) + 1
    task["status"] = "running"
    _clear_parked(task)
    task["updatedAt"] = board_store.now_iso()
    _align_step_claim(task)
    board_store.put_task(table, task)
    if enabled(settings):
        board_async.invoke_async(
            {
                "internal": "board_staff_step",
                "boardKey": BOARD_KEY,
                "taskId": task.get("taskId"),
                "step": int(task.get("step") or 0) + 1,
            },
            fallback=run_step,
        )

def expire_waiting_help(table: Any, settings: dict[str, Any]) -> int:
    cut = datetime.now(timezone.utc) - timedelta(hours=BOARD_STAFF_WAITING_EXPIRY_HOURS)
    cut_iso = _utc_iso_z(cut)
    expired = 0
    for status in ("waiting_approval", "waiting_subtask"):
        for task in board_store.list_tasks(table, status):
            parked = str(task.get("parkedAt") or task.get("updatedAt") or "")
            if parked < cut_iso:
                before = str(task.get("status") or "")
                _expire_help_wait(table, settings, task)
                latest = board_store.get_task(table, str(task.get("taskId") or "")) or task
                if str(latest.get("status") or "") != before:
                    expired += 1
    return expired
