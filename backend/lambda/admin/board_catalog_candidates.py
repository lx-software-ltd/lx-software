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
    BOARD_CATALOG_NAME_DENY_TOKENS,
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
    """Public LCSD-like types only. Commercial Places stay on the owner queue
    unless :func:`places_commercial_auto_approvable` also matches."""
    return places_public_type(place)


def auto_approve_source(source: str) -> bool:
    return source in OFFICIAL_SOURCES


_SOCIAL_HOSTS = (
    "facebook.com",
    "instagram.com",
    "fb.com",
    "fb.me",
    "wa.me",
    "whatsapp.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "youtube.com",
    "linktr.ee",
)


def _http_url(value: Any) -> str:
    url = str(value or "").strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return ""


def _is_social_url(url: str) -> bool:
    from urllib.parse import urlparse

    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return any(host == name or host.endswith("." + name) for name in _SOCIAL_HOSTS)


def competitor_auto_approvable(row: dict[str, Any], district: str | None = None) -> bool:
    """A competitor listing is ready when Places found a real site and a district."""
    url = _http_url(row.get("officialUrl") or row.get("website"))
    if not url or _is_social_url(url):
        return False
    label = district if district is not None else str(row.get("district") or "")
    return board_hk.canonical_district(str(label)) != "unknown"


def places_commercial_auto_approvable(row: dict[str, Any]) -> bool:
    """Commercial Places with a real site, address and hours — same bar as competitors."""
    url = _http_url(row.get("officialUrl") or row.get("website"))
    if not url or _is_social_url(url):
        return False
    address = str(row.get("addressEn") or row.get("address") or "").strip()
    hours = str(row.get("openingHours") or "").strip()
    return bool(address and hours)


def _maybe_auto_approve(row: dict[str, Any], *, source: str, district: str) -> bool:
    if auto_approve_source(source):
        return True
    if source == "places" and (places_quality_ok(row) or places_commercial_auto_approvable(row)):
        return True
    if source == "competitor" and competitor_auto_approvable(row, district):
        return True
    return False


def _now() -> str:
    return board_store.now_iso()


# Official / category-specific Places queries may name the thing they seek.
_DENY_ALLOW_BY_KIND = {
    "places_kindergarten": frozenset({"kindergarten", "幼稚園", "nursery", "幼兒"}),
    "places_child_care": frozenset({"nursery", "幼兒", "day care", "日間護理"}),
    "edb_kindergarten": frozenset({"kindergarten", "幼稚園", "nursery", "幼兒"}),
    "swd_child_care": frozenset({"nursery", "幼兒", "day care", "日間護理"}),
}


def name_denied(name: str, *, facility_kind: str = "") -> bool:
    """Elderly / kindergarten / tutorial names stay off the owner queue.

    Tokens that match the intended ``facilityKind`` (e.g. ``places_kindergarten``)
    are allowed so category search is not emptied by its own query.
    """
    blob = str(name or "").casefold()
    if not blob:
        return False
    allowed = {str(t).casefold() for t in _DENY_ALLOW_BY_KIND.get(str(facility_kind or ""), ())}
    for token in BOARD_CATALOG_NAME_DENY_TOKENS:
        marker = str(token or "").casefold()
        if not marker or marker in allowed:
            continue
        if any(ord(ch) > 127 for ch in marker):
            if marker in blob:
                return True
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", blob):
            return True
    return False


def upsert_candidate(table: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Insert or refresh a candidate. Official / quality Places rows auto-approve."""
    source = str(row.get("source") or "unknown")
    name = str(row.get("nameEn") or row.get("name") or "").strip()
    if not name:
        raise ValueError("candidate name is required")
    if source in ("places", "competitor") and name_denied(
        name, facility_kind=str(row.get("facilityKind") or "")
    ):
        return {
            "skipped": True,
            "reason": "name deny-list",
            "source": source,
            "nameEn": name[:200],
        }
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
        if str(merged.get("status") or "") == "new" and _maybe_auto_approve(
            merged, source=source, district=str(merged.get("district") or district)
        ):
            merged["status"] = "approved"
            merged["approvedAt"] = now
        board_store.put_candidate(table, merged)
        return merged
    status = "new"
    if _maybe_auto_approve({**row, "district": district}, source=source, district=district):
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


CANDIDATE_PAGE = 20
CANDIDATE_PAGE_MAX = 200
CANDIDATE_SCAN_ONE = 10_000
CANDIDATE_SCAN_ALL = CANDIDATE_PAGE_MAX
COMPETITOR_STALE_DAYS = 7
COMPETITOR_ENRICH_PER_RUN = 20
PLACES_MISS_COOLDOWN_HOURS = 24 * 7
_BULK_DECISIONS = {"approve": "approved", "reject": "rejected", "close": "closed"}


def _match_text(row: dict[str, Any], q: str) -> bool:
    needle = q.casefold()
    hay = " ".join(
        str(row.get(key) or "")
        for key in ("nameEn", "nameZh", "name", "district", "source", "officialUrl", "addressEn")
    )
    return needle in hay.casefold()


def filter_candidates(
    rows: list[dict[str, Any]],
    *,
    source: str | None = None,
    district: str | None = None,
    q: str | None = None,
    missing_place_id: bool = False,
) -> list[dict[str, Any]]:
    wanted_source = str(source or "").strip().lower()
    wanted_district = str(district or "").strip()
    query = str(q or "").strip()
    out: list[dict[str, Any]] = []
    for row in rows:
        if wanted_source and str(row.get("source") or "").lower() != wanted_source:
            continue
        if wanted_district and str(row.get("district") or "") != wanted_district:
            continue
        if query and not _match_text(row, query):
            continue
        if missing_place_id and str(row.get("placeId") or "").strip():
            continue
        out.append(row)
    return out


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_bool(value: Any) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes")


def list_filtered(
    table: Any,
    status: str | None = None,
    *,
    source: str | None = None,
    district: str | None = None,
    q: str | None = None,
    missing_place_id: bool = False,
    limit: int = CANDIDATE_PAGE,
    cursor: int = 0,
) -> dict[str, Any]:
    page_size = max(1, min(CANDIDATE_PAGE_MAX, _as_int(limit, CANDIDATE_PAGE)))
    start = max(0, _as_int(cursor, 0))
    fetch_cap = CANDIDATE_SCAN_ONE if status else CANDIDATE_SCAN_ALL
    rows = filter_candidates(
        board_store.list_candidates(table, status, per_status_limit=fetch_cap),
        source=source,
        district=district,
        q=q,
        missing_place_id=missing_place_id,
    )
    page = rows[start : start + page_size]
    nxt = start + page_size if start + page_size < len(rows) else None
    return {"candidates": page, "nextCursor": nxt, "total": len(rows)}


def bulk_set_status(
    table: Any,
    *,
    decision: str,
    source: str | None = None,
    status: str = "new",
    before: str | None = None,
    district: str | None = None,
    q: str | None = None,
    missing_place_id: bool = False,
) -> dict[str, Any]:
    if decision not in _BULK_DECISIONS:
        raise ValueError("decision must be approve, reject, or close")
    target = _BULK_DECISIONS[decision]
    cutoff = None
    if before:
        try:
            cutoff = board_hk.parse_iso(str(before))
        except ValueError as exc:
            raise ValueError("before must be an ISO timestamp") from exc
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
    updated: list[dict[str, Any]] = []
    for row in filter_candidates(
        board_store.list_candidates(table, status or "new", per_status_limit=CANDIDATE_SCAN_ONE),
        source=source,
        district=district,
        q=q,
        missing_place_id=missing_place_id,
    ):
        if cutoff is not None:
            created = str(row.get("createdAt") or "")
            try:
                when = board_hk.parse_iso(created)
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when >= cutoff:
                continue
        updated.append(set_status(table, str(row.get("candidateId") or ""), target))
    return {"updated": len(updated), "status": target, "candidates": updated[:20]}


def expire_stale_competitor(
    table: Any,
    *,
    now: datetime | None = None,
    before: str | None = None,
    days: int = COMPETITOR_STALE_DAYS,
) -> int:
    """Close leftover `new` competitor rows with no Places match."""
    if before:
        try:
            cutoff = board_hk.parse_iso(str(before))
        except ValueError:
            cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=max(1, int(days)))
    else:
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=max(1, int(days)))
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    out = bulk_set_status(
        table,
        decision="close",
        source="competitor",
        status="new",
        before=cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        missing_place_id=True,
    )
    n = int(out.get("updated") or 0)
    if n:
        _log_event("info", tag="board_catalog_competitor_expired", count=n)
    return n


def _place_to_candidate_fields(place: dict[str, Any]) -> dict[str, Any]:
    hours = place.get("regularOpeningHours") or {}
    opening = ""
    if isinstance(hours, dict) and hours.get("weekdayDescriptions"):
        opening = "; ".join(str(x) for x in hours.get("weekdayDescriptions") or [])[:200]
    loc = place.get("location") if isinstance(place.get("location"), dict) else {}
    return {
        "placeId": str(place.get("placeId") or ""),
        "addressEn": str(place.get("address") or "")[:300],
        "officialUrl": str(place.get("website") or "")[:400],
        "phone": str(place.get("phone") or "")[:40],
        "openingHours": opening,
        "lat": loc.get("latitude") if loc else place.get("lat"),
        "lng": loc.get("longitude") if loc else place.get("lng"),
        "placesFetchedAt": _now(),
    }


def _places_retry_blocked(row: dict[str, Any]) -> bool:
    """A Places miss is not searched again until the cooldown elapses."""
    raw = str(row.get("placesTriedAt") or "").strip()
    if not raw:
        return False
    try:
        tried = board_hk.parse_iso(raw)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - tried < timedelta(hours=PLACES_MISS_COOLDOWN_HOURS)


def _remember_places_miss(table: Any, row: dict[str, Any]) -> None:
    stamped = {**row, "placesTriedAt": _now(), "updatedAt": _now()}
    board_store.put_candidate(table, stamped)


def enrich_with_places(table: Any, settings: dict[str, Any] | None = None, *, limit: int = COMPETITOR_ENRICH_PER_RUN) -> int:
    """Fill address / placeId on new competitor rows via Places text search."""
    import board_places

    cap = max(0, min(COMPETITOR_ENRICH_PER_RUN, int(limit or 0)))
    if cap <= 0:
        return 0
    n = 0
    searches = 0
    for row in board_store.list_candidates(table, "new", per_status_limit=10_000):
        if searches >= cap or n >= cap:
            break
        if str(row.get("source") or "") != "competitor":
            continue
        if str(row.get("placeId") or "").strip():
            continue
        if _places_retry_blocked(row):
            continue
        name = str(row.get("nameEn") or row.get("name") or "").strip()
        district = str(row.get("district") or "").strip()
        if not name:
            continue
        known = board_hk.canonical_district(district) != "unknown"
        query = f"{name} {district} Hong Kong" if known else f"{name} Hong Kong"
        searches += 1
        try:
            places = board_places.text_search(table, query, limit=1, settings=settings)
        except board_places.PlacesError as exc:
            _log_event("info", tag="board_catalog_competitor_enrich_stopped", error=str(exc)[:200])
            break
        if not places:
            _remember_places_miss(table, row)
            continue
        fields = _place_to_candidate_fields(places[0])
        if not fields.get("placeId"):
            _remember_places_miss(table, row)
            continue
        if not known:
            guessed = board_hk.district_from_address(str(fields.get("addressEn") or ""))
            if board_hk.canonical_district(guessed) != "unknown":
                fields["district"] = guessed
        merged = {**row, **{k: v for k, v in fields.items() if v not in (None, "")}}
        if str(row.get("status") or "") == "new" and competitor_auto_approvable(merged):
            merged["status"] = "approved"
        merged["updatedAt"] = _now()
        board_store.put_candidate(table, merged)
        n += 1
    if n:
        _log_event("info", tag="board_catalog_competitor_enriched", count=n)
    return n
