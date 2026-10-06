"""Tool types, access levels, and schema helpers shared by tool families.

Families import this module. This module does not import the tool registry.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import board_store
from contract_constants import BOARD_TOOL_DEFINITIONS, BOARD_TOOL_LEVELS
from openrouter_client import ChatCompletion

LEVEL_RANK: dict[str, int] = {lvl: i for i, lvl in enumerate(BOARD_TOOL_LEVELS)}

GLOBAL_MODE_CAP: dict[str, str] = {"readOnly": "read", "propose": "propose", "act": "act"}

TOOL_LABELS: dict[str, str] = {str(t["id"]): str(t["label"]) for t in BOARD_TOOL_DEFINITIONS}

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
    # Sweep-created holds skip the persona matrix (still re-check tools / guards).
    internal: bool = False
    # OpenRouter / model ``tool_call_id`` for this invocation (staff evidence alias).
    llm_tool_call_id: str = ""
    usage_sink: Callable[[dict[str, Any]], None] | None = None
    # ``time.monotonic()`` value after which no new op should start and running
    # ops are cut short; 0 means "no loop deadline" (owner approvals, jobs).
    deadline: float = 0.0
    # Cached staff-task attempt metadata so each op does not re-read the row.
    task_attempt: int | None = None
    task_retried_at: str = ""

    def bind_task_meta(self) -> None:
        if not self.task_id or self.task_attempt is not None:
            return
        try:
            row = board_store.get_task(self.table, self.task_id)
        except Exception:
            return
        if row is None:
            return
        try:
            self.task_attempt = int(row.get("attempt") or 1)
        except (TypeError, ValueError):
            self.task_attempt = 1
        self.task_retried_at = str(row.get("retriedAt") or "")

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
    # Staff steps use kind="task". Default includes it so seat tools
    # (github, mail, finance, AWS, Meta, …) are offered; only task_note /
    # task_finish stay task-exclusive.
    contexts: tuple[str, ...] = ("chat", "meeting", "task")
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
    action_class: str | None = None
    # Return a reason string to refuse a propose/act before it is queued.
    validate: Callable[["ToolContext", dict[str, Any]], str | None] | None = None

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
    blocks_task: bool = True

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
        if not self.blocks_task:
            out["blocksTask"] = False
        if self.status == "held":
            out["holdId"] = str(self.result.get("holdId") or "")
            out["executeAt"] = str(self.result.get("executeAt") or "")
        if self.status in ("error", "refused"):
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
    # The loop stopped early because a further model call would not fit the
    # remaining budget; the caller continues in a fresh step instead.
    yielded: bool = False

def env_disabled() -> bool:
    """Deploy-time kill switch: ``BOARD_TOOLS_ENABLED=false`` on the Lambda."""
    from config import env_flag

    return not env_flag("BOARD_TOOLS_ENABLED", default=True)

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
        import board_tools

        op = board_tools.REGISTRY.get(op_name)
        if op is None:
            return None
        return board_policy.check_reply(ctx.settings, ctx, op, args, thread)

    return _guard
