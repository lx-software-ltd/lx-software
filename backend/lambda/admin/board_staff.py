"""Executive Board staff: seats, background tasks, steps and manager review.

See docs/architecture/executive-board-autonomy-implementation.md WP1.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import board_async
import board_budget
import board_personas
import board_store
import board_tools
from contract_constants import (
    BOARD_CHAIR_DEFAULT,
    BOARD_KEY,
    BOARD_PERSONA_IDS,
    BOARD_STAFF_DAILY_BUDGET_DEFAULT_USD,
    BOARD_STAFF_DELIVERABLE_MAX_BYTES,
    BOARD_STAFF_DELIVERABLE_TYPES,
    BOARD_STAFF_HELP_DEPTH_MAX,
    BOARD_STAFF_MAX_HELP_REQUESTS_PER_TASK,
    BOARD_STAFF_MAX_IDLE_STEPS_PER_TASK,
    BOARD_STAFF_MAX_REVISIONS,
    BOARD_STAFF_MAX_RUNNING_TASKS_DEFAULT,
    BOARD_STAFF_WAITING_EXPIRY_HOURS,
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
OWNER_HELD_CHILD_STATUSES = frozenset({"review", "needs_owner"})
_HELP_INTERNAL_TOOLS = frozenset({"board", "staff"})
_MEMORY_BLOBS: dict[str, bytes] = {}
_IDLE_TOOL_OPS = frozenset({"task_note"})
_IDLE_NUDGE = (
    "NUDGE: That step only wrote a note. Call a real tool next, or call "
    "task_finish with the deliverable. Notes-only steps burn the step budget."
)
_SALVAGE_MIN_CHARS = 200
_CANNOT_CALL_RE = re.compile(r"cannot call [`']?task_(?:note|finish)", re.I)
_PLACEHOLDER_RE = re.compile(r"\[(?:insert|todo|tbd|placeholder)[^\]]*\]", re.I)
_TEMPLATE_DATA_RE = re.compile(
    r"\bCampaign [A-C]\b|\bArticle [123]\b|\bSource [A-C]\b"
    r"|screenshot\d+\.png"
    r"|\b(?:123|456|789)\b.{0,40}\b(?:sessions|views|clicks)\b",
    re.I,
)
_CLAIMED_ACTION_RE = re.compile(
    r"\b(label|labelled|labeled|publish|published|reply|replied|create|created|"
    r"open|opened|send|sent|rebase|merge|sync|fast-forward|implement|implemented|fix|fixed)\b",
    re.I,
)
_EVIDENCE_REQUIRED_ORIGINS = frozenset({"event", "duty", "target"})
_EVIDENCE_TOOL_TOKENS = (
    "finance_cash_snapshot",
    "finance_aging_report",
    "finance_unit_economics",
    "aws_monthly_cost",
    "meta_ad_spend",
    "web_sessions",
    "web_conversions",
    "web_gtm_status",
)
# Briefs that name GA4 / visitor sources without the tool ids still require
# those reads — otherwise a seat finishes with "no analytics access" and the
# manager returns asking for a console login.
_EVIDENCE_BRIEF_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "web_sessions",
        (
            "ga4",
            "google analytics",
            "visitor source",
            "channel attribution",
            "session source",
        ),
    ),
    (
        "web_conversions",
        ("event tracking", "key events"),
    ),
    (
        "web_gtm_status",
        ("google tag manager", "gtm"),
    ),
)
_GA4_ASSIGN_ALIASES = (
    "ga4",
    "google analytics",
    "visitor source",
    "channel attribution",
    "session source",
    "event tracking",
    "google tag manager",
    "gtm",
)
RETRYABLE_STATUSES = frozenset({"failed", "needs_owner"})


class StaffError(ValueError):
    """Staff is disabled or the request is invalid."""

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.code = code


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
    parent_task_id: str | None = None,
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
    if parent_task_id:
        parent = board_store.get_task(table, parent_task_id)
        if not parent:
            raise StaffError("Parent task not found")
        depth = 1
        ancestor = parent
        while ancestor.get("parentTaskId"):
            depth += 1
            ancestor = board_store.get_task(table, str(ancestor.get("parentTaskId") or ""))
            if not ancestor:
                break
        if depth > BOARD_STAFF_HELP_DEPTH_MAX:
            raise StaffError("Help tasks cannot spawn further help")
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
        "parentTaskId": parent_task_id or None,
        "helpTaskIds": [],
        "helpRequests": 0,
        "blockedOn": [],
        "parkedAt": "",
        "parkedReason": "",
        "brief": text,
        "deliverableType": deliverable_type,
        "budgetUsd": budget,
        "slaAt": sla_at,
        "step": 0,
        "stepsUsed": 0,
        "idleSteps": 0,
        "attempt": 1,
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
    if action_id:
        _link_action_to_task(table, str(action_id), doc)
    if status == "queued":
        drain_queue(table, settings)
    return board_store.get_task(table, task_id) or doc


def _link_action_to_task(table: Any, action_id: str, task: dict[str, Any]) -> None:
    """Record on the founder action which staff task is working it (closed on accept)."""
    try:
        action = board_store.get_action(table, action_id)
        if not action or action.get("status") != "open":
            return
        action["assignee"] = str(task.get("assignee") or "")
        action["staffTaskId"] = str(task.get("taskId") or "")
        action["updatedAt"] = board_store.now_iso()
        board_store.put_action(table, action)
    except Exception as exc:
        _log_event("warning", tag="board_staff_action_link_failed", action_id=action_id, error=str(exc)[:200])


def _staff_daily_budget_exhausted(table: Any, settings: dict[str, Any]) -> str:
    staff_usage = board_store.load_staff_usage_day(table)
    staff_cap = float((settings.get("staff") or {}).get("dailyBudgetUsd") or BOARD_STAFF_DAILY_BUDGET_DEFAULT_USD)
    if staff_cap > 0 and float(staff_usage.get("cost") or 0) >= staff_cap:
        return f"Staff daily budget of USD {staff_cap:.2f} is exhausted"
    return ""


def drain_queue(table: Any, settings: dict[str, Any]) -> int:
    if not enabled(settings):
        return 0
    if _staff_daily_budget_exhausted(table, settings):
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
        try:
            board_async.invoke_async(
                {"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": task_id, "step": 1},
                fallback=run_step,
            )
        except Exception as exc:
            _log_event("error", tag="board_staff_step_invoke_failed", taskId=task_id, error=str(exc)[:300])
            _requeue_unstarted(table, task_id)
            continue
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
    return f"board/{BOARD_KEY}/staff/{task_id}/scratchpad.md"


def _deliverable_key(task_id: str, deliverable_type: str) -> str:
    ext = {"markdown": "md", "csv": "csv", "json": "json", "messages": "json"}.get(deliverable_type, "md")
    return f"board/{BOARD_KEY}/staff/{task_id}/deliverable.{ext}"


def _append_scratchpad(task: dict[str, Any], text: str) -> str:
    key = str(task.get("scratchpadKey") or _scratchpad_key(str(task["taskId"])))
    existing = _blob_get(key).decode("utf-8", errors="replace")
    combined = (existing + ("\n\n" if existing and text else "") + text).strip()
    if len(combined) > BOARD_STAFF_SCRATCHPAD_MAX_CHARS:
        combined = combined[-BOARD_STAFF_SCRATCHPAD_MAX_CHARS:]
    _blob_put(key, combined.encode("utf-8"))
    return combined


def _requeue_unstarted(table: Any, task_id: str) -> None:
    """Put a just-claimed running task back on the queue when the worker never started."""
    latest = board_store.get_task(table, task_id)
    if not latest or latest.get("status") != "running":
        return
    if int(latest.get("step") or 0) != 0:
        return
    latest["status"] = "queued"
    latest["startedAt"] = None
    latest.pop("stepClaimed", None)
    latest.pop("stepClaimedAt", None)
    latest["updatedAt"] = board_store.now_iso()
    board_store.put_task(table, latest)


def _finish_incomplete(table: Any, task: dict[str, Any], reason: str) -> dict[str, Any]:
    now = board_store.now_iso()
    updated = {
        **task,
        "status": "failed",
        "failureReason": reason[:300],
        "failureDetail": {
            "reason": reason[:300],
            "step": task.get("step"),
            "stepClaimed": task.get("stepClaimed"),
            "stepClaimedAt": task.get("stepClaimedAt"),
            "updatedAt": task.get("updatedAt"),
        },
        "finishedAt": now,
        "updatedAt": now,
        "expiresAt": int(datetime.now(timezone.utc).timestamp()) + BOARD_STAFF_RETENTION_DAYS * 86400,
    }
    board_store.put_task(table, updated)
    _log_event("warning", tag="board_staff_incomplete", taskId=task.get("taskId"), reason=reason[:200])
    _notify_parent_of_child(table, updated, f"help unavailable: {reason}")
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
    parked = _staff_daily_budget_exhausted(table, settings)
    if parked:
        _requeue_for_budget(table, task, wanted, parked)
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
    user = board_personas.render_task_frame(
        task,
        scratch,
        help_available=help_available_line(table, settings, task, roster=list(roster.values())),
    )
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
    require_finish = _should_require_finish(task)
    try:
        result = board_tools.run_tool_loop(
            ctx=ctx,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=model,
            timeout=min(90, BOARD_STAFF_STEP_MAX_SECONDS),
            max_tokens=4000 if require_finish else 2500,
            temperature=0.3,
            json_mode=False,
            tag="board_staff_step",
            max_seconds=BOARD_STAFF_STEP_MAX_SECONDS,
            require_op="task_finish" if require_finish else None,
        )
    except Exception as exc:
        _on_step_exception(table, task, payload, wanted, exc)
        return
    _complete_step(table, task_id, task, result, wanted)


def _is_retryable_step_error(exc: BaseException) -> bool:
    try:
        from openrouter_client import OpenRouterError
    except Exception:
        return True
    if not isinstance(exc, OpenRouterError) or exc.status is None:
        return True
    if exc.status == 402:
        return False
    if 400 <= exc.status < 500 and exc.status not in (408, 409, 425, 429):
        return False
    return True


def _trip_openrouter_credits(table: Any, exc: BaseException) -> None:
    try:
        from openrouter_client import OpenRouterError

        if not isinstance(exc, OpenRouterError) or exc.status != 402:
            return
        import board_breakers

        board_breakers.trip(table, "budget", f"OpenRouter 402: {exc}"[:200])
    except Exception as trip_exc:
        _log_event("warning", tag="board_staff_402_breaker_failed", error=str(trip_exc)[:200])


def _on_step_exception(
    table: Any,
    task: dict[str, Any],
    payload: dict[str, Any],
    wanted: int,
    exc: BaseException,
) -> None:
    task_id = str(task.get("taskId") or payload.get("taskId") or "")
    _log_event("error", tag="board_staff_step_failed", taskId=task_id, step=wanted, error=str(exc)[:300])
    latest = board_store.get_task(table, task_id) or task
    if latest.get("status") != "running":
        return
    _trip_openrouter_credits(table, exc)
    if _is_retryable_step_error(exc) and not payload.get("retried"):
        _release_step_claim(table, latest, wanted)
        board_async.invoke_async(
            {
                "internal": "board_staff_step",
                "boardKey": BOARD_KEY,
                "taskId": task_id,
                "step": wanted,
                "retried": True,
            },
            fallback=run_step,
        )
        return
    _finish_incomplete(table, latest, f"step error: {exc}"[:300])


def _requeue_for_budget(table: Any, task: dict[str, Any], claimed_step: int, reason: str) -> None:
    """Put a running task back on the queue when the daily cap is hit.

    The day resets; failing the task would make Retry a no-op until someone
    edits the row by hand.
    """
    latest = board_store.get_task(table, str(task.get("taskId") or "")) or task
    if latest.get("status") != "running":
        return
    latest["status"] = "queued"
    latest["stepClaimed"] = max(0, int(claimed_step) - 1)
    latest.pop("stepClaimedAt", None)
    latest["startedAt"] = None
    latest["updatedAt"] = board_store.now_iso()
    latest["parkedReason"] = reason[:300]
    board_store.put_task(table, latest)
    _log_event("warning", tag="board_staff_parked_budget", taskId=latest.get("taskId"), reason=reason[:200])


def _release_step_claim(table: Any, task: dict[str, Any], claimed_step: int) -> None:
    """Drop a held step claim so a retry (or a return verdict) can take it again."""
    latest = board_store.get_task(table, str(task.get("taskId") or "")) or task
    latest["stepClaimed"] = max(0, int(claimed_step) - 1)
    latest.pop("stepClaimedAt", None)
    latest["updatedAt"] = board_store.now_iso()
    board_store.put_task(table, latest)


def _align_step_claim(task: dict[str, Any]) -> None:
    """Make ``stepClaimed`` match the last completed step so the next seq can be claimed."""
    task["stepClaimed"] = int(task.get("step") or 0)
    task.pop("stepClaimedAt", None)


def _productive_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        c
        for c in calls
        if str(c.get("op") or "") not in _IDLE_TOOL_OPS and str(c.get("status") or "") == "ok"
    ]


def _norm_plan(text: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()[:400]


def _plans_similar(left: str, right: str) -> bool:
    a, b = _norm_plan(left), _norm_plan(right)
    if not a or not b:
        return False
    return a[:200] == b[:200]


def _should_require_finish(task: dict[str, Any]) -> bool:
    """Last idle step or last step: force the model to call task_finish."""
    idle = int(task.get("idleSteps") or 0)
    steps_used = int(task.get("step") or 0)
    return idle >= BOARD_STAFF_MAX_IDLE_STEPS_PER_TASK - 1 or steps_used >= BOARD_STAFF_MAX_STEPS_PER_TASK - 1


def _scratch_without_nudges(task_id: str, note: str) -> str:
    raw = _blob_get(_scratchpad_key(task_id)).decode("utf-8", errors="replace")
    lines = [line for line in (raw or "").splitlines() if not line.strip().startswith("NUDGE:")]
    text = "\n".join(lines).strip()
    extra = (note or "").strip()
    if extra and extra not in text:
        text = f"{text}\n\n{extra}".strip() if text else extra
    return text


def _looks_like_stuck_finish(text: str) -> bool:
    return bool(_CANNOT_CALL_RE.search(text or ""))


def _salvage_to_review(table: Any, latest: dict[str, Any], reason: str, note: str) -> bool:
    """Submit scratchpad prose as a low-confidence deliverable instead of failing.

    Seats sometimes dump the report in the step text and write that they cannot
    call task_note / task_finish. The work is still usable for manager review.
    """
    task_id = str(latest.get("taskId") or "")
    text = _scratch_without_nudges(task_id, note)
    if len(text) < _SALVAGE_MIN_CHARS:
        return False
    dtype = str(latest.get("deliverableType") or "markdown")
    key = _deliverable_key(task_id, dtype)
    encoded = text.encode("utf-8")
    _blob_put(key, encoded)
    flags = [str(f) for f in (latest.get("flags") or []) if f]
    for flag in ("salvaged", "no_evidence"):
        if flag not in flags:
            flags.append(flag)
    now = board_store.now_iso()
    latest["status"] = "review"
    latest["idleSteps"] = 0
    latest["summary"] = (note or text).strip()[:800]
    latest["confidence"] = "low"
    latest["flags"] = flags
    latest["deliverableKey"] = key
    latest["deliverableBytes"] = len(encoded)
    latest["deliverableType"] = dtype
    latest["openQuestions"] = [f"Salvaged after {reason}; no task_finish tool call."]
    latest["updatedAt"] = now
    _align_step_claim(latest)
    board_store.put_task(table, latest)
    settings = board_store.load_settings(table)
    if enabled(settings):
        board_async.invoke_async(
            {"internal": "board_staff_review", "boardKey": BOARD_KEY, "taskId": task_id},
            fallback=run_review,
        )
    _log_event("warning", tag="board_staff_salvaged", taskId=task_id, reason=reason[:200], chars=len(text))
    return True


def _task_attempt(task: dict[str, Any]) -> int:
    return max(1, int(task.get("attempt") or 1))


def _deliverable_has_placeholders(text: str) -> bool:
    raw = text or ""
    return bool(_PLACEHOLDER_RE.search(raw) or _TEMPLATE_DATA_RE.search(raw))


def _stamp_parked(task: dict[str, Any], *, reason: str, reset_clock: bool = True) -> None:
    now = board_store.now_iso()
    task["parkedReason"] = reason[:300]
    if reset_clock or not task.get("parkedAt"):
        task["parkedAt"] = now
    task["updatedAt"] = now


def _clear_parked(task: dict[str, Any]) -> None:
    task["blockedOn"] = []
    task["parkedReason"] = ""
    task["parkedAt"] = ""


def _park_waiting_approval(table: Any, task: dict[str, Any], approval_ids: list[str]) -> None:
    """Park ``task`` (the caller's in-memory row, including the step it just completed).

    Only the stored *status* is re-checked so a cancel that landed mid-step wins;
    the step counter, usage and scratchpad pointers come from ``task`` so the
    completed step is not lost and ``resume_after_approval`` continues from it.
    """
    stored = board_store.get_task(table, str(task.get("taskId") or ""))
    if stored is not None and stored.get("status") != "running":
        return
    if stored is None and task.get("status") != "running":
        return
    task["status"] = "waiting_approval"
    task["blockedOn"] = approval_ids
    task["idleSteps"] = 0
    _stamp_parked(task, reason=f"waiting on approval {','.join(approval_ids)}", reset_clock=True)
    _align_step_claim(task)
    board_store.put_task(table, task)
    _log_event("info", tag="board_staff_waiting_approval", taskId=task.get("taskId"), approvals=approval_ids)


def resume_after_approval(table: Any, settings: dict[str, Any], approval: dict[str, Any]) -> None:
    """Continue a task parked on a proposal once the founder decides it."""
    task_id = str((approval.get("context") or {}).get("taskId") or "")
    if not task_id:
        return
    task = board_store.get_task(table, task_id)
    if not task or task.get("status") != "waiting_approval":
        return
    pending = [
        a
        for a in board_store.list_approvals(table)
        if a.get("status") == "pending" and str((a.get("context") or {}).get("taskId") or "") == task_id
    ]
    if pending:
        task["blockedOn"] = [str(a.get("approvalId") or "") for a in pending if a.get("approvalId")]
        task["updatedAt"] = board_store.now_iso()
        board_store.put_task(table, task)
        return
    if str(approval.get("op") or "") == "task_request_help" and approval.get("status") in (
        "rejected",
        "failed",
    ):
        if approval.get("status") == "rejected":
            note = "HELP: founder declined the help request. Finish with what you have; set confidence low."
        else:
            err = str(approval.get("errorMessage") or "execution failed")[:200]
            note = f"HELP: the help request failed ({err}). Finish with what you have; set confidence low."
        _append_scratchpad(task, note)
        task["scratchpadKey"] = _scratchpad_key(str(task.get("taskId") or ""))
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
                "taskId": task_id,
                "step": int(task.get("step") or 0) + 1,
            },
            fallback=run_step,
        )


def _brief_has_alias(lower: str, alias: str) -> bool:
    if " " in alias or "_" in alias:
        return alias in lower
    return bool(re.search(rf"\b{re.escape(alias)}\b", lower))


def _brief_required_evidence_tools(brief: str, *, offered: set[str] | None = None) -> list[str]:
    lower = (brief or "").lower()
    needed: list[str] = []
    seen: set[str] = set()
    for token in _EVIDENCE_TOOL_TOKENS:
        if token in lower and token not in seen:
            needed.append(token)
            seen.add(token)
    for tool, aliases in _EVIDENCE_BRIEF_ALIASES:
        if tool in seen:
            continue
        if any(_brief_has_alias(lower, alias) for alias in aliases):
            needed.append(tool)
            seen.add(tool)
    if offered is not None:
        needed = [tool for tool in needed if tool in offered]
    return needed


def _offered_task_ops(ctx: board_tools.ToolContext) -> set[str]:
    roster = seats_by_id(ctx.table, ctx.settings) if ctx.seat_id else None
    return {
        op.name
        for op, _ in board_tools.available_ops(
            ctx.settings,
            ctx.persona_id,
            context="task",
            seat_id=ctx.seat_id,
            seats_by_id=roster,
        )
    }


def _evidence_task_ids(task: dict[str, Any]) -> list[str]:
    ids = [str(task.get("taskId") or "")]
    for hid in task.get("helpTaskIds") or []:
        hid_s = str(hid or "")
        if hid_s and hid_s not in ids:
            ids.append(hid_s)
    return [tid for tid in ids if tid]


def _call_evidence_aliases(call: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for key in ("callId", "toolCallId", "tool_call_id"):
        value = str(call.get(key) or "").strip()
        if value:
            aliases.add(value)
    return aliases


def _known_evidence_ids(table: Any, task: dict[str, Any]) -> set[str]:
    known: set[str] = set()
    for tid in _evidence_task_ids(task):
        for call in board_store.list_tool_calls_for_task(table, tid):
            known.update(_call_evidence_aliases(call))
        for step in board_store.list_task_steps(table, tid):
            for cid in step.get("callIds") or []:
                if cid:
                    known.add(str(cid))
    return known


def _cited_evidence_ops(table: Any, task: dict[str, Any], evidence: list[str]) -> set[str]:
    wanted = set(evidence)
    ops: set[str] = set()
    for tid in _evidence_task_ids(task):
        for call in board_store.list_tool_calls_for_task(table, tid):
            if wanted & _call_evidence_aliases(call):
                op = str(call.get("op") or "")
                if op:
                    ops.add(op)
    return ops


def _canonical_evidence_ids(table: Any, task: dict[str, Any], evidence: list[str]) -> list[str]:
    alias_to_id: dict[str, str] = {}
    for tid in _evidence_task_ids(task):
        for call in board_store.list_tool_calls_for_task(table, tid):
            cid = str(call.get("callId") or "").strip()
            if not cid:
                continue
            for alias in _call_evidence_aliases(call):
                alias_to_id.setdefault(alias, cid)
        for step in board_store.list_task_steps(table, tid):
            for cid in step.get("callIds") or []:
                value = str(cid or "").strip()
                if value:
                    alias_to_id.setdefault(value, value)
    out: list[str] = []
    seen: set[str] = set()
    for raw in evidence:
        cid = alias_to_id.get(str(raw))
        if cid and cid not in seen:
            out.append(cid)
            seen.add(cid)
    return out


def _offered_evidence_ops(ctx: board_tools.ToolContext, task: dict[str, Any]) -> set[str]:
    offered = _offered_task_ops(ctx)
    roster = seats_by_id(ctx.table, ctx.settings)
    for hid in task.get("helpTaskIds") or []:
        child = board_store.get_task(ctx.table, str(hid))
        if not child:
            continue
        seat_id = str(child.get("assignee") or "") if child.get("assigneeKind") == "seat" else ""
        persona_id = (
            str(child.get("managerId") or "")
            if child.get("assigneeKind") == "seat"
            else str(child.get("assignee") or "")
        )
        offered |= {
            op.name
            for op, _ in board_tools.available_ops(
                ctx.settings,
                persona_id,
                context="task",
                seat_id=seat_id,
                seats_by_id=roster if seat_id else None,
            )
        }
    return offered


def preferred_assignee_for_brief(
    table: Any, settings: dict[str, Any], brief: str
) -> str | None:
    """Active seat that should own a GA4 / visitor-source brief, if any."""
    lower = (brief or "").lower()
    if not any(_brief_has_alias(lower, alias) for alias in _GA4_ASSIGN_ALIASES):
        return None
    roster = seats_by_id(table, settings)
    for seat_id in ("data-analyst", "business-analyst"):
        seat = roster.get(seat_id)
        if seat and seat.get("isActive"):
            return seat_id
    return None


def ga4_assignee_hint(table: Any, settings: dict[str, Any]) -> str:
    roster = seats_by_id(table, settings)
    if roster.get("data-analyst", {}).get("isActive"):
        target = "data-analyst"
    elif roster.get("business-analyst", {}).get("isActive"):
        target = "business-analyst"
    else:
        target = "an executive with web read"
    return (
        f"GA4 / visitor sources / event tracking / GTM: assign {target}. "
        "Do not assign community-manager."
    )


def _remaining_sla_hours(task: dict[str, Any]) -> int:
    raw = str(task.get("slaAt") or "")
    try:
        sla = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return 24
    hours = (sla - datetime.now(timezone.utc)).total_seconds() / 3600.0
    return max(1, min(168, int(hours)))


def _seat_covers_tools(seat: dict[str, Any], tool_ids: list[str]) -> bool:
    levels = seat.get("effectiveLevels") or {}
    return all(str(levels.get(tid) or "off") != "off" for tid in tool_ids)


def _persona_covers_tools(settings: dict[str, Any], persona_id: str, tool_ids: list[str]) -> bool:
    return all(board_tools.effective_level(settings, tid, persona_id) != "off" for tid in tool_ids)


def _normalize_help_tool_ids(raw: Any) -> list[str]:
    ids: list[str] = []
    items = raw if isinstance(raw, list) else []
    for item in items:
        tid = str(item or "").strip()
        if tid and tid in BOARD_TOOL_IDS and tid not in _HELP_INTERNAL_TOOLS and tid not in ids:
            ids.append(tid)
    return ids


def pick_helper(
    table: Any,
    settings: dict[str, Any],
    parent: dict[str, Any],
    tool_ids: list[str],
    suggested: str = "",
) -> tuple[str, str]:
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


def prepare_help_request(ctx: board_tools.ToolContext, args: dict[str, Any]) -> dict[str, Any]:
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
    tool_ids = _normalize_help_tool_ids(args.get("toolIds"))
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
    if all(tid in offered_tools for tid in tool_ids):
        raise StaffError("You already have those tools; call them on this task instead of requesting help")
    suggested = str(args.get("suggestedAssignee") or "").strip()
    assignee, kind = pick_helper(ctx.table, ctx.settings, parent, tool_ids, suggested)
    manager_id = str(parent.get("managerId") or "")
    staff_level = board_tools.effective_level(ctx.settings, "staff", manager_id)
    if not board_tools.allows(staff_level, "propose"):
        raise StaffError("Your manager cannot assign staff help. Finish with unavailable.")
    return {
        "parent": parent,
        "need": need,
        "toolIds": tool_ids,
        "assignee": assignee,
        "assigneeKind": kind,
        "staffLevel": staff_level,
    }


def validate_task_request_help(ctx: board_tools.ToolContext, args: dict[str, Any]) -> str | None:
    try:
        prepare_help_request(ctx, args)
    except StaffError as exc:
        return str(exc)
    return None


def act_guard_task_request_help(ctx: board_tools.ToolContext, _args: dict[str, Any]) -> str | None:
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


def op_task_request_help(ctx: board_tools.ToolContext, args: dict[str, Any]) -> dict[str, Any]:
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


def preview_task_request_help(ctx: board_tools.ToolContext, args: dict[str, Any]) -> dict[str, Any] | None:
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
            if tid not in _HELP_INTERNAL_TOOLS and board_tools.effective_level(settings, tid, self_id) != "off"
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
    for hid in list(parent.get("helpTaskIds") or []):
        child = board_store.get_task(table, str(hid))
        if not child or child.get("status") in TERMINAL_STATUSES:
            continue
        cancel_task(table, str(hid), by_sub, notify_parent=False)


def _expire_help_wait(table: Any, settings: dict[str, Any], task: dict[str, Any]) -> None:
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


def _complete_step(table: Any, task_id: str, task: dict[str, Any], result: Any, wanted: int) -> None:
    usage = result.usage or {}
    latest = board_store.get_task(table, task_id) or task
    status = str(latest.get("status") or "")
    if status not in ("running", "review", "needs_owner", "delivered", "waiting_subtask", "waiting_approval"):
        return
    latest["usage"] = _task_usage_add(latest, usage)
    note = (result.text or "").strip()
    if note:
        combined = _append_scratchpad(latest, note)
        latest["scratchpadKey"] = _scratchpad_key(task_id)
        latest["scratchpadChars"] = len(combined)
    already = int(latest.get("step") or 0) >= wanted
    seq = wanted if already else int(latest.get("step") or 0) + 1
    calls = list(result.calls or [])
    board_store.put_task_step(
        table,
        task_id,
        {
            "seq": seq,
            "attempt": _task_attempt(latest),
            "plan": note[:2000],
            "callIds": [c.get("callId") for c in calls if c.get("callId")],
            "usage": usage,
            "at": board_store.now_iso(),
        },
    )
    if not already:
        latest["step"] = seq
        latest["stepsUsed"] = seq
    latest["updatedAt"] = board_store.now_iso()
    latest["stuckRetried"] = False
    if status in ("review", "needs_owner", "delivered", "waiting_subtask", "waiting_approval"):
        latest["idleSteps"] = 0
        board_store.patch_task_if_status(
            table,
            task_id,
            status,
            {
                "usage": latest["usage"],
                "step": latest["step"],
                "stepsUsed": latest["stepsUsed"],
                "idleSteps": 0,
                "scratchpadKey": latest.get("scratchpadKey") or "",
                "scratchpadChars": latest.get("scratchpadChars") or 0,
                "updatedAt": latest["updatedAt"],
                "stuckRetried": False,
            },
        )
        return
    approval_ids = [
        str(c.get("approvalId"))
        for c in calls
        if str(c.get("status") or "") == "pending_approval" and c.get("approvalId")
    ]
    if approval_ids:
        _park_waiting_approval(table, latest, approval_ids)
        return
    similar_to_last = False
    if seq > 1:
        prior = board_store.list_task_steps(table, task_id)
        if len(prior) >= 2:
            similar_to_last = _plans_similar(note, str(prior[-2].get("plan") or ""))
    if not _productive_calls(calls) or similar_to_last:
        idle = int(latest.get("idleSteps") or 0) + 1
        latest["idleSteps"] = idle
        combined = _append_scratchpad(latest, _IDLE_NUDGE)
        latest["scratchpadKey"] = _scratchpad_key(task_id)
        latest["scratchpadChars"] = len(combined)
        if _looks_like_stuck_finish(note) and _salvage_to_review(table, latest, "missing task_finish call", note):
            return
        if idle >= BOARD_STAFF_MAX_IDLE_STEPS_PER_TASK:
            if _salvage_to_review(table, latest, "idle step limit", note):
                return
            _finish_incomplete(table, latest, "idle step limit")
            return
    else:
        latest["idleSteps"] = 0
    if seq >= BOARD_STAFF_MAX_STEPS_PER_TASK:
        if _salvage_to_review(table, latest, "step limit", note):
            return
        _finish_incomplete(table, latest, "step limit")
        return
    board_store.put_task(table, latest)
    board_async.invoke_async(
        {"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": task_id, "step": seq + 1},
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
        parent = board_store.get_task(ctx.table, str(task.get("parentTaskId") or ""))
        if not parent or parent.get("assignee") != ctx.seat_id:
            raise StaffError("You cannot read another seat's deliverable")
    evidence = _child_evidence_records(ctx.table, task)
    return {
        "summary": task.get("summary") or "",
        "deliverable": read_deliverable(task, limit=6000),
        "deliverableType": task.get("deliverableType"),
        "status": task.get("status"),
        "evidence": [row["callId"] for row in evidence],
        "evidenceCalls": evidence,
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
        prior = str(cancelled.get("failureReason") or "").strip()
        extra = f"{ctx.persona_id or ctx.owner_sub}: {reason}"
        cancelled["failureReason"] = (f"{prior}; {extra}" if prior else f"cancelled by {extra}")[:300]
        board_store.put_task(ctx.table, cancelled)
    return public_task(cancelled)


def _require_running_task(task: dict[str, Any] | None) -> dict[str, Any]:
    if not task:
        raise StaffError("Task not found")
    status = str(task.get("status") or "")
    if status != "running":
        raise StaffError(f"Task is {status}; wait for it to resume before continuing")
    return task


def op_task_note(ctx: board_tools.ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task = _require_running_task(board_store.get_task(ctx.table, ctx.task_id))
    text = str(args.get("text") or "").strip()
    combined = _append_scratchpad(task, text)
    task["scratchpadKey"] = _scratchpad_key(ctx.task_id)
    task["scratchpadChars"] = len(combined)
    task["updatedAt"] = board_store.now_iso()
    board_store.put_task(ctx.table, task)
    return {"ok": True, "chars": len(combined)}


def op_task_finish(ctx: board_tools.ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task = _require_running_task(board_store.get_task(ctx.table, ctx.task_id))
    deliverable = str(args.get("deliverable") or "")
    encoded = deliverable.encode("utf-8")
    if len(encoded) > BOARD_STAFF_DELIVERABLE_MAX_BYTES:
        raise StaffError(
            f"deliverable is larger than {BOARD_STAFF_DELIVERABLE_MAX_BYTES} bytes; split it"
        )
    if _deliverable_has_placeholders(deliverable):
        raise StaffError(
            "Deliverable still has placeholder text such as [Insert …]. "
            "Call finance_cash_snapshot, finance_aging_report, aws_monthly_cost and "
            "meta_ad_spend (or finance_unit_economics), then write the verified figures. "
            "If a tool cannot verify a number, write 'unavailable' and why."
        )
    evidence = [str(x) for x in (args.get("evidence") or []) if isinstance(x, (str, int))]
    known = _known_evidence_ids(ctx.table, task)
    attempt = _task_attempt(task)
    evidence = _canonical_evidence_ids(ctx.table, task, [e for e in evidence if e in known])
    needed = _brief_required_evidence_tools(
        str(task.get("brief") or ""), offered=_offered_evidence_ops(ctx, task)
    )
    cited = _cited_evidence_ops(ctx.table, task, evidence)
    missing = [tool for tool in needed if tool not in cited]
    if missing:
        borrowed = bool(task.get("helpTaskIds"))
        hint = (
            " Cite the help task's EVIDENCE call ids from the scratchpad "
            "(or staff_get_deliverable)."
            if borrowed
            else " Call those tools first and pass their call ids in evidence."
        )
        raise StaffError("This brief requires evidence from " + ", ".join(needed) + "." + hint)
    confidence = str(args.get("confidence") or "medium")
    flags = list(task.get("flags") or [])
    if not evidence and confidence == "high":
        confidence = "medium"
        flags.append("no_evidence")
    dtype = str(args.get("deliverableType") or task.get("deliverableType") or "markdown")
    key = _deliverable_key(ctx.task_id, dtype)
    _blob_put(key, encoded)
    now = board_store.now_iso()
    seq = int(task.get("step") or 0) + 1
    board_store.put_task_step(
        ctx.table,
        ctx.task_id,
        {
            "seq": seq,
            "attempt": attempt,
            "plan": str(args.get("summary") or "")[:2000],
            "callIds": evidence,
            "at": now,
        },
    )
    updated = {
        **task,
        "status": "review",
        "step": seq,
        "stepsUsed": seq,
        "idleSteps": 0,
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
    _align_step_claim(updated)
    board_store.put_task(ctx.table, updated)
    if enabled(ctx.settings):
        board_async.invoke_async(
            {"internal": "board_staff_review", "boardKey": BOARD_KEY, "taskId": ctx.task_id},
            fallback=run_review,
        )
    return {"ok": True, "status": "review", "deliverableKey": key}


def _review_user_prompt(task: dict[str, Any], raw: str, evidence_lines: list[str]) -> str:
    """User message for the manager review call."""
    return (
        f"You are reviewing work assigned to {task.get('assignee')}.\n"
        f"Brief: {task.get('brief')}\n"
        f"Deliverable type: {task.get('deliverableType')}\n"
        f"Confidence: {task.get('confidence')}\n"
        f"Evidence:\n" + ("\n".join(evidence_lines) or "(none)") + "\n\n"
        f"Deliverable:\n{raw}\n\n"
        "Books of record: there is no QuickBooks or Xero. This board is Siu Tin Dei "
        "only. For receivables aging, accept a report backed by finance_aging_report "
        "(including zero outstanding or a Data API not-configured error from that tool). "
        "Cash and Siu Tin Dei statement-book flow come from finance_cash_snapshot; AWS "
        "from aws_monthly_cost; Meta from meta_ad_spend or finance_unit_economics. Return "
        "if the deliverable reports the LX Software statement book or other houses as "
        "Siu Tin Dei product P&L. Return if the deliverable still has "
        "[Insert …] placeholders or 0-30/31-60 aging buckets instead of current / D+7 / "
        "D+21 / D+35. Accept a memo that states a figure is unavailable with the tool error. "
        "Do not return asking for accounting software or credentials.\n"
        "If the deliverable claims an action (label, publish, reply, create, send, rebase, merge, sync, implement, fix) "
        "and Evidence is (none), you MUST return.\n"
        "If the deliverable uses Campaign A / Article 1 / screenshotN.png template data, return.\n"
        "Visitor sources and tracking: proof is web_sessions (referrers / sessionSource), "
        "web_conversions (events), and web_gtm_status when GTM is in the brief. Zero "
        "sessions or empty referrers is a valid connected result. A not-configured or "
        "WebError from those tools is a valid unavailable. Do not return asking for GA4 "
        "console access, analytics credentials, or direct access to analytics tools.\n"
        "Evidence tagged (via seat, task id) was gathered by a help subtask; accept it "
        "as if the assignee called those tools.\n"
        'Return JSON {"verdict":"accept"|"return","notes":"…"}.'
    )


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
    cited = set(task.get("evidence") or [])
    evidence_lines: list[str] = []
    for call in board_store.list_tool_calls_for_task(table, task_id):
        if str(call.get("callId")) in cited:
            evidence_lines.append(f"- {call.get('op')}: {call.get('summary')}")
    for hid in task.get("helpTaskIds") or []:
        child = board_store.get_task(table, str(hid))
        via = str((child or {}).get("assignee") or "helper")
        for call in board_store.list_tool_calls_for_task(table, str(hid)):
            if str(call.get("callId")) in cited:
                evidence_lines.append(
                    f"- {call.get('op')} (via {via}, task {hid}): {call.get('summary')}"
                )
    prompt = _review_user_prompt(task, raw, evidence_lines)
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
        if _should_hold_unverified_accept(table, task):
            task["status"] = "needs_owner"
            task["finishedAt"] = None
            board_store.put_task(table, task)
            _note_parent_if_child_needs_owner(table, task)
            return task
        return _accept_task(table, task, now)
    revisions = int(task.get("revisions") or 0)
    is_owner = str(by or "").startswith("owner")
    is_final = revisions >= BOARD_STAFF_MAX_REVISIONS
    if is_owner or is_final:
        try:
            import board_lessons

            board_lessons.create_from_return(table, task)
        except Exception as exc:
            _log_event("warning", tag="board_lesson_from_return_failed", error=str(exc)[:200])
    if revisions < BOARD_STAFF_MAX_REVISIONS:
        _append_scratchpad(task, f"MANAGER NOTES: {notes}")
        task["revisions"] = revisions + 1
        task["status"] = "running"
        task["idleSteps"] = 0
        task["failureReason"] = ""
        _align_step_claim(task)
        board_store.put_task(table, task)
        board_async.invoke_async(
            {
                "internal": "board_staff_step",
                "boardKey": BOARD_KEY,
                "taskId": task["taskId"],
                "step": int(task.get("step") or 0) + 1,
            },
            fallback=run_step,
        )
        return task
    task["status"] = "needs_owner"
    task["finishedAt"] = None
    board_store.put_task(table, task)
    _note_parent_if_child_needs_owner(table, task)
    return task


def _task_attempted_required_tools(table: Any, task: dict[str, Any]) -> bool:
    """True when the seat called every tool the brief names, even if those calls errored."""
    needed = _brief_required_evidence_tools(str(task.get("brief") or ""))
    if not needed:
        return False
    task_id = str(task.get("taskId") or "")
    if not task_id:
        return False
    ops: set[str] = set()
    for call in board_store.list_tool_calls_for_task(table, task_id):
        op = str(call.get("op") or "")
        if op and op not in _IDLE_TOOL_OPS:
            ops.add(op)
    return all(tool in ops for tool in needed)


def _note_parent_if_child_needs_owner(table: Any, task: dict[str, Any]) -> None:
    if not task.get("parentTaskId") or task.get("status") != "needs_owner":
        return
    notes = str((task.get("lastReview") or {}).get("notes") or "").strip()
    extra = f" Last review: {notes[:200]}" if notes else ""
    _note_parent_child_waiting(
        table,
        task,
        f"HELP: task {task.get('taskId')} is waiting for founder review.{extra} "
        "Stay parked until the founder accepts or cancels that help task.",
        reason=f"help task {task.get('taskId')} needs founder review",
    )


def _should_hold_unverified_accept(table: Any, task: dict[str, Any]) -> bool:
    flags = {str(f) for f in (task.get("flags") or [])}
    if "no_evidence" not in flags and "salvaged" not in flags:
        return False
    if "salvaged" not in flags and _task_attempted_required_tools(table, task):
        return False
    if str(task.get("origin") or "") in _EVIDENCE_REQUIRED_ORIGINS:
        return True
    brief = str(task.get("brief") or "")
    return bool(_CLAIMED_ACTION_RE.search(brief))


def _task_has_open_approvals(table: Any, task: dict[str, Any]) -> bool:
    task_id = str(task.get("taskId") or "")
    if not task_id:
        return False
    blocked = [str(x) for x in (task.get("blockedOn") or []) if x]
    if blocked:
        return True
    for approval in board_store.list_approvals(table):
        if str(approval.get("status") or "") != "pending":
            continue
        ctx = approval.get("context") or {}
        if str(ctx.get("taskId") or "") == task_id:
            return True
    return False


def _should_close_linked_action(table: Any, task: dict[str, Any]) -> bool:
    flags = {str(f) for f in (task.get("flags") or [])}
    if flags & {"no_evidence", "salvaged", "staging_behind"}:
        return False
    if _task_has_open_approvals(table, task):
        return False
    return True


def _accept_task(table: Any, task: dict[str, Any], now: str) -> dict[str, Any]:
    last = task.get("lastReview") or {}
    if last.get("verdict") and last.get("verdict") != "accept":
        task["status"] = "needs_owner"
        task["finishedAt"] = None
        task["updatedAt"] = now
        board_store.put_task(table, task)
        _note_parent_if_child_needs_owner(table, task)
        return task
    if _should_hold_unverified_accept(table, task):
        task["status"] = "needs_owner"
        task["finishedAt"] = None
        task["updatedAt"] = now
        board_store.put_task(table, task)
        _note_parent_if_child_needs_owner(table, task)
        return task
    ref = task.get("eventRef") or {}
    if ref.get("kind") == "ops" and str(ref.get("id") or "") == "rebase-staging":
        try:
            import board_code

            still = board_code.staging_still_behind()
        except Exception as exc:
            still = {"error": str(exc)[:200], "behindBy": "?"}
        if still:
            flags = [str(f) for f in (task.get("flags") or [])]
            if "staging_behind" not in flags:
                flags.append("staging_behind")
            task["flags"] = flags
            questions = [str(q) for q in (task.get("openQuestions") or []) if q]
            if still.get("error"):
                note = f"could not verify staging vs main: {still.get('error')}"
            else:
                note = f"staging is still {still.get('behindBy')} commit(s) behind main"
            if note not in questions:
                questions.append(note)
            task["openQuestions"] = questions
            task["status"] = "needs_owner"
            task["finishedAt"] = None
            task["updatedAt"] = now
            board_store.put_task(table, task)
            _note_parent_if_child_needs_owner(table, task)
            return task
    task["status"] = "delivered"
    task["finishedAt"] = now
    task["expiresAt"] = int(datetime.now(timezone.utc).timestamp()) + BOARD_STAFF_RETENTION_DAYS * 86400
    action_id = task.get("actionId")
    dtype = str(task.get("deliverableType") or "")
    if action_id and dtype in ("markdown", "csv", "json", "issues", "pr") and _should_close_linked_action(table, task):
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
    if task.get("parentTaskId"):
        _resume_parent_after_help(
            table,
            board_store.load_settings(table),
            str(task.get("parentTaskId") or ""),
            "help delivered",
            child=task,
            success=True,
        )
        return task
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


def retry_task(table: Any, settings: dict[str, Any], task_id: str, by_sub: str) -> dict[str, Any]:
    """Re-queue a failed task with the same brief so the seat can try again."""
    task = board_store.get_task(table, task_id)
    if not task:
        raise StaffError("Task not found", code="not_found")
    if task.get("status") not in RETRYABLE_STATUSES:
        raise StaffError("Only failed or needs_owner tasks can be retried", code="conflict")
    try:
        _resolve_assignee(table, settings, str(task.get("assignee") or ""))
    except StaffError as exc:
        raise StaffError(str(exc), code="conflict") from exc
    action_id = str(task.get("actionId") or "")
    if action_id:
        action = board_store.get_action(table, action_id)
        if action and action.get("status") != "open":
            raise StaffError("Linked action is closed", code="conflict")
    now = board_store.now_iso()
    previous = dict(task.get("usage") or {})
    task["status"] = "queued"
    task["step"] = 0
    task["stepsUsed"] = 0
    task["idleSteps"] = 0
    task["attempt"] = _task_attempt(task) + 1
    task["revisions"] = 0
    task["previousUsage"] = previous
    task["usage"] = {"promptTokens": 0, "completionTokens": 0, "cost": 0.0, "calls": 0}
    task["failureReason"] = ""
    task["parkedReason"] = ""
    task["finishedAt"] = None
    task["startedAt"] = None
    task["reviewRetried"] = False
    task["stuckRetried"] = False
    task.pop("stepClaimed", None)
    task.pop("stepClaimedAt", None)
    task["updatedAt"] = now
    task["retriedBy"] = by_sub
    task["retriedAt"] = now
    _cancel_open_help_children(table, task, by_sub)
    _clear_parked(task)
    task["helpRequests"] = 0
    board_store.put_task(table, task)
    if enabled(settings):
        drain_queue(table, settings)
    return board_store.get_task(table, task_id) or task


def cancel_task(table: Any, task_id: str, by_sub: str, *, notify_parent: bool = True) -> dict[str, Any]:
    task = board_store.get_task(table, task_id)
    if not task:
        raise StaffError("Task not found")
    status = str(task.get("status") or "")
    if status == "cancelled":
        return task
    if status == "delivered":
        raise StaffError("Delivered tasks cannot be cancelled", code="conflict")
    now = board_store.now_iso()
    if status == "failed":
        task["cancelledFrom"] = "failed"
        prior = str(task.get("failureReason") or "").strip()
        task["failureReason"] = (f"{prior}; cancelled by {by_sub}" if prior else f"cancelled by {by_sub}")[:300]
    else:
        task["failureReason"] = f"cancelled by {by_sub}"
    task["status"] = "cancelled"
    task["finishedAt"] = now
    task["updatedAt"] = now
    task["expiresAt"] = int(datetime.now(timezone.utc).timestamp()) + BOARD_STAFF_RETENTION_DAYS * 86400
    board_store.put_task(table, task)
    try:
        import board_duties

        board_duties.forget_seen_for_task(table, task)
    except Exception as exc:
        _log_event("warning", tag="board_staff_forget_seen_failed", error=str(exc)[:200])
    _cancel_open_help_children(table, task, by_sub)
    if notify_parent:
        _notify_parent_of_child(table, task, f"help unavailable: cancelled by {by_sub}")
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
        import board_duties

        board_duties.run_due(table, settings)
    except Exception as exc:
        _log_event("warning", tag="board_duties_tick_failed", error=str(exc)[:300])
    try:
        import board_code

        board_code.handle_tick(table, settings)
    except Exception as exc:
        _log_event("warning", tag="board_code_tick_failed", error=str(exc)[:300])
    try:
        import board_meeting

        board_meeting.maybe_retry_failed_schedule(table, settings)
    except Exception as exc:
        _log_event("warning", tag="board_meeting_retry_failed", error=str(exc)[:300])
    try:
        expire_waiting_help(table, settings)
    except Exception as exc:
        _log_event("warning", tag="board_staff_help_expiry_failed", error=str(exc)[:300])
    started = drain_queue(table, settings)
    stuck_cut = datetime.now(timezone.utc) - timedelta(seconds=BOARD_STAFF_TASK_STUCK_SECONDS)
    cut_iso = _utc_iso_z(stuck_cut)
    # AdminApiFn timeout is 300 s; only re-invoke after that plus a margin so
    # a live hung step cannot race a replacement invocation.
    claim_stale_cut = datetime.now(timezone.utc) - timedelta(seconds=BOARD_STAFF_STEP_MAX_SECONDS + 180)
    claim_stale_iso = _utc_iso_z(claim_stale_cut)
    for task in board_store.list_tasks(table, "running"):
        claimed_at = str(task.get("stepClaimedAt") or "")
        updated = str(task.get("updatedAt") or "")
        claim_is_stale = bool(claimed_at and claimed_at < claim_stale_iso)
        # Drain promotes queued→running without stepClaimedAt. If the Event
        # invoke never ran, retry once the same way as a hung claim.
        never_started = (not claimed_at) and int(task.get("step") or 0) == 0 and updated < claim_stale_iso
        if (claim_is_stale or never_started) and not task.get("stuckRetried"):
            wanted = int(task.get("step") or 0) + 1
            _release_step_claim(table, task, wanted)
            latest = board_store.get_task(table, str(task.get("taskId") or "")) or task
            latest["stuckRetried"] = True
            latest["updatedAt"] = board_store.now_iso()
            board_store.put_task(table, latest)
            try:
                board_async.invoke_async(
                    {
                        "internal": "board_staff_step",
                        "boardKey": BOARD_KEY,
                        "taskId": latest.get("taskId"),
                        "step": wanted,
                    },
                    fallback=run_step,
                )
            except Exception as exc:
                _log_event(
                    "error",
                    tag="board_staff_stuck_reinvoke_failed",
                    taskId=latest.get("taskId"),
                    error=str(exc)[:300],
                )
        elif (claim_is_stale or never_started or updated < claim_stale_iso) and task.get("stuckRetried"):
            _finish_incomplete(table, task, "stuck")
        elif updated < cut_iso:
            _finish_incomplete(table, task, "stuck")
    for task in board_store.list_tasks(table, "review"):
        if str(task.get("updatedAt") or "") < cut_iso:
            if not task.get("reviewRetried"):
                task["reviewRetried"] = True
                task["updatedAt"] = board_store.now_iso()
                board_store.put_task(table, task)
                board_async.invoke_async(
                    {"internal": "board_staff_review", "boardKey": BOARD_KEY, "taskId": task["taskId"]},
                    fallback=run_review,
                )
            else:
                task["status"] = "needs_owner"
                task["updatedAt"] = board_store.now_iso()
                board_store.put_task(table, task)
                _note_parent_if_child_needs_owner(table, task)
    return {"ok": True, "started": started}


def list_tasks_for_api(
    table: Any,
    *,
    status: str | None = None,
    assignee: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if status == "done":
        status = "delivered"
    if status:
        items = board_store.list_tasks(table, status, limit=max(limit, 50))
        if assignee:
            items = [t for t in items if t.get("assignee") == assignee]
        items.sort(key=lambda t: str(t.get("slaAt") or t.get("createdAt") or ""))
        return items[:limit]
    inflight: list[dict[str, Any]] = []
    for st in NON_TERMINAL_STATUSES:
        inflight.extend(board_store.list_tasks(table, st, limit=200))
    inflight.sort(key=lambda t: str(t.get("slaAt") or t.get("createdAt") or ""))
    failed = board_store.list_tasks(table, "failed", limit=50)
    failed.sort(key=lambda t: str(t.get("finishedAt") or t.get("updatedAt") or ""), reverse=True)
    delivered = board_store.list_tasks(table, "delivered", limit=30)
    cancelled = board_store.list_tasks(table, "cancelled", limit=10)
    terminal = delivered + cancelled
    terminal.sort(key=lambda t: str(t.get("finishedAt") or t.get("updatedAt") or ""), reverse=True)
    if assignee:
        inflight = [t for t in inflight if t.get("assignee") == assignee]
        failed = [t for t in failed if t.get("assignee") == assignee]
        terminal = [t for t in terminal if t.get("assignee") == assignee]
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for row in (*failed, *inflight, *terminal):
        tid = str(row.get("taskId") or "")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        items.append(row)
        if len(items) >= limit:
            break
    return items


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
    for status in ("queued", "running", "waiting_approval", "waiting_subtask", "review"):
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
            "brief": minutes_action_brief(action),
            "deliverableType": "markdown",
            "slaHours": 24,
            "actionId": action.get("actionId"),
            "reason": "Assigned in the board minutes.",
        },
    )


def minutes_action_brief(action: dict[str, Any]) -> str:
    """Task brief for a founder action: title, what done looks like, and the metric."""
    parts = [str(action.get("title") or "").strip()]
    detail = str(action.get("detail") or "").strip()
    if detail:
        parts.append(f"Done looks like: {detail}")
    metric = str(action.get("metric") or "").strip()
    if metric:
        parts.append(f"Success metric: {metric}")
    return "\n".join(parts)[:4000]


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
