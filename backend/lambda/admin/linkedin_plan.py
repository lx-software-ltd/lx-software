"""Dashboard summary for the LX Software LinkedIn plan card.

Kept out of ``linkedin_store`` so that module stays at its length allowance.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import parse_qs

import linkedin_store


def plan_summary(table: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Approved posts still ahead, approved posts that missed their slot, and the next open slot.

    A post with no slot counts as planned. ``refreshAt`` is the soonest future
    instant that changes this summary, so the dashboard can refetch then.
    """
    settings = linkedin_store.load_settings(table)
    current = linkedin_store._as_hkt(now)
    planned = 0
    overdue = 0
    refresh_at: datetime | None = None
    for row in linkedin_store.list_posts(table, status="approved", limit=400):
        slot = linkedin_store._parse_slot(str(row.get("slotAt") or ""))
        if slot is None or slot > current:
            planned += 1
            if slot is not None and (refresh_at is None or slot < refresh_at):
                refresh_at = slot
        else:
            overdue += 1
    upcoming = linkedin_store.next_slots(settings, now=current, count=1, taken=linkedin_store.taken_slots(table))
    next_empty = upcoming[0] if upcoming else None
    parsed_empty = linkedin_store._parse_slot(next_empty) if next_empty else None
    if parsed_empty is not None and (refresh_at is None or parsed_empty < refresh_at):
        refresh_at = parsed_empty
    return {
        "planned": planned,
        "overdue": overdue,
        "nextEmptySlot": next_empty,
        "refreshAt": linkedin_store._format_slot(refresh_at) if refresh_at is not None else None,
    }


def http_get(table: Any, event: dict[str, Any]) -> dict[str, Any]:
    """``?view=plan`` is the dashboard card. Anything else is the full overview."""
    view = (parse_qs(event.get("rawQueryString") or "").get("view") or [""])[0]
    if view == "plan":
        return plan_summary(table)
    return linkedin_store.overview(table)
