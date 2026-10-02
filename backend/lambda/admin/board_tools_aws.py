"""Tool operations for the aws family."""

from __future__ import annotations

import board_aws
from board_tools_core import (
    REASON_PARAM,
    ToolOp,
    _obj,
    _summ,
)


def ops() -> list[ToolOp]:
    return [
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
    ]
