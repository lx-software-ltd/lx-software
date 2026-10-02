"""Shared UTC clock and ISO-8601 helpers.

``now_iso`` matches ``board_store.now_iso`` (millisecond precision and a ``Z``
suffix). ``http_common._utc_iso_z`` formats an arbitrary datetime the same way.
Callers that persist second precision keep ``board_hk.to_iso``.

Tests freeze time by patching ``timeutil.datetime``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_iso_millis(dt: datetime) -> str:
    """UTC timestamp with millisecond precision and a ``Z`` suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    utc = dt.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def now_iso() -> str:
    return format_iso_millis(utc_now())


def parse_iso_strict(value: str) -> datetime:
    """Parse an ISO-8601 timestamp. Naive values are treated as UTC.

    ``Z`` is accepted. Raises ``ValueError`` when ``value`` is not a timestamp.
    """
    text = (value or "").strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp, or return ``None`` when it is missing or invalid."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return parse_iso_strict(text)
    except ValueError:
        return None
