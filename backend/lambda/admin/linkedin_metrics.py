"""Refresh LinkedIn reaction, comment, and impression counts.

Profile impressions, reactions, and comments use the analytics app when that
connection exists. Each metric is its own call. A missing count is read first,
newest post first. A post from the last 7 days is read again every six hours, a
post from day 8 through day 30 once a day, and an older stored count stays. The
daily analytics cap skips later profile reads and still refreshes page posts.
A denied member-analytics query is logged and not retried. A posting connection
that already asked for member post analytics still reads impressions on its own
token, and its reactions still come from social actions for the last 30 days.
Posts already published are included at any age, including a share or ugcPost URN
taken from the pasted LinkedIn URL. A failed read keeps a count already stored.
A count read from the analytics app is kept when analytics is later disconnected.
A denied social-actions read is stored and not retried.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Any

import board_async
import board_store
import linkedin_api
import linkedin_store
from ddb_convert import _from_ddb_nested
from http_common import _log_event
from linkedin_api import LinkedInApiError
from linkedin_member_analytics import (
    _analytics_carry,
    _analytics_count,
    _analytics_queries,
    _copy_bookkeeping,
    _read_member_analytics,
    _social_metrics,
)
from linkedin_store import HKT

# One analytics post can still make three eight-second calls after the budget check.
# 75 seconds plus that remainder stays far under the 300-second Lambda limit.
BUDGET_SECONDS = 75
REACTION_CAP = 5
BACKFILL_CAP = 8
POST_LIMIT = 400
_PAGE_SIZE = 100
_SHARE_URN = re.compile(r"urn:li:(?:share|ugcPost):\d+")


def _platform(row: dict[str, Any]) -> dict[str, Any]:
    platform = row.get("platform")
    return platform if isinstance(platform, dict) else {}


def _previous(row: dict[str, Any]) -> dict[str, Any]:
    metrics = row.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _share_urn(platform: dict[str, Any]) -> str:
    stored = str(platform.get("urn") or "")
    if _SHARE_URN.fullmatch(stored):
        return stored
    text = urllib.parse.unquote(f"{stored} {platform.get('url') or ''}")
    found = _SHARE_URN.search(text)
    return found.group(0) if found else ""


def _is_page(row: dict[str, Any], connection: dict[str, Any]) -> bool:
    if row.get("channel") == "page":
        return True
    manual = row.get("manual")
    org = str(connection.get("organizationId") or "")
    return isinstance(manual, dict) and connection.get("channel") == "page" and bool(org)


def _organization_id(row: dict[str, Any], platform: dict[str, Any], connection: dict[str, Any]) -> str:
    stored = str(platform.get("organizationId") or "")
    if stored:
        return stored
    if _is_page(row, connection):
        return str(connection.get("organizationId") or "")
    return ""


def _within(value: str, cutoff: datetime) -> bool:
    parsed = linkedin_store._parse_slot(value)
    return parsed is not None and parsed > cutoff


def _needs_impression(
    row: dict[str, Any],
    previous: dict[str, Any],
    connection: dict[str, Any],
    include: bool,
    cutoff: datetime,
    refresh_after: datetime | None = None,
) -> bool:
    """A missing count is due. A recent analytics count is due again after six hours."""
    if not include or _is_page(row, connection):
        return False
    if previous.get("impressions") is None:
        return not _within(str(previous.get("impressionCheckedAt") or ""), cutoff)
    if refresh_after is None:
        return False
    published = linkedin_store._parse_slot(str(_platform(row).get("publishedAt") or ""))
    if published is None or published < refresh_after:
        return False
    return not _within(str(previous.get("impressionReadAt") or ""), cutoff)


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
    _copy_bookkeeping(metrics, previous)
    return metrics


def _impressions(
    token: str,
    row: dict[str, Any],
    urn: str,
    organization_id: str,
    *,
    page: bool,
    include_member_analytics: bool,
    analytics_token: str = "",
    analytics_connected: bool = False,
) -> int | None:
    if page and organization_id and token:
        return linkedin_api.page_impressions(token, organization_id, urn)
    if analytics_connected and not page:
        if not analytics_token:
            return None
        return linkedin_api.member_impressions(analytics_token, urn)
    if include_member_analytics and not page and token:
        return linkedin_api.member_impressions(token, urn)
    return None


def _apply_impressions(
    metrics: dict[str, Any],
    previous: dict[str, Any],
    read: int | None,
    *,
    backfill: bool,
) -> None:
    if read is None and previous.get("impressions") is not None:
        metrics["impressions"] = previous["impressions"]
        return
    metrics["impressions"] = read
    if backfill and read is None:
        metrics["impressionCheckedAt"] = board_store.now_iso()
    elif read is not None:
        metrics.pop("impressionCheckedAt", None)
        metrics["impressionReadAt"] = board_store.now_iso()


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


def _published_rows(table: Any, limit: int) -> list[dict[str, Any]]:
    """Newest published rows, including ones past the first DynamoDB page."""
    out: list[dict[str, Any]] = []
    start: dict[str, Any] | None = None
    while len(out) < limit:
        kwargs: dict[str, Any] = {
            "IndexName": "gsi1",
            "KeyConditionExpression": "gsi1pk = :pk",
            "ExpressionAttributeValues": {":pk": "LINKEDIN#posts#published"},
            "ScanIndexForward": False,
            "Limit": min(_PAGE_SIZE, limit - len(out)),
        }
        if start:
            kwargs["ExclusiveStartKey"] = start
        res = table.query(**kwargs)
        rows = res.get("Items") if isinstance(res, dict) else None
        for row in rows or []:
            doc = _from_ddb_nested(linkedin_store._strip(row))
            if isinstance(doc, dict):
                out.append(doc)
        start = res.get("LastEvaluatedKey") if isinstance(res, dict) else None
        if not start:
            break
    return out


def _token_needs_reconnect(connection: dict[str, Any]) -> bool:
    if str(connection.get("refreshToken") or ""):
        return False
    expires = linkedin_store._parse_slot(str(connection.get("tokenExpiresAt") or ""))
    return expires is not None and expires <= datetime.now(HKT) + timedelta(minutes=2)


def refresh(
    table: Any,
    connection: dict[str, Any],
    token: str,
    *,
    analytics_token: str = "",
    allow_analytics_call: Any = None,
) -> int:
    now = datetime.now(HKT)
    cutoff = now - timedelta(hours=6)
    oldest = now - timedelta(days=30)
    analytics_on = bool(analytics_token)
    include = analytics_on or bool(connection.get("includeMemberAnalytics"))
    refresh_after = oldest if analytics_on else None
    started = time.monotonic()
    rows = _published_rows(table, POST_LIMIT)

    def _due(row: dict[str, Any]) -> bool:
        if analytics_on and not _is_page(row, connection):
            return bool(_analytics_queries(row, _previous(row), now))
        return _needs_impression(row, _previous(row), connection, include, cutoff, refresh_after)

    rows.sort(key=lambda row: str(_platform(row).get("publishedAt") or row.get("slotAt") or ""), reverse=True)
    rows.sort(key=lambda row: 0 if _due(row) else 1)
    reactions_done = 0
    backfill_done = 0
    updated = 0
    analytics_capped = False
    denied_now: set[str] = set()
    for row in rows:
        if time.monotonic() - started >= BUDGET_SECONDS:
            break
        if reactions_done >= REACTION_CAP and backfill_done >= BACKFILL_CAP:
            break
        platform = _platform(row)
        previous = _previous(row)
        page = _is_page(row, connection)
        urn = _share_urn(platform)
        usable = urn or str(platform.get("urn") or "")
        if analytics_on and not page:
            if analytics_capped or backfill_done >= BACKFILL_CAP or not usable:
                continue
            wanted = _analytics_queries(row, previous, now)
            if not wanted:
                continue
            metrics = _analytics_carry(previous)
            made, capped = _read_member_analytics(
                metrics, previous, usable, analytics_token, wanted, allow_analytics_call, denied_now
            )
            if made:
                _save(table, row, metrics, urn)
                updated += 1
                backfill_done += 1
            if capped:
                analytics_capped = True
            continue
        needs = _needs_impression(row, previous, connection, include, cutoff, refresh_after)
        analytics_reactions = _analytics_count(previous, "REACTION") is not None
        analytics_comments = _analytics_count(previous, "COMMENT") is not None
        do_reactions = (
            bool(token)
            and bool(usable)
            and _reactions_due(platform, previous, oldest, cutoff)
            and reactions_done < REACTION_CAP
            and not (not page and analytics_reactions and analytics_comments)
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
                metrics = _social_metrics(previous, counts)
        read: int | None = None
        capped = False
        member_token = ""  # nosec B105
        # The daily cap skips this impression read. Reactions on later posts still run.
        if do_backfill and not page and analytics_on:
            if allow_analytics_call is not None and not allow_analytics_call():
                capped = True
            else:
                member_token = analytics_token
        if capped and not do_reactions:
            continue
        try:
            read = _impressions(
                token,
                row,
                usable,
                _organization_id(row, platform, connection),
                page=page,
                include_member_analytics=include,
                analytics_token=member_token,
                analytics_connected=analytics_on,
            )
        except LinkedInApiError as exc:
            _log_event("warning", tag="linkedin_metrics_failed", error=str(exc)[:200])
        _apply_impressions(metrics, previous, read, backfill=do_backfill and not capped)
        _save(table, row, metrics, urn)
        updated += 1
        if do_reactions:
            reactions_done += 1
        if do_backfill and not capped:
            backfill_done += 1
    return updated


def _analytics_reader(table: Any) -> tuple[str, Any]:
    import linkedin_analytics

    analytics = linkedin_analytics.load_connection(table)
    if not analytics or _token_needs_reconnect(analytics):
        return "", None
    try:
        token = linkedin_analytics.access_token(table, analytics)
    except Exception as exc:  # noqa: BLE001 — a bad analytics token must not stop posting metrics
        _log_event("warning", tag="linkedin_metrics_failed", error=str(exc)[:240])
        return "", None
    return token, lambda: linkedin_analytics.take_call(table, analytics)


def refresh_connected(table: Any) -> dict[str, Any]:
    """Refresh the saved connection. A failure is logged and does not raise."""
    try:
        import linkedin

        fresh = linkedin_store.load_connection(table)
        analytics_token, allow = _analytics_reader(table)
        if fresh and not _token_needs_reconnect(fresh):
            refreshed = refresh(
                table,
                fresh,
                linkedin._access_token(table, fresh),
                analytics_token=analytics_token,
                allow_analytics_call=allow,
            )
        elif analytics_token:
            refreshed = refresh(
                table,
                fresh or {"channel": "profile"},
                "",
                analytics_token=analytics_token,
                allow_analytics_call=allow,
            )
        elif fresh:
            return {"ok": True, "refreshed": 0, "skipped": "expired"}
        else:
            return {"ok": True, "refreshed": 0}
    except Exception as exc:  # noqa: BLE001 — metrics must not fail publishing or the reminder
        _log_event("warning", tag="linkedin_metrics_failed", error=str(exc)[:240])
        return {"ok": False, "refreshed": 0}
    return {"ok": True, "refreshed": refreshed}


def queue_backfill(include_member_analytics: bool) -> None:
    """Fill impressions on the worker so the OAuth response stays short."""
    if include_member_analytics:
        board_async.try_invoke_event({"internal": "linkedin_publish_due", "metricsOnly": True})
