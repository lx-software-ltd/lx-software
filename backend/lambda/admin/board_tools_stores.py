"""Tool operations for the stores family."""

from __future__ import annotations

import board_stores
from board_tools_core import (
    REASON_PARAM,
    ToolOp,
    _int_param,
    _obj,
    _reply_guard,
    _str_param,
    _summ,
)
from contract_constants import (
    BOARD_STORES_LIST_MAX,
)


def ops() -> list[ToolOp]:
    return [
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
    ]
