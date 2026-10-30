"""Refresh LinkedIn reaction, comment, and impression counts.

Profile impressions are read when the connection asked for member post
analytics. Posts already published are included at any age, including a share
or ugcPost URN taken from the pasted LinkedIn URL. A failed impression read is
remembered for six hours. A denied reaction read is stored and not retried.
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Any

import board_async
import board_store
import linkedin_api
import linkedin_store
from http_common import _log_event
from linkedin_api import LinkedInApiError
from linkedin_store import HKT

# Five reaction reads and fifteen impression backfills stay under the Lambda
# timeout when each LinkedIn call is allowed eight seconds.
REACTION_CAP = 5
BACKFILL_CAP = 15
POST_LIMIT = 400
_SHARE_URN = re.compile(r"urn:li:(?:share|ugcPost):\d+")
_ACTIVITY_URN = re.compile(r"urn:li:activity:(\d+)")
_ACTIVITY_SLUG = re.compile(r"activity-(\d+)")


def _platform(row: dict[str, Any]) -> dict[str, Any]:
    platform = row.get("platform")
    return platform if isinstance(platform, dict) else {}


def _previous(row: dict[str, Any]) -> dict[str, Any]:
    metrics = row.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _platform_text(platform: dict[str, Any]) -> str:
    return urllib.parse.unquote(f"{platform.get('urn') or ''} {platform.get('url') or ''}")


def _share_urn(platform: dict[str, Any]) -> str:
    stored = str(platform.get("urn") or "")
    if _SHARE_URN.fullmatch(stored):
        return stored
    found = _SHARE_URN.search(_platform_text(platform))
    return found.group(0) if found else ""


def _activity_urn(platform: dict[str, Any]) -> str:
    text = _platform_text(platform)
    found = _ACTIVITY_URN.search(text)
    if found:
        return f"urn:li:activity:{found.group(1)}"
    slug = _ACTIVITY_SLUG.search(text)
    if slug:
        return f"urn:li:activity:{slug.group(1)}"
    return ""


def _within(value: str, cutoff: datetime) -> bool:
    parsed = linkedin_store._parse_slot(value)
    return parsed is not None and parsed > cutoff


def _needs_impression(row: dict[str, Any], previous: dict[str, Any], include: bool, cutoff: datetime) -> bool:
    if not include or row.get("channel") == "page":
        return False
    if previous.get("impressions") is not None:
        return False
    return not _within(str(previous.get("impressionCheckedAt") or ""), cutoff)


def _reactions_due(platform: dict[str, Any], previous: dict[str, Any], oldest: datetime, cutoff: datetime) -> bool:
    if previous.get("unavailable"):
        return False
    published_at = linkedin_store._parse_slot(str(platform.get("publishedAt") or ""))
    if published_at is not None and published_at < oldest:
        return False
    return not _within(str(previous.get("pulledAt") or ""), cutoff)


def _carry(previous: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "reactions": int(previous.get("reactions") or 0),
        "comments": int(previous.get("comments") or 0),
        "impressions": previous.get("impressions") if "impressions" in previous else None,
        "pulledAt": str(previous.get("pulledAt") or ""),
        "unavailable": bool(previous.get("unavailable")),
    }
    if previous.get("error"):
        metrics["error"] = str(previous["error"])[:200]
    checked = str(previous.get("impressionCheckedAt") or "")
    if checked:
        metrics["impressionCheckedAt"] = checked
    return metrics


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


def _save(table: Any, row: dict[str, Any], metrics: dict[str, Any], share_urn: str) -> None:
    post_id = str(row["postId"])
    stored = str(_platform(row).get("urn") or "")
    if share_urn and share_urn != stored:
        doc = linkedin_store.get_post(table, post_id) or dict(row)
        doc["platform"] = {**_platform(doc), "urn": share_urn}
        doc["metrics"] = metrics
        linkedin_store.put_post(table, doc)
        return
    linkedin_store.save_post_metrics(table, post_id, metrics)


def _stamp_checked(table: Any, row: dict[str, Any], previous: dict[str, Any]) -> None:
    metrics = _carry(previous)
    metrics["impressionCheckedAt"] = board_store.now_iso()
    _save(table, row, metrics, "")


def refresh(table: Any, connection: dict[str, Any], token: str) -> int:
    now = datetime.now(HKT)
    cutoff = now - timedelta(hours=6)
    oldest = now - timedelta(days=30)
    include = bool(connection.get("includeMemberAnalytics"))
    rows = linkedin_store.list_posts(table, status="published", limit=POST_LIMIT)
    rows.sort(
        key=lambda row: (
            0 if _needs_impression(row, _previous(row), include, cutoff) else 1,
            str(_platform(row).get("publishedAt") or row.get("slotAt") or ""),
        )
    )
    reactions_done = 0
    backfill_done = 0
    updated = 0
    for row in rows:
        if reactions_done >= REACTION_CAP and backfill_done >= BACKFILL_CAP:
            break
        platform = _platform(row)
        previous = _previous(row)
        needs = _needs_impression(row, previous, include, cutoff)
        urn = _share_urn(platform)
        if needs and not urn and backfill_done < BACKFILL_CAP:
            activity = _activity_urn(platform)
            if activity:
                urn = linkedin_api.resolve_share_urn(token, activity)
                if not urn:
                    _stamp_checked(table, row, previous)
                    backfill_done += 1
                    updated += 1
                    continue
        usable = urn or str(platform.get("urn") or "")
        do_reactions = (
            bool(usable) and _reactions_due(platform, previous, oldest, cutoff) and reactions_done < REACTION_CAP
        )
        do_backfill = needs and backfill_done < BACKFILL_CAP
        if (not do_reactions and not do_backfill) or not usable:
            continue
        metrics = _carry(previous)
        if do_reactions:
            try:
                counts = linkedin_api.social_counts(token, usable)
            except LinkedInApiError as exc:
                _log_event("warning", tag="linkedin_metrics_failed", error=str(exc)[:200])
                metrics["pulledAt"] = board_store.now_iso()
                metrics["unavailable"] = exc.status == 403
                metrics["error"] = str(exc)[:200]
            else:
                metrics = {
                    "reactions": counts["reactions"],
                    "comments": counts["comments"],
                    "impressions": previous.get("impressions") if "impressions" in previous else None,
                    "pulledAt": board_store.now_iso(),
                    "unavailable": False,
                }
        try:
            metrics["impressions"] = _impressions(
                token,
                row,
                platform,
                usable,
                include_member_analytics=include,
            )
        except LinkedInApiError as exc:
            _log_event("warning", tag="linkedin_metrics_failed", error=str(exc)[:200])
        if do_backfill and metrics.get("impressions") is None:
            metrics["impressionCheckedAt"] = board_store.now_iso()
        elif metrics.get("impressions") is not None:
            metrics.pop("impressionCheckedAt", None)
        _save(table, row, metrics, urn)
        updated += 1
        if do_reactions:
            reactions_done += 1
        if do_backfill:
            backfill_done += 1
    return updated


def refresh_connected(table: Any) -> dict[str, Any]:
    """Refresh the saved connection. A failure is logged and does not raise."""
    try:
        import linkedin

        fresh = linkedin_store.load_connection(table)
        if not fresh:
            return {"ok": True, "refreshed": 0}
        refreshed = refresh(table, fresh, linkedin._access_token(table, fresh))
    except Exception as exc:  # noqa: BLE001 — metrics must not fail publishing or the reminder
        _log_event("warning", tag="linkedin_metrics_failed", error=str(exc)[:240])
        return {"ok": False, "refreshed": 0}
    return {"ok": True, "refreshed": refreshed}


def queue_backfill(include_member_analytics: bool) -> None:
    """Fill impressions on the worker so the OAuth response stays short."""
    if include_member_analytics:
        board_async.try_invoke_event({"internal": "linkedin_publish_due", "metricsOnly": True})
