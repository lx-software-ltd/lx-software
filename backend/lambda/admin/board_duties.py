"""Seat duties on the staff tick (WP9). Cron is evaluated in HKT (no DST)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import board_hk
import board_staff
import board_store
from contract_constants import BOARD_STAFF_ACTION_CLASSES, BOARD_STAFF_SEATS
from http_common import _log_event

DOW = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}


class DutyError(ValueError):
    """Invalid cron or duty definition."""


def parse_cron(expr: str) -> dict[str, Any]:
    parts = str(expr or "").split()
    if len(parts) != 5:
        raise DutyError("cron must have five fields (min hour dom month dow) in HKT")
    minute, hour, dom, month, dow = parts
    return {
        "minute": _field(minute, 0, 59),
        "hour": _field(hour, 0, 23),
        "dom": _field(dom, 1, 31),
        "month": _field(month, 1, 12),
        "dow": _dow(dow),
    }


def _field(raw: str, lo: int, hi: int) -> set[int] | None:
    if raw == "*":
        return None
    out: set[int] = set()
    for part in raw.split(","):
        if not part.isdigit():
            raise DutyError(f"bad cron field {raw}")
        n = int(part)
        if n < lo or n > hi:
            raise DutyError(f"cron field {raw} out of range")
        out.add(n)
    return out


def _dow(raw: str) -> set[int] | None:
    if raw == "*":
        return None
    out: set[int] = set()
    for part in raw.split(","):
        key = part.strip().upper()
        if key in DOW:
            out.add(DOW[key])
            continue
        if key.isdigit():
            n = int(key)
            if n == 7:
                out.add(6)
            elif 0 <= n <= 6:
                # 0 = Sunday (UNIX), 1 = Monday … 6 = Saturday
                out.add(6 if n == 0 else n - 1)
            else:
                raise DutyError(f"bad dow {raw}")
            continue
        raise DutyError(f"bad dow {raw}")
    return out


def matches(parsed: dict[str, Any], when: datetime) -> bool:
    local = board_hk.as_hkt(when)
    if parsed["minute"] is not None and local.minute not in parsed["minute"]:
        return False
    if parsed["hour"] is not None and local.hour not in parsed["hour"]:
        return False
    if parsed["month"] is not None and local.month not in parsed["month"]:
        return False
    dom_ok = parsed["dom"] is None or local.day in parsed["dom"]
    dow_ok = parsed["dow"] is None or local.weekday() in parsed["dow"]
    if parsed["dom"] is not None and parsed["dow"] is not None:
        return dom_ok or dow_ok
    return dom_ok and dow_ok


def last_scheduled(expr: str, now: datetime) -> datetime | None:
    parsed = parse_cron(expr)
    local = board_hk.as_hkt(now).replace(second=0, microsecond=0)
    hours = parsed["hour"] if parsed["hour"] is not None else range(24)
    minutes = parsed["minute"] if parsed["minute"] is not None else range(0, 60, 5)
    best: datetime | None = None
    for day_back in range(0, 40):
        day = local - timedelta(days=day_back)
        for hour in hours:
            for minute in minutes:
                cand = day.replace(hour=int(hour), minute=int(minute))
                if cand <= local and matches(parsed, cand) and (best is None or cand > best):
                    best = cand
        if best is not None and day_back > 0:
            return best
    return best


def is_due(expr: str, last_run_iso: str, now: datetime) -> bool:
    scheduled = last_scheduled(expr, now)
    if scheduled is None:
        return False
    if not last_run_iso:
        return True
    try:
        last = board_hk.parse_iso(last_run_iso)
    except ValueError:
        return True
    return board_hk.as_hkt(last) < scheduled


def _cache_name(seat_id: str, duty_id: str) -> str:
    return f"duty:{seat_id}:{duty_id}"


def run_due(table: Any, settings: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    if not board_staff.enabled(settings):
        return []
    if not (settings.get("staff") or {}).get("dutiesEnabled"):
        return []
    when = now or board_hk.now_hkt()
    roster = board_staff.seats_by_id(table, settings)
    created: list[dict[str, Any]] = []
    for seat in BOARD_STAFF_SEATS:
        seat_id = str(seat.get("id") or "")
        live = roster.get(seat_id) or {}
        if not live.get("isActive"):
            continue
        for duty in seat.get("duties") or []:
            if not isinstance(duty, dict):
                continue
            duty_id = str(duty.get("id") or "")
            cron = str(duty.get("cron") or "")
            if not duty_id or not cron:
                continue
            hit = board_store.get_cache(table, _cache_name(seat_id, duty_id))
            last_iso = ""
            if hit and isinstance(hit.get("payload"), dict):
                last_iso = str(hit["payload"].get("scheduledAt") or hit["payload"].get("ranAt") or "")
            try:
                due = is_due(cron, last_iso, when)
            except DutyError as exc:
                _log_event("warning", tag="board_duty_bad_cron", seat=seat_id, duty=duty_id, error=str(exc)[:200])
                continue
            if not due:
                continue
            scheduled = last_scheduled(cron, when)
            date_label = board_hk.as_hkt(scheduled or when).date().isoformat()
            from board_triage import find_open_event_task

            event_id = f"{seat_id}:{duty_id}:{date_label}"
            if find_open_event_task(table, "duty", event_id):
                continue
            if not board_store.claim_duty_marker(table, f"duty:{seat_id}:{duty_id}:{date_label}"):
                continue
            try:
                task = board_staff.create_task(
                    table,
                    settings,
                    assignee=seat_id,
                    origin="duty",
                    brief=str(duty.get("brief") or duty_id)[:4000],
                    deliverable_type=str(duty.get("deliverableType") or "markdown"),
                    sla_hours=24,
                    event_ref={"kind": "duty", "id": event_id},
                    created_by="board_duties",
                )
            except board_staff.StaffError as exc:
                _log_event("info", tag="board_duty_skipped", seat=seat_id, duty=duty_id, error=str(exc)[:200])
                continue
            board_store.put_cache(
                table,
                _cache_name(seat_id, duty_id),
                {"ranAt": board_store.now_iso(), "scheduledAt": board_hk.to_iso(scheduled or when), "taskId": task.get("taskId")},
                ttl_seconds=40 * 86400,
            )
            created.append(task)
    return created


def _seen_payload(table: Any, name: str) -> set[str]:
    hit = board_store.get_cache(table, name)
    if hit and isinstance(hit.get("payload"), dict):
        return {str(x) for x in (hit["payload"].get("ids") or []) if x}
    return set()


def _save_seen(table: Any, name: str, ids: list[str]) -> None:
    board_store.put_cache(table, name, {"ids": ids[:400]}, ttl_seconds=30 * 86400)


def _assignee_architect_or_cto(roster: dict[str, dict[str, Any]]) -> str:
    if (roster.get("architect") or {}).get("isActive"):
        return "architect"
    return "cto"


def triage_ops_signals(table: Any, settings: dict[str, Any]) -> dict[str, int]:
    """After aws/security refresh: new ALARM names and alert ids become tasks."""
    if not board_staff.enabled(settings):
        return {"alarms": 0, "alerts": 0}
    roster = board_staff.seats_by_id(table, settings)
    created_alarms = 0
    created_alerts = 0
    alarms_doc = board_store.get_cache(table, "aws:alarms")
    alarms = []
    if alarms_doc and isinstance(alarms_doc.get("payload"), dict):
        alarms = list(alarms_doc["payload"].get("alarms") or [])
    seen_alarms = _seen_payload(table, "seen:alarms")
    current_alarm_ids: list[str] = []
    architect = _assignee_architect_or_cto(roster)
    for row in alarms:
        name = str((row or {}).get("name") or "")
        if not name:
            continue
        current_alarm_ids.append(name)
        if name in seen_alarms:
            continue
        _maybe_task(
            table,
            settings,
            assignee=architect,
            brief=f"CloudWatch alarm in ALARM: {name}. {str((row or {}).get('reason') or '')[:300]}",
            event_id=f"alarm:{name}",
        )
        created_alarms += 1
    _save_seen(table, "seen:alarms", current_alarm_ids)

    alert_ids: list[str] = []
    new_alerts: list[tuple[str, str]] = []
    findings = board_store.get_cache(table, "security:findings")
    if findings and isinstance(findings.get("payload"), dict):
        for section in ("securityHub", "accessAnalyzer"):
            block = findings["payload"].get(section) or {}
            for row in block.get("findings") or []:
                fid = str((row or {}).get("id") or "")
                if not fid:
                    continue
                alert_ids.append(fid)
                new_alerts.append(
                    (fid, str((row or {}).get("title") or (row or {}).get("summary") or fid))
                )
    github = board_store.get_cache(table, "security:github")
    if github and isinstance(github.get("payload"), dict):
        for key in ("dependabot", "codeScanning", "secretScanning"):
            for row in github["payload"].get(key) or []:
                fid = str((row or {}).get("number") or (row or {}).get("id") or "")
                if not fid:
                    continue
                alert_ids.append(f"gh:{key}:{fid}")
                new_alerts.append(
                    (
                        f"gh:{key}:{fid}",
                        str(
                            (row or {}).get("title")
                            or (row or {}).get("summary")
                            or (row or {}).get("description")
                            or (row or {}).get("secretType")
                            or fid
                        ),
                    )
                )
    seen_alerts = _seen_payload(table, "seen:alerts")
    security_assignee = "security-analyst" if (roster.get("security-analyst") or {}).get("isActive") else "ciso"
    for fid, title in new_alerts:
        if fid in seen_alerts:
            continue
        _maybe_task(
            table,
            settings,
            assignee=security_assignee,
            brief=f"New security alert {fid}: {title[:300]}",
            event_id=f"alert:{fid}",
        )
        created_alerts += 1
    _save_seen(table, "seen:alerts", alert_ids)
    return {"alarms": created_alarms, "alerts": created_alerts}


def _maybe_task(table: Any, settings: dict[str, Any], *, assignee: str, brief: str, event_id: str) -> None:
    from board_triage import find_open_event_task

    if find_open_event_task(table, "ops", event_id):
        return
    try:
        board_staff.create_task(
            table,
            settings,
            assignee=assignee,
            origin="event",
            brief=brief[:4000],
            deliverable_type="markdown",
            sla_hours=24,
            event_ref={"kind": "ops", "id": event_id},
            created_by="board_duties",
        )
    except board_staff.StaffError as exc:
        _log_event("info", tag="board_ops_task_skipped", error=str(exc)[:200])


def validate_boundary_suggestions(table: Any, raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    known = set(BOARD_STAFF_ACTION_CLASSES)
    out: list[dict[str, Any]] = []
    for row in raw[:12]:
        if not isinstance(row, dict):
            continue
        class_key = str(row.get("classKey") or "").strip()
        if not class_key:
            continue
        head = class_key.split(":", 1)[0]
        if head not in known and class_key not in known:
            continue
        ramp = {}
        try:
            import board_holds

            ramp = board_holds.ramp_state(table, class_key)
        except Exception:
            ramp = {}
        out.append(
            {
                "classKey": class_key[:80],
                "change": str(row.get("change") or "")[:200],
                "evidence": str(row.get("evidence") or "")[:400],
                "source": "standup",
                "ramp": {k: ramp.get(k) for k in ("actions", "vetoes", "rate", "eligibleForPromotion") if k in ramp},
            }
        )
    return out
