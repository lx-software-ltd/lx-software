"""Tool operations for the web family."""

from __future__ import annotations

import board_web
from board_tools_core import (
    ToolOp,
    _int_param,
    _obj,
    _str_param,
    _summ,
)
from contract_constants import (
    BOARD_WEB_LIST_MAX,
)


def ops() -> list[ToolOp]:
    return [
        ToolOp(
            name="web_sessions",
            tool_id="web",
            kind="read",
            description="GA4 sessions, users, top pages and referrers (sessionSource / sessionMedium) for the last 7 days (cached). This is the book of record for visitor sources; do not ask for GA4 console access. Zero sessions is a valid connected result. Optional propertyId when several properties are configured.",
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
            description="GA4 event counts and key events for the last 7 days (cached). This is the book of record for event tracking; do not ask for GA4 console access.",
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
            description="GTM container name, public id and live version (cached). This is the book of record for tag-manager setup; do not ask for GA4 or GTM console access. Publish is a later milestone.",
            parameters=_obj(
                {"containerId": _str_param("GTM container id. Omit to read every configured container.", max_len=32)}
            ),
            run=board_web.op_gtm_status,
            summarize=_summ("Read GTM status"),
        ),
    ]
