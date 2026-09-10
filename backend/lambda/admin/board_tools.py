"""Executive Board: tools that members call while chatting or meeting.

Design (see docs/architecture/executive-board-tools-plan.md):

- A **registry** of operations, each belonging to a tool (``github``,
  ``board``, ``mail``, ``research``, ``aws``, ``security``, ``product``,
  ``meta``, ``finance``, ``stores``, ``staff``, ``intel``, ``outreach``, ``content``, ``code``, ``newsletter``)
  and being either a *read* or a *write*.
- A per-tool, per-member **level** (``off`` < ``read`` < ``propose`` <
  ``act``), capped by a global mode. Read operations are offered at
  ``read`` and above; write operations at ``propose`` and above. At
  ``propose`` a write is recorded as a pending **approval** for the owner
  instead of executing; at ``act`` it executes immediately.
- The **loop**: model → tool calls → results → model, bounded by rounds,
  calls, and wall-clock seconds. Every call lands in the audit log.
"""

from __future__ import annotations

import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

import board_actions
import board_aws
import board_budget
import board_deadline
import board_github
import board_mail
import board_meta
import board_personas
import board_product
import board_receivables
import board_research
import board_security
import board_store
import board_stores
import board_web
from contract_constants import (
    BOARD_ACTION_EFFORTS,
    BOARD_ACTION_PRIORITIES,
    BOARD_ACTION_STATUSES,
    BOARD_MAIL_BODY_MAX_CHARS,
    BOARD_MAIL_SUBJECT_MAX_LEN,
    BOARD_RESEARCH_QUERY_MAX_LEN,
    BOARD_MAX_PENDING_APPROVALS,
    BOARD_MAX_TOOL_CALLS_PER_TURN,
    BOARD_MAX_TOOL_ROUNDS_PER_TURN,
    BOARD_TOOL_DEFINITIONS,
    BOARD_TOOL_LEVELS,
    BOARD_TOOL_RESULT_MAX_CHARS,
    BOARD_TOOL_CALL_TIMEOUT_SECONDS,
    BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
    BOARD_META_LIST_MAX,
    BOARD_STORES_LIST_MAX,
    BOARD_WEB_LIST_MAX,
    BOARD_STAFF_DELIVERABLE_TYPES,
    BOARD_STAFF_NEWSLETTER_LISTS,
    BOARD_STAFF_PROSPECT_TYPES,
)
from http_common import _log_event, _utc_iso_z
from openrouter_client import ChatCompletion, ToolCall, add_usage

LEVEL_RANK: dict[str, int] = {lvl: i for i, lvl in enumerate(BOARD_TOOL_LEVELS)}
GLOBAL_MODE_CAP: dict[str, str] = {"readOnly": "read", "propose": "propose", "act": "act"}
TOOL_LABELS: dict[str, str] = {str(t["id"]): str(t["label"]) for t in BOARD_TOOL_DEFINITIONS}
MAX_ARGUMENT_CHARS = 8000
MAX_RESULT_PREVIEW = 400
# Wall-clock budget of one persona turn (chat: chatToolLoopMaxSeconds, meeting:
# meetingToolLoopMaxSeconds) is shared by the model calls and the tool ops:
#   round N model call  ≤ min(openrouter timeout, seconds left)
#   each op             ≤ min(op timeout, seconds left), never below the floor
#   final answer call   ≤ min(openrouter timeout, seconds left), at least the final floor
# so a turn ends within about max(max_seconds + final floor, openrouter timeout):
# chat 120 + 45 = 165 s (< chatPollDeadlineMs 270 s, < the 300 s Lambda),
# meeting 60 + 45 = 105 s per member (members run in parallel per phase).
MODEL_CALL_TIMEOUT_FLOOR_SECONDS = 15
FINAL_CALL_TIMEOUT_FLOOR_SECONDS = 45
OP_TIMEOUT_FLOOR_SECONDS = 2


class ToolPermissionError(RuntimeError):
    """The member is not allowed to run this operation at this level."""


class InvalidArgumentsError(ValueError):
    """Arguments (from the model or an owner override) do not match the op schema."""


@dataclass
class ToolContext:
    """Who is calling, from where. ``actor`` is ``persona`` or ``owner``."""

    table: Any
    settings: dict[str, Any]
    persona_id: str
    display_name: str = ""
    kind: str = "chat"
    meeting_id: str = ""
    phase: str = ""
    job_id: str = ""
    actor: str = "persona"
    owner_sub: str = ""
    task_id: str = ""
    seat_id: str = ""
    usage_sink: Callable[[dict[str, Any]], None] | None = None
    # ``time.monotonic()`` value after which no new op should start and running
    # ops are cut short; 0 means "no loop deadline" (owner approvals, jobs).
    deadline: float = 0.0

    def seconds_left(self) -> float | None:
        if not self.deadline:
            return None
        return max(0.0, self.deadline - time.monotonic())

    def public(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        if self.meeting_id:
            out["meetingId"] = self.meeting_id
        if self.phase:
            out["phase"] = self.phase
        if self.job_id:
            out["jobId"] = self.job_id
        if self.task_id:
            out["taskId"] = self.task_id
        if self.seat_id:
            out["seatId"] = self.seat_id
        return out


@dataclass(frozen=True)
class ToolOp:
    name: str
    tool_id: str
    kind: str  # "read" | "write"
    description: str
    parameters: dict[str, Any]
    run: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]
    summarize: Callable[[dict[str, Any]], str]
    contexts: tuple[str, ...] = ("chat", "meeting")
    # Write ops only. ``act_guard`` returns a reason why an ``act``-level call
    # must still be approved (e.g. recipient not allow-listed); ``preview``
    # renders the owner-facing, un-masked payload stored on the approval.
    act_guard: Callable[[ToolContext, dict[str, Any]], str | None] | None = None
    preview: Callable[[ToolContext, dict[str, Any]], dict[str, Any] | None] | None = None
    # None → BOARD_TOOL_CALL_TIMEOUT_SECONDS. Slow Graph / GitHub reads use 25s.
    timeout_seconds: int | None = None
    # None → propose for writes, read for reads. CISO phishing is a write at read.
    level_floor: str | None = None
    # Writes that the plan keeps in Approvals even when the member is at ``act``.
    always_propose: bool = False

    @property
    def is_write(self) -> bool:
        return self.kind == "write"

    @property
    def min_level(self) -> str:
        if self.level_floor:
            return self.level_floor
        return "propose" if self.is_write else "read"

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolOutcome:
    status: str  # ok | error | pending_approval | held
    result: dict[str, Any]
    summary: str
    approval_id: str = ""
    duration_ms: int = 0
    call_id: str = ""

    def public(self, op: ToolOp) -> dict[str, Any]:
        out = {
            "callId": self.call_id,
            "op": op.name,
            "toolId": op.tool_id,
            "toolLabel": TOOL_LABELS.get(op.tool_id, op.tool_id),
            "kind": op.kind,
            "status": self.status,
            "summary": self.summary,
            "durationMs": self.duration_ms,
        }
        if self.approval_id:
            out["approvalId"] = self.approval_id
        if self.status == "held":
            out["holdId"] = str(self.result.get("holdId") or "")
            out["executeAt"] = str(self.result.get("executeAt") or "")
        if self.status == "error":
            out["error"] = str(self.result.get("error") or "")[:300]
        return out


@dataclass
class ToolLoopResult:
    text: str
    usage: dict[str, Any]
    model: str
    calls: list[dict[str, Any]] = field(default_factory=list)
    rounds: int = 0
    completion: ChatCompletion | None = None


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------

def env_disabled() -> bool:
    """Deploy-time kill switch: ``BOARD_TOOLS_ENABLED=false`` on the Lambda."""
    env = (os.environ.get("BOARD_TOOLS_ENABLED") or "").strip().lower()
    return env in ("0", "false", "no", "off")


def tools_enabled(settings: dict[str, Any]) -> bool:
    if env_disabled():
        return False
    return bool((settings.get("tools") or {}).get("enabled", True))


def global_cap(settings: dict[str, Any]) -> str:
    mode = str((settings.get("tools") or {}).get("globalMode") or "propose")
    return GLOBAL_MODE_CAP.get(mode, "propose")


def configured_level(settings: dict[str, Any], tool_id: str, persona_id: str) -> str:
    matrix = (settings.get("tools") or {}).get("matrix") or {}
    level = str((matrix.get(tool_id) or {}).get(persona_id) or "off")
    return level if level in LEVEL_RANK else "off"


def effective_level(
    settings: dict[str, Any],
    tool_id: str,
    persona_id: str,
    *,
    seat_id: str = "",
    seats_by_id: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Configured level capped by the global mode; ``off`` when tools are disabled."""
    if not tools_enabled(settings):
        return "off"
    if seat_id:
        import board_staff

        return board_staff.seat_level(settings, seats_by_id or {}, seat_id, tool_id)
    configured = configured_level(settings, tool_id, persona_id)
    cap = global_cap(settings)
    return configured if LEVEL_RANK[configured] <= LEVEL_RANK[cap] else cap


def effective_matrix(settings: dict[str, Any]) -> dict[str, dict[str, str]]:
    matrix = (settings.get("tools") or {}).get("matrix") or {}
    return {
        tool_id: {pid: effective_level(settings, tool_id, pid) for pid in cells}
        for tool_id, cells in matrix.items()
    }


def allows(level: str, required: str) -> bool:
    return LEVEL_RANK.get(level, 0) >= LEVEL_RANK.get(required, 0)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def _str_param(description: str, *, max_len: int | None = None, enum: list[str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "string", "description": description}
    if max_len:
        out["maxLength"] = max_len
    if enum:
        out["enum"] = enum
    return out


def _int_param(description: str, *, minimum: int = 1, maximum: int = 20) -> dict[str, Any]:
    return {"type": "integer", "description": description, "minimum": minimum, "maximum": maximum}


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


REASON_PARAM = _str_param(
    "One sentence for the founder explaining why this action is needed now.", max_len=400
)


def _gh(fn: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[[ToolContext, dict[str, Any]], dict[str, Any]]:
    return lambda _ctx, args: fn(args)


# --- board operations -------------------------------------------------------

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


def _summ(template: str) -> Callable[[dict[str, Any]], str]:
    def _fmt(args: dict[str, Any]) -> str:
        try:
            return template.format(**{k: _short(v) for k, v in args.items()})
        except (KeyError, IndexError, ValueError):
            return template.split("{")[0].strip() or template
    return _fmt


def _short(value: Any, limit: int = 80) -> str:
    text = " ".join(str(value if value is not None else "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _summ_search(args: dict[str, Any]) -> str:
    q = _short(args.get("query") or "")
    return f"Searched GitHub {args.get('type') or 'issue'}s" + (f" for '{q}'" if q else "") + f" ({args.get('state') or 'open'})"


def _summ_labels(args: dict[str, Any]) -> str:
    labels = args.get("labels") if isinstance(args.get("labels"), list) else []
    return f"Set labels on #{args.get('number')}: {', '.join(str(x) for x in labels) or '(none)'}"


def _summ_mail_list(args: dict[str, Any]) -> str:
    parts = ["Listed email threads"]
    if args.get("mailbox"):
        parts.append(f"in {_short(args['mailbox'], 40)}")
    if args.get("query"):
        parts.append(f"matching '{_short(args['query'], 40)}'")
    if args.get("unreadOnly"):
        parts.append("(unread only)")
    return " ".join(parts)


def _intel_list_watchlist(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_intel

    return board_intel.op_list_watchlist(ctx, args)


def _intel_get_changes(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_intel

    return board_intel.op_get_changes(ctx, args)


def _intel_fetch_page(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_intel

    return board_intel.op_fetch_page(ctx, args)


def _intel_competitor_reviews(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_intel

    return board_intel.op_competitor_reviews(ctx, args)


def _intel_search_rank(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_intel

    return board_intel.op_search_rank(ctx, args)


def _outreach_search_places(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_outreach

    return board_outreach.op_search_places(ctx, args)


def _outreach_open_data(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_outreach

    return board_outreach.op_open_data(ctx, args)


def _outreach_list_prospects(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_outreach

    return board_outreach.op_list_prospects(ctx, args)


def _outreach_get_prospect(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_outreach

    return board_outreach.op_get_prospect(ctx, args)


def _outreach_upsert_prospect(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_outreach

    return board_outreach.op_upsert_prospect(ctx, args)


def _outreach_score_prospect(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_outreach

    return board_outreach.op_score_prospect(ctx, args)


def _outreach_start_sequence(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_outreach

    return board_outreach.op_start_sequence(ctx, args)


def _outreach_send(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_outreach

    return board_outreach.op_send(ctx, args)


def _outreach_suppress(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_outreach

    return board_outreach.op_suppress(ctx, args)


def _content_list(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_content

    return board_content.op_list(ctx, args)


def _content_get(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_content

    return board_content.op_get(ctx, args)


def _content_publish(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_content

    return board_content.op_publish(ctx, args)


def _newsletter_draft_issue(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_newsletter

    return board_newsletter.op_draft_issue(ctx, args)


def _newsletter_send(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_newsletter

    return board_newsletter.op_send(ctx, args)


def _code_run_task(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_code

    return board_code.op_run_task(ctx, args)


def _code_get_run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_code

    return board_code.op_get_run(ctx, args)


def _code_review_pr(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_code

    return board_code.op_review_pr(ctx, args)


def _code_merge_staging(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_code

    return board_code.op_merge_staging(ctx, args)


def _code_promote(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_code

    return board_code.op_promote(ctx, args)


def _code_merge_guard(ctx: ToolContext, args: dict[str, Any]) -> str | None:
    import board_code

    return board_code.merge_guard(ctx, args)


def _staff_assign(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_staff

    return board_staff.op_staff_assign(ctx, args)


def _staff_list_tasks(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_staff

    return board_staff.op_staff_list_tasks(ctx, args)


def _staff_get_deliverable(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_staff

    return board_staff.op_staff_get_deliverable(ctx, args)


def _staff_request_revision(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_staff

    return board_staff.op_staff_request_revision(ctx, args)


def _staff_cancel_task(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_staff

    return board_staff.op_staff_cancel_task(ctx, args)


def _staff_assign_guard(ctx: ToolContext, args: dict[str, Any]) -> str | None:
    import board_staff

    return board_staff.act_guard_staff_assign(ctx, args)


def _reply_guard(op_name: str, inner: Any = None):
    def _guard(ctx: ToolContext, args: dict[str, Any]) -> str | None:
        if inner is not None:
            reason = inner(ctx, args)
            if reason:
                return reason
        import board_policy

        thread = None
        thread_id = str(args.get("threadId") or "")
        if thread_id:
            thread = board_store.get_mail_thread(ctx.table, thread_id) or board_store.get_meta_thread(ctx.table, thread_id)
        op = REGISTRY.get(op_name)
        if op is None:
            return None
        return board_policy.check_reply(ctx.settings, ctx, op, args, thread)

    return _guard


def _task_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_staff

    return board_staff.op_task_note(ctx, args)


def _task_finish(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_staff

    return board_staff.op_task_finish(ctx, args)


def _summ_staff_assign(args: dict[str, Any]) -> str:
    return f"Assigned {args.get('assignee')}: {_short(args.get('brief') or '', 80)}"


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


def build_registry() -> dict[str, ToolOp]:
    ops: list[ToolOp] = [
        ToolOp(
            name="github_search_issues",
            tool_id="github",
            kind="read",
            description="Search issues or pull requests in the siutindei repository by keywords. Use before proposing new work to avoid duplicates.",
            parameters=_obj(
                {
                    "query": _str_param("Keywords (GitHub search syntax allowed, e.g. 'label:bug booking').", max_len=200),
                    "state": _str_param("Filter by state.", enum=["open", "closed", "all"]),
                    "type": _str_param("issue, pr or any.", enum=["issue", "pr", "any"]),
                    "limit": _int_param("Max results (1-20).", maximum=20),
                }
            ),
            run=_gh(board_github.op_search_issues),
            summarize=_summ_search,
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
        ToolOp(
            name="github_get_issue",
            tool_id="github",
            kind="read",
            description="Read one issue or pull request in full, including its most recent comments.",
            parameters=_obj({"number": _int_param("Issue or PR number.", maximum=100000)}, ["number"]),
            run=_gh(board_github.op_get_issue),
            summarize=_summ("Read issue #{number}"),
        ),
        ToolOp(
            name="github_list_pull_requests",
            tool_id="github",
            kind="read",
            description="List pull requests (newest updated first).",
            parameters=_obj(
                {
                    "state": _str_param("open, closed or all.", enum=["open", "closed", "all"]),
                    "limit": _int_param("Max results (1-20).", maximum=20),
                }
            ),
            run=_gh(board_github.op_list_pull_requests),
            summarize=_summ("Listed {state} pull requests"),
        ),
        ToolOp(
            name="github_list_releases",
            tool_id="github",
            kind="read",
            description="List recent GitHub releases (tag, draft/prerelease, notes). Discussions are not available (GraphQL only).",
            parameters=_obj({"limit": _int_param("Max results (1-20).", maximum=20)}),
            run=_gh(board_github.op_list_releases),
            summarize=_summ("Listed releases"),
        ),
        ToolOp(
            name="github_list_workflow_runs",
            tool_id="github",
            kind="read",
            description="List recent GitHub Actions runs (CI status, conclusions, branch).",
            parameters=_obj(
                {
                    "branch": _str_param("Optional branch filter.", max_len=100),
                    "limit": _int_param("Max results (1-20).", maximum=20),
                }
            ),
            run=_gh(board_github.op_list_workflow_runs),
            summarize=_summ("Checked CI runs"),
        ),
        ToolOp(
            name="github_list_commits",
            tool_id="github",
            kind="read",
            description="List recent commits on the default branch, optionally for one path.",
            parameters=_obj(
                {
                    "path": _str_param("Optional file or directory path.", max_len=200),
                    "limit": _int_param("Max results (1-20).", maximum=20),
                }
            ),
            run=_gh(board_github.op_list_commits),
            summarize=_summ("Listed recent commits"),
        ),
        ToolOp(
            name="github_get_file",
            tool_id="github",
            kind="read",
            description="Read a file (text, truncated) or list a directory in the repository.",
            parameters=_obj(
                {
                    "path": _str_param("Path from the repository root, e.g. README.md or docs/architecture.", max_len=200),
                    "ref": _str_param("Optional branch or tag.", max_len=100),
                },
                ["path"],
            ),
            run=_gh(board_github.op_get_file),
            summarize=_summ("Read {path}"),
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
        ToolOp(
            name="github_list_security_alerts",
            tool_id="github",
            kind="read",
            description="List open Dependabot and code-scanning alerts (needs a token with security_events access; otherwise reports why).",
            parameters=_obj({"limit": _int_param("Max alerts per kind (1-50).", maximum=50)}),
            run=_gh(board_github.op_list_security_alerts),
            summarize=_summ("Checked security alerts"),
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
        ToolOp(
            name="github_create_issue",
            tool_id="github",
            kind="write",
            always_propose=True,
            description="Open a new GitHub issue. Search first; never duplicate an open issue.",
            parameters=_obj(
                {
                    "title": _str_param("Short imperative title.", max_len=200),
                    "body": _str_param("Markdown body: context, acceptance criteria, links.", max_len=4000),
                    "labels": {"type": "array", "items": {"type": "string"}, "description": "Optional labels."},
                    "reason": REASON_PARAM,
                },
                ["title", "body", "reason"],
            ),
            run=_gh(board_github.op_create_issue),
            summarize=_summ("Open GitHub issue: {title}"),
        ),
        ToolOp(
            name="github_comment_issue",
            tool_id="github",
            kind="write",
            description="Add a comment to an existing issue or pull request.",
            parameters=_obj(
                {
                    "number": _int_param("Issue or PR number.", maximum=100000),
                    "body": _str_param("Markdown comment.", max_len=4000),
                    "reason": REASON_PARAM,
                },
                ["number", "body", "reason"],
            ),
            run=_gh(board_github.op_comment_issue),
            summarize=_summ("Comment on #{number}"),
        ),
        ToolOp(
            name="github_set_labels",
            tool_id="github",
            kind="write",
            description="Replace the labels on an issue or pull request.",
            parameters=_obj(
                {
                    "number": _int_param("Issue or PR number.", maximum=100000),
                    "labels": {"type": "array", "items": {"type": "string"}, "description": "Full label set to apply."},
                    "reason": REASON_PARAM,
                },
                ["number", "labels", "reason"],
            ),
            run=_gh(board_github.op_set_labels),
            summarize=_summ_labels,
        ),
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
        ToolOp(
            name="mail_list_mailboxes",
            tool_id="mail",
            kind="read",
            description="List the company mailboxes (hello@, billing@, ...) with thread and unread counts.",
            parameters=_obj({}),
            run=board_mail.op_list_mailboxes,
            summarize=_summ("Listed mailboxes"),
        ),
        ToolOp(
            name="mail_list_threads",
            tool_id="mail",
            kind="read",
            description=(
                "List email threads, newest first, optionally for one mailbox, matching keywords, or unread only. "
                "Contacts appear as stable aliases like contact#12; never guess real names or addresses. "
                "hasAttachments only signals files are present; PDF contents are not readable."
            ),
            parameters=_obj(
                {
                    "mailbox": _str_param("Optional mailbox (local part or full address).", max_len=120),
                    "query": _str_param("Optional keywords; all must match subject, snippet or sender.", max_len=200),
                    "unreadOnly": {"type": "boolean", "description": "Only threads the founder has not read yet."},
                    "limit": _int_param("Max threads (1-30).", maximum=30),
                }
            ),
            run=board_mail.op_list_threads,
            summarize=_summ_mail_list,
        ),
        ToolOp(
            name="mail_get_thread",
            tool_id="mail",
            kind="read",
            description=(
                "Read every message in one thread (bodies, text attachments and attachment names; contacts pseudonymised). "
                "PDF attachment text is NOT extracted: such files are listed under attachmentsSkipped, so ask the founder for anything inside a PDF."
            ),
            parameters=_obj({"threadId": _str_param("Thread id from mail_list_threads.", max_len=64)}, ["threadId"]),
            run=board_mail.op_get_thread,
            summarize=_summ("Read email thread {threadId}"),
        ),
        ToolOp(
            name="mail_contact_history",
            tool_id="mail",
            kind="read",
            description="List the threads a contact alias (e.g. contact#12) has taken part in.",
            parameters=_obj({"contact": _str_param("Contact alias exactly as shown in a thread.", max_len=40)}, ["contact"]),
            run=board_mail.op_contact_history,
            summarize=_summ("Looked up history for {contact}"),
        ),
        ToolOp(
            name="mail_reply",
            tool_id="mail",
            kind="write",
            description=(
                "Reply to the last inbound message of a thread from the mailbox it was sent to. "
                "Plain text only; write as the company, sign off as 'The siutindei team'."
            ),
            parameters=_obj(
                {
                    "threadId": _str_param("Thread id from mail_list_threads.", max_len=64),
                    "body": _str_param("Plain-text reply body.", max_len=BOARD_MAIL_BODY_MAX_CHARS),
                    "templateId": _str_param("Optional approved template id.", max_len=80),
                    "reason": REASON_PARAM,
                },
                ["threadId", "body", "reason"],
            ),
            run=board_mail._op_write("mail_reply"),
            summarize=_summ("Reply in email thread {threadId}"),
            act_guard=_reply_guard(
                "mail_reply",
                lambda ctx, args: board_mail.act_guard(ctx, args, op="mail_reply"),
            ),
            preview=lambda ctx, args: board_mail.owner_preview(ctx, args, op="mail_reply"),
        ),
        ToolOp(
            name="mail_send",
            tool_id="mail",
            kind="write",
            description="Start a new email from a company mailbox to one or more contacts (aliases or full addresses).",
            parameters=_obj(
                {
                    "fromMailbox": _str_param("Sending mailbox, e.g. hello or billing@siutindei.com.", max_len=120),
                    "to": {"type": "array", "items": {"type": "string"}, "description": "Recipients: contact aliases or addresses."},
                    "subject": _str_param("Subject line.", max_len=BOARD_MAIL_SUBJECT_MAX_LEN),
                    "body": _str_param("Plain-text body.", max_len=BOARD_MAIL_BODY_MAX_CHARS),
                    "reason": REASON_PARAM,
                },
                ["fromMailbox", "to", "subject", "body", "reason"],
            ),
            run=board_mail._op_write("mail_send"),
            summarize=_summ("Send email: {subject}"),
            act_guard=lambda ctx, args: board_mail.act_guard(ctx, args, op="mail_send"),
            preview=lambda ctx, args: board_mail.owner_preview(ctx, args, op="mail_send"),
        ),
        ToolOp(
            name="mail_forward",
            tool_id="mail",
            kind="write",
            description="Forward the latest message of a thread to a provider or vendor with a short note.",
            parameters=_obj(
                {
                    "threadId": _str_param("Thread id from mail_list_threads.", max_len=64),
                    "to": {"type": "array", "items": {"type": "string"}, "description": "Recipients: contact aliases or addresses."},
                    "note": _str_param("Short note placed above the forwarded message.", max_len=2000),
                    "reason": REASON_PARAM,
                },
                ["threadId", "to", "reason"],
            ),
            run=board_mail._op_write("mail_forward"),
            summarize=_summ("Forward email thread {threadId}"),
            act_guard=lambda ctx, args: board_mail.act_guard(ctx, args, op="mail_forward"),
            preview=lambda ctx, args: board_mail.owner_preview(ctx, args, op="mail_forward"),
        ),
        ToolOp(
            name="mail_report_phishing",
            tool_id="mail",
            kind="write",
            description=(
                "Flag a mailbox thread as suspected phishing for the founder. Always queued to Approvals; "
                "available to every role that can read mail, including the CISO."
            ),
            parameters=_obj(
                {
                    "threadId": _str_param("Thread id from mail_list_threads.", max_len=64),
                    "note": _str_param("Why this looks like phishing.", max_len=800),
                    "reason": REASON_PARAM,
                },
                ["threadId", "reason"],
            ),
            run=board_mail.op_report_phishing,
            summarize=_summ("Report phishing on thread {threadId}"),
            level_floor="read",
            always_propose=True,
            preview=board_mail.owner_preview_phishing,
        ),
        ToolOp(
            name="research_search",
            tool_id="research",
            kind="read",
            description="Search the public web (cached 24h). Use for competitor pages, market facts, or anything not in GitHub or company mail.",
            parameters=_obj(
                {
                    "query": _str_param("Search query.", max_len=BOARD_RESEARCH_QUERY_MAX_LEN),
                    "limit": _int_param("Max results (1-8).", maximum=8),
                },
                ["query"],
            ),
            run=board_research.op_search,
            summarize=_summ("Searched the web for '{query}'"),
        ),
        ToolOp(
            name="research_hk_news",
            tool_id="research",
            kind="read",
            description="Hong Kong market / education news (gov.hk, SCMP, The Standard), cached 24h.",
            parameters=_obj(
                {
                    "query": _str_param("Topic, e.g. 'after-school activities regulation'.", max_len=BOARD_RESEARCH_QUERY_MAX_LEN),
                    "limit": _int_param("Max results (1-8).", maximum=8),
                }
            ),
            run=board_research.op_hk_news,
            summarize=_summ("Looked up HK news on '{query}'"),
        ),
        ToolOp(
            name="research_edb_holidays",
            tool_id="research",
            kind="read",
            description="Education Bureau school-holiday calendar for Hong Kong (cached 24h).",
            parameters=_obj({"year": _str_param("Calendar year, e.g. 2026.", max_len=12)}),
            run=board_research.op_edb_holidays,
            summarize=_summ("Looked up EDB holidays"),
        ),
        ToolOp(
            name="research_venues",
            tool_id="research",
            kind="read",
            description="Public listings of children's activity venues in a Hong Kong district (cached 24h).",
            parameters=_obj(
                {
                    "district": _str_param("Hong Kong district, e.g. 'tuen mun' or 'kwun tong'.", max_len=40),
                    "kind": _str_param("Venue type, e.g. 'swimming' or 'coding class'.", max_len=80),
                    "limit": _int_param("Max results (1-8).", maximum=8),
                }
            ),
            run=board_research.op_venues,
            summarize=_summ("Looked up venues in {district}"),
        ),
        ToolOp(
            name="aws_monthly_cost",
            tool_id="aws",
            kind="read",
            description="Last full month of AWS UnblendedCost by service. scope is 'siutindei' when the stack tag filter matched, or 'account' (whole account, see note) when it did not (cached hourly).",
            parameters=_obj({}),
            run=board_aws.op_monthly_cost,
            summarize=_summ("Read AWS monthly cost"),
        ),
        ToolOp(
            name="aws_list_alarms",
            tool_id="aws",
            kind="read",
            description="CloudWatch alarms currently in ALARM, filtered to siutindei stacks (cached hourly).",
            parameters=_obj({}),
            run=board_aws.op_alarms,
            summarize=_summ("Listed CloudWatch alarms"),
        ),
        ToolOp(
            name="aws_lambda_health",
            tool_id="aws",
            kind="read",
            description="24-hour error count and average duration for the Lambda functions listed in BOARD_AWS_LAMBDA_NAMES; reports 'no functions configured' otherwise (cached hourly).",
            parameters=_obj({}),
            run=board_aws.op_lambda_health,
            summarize=_summ("Read Lambda health"),
        ),
        ToolOp(
            name="aws_health_events",
            tool_id="aws",
            kind="read",
            description="Open or upcoming AWS Health events (needs Business support; cached hourly).",
            parameters=_obj({}),
            run=board_aws.op_health_events,
            summarize=_summ("Listed AWS Health events"),
        ),
        ToolOp(
            name="aws_propose_budget_alert",
            tool_id="aws",
            kind="write",
            always_propose=True,
            description="Propose that the founder create an AWS Budget alert. Does not change AWS; approval adds an action item.",
            parameters=_obj(
                {
                    "monthlyUsd": {"type": "number", "description": "Monthly ceiling in USD."},
                    "thresholdPercent": {"type": "number", "description": "Alert at this percent of the ceiling (default 80)."},
                    "reason": REASON_PARAM,
                },
                ["monthlyUsd", "reason"],
            ),
            run=board_aws.op_propose_budget_alert,
            summarize=_summ("Propose AWS budget alert at ${monthlyUsd}/mo"),
        ),
        ToolOp(
            name="security_github_alerts",
            tool_id="security",
            kind="read",
            description="Open Dependabot, code-scanning and secret-scanning alerts on the siutindei repo (cached hourly).",
            parameters=_obj({"limit": _int_param("Max alerts per type (1-50).", maximum=50)}),
            run=board_security.op_github_alerts,
            summarize=_summ("Listed GitHub security alerts"),
        ),
        ToolOp(
            name="security_aws_findings",
            tool_id="security",
            kind="read",
            description="Active HIGH/CRITICAL Security Hub findings and IAM Access Analyzer findings (cached hourly).",
            parameters=_obj({}),
            run=board_security.op_hub_findings,
            summarize=_summ("Listed AWS security findings"),
        ),
        ToolOp(
            name="security_cognito",
            tool_id="security",
            kind="read",
            description="Cognito user-pool MFA, tier, threat-protection mode, password policy, and 24h CloudWatch sign-in throttles/successes. Failed sign-ins are not measured; no user listing.",
            parameters=_obj({}),
            run=board_security.op_cognito,
            summarize=_summ("Read Cognito security posture"),
        ),
        ToolOp(
            name="security_open_remediation",
            tool_id="security",
            kind="write",
            always_propose=True,
            description="Open a GitHub issue describing a finding and the fix. Always a proposal until the founder approves.",
            parameters=_obj(
                {
                    "title": _str_param("Issue title.", max_len=200),
                    "body": _str_param("Markdown: finding, impact, proposed fix.", max_len=4000),
                    "labels": {"type": "array", "items": {"type": "string"}, "description": "Labels; 'security' is added if missing."},
                    "reason": REASON_PARAM,
                },
                ["title", "body", "reason"],
            ),
            run=board_security.op_open_remediation,
            summarize=_summ("Propose security issue: {title}"),
        ),
        ToolOp(
            name="product_catalog_health",
            tool_id="product",
            kind="read",
            description="Catalog counts by district/category with completeness (photos, price, schedule, geocode).",
            parameters=_obj(
                {
                    "district": _str_param("Optional Hong Kong district.", max_len=40),
                    "category": _str_param("Optional activity category.", max_len=40),
                }
            ),
            run=board_product.op_catalog_health,
            summarize=_summ("Read catalog health"),
        ),
        ToolOp(
            name="product_funnel",
            tool_id="product",
            kind="read",
            description="Daily searches, listing views, CTA taps, leads and bookings from v_funnel_daily.",
            parameters=_obj(
                {
                    "from": _str_param("Start date YYYY-MM-DD.", max_len=10),
                    "to": _str_param("End date YYYY-MM-DD.", max_len=10),
                    "district": _str_param("Optional district.", max_len=40),
                }
            ),
            run=board_product.op_funnel,
            summarize=_summ("Read product funnel"),
        ),
        ToolOp(
            name="product_provider_pipeline",
            tool_id="product",
            kind="read",
            description="Provider sign-ups, onboarding step, days since last edit, subscription status.",
            parameters=_obj({"status": _str_param("Optional subscription status.", enum=["trial", "active", "past_due", "cancelled"])}),
            run=board_product.op_provider_pipeline,
            summarize=_summ("Read provider pipeline"),
        ),
        ToolOp(
            name="product_flag_listing",
            tool_id="product",
            kind="write",
            description="Flag a listing for the founder to review. Does not change the catalog.",
            parameters=_obj(
                {
                    "listingId": _str_param("Listing or activity id.", max_len=64),
                    "reason": REASON_PARAM,
                },
                ["listingId", "reason"],
            ),
            run=board_product.op_flag_listing,
            summarize=_summ("Flag listing {listingId}"),
        ),
        ToolOp(
            name="meta_page_insights",
            tool_id="meta",
            kind="read",
            description="Facebook Page daily insights (impressions, engaged users).",
            parameters=_obj({"metric": _str_param("Comma-separated insight metrics.", max_len=120)}),
            run=board_meta.op_page_insights,
            summarize=_summ("Read Page insights"),
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
        ToolOp(
            name="meta_ig_insights",
            tool_id="meta",
            kind="read",
            description="Instagram daily insights (impressions, reach, profile views).",
            parameters=_obj({"metric": _str_param("Comma-separated insight metrics.", max_len=120)}),
            run=board_meta.op_ig_insights,
            summarize=_summ("Read Instagram insights"),
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
        ToolOp(
            name="meta_list_comments",
            tool_id="meta",
            kind="read",
            description="Recent Page posts and their comments (contacts masked).",
            parameters=_obj({"limit": _int_param("How many posts.", maximum=BOARD_META_LIST_MAX)}),
            run=board_meta.op_list_comments,
            summarize=_summ("Listed Page comments"),
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
        ToolOp(
            name="meta_list_dms",
            tool_id="meta",
            kind="read",
            description="Inbound Facebook Page DMs stored from the webhook (masked).",
            parameters=_obj({"limit": _int_param("How many threads.", maximum=40)}),
            run=board_meta.op_list_dms,
            summarize=_summ("Listed Page DMs"),
        ),
        ToolOp(
            name="meta_list_whatsapp",
            tool_id="meta",
            kind="read",
            description="Inbound WhatsApp threads stored from the webhook (masked). Notes the 24-hour window.",
            parameters=_obj({"limit": _int_param("How many threads.", maximum=40)}),
            run=board_meta.op_list_whatsapp,
            summarize=_summ("Listed WhatsApp threads"),
        ),
        ToolOp(
            name="meta_list_whatsapp_templates",
            tool_id="meta",
            kind="read",
            description="List approved WhatsApp message templates (name, language, status). Use a template name when the 24-hour window is closed.",
            parameters=_obj({}),
            run=board_meta.op_list_whatsapp_templates,
            summarize=_summ("Listed WhatsApp templates"),
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
        ToolOp(
            name="meta_ad_spend",
            tool_id="meta",
            kind="read",
            description="This month's ad account spend versus the monthly cap.",
            parameters=_obj({}),
            run=board_meta.op_ad_spend,
            summarize=_summ("Read ad spend"),
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
        ToolOp(
            name="meta_propose_post",
            tool_id="meta",
            kind="write",
            always_propose=True,
            description="Draft a Facebook Page post. Publishes only after the founder approves.",
            parameters=_obj(
                {
                    "message": _str_param("Post text.", max_len=2000),
                    "reason": REASON_PARAM,
                },
                ["message", "reason"],
            ),
            run=board_meta.op_propose_post,
            summarize=_summ("Propose Page post"),
            preview=lambda ctx, args: board_meta.owner_preview_message(ctx, args, op="meta_propose_post"),
        ),
        ToolOp(
            name="meta_propose_story",
            tool_id="meta",
            kind="write",
            always_propose=True,
            description="Draft an Instagram story from an image URL.",
            parameters=_obj(
                {
                    "imageUrl": _str_param("Public image URL.", max_len=500),
                    "caption": _str_param("Optional caption.", max_len=500),
                    "reason": REASON_PARAM,
                },
                ["imageUrl", "reason"],
            ),
            run=board_meta.op_propose_story,
            summarize=_summ("Propose Instagram story"),
            preview=lambda ctx, args: board_meta.owner_preview_message(ctx, args, op="meta_propose_story"),
        ),
        ToolOp(
            name="meta_reply_comment",
            tool_id="meta",
            kind="write",
            description="Reply to a Page or Instagram comment.",
            parameters=_obj(
                {
                    "commentId": _str_param("Graph comment id.", max_len=64),
                    "message": _str_param("Reply text.", max_len=1000),
                    "templateId": _str_param("Optional approved template id.", max_len=80),
                    "reason": REASON_PARAM,
                },
                ["commentId", "message", "reason"],
            ),
            run=board_meta.op_reply_comment,
            summarize=_summ("Reply to comment {commentId}"),
            act_guard=_reply_guard("meta_reply_comment"),
            preview=lambda ctx, args: board_meta.owner_preview_message(ctx, args, op="meta_reply_comment"),
        ),
        ToolOp(
            name="meta_reply_dm",
            tool_id="meta",
            kind="write",
            description="Reply to a Page DM. Act only to allow-listed recipients.",
            parameters=_obj(
                {
                    "threadId": _str_param("Stored DM thread id (preferred; the recipient is taken from it). One of threadId or recipientId is required.", max_len=40),
                    "recipientId": _str_param("Page-scoped user id, only when no thread is stored.", max_len=64),
                    "message": _str_param("Reply text.", max_len=1000),
                    "reason": REASON_PARAM,
                },
                ["message", "reason"],
            ),
            run=board_meta.op_reply_dm,
            summarize=_summ("Reply to Page DM {threadId}"),
            act_guard=_reply_guard(
                "meta_reply_dm",
                lambda ctx, args: board_meta.act_guard_allow_list(ctx, args, field="recipientId"),
            ),
            preview=lambda ctx, args: board_meta.owner_preview_message(ctx, args, op="meta_reply_dm"),
        ),
        ToolOp(
            name="meta_reply_whatsapp",
            tool_id="meta",
            kind="write",
            description="Reply on WhatsApp. Act only inside the 24-hour window to an allow-listed number; otherwise propose a template.",
            parameters=_obj(
                {
                    "threadId": _str_param("Stored WhatsApp thread id (preferred; the number is taken from it). One of threadId or to is required.", max_len=40),
                    "to": _str_param("WhatsApp number (E.164), only when no thread is stored.", max_len=20),
                    "message": _str_param("Reply text (session message).", max_len=1000),
                    "template": _str_param("Pre-approved template name when the window is closed.", max_len=80),
                    "language": _str_param("Template language code.", max_len=8),
                    "reason": REASON_PARAM,
                },
                ["reason"],
            ),
            run=board_meta.op_reply_whatsapp,
            summarize=_summ("WhatsApp reply in thread {threadId}"),
            act_guard=_reply_guard("meta_reply_whatsapp", board_meta.act_guard_whatsapp),
            preview=lambda ctx, args: board_meta.owner_preview_message(ctx, args, op="meta_reply_whatsapp"),
        ),
        ToolOp(
            name="meta_create_ad_set",
            tool_id="meta",
            kind="write",
            description="Create a PAUSED ad set. Act only when the daily and monthly ads caps still have room; otherwise propose.",
            parameters=_obj(
                {
                    "name": _str_param("Ad set name.", max_len=80),
                    "dailyBudgetUsd": {"type": "number", "description": "Daily budget in USD."},
                    "campaignId": _str_param("Existing campaign id.", max_len=64),
                    "reason": REASON_PARAM,
                },
                ["name", "dailyBudgetUsd", "reason"],
            ),
            run=board_meta.op_create_ad_set,
            summarize=_summ("Create ad set {name}"),
            act_guard=board_meta.act_guard_ad_set,
            preview=lambda ctx, args: board_meta.owner_preview_message(ctx, args, op="meta_create_ad_set"),
        ),
        ToolOp(
            name="meta_boost_post",
            tool_id="meta",
            kind="write",
            description="Boost a Page post. Act only when the daily and monthly ads caps still have room; otherwise propose.",
            parameters=_obj(
                {
                    "postId": _str_param("Page post id (or pageId_postId).", max_len=80),
                    "dailyBudgetUsd": {"type": "number", "description": "Daily budget in USD."},
                    "days": {"type": "integer", "description": "How many days to boost (1–30)."},
                    "reason": REASON_PARAM,
                },
                ["postId", "dailyBudgetUsd", "days", "reason"],
            ),
            run=board_meta.op_boost_post,
            summarize=_summ("Boost post {postId}"),
            act_guard=board_meta.act_guard_boost_post,
            preview=lambda ctx, args: board_meta.owner_preview_message(ctx, args, op="meta_boost_post"),
        ),
        ToolOp(
            name="meta_relay_lead",
            tool_id="meta",
            kind="write",
            description=(
                "COO: hand a parent lead to the provider (email, or WhatsApp template with providerPhone) and confirm to the parent. "
                "Recorded as a board action. Always propose until every address/number is allow-listed."
            ),
            parameters=_obj(
                {
                    "providerEmail": _str_param("Provider address.", max_len=120),
                    "providerPhone": _str_param("Provider WhatsApp number (E.164) for a template hand-off.", max_len=20),
                    "template": _str_param("Approved WhatsApp template name (required with providerPhone).", max_len=80),
                    "language": _str_param("Template language code.", max_len=8),
                    "parentEmail": _str_param("Parent address.", max_len=120),
                    "summary": _str_param("What the parent asked for.", max_len=800),
                    "reason": REASON_PARAM,
                },
                ["parentEmail", "reason"],
            ),
            run=board_meta.op_relay_lead,
            summarize=_summ("Relay lead for {parentEmail}"),
            act_guard=board_meta.act_guard_relay,
            preview=lambda ctx, args: board_meta.owner_preview_message(ctx, args, op="meta_relay_lead"),
        ),
        ToolOp(
            name="finance_list_subscriptions",
            tool_id="finance",
            kind="read",
            description="Listing subscriptions with plan name, price and payer contact.",
            parameters=_obj({"status": _str_param("Optional status.", enum=["trial", "active", "past_due", "cancelled"])}),
            run=board_receivables.op_list_subscriptions,
            summarize=_summ("Listed subscriptions"),
        ),
        ToolOp(
            name="finance_list_invoices",
            tool_id="finance",
            kind="read",
            description="Invoices with FPS reference, amount and status.",
            parameters=_obj({"status": _str_param("Optional status.", enum=["draft", "sent", "paid", "overdue", "void"])}),
            run=board_receivables.op_list_invoices,
            summarize=_summ("Listed invoices"),
        ),
        ToolOp(
            name="finance_aging_report",
            tool_id="finance",
            kind="read",
            description="Receivables aging: current / D+7 / D+21 / D+35, DSO (trailing 90-day paid revenue) and past-due by provider.",
            parameters=_obj({}),
            run=board_receivables.op_aging_report,
            summarize=_summ("Ran aging report"),
        ),
        ToolOp(
            name="finance_unit_economics",
            tool_id="finance",
            kind="read",
            description="Revenue per subscription, month-to-date CPA (AWS + Meta USD per new subscription) and gross margin at a fixed 7.8 HKD/USD; Meta from Graph month-to-date.",
            parameters=_obj({}),
            run=board_receivables.op_unit_economics,
            summarize=_summ("Read unit economics"),
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
        ToolOp(
            name="finance_draft_invoice",
            tool_id="finance",
            kind="write",
            always_propose=True,
            description="Create a draft invoice with a unique FPS reference for a subscription.",
            parameters=_obj(
                {
                    "subscriptionId": _str_param("listing_subscriptions.id.", max_len=64),
                    "amountHkd": {"type": "number", "description": "Amount in HKD."},
                    "dueInDays": _int_param("Days until due (1-90).", maximum=90),
                    "reason": REASON_PARAM,
                },
                ["subscriptionId", "amountHkd", "reason"],
            ),
            run=board_receivables.op_draft_invoice,
            summarize=_summ("Draft invoice for {subscriptionId}"),
        ),
        ToolOp(
            name="finance_send_invoice",
            tool_id="finance",
            kind="write",
            description="Email an invoice from billing@siutindei.com. Act only for allow-listed payers.",
            parameters=_obj(
                {
                    "invoiceId": _str_param("invoices.id.", max_len=64),
                    "reason": REASON_PARAM,
                },
                ["invoiceId", "reason"],
            ),
            run=board_receivables.op_send_invoice,
            summarize=_summ("Send invoice {invoiceId}"),
            act_guard=lambda ctx, args: board_receivables.act_guard_send(ctx, args, op="finance_send_invoice"),
            preview=lambda ctx, args: board_receivables.owner_preview_send(ctx, args, op="finance_send_invoice"),
        ),
        ToolOp(
            name="finance_send_reminder",
            tool_id="finance",
            kind="write",
            description="Dunning reminder at D+7 / D+21 / D+35. Act only for allow-listed payers.",
            parameters=_obj(
                {
                    "invoiceId": _str_param("invoices.id.", max_len=64),
                    "stage": _str_param("Dunning stage; set by the nightly scheduler.", enum=["d7", "d21", "d35"]),
                    "reason": REASON_PARAM,
                },
                ["invoiceId", "reason"],
            ),
            run=board_receivables.op_send_reminder,
            summarize=_summ("Send reminder for {invoiceId}"),
            act_guard=lambda ctx, args: board_receivables.act_guard_send(ctx, args, op="finance_send_reminder"),
            preview=lambda ctx, args: board_receivables.owner_preview_send(ctx, args, op="finance_send_reminder"),
        ),
        ToolOp(
            name="finance_match_payment",
            tool_id="finance",
            kind="write",
            description="Attach a payment to an invoice. Act only when amount and FPS reference agree and the invoice is open; otherwise propose with candidate invoices.",
            parameters=_obj(
                {
                    "paymentId": _str_param("payments.id.", max_len=64),
                    "invoiceId": _str_param("invoices.id.", max_len=64),
                    "reason": REASON_PARAM,
                },
                ["paymentId", "invoiceId", "reason"],
            ),
            run=board_receivables.op_match_payment,
            summarize=_summ("Match payment {paymentId} to {invoiceId}"),
            act_guard=board_receivables.act_guard_match,
        ),
        ToolOp(
            name="finance_propose_price_change",
            tool_id="finance",
            kind="write",
            always_propose=True,
            description="Create a listing_plans row (pricing proposal). First approved plan seeds the price list.",
            parameters=_obj(
                {
                    "name": _str_param("Plan name, e.g. 'Store listing — monthly'.", max_len=80),
                    "priceHkd": {"type": "number", "description": "Price in HKD."},
                    "billingPeriod": _str_param("monthly or annual.", enum=["monthly", "annual"]),
                    "reason": REASON_PARAM,
                },
                ["name", "priceHkd", "billingPeriod", "reason"],
            ),
            run=board_receivables.op_propose_price_change,
            summarize=_summ("Propose plan {name} at ${priceHkd}"),
        ),
        ToolOp(
            name="finance_record_manual_payment",
            tool_id="finance",
            kind="write",
            always_propose=True,
            description="Record cash or cheque handed over in person (source=manual).",
            parameters=_obj(
                {
                    "amountHkd": {"type": "number", "description": "Amount in HKD."},
                    "receivedOn": _str_param("Date received YYYY-MM-DD.", max_len=10),
                    "payerName": _str_param("Who paid.", max_len=120),
                    "bankReference": _str_param("Optional FPS or cheque reference.", max_len=80),
                    "invoiceId": _str_param("Optional invoice to match.", max_len=64),
                    "reason": REASON_PARAM,
                },
                ["amountHkd", "reason"],
            ),
            run=board_receivables.op_record_manual_payment,
            summarize=_summ("Record manual payment of ${amountHkd}"),
        ),
        ToolOp(
            name="stores_metrics",
            tool_id="stores",
            kind="read",
            description="Cached App Store Connect and Google Play ratings, review counts and latest App Store version. Apple downloads come from yesterday's daily sales report (needs ASC_VENDOR_NUMBER); installs are not available from these APIs and are reported as null.",
            parameters=_obj({}),
            run=board_stores.op_metrics,
            summarize=_summ("Read store metrics"),
        ),
        ToolOp(
            name="stores_crashes",
            tool_id="stores",
            kind="read",
            description="Play daily crash rate (last 7 days) and App Store hang/performance metrics — Apple exposes no crash counts (cached).",
            parameters=_obj({}),
            run=board_stores.op_crashes,
            summarize=_summ("Read store crashes"),
        ),
        ToolOp(
            name="stores_ratings",
            tool_id="stores",
            kind="read",
            description="Average ratings and review counts for App Store and Play (cached).",
            parameters=_obj({}),
            run=board_stores.op_ratings,
            summarize=_summ("Read store ratings"),
        ),
        ToolOp(
            name="stores_list_reviews",
            tool_id="stores",
            kind="read",
            description="Recent customer reviews and reply status. Contacts in the text are masked.",
            parameters=_obj(
                {
                    "store": _str_param("apple, play, or both.", enum=["apple", "play", "both"]),
                    "limit": _int_param("How many reviews.", maximum=BOARD_STORES_LIST_MAX),
                }
            ),
            run=board_stores.op_list_reviews,
            summarize=_summ("Listed store reviews"),
        ),
        ToolOp(
            name="stores_reply_review",
            tool_id="stores",
            kind="write",
            description="Reply to an App Store or Play review. The CMO may act; everyone else proposes.",
            parameters=_obj(
                {
                    "store": _str_param("Which store.", enum=["apple", "play"]),
                    "reviewId": _str_param("Store review id.", max_len=80),
                    "message": _str_param("Reply text.", max_len=1000),
                    "templateId": _str_param("Optional approved template id.", max_len=80),
                    "reason": REASON_PARAM,
                },
                ["store", "reviewId", "message", "reason"],
            ),
            run=board_stores.op_reply_review,
            summarize=_summ("Reply to {store} review {reviewId}"),
            act_guard=_reply_guard("stores_reply_review"),
            preview=lambda ctx, args: board_stores.owner_preview_message(ctx, args, op="stores_reply_review"),
        ),
        ToolOp(
            name="stores_draft_release_notes",
            tool_id="stores",
            kind="write",
            description="Draft What's New / release notes. Always goes to Approvals; never published automatically.",
            parameters=_obj(
                {
                    "store": _str_param("apple, play, or both.", enum=["apple", "play", "both"]),
                    "version": _str_param("Version string, if known.", max_len=20),
                    "locale": _str_param("Locale code.", max_len=12),
                    "notes": _str_param("Draft What's New text.", max_len=2000),
                    "reason": REASON_PARAM,
                },
                ["notes", "reason"],
            ),
            run=board_stores.op_draft_release_notes,
            summarize=_summ("Draft release notes"),
            act_guard=board_stores.act_guard_release_notes,
            preview=lambda ctx, args: board_stores.owner_preview_message(ctx, args, op="stores_draft_release_notes"),
        ),
        ToolOp(
            name="web_sessions",
            tool_id="web",
            kind="read",
            description="GA4 sessions, users, top pages and referrers for the last 7 days (cached). Optional propertyId when several properties are configured.",
            parameters=_obj(
                {
                    "propertyId": _str_param("GA4 property id. Omit to read every configured property.", max_len=32),
                    "limit": _int_param("How many pages / referrers.", maximum=BOARD_WEB_LIST_MAX),
                }
            ),
            run=board_web.op_sessions,
            summarize=_summ("Read GA4 sessions"),
        ),
        ToolOp(
            name="web_conversions",
            tool_id="web",
            kind="read",
            description="GA4 event counts and conversions for the last 7 days (cached).",
            parameters=_obj(
                {
                    "propertyId": _str_param("GA4 property id. Omit to read every configured property.", max_len=32),
                    "limit": _int_param("How many events.", maximum=BOARD_WEB_LIST_MAX),
                }
            ),
            run=board_web.op_conversions,
            summarize=_summ("Read GA4 conversions"),
        ),
        ToolOp(
            name="web_gtm_status",
            tool_id="web",
            kind="read",
            description="GTM container name, public id and live version (cached). Publish is a later milestone.",
            parameters=_obj(
                {"containerId": _str_param("GTM container id. Omit to read every configured container.", max_len=32)}
            ),
            run=board_web.op_gtm_status,
            summarize=_summ("Read GTM status"),
        ),
        ToolOp(
            name="intel_list_watchlist",
            tool_id="intel",
            kind="read",
            description="List competitor, directory and candidate watches.",
            parameters=_obj({}),
            run=_intel_list_watchlist,
            summarize=_summ("Listed the watchlist"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="intel_get_changes",
            tool_id="intel",
            kind="read",
            description="Change notes from the daily crawl (pricing, features, categories, other).",
            parameters=_obj({"days": _int_param("How many days back (1-30).", minimum=1, maximum=30)}),
            run=_intel_get_changes,
            summarize=_summ("Read watchlist changes"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="intel_fetch_page",
            tool_id="intel",
            kind="read",
            description="Fetch one allowed public URL (robots-checked). Returns a short text digest, never a whole page.",
            parameters=_obj({"url": _str_param("https URL to fetch.", max_len=500)}, ["url"]),
            run=_intel_fetch_page,
            summarize=_summ("Fetched a public page"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="intel_competitor_reviews",
            tool_id="intel",
            kind="read",
            description="Public App Store / Play reviews for a watch that has app ids.",
            parameters=_obj({"watchId": _str_param("Watch id.", max_len=40)}, ["watchId"]),
            run=_intel_competitor_reviews,
            summarize=_summ("Read competitor store reviews"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="intel_search_rank",
            tool_id="intel",
            kind="read",
            description="Search-rank snapshot for a query (research_search, cached).",
            parameters=_obj({"query": _str_param("Search query.", max_len=BOARD_RESEARCH_QUERY_MAX_LEN)}, ["query"]),
            run=_intel_search_rank,
            summarize=_summ("Checked search rank"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="outreach_search_places",
            tool_id="outreach",
            kind="read",
            description="Search Google Places (New) in Hong Kong. Costs count against the monthly Places cap.",
            parameters=_obj(
                {
                    "query": _str_param("What to search for.", max_len=200),
                    "district": _str_param("Optional Hong Kong district.", max_len=40),
                },
                ["query"],
            ),
            run=_outreach_search_places,
            summarize=_summ("Searched Places"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="outreach_open_data",
            tool_id="outreach",
            kind="read",
            description="Read FEHD restaurants, EDB schools or LCSD venues (cached open data).",
            parameters=_obj(
                {
                    "kind": _str_param("Dataset.", enum=["fehd", "edb", "lcsd"]),
                    "district": _str_param("Optional district filter.", max_len=40),
                },
                ["kind"],
            ),
            run=_outreach_open_data,
            summarize=_summ("Read open data"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="outreach_list_prospects",
            tool_id="outreach",
            kind="read",
            description="List prospects. Contacts are masked.",
            parameters=_obj(
                {
                    "stage": _str_param("Optional stage filter.", max_len=20),
                    "type": _str_param("Optional type filter.", max_len=20),
                    "limit": _int_param("Max rows (1-50).", maximum=50),
                }
            ),
            run=_outreach_list_prospects,
            summarize=_summ("Listed prospects"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="outreach_get_prospect",
            tool_id="outreach",
            kind="read",
            description="Get one prospect. Email and phone are masked.",
            parameters=_obj({"id": _str_param("Prospect id.", max_len=40)}, ["id"]),
            run=_outreach_get_prospect,
            summarize=_summ("Read a prospect"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="outreach_upsert_prospect",
            tool_id="outreach",
            kind="write",
            description="Create or update a prospect from public data. Dedupes by domain, phone or place id.",
            parameters=_obj(
                {
                    "name": _str_param("Organisation name.", max_len=200),
                    "type": _str_param("Prospect type.", enum=list(BOARD_STAFF_PROSPECT_TYPES)),
                    "district": _str_param("Hong Kong district.", max_len=40),
                    "website": _str_param("Public website.", max_len=300),
                    "phone": _str_param("Public phone.", max_len=40),
                    "email": _str_param("Public email.", max_len=120),
                    "placeId": _str_param("Google place id.", max_len=80),
                    "source": _str_param("Where this came from.", max_len=40),
                    "reason": REASON_PARAM,
                },
                ["name", "type"],
            ),
            run=_outreach_upsert_prospect,
            summarize=_summ("Upserted a prospect"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="outreach_score_prospect",
            tool_id="outreach",
            kind="read",
            description="Score a prospect with the fit rubric (one desk model call) and qualify it.",
            parameters=_obj({"id": _str_param("Prospect id.", max_len=40)}, ["id"]),
            run=_outreach_score_prospect,
            summarize=_summ("Scored a prospect"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="outreach_start_sequence",
            tool_id="outreach",
            kind="write",
            description="Start the outreach sequence for a qualified prospect with a contact.",
            parameters=_obj(
                {
                    "id": _str_param("Prospect id.", max_len=40),
                    "reason": REASON_PARAM,
                },
                ["id"],
            ),
            run=_outreach_start_sequence,
            summarize=_summ("Started a sequence"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="outreach_send",
            tool_id="outreach",
            kind="write",
            description="Send one sequence step to a prospect. First touches are cold-outreach holds until the class is promoted.",
            parameters=_obj(
                {
                    "prospectId": _str_param("Prospect id.", max_len=40),
                    "stepIndex": _int_param("Sequence step (0-2).", minimum=0, maximum=5),
                    "personalisation": _str_param("Fit note, at most 400 characters.", max_len=400),
                    "reason": REASON_PARAM,
                },
                ["prospectId"],
            ),
            run=_outreach_send,
            summarize=_summ("Sent outreach"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="outreach_suppress",
            tool_id="outreach",
            kind="write",
            description="Suppress a prospect so they are never emailed again.",
            parameters=_obj(
                {
                    "id": _str_param("Prospect id.", max_len=40),
                    "reason": _str_param("Why they are suppressed.", max_len=200),
                },
                ["id", "reason"],
            ),
            run=_outreach_suppress,
            summarize=_summ("Suppressed a prospect"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="content_list",
            tool_id="content",
            kind="read",
            description="List calendar items, optionally filtered by status.",
            parameters=_obj({"status": _str_param("Content status.", max_len=20), "limit": _int_param("Max rows.", minimum=1, maximum=80)}),
            run=_content_list,
            summarize=_summ("Listed calendar items"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="content_get",
            tool_id="content",
            kind="read",
            description="Get one calendar item including copy and creative keys.",
            parameters=_obj({"contentId": _str_param("Content id.", max_len=40)}, ["contentId"]),
            run=_content_get,
            summarize=_summ("Read a calendar item"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="content_publish",
            tool_id="content",
            kind="write",
            description="Publish a scheduled calendar item to Facebook or Instagram. Held until slotAt.",
            parameters=_obj(
                {
                    "contentId": _str_param("Content id.", max_len=40),
                    "slotAt": _str_param("ISO slot time (HKT).", max_len=40),
                    "channel": _str_param("Publish channel.", max_len=40),
                    "reason": REASON_PARAM,
                },
                ["contentId"],
            ),
            run=_content_publish,
            summarize=_summ("Published a calendar item"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="newsletter_draft_issue",
            tool_id="newsletter",
            kind="write",
            description="Draft a fortnightly newsletter issue from recent content and catalogue highlights.",
            parameters=_obj(
                {
                    "list": _str_param("parents or providers.", enum=list(BOARD_STAFF_NEWSLETTER_LISTS)),
                    "markdown": _str_param("Optional Markdown body.", max_len=20000),
                    "reason": REASON_PARAM,
                },
                ["list"],
            ),
            run=_newsletter_draft_issue,
            summarize=_summ("Drafted a newsletter issue"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="newsletter_send",
            tool_id="newsletter",
            kind="write",
            description="Send a drafted issue to one confirmed list. Held as publish:newsletter.",
            parameters=_obj(
                {
                    "issueId": _str_param("Issue id.", max_len=40),
                    "list": _str_param("parents or providers.", enum=list(BOARD_STAFF_NEWSLETTER_LISTS)),
                    "reason": REASON_PARAM,
                },
                ["issueId", "list"],
            ),
            run=_newsletter_send,
            summarize=_summ("Sent a newsletter issue"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="code_run_task",
            tool_id="code",
            kind="write",
            description="Dispatch the coding runner. Opens a draft PR on board/{taskId} from staging. Does not merge.",
            parameters=_obj(
                {
                    "issueNumber": _int_param("GitHub issue number.", minimum=1, maximum=100000),
                    "brief": _str_param("What to implement. Include acceptance criteria.", max_len=4000),
                    "kind": _str_param("feature, fix or content (SEO).", enum=["feature", "fix", "content"]),
                    "reason": REASON_PARAM,
                },
                ["issueNumber", "brief"],
            ),
            run=_code_run_task,
            summarize=_summ("Dispatched the coding runner"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="code_get_run",
            tool_id="code",
            kind="read",
            description="Poll the Actions run and draft PR for a runner task_id.",
            parameters=_obj({"taskId": _str_param("Staff or runner task id.", max_len=40)}),
            run=_code_get_run,
            summarize=_summ("Polled a coding run"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="code_review_pr",
            tool_id="code",
            kind="read",
            description="Read a pull request: diff stats, paths, CI, and a 30 000 character diff for architect review.",
            parameters=_obj({"prNumber": _int_param("Pull request number.", minimum=1, maximum=100000)}, ["prNumber"]),
            run=_code_review_pr,
            summarize=_summ("Reviewed a pull request"),
            contexts=("chat", "meeting", "task"),
            timeout_seconds=25,
        ),
        ToolOp(
            name="code_merge_staging",
            tool_id="code",
            kind="write",
            description="Merge a board/* PR into staging after CI, architect accept, size and path checks. Held as code_staging.",
            parameters=_obj(
                {
                    "prNumber": _int_param("Pull request number.", minimum=1, maximum=100000),
                    "kind": _str_param("feature, fix or content.", enum=["feature", "fix", "content"]),
                    "reason": REASON_PARAM,
                },
                ["prNumber"],
            ),
            run=_code_merge_staging,
            summarize=_summ("Merged a pull request to staging"),
            contexts=("chat", "meeting", "task"),
            act_guard=_code_merge_guard,
        ),
        ToolOp(
            name="code_promote",
            tool_id="code",
            kind="write",
            description="Open or update the staging→main promotion PR. Always an Approval; the owner merges in GitHub.",
            parameters=_obj(
                {
                    "kind": _str_param("Always production in v1.", enum=["production"]),
                    "reason": REASON_PARAM,
                }
            ),
            run=_code_promote,
            summarize=_summ("Proposed a staging promotion"),
            contexts=("chat", "meeting", "task"),
            always_propose=True,
        ),
        ToolOp(
            name="staff_assign",
            tool_id="staff",
            kind="write",
            description="Assign a background task to a board member or an active staff seat. The assignee works in steps and produces a deliverable for review.",
            parameters=_obj(
                {
                    "assignee": _str_param("Persona id or active seat id.", max_len=40),
                    "brief": _str_param("What to do. Be specific about the evidence to gather.", max_len=4000),
                    "deliverableType": _str_param(
                        "Deliverable format.",
                        enum=list(BOARD_STAFF_DELIVERABLE_TYPES),
                    ),
                    "slaHours": _int_param("Hours until the SLA (1-168).", minimum=1, maximum=168),
                    "budgetUsd": {"type": "number", "description": "Optional USD cap for this task."},
                    "actionId": _str_param("Optional action id to close when the task is accepted.", max_len=40),
                    "reason": REASON_PARAM,
                },
                ["assignee", "brief", "deliverableType"],
            ),
            run=_staff_assign,
            summarize=_summ_staff_assign,
            act_guard=_staff_assign_guard,
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="staff_list_tasks",
            tool_id="staff",
            kind="read",
            description="List staff tasks. Seats see only their own; executives see all.",
            parameters=_obj(
                {
                    "status": _str_param("Optional status filter.", max_len=20),
                    "limit": _int_param("Max tasks (1-50).", maximum=50),
                }
            ),
            run=_staff_list_tasks,
            summarize=_summ("Listed staff tasks"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="staff_get_deliverable",
            tool_id="staff",
            kind="read",
            description="Read a task summary and the first 6000 characters of its deliverable.",
            parameters=_obj({"taskId": _str_param("Task id.", max_len=40)}, ["taskId"]),
            run=_staff_get_deliverable,
            summarize=_summ("Read staff deliverable"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="staff_request_revision",
            tool_id="staff",
            kind="write",
            description="Ask the assignee to revise a task that is in review. Only the manager of the task may do this.",
            parameters=_obj(
                {
                    "taskId": _str_param("Task id.", max_len=40),
                    "notes": _str_param("What to change.", max_len=2000),
                    "reason": REASON_PARAM,
                },
                ["taskId", "notes"],
            ),
            run=_staff_request_revision,
            summarize=_summ("Requested a staff revision"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="staff_cancel_task",
            tool_id="staff",
            kind="write",
            description="Cancel a queued or running staff task. Manager or founder only.",
            parameters=_obj(
                {
                    "taskId": _str_param("Task id.", max_len=40),
                    "reason": _str_param("Why the task is cancelled.", max_len=400),
                },
                ["taskId", "reason"],
            ),
            run=_staff_cancel_task,
            summarize=_summ("Cancelled a staff task"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="task_note",
            tool_id="task",
            kind="write",
            description="Record progress on the current task and continue. Call this when you are not finished.",
            parameters=_obj(
                {
                    "text": _str_param("Progress note to append to the scratchpad.", max_len=4000),
                    "reason": REASON_PARAM,
                },
                ["text"],
            ),
            run=_task_note,
            summarize=_summ("Noted task progress"),
            contexts=("task",),
        ),
        ToolOp(
            name="task_finish",
            tool_id="task",
            kind="write",
            description="Finish the current task. Provide the deliverable and evidence call ids. Do not call this without evidence unless the brief needs none.",
            parameters=_obj(
                {
                    "summary": _str_param("One-paragraph summary of the result.", max_len=800),
                    "deliverableType": _str_param(
                        "Deliverable format.",
                        enum=list(BOARD_STAFF_DELIVERABLE_TYPES),
                    ),
                    "deliverable": _str_param("The deliverable body as text."),
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tool-call ids from this task that support the deliverable.",
                    },
                    "openQuestions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Questions you could not answer.",
                    },
                    "confidence": _str_param("How confident you are.", enum=["high", "medium", "low"]),
                    "reason": REASON_PARAM,
                },
                ["summary", "deliverableType", "deliverable", "confidence"],
            ),
            run=_task_finish,
            summarize=_summ("Finished the task"),
            contexts=("task",),
        ),
    ]
    return {op.name: op for op in ops}


REGISTRY: dict[str, ToolOp] = build_registry()


def public_registry() -> list[dict[str, Any]]:
    """Tool and operation descriptions for the SPA."""
    out = []
    for tool in BOARD_TOOL_DEFINITIONS:
        tool_id = str(tool["id"])
        out.append(
            {
                "id": tool_id,
                "label": tool.get("label"),
                "description": tool.get("description"),
                "maxLevel": tool.get("maxLevel"),
                "operations": [
                    {
                        "name": op.name,
                        "kind": op.kind,
                        "description": op.description,
                        "contexts": list(op.contexts),
                    }
                    for op in REGISTRY.values()
                    if op.tool_id == tool_id
                ],
            }
        )
    return out


def available_ops(
    settings: dict[str, Any],
    persona_id: str,
    *,
    context: str,
    seat_id: str = "",
    seats_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[tuple[ToolOp, str]]:
    """Operations this member may call now, each with its effective level."""
    out: list[tuple[ToolOp, str]] = []
    if not tools_enabled(settings):
        return out
    for op in REGISTRY.values():
        if context not in op.contexts:
            continue
        if op.tool_id == "task":
            level = "act" if context == "task" else "off"
        elif op.tool_id in ("staff", "intel", "outreach", "content", "newsletter", "code"):
            import board_staff

            if not board_staff.enabled(settings):
                continue
            if seat_id:
                level = effective_level(settings, op.tool_id, persona_id, seat_id=seat_id, seats_by_id=seats_by_id)
            else:
                level = effective_level(settings, op.tool_id, persona_id)
        elif seat_id:
            level = effective_level(settings, op.tool_id, persona_id, seat_id=seat_id, seats_by_id=seats_by_id)
        else:
            level = effective_level(settings, op.tool_id, persona_id)
        if allows(level, op.min_level):
            out.append((op, level))
    return out


def tools_preamble(ops: list[tuple[ToolOp, str]]) -> str:
    """System text explaining what the offered tools do and do not do."""
    if not ops:
        return ""
    lines = [
        "TOOLS: you can call the functions offered to you. Use read tools to check live facts "
        "before asserting them; cite what you found. Never call the same function twice with the "
        f"same arguments, and make at most {BOARD_MAX_TOOL_CALLS_PER_TURN} calls per reply.",
    ]
    proposes = sorted({TOOL_LABELS.get(op.tool_id, op.tool_id) for op, lvl in ops if op.is_write and lvl == "propose"})
    acts = sorted({TOOL_LABELS.get(op.tool_id, op.tool_id) for op, lvl in ops if op.is_write and lvl == "act"})
    if proposes:
        lines.append(
            f"Write operations on {', '.join(proposes)} only RECORD A PROPOSAL for the founder to approve; "
            "nothing happens until they approve it. Say 'I have proposed ...' and never claim it is done."
        )
    if acts:
        lines.append(
            f"Write operations on {', '.join(acts)} execute immediately and are logged. Use them only when "
            "the founder asked for it or your mandate clearly covers it; explain what you did."
        )
        lines.append(
            "A result status of 'held' means the write is scheduled and will happen automatically unless the "
            "founder vetoes it. Say 'I have scheduled …' and never claim it is already done."
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Execution and audit
# ---------------------------------------------------------------------------

def _truncate_json(value: Any, limit: int) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[: limit - 60].rstrip() + f" ... [truncated, {len(text)} chars total]"


def _clean_arguments(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    text = json.dumps(args, default=str)
    if len(text) > MAX_ARGUMENT_CHARS:
        raise InvalidArgumentsError(f"arguments too large (over {MAX_ARGUMENT_CHARS} characters)")
    return args


def _check_value(key: str, value: Any, spec: dict[str, Any]) -> tuple[Any, str]:
    """Return ``(normalised_value, problem)`` for one schema property."""
    kind = spec.get("type")
    if kind == "string":
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            value = str(value)
        if not isinstance(value, str):
            return None, f"'{key}' must be a string"
        max_len = spec.get("maxLength")
        if max_len and len(value) > int(max_len):
            return None, f"'{key}' is longer than {max_len} characters"
        enum = spec.get("enum")
        if enum and value not in enum:
            return None, f"'{key}' must be one of: {', '.join(str(e) for e in enum)}"
        return value, ""
    if kind in ("integer", "number"):
        if isinstance(value, bool):
            return None, f"'{key}' must be a number"
        if isinstance(value, str):
            try:
                value = int(value.strip()) if kind == "integer" else float(value.strip())
            except ValueError:
                return None, f"'{key}' must be a number"
        if isinstance(value, Decimal):
            value = int(value) if value == value.to_integral_value() else float(value)
        if not isinstance(value, (int, float)):
            return None, f"'{key}' must be a number"
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None, f"'{key}' must be a finite number"
        if kind == "integer" and isinstance(value, float):
            if not value.is_integer():
                return None, f"'{key}' must be a whole number"
            value = int(value)
        minimum = spec.get("minimum")
        if minimum is not None and value < minimum:
            return None, f"'{key}' must be at least {minimum}"
        maximum = spec.get("maximum")
        if maximum is not None and value > maximum:
            return None, f"'{key}' must be at most {maximum}"
        return value, ""
    if kind == "boolean":
        if isinstance(value, bool):
            return value, ""
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true", ""
        return None, f"'{key}' must be true or false"
    if kind == "array":
        if not isinstance(value, list):
            return None, f"'{key}' must be a list"
        max_items = spec.get("maxItems")
        if max_items and len(value) > int(max_items):
            return None, f"'{key}' has more than {max_items} items"
        item_spec = spec.get("items") if isinstance(spec.get("items"), dict) else {}
        cleaned: list[Any] = []
        for index, item in enumerate(value):
            if item_spec.get("type"):
                item, problem = _check_value(f"{key}[{index}]", item, item_spec)
                if problem:
                    return None, problem
            cleaned.append(item)
        return cleaned, ""
    if kind == "object":
        if not isinstance(value, dict):
            return None, f"'{key}' must be an object"
        nested, problems = _validate_against(value, spec, prefix=f"{key}.")
        return nested, problems[0] if problems else ""
    return value, ""


def _validate_against(args: dict[str, Any], schema: dict[str, Any], *, prefix: str = "") -> tuple[dict[str, Any], list[str]]:
    props: dict[str, Any] = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    problems: list[str] = []
    out: dict[str, Any] = {}
    for key in schema.get("required") or []:
        if args.get(key) in (None, "", [], {}):
            problems.append(f"'{prefix}{key}' is required")
    for key, value in args.items():
        spec = props.get(key)
        if spec is None:
            if schema.get("additionalProperties") is False:
                problems.append(f"unknown argument '{prefix}{key}'")
            else:
                out[key] = value
            continue
        if value is None:
            continue
        cleaned, problem = _check_value(f"{prefix}{key}", value, spec)
        if problem:
            problems.append(problem)
        else:
            out[key] = cleaned
    return out, problems


def validate_arguments(op: ToolOp, args: dict[str, Any]) -> dict[str, Any]:
    """Check ``args`` against the schema the model was shown and return a normalised copy.

    Numeric strings are coerced, ``null`` values dropped; unknown keys, wrong
    types, enum / length / range violations raise :class:`InvalidArgumentsError`
    so neither a persona nor an owner override can smuggle an undeclared or
    oversized value into an op.
    """
    cleaned, problems = _validate_against(args, op.parameters or {})
    if problems:
        raise InvalidArgumentsError("Invalid arguments: " + "; ".join(problems[:6]))
    return cleaned


_SENSITIVE_ARG_KEYS = frozenset({"to", "cc", "recipientId", "contact", "providerEmail", "providerPhone", "parentContact"})


def mask_arguments(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """Alias e-mail addresses and phone numbers inside ``arguments`` for the audit log.

    Tool-call rows are browsable in the SPA activity feed and are kept far longer
    than the approval they came from, so they never store raw contact details.
    Approvals keep the real arguments because they are executed from them and
    already carry the un-masked owner preview by design.
    """
    try:
        pseud = board_mail.pseudonymizer(ctx.table)
    except Exception:  # pragma: no cover - masking is best effort, never blocks a call
        return arguments

    def _walk(value: Any, key: str = "") -> Any:
        if isinstance(value, str):
            if key in _SENSITIVE_ARG_KEYS and "@" in value:
                return pseud.alias_for_address(value)
            return pseud.mask_text(value)
        if isinstance(value, list):
            return [_walk(v, key) for v in value]
        if isinstance(value, dict):
            return {k: _walk(v, str(k)) for k, v in value.items()}
        return value

    masked = _walk(arguments)
    try:
        pseud.save()
    except Exception as exc:  # pragma: no cover - alias map save is retried elsewhere
        _log_event("warning", tag="board_tool_mask_save_failed", error=str(exc)[:200])
    return masked


def _invoke_op(ctx: ToolContext, op: ToolOp, arguments: dict[str, Any]) -> dict[str, Any]:
    timeout = op.timeout_seconds if op.timeout_seconds is not None else BOARD_TOOL_CALL_TIMEOUT_SECONDS
    left = ctx.seconds_left()
    if left is not None and timeout > 0:
        # A slow op late in the turn may not overrun the loop's wall-clock budget.
        timeout = max(OP_TIMEOUT_FLOOR_SECONDS, min(timeout, int(math.ceil(left))))
    if timeout <= 0:
        result = op.run(ctx, arguments)
    else:
        token = board_deadline.set_deadline(timeout)
        # Not a ``with`` block: the context manager joins the worker on exit,
        # which would make the caller wait out the whole slow op anyway.
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"board-op-{op.name}")
        try:
            future = pool.submit(board_deadline.bind_context(op.run), ctx, arguments)
            try:
                result = future.result(timeout=timeout)
            except FuturesTimeout as exc:
                _log_event("warning", tag="board_tool_timeout", op=op.name, timeoutSeconds=timeout)
                raise TimeoutError(f"{op.name} timed out after {timeout}s") from exc
        finally:
            board_deadline.reset(token)
            pool.shutdown(wait=False, cancel_futures=True)
    return result if isinstance(result, dict) else {"result": result}


def execute_call(ctx: ToolContext, op: ToolOp, arguments: dict[str, Any]) -> ToolOutcome:
    """Run (or record for approval) one operation and write the audit row."""
    started = time.monotonic()
    raw = arguments if isinstance(arguments, dict) else {}
    invalid = ""
    try:
        arguments = validate_arguments(op, _clean_arguments(raw))
    except InvalidArgumentsError as exc:
        invalid = str(exc)
        # Keep the (bounded) raw arguments so the audit row shows what was asked.
        arguments = raw if len(json.dumps(raw, default=str)) <= MAX_ARGUMENT_CHARS else {}
    if ctx.actor == "persona":
        seats = None
        if ctx.seat_id:
            import board_staff

            seats = board_staff.seats_by_id(ctx.table, ctx.settings)
        level = effective_level(
            ctx.settings,
            op.tool_id,
            ctx.persona_id,
            seat_id=ctx.seat_id,
            seats_by_id=seats,
        )
    else:
        level = "act"
    summary = op.summarize(arguments)
    approval_id = ""
    guard_reason = ""
    if op.is_write and not invalid and level == "act" and ctx.actor == "persona" and op.act_guard is not None:
        try:
            guard_reason = str(op.act_guard(ctx, arguments) or "")
        except Exception as exc:  # pragma: no cover - a guard bug must fail closed
            _log_event("error", tag="board_tool_guard_crashed", op=op.name, error=str(exc)[:300])
            guard_reason = "the safety check could not be completed"
    breaker_error: dict[str, Any] | None = None
    if op.is_write and not invalid and ctx.actor == "persona":
        try:
            import board_staff as _staff
            import board_breakers

            if _staff.enabled(ctx.settings):
                breaker_error = board_breakers.write_blocked(ctx.table, op)
        except Exception as exc:
            _log_event("warning", tag="board_breaker_check_failed", op=op.name, error=str(exc)[:200])
            breaker_error = None
    hold_doc: dict[str, Any] | None = None
    if (
        op.is_write
        and not invalid
        and not breaker_error
        and level == "act"
        and not guard_reason
        and ctx.actor == "persona"
    ):
        try:
            import board_holds

            hold_doc = board_holds.maybe_hold(ctx, op, arguments, summary=summary)
        except Exception as exc:  # pragma: no cover - hold bugs must not block today's path
            _log_event("error", tag="board_hold_check_failed", op=op.name, error=str(exc)[:300])
            hold_doc = None
    if not allows(level, op.min_level):
        outcome = ToolOutcome(
            status="error",
            result={"error": f"{op.name} is not available to you at level '{level}'."},
            summary=summary,
        )
    elif invalid:
        # Never queue a malformed proposal: the model gets the schema problem back
        # and can retry with corrected arguments.
        outcome = ToolOutcome(status="error", result={"error": invalid[:500]}, summary=summary)
    elif breaker_error:
        outcome = ToolOutcome(status="error", result=breaker_error, summary=summary)
    elif hold_doc:
        execute_at = str(hold_doc.get("executeAt") or "")
        hold_id = str(hold_doc.get("holdId") or "")
        outcome = ToolOutcome(
            status="held",
            result={
                "status": "held",
                "holdId": hold_id,
                "executeAt": execute_at,
                "message": f"Scheduled; executes {execute_at} unless the founder vetoes.",
            },
            summary=f"Scheduled {summary} (executes {execute_at} unless vetoed)",
        )
    elif op.is_write and (level != "act" or guard_reason or (op.always_propose and ctx.actor == "persona")):
        approval = create_approval(ctx, op, arguments, summary=summary, downgrade_reason=guard_reason)
        approval_id = str(approval["approvalId"])
        message = (
            "Recorded as a proposal for the founder. It has NOT been executed; "
            "tell the founder it awaits their approval in the Approvals section."
        )
        if guard_reason:
            message = f"Not sent automatically because {guard_reason}. " + message
        outcome = ToolOutcome(
            status="pending_approval",
            result={"status": "pending_approval", "approvalId": approval_id, "message": message},
            summary=summary,
            approval_id=approval_id,
        )
    else:
        try:
            result = _invoke_op(ctx, op, arguments)
            status = "error" if result.get("error") and len(result) == 1 else "ok"
            outcome = ToolOutcome(status=status, result=result, summary=summary)
            if status == "ok":
                try:
                    import board_policy

                    if op.name in board_policy.REPLY_OPS:
                        board_policy.record_reply(ctx.table, op.name, arguments)
                except Exception:
                    pass
        except (
            board_github.GitHubSnapshotError,
            board_mail.MailError,
            board_research.ResearchError,
            board_aws.AwsToolError,
            board_security.SecurityToolError,
            board_receivables.ReceivablesError,
            board_product.ProductError,
            board_meta.MetaError,
            board_stores.StoresError,
            board_web.WebError,
            TimeoutError,
            ValueError,
        ) as exc:
            outcome = ToolOutcome(status="error", result={"error": str(exc)[:500]}, summary=summary)
        except Exception as exc:  # pragma: no cover - defensive: a tool bug must not kill the reply
            _log_event("error", tag="board_tool_crashed", op=op.name, error=str(exc)[:300])
            outcome = ToolOutcome(status="error", result={"error": f"Tool failed: {str(exc)[:200]}"}, summary=summary)
    outcome.duration_ms = int((time.monotonic() - started) * 1000)
    outcome.approval_id = approval_id or outcome.approval_id
    audit = mask_arguments(ctx, {"arguments": arguments, "summary": summary})
    record = board_store.add_tool_call(
        ctx.table,
        {
            "personaId": ctx.persona_id,
            "displayName": ctx.display_name,
            "actor": ctx.actor,
            "ownerSub": ctx.owner_sub if ctx.actor == "owner" else "",
            "toolId": op.tool_id,
            "op": op.name,
            "kind": op.kind,
            "level": level,
            "arguments": audit["arguments"],
            "status": outcome.status,
            "summary": audit["summary"],
            "resultPreview": _truncate_json(outcome.result, MAX_RESULT_PREVIEW),
            "approvalId": approval_id,
            "downgradeReason": guard_reason,
            "context": ctx.public(),
            "durationMs": outcome.duration_ms,
            "taskId": ctx.task_id,
            "seatId": ctx.seat_id,
        },
    )
    outcome.call_id = str(record["callId"])
    _log_event(
        "info",
        tag="board_tool_call",
        op=op.name,
        persona=ctx.persona_id,
        actor=ctx.actor,
        status=outcome.status,
        duration_ms=outcome.duration_ms,
    )
    return outcome


def render_preview(ctx: ToolContext, op: ToolOp, arguments: dict[str, Any]) -> dict[str, Any] | None:
    if op.preview is None:
        return None
    try:
        return op.preview(ctx, arguments)
    except Exception as exc:  # pragma: no cover - preview is best effort
        _log_event("warning", tag="board_tool_preview_failed", op=op.name, error=str(exc)[:300])
        return {"error": "Preview unavailable"}


def create_approval(
    ctx: ToolContext,
    op: ToolOp,
    arguments: dict[str, Any],
    *,
    summary: str,
    downgrade_reason: str = "",
) -> dict[str, Any]:
    pending = [a for a in board_store.list_approvals(ctx.table) if a.get("status") == "pending"]
    if len(pending) >= BOARD_MAX_PENDING_APPROVALS:
        raise ToolPermissionError("Too many pending approvals; ask the founder to review the queue first.")
    now = board_store.now_iso()
    preview = render_preview(ctx, op, arguments)
    doc = {
        "approvalId": board_store.new_id(),
        "status": "pending",
        "personaId": ctx.persona_id,
        "displayName": ctx.display_name,
        "toolId": op.tool_id,
        "toolLabel": TOOL_LABELS.get(op.tool_id, op.tool_id),
        "op": op.name,
        "kind": op.kind,
        "arguments": arguments,
        "summary": summary,
        "reason": str(arguments.get("reason") or "")[:400],
        "context": ctx.public(),
        "createdAt": now,
        "updatedAt": now,
    }
    if downgrade_reason:
        doc["downgradeReason"] = downgrade_reason[:300]
    if preview is not None:
        doc["preview"] = preview
    board_store.put_approval(ctx.table, doc)
    return doc


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

def run_tool_loop(
    *,
    ctx: ToolContext,
    messages: list[dict[str, Any]],
    model: str,
    timeout: int,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
    tag: str,
    max_seconds: int,
    on_progress: Callable[[list[dict[str, Any]]], None] | None = None,
) -> ToolLoopResult:
    """Call the model, execute any requested tools, repeat, then return the final text.

    Falls back to a single plain completion when the member has no tools.
    The final answer is always produced by a call where the model was not
    allowed to request more tools, so the loop terminates deterministically.
    """
    seats = None
    if ctx.seat_id:
        import board_staff

        seats = board_staff.seats_by_id(ctx.table, ctx.settings)
    ops = available_ops(
        ctx.settings,
        ctx.persona_id,
        context=ctx.kind,
        seat_id=ctx.seat_id,
        seats_by_id=seats,
    )
    if not ops:
        completion = board_budget.board_completion(
            table=ctx.table,
            messages=messages,
            model=model,
            timeout=timeout,
            json_mode=json_mode,
            temperature=temperature,
            max_tokens=max_tokens,
            tag=tag,
            usage_sink=ctx.usage_sink,
        )
        return ToolLoopResult(text=completion.text, usage=completion.usage, model=completion.model, rounds=1, completion=completion)

    by_name = {op.name: op for op, _lvl in ops}
    schemas = [op.schema() for op, _lvl in ops]
    convo: list[dict[str, Any]] = [*messages]
    preamble = tools_preamble(ops)
    if preamble:
        # After the persona prompt and context pack, before the conversation.
        index = 0
        while index < len(convo) and convo[index].get("role") == "system":
            index += 1
        convo.insert(index, {"role": "system", "content": preamble})

    usage = add_usage(None, None)
    calls: list[dict[str, Any]] = []
    started = time.monotonic()
    ctx.deadline = started + max_seconds
    rounds = 0
    final: ChatCompletion | None = None
    stop_reason = ""
    while rounds < BOARD_MAX_TOOL_ROUNDS_PER_TURN:
        left = max_seconds - (time.monotonic() - started)
        calls_left = BOARD_MAX_TOOL_CALLS_PER_TURN - len(calls)
        if left <= 0 or calls_left <= 0:
            break
        if rounds:
            # The caller checked the daily cap before the turn; every further
            # round is another paid call, so re-check between rounds.
            try:
                board_budget.check_budget(ctx.table, ctx.settings)
            except board_budget.BudgetExceeded as exc:
                stop_reason = str(exc)
                _log_event("warning", tag="board_tool_loop_budget_stop", persona=ctx.persona_id, rounds=rounds)
                break
        rounds += 1
        completion = board_budget.board_completion(
            table=ctx.table,
            messages=convo,
            model=model,
            timeout=max(MODEL_CALL_TIMEOUT_FLOOR_SECONDS, min(timeout, int(left))),
            json_mode=False,
            temperature=temperature,
            max_tokens=max_tokens,
            tag=tag,
            tools=schemas,
            tool_choice="auto",
            usage_sink=ctx.usage_sink,
        )
        usage = add_usage(usage, completion.usage)
        if not completion.tool_calls:
            final = completion
            break
        convo.append(completion.assistant_message())
        for index, tc in enumerate(completion.tool_calls):
            if index >= calls_left:
                convo.append(_tool_message(tc, {"error": "Call budget for this reply is exhausted; answer with what you have."}))
            elif time.monotonic() >= ctx.deadline:
                convo.append(_tool_message(tc, {"error": "Time budget for this reply is exhausted; answer with what you have."}))
            else:
                convo.append(_run_one(ctx, by_name, tc, calls))
        if on_progress:
            try:
                on_progress(list(calls))
            except Exception:  # pragma: no cover - progress is best effort
                pass

    if final is None:
        if stop_reason:
            convo.append({"role": "system", "content": f"No more tool calls are possible: {stop_reason} Answer with what you have."})
        rounds += 1
        # The answer call may run past the loop budget, but only up to the
        # OpenRouter timeout; the sums in the module header rely on that.
        left = max_seconds - (time.monotonic() - started)
        final = board_budget.board_completion(
            table=ctx.table,
            messages=convo,
            model=model,
            timeout=max(FINAL_CALL_TIMEOUT_FLOOR_SECONDS, min(timeout, int(left))),
            json_mode=json_mode,
            temperature=temperature,
            max_tokens=max_tokens,
            tag=tag,
            tools=schemas,
            tool_choice="none",
            usage_sink=ctx.usage_sink,
        )
        usage = add_usage(usage, final.usage)
    return ToolLoopResult(text=final.text, usage=usage, model=final.model, calls=calls, rounds=rounds, completion=final)


def _run_one(
    ctx: ToolContext,
    by_name: dict[str, ToolOp],
    tc: ToolCall,
    calls: list[dict[str, Any]],
) -> dict[str, Any]:
    op = by_name.get(tc.name)
    if op is None:
        return _tool_message(tc, {"error": f"Unknown tool {tc.name}"})
    try:
        outcome = execute_call(ctx, op, tc.arguments)
    except ToolPermissionError as exc:
        return _tool_message(tc, {"error": str(exc)})
    calls.append(outcome.public(op))
    return _tool_message(tc, outcome.result)


def _tool_message(tc: ToolCall, result: Any) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": tc.id,
        "name": tc.name,
        "content": _truncate_json(result, BOARD_TOOL_RESULT_MAX_CHARS),
    }


# ---------------------------------------------------------------------------
# Owner decisions on approvals
# ---------------------------------------------------------------------------

def decide_approval(
    table: Any,
    settings: dict[str, Any],
    approval_id: str,
    *,
    approve: bool,
    owner_sub: str,
    note: str = "",
    arguments_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Approve (execute as the owner) or reject a pending proposal."""
    doc = board_store.get_approval(table, approval_id)
    if not doc:
        raise LookupError("Approval not found")
    if doc.get("status") != "pending":
        raise ValueError(f"Approval is already {doc.get('status')}")
    op = REGISTRY.get(str(doc.get("op") or ""))
    arguments = dict(doc.get("arguments") or {})
    if approve:
        # Everything that can be checked up front happens before the claim so a
        # refused decision leaves the approval pending instead of half-decided.
        if not tools_enabled(settings):
            raise ValueError("Board tools are switched off; enable them before approving proposals.")
        if global_cap(settings) == "read":
            raise ValueError("The board is in read-only mode; switch it to propose or act before approving proposals.")
        if isinstance(arguments_override, dict):
            arguments.update(arguments_override)
        if op is not None:
            arguments = validate_arguments(op, _clean_arguments(arguments))
    next_status = "approved" if approve else "rejected"
    if not board_store.claim_approval_decision(table, approval_id, status=next_status):
        raise ValueError("Approval was decided by someone else a moment ago")
    now = board_store.now_iso()
    decided = {
        **doc,
        "status": next_status,
        "decidedAt": now,
        "decidedBySub": owner_sub,
        "note": note[:1000],
        "updatedAt": now,
    }
    if not approve:
        board_store.put_approval(table, decided)
        return decided

    if op is None:
        decided.update({"status": "failed", "errorMessage": "This operation no longer exists."})
        board_store.put_approval(table, decided)
        return decided
    profile = board_personas.persona_default(str(doc.get("personaId") or "")) or {}
    ctx = ToolContext(
        table=table,
        settings=settings,
        persona_id=str(doc.get("personaId") or ""),
        display_name=str(doc.get("displayName") or profile.get("shortName") or ""),
        kind=str((doc.get("context") or {}).get("kind") or "approval"),
        meeting_id=str((doc.get("context") or {}).get("meetingId") or ""),
        actor="owner",
        owner_sub=owner_sub,
    )
    if isinstance(arguments_override, dict) and arguments_override:
        refreshed = render_preview(ctx, op, arguments)
        if refreshed is not None:
            decided["preview"] = refreshed
    decided["arguments"] = arguments
    try:
        outcome = execute_call(ctx, op, arguments)
    except Exception as exc:  # pragma: no cover - the claim is taken; never leave it "approved" forever
        _log_event("error", tag="board_approval_execute_crashed", op=op.name, error=str(exc)[:300])
        decided.update({"status": "failed", "errorMessage": f"Execution failed: {str(exc)[:400]}"})
        board_store.put_approval(table, decided)
        return decided
    decided["executedCallId"] = outcome.call_id
    if outcome.status == "ok":
        decided.update({"status": "executed", "result": outcome.result})
    else:
        decided.update({"status": "failed", "errorMessage": str(outcome.result.get("error") or "Execution failed")[:500]})
    board_store.put_approval(table, decided)
    return decided


def public_approval(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in ("decidedBySub",)}
