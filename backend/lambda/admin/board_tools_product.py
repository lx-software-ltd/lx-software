"""Tool operations for the product family."""

from __future__ import annotations

import board_product
from board_tools_core import (
    REASON_PARAM,
    ToolOp,
    _obj,
    _str_param,
    _summ,
)


def ops() -> list[ToolOp]:
    return [
        ToolOp(
            name="product_catalog_health",
            tool_id="product",
            kind="read",
            description="Catalog counts by district/category with completeness (photos, price, schedule, geocode).",
            parameters=_obj(
                {
                    "district": _str_param("Optional Hong Kong district.", max_len=40),
                    "category": _str_param("Optional activity category.", max_len=40),
                }
            ),
            run=board_product.op_catalog_health,
            summarize=_summ("Read catalog health"),
        ),
        ToolOp(
            name="product_funnel",
            tool_id="product",
            kind="read",
            description="Daily searches, listing views, CTA taps, leads and bookings from v_funnel_daily.",
            parameters=_obj(
                {
                    "from": _str_param("Start date YYYY-MM-DD.", max_len=10),
                    "to": _str_param("End date YYYY-MM-DD.", max_len=10),
                    "district": _str_param("Optional district.", max_len=40),
                }
            ),
            run=board_product.op_funnel,
            summarize=_summ("Read product funnel"),
        ),
        ToolOp(
            name="product_provider_pipeline",
            tool_id="product",
            kind="read",
            description="Provider sign-ups, onboarding step, days since last edit, subscription status.",
            parameters=_obj({"status": _str_param("Optional subscription status.", enum=["trial", "active", "past_due", "cancelled"])}),
            run=board_product.op_provider_pipeline,
            summarize=_summ("Read provider pipeline"),
        ),
        ToolOp(
            name="product_flag_listing",
            tool_id="product",
            kind="write",
            description="Flag a listing for the founder to review. Does not change the catalog.",
            parameters=_obj(
                {
                    "listingId": _str_param("Listing or activity id.", max_len=64),
                    "reason": REASON_PARAM,
                },
                ["listingId", "reason"],
            ),
            run=board_product.op_flag_listing,
            summarize=_summ("Flag listing {listingId}"),
        ),
    ]
