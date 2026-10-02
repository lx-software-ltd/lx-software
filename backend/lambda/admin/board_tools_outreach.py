"""Tool operations for the outreach family."""

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
from contract_constants import (
    BOARD_STAFF_PROSPECT_TYPES,
)


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

def _outreach_personalisation_guard(_ctx: ToolContext, args: dict[str, Any]) -> str | None:
    import board_policy

    text = str(args.get("personalisation") or "")
    if board_policy.PROMISE_RE.search(text):
        return "the draft promises a refund, a guarantee, or to hold a place"
    return None

def _outreach_suppress(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_outreach

    return board_outreach.op_suppress(ctx, args)

def ops() -> list[ToolOp]:
    return [
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
            act_guard=_outreach_personalisation_guard,
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
    ]
