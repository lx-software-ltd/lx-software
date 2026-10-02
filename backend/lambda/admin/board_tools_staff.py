"""Tool operations for the staff family."""

from __future__ import annotations

from typing import Any

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
    BOARD_STAFF_DELIVERABLE_TYPES,
)


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

def _summ_staff_assign(args: dict[str, Any]) -> str:
    return f"Assigned {args.get('assignee')}: {_short(args.get('brief') or '', 80)}"

def ops() -> list[ToolOp]:
    return [
        ToolOp(
            name="staff_assign",
            tool_id="staff",
            kind="write",
            description="Assign a background task to a board member or an active staff seat. The assignee works in steps and produces a deliverable for review. GA4 / visitor-source / event-tracking / GTM briefs go to data-analyst (or business-analyst if that seat is inactive), not community-manager.",
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
            description="Cancel a queued, running, waiting, or failed staff task. Manager or founder only. Delivered tasks cannot be cancelled.",
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
    ]
