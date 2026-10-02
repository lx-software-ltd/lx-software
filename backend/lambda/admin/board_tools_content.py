"""Tool operations for the content family."""

from __future__ import annotations

from typing import Any

from board_tools_core import (
    REASON_PARAM,
    ToolContext,
    ToolOp,
    _int_param,
    _obj,
    _str_param,
    _summ,
)


def _content_list(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_content

    return board_content.op_list(ctx, args)

def _content_stage_items(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_content

    return board_content.op_stage_items(ctx, args)

def _content_get(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_content

    return board_content.op_get(ctx, args)

def _content_publish(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_content

    return board_content.op_publish(ctx, args)

def _validate_content_publish(ctx: ToolContext, args: dict[str, Any]) -> str | None:
    import board_content

    return board_content.validate_publish(ctx.table, args)

def ops() -> list[ToolOp]:
    return [
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
            name="content_stage_items",
            tool_id="content",
            kind="read",
            description=(
                "Save up to 6 content-calendar items on this task. Call it once per batch "
                "(facebook, then instagram, then stories) instead of putting the whole week "
                "in task_finish. Items with the same slotAt and channel replace earlier ones. "
                "task_finish merges staged items into the deliverable."
            ),
            parameters=_obj(
                {
                    "items": {
                        "type": "array",
                        "maxItems": 6,
                        "description": "Calendar items for this batch.",
                        "items": _obj(
                            {
                                "slotAt": _str_param("ISO slot time.", max_len=40),
                                "channel": _str_param("facebook, instagram, instagram_story, or seo.", max_len=40),
                                "pillar": _str_param("Content pillar.", max_len=80),
                                "copyEn": _str_param("English caption.", max_len=400),
                                "copyZh": _str_param("Traditional Chinese caption.", max_len=400),
                                "hashtags": _str_param("Hashtags.", max_len=200),
                                "template": _str_param("Card template.", max_len=40),
                                "fields": {
                                    "type": "object",
                                    "description": "Template fields such as title, body, and titleZh.",
                                    "additionalProperties": True,
                                },
                                "linkPath": _str_param("Site path.", max_len=120),
                            },
                            ["slotAt", "channel"],
                        ),
                    }
                },
                ["items"],
            ),
            run=_content_stage_items,
            summarize=_summ("Staged calendar items"),
            contexts=("task",),
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
            validate=_validate_content_publish,
        ),
    ]
