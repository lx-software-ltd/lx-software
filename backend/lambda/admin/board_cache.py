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
    """Refresh every cheap cache. One subsystem failure must not skip the rest.

    Production Health ``describe_events`` used to raise ``ParamValidationError``
    (``maxResults`` in the filter) and abort before GA4 / GTM ever ran.
    """
    result: dict[str, Any] = {}
    jobs = (
        ("aws", board_aws.refresh_caches),
        ("security", board_security.refresh_caches),
        ("stores", board_stores.refresh_caches),
        ("web", board_web.refresh_caches),
        ("product", board_product.refresh_caches),
    )
    for name, fn in jobs:
        try:
            result[name] = fn(table)
        except Exception as exc:
            _log_event("error", tag="board_cache_refresh_failed", key=name, error=str(exc)[:300])
            result[name] = {"error": str(exc)[:200]}
    try:
        import board_duties
        import board_staff

        settings = board_store.load_settings(table)
        if board_staff.enabled(settings):
            result["opsTriage"] = board_duties.triage_ops_signals(table, settings)
    except Exception as exc:
        _log_event("warning", tag="board_ops_triage_failed", error=str(exc)[:200])
    return result


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
