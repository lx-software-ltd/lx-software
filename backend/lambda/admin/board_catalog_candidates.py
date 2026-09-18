"""Catalog candidate queue, listing-name dedupe and Places-field expiry."""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import board_hk
import board_store
from contract_constants import (
    BOARD_CATALOG_CANDIDATE_STATUSES,
    BOARD_CATALOG_PLACES_TTL_DAYS,
    BOARD_CATALOG_SOURCE_CATEGORY,
)
from http_common import _log_event

OFFICIAL_SOURCES = frozenset({"lcsd", "edb", "swd"})
PLACES_PUBLIC_TYPES = frozenset(
    {
        "park",
        "playground",
        "library",
        "swimming_pool",
        "museum",
        "tourist_attraction",
    }
)
_NAME_STRIP = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")


def norm_name(value: str) -> str:
    return _NAME_STRIP.sub("", (value or "").lower())


def listing_key(name: str, district: str) -> str:
    return f"{norm_name(name)}|{board_hk.district_from_address(district) if district else ''}"[:160]


def geohash_approx(lat: Any, lng: Any, *, metres: int = 50) -> str:
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return ""
    # ~50 m at HK latitudes: 0.00045 deg lat, 0.00049 deg lng
    step_lat = max(metres, 1) / 111_000
    step_lng = max(metres, 1) / (111_000 * max(0.2, math.cos(math.radians(lat_f))))
    return f"{round(lat_f / step_lat) * step_lat:.5f},{round(lng_f / step_lng) * step_lng:.5f}"


def candidate_dedupe_key(row: dict[str, Any]) -> str:
    source = str(row.get("source") or "")
    source_id = str(row.get("sourceId") or row.get("placeId") or "")
    if source and source_id:
        return hashlib.sha256(f"{source}|{source_id}".encode("utf-8")).hexdigest()[:24]
    key = listing_key(str(row.get("nameEn") or row.get("name") or ""), str(row.get("district") or ""))
    geo = geohash_approx(row.get("lat"), row.get("lng"))
    return hashlib.sha256(f"{key}|{geo}".encode("utf-8")).hexdigest()[:24]


def category_for(row: dict[str, Any]) -> str:
    kind = str(row.get("facilityKind") or row.get("sourceKind") or "")
    if kind and BOARD_CATALOG_SOURCE_CATEGORY.get(kind):
        return BOARD_CATALOG_SOURCE_CATEGORY[kind]
    if row.get("category"):
        return str(row.get("category"))
    source = str(row.get("source") or "")
    return BOARD_CATALOG_SOURCE_CATEGORY.get(source, "Class")


PLACES_PUBLIC_KINDS = frozenset(
    {
        "places_playground",
        "places_park",
        "places_swimming",
        "places_library",
        "places_museum",
    }
)


def places_public_type(place: dict[str, Any]) -> bool:
    types = {str(t).lower() for t in (place.get("types") or [])}
    if types & PLACES_PUBLIC_TYPES:
        return True
    return str(place.get("facilityKind") or "") in PLACES_PUBLIC_KINDS


def places_quality_ok(place: dict[str, Any]) -> bool:
    """Public LCSD-like types only. Commercial Places stay on the owner queue."""
    return places_public_type(place)


def auto_approve_source(source: str) -> bool:
    return source in OFFICIAL_SOURCES


def _now() -> str:
    return board_store.now_iso()


def upsert_candidate(table: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Insert or refresh a candidate. Official / quality Places rows auto-approve."""
    source = str(row.get("source") or "unknown")
    name = str(row.get("nameEn") or row.get("name") or "").strip()
    if not name:
        raise ValueError("candidate name is required")
    district = str(row.get("district") or board_hk.district_from_address(str(row.get("addressEn") or row.get("address") or "")))
    dedupe = candidate_dedupe_key({**row, "nameEn": name, "district": district})
    existing_id = board_store.get_candidate_by_dedupe(table, dedupe)
    now = _now()
    if existing_id:
        current = board_store.get_candidate(table, existing_id) or {}
        if current.get("status") in ("imported", "rejected", "closed"):
            return current
        incoming = {k: v for k, v in row.items() if v not in (None, "")}
        described = str(current.get("descriptionSource") or "") not in ("", "template")
        incoming_is_template = str(incoming.get("descriptionSource") or "template") in ("", "template")
        if described and incoming_is_template:
            for key in ("descriptionEn", "descriptionZh", "descriptionSource"):
                incoming.pop(key, None)
        merged = {**current, **incoming}
        merged["candidateId"] = existing_id
        merged["updatedAt"] = now
        board_store.put_candidate(table, merged)
        return merged
    status = "approved" if auto_approve_source(source) else "new"
    if source == "places" and places_quality_ok(row):
        status = "approved"
    doc = {
        "candidateId": board_store.new_id(),
        "source": source,
        "sourceId": str(row.get("sourceId") or row.get("placeId") or "")[:80],
        "placeId": str(row.get("placeId") or ""),
        "nameEn": name[:200],
        "nameZh": str(row.get("nameZh") or "")[:200],
        "district": district[:80],
        "addressEn": str(row.get("addressEn") or row.get("address") or "")[:300],
        "addressZh": str(row.get("addressZh") or "")[:300],
        "lat": row.get("lat"),
        "lng": row.get("lng"),
        "phone": str(row.get("phone") or "")[:40],
        "openingHours": str(row.get("openingHours") or "")[:200],
        "officialUrl": str(row.get("officialUrl") or row.get("website") or "")[:400],
        "category": category_for(row),
        "facilityKind": str(row.get("facilityKind") or ""),
        "descriptionEn": str(row.get("descriptionEn") or "")[:400],
        "descriptionZh": str(row.get("descriptionZh") or "")[:400],
        "descriptionSource": str(row.get("descriptionSource") or "template"),
        "placesFetchedAt": str(row.get("placesFetchedAt") or (now if source == "places" else "")),
        "status": status,
        "createdAt": now,
        "updatedAt": now,
    }
    board_store.put_candidate(table, doc)
    board_store.put_candidate_dedupe(table, dedupe, str(doc["candidateId"]))
    return doc


def remember_listing(table: Any, org: dict[str, Any]) -> None:
    name = str(org.get("name") or org.get("nameEn") or "")
    district = str(org.get("area_name") or org.get("district") or "")
    key = listing_key(name, district)
    if not key.startswith("|") and not board_store.get_listing_mirror(table, key):
        board_store.put_listing_mirror(
            table,
            key,
            {
                "name": name,
                "district": district,
                "lat": org.get("lat"),
                "lng": org.get("lng"),
                "placeId": org.get("placeId") or "",
                "updatedAt": _now(),
            },
        )
    geo = geohash_approx(org.get("lat"), org.get("lng"))
    if geo and not board_store.get_listing_mirror(table, f"geo|{geo}"):
        board_store.put_listing_mirror(table, f"geo|{geo}", {"name": name, "district": district, "updatedAt": _now()})


def is_duplicate(table: Any, row: dict[str, Any]) -> bool:
    name = str(row.get("nameEn") or row.get("name") or "")
    district = str(row.get("district") or "")
    key = listing_key(name, district)
    if board_store.get_listing_mirror(table, key):
        return True
    geo = geohash_approx(row.get("lat"), row.get("lng"))
    if geo and board_store.get_listing_mirror(table, f"geo|{geo}"):
        return True
    existing = board_store.get_candidate_by_dedupe(table, candidate_dedupe_key(row))
    if not existing:
        return False
    doc = board_store.get_candidate(table, existing) or {}
    return str(doc.get("status") or "") in ("imported", "closed")


def set_status(table: Any, candidate_id: str, status: str) -> dict[str, Any]:
    if status not in BOARD_CATALOG_CANDIDATE_STATUSES:
        raise ValueError(f"unknown candidate status {status}")
    doc = board_store.get_candidate(table, candidate_id)
    if not doc:
        raise KeyError(candidate_id)
    doc["status"] = status
    doc["updatedAt"] = _now()
    board_store.put_candidate(table, doc)
    return doc


def seed_listing_mirror(table: Any) -> int:
    """Remember names already imported through catalog sheets or this queue.

    Runs once per table object so preview + import + discovery do not rewrite
    the mirror on every nested call in the same Lambda invocation.
    """
    import board_catalog_import

    if getattr(table, "_catalog_mirror_seeded", False):
        return 0
    try:
        setattr(table, "_catalog_mirror_seeded", True)
    except Exception:
        pass
    n = 0
    for status in ("delivered", "awaiting_import", "needs_owner"):
        for task in board_store.list_tasks(table, status, limit=200):
            if not board_catalog_import.is_catalog_sheet(task):
                continue
            preview = task.get("importPreview") if isinstance(task.get("importPreview"), dict) else {}
            payload = preview.get("payload") if isinstance(preview.get("payload"), dict) else {}
            for org in payload.get("organizations") or []:
                if isinstance(org, dict) and (org.get("name") or org.get("nameEn")):
                    remember_listing(table, org)
                    n += 1
    for cand in board_store.list_candidates(table, "imported", limit=10_000):
        remember_listing(
            table,
            {
                "name": cand.get("nameEn") or cand.get("name"),
                "area_name": cand.get("district"),
                "lat": cand.get("lat"),
                "lng": cand.get("lng"),
                "placeId": cand.get("placeId"),
            },
        )
        n += 1
    return n


def counts_by_source(table: Any) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for row in board_store.list_candidates(table, per_status_limit=10_000):
        source = str(row.get("source") or "unknown")
        status = str(row.get("status") or "new")
        bucket = out.setdefault(source, {s: 0 for s in BOARD_CATALOG_CANDIDATE_STATUSES})
        bucket[status] = int(bucket.get(status) or 0) + 1
    return out


def expire_stale_places(table: Any, *, now: datetime | None = None) -> int:
    """Drop Places-derived hours / phone / rating after the 30-day cache window."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=BOARD_CATALOG_PLACES_TTL_DAYS)
    n = 0
    for row in board_store.list_candidates(table, per_status_limit=10_000):
        if str(row.get("source") or "") != "places":
            continue
        if row.get("placesExpired"):
            continue
        fetched = str(row.get("placesFetchedAt") or "")
        if not fetched:
            continue
        try:
            when = board_hk.parse_iso(fetched)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        compare = cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)
        if when > compare:
            continue
        row["openingHours"] = ""
        row["phone"] = ""
        row["rating"] = None
        row["placesExpired"] = True
        row["updatedAt"] = _now()
        board_store.put_candidate(table, row)
        n += 1
    if n:
        _log_event("info", tag="board_catalog_places_expired", count=n)
    return n
