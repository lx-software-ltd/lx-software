"""Google Places API (New) for prospect discovery.

Field mask is one constant (Places rejects unknown fields with 400).
The spec quoted Pro SKUs (USD 0.032 / 0.017). This mask includes
website, phone, rating and hours, which are **Enterprise** fields.
Prices verified 2026-09-10:

  Text Search Enterprise  USD 0.035
  Place Details Enterprise USD 0.020

See docs/architecture/executive-board-autonomy-reviewer-notes.md WP6.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import board_hk
import board_store
from admin_runtime import _get_secretsmanager_client
from contract_constants import BOARD_STAFF_PLACES_MONTHLY_CAP_USD
from http_common import _log_event
from openrouter_client import read_secret_string

# Spec field mask (no ``places.`` prefix). Search requests prefix each path.
FIELD_MASK = (
    "id,displayName,formattedAddress,websiteUri,nationalPhoneNumber,"
    "rating,userRatingCount,regularOpeningHours,businessStatus,types"
)
SEARCH_FIELD_MASK = ",".join(f"places.{part}" for part in FIELD_MASK.split(","))
TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
TEXT_SEARCH_USD = 0.035
DETAILS_USD = 0.020
CACHE_TTL_SECONDS = 30 * 86400
_key_cache: str | None = None


class PlacesError(ValueError):
    """Places request cannot run (cap, config, or upstream)."""

    def __init__(self, message: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.payload = payload or {"error": message}


def _api_key() -> str:
    global _key_cache
    if _key_cache:
        return _key_cache
    plain = (os.environ.get("GOOGLE_PLACES_KEY") or "").strip()
    if plain:
        _key_cache = plain
        return plain
    arn = (os.environ.get("GOOGLE_PLACES_KEY_SECRET_ARN") or "").strip()
    if not arn:
        raise PlacesError("Google Places key is not configured")
    _key_cache = read_secret_string(_get_secretsmanager_client(), arn, what="Google Places key").strip()
    return _key_cache


def reset_key_cache_for_tests() -> None:
    global _key_cache
    _key_cache = None


def _month_key() -> str:
    return f"places:month:{board_hk.today_hkt()[:7]}"


def _month_doc(table: Any) -> dict[str, Any]:
    hit = board_store.get_cache(table, _month_key())
    payload = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else {}
    return {
        "usd": float(payload.get("usd") or 0),
        "searches": int(payload.get("searches") or 0),
        "details": int(payload.get("details") or 0),
    }


def _save_month(table: Any, doc: dict[str, Any]) -> None:
    board_store.put_cache(table, _month_key(), doc, ttl_seconds=40 * 86400)


def monthly_cap_usd(settings: dict[str, Any] | None = None) -> float:
    staff = (settings or {}).get("staff") or {}
    try:
        override = float(staff.get("placesMonthlyCapUsd"))
    except (TypeError, ValueError):
        override = 0
    if override > 0:
        return override
    return float(BOARD_STAFF_PLACES_MONTHLY_CAP_USD)


def _charge(table: Any, settings: dict[str, Any] | None, usd: float, *, kind: str) -> None:
    doc = _month_doc(table)
    cap = monthly_cap_usd(settings)
    if doc["usd"] + usd > cap + 1e-9:
        raise PlacesError(
            "places monthly cap exceeded",
            {"error": "places monthly cap exceeded", "usd": doc["usd"], "cap": cap},
        )
    doc["usd"] = round(doc["usd"] + usd, 6)
    if kind == "search":
        doc["searches"] = int(doc["searches"]) + 1
    else:
        doc["details"] = int(doc["details"]) + 1
    _save_month(table, doc)
    board_store.add_external_usage_day(table, "places", 1)


def _http(method: str, url: str, *, headers: dict[str, str], body: bytes | None = None) -> dict[str, Any]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read() if exc.fp else b""
        raise PlacesError(f"Places HTTP {exc.code}: {raw[:200]!r}") from exc
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise PlacesError("Places returned non-JSON") from exc
    return parsed if isinstance(parsed, dict) else {}


def _normalise_place(raw: dict[str, Any]) -> dict[str, Any]:
    name = raw.get("displayName")
    if isinstance(name, dict):
        name = name.get("text") or ""
    return {
        "placeId": str(raw.get("id") or raw.get("placeId") or ""),
        "name": str(name or raw.get("name") or ""),
        "address": str(raw.get("formattedAddress") or ""),
        "website": str(raw.get("websiteUri") or ""),
        "phone": str(raw.get("nationalPhoneNumber") or ""),
        "rating": raw.get("rating"),
        "userRatingCount": raw.get("userRatingCount"),
        "regularOpeningHours": raw.get("regularOpeningHours") or {},
        "businessStatus": str(raw.get("businessStatus") or ""),
        "types": list(raw.get("types") or []),
    }


def text_search(
    table: Any,
    query: str,
    *,
    region: str = "hk",
    limit: int = 20,
    settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    q = " ".join(str(query or "").split())
    if not q:
        raise PlacesError("query is required")
    limit = max(1, min(20, int(limit)))
    region = (region or "hk").strip().lower() or "hk"
    cache_name = "places:q:" + hashlib.sha256(f"{q}|{region}|{limit}".encode("utf-8")).hexdigest()[:24]
    hit = board_store.get_cache(table, cache_name)
    if hit and isinstance(hit.get("payload"), dict) and isinstance(hit["payload"].get("places"), list):
        return list(hit["payload"]["places"])
    _charge(table, settings, TEXT_SEARCH_USD, kind="search")
    payload = json.dumps(
        {"textQuery": q, "regionCode": region.upper(), "maxResultCount": limit}
    ).encode("utf-8")
    data = _http(
        "POST",
        TEXT_SEARCH_URL,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": _api_key(),
            "X-Goog-FieldMask": SEARCH_FIELD_MASK,
        },
        body=payload,
    )
    places = [_normalise_place(p) for p in (data.get("places") or []) if isinstance(p, dict)]
    board_store.put_cache(table, cache_name, {"places": places}, ttl_seconds=CACHE_TTL_SECONDS)
    for place in places:
        pid = place.get("placeId") or ""
        if pid:
            board_store.put_cache(table, f"places:id:{pid}", {"place": place}, ttl_seconds=CACHE_TTL_SECONDS)
    return places


def details(
    table: Any,
    place_id: str,
    *,
    settings: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    pid = str(place_id or "").strip()
    if not pid:
        raise PlacesError("place_id is required")
    cache_name = f"places:id:{pid}"
    if not force:
        hit = board_store.get_cache(table, cache_name)
        if hit and isinstance(hit.get("payload"), dict) and isinstance(hit["payload"].get("place"), dict):
            return dict(hit["payload"]["place"])
    _charge(table, settings, DETAILS_USD, kind="details")
    data = _http(
        "GET",
        DETAILS_URL.format(place_id=urllib.parse.quote(pid, safe="")),
        headers={"X-Goog-Api-Key": _api_key(), "X-Goog-FieldMask": FIELD_MASK},
    )
    place = _normalise_place(data)
    if not place.get("placeId"):
        place["placeId"] = pid
    board_store.put_cache(table, cache_name, {"place": place}, ttl_seconds=CACHE_TTL_SECONDS)
    return place
