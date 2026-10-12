"""Config-gap cache for the daily review. One row per gap id."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import board_store
from http_common import _log_event


def _iso_week_id() -> str:
    return datetime.now(timezone.utc).strftime("%G-W%V")


_CONFIG_GAPS_CACHE = "config:gaps"


def note_config_gap(table: Any, *, gap_id: str, reason: str) -> dict[str, Any] | None:
    """Record an unconfigured integration on the daily review — no staff task.

    The same gap in the same ISO week refreshes ``reason`` and does not write another owner update.
    Older weeks of that same gap id are dropped, so the review shows one row.
    """
    week = _iso_week_id()
    text = str(reason or "")[:400]
    items = list_config_gaps(table)
    current: dict[str, Any] | None = None
    others: list[dict[str, Any]] = []
    dropped = False
    for row in items:
        if str(row.get("gapId") or "") != gap_id:
            others.append(row)
            continue
        if current is None and str(row.get("week") or "") == week:
            current = row
        else:
            dropped = True
    if current is not None:
        changed = str(current.get("reason") or "") != text
        if changed:
            current["reason"] = text
            current["at"] = board_store.now_iso()
        if changed or dropped:
            kept = others + [current]
            board_store.put_cache(table, _CONFIG_GAPS_CACHE, {"items": kept[-20:]}, ttl_seconds=40 * 86400)
        return None
    row = {
        "gapId": gap_id,
        "week": week,
        "reason": text,
        "at": board_store.now_iso(),
    }
    others.append(row)
    board_store.put_cache(table, _CONFIG_GAPS_CACHE, {"items": others[-20:]}, ttl_seconds=40 * 86400)
    try:
        board_store.add_update(table, text=f"CONFIG {gap_id} — {reason}"[:400], owner_sub=None)
    except Exception as exc:
        _log_event("warning", tag="board_config_gap_update_failed", error=str(exc)[:200])
    return row


def list_config_gaps(table: Any) -> list[dict[str, Any]]:
    hit = board_store.get_cache(table, _CONFIG_GAPS_CACHE)
    payload = hit.get("payload") if isinstance(hit, dict) else None
    if not isinstance(payload, dict):
        return []
    return [row for row in (payload.get("items") or []) if isinstance(row, dict)]


def clear_config_gap(table: Any, gap_id: str) -> int:
    wanted = str(gap_id or "")
    if not wanted:
        return 0
    items = list_config_gaps(table)
    kept = [row for row in items if str(row.get("gapId") or "") != wanted]
    dropped = len(items) - len(kept)
    if not dropped:
        return 0
    board_store.put_cache(table, _CONFIG_GAPS_CACHE, {"items": kept[-20:]}, ttl_seconds=40 * 86400)
    return dropped
