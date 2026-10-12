"""Neighbourhood-first go-live: which areas and districts the catalog works first.

The owner launches one neighbourhood at a time (Stanley, then the rest of
Southern, then Hong Kong Island, then everywhere). ``settings.catalog.focusAreas``
names the current neighbourhood(s) from ``AREAS``; when the key is absent
``FOCUS_AREAS_DEFAULT`` applies, and an explicit empty list means "no focus"
(the plain 18-district rotation). ``settings.catalog.focusDistricts`` adds
whole districts after the areas; when that key is absent ``DEFAULT_FOCUS_DISTRICTS``
(the go-live order: Southern, the rest of Hong Kong Island, then everywhere)
applies. Every catalog surface asks this module for order and membership so the
rule lives in one place.

The area list, the default focus, the district order and the discovery queries
are Python constants here rather than ``contracts/board-staff.json`` so this
change stays in the Lambda; moving them to the contract is a separate owner
decision.
"""

from __future__ import annotations

import math
import re
from typing import Any

import board_hk
from contract_constants import BOARD_CATALOG_DISTRICTS

_WORD = re.compile(r"[a-z0-9]+")

# Neighbourhoods with a centre + radius (metres) so a Places result can be placed
# without an LLM. ``district`` is the canonical board district name.
AREAS: tuple[dict[str, Any], ...] = (
    {"id": "stanley", "name": "Stanley", "nameZh": "赤柱", "district": "Southern", "lat": 22.2185, "lng": 114.2125, "radius": 2500,
     "aliases": ["Chung Hom Kok", "舂坎角", "Tai Tam", "大潭", "Red Hill", "紅山", "Stanley Plaza", "赤柱廣場"]},
    {"id": "repulse-bay", "name": "Repulse Bay", "nameZh": "淺水灣", "district": "Southern", "lat": 22.236, "lng": 114.196, "radius": 2000,
     "aliases": ["Deep Water Bay", "深水灣", "Middle Bay", "South Bay"]},
    {"id": "shek-o", "name": "Shek O", "nameZh": "石澳", "district": "Southern", "lat": 22.23, "lng": 114.25, "radius": 2000,
     "aliases": ["Big Wave Bay", "大浪灣"]},
    {"id": "wong-chuk-hang", "name": "Wong Chuk Hang", "nameZh": "黃竹坑", "district": "Southern", "lat": 22.248, "lng": 114.173, "radius": 1300,
     "aliases": ["Ocean Park", "海洋公園", "Shouson Hill", "壽臣山"]},
    {"id": "aberdeen", "name": "Aberdeen", "nameZh": "香港仔", "district": "Southern", "lat": 22.248, "lng": 114.155, "radius": 1500,
     "aliases": ["Tin Wan", "田灣", "Shek Pai Wan", "石排灣"]},
    {"id": "ap-lei-chau", "name": "Ap Lei Chau", "nameZh": "鴨脷洲", "district": "Southern", "lat": 22.242, "lng": 114.155, "radius": 1200,
     "aliases": ["South Horizons", "海怡半島", "Lei Tung", "利東"]},
    {"id": "pok-fu-lam", "name": "Pok Fu Lam", "nameZh": "薄扶林", "district": "Southern", "lat": 22.265, "lng": 114.133, "radius": 2500,
     "aliases": ["Cyberport", "數碼港", "Wah Fu", "華富", "Chi Fu", "置富"]},
    {"id": "central", "name": "Central", "nameZh": "中環", "district": "Central and Western", "lat": 22.2819, "lng": 114.1582, "radius": 1200,
     "aliases": ["Admiralty", "金鐘", "Mid-Levels", "半山", "SoHo"]},
    {"id": "sheung-wan", "name": "Sheung Wan", "nameZh": "上環", "district": "Central and Western", "lat": 22.2868, "lng": 114.15, "radius": 900,
     "aliases": []},
    {"id": "sai-ying-pun", "name": "Sai Ying Pun", "nameZh": "西營盤", "district": "Central and Western", "lat": 22.2866, "lng": 114.142, "radius": 900,
     "aliases": ["Shek Tong Tsui", "石塘咀"]},
    {"id": "kennedy-town", "name": "Kennedy Town", "nameZh": "堅尼地城", "district": "Central and Western", "lat": 22.2812, "lng": 114.1278, "radius": 1200,
     "aliases": []},
    {"id": "the-peak", "name": "The Peak", "nameZh": "山頂", "district": "Central and Western", "lat": 22.2708, "lng": 114.15, "radius": 1500,
     "aliases": ["Victoria Peak"]},
    {"id": "wan-chai", "name": "Wan Chai", "nameZh": "灣仔", "district": "Wan Chai", "lat": 22.2775, "lng": 114.1725, "radius": 1200,
     "aliases": []},
    {"id": "causeway-bay", "name": "Causeway Bay", "nameZh": "銅鑼灣", "district": "Wan Chai", "lat": 22.28, "lng": 114.186, "radius": 1100,
     "aliases": []},
    {"id": "happy-valley", "name": "Happy Valley", "nameZh": "跑馬地", "district": "Wan Chai", "lat": 22.269, "lng": 114.183, "radius": 1300,
     "aliases": ["Tai Hang", "大坑"]},
    {"id": "north-point", "name": "North Point", "nameZh": "北角", "district": "Eastern", "lat": 22.291, "lng": 114.196, "radius": 1300,
     "aliases": ["Fortress Hill", "炮台山"]},
    {"id": "quarry-bay", "name": "Quarry Bay", "nameZh": "鰂魚涌", "district": "Eastern", "lat": 22.287, "lng": 114.213, "radius": 1200,
     "aliases": ["Tai Koo", "太古", "Taikoo"]},
    {"id": "sai-wan-ho", "name": "Sai Wan Ho", "nameZh": "西灣河", "district": "Eastern", "lat": 22.2825, "lng": 114.222, "radius": 900,
     "aliases": []},
    {"id": "shau-kei-wan", "name": "Shau Kei Wan", "nameZh": "筲箕灣", "district": "Eastern", "lat": 22.279, "lng": 114.23, "radius": 1300,
     "aliases": ["Heng Fa Chuen", "杏花邨"]},
    {"id": "chai-wan", "name": "Chai Wan", "nameZh": "柴灣", "district": "Eastern", "lat": 22.264, "lng": 114.237, "radius": 1800,
     "aliases": ["Siu Sai Wan", "小西灣"]},
)

# The neighbourhood the owner goes live with first.
FOCUS_AREAS_DEFAULT: tuple[str, ...] = ("stanley",)

# Go-live order: Southern, the rest of Hong Kong Island, then everywhere. Applied
# when ``settings.catalog.focusDistricts`` is absent; an explicit ``[]`` keeps
# the contract order.
DEFAULT_FOCUS_DISTRICTS: tuple[str, ...] = (
    "Southern",
    "Central and Western",
    "Wan Chai",
    "Eastern",
)

# Places text searches run inside each focus area circle (query, facility kind).
FOCUS_QUERIES: tuple[tuple[str, str], ...] = (
    ("kids activities", "places_class"),
    ("children's classes", "places_class"),
    ("kids art class", "places_class"),
    ("children music lessons", "places_class"),
    ("kids dance class", "places_class"),
    ("children drama class", "places_class"),
    ("kids coding STEM class", "places_class"),
    ("children language centre", "places_class"),
    ("playgroup toddlers", "places_class"),
    ("kids swimming lessons", "places_sport"),
    ("children sports club", "places_sport"),
    ("kids martial arts", "places_sport"),
    ("children gymnastics", "places_sport"),
    ("kids tennis lessons", "places_sport"),
    ("indoor playground kids", "places_amusement"),
    ("children playground", "places_playground"),
    ("public library", "places_library"),
)

# Facility kinds that only focus discovery produces; the contract maps the rest.
FOCUS_KIND_CATEGORY: dict[str, str] = {"places_class": "Class", "places_sport": "Sport"}

# Owner-added rows (``POST /catalog/candidates``) are their own bulk source.
MANUAL_SOURCE = "manual"


def areas() -> list[dict[str, Any]]:
    return [row for row in AREAS if isinstance(row, dict) and row.get("id")]


def area_by_id(area_id: str) -> dict[str, Any] | None:
    wanted = str(area_id or "").strip().lower()
    for row in areas():
        if str(row.get("id") or "").lower() == wanted:
            return row
    return None


def _catalog(settings: dict[str, Any] | None) -> dict[str, Any]:
    catalog = (settings or {}).get("catalog") if isinstance(settings, dict) else None
    return catalog if isinstance(catalog, dict) else {}


def focus_area_ids(settings: dict[str, Any] | None) -> list[str]:
    """Owner list when the key is present (empty = no focus), else the contract default."""
    catalog = _catalog(settings)
    if "focusAreas" in catalog:
        raw = catalog.get("focusAreas")
        ids = [str(a).strip().lower() for a in (raw if isinstance(raw, list) else []) if str(a).strip()]
    else:
        ids = [str(a).strip().lower() for a in FOCUS_AREAS_DEFAULT]
    out: list[str] = []
    for aid in ids:
        if aid not in out and area_by_id(aid):
            out.append(aid)
    return out


def focus_areas(settings: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = [area_by_id(aid) for aid in focus_area_ids(settings)]
    return [row for row in rows if row]


def focus_district_names(settings: dict[str, Any] | None) -> list[str]:
    """Districts that count as *in focus*: the focus areas' districts, then an
    explicit ``focusDistricts`` list. Membership (auto-approve, launch-gate
    bypass, discovery sweep) uses this; the default go-live order does not
    widen it, see :func:`priority_district_names`.
    """
    out: list[str] = []
    for area in focus_areas(settings):
        name = board_hk.canonical_district(str(area.get("district") or ""))
        if name != "unknown" and name not in out:
            out.append(name)
    raw = _catalog(settings).get("focusDistricts")
    for value in raw if isinstance(raw, list) else []:
        name = board_hk.canonical_district(str(value or ""))
        if name != "unknown" and name not in out:
            out.append(name)
    return out


def priority_district_names(settings: dict[str, Any] | None) -> list[str]:
    """Rotation order: focus districts, then ``DEFAULT_FOCUS_DISTRICTS`` unless the
    owner set ``focusDistricts`` (an explicit ``[]`` keeps the contract order)."""
    out = focus_district_names(settings)
    if "focusDistricts" in _catalog(settings):
        return out
    for value in DEFAULT_FOCUS_DISTRICTS:
        name = board_hk.canonical_district(value)
        if name != "unknown" and name not in out:
            out.append(name)
    return out


def has_focus(settings: dict[str, Any] | None) -> bool:
    return bool(focus_area_ids(settings)) or bool(focus_district_names(settings))


def focus_label(settings: dict[str, Any] | None) -> str:
    parts = [f"{a.get('name')} ({a.get('district')})" for a in focus_areas(settings)]
    if not parts:
        parts = focus_district_names(settings)
    return ", ".join(parts)


def order_districts(
    rows: list[dict[str, Any]] | None = None,
    settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Contract districts with the priority districts moved to the front, in go-live order."""
    source = [row for row in (rows if rows is not None else BOARD_CATALOG_DISTRICTS) if isinstance(row, dict)]
    first = priority_district_names(settings)
    if not first:
        return source
    head: list[dict[str, Any]] = []
    for name in first:
        for row in source:
            if str(row.get("name") or "") == name and row not in head:
                head.append(row)
    return head + [row for row in source if row not in head]


def order_district_names(names: list[str], settings: dict[str, Any] | None = None) -> list[str]:
    first = [n for n in priority_district_names(settings) if n in names]
    return first + [n for n in names if n not in first]


def _metres(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _name_in_text(name: str, text: str) -> bool:
    marker = str(name or "").strip()
    if not marker:
        return False
    if any(ord(ch) > 127 for ch in marker):
        return marker in text
    pattern = r"(?<![a-z0-9])" + r"[\s\-]*".join(re.escape(w) for w in _WORD.findall(marker.lower())) + r"(?![a-z0-9])"
    return re.search(pattern, text.lower()) is not None


# Street names that contain a neighbourhood name but sit elsewhere.
_FALSE_FRIENDS = re.compile(r"stanley\s+st(?:reet)?\b|士丹利街", re.I)


def area_from_text(text: str) -> str:
    """Area id named in an address or description (English or Chinese), else ``""``."""
    blob = _FALSE_FRIENDS.sub(" ", str(text or ""))
    if not blob.strip():
        return ""
    for row in areas():
        names = [str(row.get("name") or ""), str(row.get("nameZh") or "")]
        names.extend(str(a) for a in (row.get("aliases") or []))
        if any(_name_in_text(n, blob) for n in names if n):
            return str(row["id"])
    return ""


def area_from_point(lat: Any, lng: Any) -> str:
    """Area whose circle contains the point (nearest centre wins on overlap), else ``""``."""
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return ""
    best: tuple[float, str] | None = None
    for row in areas():
        try:
            c_lat = float(row.get("lat"))
            c_lng = float(row.get("lng"))
            radius = float(row.get("radius") or 0)
        except (TypeError, ValueError):
            continue
        d = _metres(lat_f, lng_f, c_lat, c_lng)
        if radius > 0 and d <= radius and (best is None or d < best[0]):
            best = (d, str(row["id"]))
    return best[1] if best else ""


def area_for(row: dict[str, Any]) -> str:
    """Stored ``area`` when valid, else the address text, else the lat/lng circle."""
    stored = str(row.get("area") or "").strip().lower()
    if stored and area_by_id(stored):
        return stored
    district = board_hk.canonical_district(str(row.get("district") or "")) if row.get("district") else "unknown"

    def consistent(area_id: str) -> bool:
        area = area_by_id(area_id)
        if not area:
            return False
        return district == "unknown" or str(area.get("district") or "") == district

    text = " ".join(
        str(row.get(key) or "")
        for key in ("addressEn", "address", "addressZh", "nameEn", "nameZh", "name")
    )
    found = area_from_text(text)
    if found and consistent(found):
        return found
    point = area_from_point(row.get("lat"), row.get("lng"))
    return point if point and consistent(point) else ""


def is_focus_row(row: dict[str, Any], settings: dict[str, Any] | None) -> bool:
    """True when the candidate sits in a focus area (or, with district-only focus, in that district)."""
    ids = focus_area_ids(settings)
    if ids:
        return area_for(row) in ids
    districts = focus_district_names(settings)
    if not districts:
        return False
    return board_hk.canonical_district(str(row.get("district") or "")) in districts


def focus_queries() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for query, kind in FOCUS_QUERIES:
        text = " ".join(str(query or "").split())
        if text:
            out.append((text, str(kind or "places_class").strip()))
    return out


def category_for_kind(kind: str) -> str:
    """Category for a facility kind that only focus discovery produces, else ``""``."""
    return FOCUS_KIND_CATEGORY.get(str(kind or "").strip(), "")


def normalize_focus_settings(raw: dict[str, Any], out: dict[str, Any], *, strict: bool = False) -> None:
    """Copy ``focusAreas`` / ``focusDistricts`` from ``raw`` into ``out``.

    ``strict`` (owner PUT) rejects unknown ids; the load path drops them so a
    contract edit cannot break settings. ``null`` removes the key, which
    returns that list to the contract default; ``[]`` is an explicit no-focus.
    """
    if "focusAreas" in raw and raw.get("focusAreas") is not None:
        value = raw.get("focusAreas")
        if value == "":
            value = []
        if not isinstance(value, list):
            raise ValueError("catalog.focusAreas must be a list of area ids")
        ids: list[str] = []
        for item in value:
            aid = str(item or "").strip().lower()
            if not aid:
                continue
            if not area_by_id(aid):
                if strict:
                    raise ValueError(f"unknown catalog area {aid}")
                continue
            if aid not in ids:
                ids.append(aid)
        out["focusAreas"] = ids
    if "focusDistricts" in raw and raw.get("focusDistricts") is not None:
        value = raw.get("focusDistricts")
        if value == "":
            value = []
        if not isinstance(value, list):
            raise ValueError("catalog.focusDistricts must be a list of district names")
        names: list[str] = []
        for item in value:
            name = board_hk.canonical_district(str(item or ""))
            if name == "unknown":
                if strict:
                    raise ValueError(f"unknown catalog district {item}")
                continue
            if name not in names:
                names.append(name)
        out["focusDistricts"] = names


def brief_paragraph(area: dict[str, Any]) -> str:
    """Sentence for a neighbourhood sheet brief."""
    aliases = [str(x) for x in (area.get("aliases") or []) if not any(ord(ch) > 127 for ch in str(x))]
    label = str(area.get("name") or "")
    if aliases:
        label += " (incl. " + ", ".join(aliases[:4]) + ")"
    return (
        "FOCUS — the go-live plan is neighbourhood by neighbourhood: every organisation on this "
        f"sheet must be physically in {label}. Skip the rest of the district. "
        "Prefer classes, clubs and playgroups that run there weekly over venues that already appear "
        "on LCSD pages. "
    )
