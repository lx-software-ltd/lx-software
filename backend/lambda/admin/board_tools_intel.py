"""Tool operations for the intel family."""

from __future__ import annotations

from typing import Any

from board_tools_core import (
    ToolContext,
    ToolOp,
    _int_param,
    _obj,
    _str_param,
    _summ,
)
from contract_constants import (
    BOARD_RESEARCH_QUERY_MAX_LEN,
)


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

def ops() -> list[ToolOp]:
    return [
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
    ]
