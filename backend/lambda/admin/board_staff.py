"""Executive Board staff: seats, background tasks, steps and manager review.

See docs/architecture/executive-board.md §7 (Staff).
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import board_async
import board_budget
import board_personas
import board_store
import board_tools
from board_tools_core import LEVEL_RANK, ToolContext, allows, effective_level, global_cap
from contract_constants import (
    BOARD_CATALOG_EVENT_KINDS,
    BOARD_KEY,
    BOARD_STAFF_DAILY_BUDGET_DEFAULT_USD,
    BOARD_STAFF_DELIVERABLE_MAX_BYTES,
    BOARD_STAFF_DELIVERABLE_TYPES,
    BOARD_STAFF_HELP_DEPTH_MAX,
    BOARD_STAFF_MAX_IDLE_STEPS_PER_TASK,
    BOARD_STAFF_MAX_RUNNING_TASKS_DEFAULT,
    BOARD_STAFF_MAX_STEPS_PER_TASK,
    BOARD_STAFF_MODEL_TIERS,
    BOARD_STAFF_RETENTION_DAYS,
    BOARD_STAFF_SCRATCHPAD_MAX_CHARS,
    BOARD_STAFF_SEAT_IDS,
    BOARD_STAFF_SEATS,
    BOARD_STAFF_STEP_MAX_SECONDS,
    BOARD_STAFF_STEP_MODEL_LIST,
    BOARD_STAFF_STEP_MODELS,
    BOARD_STAFF_STEP_YIELD_SECONDS,
    BOARD_STAFF_TASK_BUDGET_DESK_USD,
    BOARD_STAFF_TASK_BUDGET_MAX_USD,
    BOARD_STAFF_TASK_BUDGET_SENIOR_USD,
    BOARD_STAFF_TASK_ORIGINS,
    BOARD_STAFF_TASK_STATUSES,
    BOARD_TOOL_IDS,
    BOARD_TOOL_LEVELS,
)
from http_common import _log_event, _utc_iso_z

TERMINAL_STATUSES = frozenset({"delivered", "failed", "cancelled"})
NON_TERMINAL_STATUSES = frozenset(s for s in BOARD_STAFF_TASK_STATUSES if s not in TERMINAL_STATUSES)
OWNER_HELD_CHILD_STATUSES = frozenset({"review", "needs_owner"})
_HELP_INTERNAL_TOOLS = frozenset({"board", "staff"})
_MEMORY_BLOBS: dict[str, bytes] = {}
_IDLE_TOOL_OPS = frozenset({"task_note"})
_POLL_REPEAT_OPS = frozenset(
    {
        "code_get_run",
        "code_review_pr",
        "github_get_pr",
        "github_get_issue",
        "github_list_prs",
        "github_list_issues",
        "github_search_issues",
        "github_list_check_runs",
    }
)
_BLOCK_LOOKBACK_CALLS = 12
_TOOL_BREAKER_RE = re.compile(r"\btool:([a-z0-9_-]+)\b", re.I)
_IDLE_NUDGE = (
    "NUDGE: That step only wrote a note. Call a real tool next, or call "
    "task_finish with the deliverable. Notes-only steps burn the step budget."
)
_FINISH_NUDGE = "NUDGE: Two steps left — call task_finish now with the deliverable."
MAIL_ARCHIVE_FINISH_PREFIX = "ARCHIVED — no action:"
_FC_LINE_RE = re.compile(r"^!function_call:.*$", re.M)
_HELP_IN_FLIGHT_RE = re.compile(
    r"help(?:\s+request)?(?:\s+is)?(?:\s+still)?\s+in flight",
    re.I,
)
_JSON_BRIEF_RE = re.compile(
    r"(?i)\b(?:return|as|valid|deliver(?:able)?)\b(?:\s+\w+){0,3}\s+json\b"
    r"|\bjson\s+(?:object|array|document)\b"
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



from board_staff_blobs import (  # noqa: E402
    _append_scratchpad,
    _blob_bucket,
    _blob_delete,
    _blob_get,
    _blob_put,
    _deliverable_key,
    _memory_blobs_enabled,
    _prepend_scratchpad,
    _scratchpad_key,
    presign_deliverable,
    read_deliverable,
)
from board_staff_help import (  # noqa: E402
    _cancel_open_help_children,
    _child_evidence_records,
    _expire_help_wait,
    _help_child_brief,
    _help_children_held_for_owner,
    _help_evidence_block,
    _help_finish_blocked,
    _normalize_help_tool_ids,
    _note_parent_child_waiting,
    _notify_parent_of_child,
    _open_help_child_ids,
    _park_waiting_subtask,
    _pending_help_approvals,
    _persona_covers_tools,
    _reject_pending_help_approvals,
    _remap_help_tool_ids,
    _resume_parent_after_help,
    _seat_covers_tools,
    act_guard_task_request_help,
    expire_waiting_help,
    help_available_line,
    op_task_request_help,
    pick_helper,
    prepare_help_request,
    preview_task_request_help,
    summarize_help_request,
    validate_task_request_help,
)
from board_staff_review import (  # noqa: E402
    _accept_task,
    _catalog_quality_return,
    _is_review_headline_duty,
    _mark_delivered,
    _note_parent_if_child_needs_owner,
    _review_flag_line,
    _review_user_prompt,
    _reviewer_id,
    _should_close_linked_action,
    _should_hold_unverified_accept,
    _task_attempted_required_tools,
    _task_has_open_approvals,
    apply_review,
    note_parent_if_child_needs_owner,
    owner_review,
    run_review,
)
from board_staff_tick import _continue_tick_stages, _run_tick_stage, handle_tick  # noqa: E402

# Names tests and other modules look up on this module. Submodules read the
# scratchpad cap from here so patch.object(board_staff, "BOARD_STAFF_SCRATCHPAD_MAX_CHARS") works.
__all__ = [
    "BOARD_STAFF_SCRATCHPAD_MAX_CHARS",
    "_MEMORY_BLOBS",
    "_append_scratchpad",
    "_blob_bucket",
    "_blob_delete",
    "_blob_get",
    "_blob_put",
    "_deliverable_key",
    "_memory_blobs_enabled",
    "_prepend_scratchpad",
    "_scratchpad_key",
    "presign_deliverable",
    "read_deliverable",
    "_cancel_open_help_children",
    "_child_evidence_records",
    "_expire_help_wait",
    "_help_child_brief",
    "_help_children_held_for_owner",
    "_help_evidence_block",
    "_help_finish_blocked",
    "_normalize_help_tool_ids",
    "_note_parent_child_waiting",
    "_notify_parent_of_child",
    "_open_help_child_ids",
    "_park_waiting_subtask",
    "_pending_help_approvals",
    "_persona_covers_tools",
    "_reject_pending_help_approvals",
    "_remap_help_tool_ids",
    "_resume_parent_after_help",
    "_seat_covers_tools",
    "act_guard_task_request_help",
    "expire_waiting_help",
    "help_available_line",
    "op_task_request_help",
    "pick_helper",
    "prepare_help_request",
    "preview_task_request_help",
    "summarize_help_request",
    "validate_task_request_help",
    "_accept_task",
    "_catalog_quality_return",
    "_is_review_headline_duty",
    "_mark_delivered",
    "_note_parent_if_child_needs_owner",
    "_review_flag_line",
    "_review_user_prompt",
    "_reviewer_id",
    "_should_close_linked_action",
    "_should_hold_unverified_accept",
    "_task_attempted_required_tools",
    "_task_has_open_approvals",
    "apply_review",
    "note_parent_if_child_needs_owner",
    "owner_review",
    "run_review",
    "_continue_tick_stages",
    "_run_tick_stage",
    "handle_tick",
]

def env_enabled() -> bool:
    from config import env_flag

    return env_flag("BOARD_STAFF_ENABLED")


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
    ranks = [LEVEL_RANK.get(lvl, 0) for lvl in levels]
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
    manager_level = effective_level(settings, tool_id, manager_id)
    cap = global_cap(settings)
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
    import board_breakers

    if board_breakers.openrouter_credits_paused(table):
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


def _model_for_seat(settings: dict[str, Any], seat_id: str, kind: str) -> str:
    """Per-seat OpenRouter model override, else the meeting-kind default."""
    raw = ((settings.get("staff") or {}).get("modelBySeat") or {}).get(seat_id)
    model = str(raw or "").strip()
    if model and model in BOARD_STAFF_STEP_MODELS:
        return model
    return board_budget.model_for(kind, settings)






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
    import board_breakers

    if board_breakers.openrouter_credits_paused(table):
        _requeue_for_budget(table, task, wanted, "openrouter credits paused")
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
    ref = task.get("eventRef") or {}
    if str(task.get("origin") or "") == "event" and str(ref.get("kind") or "") == "mail":
        user += (
            f'\nIf this inbound mail is a bounce, DMARC/SES report, or other automated notice '
            f'that needs no reply, call task_finish with "{MAIL_ARCHIVE_FINISH_PREFIX} <reason>" '
            "instead of writing back."
        )
    kind = "standup" if tier != "senior" else "deepDive"
    if (settings.get("staff") or {}).get("seniorPaused") and kind == "deepDive":
        kind = "standup"
    model = str(payload.get("modelOverride") or "").strip() or _model_for_seat(settings, seat_id, kind)
    if model not in BOARD_STAFF_STEP_MODELS:
        model = _model_for_seat(settings, seat_id, kind)
    def _sink(usage: dict[str, Any]) -> None:
        board_store.add_staff_usage_day(table, seat_id or persona_id, {**usage, "calls": 1})

    ctx = ToolContext(
        table=table,
        settings=settings,
        persona_id=persona_id,
        display_name=display,
        kind="task",
        task_id=task_id,
        seat_id=seat_id,
        actor="persona",
        usage_sink=_sink,
        task_attempt=_task_attempt(task),
        task_retried_at=str(task.get("retriedAt") or ""),
    )
    step_started = time.monotonic()
    ctx.deadline = step_started + BOARD_STAFF_STEP_MAX_SECONDS
    seeded = _seed_content_plan_evidence(table, task, ctx)
    if seeded:
        user += "\n" + seeded
    elapsed = int(time.monotonic() - step_started)
    loop_seconds = max(30, BOARD_STAFF_STEP_MAX_SECONDS - elapsed)
    require_finish = _should_require_finish(task)
    progress_at = {"n": 0}

    def _on_progress(calls: list[dict[str, Any]]) -> None:
        fresh = list(calls)[progress_at["n"] :]
        progress_at["n"] = len(calls)
        if fresh:
            _persist_step_progress(table, task_id, fresh)

    try:
        result = board_tools.run_tool_loop(
            ctx=ctx,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=model,
            timeout=min(90, loop_seconds),
            max_tokens=_step_max_tokens(task),
            temperature=0.3,
            json_mode=False,
            tag="board_staff_step",
            max_seconds=loop_seconds,
            on_progress=_on_progress,
            require_op="task_finish" if require_finish else None,
            yield_below_seconds=BOARD_STAFF_STEP_YIELD_SECONDS,
        )
    except Exception as exc:
        _on_step_exception(table, task, payload, wanted, exc)
        return
    _complete_step(table, task_id, task, result, wanted)


def _is_credit_error(exc: BaseException) -> bool:
    try:
        from openrouter_client import OpenRouterError
    except Exception:
        return "402" in str(exc)
    return isinstance(exc, OpenRouterError) and exc.status == 402


def _is_retryable_step_error(exc: BaseException) -> bool:
    try:
        from openrouter_client import OpenRouterError
    except Exception:
        return True
    if not isinstance(exc, OpenRouterError) or exc.status is None:
        return True
    if exc.status == 402:
        return False
    if 400 <= exc.status < 500 and exc.status not in (403, 408, 409, 425, 429):
        return False
    return True


def _seat_model_pinned(settings: dict[str, Any], seat_id: str) -> bool:
    raw = ((settings.get("staff") or {}).get("modelBySeat") or {}).get(seat_id)
    model = str(raw or "").strip()
    return bool(model and model in BOARD_STAFF_STEP_MODELS)


def _alternate_step_model(current: str) -> str:
    for model in BOARD_STAFF_STEP_MODEL_LIST:
        if model != current:
            return model
    return current


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
    if _is_credit_error(exc):
        _requeue_for_budget(table, latest, wanted, f"OpenRouter credits: {exc}"[:300])
        return
    if _is_retryable_step_error(exc) and not payload.get("retried"):
        settings = board_store.load_settings(table)
        seat_id = str(latest.get("assignee") or "")
        current_model = str(payload.get("modelOverride") or "") or _model_for_seat(
            settings, seat_id, "standup"
        )
        retry_model = (
            current_model
            if _seat_model_pinned(settings, seat_id)
            else _alternate_step_model(current_model)
        )
        _release_step_claim(table, latest, wanted)
        board_async.invoke_async(
            {
                "internal": "board_staff_step",
                "boardKey": BOARD_KEY,
                "taskId": task_id,
                "step": wanted,
                "retried": True,
                "modelOverride": retry_model,
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


def _token_overlap(left: str, right: str) -> float:
    a = set(_norm_plan(left).split())
    b = set(_norm_plan(right).split())
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _strip_function_call_leak(text: str) -> str:
    return _FC_LINE_RE.sub("", text or "").strip()


def _require_json_deliverable(text: str) -> None:
    idx = (text or "").find("{")
    if idx < 0:
        raise StaffError("deliverable JSON does not parse: no JSON object found")
    try:
        json.JSONDecoder().raw_decode(text[idx:])
    except json.JSONDecodeError as exc:
        raise StaffError(f"deliverable JSON does not parse: {exc}") from exc


def _deliverable_requires_json(task: dict[str, Any], dtype: str) -> bool:
    if dtype == "json":
        return True
    return bool(_JSON_BRIEF_RE.search(str(task.get("brief") or "")))


def _maybe_archive_mail_from_finish(table: Any, task: dict[str, Any], deliverable: str) -> None:
    if not deliverable.startswith(MAIL_ARCHIVE_FINISH_PREFIX):
        return
    if str(task.get("origin") or "") != "event":
        return
    ref = task.get("eventRef") or {}
    if str(ref.get("kind") or "") != "mail":
        return
    thread = board_store.get_mail_thread(table, str(ref.get("id") or ""))
    if not thread:
        return
    thread["disposition"] = "archived"
    thread["archivedReason"] = deliverable.split(":", 1)[-1].strip()[:200]
    thread["updatedAt"] = board_store.now_iso()
    board_store.put_mail_thread(table, thread)




def _call_fingerprint(call: dict[str, Any]) -> tuple[str, str]:
    args = {k: v for k, v in (call.get("arguments") or {}).items() if k != "reason"}
    return (str(call.get("op") or ""), json.dumps(args, sort_keys=True, default=str))


def _same_as_previous_step(table: Any, task_id: str, calls: list[dict[str, Any]]) -> bool:
    steps = board_store.list_task_steps(table, task_id)
    if len(steps) < 2:
        return False
    prev_ids = [str(x) for x in (steps[-2].get("callIds") or []) if x]
    if not prev_ids:
        return False
    by_id = {str(c.get("callId") or ""): c for c in board_store.list_tool_calls_for_task(table, task_id)}
    previous = [by_id[i] for i in prev_ids if i in by_id]
    left = [_call_fingerprint(c) for c in _productive_calls(previous)]
    right = [_call_fingerprint(c) for c in _productive_calls(calls)]
    return bool(left) and left == right


def _repeats_within_step(calls: list[dict[str, Any]]) -> bool:
    """True when one step polls the same op+args two or more times.

    Conservative: a mixed step (poll plus a different read) is not idle.
    """
    productive = _productive_calls(calls)
    if len(productive) < 2:
        return False
    fingerprints = [_call_fingerprint(c) for c in productive]
    first = fingerprints[0]
    if first[0] not in _POLL_REPEAT_OPS:
        return False
    return all(fp == first for fp in fingerprints)


def _counts_as_poll_loop(task: dict[str, Any], calls: list[dict[str, Any]]) -> bool:
    """True when identical steps are CI/issue polling, not productive research."""
    kind = str((task.get("eventRef") or {}).get("kind") or "")
    if kind.startswith("code-"):
        return True
    productive = _productive_calls(calls)
    return bool(productive) and all(str(c.get("op") or "") in _POLL_REPEAT_OPS for c in productive)


def _block_evidence(table: Any, task: dict[str, Any]) -> dict[str, str] | None:
    """Last refused or breaker-tripped tool call on this task, if any."""
    tid = str(task.get("taskId") or "")
    calls = board_store.list_tool_calls_for_task(table, tid, limit=_BLOCK_LOOKBACK_CALLS)
    used: set[str] = set()
    for call in calls:
        tool_id = str(call.get("toolId") or "").strip()
        if tool_id:
            used.add(tool_id)
        status = str(call.get("status") or "")
        preview = str(call.get("resultPreview") or call.get("result") or "")
        breaker = ""
        if isinstance(call.get("result"), dict):
            breaker = str((call.get("result") or {}).get("breaker") or "")
        if not breaker:
            match = _TOOL_BREAKER_RE.search(preview)
            if match:
                breaker = f"tool:{match.group(1)}"
        if breaker.startswith("tool:"):
            tool_id = tool_id or breaker.split(":", 1)[1]
        if status == "refused" and tool_id:
            return {"toolId": tool_id, "callId": str(call.get("callId") or "")}
        if breaker.startswith("tool:") and tool_id:
            return {"toolId": tool_id, "callId": str(call.get("callId") or "")}
    try:
        import board_breakers

        for tool_id in used:
            if board_breakers.is_tripped(table, f"tool:{tool_id}"):
                return {"toolId": tool_id, "callId": ""}
    except Exception as exc:
        _log_event("error", tag="board_staff_breaker_lookup_failed", error=str(exc)[:300])
        tripped = next(iter(used), "unknown")
        return {"toolId": tripped, "callId": ""}
    return None


def _should_require_finish(task: dict[str, Any]) -> bool:
    """Last idle step or last step: force the model to call task_finish."""
    idle = int(task.get("idleSteps") or 0)
    steps_used = int(task.get("step") or 0)
    return idle >= BOARD_STAFF_MAX_IDLE_STEPS_PER_TASK - 1 or steps_used >= BOARD_STAFF_MAX_STEPS_PER_TASK - 1


_STEP_TOKENS_DEFAULT = 2500
_STEP_TOKENS_LARGE = 6000
# Content-plan weeks are staged in batches (content_stage_items). A 12000-token
# completion does not fit in staffStepMaxSeconds once the model also has to
# call evidence tools.
_STEP_TOKENS_CONTENT_PLAN = 6000


def _is_content_plan(task: dict[str, Any]) -> bool:
    event_id = str((task.get("eventRef") or {}).get("id") or "")
    return event_id.startswith("content-plan")


def _step_max_tokens(task: dict[str, Any]) -> int:
    """Completion budget for one staff step.

    Content-plan steps stage at most six items, so they use the same 6000
    budget as other JSON deliverables. A 2500 cap still truncates a batch.
    The last/idle step uses 6000; everything else stays 2500.
    """
    if _is_content_plan(task):
        return _STEP_TOKENS_CONTENT_PLAN
    if str(task.get("deliverableType") or "") == "json" or _should_require_finish(task):
        return _STEP_TOKENS_LARGE
    return _STEP_TOKENS_DEFAULT


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
    last = latest.get("lastReview") or {}
    if _review_is_current_return(latest, last):
        latest["status"] = "needs_owner"
        latest["finishedAt"] = None
        question = f"Salvaged after {reason}; manager already returned this work."
        latest["openQuestions"] = [question]
        _stamp_parked(latest, reason=question)
        board_store.put_task(table, latest)
        _note_parent_if_child_needs_owner(table, latest)
        _log_event("warning", tag="board_staff_salvaged_after_return", taskId=task_id, reason=reason[:200], chars=len(text))
        return True
    board_store.put_task(table, latest)
    settings = board_store.load_settings(table)
    if enabled(settings):
        board_async.invoke_async(
            {"internal": "board_staff_review", "boardKey": BOARD_KEY, "taskId": task_id},
            fallback=run_review,
        )
    _log_event("warning", tag="board_staff_salvaged", taskId=task_id, reason=reason[:200], chars=len(text))
    return True


def _review_is_current_return(task: dict[str, Any], last: dict[str, Any]) -> bool:
    """True when ``lastReview`` is a return from this attempt, not a prior retry."""
    if str(last.get("verdict") or "") != "return":
        return False
    retried = str(task.get("retriedAt") or "")
    reviewed = str(last.get("at") or "")
    if retried and reviewed and reviewed < retried:
        return False
    if retried and not reviewed:
        return False
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

    ``review`` is also accepted: ``task_finish`` in the same step may have moved
    the row there before a blocking ``pending_approval`` was recorded.
    """
    stored = board_store.get_task(table, str(task.get("taskId") or ""))
    stored_status = str((stored or task).get("status") or "")
    if stored_status not in ("running", "review"):
        return
    task["status"] = "waiting_approval"
    task["blockedOn"] = approval_ids
    task["idleSteps"] = 0
    _stamp_parked(task, reason=f"waiting on approval {','.join(approval_ids)}", reset_clock=True)
    _align_step_claim(task)
    board_store.put_task(table, task)
    _log_event("info", tag="board_staff_waiting_approval", taskId=task.get("taskId"), approvals=approval_ids)


_APPROVAL_RESULT_CHARS = 400


def _approval_outcome_note(approval: dict[str, Any]) -> str:
    """Scratchpad line that tells the resumed seat how the founder decided.

    Without it the seat only sees its own ``pending_approval`` call and
    proposes the same write again on the next step (a rejected GitHub issue
    was re-proposed twice in production). The note names the outcome and the
    executed callId so ``task_finish`` can cite it.
    """
    op = str(approval.get("op") or "the proposal")
    summary = str(approval.get("summary") or "").strip()
    label = f"`{op}`" + (f" ({summary[:160]})" if summary else "")
    status = str(approval.get("status") or "")
    owner_note = str(approval.get("note") or "").strip()
    reason = f' Founder note: "{owner_note[:300]}".' if owner_note else ""
    if status == "executed":
        result = approval.get("result")
        try:
            rendered = json.dumps(result, ensure_ascii=False, default=str) if result not in (None, {}) else ""
        except (TypeError, ValueError):
            rendered = str(result)
        if len(rendered) > _APPROVAL_RESULT_CHARS:
            rendered = rendered[: _APPROVAL_RESULT_CHARS - 1] + "…"
        call_id = str(approval.get("executedCallId") or "")
        evidence = f" Cite callId {call_id} as evidence." if call_id else ""
        detail = f" Result: {rendered}" if rendered else ""
        return (
            f"APPROVAL: founder approved {label}; it has been executed.{detail}{evidence} "
            "Do not propose it again. Continue with the remaining work or finish."
        )
    if status == "rejected":
        return (
            f"APPROVAL: founder rejected {label}.{reason} "
            "Do not propose it again or any variant of it. Finish with what you have and say the proposal was declined."
        )
    err = str(approval.get("errorMessage") or "execution failed")[:300]
    return (
        f"APPROVAL: founder approved {label} but execution failed ({err}). "
        "Do not propose it again. Finish with what you have and report the failure."
    )


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
    try:
        import board_code

        if board_code.find_scheduled_sync_hold(table, task_id):
            return
        if board_code.on_sync_approval_outcome(table, approval) is not None:
            return
    except Exception:
        logging.getLogger(__name__).warning(
            "board code sync hook failed while resuming task %s",
            task_id,
            exc_info=True,
        )
    if _is_code_implement(task) and str(approval.get("op") or "") == "code_run_task":
        _settle_code_implement_approval(table, task, approval)
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
    elif str(approval.get("op") or "") != "task_request_help":
        _append_scratchpad(task, _approval_outcome_note(approval))
        task["scratchpadKey"] = _scratchpad_key(str(task.get("taskId") or ""))
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


def _is_code_implement(task: dict[str, Any]) -> bool:
    return str((task.get("eventRef") or {}).get("kind") or "") == "code-implement"


def _pending_code_run_approvals(table: Any, task: dict[str, Any]) -> list[dict[str, Any]]:
    tid = str(task.get("taskId") or "")
    if not tid:
        return []
    return [
        a
        for a in board_store.list_approvals(table)
        if a.get("status") == "pending"
        and a.get("op") == "code_run_task"
        and str((a.get("context") or {}).get("taskId") or "") == tid
    ]


def _after_this_attempt(task: dict[str, Any], when: Any) -> bool:
    """True when ``when`` is on the current attempt (after ``retriedAt``)."""
    floor = str(task.get("retriedAt") or "").strip()
    if not floor:
        return True
    return str(when or "") >= floor


def _run_row_failed(row: dict[str, Any]) -> bool:
    if row.get("failedAt"):
        return True
    return str(row.get("conclusion") or "").lower() in {
        "failure",
        "cancelled",
        "timed_out",
        "startup_failure",
    }


def _code_run_dispatched(table: Any, task: dict[str, Any]) -> bool:
    """True when this attempt already dispatched a coding runner.

    Approvals, tool calls and the ``code:run`` cache from a previous
    attempt (before ``retriedAt``) do not count. A run row with
    ``failedAt`` or a failed conclusion is not a live dispatch.
    """
    tid = str(task.get("taskId") or "")
    if not tid:
        return False
    for approval in board_store.list_approvals(table):
        if approval.get("op") != "code_run_task":
            continue
        if str((approval.get("context") or {}).get("taskId") or "") != tid:
            continue
        if approval.get("status") != "executed":
            continue
        when = approval.get("decidedAt") or approval.get("updatedAt") or approval.get("createdAt")
        if _after_this_attempt(task, when):
            return True
    for call in board_store.list_tool_calls_for_task(table, tid):
        if call.get("op") != "code_run_task" or call.get("status") != "ok":
            continue
        if _after_this_attempt(task, call.get("createdAt") or call.get("updatedAt")):
            return True
    try:
        import board_code

        row = board_code._get_run(table, tid)  # noqa: SLF001
    except Exception:
        row = {}
    if not row or _run_row_failed(row):
        return False
    when = row.get("dispatchedAt") or row.get("updatedAt") or ""
    if not when:
        return False
    return _after_this_attempt(task, when)


def _mark_code_runner_dispatched(task: dict[str, Any]) -> None:
    flags = [str(f) for f in (task.get("flags") or []) if f]
    if "code_runner_dispatched" not in flags:
        flags.append("code_runner_dispatched")
    task["flags"] = flags


def _settle_code_implement_approval(table: Any, task: dict[str, Any], approval: dict[str, Any]) -> None:
    """A code-implement task's job is to dispatch the runner, not wait for a PR."""
    now = board_store.now_iso()
    status = str(approval.get("status") or "")
    _clear_parked(task)
    task["updatedAt"] = now
    if status == "executed":
        task["summary"] = str(task.get("summary") or "Coding runner dispatched.")[:800]
        _mark_code_runner_dispatched(task)
        _mark_delivered(table, task, now)
        return
    reason = (
        "founder rejected the code_run_task proposal"
        if status == "rejected"
        else f"code_run_task failed: {str(approval.get('errorMessage') or 'execution failed')[:200]}"
    )
    task["status"] = "needs_owner"
    task["failureReason"] = reason[:300]
    task["finishedAt"] = None
    board_store.put_task(table, task)


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


def _offered_task_ops(ctx: ToolContext) -> set[str]:
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


def _is_idle_evidence_call(call: dict[str, Any]) -> bool:
    return str(call.get("op") or "") in _IDLE_TOOL_OPS


def _evidence_catalog(
    table: Any, task: dict[str, Any]
) -> tuple[set[str], dict[str, str], dict[str, str], set[str]]:
    """Return (known ids, alias→canonical, canonical→op, idle aliases) in one scan."""
    known: set[str] = set()
    alias_to_id: dict[str, str] = {}
    id_to_op: dict[str, str] = {}
    idle: set[str] = set()
    for tid in _evidence_task_ids(task):
        for call in board_store.list_tool_calls_for_task(table, tid):
            aliases = _call_evidence_aliases(call)
            if _is_idle_evidence_call(call):
                idle.update(aliases)
                continue
            known.update(aliases)
            cid = str(call.get("callId") or "").strip()
            if cid:
                for alias in aliases:
                    alias_to_id.setdefault(alias, cid)
                op = str(call.get("op") or "")
                if op:
                    id_to_op[cid] = op
        for step in board_store.list_task_steps(table, tid):
            for cid in step.get("callIds") or []:
                value = str(cid or "").strip()
                if value and value not in idle:
                    known.add(value)
                    alias_to_id.setdefault(value, value)
    return known, alias_to_id, id_to_op, idle


def _latest_ok_calls_by_op(table: Any, task: dict[str, Any]) -> dict[str, str]:
    """Newest ok call id per op on this task's current attempt.

    Help-child calls stay out of this map. The parent still has to cite the
    EVIDENCE lines the child wrote into the scratchpad.
    """
    found: dict[str, str] = {}
    for call in board_store.list_tool_calls_for_task(table, str(task.get("taskId") or "")):
        op = str(call.get("op") or "")
        cid = str(call.get("callId") or "")
        if not op or not cid or op in found or _is_idle_evidence_call(call):
            continue
        if str(call.get("status") or "") not in ("ok", ""):
            continue
        if not _after_this_attempt(task, call.get("createdAt")):
            continue
        found[op] = cid
    return found


def _persist_step_progress(table: Any, task_id: str, calls: list[dict[str, Any]]) -> None:
    """Flush tool-call ids onto the scratchpad before the next model round.

    A Lambda kill mid-generation otherwise leaves the re-claimed step with no
    memory of web_sessions (or any other call) it already made.
    """
    if not calls:
        return
    task = board_store.get_task(table, task_id)
    if not task or task.get("status") != "running":
        return
    existing = _blob_get(_scratchpad_key(task_id)).decode("utf-8", errors="replace")
    bits = []
    for call in calls:
        op = str(call.get("op") or "")
        cid = str(call.get("callId") or "")
        if not op:
            continue
        if cid and cid in existing:
            continue
        bits.append(f"{op} {cid} {call.get('status')}".strip())
    if not bits:
        return
    note = "STEP PROGRESS: " + "; ".join(bits)
    if len(note) > 1500:
        note = note[:1500]
    if note in existing:
        return
    combined = _append_scratchpad(task, note)
    task["scratchpadKey"] = _scratchpad_key(task_id)
    task["scratchpadChars"] = len(combined)
    task["updatedAt"] = board_store.now_iso()
    board_store.put_task(table, task)


def _seed_content_plan_evidence(table: Any, task: dict[str, Any], ctx: ToolContext) -> str:
    """Run GA4 reads the content-plan brief requires, before the model generates the week."""
    if not _is_content_plan(task):
        return ""
    needed = _brief_required_evidence_tools(
        str(task.get("brief") or ""), offered=_offered_evidence_ops(ctx, task)
    )
    wanted = [op for op in needed if op in ("web_sessions", "web_conversions", "web_gtm_status")]
    if not wanted:
        return ""
    have = _latest_ok_calls_by_op(table, task)
    lines: list[str] = []
    for op_name in wanted:
        if op_name in have:
            lines.append(f"{op_name} {have[op_name]}")
            continue
        op = board_tools.REGISTRY.get(op_name)
        if op is None:
            continue
        try:
            outcome = board_tools.execute_call(ctx, op, {})
        except Exception as exc:
            _log_event("warning", tag="board_content_plan_seed_failed", op=op_name, error=str(exc)[:200])
            continue
        lines.append(f"{op_name} {outcome.call_id} {outcome.status}")
    if not lines:
        return ""
    note = "SEEDED EVIDENCE: " + "; ".join(lines)
    _append_scratchpad(task, note)
    return note + ". Cite these call ids in task_finish evidence."




def _canonical_evidence_ids(table: Any, task: dict[str, Any], evidence: list[str]) -> list[str]:
    _, alias_to_id, _, _ = _evidence_catalog(table, task)
    out: list[str] = []
    seen: set[str] = set()
    for raw in evidence:
        cid = alias_to_id.get(str(raw))
        if cid and cid not in seen:
            out.append(cid)
            seen.add(cid)
    return out


def _offered_evidence_ops(ctx: ToolContext, task: dict[str, Any]) -> set[str]:
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








_PAGE_FETCH_NEED = ("fetch", "page", "official", "website", "url", "lcsd", "provider site")














































_DUTY_DATE_SUFFIX_RE = re.compile(r":\d{4}-\d{2}-\d{2}$")
_LENGTH_CUTOFF_NUDGE = (
    "NUDGE: Your previous reply was cut off at the length limit. "
    "Continue from where you stopped, or call task_finish with the full deliverable."
)
_CONTENT_PLAN_LENGTH_NUDGE = (
    "NUDGE: Your previous reply was cut off at the length limit. "
    "Do not send the whole week in one call. Call content_stage_items with at most "
    "6 items, repeat until the week is staged, then task_finish with {\"items\":[]}."
)


def _duty_event_id(task: dict[str, Any]) -> str:
    if str(task.get("origin") or "") != "duty":
        return ""
    return str((task.get("eventRef") or {}).get("id") or "").strip()


def _duty_event_key(event_id: str) -> str:
    """Strip a trailing ``:YYYY-MM-DD`` so dated duty ids group together."""
    return _DUTY_DATE_SUFFIX_RE.sub("", str(event_id or "").strip())


def supersede_stale_failed_duties(table: Any) -> int:
    """Cancel a failed/needs_owner duty when a newer task shares its duty key.

    Duty ids are often dated (``content-plan:2026-09-20``); the trailing date is
    stripped so a later run matches. ``failed`` and ``needs_owner`` start the
    scan; older ``needs_owner`` rows are cancelled only once a newer run has
    delivered. Older failures are cancelled whenever any newer task exists.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for status in ("failed", "needs_owner"):
        for task in board_store.list_tasks(table, status, limit=200):
            event_id = _duty_event_id(task)
            key = _duty_event_key(event_id)
            if key:
                grouped.setdefault(key, []).append(task)
    if not grouped:
        return 0
    wanted = set(grouped)
    for status in (
        "queued",
        "running",
        "waiting_approval",
        "waiting_subtask",
        "review",
        "awaiting_import",
        "delivered",
    ):
        for task in board_store.list_tasks(table, status, limit=200):
            event_id = _duty_event_id(task)
            key = _duty_event_key(event_id)
            if key in wanted:
                grouped[key].append(task)
    cancelled = 0
    for tasks in grouped.values():
        newest = max(tasks, key=lambda row: str(row.get("createdAt") or ""))
        newest_id = str(newest.get("taskId") or "")
        newest_status = str(newest.get("status") or "")
        newest_delivered = newest_status == "delivered"
        for task in tasks:
            if str(task.get("taskId") or "") == newest_id:
                continue
            status = str(task.get("status") or "")
            if status == "failed":
                pass
            elif status == "needs_owner" and newest_delivered:
                # Parked catalog import sheets wait for Import/Skip; a newer
                # enrich of the same district must not cancel them.
                phase = str(task.get("importPhase") or "")
                if phase in ("collision", "rejected", "partial", "failed", "invalid"):
                    continue
            else:
                continue
            task_id = str(task.get("taskId") or "")
            if not task_id:
                continue
            try:
                closed = cancel_task(
                    table,
                    task_id,
                    "board_staff:superseded",
                    reason="Superseded by a newer duty with the same event.",
                    record_failure=False,
                )
            except StaffError as exc:
                _log_event("info", tag="board_staff_supersede_skipped", taskId=task_id, error=str(exc)[:200])
                continue
            closed["closedBy"] = "board_staff:superseded"
            closed["failureReason"] = ""
            if not str(closed.get("summary") or "").strip():
                closed["summary"] = "Superseded by a newer duty with the same event."
            board_store.put_task(table, closed)
            cancelled += 1
    return cancelled




def _complete_step(table: Any, task_id: str, task: dict[str, Any], result: Any, wanted: int) -> None:
    usage = result.usage or {}
    latest = board_store.get_task(table, task_id) or task
    status = str(latest.get("status") or "")
    if status not in (
        "running",
        "review",
        "needs_owner",
        "delivered",
        "waiting_subtask",
        "waiting_approval",
        "awaiting_import",
    ):
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
    approval_ids = [
        str(c.get("approvalId"))
        for c in calls
        if str(c.get("status") or "") == "pending_approval"
        and c.get("approvalId")
        and c.get("blocksTask") is not False
    ]
    if approval_ids:
        # task_finish may already have moved the row to review; still park so
        # the founder decision can resume instead of duplicate proposals.
        _park_waiting_approval(table, latest, approval_ids)
        return
    if status in ("review", "needs_owner", "delivered", "waiting_subtask", "waiting_approval", "awaiting_import"):
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
    if _is_code_implement(latest) and _code_run_dispatched(table, latest):
        _mark_code_runner_dispatched(latest)
        _mark_delivered(table, latest, board_store.now_iso())
        return
    truncated = board_tools._completion_hit_length_limit(getattr(result, "completion", None))  # noqa: SLF001
    yielded = bool(getattr(result, "yielded", False)) and bool(_productive_calls(calls))
    similar_to_last = False
    if seq > 1:
        prior = board_store.list_task_steps(table, task_id)
        if len(prior) >= 2:
            similar_to_last = _plans_similar(note, str(prior[-2].get("plan") or ""))
    repeated_calls = _same_as_previous_step(table, task_id, calls)
    intra_poll = _repeats_within_step(calls)
    poll_loop = (repeated_calls or intra_poll) and _counts_as_poll_loop(latest, calls)
    if yielded:
        # The loop stopped before a call that would not fit the step budget;
        # the seat has not answered yet, so this is not an idle step.
        latest["idleSteps"] = 0
        latest["yieldedSteps"] = int(latest.get("yieldedSteps") or 0) + 1
    elif truncated:
        latest["idleSteps"] = 0
        nudge = _CONTENT_PLAN_LENGTH_NUDGE if _is_content_plan(latest) else _LENGTH_CUTOFF_NUDGE
        combined = _append_scratchpad(latest, nudge)
        latest["scratchpadKey"] = _scratchpad_key(task_id)
        latest["scratchpadChars"] = len(combined)
    elif not _productive_calls(calls) or similar_to_last or repeated_calls or intra_poll:
        idle = int(latest.get("idleSteps") or 0) + 1
        latest["idleSteps"] = idle
        combined = _append_scratchpad(latest, _IDLE_NUDGE)
        latest["scratchpadKey"] = _scratchpad_key(task_id)
        latest["scratchpadChars"] = len(combined)
        if _looks_like_stuck_finish(note) and _salvage_to_review(table, latest, "missing task_finish call", note):
            return
        if idle >= BOARD_STAFF_MAX_IDLE_STEPS_PER_TASK:
            if poll_loop and not _looks_like_stuck_finish(note):
                _finish_incomplete(table, latest, "no progress")
                return
            if _salvage_to_review(table, latest, "idle step limit", note):
                return
            _finish_incomplete(table, latest, "idle step limit")
            return
    else:
        latest["idleSteps"] = 0
    if seq == BOARD_STAFF_MAX_STEPS_PER_TASK - 2:
        combined = _append_scratchpad(latest, _FINISH_NUDGE)
        latest["scratchpadKey"] = _scratchpad_key(task_id)
        latest["scratchpadChars"] = len(combined)
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


def _origin_from_ctx(ctx: ToolContext) -> str:
    if ctx.actor == "owner":
        return "owner"
    if ctx.kind == "meeting":
        return "minutes"
    if ctx.kind == "task":
        return "task" if "task" in BOARD_STAFF_TASK_ORIGINS else "chat"
    if ctx.kind == "chat":
        return "chat"
    return "chat"


def act_guard_staff_assign(ctx: ToolContext, _args: dict[str, Any]) -> str | None:
    cap = int((ctx.settings.get("staff") or {}).get("maxRunningTasks") or BOARD_STAFF_MAX_RUNNING_TASKS_DEFAULT)
    running = len([t for t in board_store.list_tasks(ctx.table, "running") if t.get("status") == "running"])
    reviewing = len([t for t in board_store.list_tasks(ctx.table, "review") if t.get("status") == "review"])
    if running + reviewing >= cap * 2:
        return "queue full"
    return None


def reuse_open_assignment(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any] | None:
    """Attach a minutes action to an existing open task instead of proposing again."""
    if _origin_from_ctx(ctx) != "minutes":
        return None
    assignee = str(args.get("assignee") or "")
    brief = str(args.get("brief") or "")
    if not assignee or not brief:
        return None
    match = None
    for status in ("queued", "running", "review", "waiting_approval", "waiting_subtask"):
        for task in board_store.list_tasks(ctx.table, status, limit=200):
            if str(task.get("assignee") or "") != assignee:
                continue
            if _token_overlap(brief, str(task.get("brief") or "")) >= 0.6:
                match = task
                break
        if match:
            break
    if not match:
        return None
    action_id = str(args.get("actionId") or "")
    if action_id and not match.get("actionId"):
        match["actionId"] = action_id
        match["updatedAt"] = board_store.now_iso()
        board_store.put_task(ctx.table, match)
        action = board_store.get_action(ctx.table, action_id)
        if action:
            action["taskId"] = match.get("taskId")
            action["staffTaskId"] = match.get("taskId")
            board_store.put_action(ctx.table, action)
    return public_task(match)


def op_staff_assign(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
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


def op_staff_list_tasks(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    status = str(args.get("status") or "") or None
    if status and status not in BOARD_STAFF_TASK_STATUSES:
        raise StaffError(f"status must be one of {', '.join(BOARD_STAFF_TASK_STATUSES)}")
    limit = max(1, min(50, int(args.get("limit") or 20)))
    tasks = board_store.list_tasks(ctx.table, status, limit=200)
    if ctx.seat_id:
        tasks = [t for t in tasks if t.get("assignee") == ctx.seat_id]
    return {"tasks": [public_task(t) for t in tasks[:limit]]}


def op_staff_get_deliverable(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
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


def op_staff_request_revision(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task = board_store.get_task(ctx.table, str(args.get("taskId") or ""))
    if not task:
        raise StaffError("Task not found")
    if ctx.persona_id != task.get("managerId"):
        raise StaffError("Only the manager can request a revision")
    notes = str(args.get("notes") or "").strip()
    if not notes:
        raise StaffError("notes are required")
    return public_task(apply_review(ctx.table, ctx.settings, task, verdict="return", notes=notes, by=ctx.persona_id))


def op_staff_cancel_task(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
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


def op_task_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task = _require_running_task(board_store.get_task(ctx.table, ctx.task_id))
    text = str(args.get("text") or "").strip()
    combined = _append_scratchpad(task, text)
    task["scratchpadKey"] = _scratchpad_key(ctx.task_id)
    task["scratchpadChars"] = len(combined)
    task["updatedAt"] = board_store.now_iso()
    board_store.put_task(ctx.table, task)
    return {"ok": True, "chars": len(combined)}


def _finish_blocked(
    ctx: ToolContext,
    task: dict[str, Any],
    args: dict[str, Any],
    deliverable: str,
) -> dict[str, Any]:
    """Park an honest 'cannot proceed' finish without manager review or a revision."""
    evidence = _block_evidence(ctx.table, task)
    if not evidence:
        raise StaffError(
            "status=blocked needs a recent refused tool call or a tripped tool breaker on this task"
        )
    reason = str(
        args.get("blockedReason") or args.get("reason") or args.get("summary") or deliverable
    ).strip()[:300]
    if not reason:
        raise StaffError("blocked finish needs a blockedReason")
    parked = f"blocked:tool:{evidence['toolId']}"
    encoded = deliverable.encode("utf-8") if deliverable else reason.encode("utf-8")
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
            "attempt": _task_attempt(task),
            "plan": str(args.get("summary") or reason)[:2000],
            "callIds": [],
            "at": now,
        },
    )
    updated = {
        **task,
        "status": "needs_owner",
        "step": seq,
        "stepsUsed": seq,
        "idleSteps": 0,
        "summary": str(args.get("summary") or reason)[:800],
        "deliverableKey": key,
        "deliverableBytes": len(encoded),
        "deliverableType": dtype,
        "parkedReason": parked,
        "finishedAt": None,
        "updatedAt": now,
    }
    _align_step_claim(updated)
    board_store.put_task(ctx.table, updated)
    _note_parent_if_child_needs_owner(ctx.table, updated)
    return {"ok": True, "status": "needs_owner", "blocked": True, "parkedReason": parked}


def op_task_finish(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task = _require_running_task(board_store.get_task(ctx.table, ctx.task_id))
    status_arg = str(args.get("status") or "").strip().lower()
    deliverable = _strip_function_call_leak(str(args.get("deliverable") or ""))
    if _is_content_plan(task):
        import board_content

        deliverable = board_content.merge_plan_deliverable(ctx.task_id, deliverable)
    encoded = deliverable.encode("utf-8")
    if len(encoded) > BOARD_STAFF_DELIVERABLE_MAX_BYTES:
        raise StaffError(
            f"deliverable is larger than {BOARD_STAFF_DELIVERABLE_MAX_BYTES} bytes; split it"
        )
    blocked_note = ""
    if status_arg == "blocked":
        if _block_evidence(ctx.table, task):
            return _finish_blocked(ctx, task, args, deliverable)
        # "blocked" is for a refused tool or a tripped breaker. A seat that
        # simply found nothing to act on (no published email, no data) used to
        # get an error here and call task_finish again with the same status
        # until the step limit; the work it has is sent to review instead.
        if not deliverable.strip():
            raise StaffError(
                "status=blocked needs a recent refused tool call or a tripped tool breaker on this task. "
                "If the work itself cannot be done (nothing to contact, no data), finish without a "
                "status and say so in the deliverable, citing the calls you made as evidence."
            )
        status_arg = ""
        blocked_note = (
            "status=blocked needs a refused tool call or a tripped breaker; "
            "the deliverable was sent to review instead"
        )
        _log_event("info", tag="board_task_blocked_downgraded", taskId=ctx.task_id)
    if _deliverable_has_placeholders(deliverable):
        raise StaffError(
            "Deliverable still has placeholder text such as [Insert …]. "
            "Call finance_cash_snapshot, finance_aging_report, aws_monthly_cost and "
            "meta_ad_spend (or finance_unit_economics), then write the verified figures. "
            "If a tool cannot verify a number, write 'unavailable' and why."
        )
    evidence = [str(x) for x in (args.get("evidence") or []) if isinstance(x, (str, int))]
    known, alias_to_id, id_to_op, idle = _evidence_catalog(ctx.table, task)
    attempt = _task_attempt(task)
    if evidence and not any(item in known for item in evidence) and any(item in idle for item in evidence):
        raise StaffError("task_note call ids are not evidence; cite a read or write tool call")
    canonical: list[str] = []
    seen_ids: set[str] = set()
    for raw in evidence:
        if raw not in known:
            continue
        cid = alias_to_id.get(raw) or raw
        if cid not in seen_ids:
            canonical.append(cid)
            seen_ids.add(cid)
    evidence = canonical
    needed = _brief_required_evidence_tools(
        str(task.get("brief") or ""), offered=_offered_evidence_ops(ctx, task)
    )
    cited = {id_to_op[cid] for cid in evidence if cid in id_to_op}
    missing = [tool for tool in needed if tool not in cited]
    latest_calls = _latest_ok_calls_by_op(ctx.table, task) if missing else {}
    if missing:
        for tool in missing:
            cid = latest_calls.get(tool)
            if cid and cid not in evidence:
                evidence.append(cid)
        cited = {id_to_op[cid] for cid in evidence if cid in id_to_op}
        # Seeded calls are in the catalog; a call recorded after the catalog
        # scan still has an id we just appended. Fill ops from the latest map.
        for tool, cid in latest_calls.items():
            if cid in evidence:
                cited.add(tool)
        missing = [tool for tool in needed if tool not in cited]
    if missing:
        borrowed = bool(task.get("helpTaskIds"))
        hint = (
            " Cite the help task's EVIDENCE call ids from the scratchpad "
            "(or staff_get_deliverable)."
            if borrowed
            else " Call those tools first and pass their call ids in evidence."
        )
        known = [f"{op} {cid}" for op, cid in latest_calls.items() if op in needed]
        if known:
            hint += " Already on this attempt: " + ", ".join(known) + "."
        raise StaffError("This brief requires evidence from " + ", ".join(needed) + "." + hint)
    confidence = str(args.get("confidence") or "medium")
    flags = list(task.get("flags") or [])
    if not evidence and confidence == "high":
        confidence = "medium"
        flags.append("no_evidence")
    dtype = str(args.get("deliverableType") or task.get("deliverableType") or "markdown")
    if _deliverable_requires_json(task, dtype):
        _require_json_deliverable(deliverable)
    if _help_finish_blocked(ctx.table, task, deliverable):
        raise StaffError("finish the work with what you have, or wait for the help task")
    _maybe_archive_mail_from_finish(ctx.table, task, deliverable)
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
        "status": "running",
        "step": seq,
        "stepsUsed": seq,
        "idleSteps": 0,
        "summary": _strip_function_call_leak(str(args.get("summary") or ""))[:800],
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
    if _is_code_implement(task):
        pending = _pending_code_run_approvals(ctx.table, updated)
        if pending:
            board_store.put_task(ctx.table, updated)
            _park_waiting_approval(
                ctx.table,
                updated,
                [str(a.get("approvalId") or "") for a in pending if a.get("approvalId")],
            )
            return {"ok": True, "status": "waiting_approval", "deliverableKey": key}
        if _code_run_dispatched(ctx.table, updated):
            _mark_code_runner_dispatched(updated)
            delivered = _mark_delivered(ctx.table, updated, now)
            return {"ok": True, "status": str(delivered.get("status") or "delivered"), "deliverableKey": key}
        raise StaffError(
            "This task revises an existing board PR. Call code_run_task once, then "
            "task_finish. Do not invent GitHub write tools or open a second pull request."
        )
    updated["status"] = "review"
    board_store.put_task(ctx.table, updated)
    if enabled(ctx.settings):
        board_async.invoke_async(
            {"internal": "board_staff_review", "boardKey": BOARD_KEY, "taskId": ctx.task_id},
            fallback=run_review,
        )
    return {
        "ok": True,
        "status": "review",
        "deliverableKey": key,
        **({"note": blocked_note} if blocked_note else {}),
    }




























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
    task["previousFailureReason"] = str(task.get("failureReason") or "")
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
    task["lastReview"] = None
    task.pop("stepClaimed", None)
    task.pop("stepClaimedAt", None)
    task["updatedAt"] = now
    task["retriedBy"] = by_sub
    task["retriedAt"] = now
    _cancel_open_help_children(table, task, by_sub)
    _clear_parked(task)
    task["helpRequests"] = 0
    retry_banner = (
        "RETRY — the notes below are from a failed attempt; verify state with tools "
        "before trusting them."
    )
    import_notes = [str(q) for q in (task.get("openQuestions") or []) if q]
    if import_notes and str((task.get("eventRef") or {}).get("kind") or "") in BOARD_CATALOG_EVENT_KINDS:
        retry_banner = retry_banner + " Importer: " + "; ".join(import_notes[:6])
    combined = _prepend_scratchpad(task, retry_banner)
    task["scratchpadKey"] = _scratchpad_key(task_id)
    task["scratchpadChars"] = len(combined)
    board_store.put_task(table, task)
    if enabled(settings):
        drain_queue(table, settings)
    return board_store.get_task(table, task_id) or task


def cancel_task(
    table: Any,
    task_id: str,
    by_sub: str,
    *,
    notify_parent: bool = True,
    reason: str = "",
    record_failure: bool = True,
) -> dict[str, Any]:
    task = board_store.get_task(table, task_id)
    if not task:
        raise StaffError("Task not found")
    status = str(task.get("status") or "")
    if status == "cancelled":
        return task
    if status == "delivered":
        raise StaffError("Delivered tasks cannot be cancelled", code="conflict")
    now = board_store.now_iso()
    message = (str(reason or "").strip() or f"cancelled by {by_sub}")[:300]
    if status == "failed":
        task["cancelledFrom"] = "failed"
        prior = str(task.get("failureReason") or "").strip()
        task["failureReason"] = (f"{prior}; {message}" if prior else message)[:300]
    elif record_failure:
        task["failureReason"] = message
    else:
        task["failureReason"] = ""
        if reason and not str(task.get("summary") or "").strip():
            task["summary"] = message[:200]
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
    level = effective_level(settings, "staff", chair_id)
    if not allows(level, "propose"):
        return
    overrides = board_store.load_member_overrides(table)
    default = board_personas.persona_default(chair_id) or {}
    profile = board_personas.effective_profile(default, overrides.get(chair_id))
    ctx = ToolContext(
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




