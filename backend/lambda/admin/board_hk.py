"""Hong Kong civil time helpers. HKT is UTC+08:00 with no DST."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
    ("North", "North"),
    ("北區", "North"),
    ("Fanling", "North"),
    ("粉嶺", "North"),
    ("Sheung Shui", "North"),
    ("上水", "North"),
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
    ("Wan Chai", "Wan Chai"),
    ("灣仔", "Wan Chai"),
    ("Eastern", "Eastern"),
    ("東區", "Eastern"),
    ("Southern", "Southern"),
    ("南區", "Southern"),
)


def district_from_address(address: str) -> str:
    text = address or ""
    for token, district in HK_DISTRICTS:
        if token.lower() in text.lower() or token in text:
            return district
    return ""


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
