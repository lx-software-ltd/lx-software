"""Tool operations for the newsletter family."""

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
    BOARD_STAFF_NEWSLETTER_LISTS,
)


def _newsletter_draft_issue(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_newsletter

    return board_newsletter.op_draft_issue(ctx, args)

def _newsletter_send(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_newsletter

    return board_newsletter.op_send(ctx, args)

def ops() -> list[ToolOp]:
    return [
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
    ]
