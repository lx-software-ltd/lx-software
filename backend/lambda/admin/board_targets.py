"""Daily pipeline target check: qualify shortfall, due touches, cap raise."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import board_hk
import board_outreach
import board_sequences
import board_staff
import board_store
from contract_constants import (
    BOARD_STAFF_BOUNCE_RATE_BREAKER,
    BOARD_STAFF_COMPLAINT_RATE_BREAKER,
    BOARD_STAFF_OUTREACH_CAP_STEP_DAYS,
    BOARD_STAFF_OUTREACH_DAILY_CAP_MAX,
    BOARD_STAFF_OUTREACH_DAILY_CAP_STEP,
)
from http_common import _log_event


def _week_start_hkt(now: datetime | None = None) -> datetime:
    local = board_hk.as_hkt(now or datetime.now())
    monday = local.date() - timedelta(days=local.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=board_hk.HKT)


def qualified_this_week(table: Any, now: datetime | None = None) -> list[dict[str, Any]]:
    start = board_hk.to_iso(_week_start_hkt(now))
    counted_stages = ("qualified", "contacted", "replied", "onboarding", "listed")
    out: list[dict[str, Any]] = []
    for stage in counted_stages:
        for row in board_store.list_prospects(table, stage, limit=400):
            marked = str(row.get("qualifiedAt") or row.get("createdAt") or "")
            if marked >= start:
                out.append(row)
    return out


def prorated_target(settings: dict[str, Any], now: datetime | None = None) -> int:
    weekly = int(
        (((settings.get("boundaries") or {}).get("outreach") or {}).get("targets") or {}).get("qualifiedPerWeek")
        or 50
    )
    local = board_hk.as_hkt(now or datetime.now())
    # Monday = day 1 of 7.
    return max(1, int(round(weekly * (local.weekday() + 1) / 7)))


def _maybe_raise_cap(table: Any, settings: dict[str, Any]) -> dict[str, Any]:
    outreach = dict((settings.get("boundaries") or {}).get("outreach") or {})
    cap = int(outreach.get("dailyCap") or 20)
    raised_at = str(outreach.get("capRaisedAt") or "")
    now = board_hk.now_hkt()
    if not raised_at:
        outreach["capRaisedAt"] = board_hk.to_iso(now)

        def apply_stamp(current: dict[str, Any]) -> dict[str, Any]:
            bounds = dict(current.get("boundaries") or {})
            current_out = dict(bounds.get("outreach") or {})
            current_out.setdefault("capRaisedAt", outreach["capRaisedAt"])
            bounds["outreach"] = current_out
            current["boundaries"] = board_store.normalize_boundaries(bounds)
            return current

        return board_store.save_settings_retry(table, apply_stamp)
    try:
        last = board_hk.as_hkt(board_hk.parse_iso(raised_at))
    except ValueError:
        last = now - timedelta(days=BOARD_STAFF_OUTREACH_CAP_STEP_DAYS + 1)
    if (now - last).days < BOARD_STAFF_OUTREACH_CAP_STEP_DAYS:
        return settings
    rates = board_outreach.trailing_rates(table, days=7)
    if rates["sent"] >= 50 and (
        rates["bounceRate"] >= BOARD_STAFF_BOUNCE_RATE_BREAKER
        or rates["complaintRate"] >= BOARD_STAFF_COMPLAINT_RATE_BREAKER
    ):
        return settings
    if rates["bounceRate"] >= BOARD_STAFF_BOUNCE_RATE_BREAKER or rates["complaintRate"] >= BOARD_STAFF_COMPLAINT_RATE_BREAKER:
        return settings
    new_cap = min(BOARD_STAFF_OUTREACH_DAILY_CAP_MAX, cap + BOARD_STAFF_OUTREACH_DAILY_CAP_STEP)
    if new_cap == cap:
        return settings
    outreach["dailyCap"] = new_cap
    outreach["capRaisedAt"] = board_hk.to_iso(now)

    def apply_raise(current: dict[str, Any]) -> dict[str, Any]:
        bounds = dict(current.get("boundaries") or {})
        current_out = dict(bounds.get("outreach") or {})
        current_out["dailyCap"] = new_cap
        current_out["capRaisedAt"] = outreach["capRaisedAt"]
        bounds["outreach"] = current_out
        current["boundaries"] = board_store.normalize_boundaries(bounds)
        return current

    return board_store.save_settings_retry(table, apply_raise)


def check(table: Any, settings: dict[str, Any]) -> dict[str, Any]:
    if not board_staff.enabled(settings):
        return {"ok": False, "reason": "staff disabled"}
    settings = _maybe_raise_cap(table, settings)
    created: list[str] = []
    now = datetime.now()
    have = len(qualified_this_week(table, now))
    target = prorated_target(settings, now)
    shortfall = max(0, target - have)
    today = board_hk.today_hkt()
    outreach = (settings.get("boundaries") or {}).get("outreach") or {}
    types = ", ".join(outreach.get("typesEnabled") or [])
    districts = ", ".join(outreach.get("districtsFirst") or [])
    gaps = board_store.get_cache(table, "intel:gaps")
    gap_text = ""
    if gaps and isinstance(gaps.get("payload"), dict):
        gap_text = str(gaps["payload"].get("gaps") or gaps["payload"])[:800]
    if shortfall:
        brief = (
            f"Find and qualify {shortfall} prospects of types {types} in districts {districts} "
            f"using gaps {gap_text or '(none cached)'}; use open data first, Places second, search third"
        )
        try:
            from board_triage import find_open_event_task

            if find_open_event_task(table, "duty", f"target-qualify:{today}"):
                raise board_staff.StaffError("qualify task already open")
            task = board_staff.create_task(
                table,
                settings,
                assignee="prospector",
                origin="target",
                brief=brief[:4000],
                deliverable_type="prospects",
                sla_hours=12,
                event_ref={"kind": "duty", "id": f"target-qualify:{today}"},
                created_by="board_targets",
            )
            created.append(str(task.get("taskId") or ""))
        except board_staff.StaffError as exc:
            _log_event("info", tag="board_targets_qualify_skipped", error=str(exc)[:200])
    due_now = board_hk.to_iso(datetime.now())
    due_rows = board_sequences.due(table, due_now)
    if due_rows:
        names = ", ".join(str(r.get("name") or r.get("prospectId")) for r in due_rows[:20])
        brief = f"Send due touches ({len(due_rows)}): {names}"
        try:
            from board_triage import find_open_event_task

            if find_open_event_task(table, "duty", f"target-touches:{today}"):
                raise board_staff.StaffError("touches task already open")
            task = board_staff.create_task(
                table,
                settings,
                assignee="prospector",
                origin="target",
                brief=brief[:4000],
                deliverable_type="prospects",
                sla_hours=8,
                event_ref={"kind": "duty", "id": f"target-touches:{today}"},
                created_by="board_targets",
            )
            created.append(str(task.get("taskId") or ""))
        except board_staff.StaffError as exc:
            _log_event("info", tag="board_targets_touches_skipped", error=str(exc)[:200])
    return {
        "ok": True,
        "qualifiedThisWeek": have,
        "proratedTarget": target,
        "shortfall": shortfall,
        "dueTouches": len(due_rows) if due_rows else 0,
        "taskIds": created,
        "dailyCap": ((settings.get("boundaries") or {}).get("outreach") or {}).get("dailyCap"),
    }


def handle_check(event: dict[str, Any] | None = None) -> dict[str, Any]:
    if not board_store.event_targets_this_board(event):
        return {"ok": True, "skipped": "other board"}
    if not board_staff.env_enabled():
        return {"ok": True, "skipped": "env"}
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    return check(table, settings)
