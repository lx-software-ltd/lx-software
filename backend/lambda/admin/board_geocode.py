"""Hong Kong Address Lookup Service geocoding for catalog imports.

Used when a sheet has a verified address and no lat/lng. Lookups are cached
30 days. Fail-open: a miss or network error leaves the org without
coordinates. A hit whose ALS district does not match ``area_name`` is dropped.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

import board_hk
from http_common import _log_event

ALS_LOOKUP = "https://www.als.gov.hk/lookup"
ALS_TIMEOUT_SECONDS = 4
ALS_CACHE_TTL_SECONDS = 30 * 86400
ALS_MAX_LIVE_LOOKUPS = 3
ALS_SHEET_BUDGET_SECONDS = 12
ALS_USER_AGENT = "SiuTinDeiBoardBot/1.0 (+https://siutindei.com/bot)"

_lookup_fn: Any = None


class AlsBudget:
    """Cap live ALS calls per sheet (cache hits do not count)."""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.live = 0

    def allow_live(self) -> bool:
        if self.live >= ALS_MAX_LIVE_LOOKUPS:
            return False
        return (time.monotonic() - self.started) < ALS_SHEET_BUDGET_SECONDS

    def record_live(self) -> None:
        self.live += 1


def set_lookup_for_tests(fn: Any) -> None:
    global _lookup_fn
    _lookup_fn = fn


def cache_name(address: str) -> str:
    digest = hashlib.sha256(_norm_address(address).encode("utf-8")).hexdigest()[:24]
    return f"geocode:als:{digest}"


def lookup_address(
    address: str,
    *,
    district: str,
    table: Any = None,
    budget: AlsBudget | None = None,
) -> dict[str, Any] | None:
    """Return ``{lat, lng, alsDistrict, source}`` when ALS agrees on the district."""
    text = str(address or "").strip()
    if not text or not district:
        return None
    if table is not None:
        try:
            import board_store

            hit = board_store.get_cache(table, cache_name(text))
        except Exception:
            hit = None
        payload = hit.get("payload") if isinstance(hit, dict) else None
        if isinstance(payload, dict) and payload.get("miss"):
            return None
        if isinstance(payload, dict) and payload.get("lat") is not None:
            if _districts_match(district, str(payload.get("alsDistrict") or "")):
                return {
                    "lat": float(payload["lat"]),
                    "lng": float(payload["lng"]),
                    "alsDistrict": str(payload.get("alsDistrict") or ""),
                    "source": "als",
                    "cached": True,
                }
            return None
    if budget is not None and not budget.allow_live():
        _log_event("info", tag="board_geocode_als_budget", address=text[:80])
        return None
    try:
        if budget is not None:
            budget.record_live()
        raw = _fetch_als(text) if _lookup_fn is None else _lookup_fn(text)
    except Exception as exc:
        _log_event("info", tag="board_geocode_als_failed", error=str(exc)[:200])
        return None
    if not isinstance(raw, dict):
        raw = {}
    chosen = _pick_suggestion(raw, district)
    if table is not None:
        try:
            import board_store

            board_store.put_cache(
                table,
                cache_name(text),
                chosen or {"miss": True},
                ttl_seconds=ALS_CACHE_TTL_SECONDS,
            )
        except Exception as exc:
            _log_event("info", tag="board_geocode_cache_failed", error=str(exc)[:200])
    if not chosen:
        return None
    return {**chosen, "source": "als", "cached": False}


def fill_org_coords(
    org: dict[str, Any],
    *,
    district: str,
    table: Any = None,
    budget: AlsBudget | None = None,
) -> dict[str, Any]:
    """Stamp lat/lng on a transformed org when address is present and coords are not."""
    if org.get("lat") is not None and org.get("lng") is not None:
        return org
    address = str(org.get("address") or "").strip()
    if not address:
        return org
    hit = lookup_address(
        address,
        district=district or str(org.get("area_name") or ""),
        table=table,
        budget=budget,
    )
    if not hit:
        return org
    org["lat"] = hit["lat"]
    org["lng"] = hit["lng"]
    note = str(org.get("vetting_note") or "")
    extra = "geocode_source=als"
    org["vetting_note"] = f"{note}; {extra}" if note else extra
    return org


def _fetch_als(address: str) -> dict[str, Any]:
    url = ALS_LOOKUP + "?" + urlparse.urlencode({"q": address})
    req = urlrequest.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": ALS_USER_AGENT},
        method="GET",
    )
    with urlrequest.urlopen(req, timeout=ALS_TIMEOUT_SECONDS) as resp:  # noqa: S310
        raw = resp.read()
    data = json.loads(raw.decode("utf-8", errors="replace") if raw else "{}")
    return data if isinstance(data, dict) else {}


def _pick_suggestion(payload: dict[str, Any], district: str) -> dict[str, Any] | None:
    rows = payload.get("SuggestedAddress")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        premises = ((row.get("Address") or {}).get("PremisesAddress") or {}) if isinstance(row.get("Address"), dict) else {}
        eng = premises.get("EngPremisesAddress") if isinstance(premises, dict) else {}
        als_district = ""
        if isinstance(eng, dict):
            block = eng.get("EngDistrict") if isinstance(eng.get("EngDistrict"), dict) else {}
            als_district = str((block or {}).get("DcDistrict") or "")
        geo = premises.get("GeospatialInformation") if isinstance(premises, dict) else {}
        if not isinstance(geo, dict):
            continue
        try:
            lat = float(geo.get("Latitude"))
            lng = float(geo.get("Longitude"))
        except (TypeError, ValueError):
            continue
        if not _districts_match(district, als_district):
            continue
        return {"lat": lat, "lng": lng, "alsDistrict": als_district}
    return None


def _districts_match(wanted: str, als: str) -> bool:
    left = _norm_district(wanted)
    right = _norm_district(als)
    if not left or not right:
        return False
    if left == right:
        return True
    mapped = board_hk.district_from_address(als)
    return mapped != "unknown" and _norm_district(mapped) == left


def _norm_district(name: str) -> str:
    text = " ".join(str(name or "").split())
    if text.lower().endswith(" district"):
        text = text[: -len(" district")]
    return text.casefold()


def _norm_address(address: str) -> str:
    return " ".join(str(address or "").casefold().split())
