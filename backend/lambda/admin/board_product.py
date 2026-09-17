"""Executive Board ``product`` tools: read-only siutindei SQL views (§5.7).

Parameters are limited to date ranges and district/category filters. The
only write is ``product_flag_listing``, which records an action item for
the founder (no catalog mutation from this stack).

Unfiltered view reads are cached (``product:*``, §7) so a board of eight
members asking the same question in one meeting costs one Aurora round trip;
filtered reads always go to the database.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import board_data_api
import board_store
from board_data_api import Date
from contract_constants import BOARD_CACHE_REFRESH_TTL_HOURS
from http_common import _utc_iso_z

CATALOG_CACHE = "product:catalog_health"
FUNNEL_CACHE = "product:funnel"
PIPELINE_CACHE = "product:provider_pipeline"


class ProductError(RuntimeError):
    """User-facing product-analytics failure."""


def _iso_date(raw: Any, label: str) -> str:
    text = str(raw or "").strip()[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ProductError(f"{label} must be a date YYYY-MM-DD") from exc


def _q(sql: str, **kwargs: Any) -> list[dict[str, Any]]:
    try:
        return board_data_api.execute(sql, board_data_api.params(**kwargs) if kwargs else None)
    except board_data_api.DataApiError as exc:
        raise ProductError(str(exc)) from exc


def _cached_rows(table: Any, name: str, fetcher: Any) -> dict[str, Any]:
    """Serve the unfiltered view from the ``product:*`` cache, filling it on a miss."""
    if table is None:
        return {"rows": fetcher(), "cached": False}
    hit = board_store.get_cache(table, name)
    payload = hit.get("payload") if isinstance(hit, dict) else None
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return {**payload, "cached": True, "fetchedAt": hit.get("fetchedAt")}
    rows = fetcher()
    doc = board_store.put_cache(table, name, {"rows": rows}, ttl_seconds=BOARD_CACHE_REFRESH_TTL_HOURS * 3600)
    return {"rows": rows, "cached": False, "fetchedAt": doc.get("fetchedAt")}


def refresh_caches(table: Any) -> dict[str, str]:
    """Hourly refresh of the unfiltered product views (skipped when the Data API is not configured)."""
    if not (board_data_api.configured() or board_data_api._executor is not None):
        return {CATALOG_CACHE: "skipped"}
    notes: dict[str, str] = {}
    for name, fetcher in (
        (CATALOG_CACHE, lambda: _q(_CATALOG_SQL + " ORDER BY activities DESC LIMIT 50")),
        (FUNNEL_CACHE, lambda: _q(_FUNNEL_SQL + " ORDER BY day DESC LIMIT 60")),
        (PIPELINE_CACHE, lambda: _q(_PIPELINE_SQL + " ORDER BY days_since_last_edit DESC LIMIT 50")),
    ):
        try:
            board_store.put_cache(table, name, {"rows": fetcher()}, ttl_seconds=BOARD_CACHE_REFRESH_TTL_HOURS * 3600)
            notes[name] = "ok"
        except ProductError as exc:
            notes[name] = str(exc)[:200]
    return notes


_CATALOG_SQL = (
    "SELECT district, category, activities, providers, stores, completeness, "
    "has_photo, has_price, has_schedule, has_geo FROM v_catalog_health"
)
_FUNNEL_SQL = (
    "SELECT day, district, searches, listing_views, cta_taps, leads_relayed, bookings_confirmed "
    "FROM v_funnel_daily"
)
_PIPELINE_SQL = (
    "SELECT organization_id, organization_name, signed_up_on, onboarding_step, "
    "days_since_last_edit, subscription_status FROM v_provider_pipeline"
)


def op_catalog_health(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    district = str(args.get("district") or "").strip()
    category = str(args.get("category") or "").strip()
    sql = _CATALOG_SQL
    if not district and not category:
        return _cached_rows(getattr(ctx, "table", None), CATALOG_CACHE, lambda: _q(sql + " ORDER BY activities DESC LIMIT 50"))
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if district:
        clauses.append("district = :district")
        params["district"] = district
    if category:
        clauses.append("category = :category")
        params["category"] = category
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY activities DESC LIMIT 50"
    return {"rows": _q(sql, **params)}


def op_funnel(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    start = str(args.get("from") or "").strip()
    end = str(args.get("to") or "").strip()
    district = str(args.get("district") or "").strip()
    sql = _FUNNEL_SQL
    if not start and not end and not district:
        return _cached_rows(getattr(ctx, "table", None), FUNNEL_CACHE, lambda: _q(sql + " ORDER BY day DESC LIMIT 60"))
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if start:
        clauses.append("day >= :dfrom")
        params["dfrom"] = Date(_iso_date(start, "from"))
    if end:
        clauses.append("day <= :dto")
        params["dto"] = Date(_iso_date(end, "to"))
    if district:
        clauses.append("district = :district")
        params["district"] = district
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY day DESC LIMIT 60"
    return {"rows": _q(sql, **params)}


def op_provider_pipeline(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    status = str(args.get("status") or "").strip()
    sql = _PIPELINE_SQL
    if status:
        rows = _q(sql + " WHERE subscription_status = :status ORDER BY days_since_last_edit DESC LIMIT 50", status=status)
        return {"providers": rows, "count": len(rows)}
    hit = _cached_rows(getattr(ctx, "table", None), PIPELINE_CACHE, lambda: _q(sql + " ORDER BY days_since_last_edit DESC LIMIT 50"))
    rows = hit["rows"]
    return {"providers": rows, "count": len(rows), "cached": hit.get("cached", False), "fetchedAt": hit.get("fetchedAt")}


def op_flag_listing(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    listing_id = str(args.get("listingId") or "").strip()
    reason = str(args.get("reason") or "").strip()
    if not listing_id:
        raise ProductError("listingId is required")
    now = _utc_iso_z(datetime.now(timezone.utc))
    title = f"Review listing {listing_id}"
    doc = {
        "actionId": board_store.new_id(),
        "title": title[:200],
        "detail": reason[:800],
        "persona": ctx.persona_id or "cpo",
        "priority": "next",
        "effort": "S",
        "metric": "Listing reviewed or unpublished",
        "dependsOn": [],
        "status": "open",
        "note": "",
        "meetingId": getattr(ctx, "meeting_id", "") or "",
        "source": "tool",
        "reaffirmedByMeetingIds": [],
        "dueAt": None,
        "createdAt": now,
        "updatedAt": now,
    }
    board_store.put_action(ctx.table, doc)
    return {"ok": True, "actionId": doc["actionId"], "listingId": listing_id}
