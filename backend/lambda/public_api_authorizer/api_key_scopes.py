"""Public API key scopes and CIDR checks.

Kept next to the authorizer so mint (``scripts/manage-public-api-keys.py``)
and verify share one list. ``backend/lambda/admin/board_public_api.py``
duplicates the path-class rules that only the admin handler needs.
"""

from __future__ import annotations

import ipaddress
from typing import Any

SCOPE_FINANCE = "finance"
SCOPE_BOARD_OPS = "siutindei-board-ops"
SCOPE_BOARD_FULL = "siutindei-board-full"
SCOPE_PII = "siutindei-pii"
SCOPE_ASSETS = "siutindei-assets"

ALL_SCOPES = frozenset(
    {
        SCOPE_FINANCE,
        SCOPE_BOARD_OPS,
        SCOPE_BOARD_FULL,
        SCOPE_PII,
        SCOPE_ASSETS,
    }
)
LEGACY_READ_SCOPE = "read"


def normalize_scopes(item: dict[str, Any]) -> list[str]:
    """Return allowed scopes. Legacy ``scope=read`` is finance only."""
    raw = item.get("scopes")
    found: set[str] = set()
    if isinstance(raw, list):
        found.update(str(s).strip() for s in raw if str(s).strip() in ALL_SCOPES)
    elif isinstance(raw, str) and raw.strip():
        found.update(part.strip() for part in raw.split(",") if part.strip() in ALL_SCOPES)
    if found:
        return sorted(found)
    if item.get("scope") == LEGACY_READ_SCOPE:
        return [SCOPE_FINANCE]
    return []


def scopes_csv(scopes: list[str]) -> str:
    return ",".join(scopes)


def parse_cidrs(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for entry in raw:
        text = str(entry or "").strip()
        if not text:
            continue
        try:
            ipaddress.ip_network(text, strict=False)
        except ValueError:
            continue
        out.append(text)
    return out


def ip_allowed(source_ip: str, cidrs: list[str]) -> bool:
    """Fail closed when a CIDR list is set and the client IP is missing or outside it."""
    if not cidrs:
        return True
    text = (source_ip or "").strip()
    if not text:
        return False
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def source_ip_from_event(event: dict[str, Any]) -> str:
    http = (event.get("requestContext") or {}).get("http") or {}
    raw = http.get("sourceIp") or (event.get("requestContext") or {}).get("identity", {}).get("sourceIp")
    return str(raw or "").strip()
