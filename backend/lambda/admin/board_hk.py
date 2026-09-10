"""Hong Kong civil time helpers. HKT is UTC+08:00 with no DST."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

HKT = timezone(timedelta(hours=8))


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
