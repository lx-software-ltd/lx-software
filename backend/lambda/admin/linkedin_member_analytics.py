"""Profile-post totals from memberCreatorPostAnalytics.

Each metric is its own call. A missing count is read first. A post from the
last 7 days is read again every six hours, a post from day 8 through day 30
once a day, and an older stored count stays. A denied query is logged and not
retried. A count already read here is kept when a later social-actions read
runs.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import board_store
import linkedin_api
import linkedin_store
from http_common import _log_event
from linkedin_api import LinkedInApiError

_ANALYTICS_QUERIES = ("IMPRESSION", "REACTION", "COMMENT")
_READ_AT = {"IMPRESSION": "impressionReadAt", "REACTION": "reactionReadAt", "COMMENT": "commentReadAt"}
_CHECKED_AT = {
    "IMPRESSION": "impressionCheckedAt",
    "REACTION": "reactionCheckedAt",
    "COMMENT": "commentCheckedAt",
}
_DENIED = {"IMPRESSION": "impressionDenied", "REACTION": "reactionDenied", "COMMENT": "commentDenied"}
_COUNT_KEY = {"REACTION": "reactions", "COMMENT": "comments"}
_BOOKKEEPING = (
    "impressionCheckedAt",
    "impressionReadAt",
    "reactionCheckedAt",
    "reactionReadAt",
    "commentCheckedAt",
    "commentReadAt",
    "engagementReadAt",
    "engagementCheckedAt",
    "impressionDenied",
    "reactionDenied",
    "commentDenied",
)
_FRESH_DAYS = 7
_ACTIVE_DAYS = 30


def _platform(row: dict[str, Any]) -> dict[str, Any]:
    platform = row.get("platform")
    return _g if isinstance(_g := platform, dict) else {}


def _within(value: str, cutoff: datetime) -> bool:
    parsed = linkedin_store._parse_slot(value)
    return parsed is not None and parsed > cutoff


def _stamp(value: object) -> datetime | None:
    return linkedin_store._parse_slot(str(value or ""))


def _query_settled(previous: dict[str, Any], query: str) -> bool:
    """True when this metric was read or LinkedIn refused it."""
    if previous.get(_DENIED[query]) or previous.get(_READ_AT[query]):
        return True
    return query != "IMPRESSION" and bool(previous.get("engagementReadAt"))


def _analytics_queries(row: dict[str, Any], previous: dict[str, Any], now: datetime) -> set[str]:
    """Member metrics still due for this profile post. Empty means leave it."""
    checked = now - timedelta(hours=6)
    wanted: set[str] = set()
    for query in _ANALYTICS_QUERIES:
        if _query_settled(previous, query):
            continue
        checked_at = str(previous.get(_CHECKED_AT[query]) or "")
        if query != "IMPRESSION" and not checked_at:
            checked_at = str(previous.get("engagementCheckedAt") or "")
        if _within(checked_at, checked):
            continue
        if query == "IMPRESSION" and previous.get("impressions") is not None:
            continue
        wanted.add(query)
    if wanted:
        return wanted
    published = _stamp(_platform(row).get("publishedAt"))
    if published is None or now - published > timedelta(days=_ACTIVE_DAYS):
        return set()
    wait = timedelta(hours=6) if now - published <= timedelta(days=_FRESH_DAYS) else timedelta(days=1)
    read_at = [
        stamp
        for key in ("impressionReadAt", "reactionReadAt", "commentReadAt", "engagementReadAt")
        for stamp in (_stamp(previous.get(key)),)
        if stamp is not None
    ]
    if not read_at or now - min(read_at) >= wait:
        return {query for query in _ANALYTICS_QUERIES if not previous.get(_DENIED[query])}
    return set()


def _copy_bookkeeping(metrics: dict[str, Any], previous: dict[str, Any]) -> None:
    for key in _BOOKKEEPING:
        if previous.get(key):
            metrics[key] = previous[key]


def _analytics_carry(previous: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "pulledAt": str(previous.get("pulledAt") or ""),
        "unavailable": bool(previous.get("unavailable")),
    }
    if "impressions" in previous:
        metrics["impressions"] = previous.get("impressions")
    for key in ("reactions", "comments"):
        if key in previous and previous.get(key) is not None:
            metrics[key] = int(previous[key])
    _copy_bookkeeping(metrics, previous)
    if previous.get("error"):
        metrics["error"] = str(previous["error"])[:200]
    return metrics


def _mark_read(metrics: dict[str, Any], query: str, read_at: str) -> None:
    metrics[_READ_AT[query]] = read_at
    metrics.pop(_CHECKED_AT[query], None)
    metrics.pop(_DENIED[query], None)


def _mark_denied(metrics: dict[str, Any], query: str) -> None:
    metrics[_DENIED[query]] = True
    metrics.pop(_CHECKED_AT[query], None)
    metrics.pop(_READ_AT[query], None)


def _store_member_reads(
    metrics: dict[str, Any],
    previous: dict[str, Any],
    fresh: dict[str, int | None],
    outcomes: dict[str, str],
    read_at: str,
) -> None:
    for query, outcome in outcomes.items():
        if query == "IMPRESSION":
            if outcome == "ok":
                metrics["impressions"] = fresh[query]
                _mark_read(metrics, query, read_at)
            elif outcome == "denied":
                _mark_denied(metrics, query)
            else:
                if previous.get("impressions") is not None:
                    metrics["impressions"] = previous["impressions"]
                else:
                    metrics["impressions"] = None
                metrics[_CHECKED_AT[query]] = read_at
            continue
        key = _COUNT_KEY[query]
        if outcome == "ok":
            metrics[key] = fresh[query]
            _mark_read(metrics, query, read_at)
        elif outcome == "denied":
            _mark_denied(metrics, query)
        else:
            if previous.get(key) is not None:
                metrics[key] = int(previous[key])
            metrics[_CHECKED_AT[query]] = read_at
    if metrics.get("reactionReadAt") and metrics.get("commentReadAt"):
        if outcomes.get("REACTION") == "ok" or outcomes.get("COMMENT") == "ok":
            metrics["engagementReadAt"] = read_at
            metrics.pop("engagementCheckedAt", None)


def _read_member_analytics(
    metrics: dict[str, Any],
    previous: dict[str, Any],
    urn: str,
    token: str,
    wanted: set[str],
    allow: Any,
    denied_now: set[str],
) -> tuple[bool, bool]:
    """Read the wanted totals. Returns whether a post changed, and whether to stop profile reads."""
    fresh: dict[str, int | None] = {}
    outcomes: dict[str, str] = {}
    stamped = False
    capped = False
    for query in _ANALYTICS_QUERIES:
        if query not in wanted:
            continue
        if previous.get(_DENIED[query]) or query in denied_now:
            metrics[_DENIED[query]] = True
            stamped = True
            continue
        if allow is not None and not allow():
            capped = True
            break
        try:
            fresh[query] = linkedin_api.member_post_count(token, urn, query)
        except LinkedInApiError as exc:
            _log_event(
                "warning",
                tag="linkedin_metrics_failed",
                query=query,
                status=exc.status,
                error=str(exc)[:200],
            )
            fresh[query] = None
            if exc.status == 403:
                outcomes[query] = "denied"
                denied_now.add(query)
            else:
                outcomes[query] = "miss"
                if exc.status == 429:
                    capped = True
                    break
            continue
        outcomes[query] = "ok" if fresh[query] is not None else "miss"
    if outcomes:
        _store_member_reads(metrics, previous, fresh, outcomes, board_store.now_iso())
    return bool(fresh) or stamped, capped


def _analytics_count(previous: dict[str, Any], query: str) -> int | None:
    """A reaction or comment already read from the analytics app."""
    key = _COUNT_KEY[query]
    if previous.get(key) is None:
        return None
    if previous.get(_READ_AT[query]) or previous.get("engagementReadAt"):
        return int(previous[key])
    return None


def _social_metrics(previous: dict[str, Any], counts: dict[str, int]) -> dict[str, Any]:
    """Social-actions counts, keeping a reaction or comment the analytics app already read."""
    reactions = _analytics_count(previous, "REACTION")
    comments = _analytics_count(previous, "COMMENT")
    metrics: dict[str, Any] = {
        "reactions": counts["reactions"] if reactions is None else reactions,
        "comments": counts["comments"] if comments is None else comments,
        "impressions": previous.get("impressions") if "impressions" in previous else None,
        "pulledAt": board_store.now_iso(),
        "unavailable": False,
    }
    _copy_bookkeeping(metrics, previous)
    return metrics
