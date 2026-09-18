"""Always-on catalog discovery: Places sweep, open-data refresh, competitor indexes."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import board_catalog_bulk
import board_catalog_candidates
import board_hk
import board_places
import board_staff
import board_store
from contract_constants import (
    BOARD_CATALOG_DISCOVERY_DISTRICTS_PER_DAY,
    BOARD_CATALOG_DISTRICTS,
    BOARD_KEY,
)
from http_common import _log_event

CURSOR_CACHE = "catalog:discovery:cursor"
NAME_LINE = re.compile(r"^(?:[-*•]\s*)?([A-Z][\w'&.\-]{2,}(?:\s+[A-Za-z0-9'&.\-]{2,}){0,8})\s*$")
ANCHOR = re.compile(r"<a\b[^>]*>([^<]{4,80})</a>", re.I)
HEADING = re.compile(r"<h[1-3]\b[^>]*>([^<]{4,80})</h[1-3]>", re.I)


def _district_names() -> list[str]:
    names: list[str] = []
    for row in BOARD_CATALOG_DISTRICTS:
        if isinstance(row, dict) and row.get("name"):
            names.append(str(row["name"]))
    return names or list(board_hk.DISTRICT_CENTERS.keys())


def _cursor(table: Any) -> dict[str, Any]:
    hit = board_store.get_cache(table, CURSOR_CACHE)
    payload = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else {}
    return {
        "offset": int(payload.get("offset") or 0),
        "lastOpenDataAt": str(payload.get("lastOpenDataAt") or ""),
        "lastPlacesAt": str(payload.get("lastPlacesAt") or ""),
    }


def _save_cursor(table: Any, doc: dict[str, Any]) -> None:
    board_store.put_cache(table, CURSOR_CACHE, doc, ttl_seconds=40 * 86400)


def rotate_districts(table: Any, n: int | None = None) -> list[str]:
    names = _district_names()
    if not names:
        return []
    take = max(1, int(n or BOARD_CATALOG_DISCOVERY_DISTRICTS_PER_DAY))
    cur = _cursor(table)
    start = int(cur.get("offset") or 0) % len(names)
    chosen = [names[(start + i) % len(names)] for i in range(take)]
    cur["offset"] = (start + take) % len(names)
    _save_cursor(table, cur)
    return chosen


def discover_places(table: Any, settings: dict[str, Any], districts: list[str] | None = None) -> dict[str, Any]:
    chosen = districts or rotate_districts(table)
    upserted = 0
    errors: list[str] = []
    for name in chosen:
        try:
            places = board_places.discover(table, name, settings=settings, pages=1, limit=10)
        except board_places.PlacesError as exc:
            errors.append(f"{name}:{exc}"[:160])
            continue
        now = board_store.now_iso()
        for place in places:
            if str(place.get("businessStatus") or "") == "CLOSED_PERMANENTLY":
                cand = {
                    "source": "places",
                    "placeId": place.get("placeId"),
                    "sourceId": place.get("placeId"),
                    "nameEn": place.get("name"),
                    "addressEn": place.get("address"),
                    "district": name,
                }
                if not board_catalog_candidates.is_duplicate(table, cand):
                    doc = board_catalog_candidates.upsert_candidate(table, cand)
                    board_catalog_candidates.set_status(table, str(doc["candidateId"]), "closed")
                continue
            row = {
                "source": "places",
                "placeId": place.get("placeId"),
                "sourceId": place.get("placeId"),
                "nameEn": place.get("name"),
                "addressEn": place.get("address"),
                "district": name or board_hk.district_from_address(str(place.get("address") or "")),
                "phone": place.get("phone") or "",
                "officialUrl": place.get("website") or "",
                "facilityKind": place.get("facilityKind") or "places_park",
                "types": place.get("types") or [],
                "rating": place.get("rating"),
                "userRatingCount": place.get("userRatingCount"),
                "placesFetchedAt": now,
            }
            hours = place.get("regularOpeningHours") or {}
            if isinstance(hours, dict) and hours.get("weekdayDescriptions"):
                row["openingHours"] = "; ".join(str(x) for x in hours.get("weekdayDescriptions") or [])[:200]
            board_catalog_candidates.upsert_candidate(table, row)
            upserted += 1
    cur = _cursor(table)
    cur["lastPlacesAt"] = board_store.now_iso()
    _save_cursor(table, cur)
    return {"districts": chosen, "upserted": upserted, "errors": errors}


def refresh_open_data(table: Any) -> dict[str, Any]:
    notes: dict[str, Any] = {}
    for source in ("lcsd", "edb", "swd"):
        try:
            notes[source] = board_catalog_bulk.ingest_source(table, source, force=True)
        except Exception as exc:
            notes[source] = {"error": str(exc)[:200]}
    cur = _cursor(table)
    cur["lastOpenDataAt"] = board_store.now_iso()
    _save_cursor(table, cur)
    return notes


def extract_listing_names(html_or_text: str) -> list[str]:
    """Names only — never copy competitor descriptions or photos."""
    names: list[str] = []
    seen: set[str] = set()
    blob = html_or_text or ""
    for pattern in (ANCHOR, HEADING):
        for match in pattern.findall(blob):
            name = " ".join(str(match).split())
            key = board_catalog_candidates.norm_name(name)
            if 3 < len(name) < 80 and key and key not in seen:
                seen.add(key)
                names.append(name)
    for line in blob.splitlines():
        match = NAME_LINE.match(line.strip())
        if not match:
            continue
        name = match.group(1).strip()
        key = board_catalog_candidates.norm_name(name)
        if key and key not in seen and "http" not in name.lower():
            seen.add(key)
            names.append(name)
        if len(names) >= 80:
            break
    return names[:80]


def ingest_listings_page(table: Any, watch: dict[str, Any], text: str, url: str) -> int:
    host = (urlparse(url).netloc or "").lower()
    names = extract_listing_names(text)
    page_district = str(watch.get("district") or "")
    if not page_district or page_district == "unknown":
        guessed = board_hk.district_from_address(text)
        page_district = guessed if guessed != "unknown" else ""
    n = 0
    for name in names:
        district = page_district
        board_catalog_candidates.upsert_candidate(
            table,
            {
                "source": "competitor",
                "sourceId": f"{host}:{board_catalog_candidates.norm_name(name)}"[:80],
                "nameEn": name,
                "district": district or "unknown",
                "officialUrl": "",
                "facilityKind": "competitor",
            },
        )
        n += 1
    _log_event("info", tag="board_catalog_listings_index", host=host[:80], names=n, watch=str(watch.get("watchId") or ""))
    return n


def run_discovery(table: Any, settings: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    if not board_staff.enabled(settings):
        return {"ok": True, "skipped": "disabled"}
    board_catalog_candidates.seed_listing_mirror(table)
    when = now or board_hk.now_hkt()
    places = discover_places(table, settings)
    open_data: dict[str, Any] = {}
    if when.weekday() == 0 or not _cursor(table).get("lastOpenDataAt"):
        open_data = refresh_open_data(table)
    expired = board_catalog_candidates.expire_stale_places(table, now=when.astimezone() if when.tzinfo else when)
    return {"ok": True, "places": places, "openData": open_data, "placesExpired": expired}


def handle_tick(event: dict[str, Any]) -> dict[str, Any]:
    if not board_store.event_targets_this_board(event):
        return {"ok": True, "skipped": "other-board"}
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    return run_discovery(table, settings)
