"""Daily probe of the public home page. Maintenance mode explains a zero GA4 count."""

from __future__ import annotations

import re
from typing import Any

import board_crawl
import board_store

HOME_URL = "https://siutindei.com/"
CACHE_NAME = "web:site-live"
FAIL_TTL = 900
MAINTENANCE_TTL = 3600
LIVE_TTL = 86400
_GTM_RE = re.compile(r"GTM-[A-Z0-9]+")
MAINTENANCE_LINE = (
    "Public site is in pre-launch maintenance mode. GA4 reads zero until launch. "
    "Do not open tracking, conversion or ad-performance actions."
)


def for_context(table: Any) -> dict[str, Any]:
    return site_status(table)


def annotate(table: Any, result: dict[str, Any]) -> dict[str, Any]:
    status = site_status(table)
    if status.get("siteLive") is False:
        return {**result, "siteLive": False, "note": MAINTENANCE_LINE}
    return result


def site_status(table: Any) -> dict[str, Any]:
    if table is None:
        return {}
    hit = board_store.get_cache(table, CACHE_NAME)
    payload = hit.get("payload") if isinstance(hit, dict) else None
    if isinstance(payload, dict) and payload.get("probe") == "failed":
        return {}
    if isinstance(payload, dict) and "siteLive" in payload:
        return {"siteLive": bool(payload.get("siteLive")), "siteLiveReason": str(payload.get("siteLiveReason") or "")}
    probed = _probe()
    if probed is None:
        try:
            board_store.put_cache(table, CACHE_NAME, {"probe": "failed"}, ttl_seconds=FAIL_TTL)
        except Exception:
            return {}
        return {}
    ttl = LIVE_TTL if probed.get("siteLive") else MAINTENANCE_TTL
    try:
        board_store.put_cache(table, CACHE_NAME, probed, ttl_seconds=ttl)
    except Exception:
        return probed
    return probed


def _probe() -> dict[str, Any] | None:
    try:
        fetched = board_crawl.fetch(HOME_URL, timeout=8)
    except Exception:
        return None
    body = fetched.text or ""
    maintenance = "noindex" in body.lower() and _GTM_RE.search(body) is None
    if maintenance:
        return {"siteLive": False, "siteLiveReason": "pre-launch maintenance (noindex, no GTM)"}
    return {"siteLive": True, "siteLiveReason": ""}
