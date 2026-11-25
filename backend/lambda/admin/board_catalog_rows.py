"""Facts copied onto a catalog describe row, and generic host-root URLs."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def generic_host_root(url: str) -> bool:
    """True for a host with no path, such as ``https://lcsd.gov.hk/``."""
    parsed = urlparse(str(url or "").strip())
    if not parsed.netloc:
        return False
    return (parsed.path or "") in ("", "/") and not parsed.query


def describe_candidate(cand: dict[str, Any], name: str, url: str) -> dict[str, str]:
    """Name and URL plus address, phone and coordinates already on the record."""
    row = {"name": name, "url": url}
    address = str(cand.get("addressEn") or cand.get("address") or "").strip()
    phone = str(cand.get("phone") or "").strip()
    if address:
        row["address"] = address[:200]
    if phone:
        row["phone"] = phone[:40]
    if cand.get("lat") not in (None, ""):
        row["lat"] = str(cand.get("lat"))
    if cand.get("lng") not in (None, ""):
        row["lng"] = str(cand.get("lng"))
    return row
