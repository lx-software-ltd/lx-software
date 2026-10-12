"""Places sweep inside the go-live neighbourhoods (Stanley first).

Kept out of ``board_catalog_discovery`` so that module stays under the 500-line
ceiling. The daily tick still enters through ``discover_places``.
"""

from __future__ import annotations

from typing import Any

import board_catalog_candidates
import board_catalog_focus
import board_hk
import board_places
import board_store
from http_common import _log_event


def place_row(place: dict[str, Any], district: str, now: str, *, area: str = "") -> dict[str, Any]:
    row = {
        "source": "places",
        "placeId": place.get("placeId"),
        "sourceId": place.get("placeId"),
        "nameEn": place.get("name"),
        "addressEn": place.get("address"),
        "district": district or board_hk.district_from_address(str(place.get("address") or "")),
        "lat": place.get("lat"),
        "lng": place.get("lng"),
        "phone": place.get("phone") or "",
        "officialUrl": place.get("website") or "",
        "facilityKind": place.get("facilityKind") or "places_park",
        "types": place.get("types") or [],
        "rating": place.get("rating"),
        "userRatingCount": place.get("userRatingCount"),
        "placesFetchedAt": now,
    }
    if area:
        row["area"] = area
    hours = place.get("regularOpeningHours") or {}
    if isinstance(hours, dict) and hours.get("weekdayDescriptions"):
        row["openingHours"] = "; ".join(str(x) for x in hours.get("weekdayDescriptions") or [])[:200]
    return row


def upsert_places(
    table: Any,
    places: list[dict[str, Any]],
    district: str,
    *,
    area: str = "",
    settings: dict[str, Any] | None = None,
) -> int:
    upserted = 0
    now = board_store.now_iso()
    for place in places:
        if str(place.get("businessStatus") or "") == "CLOSED_PERMANENTLY":
            cand = {
                "source": "places",
                "placeId": place.get("placeId"),
                "sourceId": place.get("placeId"),
                "nameEn": place.get("name"),
                "addressEn": place.get("address"),
                "district": district,
            }
            if not board_catalog_candidates.is_duplicate(table, cand):
                doc = board_catalog_candidates.upsert_candidate(table, cand)
                cid = str(doc.get("candidateId") or "")
                if cid:
                    board_catalog_candidates.set_status(table, cid, "closed")
            continue
        doc = board_catalog_candidates.upsert_candidate(
            table, place_row(place, district, now, area=area), settings=settings
        )
        if not doc.get("skipped"):
            upserted += 1
    return upserted


def discover_focus_areas(table: Any, settings: dict[str, Any]) -> dict[str, Any]:
    """Neighbourhood sweep for the go-live focus: free-text class / club queries per area.

    Results that Places pulls in from outside the area circle (a Causeway Bay
    studio for "kids dance class Stanley") are dropped unless the address or
    the point sits in that area.
    """
    areas = board_catalog_focus.focus_areas(settings)
    queries = board_catalog_focus.focus_queries()
    out: dict[str, Any] = {"areas": [], "upserted": 0, "outside": 0, "errors": []}
    if not areas or not queries:
        return out
    for area in areas:
        aid = str(area.get("id") or "")
        district = str(area.get("district") or "")
        try:
            places = board_places.discover_area(table, area, queries, settings=settings)
        except board_places.PlacesError as exc:
            out["errors"].append(f"{aid}:{exc}"[:160])
            continue
        inside: list[dict[str, Any]] = []
        for place in places:
            probe = {
                "addressEn": place.get("address"),
                "nameEn": place.get("name"),
                "lat": place.get("lat"),
                "lng": place.get("lng"),
            }
            if board_catalog_focus.area_for(probe) == aid:
                inside.append(place)
            else:
                out["outside"] += 1
        out["areas"].append(aid)
        out["upserted"] += upsert_places(table, inside, district, area=aid, settings=settings)
    _log_event(
        "info",
        tag="board_catalog_focus_discovery",
        areas=out["areas"],
        upserted=out["upserted"],
        outside=out["outside"],
        errors=len(out["errors"]),
    )
    return out
