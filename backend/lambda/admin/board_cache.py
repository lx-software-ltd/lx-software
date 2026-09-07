"""Hourly cache refresh for cheap, cacheable board reads (plan §7 / §8).

EventBridge Scheduler invokes AdminApiFn with ``{internal: "board_cache_refresh"}``.
Research queries are cached on first use (24 h) and are not pre-warmed — they
depend on the question. AWS cost/alarms/health, security findings, and
stores daily metrics, GA4 / GTM reads and the unfiltered product views are.
"""

from __future__ import annotations

from typing import Any

import board_aws
import board_product
import board_security
import board_store
import board_stores
import board_web
from http_common import _log_event


def refresh_all(table: Any) -> dict[str, Any]:
    aws_notes = board_aws.refresh_caches(table)
    sec_notes = board_security.refresh_caches(table)
    store_notes = board_stores.refresh_caches(table)
    web_notes = board_web.refresh_caches(table)
    product_notes = board_product.refresh_caches(table)
    return {"aws": aws_notes, "security": sec_notes, "stores": store_notes, "web": web_notes, "product": product_notes}


def handle_schedule_trigger(event: dict[str, Any]) -> dict[str, Any]:
    if not board_store.event_targets_this_board(event):
        return {"ok": True, "skipped": "other_board"}
    table = board_store.records_table()
    try:
        result = refresh_all(table)
    except Exception as exc:  # pragma: no cover - defensive: a refresh bug must not retry forever
        _log_event("error", tag="board_cache_refresh_failed", error=str(exc)[:300])
        return {"ok": False, "error": str(exc)[:300]}
    _log_event(
        "info",
        tag="board_cache_refreshed",
        aws=result.get("aws"),
        security=result.get("security"),
        stores=result.get("stores"),
        web=result.get("web"),
        product=result.get("product"),
    )
    return {"ok": True, **result}
