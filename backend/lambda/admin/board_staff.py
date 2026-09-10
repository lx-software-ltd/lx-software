"""Executive Board staff: seats, background tasks, steps and manager review.

See docs/architecture/executive-board-autonomy-implementation.md WP1.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import board_async
import board_budget
import board_personas
import board_store
import board_tools
from contract_constants import (
    BOARD_CHAIR_DEFAULT,
    BOARD_PERSONA_IDS,
    BOARD_STAFF_DAILY_BUDGET_DEFAULT_USD,
    BOARD_STAFF_DELIVERABLE_MAX_BYTES,
    BOARD_STAFF_DELIVERABLE_TYPES,
    BOARD_STAFF_MAX_REVISIONS,
    BOARD_STAFF_MAX_RUNNING_TASKS_DEFAULT,
    BOARD_STAFF_MAX_STEPS_PER_TASK,
    BOARD_STAFF_MODEL_TIERS,
    BOARD_STAFF_RETENTION_DAYS,
    BOARD_STAFF_SCRATCHPAD_MAX_CHARS,
    BOARD_STAFF_SEAT_IDS,
    BOARD_STAFF_SEATS,
    BOARD_STAFF_STEP_MAX_SECONDS,
    BOARD_STAFF_TASK_BUDGET_DESK_USD,
    BOARD_STAFF_TASK_BUDGET_MAX_USD,
    BOARD_STAFF_TASK_BUDGET_SENIOR_USD,
    BOARD_STAFF_TASK_ORIGINS,
    BOARD_STAFF_TASK_STUCK_SECONDS,
    BOARD_STAFF_TASK_STATUSES,
    BOARD_TOOL_IDS,
    BOARD_TOOL_LEVELS,
)
from http_common import _log_event, _utc_iso_z

_LEVEL_RANK = {lvl: i for i, lvl in enumerate(BOARD_TOOL_LEVELS)}
TERMINAL_STATUSES = frozenset({"delivered", "failed", "cancelled"})
NON_TERMINAL_STATUSES = frozenset(s for s in BOARD_STAFF_TASK_STATUSES if s not in TERMINAL_STATUSES)
_MEMORY_BLOBS: dict[str, bytes] = {}


class StaffError(ValueError):
    """Staff is disabled or the request is invalid."""


def env_enabled() -> bool:
    env = (os.environ.get("BOARD_STAFF_ENABLED") or "").strip().lower()
    return env in ("1", "true", "yes", "on")


def enabled(settings: dict[str, Any]) -> bool:
    if not env_enabled():
        return False
    return bool((settings.get("staff") or {}).get("enabled"))


def seat_default(seat_id: str) -> dict[str, Any] | None:
    for seat in BOARD_STAFF_SEATS:
        if seat.get("id") == seat_id:
            return seat
    return None


def is_seat_id(value: Any) -> bool:
    return isinstance(value, str) and value in BOARD_STAFF_SEAT_IDS


def _min_level(*levels: str) -> str:
    ranks = [_LEVEL_RANK.get(lvl, 0) for lvl in levels]
    return BOARD_TOOL_LEVELS[min(ranks)] if ranks else "off"


def seat_level(
    settings: dict[str, Any],
    seats_by_id: dict[str, dict[str, Any]],
    seat_id: str,
    tool_id: str,
) -> str:
    seat = seats_by_id.get(seat_id)
    if not seat:
        return "off"
    if not seat.get("isActive"):
        return "off"
    seat_default_level = str((seat.get("tools") or {}).get(tool_id) or "off")
    manager_id = str(seat.get("reportsTo") or "")
    manager_level = board_tools.effective_level(settings, tool_id, manager_id)
    cap = board_tools.global_cap(settings)
    return _min_level(seat_default_level, manager_level, cap)


def seats(table: Any, settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    settings = settings if settings is not None else board_store.load_settings(table)
    overrides = board_store.load_staff_overrides(table)
    roster: list[dict[str, Any]] = []
    for default in BOARD_STAFF_SEATS:
        ov = overrides.get(str(default["id"])) or {}
        is_active = ov["isActive"] if "isActive" in ov else bool(default.get("isActiveDefault"))
        tier = ov.get("modelTier") if ov.get("modelTier") in BOARD_STAFF_MODEL_TIERS else default.get("modelTier")
        brief = ov.get("brief") if isinstance(ov.get("brief"), str) and ov.get("brief").strip() else str(default.get("brief") or "")
        display = ov.get("displayName") if isinstance(ov.get("displayName"), str) and ov.get("displayName").strip() else str(default.get("title") or "")
        seat = {
            "id": default["id"],
            "reportsTo": default["reportsTo"],
            "title": default["title"],
            "modelTier": tier,
            "isActive": bool(is_active),
            "isActiveDefault": bool(default.get("isActiveDefault")),
            "tools": dict(default.get("tools") or {}),
            "brief": brief,
            "displayName": display,
            "defaults": {
                "brief": str(default.get("brief") or ""),
                "displayName": str(default.get("title") or ""),
                "modelTier": str(default.get("modelTier") or "desk"),
            },
            "isOverridden": {
                "brief": bool(ov.get("brief")),
                "displayName": bool(ov.get("displayName")),
                "isActive": "isActive" in ov,
                "modelTier": bool(ov.get("modelTier")),
            },
            "updatedAt": ov.get("updatedAt"),
        }
        roster.append(seat)
    by_id = {str(s["id"]): s for s in roster}
    for seat in roster:
        seat["effectiveLevels"] = {
            tool_id: seat_level(settings, by_id, str(seat["id"]), tool_id) for tool_id in BOARD_TOOL_IDS
        }
    return roster


def seats_by_id(table: Any, settings: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    return {str(s["id"]): s for s in seats(table, settings)}


def _tier_budget(tier: str) -> float:
    return BOARD_STAFF_TASK_BUDGET_SENIOR_USD if tier == "senior" else BOARD_STAFF_TASK_BUDGET_DESK_USD


def _resolve_assignee(
    table: Any, settings: dict[str, Any], assignee: str
) -> tuple[str, str, str, str]:
    """Return (assignee, assigneeKind, managerId, tier)."""
    if board_personas.is_persona_id(assignee):
        return assignee, "persona", assignee, "desk"
    if not is_seat_id(assignee):
        raise StaffError(f"Unknown assignee '{assignee}'")
    roster = seats_by_id(table, settings)
    seat = roster.get(assignee)
    if not seat or not seat.get("isActive"):
        raise StaffError(f"Seat '{assignee}' is not active")
    return assignee, "seat", str(seat["reportsTo"]), str(seat.get("modelTier") or "desk")


def create_task(
    table: Any,
    settings: dict[str, Any],
    *,
    assignee: str,
    origin: str,
    brief: str,
    deliverable_type: str,
    budget_usd: float | None = None,
    sla_hours: int = 24,
    event_ref: dict[str, Any] | None = None,
    action_id: str | None = None,
    meeting_id: str | None = None,
    created_by: str = "",
    status: str = "queued",
) -> dict[str, Any]:
    if not enabled(settings):
        raise StaffError("Staff is disabled")
    if origin not in BOARD_STAFF_TASK_ORIGINS:
        raise StaffError(f"origin must be one of {', '.join(BOARD_STAFF_TASK_ORIGINS)}")
    if deliverable_type not in BOARD_STAFF_DELIVERABLE_TYPES:
        raise StaffError(f"deliverableType must be one of {', '.join(BOARD_STAFF_DELIVERABLE_TYPES)}")
    text = " ".join(str(brief or "").split())
    if not text:
        raise StaffError("brief is required")
    if len(text) > 4000:
        raise StaffError("brief must be at most 4000 characters")
    sla_hours = max(1, min(168, int(sla_hours)))
    assignee, kind, manager_id, tier = _resolve_assignee(table, settings, assignee)
    default_budget = _tier_budget(tier)
    try:
        budget = float(budget_usd) if budget_usd is not None else default_budget
    except (TypeError, ValueError):
        budget = default_budget
    budget = max(0.01, min(BOARD_STAFF_TASK_BUDGET_MAX_USD, budget))
    if status not in BOARD_STAFF_TASK_STATUSES:
        raise StaffError(f"status must be one of {', '.join(BOARD_STAFF_TASK_STATUSES)}")
    now = datetime.now(timezone.utc)
    sla_at = _utc_iso_z(now + timedelta(hours=sla_hours))
    task_id = board_store.new_id()
    doc: dict[str, Any] = {
        "taskId": task_id,
        "status": status,
        "assignee": assignee,
        "assigneeKind": kind,
        "managerId": manager_id,
        "origin": origin,
        "eventRef": event_ref,
        "actionId": action_id or None,
        "meetingId": meeting_id or None,
        "brief": text,
        "deliverableType": deliverable_type,
        "budgetUsd": budget,
        "slaAt": sla_at,
        "step": 0,
        "stepsUsed": 0,
        "revisions": 0,
        "usage": {"promptTokens": 0, "completionTokens": 0, "cost": 0.0, "calls": 0},
        "scratchpadKey": "",
        "scratchpadChars": 0,
        "deliverableKey": "",
        "deliverableBytes": 0,
        "summary": "",
        "evidence": [],
        "openQuestions": [],
        "actions": [],
        "confidence": "",
        "flags": [],
        "reviews": 0,
        "lastReview": None,
        "createdAt": _utc_iso_z(now),
        "createdBy": created_by,
        "updatedAt": _utc_iso_z(now),
        "startedAt": None,
        "finishedAt": None,
        "failureReason": "",
    }
    board_store.put_task(table, doc)
    if status == "queued":
        drain_queue(table, settings)
    return board_store.get_task(table, task_id) or doc


def drain_queue(table: Any, settings: dict[str, Any]) -> int:
    if not enabled(settings):
        return 0
    cap = int((settings.get("staff") or {}).get("maxRunningTasks") or BOARD_STAFF_MAX_RUNNING_TASKS_DEFAULT)
    running = [t for t in board_store.list_tasks(table, "running") if t.get("status") == "running"]
    reviewing = [t for t in board_store.list_tasks(table, "review") if t.get("status") == "review"]
    slots = max(0, cap - len(running) - len(reviewing))
    started = 0
    queued = [t for t in board_store.list_tasks(table, "queued") if t.get("status") == "queued"]
    queued.sort(key=lambda t: str(t.get("slaAt") or ""))
    for task in queued:
        if started >= slots:
            break
        task_id = str(task.get("taskId") or "")
        if not task_id:
            continue
        if not board_store.claim_task_step(table, task_id, 0):
            continue
        board_async.invoke_async(
            {"internal": "board_staff_step", "boardKey": "siuTinDei", "taskId": task_id, "step": 1},
            fallback=run_step,
        )
        started += 1
    return started


def _blob_put(key: str, body: bytes) -> None:
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if not bucket:
        _MEMORY_BLOBS[key] = body
        return
    import runtime

    runtime._s3.put_object(Bucket=bucket, Key=key, Body=body)


def _blob_get(key: str) -> bytes:
    if key in _MEMORY_BLOBS:
        return _MEMORY_BLOBS[key]
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if not bucket:
        return b""
    import runtime

    try:
        res = runtime._s3.get_object(Bucket=bucket, Key=key)
        return res["Body"].read()
    except Exception:
        return b""


def _scratchpad_key(task_id: str) -> str:
    return f"board/siuTinDei/staff/{task_id}/scratchpad.md"


def _deliverable_key(task_id: str, deliverable_type: str) -> str:
    ext = {"markdown": "md", "csv": "csv", "json": "json", "messages": "json"}.get(deliverable_type, "md")
    return f"board/siuTinDei/staff/{task_id}/deliverable.{ext}"


def _append_scratchpad(task: dict[str, Any], text: str) -> str:
    key = str(task.get("scratchpadKey") or _scratchpad_key(str(task["taskId"])))
    existing = _blob_get(key).decode("utf-8", errors="replace")
    combined = (existing + ("\n\n" if existing and text else "") + text).strip()
    if len(combined) > BOARD_STAFF_SCRATCHPAD_MAX_CHARS:
        combined = combined[-BOARD_STAFF_SCRATCHPAD_MAX_CHARS:]
    _blob_put(key, combined.encode("utf-8"))
    return combined


def _finish_incomplete(table: Any, task: dict[str, Any], reason: str) -> dict[str, Any]:
    now = board_store.now_iso()
    updated = {
        **task,
        "status": "failed",
        "failureReason": reason[:300],
        "finishedAt": now,
        "updatedAt": now,
        "expiresAt": int(datetime.now(timezone.utc).timestamp()) + BOARD_STAFF_RETENTION_DAYS * 86400,
    }
    board_store.put_task(table, updated)
    _log_event("warning", tag="board_staff_incomplete", taskId=task.get("taskId"), reason=reason[:200])
    return updated


def _task_usage_add(task: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
    current = dict(task.get("usage") or {})
    current["promptTokens"] = int(current.get("promptTokens") or 0) + int(usage.get("promptTokens") or 0)
    current["completionTokens"] = int(current.get("completionTokens") or 0) + int(usage.get("completionTokens") or 0)
    current["cost"] = float(current.get("cost") or 0.0) + float(usage.get("cost") or 0.0)
    current["calls"] = int(current.get("calls") or 0) + 1
    return current


def _reviewer_id(task: dict[str, Any]) -> str:
    if task.get("assigneeKind") == "persona" and task.get("assignee") == BOARD_CHAIR_DEFAULT:
        return "cfo"
    if task.get("assigneeKind") == "persona":
        return BOARD_CHAIR_DEFAULT
    return str(task.get("managerId") or BOARD_CHAIR_DEFAULT)


def run_step(payload: dict[str, Any]) -> None:
    if not board_store.event_targets_this_board(payload):
        return
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    if not enabled(settings):
        return
    task_id = str(payload.get("taskId") or "")
    wanted = int(payload.get("step") or 0)
    task = board_store.get_task(table, task_id)
    if not task or task.get("status") != "running":
        return
    if wanted != int(task.get("step") or 0) + 1:
        return
    if not board_store.claim_task_step(table, task_id, wanted - 1):
        return
    try:
        board_budget.check_budget(table, settings)
    except board_budget.BudgetExceeded as exc:
        _finish_incomplete(table, task, str(exc))
        return
    staff_usage = board_store.load_staff_usage_day(table)
    staff_cap = float((settings.get("staff") or {}).get("dailyBudgetUsd") or BOARD_STAFF_DAILY_BUDGET_DEFAULT_USD)
    if staff_cap > 0 and staff_usage["cost"] >= staff_cap:
        _finish_incomplete(table, task, f"Staff daily budget of USD {staff_cap:.2f} is exhausted")
        return
    if float((task.get("usage") or {}).get("cost") or 0.0) >= float(task.get("budgetUsd") or 0):
        _finish_incomplete(table, task, "Task budget exhausted")
        return
    roster = seats_by_id(table, settings)
    persona_overrides = board_store.load_member_overrides(table)
    charter = board_store.load_charter(table)
    if task.get("assigneeKind") == "seat":
        seat = roster.get(str(task.get("assignee")))
        manager = board_personas.effective_profile(
            board_personas.persona_default(str(seat["reportsTo"])) or {},
            persona_overrides.get(str(seat["reportsTo"])),
        ) if seat else None
        lessons = _confirmed_lessons(table, str(task.get("assignee")))
        system = board_personas.render_seat_prompt(seat or {}, manager or {}, charter, lessons)
        persona_id = str(task.get("managerId") or "")
        seat_id = str(task.get("assignee") or "")
        display = str((seat or {}).get("displayName") or seat_id)
        tier = str((seat or {}).get("modelTier") or "desk")
    else:
        persona_id = str(task.get("assignee") or "")
        default = board_personas.persona_default(persona_id) or {}
        profile = board_personas.effective_profile(default, persona_overrides.get(persona_id))
        lessons = _confirmed_lessons(table, persona_id)
        system = board_personas.render_system_prompt(profile, charter, lessons=lessons)
        seat_id = ""
        display = str(profile.get("displayName") or persona_id)
        tier = "desk"
    scratch = _blob_get(_scratchpad_key(task_id)).decode("utf-8", errors="replace")
    user = board_personas.render_task_frame(task, scratch)
    kind = "standup" if tier != "senior" else "deepDive"
    if (settings.get("staff") or {}).get("seniorPaused") and kind == "deepDive":
        kind = "standup"
    model = board_budget.model_for(kind, settings)
    def _sink(usage: dict[str, Any]) -> None:
        board_store.add_staff_usage_day(table, seat_id or persona_id, {**usage, "calls": 1})

    ctx = board_tools.ToolContext(
        table=table,
        settings=settings,
        persona_id=persona_id,
        display_name=display,
        kind="task",
        task_id=task_id,
        seat_id=seat_id,
        actor="persona",
        usage_sink=_sink,
    )
    result = board_tools.run_tool_loop(
        ctx=ctx,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        model=model,
        timeout=min(90, BOARD_STAFF_STEP_MAX_SECONDS),
        max_tokens=2500,
        temperature=0.3,
        json_mode=False,
        tag="board_staff_step",
        max_seconds=BOARD_STAFF_STEP_MAX_SECONDS,
    )
    usage = result.usage or {}
    task = board_store.get_task(table, task_id) or task
    if task.get("status") != "running":
        return
    latest = board_store.get_task(table, task_id) or task
    if latest.get("status") == "review":
        return
    latest["usage"] = _task_usage_add(latest, usage)
    note = (result.text or "").strip()
    if note:
        combined = _append_scratchpad(latest, note)
        latest["scratchpadKey"] = _scratchpad_key(task_id)
        latest["scratchpadChars"] = len(combined)
    seq = int(latest.get("step") or 0) + 1
    board_store.put_task_step(
        table,
        task_id,
        {
            "seq": seq,
            "plan": note[:2000],
            "callIds": [c.get("callId") for c in result.calls if c.get("callId")],
            "usage": usage,
            "at": board_store.now_iso(),
        },
    )
    latest["step"] = seq
    latest["stepsUsed"] = seq
    latest["updatedAt"] = board_store.now_iso()
    if seq >= BOARD_STAFF_MAX_STEPS_PER_TASK:
        _finish_incomplete(table, latest, "step limit")
        return
    board_store.put_task(table, latest)
    board_async.invoke_async(
        {"internal": "board_staff_step", "boardKey": "siuTinDei", "taskId": task_id, "step": seq + 1},
        fallback=run_step,
    )


def _confirmed_lessons(table: Any, subject: str) -> list[str]:
    from contract_constants import BOARD_STAFF_LESSONS_PER_SEAT_IN_PROMPT

    rows = board_store.list_lessons(table, subject, limit=BOARD_STAFF_LESSONS_PER_SEAT_IN_PROMPT)
    out: list[str] = []
    for row in rows:
        if not row.get("confirmed"):
            continue
        text = str(row.get("instruction") or "").strip()
        if text:
            out.append(text)
        if len(out) >= BOARD_STAFF_LESSONS_PER_SEAT_IN_PROMPT:
            break
    return out


def _origin_from_ctx(ctx: board_tools.ToolContext) -> str:
    if ctx.actor == "owner":
        return "owner"
    if ctx.kind == "meeting":
        return "minutes"
    if ctx.kind == "task":
        return "task" if "task" in BOARD_STAFF_TASK_ORIGINS else "chat"
    if ctx.kind == "chat":
        return "chat"
    return "chat"


def act_guard_staff_assign(ctx: board_tools.ToolContext, _args: dict[str, Any]) -> str | None:
    cap = int((ctx.settings.get("staff") or {}).get("maxRunningTasks") or BOARD_STAFF_MAX_RUNNING_TASKS_DEFAULT)
    running = len([t for t in board_store.list_tasks(ctx.table, "running") if t.get("status") == "running"])
    reviewing = len([t for t in board_store.list_tasks(ctx.table, "review") if t.get("status") == "review"])
    if running + reviewing >= cap * 2:
        return "queue full"
    return None


def op_staff_assign(ctx: board_tools.ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task = create_task(
        ctx.table,
        ctx.settings,
        assignee=str(args.get("assignee") or ""),
        origin=_origin_from_ctx(ctx),
        brief=str(args.get("brief") or ""),
        deliverable_type=str(args.get("deliverableType") or "markdown"),
        budget_usd=args.get("budgetUsd"),
        sla_hours=int(args.get("slaHours") or 24),
        action_id=str(args.get("actionId") or "") or None,
        created_by=ctx.owner_sub or ctx.persona_id or ctx.seat_id,
    )
    return public_task(task)


def op_staff_list_tasks(ctx: board_tools.ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    status = str(args.get("status") or "") or None
    if status and status not in BOARD_STAFF_TASK_STATUSES:
        raise StaffError(f"status must be one of {', '.join(BOARD_STAFF_TASK_STATUSES)}")
    limit = max(1, min(50, int(args.get("limit") or 20)))
    tasks = board_store.list_tasks(ctx.table, status, limit=200)
    if ctx.seat_id:
        tasks = [t for t in tasks if t.get("assignee") == ctx.seat_id]
    return {"tasks": [public_task(t) for t in tasks[:limit]]}


def op_staff_get_deliverable(ctx: board_tools.ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task = board_store.get_task(ctx.table, str(args.get("taskId") or ""))
    if not task:
        raise StaffError("Task not found")
    if ctx.seat_id and task.get("assignee") != ctx.seat_id and ctx.persona_id != task.get("managerId"):
        raise StaffError("You cannot read another seat's deliverable")
    return {
        "summary": task.get("summary") or "",
        "deliverable": read_deliverable(task, limit=6000),
        "deliverableType": task.get("deliverableType"),
        "status": task.get("status"),
    }


def op_staff_request_revision(ctx: board_tools.ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task = board_store.get_task(ctx.table, str(args.get("taskId") or ""))
    if not task:
        raise StaffError("Task not found")
    if ctx.persona_id != task.get("managerId"):
        raise StaffError("Only the manager can request a revision")
    notes = str(args.get("notes") or "").strip()
    if not notes:
        raise StaffError("notes are required")
    return public_task(apply_review(ctx.table, ctx.settings, task, verdict="return", notes=notes, by=ctx.persona_id))


def op_staff_cancel_task(ctx: board_tools.ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task = board_store.get_task(ctx.table, str(args.get("taskId") or ""))
    if not task:
        raise StaffError("Task not found")
    if ctx.actor != "owner" and ctx.persona_id != task.get("managerId"):
        raise StaffError("Only the manager or founder can cancel this task")
    reason = str(args.get("reason") or "").strip()
    cancelled = cancel_task(ctx.table, str(task["taskId"]), ctx.owner_sub or ctx.persona_id)
    if reason:
        cancelled["failureReason"] = f"cancelled by {ctx.persona_id or ctx.owner_sub}: {reason}"[:300]
        board_store.put_task(ctx.table, cancelled)
    return public_task(cancelled)


def op_task_note(ctx: board_tools.ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task = board_store.get_task(ctx.table, ctx.task_id)
    if not task:
        raise StaffError("Task not found")
    text = str(args.get("text") or "").strip()
    combined = _append_scratchpad(task, text)
    task["scratchpadKey"] = _scratchpad_key(ctx.task_id)
    task["scratchpadChars"] = len(combined)
    task["updatedAt"] = board_store.now_iso()
    board_store.put_task(ctx.table, task)
    return {"ok": True, "chars": len(combined)}


def op_task_finish(ctx: board_tools.ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task = board_store.get_task(ctx.table, ctx.task_id)
    if not task:
        raise StaffError("Task not found")
    deliverable = str(args.get("deliverable") or "")
    encoded = deliverable.encode("utf-8")
    if len(encoded) > BOARD_STAFF_DELIVERABLE_MAX_BYTES:
        raise StaffError(
            f"deliverable is larger than {BOARD_STAFF_DELIVERABLE_MAX_BYTES} bytes; split it"
        )
    evidence = [str(x) for x in (args.get("evidence") or []) if isinstance(x, (str, int))]
    known = {str(c.get("callId")) for c in board_store.list_tool_calls_for_task(ctx.table, ctx.task_id)}
    for step in board_store.list_task_steps(ctx.table, ctx.task_id):
        for cid in step.get("callIds") or []:
            if cid:
                known.add(str(cid))
    evidence = [e for e in evidence if e in known]
    confidence = str(args.get("confidence") or "medium")
    flags = list(task.get("flags") or [])
    if not evidence and confidence == "high":
        confidence = "medium"
        flags.append("no_evidence")
    dtype = str(args.get("deliverableType") or task.get("deliverableType") or "markdown")
    key = _deliverable_key(ctx.task_id, dtype)
    _blob_put(key, encoded)
    now = board_store.now_iso()
    updated = {
        **task,
        "status": "review",
        "summary": str(args.get("summary") or "")[:800],
        "evidence": evidence,
        "openQuestions": [str(x) for x in (args.get("openQuestions") or []) if x][:10],
        "confidence": confidence,
        "flags": flags,
        "deliverableKey": key,
        "deliverableBytes": len(encoded),
        "deliverableType": dtype,
        "updatedAt": now,
    }
    board_store.put_task(ctx.table, updated)
    if enabled(ctx.settings):
        board_async.invoke_async(
            {"internal": "board_staff_review", "boardKey": "siuTinDei", "taskId": ctx.task_id},
            fallback=run_review,
        )
    return {"ok": True, "status": "review", "deliverableKey": key}


def run_review(payload: dict[str, Any]) -> None:
    if not board_store.event_targets_this_board(payload):
        return
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    if not enabled(settings):
        return
    task_id = str(payload.get("taskId") or "")
    task = board_store.get_task(table, task_id)
    if not task or task.get("status") != "review":
        return
    reviewer_id = _reviewer_id(task)
    overrides = board_store.load_member_overrides(table)
    charter = board_store.load_charter(table)
    default = board_personas.persona_default(reviewer_id) or {}
    profile = board_personas.effective_profile(default, overrides.get(reviewer_id))
    raw = _blob_get(str(task.get("deliverableKey") or "")).decode("utf-8", errors="replace")
    if len(raw) > 12000:
        raw = raw[:12000] + "\n[… truncated]"
    calls = board_store.list_tool_calls_for_task(table, task_id)
    evidence_lines = [
        f"- {c.get('op')}: {c.get('summary')}" for c in calls if str(c.get("callId")) in set(task.get("evidence") or [])
    ]
    prompt = (
        f"You are reviewing work assigned to {task.get('assignee')}.\n"
        f"Brief: {task.get('brief')}\n"
        f"Deliverable type: {task.get('deliverableType')}\n"
        f"Confidence: {task.get('confidence')}\n"
        f"Evidence:\n" + ("\n".join(evidence_lines) or "(none)") + "\n\n"
        f"Deliverable:\n{raw}\n\n"
        'Return JSON {"verdict":"accept"|"return","notes":"…"}.'
    )
    system = board_personas.render_system_prompt(profile, charter)
    model = board_budget.model_for("standup", settings)
    completion = board_budget.board_completion(
        table=table,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        model=model,
        timeout=60,
        json_mode=True,
        temperature=0.2,
        max_tokens=800,
        tag="board_staff_review",
    )
    board_store.add_staff_usage_day(table, reviewer_id, {**(completion.usage or {}), "calls": 1})
    verdict = "return"
    notes = ""
    parsed_ok = False
    try:
        parsed = json.loads(completion.text or "")
        raw_verdict = str(parsed.get("verdict") or "").lower()
        if raw_verdict in ("accept", "return"):
            verdict = raw_verdict
            parsed_ok = True
        notes = str(parsed.get("notes") or "")[:2000]
    except json.JSONDecodeError:
        notes = (completion.text or "")[:2000]
    if not parsed_ok:
        _log_event("warning", tag="board_staff_review_unparsed", taskId=task_id)
        verdict = "return"
    apply_review(table, settings, task, verdict=verdict, notes=notes, by="manager")


def apply_review(
    table: Any,
    settings: dict[str, Any],
    task: dict[str, Any],
    *,
    verdict: str,
    notes: str,
    by: str,
) -> dict[str, Any]:
    now = board_store.now_iso()
    seq = int(task.get("reviews") or 0) + 1
    review = {"seq": seq, "verdict": verdict, "notes": notes, "at": now, "by": by}
    board_store.put_task_review(table, str(task["taskId"]), review)
    task["reviews"] = seq
    task["lastReview"] = {"verdict": verdict, "notes": notes, "at": now, "by": by}
    task["updatedAt"] = now
    if verdict == "accept":
        return _accept_task(table, task, now)
    try:
        import board_lessons

        board_lessons.create_from_return(table, task)
    except Exception as exc:
        _log_event("warning", tag="board_lesson_from_return_failed", error=str(exc)[:200])
    revisions = int(task.get("revisions") or 0)
    if revisions < BOARD_STAFF_MAX_REVISIONS:
        _append_scratchpad(task, f"MANAGER NOTES: {notes}")
        task["revisions"] = revisions + 1
        task["status"] = "running"
        board_store.put_task(table, task)
        board_async.invoke_async(
            {
                "internal": "board_staff_step",
                "boardKey": "siuTinDei",
                "taskId": task["taskId"],
                "step": int(task.get("step") or 0) + 1,
            },
            fallback=run_step,
        )
        return task
    task["status"] = "delivered"
    task["finishedAt"] = now
    task["expiresAt"] = int(datetime.now(timezone.utc).timestamp()) + BOARD_STAFF_RETENTION_DAYS * 86400
    board_store.put_task(table, task)
    return task


def _accept_task(table: Any, task: dict[str, Any], now: str) -> dict[str, Any]:
    task["status"] = "delivered"
    task["finishedAt"] = now
    task["expiresAt"] = int(datetime.now(timezone.utc).timestamp()) + BOARD_STAFF_RETENTION_DAYS * 86400
    action_id = task.get("actionId")
    dtype = str(task.get("deliverableType") or "")
    if action_id and dtype in ("markdown", "csv", "json", "issues", "pr"):
        action = board_store.get_action(table, str(action_id))
        if action:
            action["note"] = (
                (str(action.get("note") or "") + "\n" if action.get("note") else "")
                + f"Closed by staff task {task['taskId']}: {task.get('summary') or ''}"
            )[:2000]
            action["status"] = "done"
            action["closedBy"] = f"staff:{task['taskId']}"
            action["updatedAt"] = now
            board_store.put_action(table, action)
    board_store.put_task(table, task)
    ref = task.get("eventRef") or {}
    if ref.get("kind") == "duty" and str(ref.get("id") or "").startswith("market-brief:"):
        try:
            import board_intel

            board_intel.on_brief_delivered(table, task)
        except Exception as exc:
            _log_event("warning", tag="board_intel_brief_deliver_failed", error=str(exc)[:200])
    if ref.get("kind") == "duty" and str(ref.get("id") or "").startswith("content-plan:"):
        try:
            import board_content

            board_content.on_plan_delivered(table, board_store.load_settings(table), task)
        except Exception as exc:
            _log_event("warning", tag="board_content_plan_deliver_failed", error=str(exc)[:200])
    if ref.get("kind") == "duty" and str(ref.get("id") or "").startswith("content-readout:"):
        try:
            import board_content

            board_content.on_readout_delivered(table, board_store.load_settings(table), task)
        except Exception as exc:
            _log_event("warning", tag="board_content_readout_deliver_failed", error=str(exc)[:200])
    if ref.get("kind") == "code-review":
        try:
            import board_code

            board_code.on_review_delivered(table, board_store.load_settings(table), task)
        except Exception as exc:
            _log_event("warning", tag="board_code_review_deliver_failed", error=str(exc)[:200])
    return task


def cancel_task(table: Any, task_id: str, by_sub: str) -> dict[str, Any]:
    task = board_store.get_task(table, task_id)
    if not task:
        raise StaffError("Task not found")
    if task.get("status") in TERMINAL_STATUSES:
        return task
    now = board_store.now_iso()
    task["status"] = "cancelled"
    task["finishedAt"] = now
    task["updatedAt"] = now
    task["failureReason"] = f"cancelled by {by_sub}"
    task["expiresAt"] = int(datetime.now(timezone.utc).timestamp()) + BOARD_STAFF_RETENTION_DAYS * 86400
    board_store.put_task(table, task)
    return task


def owner_review(table: Any, settings: dict[str, Any], task_id: str, verdict: str, notes: str, by_sub: str) -> dict[str, Any]:
    task = board_store.get_task(table, task_id)
    if not task:
        raise StaffError("Task not found")
    if verdict not in ("accept", "return"):
        raise StaffError("verdict must be accept or return")
    return apply_review(table, settings, task, verdict=verdict, notes=notes, by=f"owner:{by_sub}")


def handle_tick(event: dict[str, Any]) -> dict[str, Any]:
    if not board_store.event_targets_this_board(event):
        return {"ok": True, "skipped": "other_board"}
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    try:
        import board_holds

        board_holds.expire_stale(table, settings, board_store.now_iso())
    except Exception as exc:
        _log_event("warning", tag="board_holds_expire_failed", error=str(exc)[:300])
    if not enabled(settings):
        return {"ok": True, "skipped": "disabled"}
    try:
        import board_breakers

        board_breakers.evaluate(table, settings)
        settings = board_store.load_settings(table)
        if not enabled(settings):
            return {"ok": True, "skipped": "disabled", "breaker": "budget"}
    except ImportError:
        pass
    except Exception as exc:
        _log_event("error", tag="board_breakers_tick_failed", error=str(exc)[:300])
    try:
        import board_holds

        board_holds.execute_due(table, settings, board_store.now_iso())
    except ImportError:
        pass
    except Exception as exc:
        _log_event("error", tag="board_holds_tick_failed", error=str(exc)[:300])
    try:
        import board_review

        board_review.maybe_create_headline_duty(table, settings)
    except Exception as exc:
        _log_event("warning", tag="board_review_duty_failed", error=str(exc)[:300])
    try:
        import board_duties

        board_duties.run_due(table, settings)
    except Exception as exc:
        _log_event("warning", tag="board_duties_tick_failed", error=str(exc)[:300])
    try:
        import board_code

        board_code.handle_tick(table, settings)
    except Exception as exc:
        _log_event("warning", tag="board_code_tick_failed", error=str(exc)[:300])
    started = drain_queue(table, settings)
    stuck_cut = datetime.now(timezone.utc) - timedelta(seconds=BOARD_STAFF_TASK_STUCK_SECONDS)
    cut_iso = _utc_iso_z(stuck_cut)
    for task in board_store.list_tasks(table, "running"):
        if str(task.get("updatedAt") or "") < cut_iso:
            _finish_incomplete(table, task, "stuck")
    for task in board_store.list_tasks(table, "review"):
        if str(task.get("updatedAt") or "") < cut_iso:
            if not task.get("reviewRetried"):
                task["reviewRetried"] = True
                task["updatedAt"] = board_store.now_iso()
                board_store.put_task(table, task)
                board_async.invoke_async(
                    {"internal": "board_staff_review", "boardKey": "siuTinDei", "taskId": task["taskId"]},
                    fallback=run_review,
                )
            else:
                task["status"] = "needs_owner"
                task["updatedAt"] = board_store.now_iso()
                board_store.put_task(table, task)
    return {"ok": True, "started": started}


def list_tasks_for_api(
    table: Any,
    *,
    status: str | None = None,
    assignee: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if status:
        items = board_store.list_tasks(table, status, limit=max(limit, 50))
    else:
        items = []
        for st in NON_TERMINAL_STATUSES:
            items.extend(board_store.list_tasks(table, st, limit=200))
        terminal: list[dict[str, Any]] = []
        for st in TERMINAL_STATUSES:
            terminal.extend(board_store.list_tasks(table, st, limit=50))
        terminal.sort(key=lambda t: str(t.get("finishedAt") or t.get("updatedAt") or ""), reverse=True)
        items.extend(terminal[:50])
    if assignee:
        items = [t for t in items if t.get("assignee") == assignee]
    items.sort(key=lambda t: str(t.get("slaAt") or t.get("createdAt") or ""))
    return items[:limit]


def staff_counts(table: Any) -> dict[str, int]:
    counts = {status: 0 for status in BOARD_STAFF_TASK_STATUSES}
    for status in BOARD_STAFF_TASK_STATUSES:
        counts[status] = len(board_store.list_tasks(table, status, limit=200))
    return counts


def context_staff_pack(table: Any) -> dict[str, Any]:
    delivered = [
        {"taskId": t.get("taskId"), "assignee": t.get("assignee"), "summary": t.get("summary")}
        for t in board_store.list_tasks(table, "delivered", limit=10)
    ]
    inflight = []
    for status in ("queued", "running", "review"):
        for t in board_store.list_tasks(table, status, limit=20):
            inflight.append({"taskId": t.get("taskId"), "assignee": t.get("assignee"), "brief": str(t.get("brief") or "")[:80], "status": status})
    return {"staffDelivered": delivered[:10], "staffInFlight": inflight}


def assign_from_minutes(table: Any, settings: dict[str, Any], *, action: dict[str, Any], chair_id: str) -> None:
    assignee = str(action.get("assignee") or "")
    if not assignee:
        return
    if not enabled(settings):
        return
    level = board_tools.effective_level(settings, "staff", chair_id)
    if not board_tools.allows(level, "propose"):
        return
    overrides = board_store.load_member_overrides(table)
    default = board_personas.persona_default(chair_id) or {}
    profile = board_personas.effective_profile(default, overrides.get(chair_id))
    ctx = board_tools.ToolContext(
        table=table,
        settings=settings,
        persona_id=chair_id,
        display_name=str(profile.get("displayName") or chair_id),
        kind="meeting",
        meeting_id=str(action.get("meetingId") or ""),
        actor="persona",
    )
    op = board_tools.REGISTRY.get("staff_assign")
    if not op:
        return
    board_tools.execute_call(
        ctx,
        op,
        {
            "assignee": assignee,
            "brief": str(action.get("title") or "") + (f": {action.get('detail')}" if action.get("detail") else ""),
            "deliverableType": "markdown",
            "slaHours": 24,
            "actionId": action.get("actionId"),
        },
    )


def validate_seat_override(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise StaffError("Body must be a JSON object")
    out: dict[str, Any] = {}
    if "displayName" in body and body.get("displayName") not in (None, ""):
        if not isinstance(body.get("displayName"), str):
            raise StaffError("displayName must be a string")
        name = " ".join(body["displayName"].split())
        if len(name) > 60:
            raise StaffError("displayName must be at most 60 characters")
        out["displayName"] = name
    if "brief" in body and body.get("brief") not in (None, ""):
        if not isinstance(body.get("brief"), str):
            raise StaffError("brief must be a string")
        text = body["brief"].strip()
        if len(text) > 2000:
            raise StaffError("brief must be at most 2000 characters")
        out["brief"] = text
    if "isActive" in body:
        out["isActive"] = bool(body.get("isActive"))
    if "modelTier" in body and body.get("modelTier") not in (None, ""):
        tier = str(body.get("modelTier"))
        if tier not in BOARD_STAFF_MODEL_TIERS:
            raise StaffError("modelTier must be desk or senior")
        out["modelTier"] = tier
    return out


def append_event_note(table: Any, task: dict[str, Any], text: str) -> dict[str, Any]:
    combined = _append_scratchpad(task, text)
    task["scratchpadKey"] = str(task.get("scratchpadKey") or _scratchpad_key(str(task["taskId"])))
    task["scratchpadChars"] = len(combined)
    task["updatedAt"] = board_store.now_iso()
    board_store.put_task(table, task)
    return task


def public_task(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in ("pk", "sk", "gsi1pk", "gsi1sk")}


def read_deliverable(task: dict[str, Any], *, limit: int = 6000) -> str:
    raw = _blob_get(str(task.get("deliverableKey") or "")).decode("utf-8", errors="replace")
    return raw[:limit]


def presign_deliverable(key: str) -> str:
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if not bucket or not key:
        return ""
    import runtime

    return runtime._s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=900,
    )
