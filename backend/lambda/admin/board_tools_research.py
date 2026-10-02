"""Tool operations for the research family."""

from __future__ import annotations

import board_research
from board_tools_core import (
    ToolOp,
    _int_param,
    _obj,
    _str_param,
    _summ,
)
from contract_constants import (
    BOARD_RESEARCH_QUERY_MAX_LEN,
)


def ops() -> list[ToolOp]:
    return [
        ToolOp(
            name="research_search",
            tool_id="research",
            kind="read",
            description="Search the public web (cached 24h). Use for competitor pages, market facts, or anything not in GitHub or company mail.",
            parameters=_obj(
                {
                    "query": _str_param("Search query.", max_len=BOARD_RESEARCH_QUERY_MAX_LEN),
                    "limit": _int_param("Max results (1-8).", maximum=8),
                },
                ["query"],
            ),
            run=board_research.op_search,
            summarize=_summ("Searched the web for '{query}'"),
        ),
        ToolOp(
            name="research_hk_news",
            tool_id="research",
            kind="read",
            description="Hong Kong market / education news (gov.hk, SCMP, The Standard), cached 24h.",
            parameters=_obj(
                {
                    "query": _str_param("Topic, e.g. 'after-school activities regulation'.", max_len=BOARD_RESEARCH_QUERY_MAX_LEN),
                    "limit": _int_param("Max results (1-8).", maximum=8),
                }
            ),
            run=board_research.op_hk_news,
            summarize=_summ("Looked up HK news on '{query}'"),
        ),
        ToolOp(
            name="research_edb_holidays",
            tool_id="research",
            kind="read",
            description="Education Bureau school-holiday calendar for Hong Kong (cached 24h).",
            parameters=_obj({"year": _str_param("Calendar year, e.g. 2026.", max_len=12)}),
            run=board_research.op_edb_holidays,
            summarize=_summ("Looked up EDB holidays"),
        ),
        ToolOp(
            name="research_venues",
            tool_id="research",
            kind="read",
            description="Public listings of children's activity venues in a Hong Kong district (cached 24h).",
            parameters=_obj(
                {
                    "district": _str_param("Hong Kong district, e.g. 'tuen mun' or 'kwun tong'.", max_len=40),
                    "kind": _str_param("Venue type, e.g. 'swimming' or 'coding class'.", max_len=80),
                    "limit": _int_param("Max results (1-8).", maximum=8),
                }
            ),
            run=board_research.op_venues,
            summarize=_summ("Looked up venues in {district}"),
        ),
        ToolOp(
            name="research_fetch_page",
            tool_id="research",
            kind="read",
            description=(
                "Fetch a public http(s) page as text. Refuses private/link-local hosts. "
                "At most 6 fetches per task (9 on catalog-micro-batch / catalog-enrich). "
                "Prefer official LCSD or provider pages."
            ),
            parameters=_obj({"url": _str_param("https URL to fetch.", max_len=500)}, ["url"]),
            run=board_research.op_fetch_page,
            summarize=_summ("Fetched {url}"),
        ),
    ]
