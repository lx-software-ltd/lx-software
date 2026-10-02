"""Tool operations for the task family."""

from __future__ import annotations

from typing import Any

from board_tools_core import (
    REASON_PARAM,
    ToolContext,
    ToolOp,
    _obj,
    _str_param,
    _summ,
)
from contract_constants import (
    BOARD_STAFF_DELIVERABLE_TYPES,
)


def _task_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_staff

    return board_staff.op_task_note(ctx, args)

def _task_finish(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_staff

    return board_staff.op_task_finish(ctx, args)

def _task_request_help(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_staff

    return board_staff.op_task_request_help(ctx, args)

def _task_request_help_guard(ctx: ToolContext, args: dict[str, Any]) -> str | None:
    import board_staff

    return board_staff.act_guard_task_request_help(ctx, args)

def _validate_task_request_help(ctx: ToolContext, args: dict[str, Any]) -> str | None:
    import board_staff

    return board_staff.validate_task_request_help(ctx, args)

def _preview_task_request_help(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any] | None:
    import board_staff

    return board_staff.preview_task_request_help(ctx, args)

def _summ_request_help(args: dict[str, Any]) -> str:
    import board_staff

    return board_staff.summarize_help_request(args=args)

def ops() -> list[ToolOp]:
    return [
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
            description="Finish the current task. Provide the deliverable and evidence call ids from read or write tools — task_note ids are not evidence. If no offered function can verify more, finish anyway with confidence low and openQuestions.",
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
                        "description": "Tool-call ids from this task that support the deliverable. Do not pass task_note call ids.",
                    },
                    "openQuestions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Questions you could not answer.",
                    },
                    "confidence": _str_param("How confident you are.", enum=["high", "medium", "low"]),
                    "status": _str_param(
                        "Use blocked when a breaker or runner guard stops the work.",
                        enum=["ok", "blocked"],
                    ),
                    "blockedReason": _str_param(
                        "Why the work cannot proceed. Required with status=blocked.",
                        max_len=300,
                    ),
                    "reason": REASON_PARAM,
                },
                ["summary", "deliverableType", "deliverable", "confidence"],
            ),
            run=_task_finish,
            summarize=_summ("Finished the task"),
            contexts=("task",),
        ),
        ToolOp(
            name="task_request_help",
            tool_id="task",
            kind="write",
            description=(
                "Ask another active seat that has tools you were not offered to gather that "
                "information. Use tool ids such as web or finance, not operation names. "
                "The founder must usually approve. Do not call this when you already have "
                "the tools, and do not call it from a help task."
            ),
            parameters=_obj(
                {
                    "need": _str_param("What information to obtain, specifically.", max_len=2000),
                    "toolIds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Board tool ids you need (web, finance, aws), not operation names.",
                    },
                    "suggestedAssignee": _str_param(
                        "Optional active seat id you believe has those tools.",
                        max_len=40,
                    ),
                    "reason": REASON_PARAM,
                },
                ["need", "toolIds"],
            ),
            run=_task_request_help,
            summarize=_summ_request_help,
            act_guard=_task_request_help_guard,
            validate=_validate_task_request_help,
            preview=_preview_task_request_help,
            contexts=("task",),
        ),
    ]
