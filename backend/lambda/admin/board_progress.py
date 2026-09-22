"""Listing, vendor-signing and content-curation progress for the owner.

The architect task that asked for realtime visibility of catalog gaps and
partnership bottlenecks is served here: one GET snapshot combining Aurora
product views (cached) with board prospects and the content calendar.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import board_content
import board_hk
import board_product
import board_store
from contract_constants import (
    BOARD_CATALOG_LAUNCH_LISTING_TARGET,
    BOARD_STAFF_CONTENT_CHANNELS,
    BOARD_STAFF_PROSPECT_STAGES,
)
from http_common import _utc_iso_z

PARTNERSHIP_WEEKLY_TARGET = 15
STALL_EDIT_DAYS = 7
LOW_COMPLETENESS = 0.5
UNLINKED_DISTRICT_LABEL = "No venue linked"
FUNNEL_DAYS = 7
CONTENT_HORIZON_DAYS = 7
MAX_STALLED_ROWS = 8
PUBLISHED_CONTENT = frozenset({"scheduled", "published"})
WARM_PIPELINE = frozenset({"qualified", "contacted", "replied", "onboarding", "listed"})
ACTIVE_SIGNING = frozenset({"trial", "active"})
CURATION_CHANNELS = ("facebook", "instagram", "instagram_story")


class _Ctx:
    def __init__(self, table: Any, settings: dict[str, Any] | None = None) -> None:
        self.table = table
        self.settings = settings or {}
        self.persona_id = ""


def snapshot(table: Any, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Owner-facing pack: listings, signings, outreach, content, bottlenecks."""
    now = datetime.now(timezone.utc)
    listings = _listings(table, settings)
    signings = _signings(table, settings)
    partnerships = _partnerships(table, now)
    content = _content_pack(table, now)
    return {
        "fetchedAt": _utc_iso_z(now),
        "listings": listings,
        "signings": signings,
        "partnerships": partnerships,
        "content": content,
        "bottlenecks": _bottlenecks(listings, signings, partnerships, content),
    }


def headline_pack(table: Any, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compact numbers for the daily-review headline (fills the unused slots)."""
    snap = snapshot(table, settings)
    listings = snap["listings"]
    signings = snap["signings"]
    partnerships = snap["partnerships"]
    content = snap["content"]
    return {
        "pipeline": {
            "qualifiedThisWeek": partnerships.get("qualifiedThisWeek") or 0,
            "weeklyTarget": partnerships.get("weeklyTarget") or PARTNERSHIP_WEEKLY_TARGET,
            "listed": int((partnerships.get("byStage") or {}).get("listed") or 0),
            "stalled": len(partnerships.get("stalled") or []),
        },
        "content": {
            "scheduledNext7": content.get("scheduledNext7") or 0,
            "emptyChannels": len(content.get("emptyChannels") or []),
            "drafted": int((content.get("byStatus") or {}).get("drafted") or 0),
        },
        "listings": {
            "activities": listings.get("activities") or 0,
            "providers": listings.get("providers") or 0,
            "lowCompleteness": len(listings.get("gaps") or []),
            "error": listings.get("error") or "",
            "launchTarget": listings.get("launchTarget") or BOARD_CATALOG_LAUNCH_LISTING_TARGET,
        },
        "signings": {
            "count": signings.get("count") or 0,
            "stalled": len(signings.get("stalled") or []),
            "error": signings.get("error") or "",
        },
    }


def _listings(table: Any, settings: dict[str, Any] | None) -> dict[str, Any]:
    empty = {
        "activities": 0,
        "providers": 0,
        "stores": 0,
        "completenessAvg": None,
        "hasPhotoAvg": None,
        "hasPriceAvg": None,
        "hasScheduleAvg": None,
        "hasGeoAvg": None,
        "byDistrict": [],
        "byCategory": [],
        "funnel7d": {"listingViews": 0, "leads": 0, "bookings": 0},
        "gaps": [],
        "error": "",
        "cached": False,
        "fetchedAt": None,
        "launchTarget": BOARD_CATALOG_LAUNCH_LISTING_TARGET,
    }
    try:
        ctx = _Ctx(table, settings)
        health = board_product.op_catalog_health(ctx, {})
        funnel = board_product.op_funnel(ctx, {})
    except (board_product.ProductError, Exception) as exc:
        empty["error"] = str(exc)[:200]
        return empty
    rows = [r for r in (health.get("rows") or []) if isinstance(r, dict)]
    funnel_rows = [r for r in (funnel.get("rows") or []) if isinstance(r, dict)]
    activities = sum(_num(r.get("activities")) for r in rows)
    providers = sum(_num(r.get("providers")) for r in rows)
    stores = sum(_num(r.get("stores")) for r in rows)
    scores = [_num(r.get("completeness")) for r in rows if r.get("completeness") is not None]
    photos = [_num(r.get("has_photo")) for r in rows if r.get("has_photo") is not None]
    prices = [_num(r.get("has_price")) for r in rows if r.get("has_price") is not None]
    hours = [_num(r.get("has_schedule")) for r in rows if r.get("has_schedule") is not None]
    geos = [_num(r.get("has_geo")) for r in rows if r.get("has_geo") is not None]
    by_district = _group_catalog(rows, "district")
    by_category = _group_catalog(rows, "category")
    unlinked_providers = 0
    for row in by_district:
        if row.get("label") == UNLINKED_DISTRICT_LABEL:
            unlinked_providers = int(row.get("providers") or 0)
            break
    providers_with_venue = max(0, int(providers) - unlinked_providers)
    gaps = []
    for row in by_district:
        if row["activities"] <= 0 or (
            row.get("completenessAvg") is not None and row["completenessAvg"] < LOW_COMPLETENESS
        ):
            missing = [
                name
                for name, key in (
                    ("photos", "hasPhotoAvg"),
                    ("price", "hasPriceAvg"),
                    ("hours", "hasScheduleAvg"),
                    ("geo", "hasGeoAvg"),
                )
                if row.get(key) is not None and row[key] < LOW_COMPLETENESS
            ]
            detail = (
                f"{row['activities']} listings · completeness "
                f"{_pct(row.get('completenessAvg'))}"
            )
            if missing:
                detail += " · missing " + ", ".join(missing)
            gaps.append(
                {
                    "kind": "district",
                    "label": row["label"] or "(unmapped)",
                    "detail": detail,
                }
            )
    cutoff = (datetime.now(timezone.utc) - timedelta(days=FUNNEL_DAYS)).date().isoformat()
    recent = [r for r in funnel_rows if str(r.get("day") or "") >= cutoff]
    return {
        **empty,
        "activities": int(activities),
        "providers": int(providers),
        "stores": int(stores),
        "completenessAvg": (sum(scores) / len(scores)) if scores else None,
        "hasPhotoAvg": (sum(photos) / len(photos)) if photos else None,
        "hasPriceAvg": (sum(prices) / len(prices)) if prices else None,
        "hasScheduleAvg": (sum(hours) / len(hours)) if hours else None,
        "hasGeoAvg": (sum(geos) / len(geos)) if geos else None,
        "byDistrict": by_district[:12],
        "byCategory": by_category[:12],
        "providersWithVenue": providers_with_venue,
        "funnel7d": {
            "listingViews": int(sum(_num(r.get("listing_views")) for r in recent)),
            "leads": int(sum(_num(r.get("leads_relayed")) for r in recent)),
            "bookings": int(sum(_num(r.get("bookings_confirmed")) for r in recent)),
        },
        "gaps": gaps[:8],
        "cached": bool(health.get("cached")),
        "fetchedAt": health.get("fetchedAt"),
    }


def _signings(table: Any, settings: dict[str, Any] | None) -> dict[str, Any]:
    empty: dict[str, Any] = {
        "count": 0,
        "byOnboardingStep": {},
        "bySubscription": {},
        "stalled": [],
        "error": "",
        "cached": False,
        "fetchedAt": None,
    }
    try:
        payload = board_product.op_provider_pipeline(_Ctx(table, settings), {})
    except (board_product.ProductError, Exception) as exc:
        empty["error"] = str(exc)[:200]
        return empty
    rows = [r for r in (payload.get("providers") or []) if isinstance(r, dict)]
    steps: dict[str, int] = {}
    subs: dict[str, int] = {}
    stalled: list[dict[str, Any]] = []
    for row in rows:
        step = str(row.get("onboarding_step") or "unknown")
        status = str(row.get("subscription_status") or "unknown")
        steps[step] = steps.get(step, 0) + 1
        subs[status] = subs.get(status, 0) + 1
        idle = _num(row.get("days_since_last_edit"))
        if idle >= STALL_EDIT_DAYS and status not in ACTIVE_SIGNING:
            stalled.append(
                {
                    "id": str(row.get("organization_id") or ""),
                    "name": str(row.get("organization_name") or row.get("organization_id") or "Provider"),
                    "step": step,
                    "status": status,
                    "daysSinceLastEdit": int(idle),
                    "signedUpOn": str(row.get("signed_up_on") or ""),
                }
            )
    stalled.sort(key=lambda r: int(r.get("daysSinceLastEdit") or 0), reverse=True)
    return {
        **empty,
        "count": int(payload.get("count") or len(rows)),
        "byOnboardingStep": steps,
        "bySubscription": subs,
        "stalled": stalled[:MAX_STALLED_ROWS],
        "cached": bool(payload.get("cached")),
        "fetchedAt": payload.get("fetchedAt"),
    }


def _partnerships(table: Any, now: datetime) -> dict[str, Any]:
    by_stage = {stage: 0 for stage in BOARD_STAFF_PROSPECT_STAGES}
    stalled: list[dict[str, Any]] = []
    qualified_this_week = 0
    week_start = _week_start_iso(now)
    now_iso = _utc_iso_z(now)
    rows = board_store.list_prospects(table, None, limit=400)
    needs_contact = 0
    for row in rows:
        stage = str(row.get("stage") or "discovered")
        if stage in by_stage:
            by_stage[stage] += 1
        else:
            by_stage[stage] = by_stage.get(stage, 0) + 1
        stamp = str(row.get("qualifiedAt") or row.get("updatedAt") or row.get("createdAt") or "")
        if stage in WARM_PIPELINE and stamp >= week_start:
            qualified_this_week += 1
        if stage == "qualified" and not row.get("contact"):
            needs_contact += 1
        next_touch = str(row.get("nextTouchAt") or "")
        if stage in ("contacted", "unresponsive") and (not next_touch or next_touch <= now_iso):
            stalled.append(
                {
                    "id": str(row.get("prospectId") or ""),
                    "name": str(row.get("name") or "Prospect"),
                    "stage": stage,
                    "district": str(row.get("district") or ""),
                    "nextTouchAt": next_touch,
                }
            )
    stalled.sort(key=lambda r: str(r.get("nextTouchAt") or ""))
    return {
        "byStage": by_stage,
        "qualifiedThisWeek": qualified_this_week,
        "weeklyTarget": PARTNERSHIP_WEEKLY_TARGET,
        "needsContact": needs_contact,
        "stalled": stalled[:MAX_STALLED_ROWS],
    }


def _content_pack(table: Any, now: datetime) -> dict[str, Any]:
    horizon_end = _utc_iso_z(now + timedelta(days=CONTENT_HORIZON_DAYS))
    now_iso = _utc_iso_z(now)
    rows = board_content.list_for_api(table, limit=400)
    by_status: dict[str, int] = {}
    scheduled_next = 0
    empty_channels: list[str] = []
    stalled_drafts: list[dict[str, Any]] = []
    per_channel: dict[str, int] = {ch: 0 for ch in CURATION_CHANNELS}
    for row in rows:
        status = str(row.get("status") or "idea")
        by_status[status] = by_status.get(status, 0) + 1
        slot = str(row.get("slotAt") or "")
        channel = str(row.get("channel") or "")
        if status in PUBLISHED_CONTENT and now_iso <= slot <= horizon_end:
            scheduled_next += 1
            if channel in per_channel:
                per_channel[channel] += 1
        if status in ("idea", "drafted") and slot and slot < _utc_iso_z(now - timedelta(days=3)):
            stalled_drafts.append(
                {
                    "id": str(row.get("contentId") or ""),
                    "channel": channel,
                    "status": status,
                    "slotAt": slot,
                    "title": str(row.get("copyEn") or row.get("copyZh") or row.get("pillar") or "Untitled"),
                }
            )
    for channel in CURATION_CHANNELS:
        if channel in BOARD_STAFF_CONTENT_CHANNELS and per_channel.get(channel, 0) == 0:
            empty_channels.append(channel)
    return {
        "byStatus": by_status,
        "scheduledNext7": scheduled_next,
        "emptyChannels": empty_channels,
        "stalledDrafts": stalled_drafts[:MAX_STALLED_ROWS],
        "horizonDays": CONTENT_HORIZON_DAYS,
    }


def _bottlenecks(
    listings: dict[str, Any],
    signings: dict[str, Any],
    partnerships: dict[str, Any],
    content: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if listings.get("error"):
        out.append(
            {
                "id": "listings-unavailable",
                "area": "listings",
                "severity": "warning",
                "summary": f"Catalog health is unavailable: {listings['error']}",
                "section": "progress",
            }
        )
    else:
        unlinked = next(
            (
                row
                for row in (listings.get("byDistrict") or [])
                if row.get("label") == UNLINKED_DISTRICT_LABEL and row.get("activities")
            ),
            None,
        )
        if unlinked:
            out.append(
                {
                    "id": "listings-unlinked",
                    "area": "listings",
                    "severity": "warning",
                    "summary": (
                        f"{int(unlinked['activities'])} listing(s) have no venue linked "
                        f"to the activity (district unknown)"
                    ),
                    "section": "progress",
                }
            )
        gap = next(
            (
                row
                for row in (listings.get("gaps") or [])
                if row.get("label") != UNLINKED_DISTRICT_LABEL
            ),
            None,
        )
        if gap:
            out.append(
                {
                    "id": "listings-gap",
                    "area": "listings",
                    "severity": "warning",
                    "summary": f"Listing gap in {gap.get('label')}: {gap.get('detail')}",
                    "section": "progress",
                }
            )
    stalled_sign = signings.get("stalled") or []
    if signings.get("error"):
        out.append(
            {
                "id": "signings-unavailable",
                "area": "signings",
                "severity": "warning",
                "summary": f"Provider pipeline is unavailable: {signings['error']}",
                "section": "receivables",
            }
        )
    elif stalled_sign:
        first = stalled_sign[0]
        out.append(
            {
                "id": "signings-stalled",
                "area": "signings",
                "severity": "warning",
                "summary": (
                    f"{len(stalled_sign)} vendor onboarding(s) idle ≥ {STALL_EDIT_DAYS} days "
                    f"(e.g. {first.get('name')} on {first.get('step')})"
                ),
                "section": "receivables",
            }
        )
    warm = int((partnerships.get("qualifiedThisWeek") or 0))
    target = int(partnerships.get("weeklyTarget") or PARTNERSHIP_WEEKLY_TARGET)
    if warm < target:
        out.append(
            {
                "id": "partnerships-target",
                "area": "partnerships",
                "severity": "warning" if warm > 0 else "danger",
                "summary": f"Partnership pipeline {warm} this week vs target {target}",
                "section": "pipeline",
            }
        )
    stalled_p = partnerships.get("stalled") or []
    if stalled_p:
        out.append(
            {
                "id": "partnerships-stalled",
                "area": "partnerships",
                "severity": "warning",
                "summary": f"{len(stalled_p)} outreach sequence(s) waiting on a next touch",
                "section": "pipeline",
            }
        )
    needs = int(partnerships.get("needsContact") or 0)
    if needs:
        out.append(
            {
                "id": "partnerships-contact",
                "area": "partnerships",
                "severity": "warning",
                "summary": f"{needs} qualified prospect(s) still need a business email",
                "section": "pipeline",
            }
        )
    empty = content.get("emptyChannels") or []
    if empty:
        out.append(
            {
                "id": "content-empty",
                "area": "content",
                "severity": "warning",
                "summary": f"No posts scheduled in the next {CONTENT_HORIZON_DAYS} days on {', '.join(empty)}",
                "section": "content",
            }
        )
    drafts = content.get("stalledDrafts") or []
    if drafts:
        out.append(
            {
                "id": "content-drafts",
                "area": "content",
                "severity": "warning",
                "summary": f"{len(drafts)} content draft(s) sitting more than three days",
                "section": "content",
            }
        )
    return out[:8]


def _group_catalog(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, float]] = {}
    scores: dict[str, list[float]] = {}
    photos: dict[str, list[float]] = {}
    prices: dict[str, list[float]] = {}
    hours: dict[str, list[float]] = {}
    geos: dict[str, list[float]] = {}
    for row in rows:
        label = str(row.get(key) or "").strip() or "(unmapped)"
        if key == "district" and label.lower() == "unknown":
            label = UNLINKED_DISTRICT_LABEL
        bucket = buckets.setdefault(label, {"activities": 0, "providers": 0, "stores": 0})
        bucket["activities"] += _num(row.get("activities"))
        bucket["providers"] += _num(row.get("providers"))
        bucket["stores"] += _num(row.get("stores"))
        if row.get("completeness") is not None:
            scores.setdefault(label, []).append(_num(row.get("completeness")))
        if row.get("has_photo") is not None:
            photos.setdefault(label, []).append(_num(row.get("has_photo")))
        if row.get("has_price") is not None:
            prices.setdefault(label, []).append(_num(row.get("has_price")))
        if row.get("has_schedule") is not None:
            hours.setdefault(label, []).append(_num(row.get("has_schedule")))
        if row.get("has_geo") is not None:
            geos.setdefault(label, []).append(_num(row.get("has_geo")))
    out: list[dict[str, Any]] = []
    for label, bucket in buckets.items():
        vals = scores.get(label) or []
        photo_vals = photos.get(label) or []
        price_vals = prices.get(label) or []
        hour_vals = hours.get(label) or []
        geo_vals = geos.get(label) or []
        out.append(
            {
                "label": label,
                "activities": int(bucket["activities"]),
                "providers": int(bucket["providers"]),
                "stores": int(bucket["stores"]),
                "completenessAvg": (sum(vals) / len(vals)) if vals else None,
                "hasPhotoAvg": (sum(photo_vals) / len(photo_vals)) if photo_vals else None,
                "hasPriceAvg": (sum(price_vals) / len(price_vals)) if price_vals else None,
                "hasScheduleAvg": (sum(hour_vals) / len(hour_vals)) if hour_vals else None,
                "hasGeoAvg": (sum(geo_vals) / len(geo_vals)) if geo_vals else None,
            }
        )
    out.sort(key=lambda r: r["activities"], reverse=True)
    return out


def _week_start_iso(now: datetime) -> str:
    local = board_hk.as_hkt(now)
    monday = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return board_hk.to_iso(monday.astimezone(timezone.utc))


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "n/a"


def public_snapshot(table: Any, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings if settings is not None else board_store.load_settings(table)
    return snapshot(table, settings)
