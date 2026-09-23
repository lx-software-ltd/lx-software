"""Hong Kong civil time helpers. HKT is UTC+08:00 with no DST."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import unquote, urlparse

HKT = timezone(timedelta(hours=8))

# District keywords used to map a Hong Kong address to an 18-district label.
# Longer / more specific tokens are matched first.
HK_DISTRICTS: tuple[tuple[str, str], ...] = (
    ("Sai Kung", "Sai Kung"),
    ("西貢", "Sai Kung"),
    ("Tseung Kwan O", "Sai Kung"),
    ("將軍澳", "Sai Kung"),
    ("Sha Tin", "Sha Tin"),
    ("沙田", "Sha Tin"),
    ("Tai Po", "Tai Po"),
    ("大埔", "Tai Po"),
    ("North Point", "Eastern"),
    ("北角", "Eastern"),
    ("North", "North"),
    ("北區", "North"),
    ("Fanling", "North"),
    ("粉嶺", "North"),
    ("Sheung Shui", "North"),
    ("上水", "North"),
    ("Quarry Bay", "Eastern"),
    ("鰂魚涌", "Eastern"),
    ("Sai Wan Ho", "Eastern"),
    ("西灣河", "Eastern"),
    ("Shau Kei Wan", "Eastern"),
    ("筲箕灣", "Eastern"),
    ("Chai Wan", "Eastern"),
    ("柴灣", "Eastern"),
    ("Fortress Hill", "Eastern"),
    ("炮台山", "Eastern"),
    ("Tin Hau", "Eastern"),
    ("天后", "Eastern"),
    ("Kennedy Town", "Central and Western"),
    ("堅尼地城", "Central and Western"),
    ("Sai Ying Pun", "Central and Western"),
    ("西營盤", "Central and Western"),
    ("Sheung Wan", "Central and Western"),
    ("上環", "Central and Western"),
    ("Admiralty", "Central and Western"),
    ("金鐘", "Central and Western"),
    ("Mid-Levels", "Central and Western"),
    ("半山", "Central and Western"),
    ("The Peak", "Central and Western"),
    ("山頂", "Central and Western"),
    ("Aberdeen", "Southern"),
    ("香港仔", "Southern"),
    ("Ap Lei Chau", "Southern"),
    ("鴨脷洲", "Southern"),
    ("Wong Chuk Hang", "Southern"),
    ("黃竹坑", "Southern"),
    ("Stanley", "Southern"),
    ("赤柱", "Southern"),
    ("Repulse Bay", "Southern"),
    ("淺水灣", "Southern"),
    ("Yuen Long", "Yuen Long"),
    ("元朗", "Yuen Long"),
    ("Tuen Mun", "Tuen Mun"),
    ("屯門", "Tuen Mun"),
    ("Tsuen Wan", "Tsuen Wan"),
    ("荃灣", "Tsuen Wan"),
    ("Kwai Tsing", "Kwai Tsing"),
    ("葵青", "Kwai Tsing"),
    ("Kwai Chung", "Kwai Tsing"),
    ("葵涌", "Kwai Tsing"),
    ("Tsing Yi", "Kwai Tsing"),
    ("青衣", "Kwai Tsing"),
    ("Islands", "Islands"),
    ("離島", "Islands"),
    ("Discovery Bay", "Islands"),
    ("愉景灣", "Islands"),
    ("Tung Chung", "Islands"),
    ("東涌", "Islands"),
    ("Kwun Tong", "Kwun Tong"),
    ("觀塘", "Kwun Tong"),
    ("Wong Tai Sin", "Wong Tai Sin"),
    ("黃大仙", "Wong Tai Sin"),
    ("Kowloon City", "Kowloon City"),
    ("九龍城", "Kowloon City"),
    ("Sham Shui Po", "Sham Shui Po"),
    ("深水埗", "Sham Shui Po"),
    ("Yau Tsim Mong", "Yau Tsim Mong"),
    ("油尖旺", "Yau Tsim Mong"),
    ("Mong Kok", "Yau Tsim Mong"),
    ("旺角", "Yau Tsim Mong"),
    ("Tsim Sha Tsui", "Yau Tsim Mong"),
    ("尖沙咀", "Yau Tsim Mong"),
    ("Yau Ma Tei", "Yau Tsim Mong"),
    ("油麻地", "Yau Tsim Mong"),
    ("Central and Western", "Central and Western"),
    ("中西區", "Central and Western"),
    ("Central", "Central and Western"),
    ("中環", "Central and Western"),
    ("Causeway Bay", "Wan Chai"),
    ("銅鑼灣", "Wan Chai"),
    ("Wan Chai", "Wan Chai"),
    ("灣仔", "Wan Chai"),
    ("Eastern", "Eastern"),
    ("東區", "Eastern"),
    ("Southern", "Southern"),
    ("南區", "Southern"),
)


# Approximate district centres for Places locationBias circles (WGS84).
DISTRICT_CENTERS: dict[str, tuple[float, float, int]] = {
    "Eastern": (22.284, 114.224, 7000),
    "Wan Chai": (22.277, 114.173, 4500),
    "Central and Western": (22.282, 114.145, 5000),
    "Southern": (22.247, 114.168, 8000),
    "Islands": (22.288, 113.943, 15000),
    "Kwun Tong": (22.313, 114.226, 5500),
    "Wong Tai Sin": (22.342, 114.195, 5000),
    "Kowloon City": (22.328, 114.188, 5000),
    "Sham Shui Po": (22.331, 114.162, 5000),
    "Yau Tsim Mong": (22.307, 114.171, 4500),
    "Sha Tin": (22.382, 114.190, 8000),
    "Tai Po": (22.451, 114.165, 8000),
    "North": (22.495, 114.138, 10000),
    "Tsuen Wan": (22.372, 114.115, 6000),
    "Kwai Tsing": (22.357, 114.128, 6000),
    "Tuen Mun": (22.392, 113.973, 8000),
    "Yuen Long": (22.445, 114.022, 8000),
    "Sai Kung": (22.382, 114.271, 10000),
}


def district_center(name: str) -> tuple[float, float, int] | None:
    return DISTRICT_CENTERS.get(name)


def district_from_address(address: str) -> str:
    text = address or ""
    for token, district in HK_DISTRICTS:
        if token.lower() in text.lower() or token in text:
            return district
    return "unknown"


def districts_named_in_address(address: str) -> list[str]:
    """Districts named in an address, longest token first and non-overlapping.

    ``North Point`` is Eastern only; the shorter token ``North`` does not also
    match inside it. ``Central Plaza, Wan Chai`` names both Central and Western
    and Wan Chai, so a caller can keep the claimed district when it is one of them.
    """
    text = address or ""
    if not text:
        return []
    lower = text.lower()
    occupied = [False] * len(text)
    found: list[str] = []
    tokens = sorted(HK_DISTRICTS, key=lambda pair: len(pair[0]), reverse=True)
    for token, district in tokens:
        needle = token.lower()
        if not needle:
            continue
        start = 0
        while True:
            idx = lower.find(needle, start)
            if idx < 0:
                break
            end = idx + len(needle)
            if any(occupied[idx:end]):
                start = idx + 1
                continue
            for pos in range(idx, end):
                occupied[pos] = True
            if district not in found:
                found.append(district)
            start = end
    return found


def _metres_between(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    haversine = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lng / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(haversine)))


def district_containing_point(lat: Any, lng: Any) -> str | None:
    """The district whose centre radius contains the point, when exactly one does.

    Overlapping circles (dense Kowloon) return None so a caller does not guess.
    """
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lat_f) or not math.isfinite(lng_f):
        return None
    hits: list[str] = []
    for name, (centre_lat, centre_lng, radius_m) in DISTRICT_CENTERS.items():
        if _metres_between(lat_f, lng_f, centre_lat, centre_lng) <= radius_m:
            hits.append(name)
    if len(hits) == 1:
        return hits[0]
    return None


def canonical_district(value: str) -> str:
    """Map a label, alias or slug to an 18-district name, else ``unknown``."""
    text = (value or "").strip()
    if not text:
        return "unknown"
    keyed = {name.lower(): name for name in DISTRICT_CENTERS}
    if text.lower() in keyed:
        return keyed[text.lower()]
    return district_from_address(text.replace("_", " ").replace("-", " "))


def district_from_url(url: str) -> str:
    """Guess a district from path slugs such as ``/activities/area/tung_chung``."""
    parsed = urlparse(url or "")
    parts: list[str] = []
    for seg in unquote(parsed.path or "").split("/"):
        if seg:
            parts.append(seg.replace("-", " ").replace("_", " "))
    query = unquote(parsed.query or "").replace("&", " ").replace("=", " ").replace("+", " ")
    if query:
        parts.append(query)
    return district_from_address(" ".join(parts))


def is_hk_address(address: str) -> bool:
    """True when an address looks like it is in Hong Kong."""
    text = (address or "").strip()
    if not text:
        return False
    lower = text.lower()
    if "hong kong" in lower or "hongkong" in lower or "香港" in text:
        return True
    return district_from_address(text) != "unknown"


def parse_iso(value: str) -> datetime:
    text = (value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def as_hkt(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(HKT)


def in_quiet_hours(dt: datetime, start_hour: int, end_hour: int) -> bool:
    """True when ``dt`` falls in ``[start_hour, end_hour)`` HKT, wrapping midnight."""
    hour = as_hkt(dt).hour
    start_hour = int(start_hour) % 24
    end_hour = int(end_hour) % 24
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def next_hour_hkt(dt: datetime, hour: int) -> datetime:
    """Next occurrence of ``hour:00`` HKT at or after ``dt``, returned in UTC."""
    local = as_hkt(dt)
    candidate = local.replace(hour=int(hour) % 24, minute=0, second=0, microsecond=0)
    if local >= candidate:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    utc = dt.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_hkt() -> datetime:
    return as_hkt(datetime.now(timezone.utc))


def today_hkt() -> str:
    return now_hkt().date().isoformat()
