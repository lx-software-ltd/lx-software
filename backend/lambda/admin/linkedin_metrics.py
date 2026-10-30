"""Refresh reaction, comment, and impression counts for recent LinkedIn posts.

Profile impressions are read only when the connection asked for member post
analytics. A failed impression read leaves the count empty. A denied reaction
read is stored and not retried.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import board_store
import linkedin_api
import linkedin_store
from http_common import _log_event
from linkedin_api import LinkedInApiError
from linkedin_store import HKT


def _impressions(
    token: str,
    row: dict[str, Any],
    platform: dict[str, Any],
    urn: str,
    *,
    include_member_analytics: bool,
) -> int | None:
    organization_id = str(platform.get("organizationId") or "")
    if row.get("channel") == "page" and organization_id:
        return linkedin_api.page_impressions(token, organization_id, urn)
    if include_member_analytics:
        return linkedin_api.member_impressions(token, urn)
    return None


def refresh(table: Any, connection: dict[str, Any], token: str) -> int:
    now = datetime.now(HKT)
    cutoff = now - timedelta(hours=6)
    oldest = now - timedelta(days=30)
    include_member_analytics = bool(connection.get("includeMemberAnalytics"))
    refreshed = 0
    for row in linkedin_store.list_posts(table, status="published", limit=80):
        if refreshed >= 5:
            break
        platform = row.get("platform") if isinstance(row.get("platform"), dict) else {}
        urn = str(platform.get("urn") or "")
        if not urn:
            continue
        published_at = linkedin_store._parse_slot(str(platform.get("publishedAt") or ""))
        if published_at is not None and published_at < oldest:
            continue
        previous = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        if previous.get("unavailable"):
            continue
        pulled = linkedin_store._parse_slot(str(previous.get("pulledAt") or ""))
        if pulled is not None and pulled > cutoff:
            continue
        try:
            counts = linkedin_api.social_counts(token, urn)
            metrics = {
                "reactions": counts["reactions"],
                "comments": counts["comments"],
                "impressions": _impressions(
                    token,
                    row,
                    platform,
                    urn,
                    include_member_analytics=include_member_analytics,
                ),
                "pulledAt": board_store.now_iso(),
                "unavailable": False,
            }
        except LinkedInApiError as exc:
            _log_event("warning", tag="linkedin_metrics_failed", error=str(exc)[:200])
            metrics = {
                "reactions": int(previous.get("reactions") or 0),
                "comments": int(previous.get("comments") or 0),
                "impressions": previous.get("impressions") if "impressions" in previous else None,
                "pulledAt": board_store.now_iso(),
                "unavailable": exc.status == 403,
                "error": str(exc)[:200],
            }
        linkedin_store.save_post_metrics(table, str(row["postId"]), metrics)
        refreshed += 1
    return refreshed
