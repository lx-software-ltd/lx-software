"""Hold windows: classify write ops, schedule, execute, veto.

See docs/architecture/executive-board-autonomy-implementation.md WP2.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import board_hk
import board_mail
import board_staff
import board_store
import board_tools
from contract_constants import (
    BOARD_STAFF_HOLD_DEFAULT_HOURS,
    BOARD_STAFF_RAMP_DEMOTE_VETO_RATE,
    BOARD_STAFF_RAMP_DEMOTE_WINDOW_ACTIONS,
    BOARD_STAFF_RAMP_MIN_ACTIONS,
    BOARD_STAFF_RAMP_PROMOTE_MAX_VETO_RATE,
    BOARD_STAFF_RAMP_WINDOW_DAYS,
    BOARD_STAFF_RETENTION_DAYS,
)
from http_common import _log_event

INTERNAL_OPS = frozenset(
    {
        "product_flag_listing",
        "security_open_remediation",
        "aws_propose_budget_alert",
        "finance_draft_invoice",
        "finance_propose_price_change",
        "finance_record_manual_payment",
        "finance_match_payment",
        "outreach_upsert_prospect",
        "outreach_start_sequence",
        "outreach_suppress",
    }
)
INBOUND_REPLY_OPS = {
    "mail_reply": "mail",
    "meta_reply_comment": "meta",
    "meta_reply_dm": "meta",
    "meta_reply_whatsapp": "whatsapp",
    "stores_reply_review": "stores",
}
OUTBOUND_OPS = frozenset(
    {"mail_send", "mail_forward", "finance_send_invoice", "finance_send_reminder", "meta_relay_lead"}
)
PUBLISH_OPS = {
    "meta_propose_post": "facebook",
    "meta_propose_story": "instagram",
    "stores_draft_release_notes": "stores",
    "content_publish": "content",
    "newsletter_send": "newsletter",
}
SPEND_OPS = frozenset({"meta_create_ad_set", "meta_boost_post"})
REPLIED_STAGES = frozenset({"replied", "onboarding", "listed"})


class HoldError(ValueError):
    """Hold is missing or cannot be changed."""


def classify(op: board_tools.ToolOp, ctx: board_tools.ToolContext, args: dict[str, Any], settings: dict[str, Any]) -> tuple[str, str]:
    name = op.name
    if op.tool_id in ("board", "staff", "task"):
        return "internal", "internal"
    if name == "outreach_send":
        ptype = str(args.get("prospectType") or _prospect_type_for_args(ctx.table, args) or "unknown")
        return "cold_outreach", f"cold_outreach:{ptype}"
    if name in INTERNAL_OPS or name.startswith("github_"):
        return "internal", "internal"
    if name in INBOUND_REPLY_OPS:
        channel = INBOUND_REPLY_OPS[name]
        return "inbound_reply", f"inbound_reply:{channel}"
    if name in OUTBOUND_OPS:
        if _outbound_known(ctx, args, settings):
            return "outbound_known", "outbound_known"
        ptype = str(args.get("prospectType") or _prospect_type_for_args(ctx.table, args) or "unknown")
        return "cold_outreach", f"cold_outreach:{ptype}"
    if name == "content_publish":
        channel = str(args.get("channel") or _content_channel(ctx.table, args) or "content")
        return "publish", f"publish:{channel}"
    if name in PUBLISH_OPS:
        return "publish", f"publish:{PUBLISH_OPS[name]}"
    if name in SPEND_OPS:
        return "spend", "spend:meta"
    if name == "code_merge_staging":
        return "code_staging", "code_staging"
    if op.is_write:
        return "internal", "internal"
    return "internal", "internal"


def _outbound_known(ctx: board_tools.ToolContext, args: dict[str, Any], settings: dict[str, Any]) -> bool:
    recipients = _recipients(args)
    if not recipients:
        return False
    for addr in recipients:
        if board_mail.recipient_allowed(settings, addr):
            continue
        prospect = _prospect_for_address(ctx.table, addr)
        if prospect and str(prospect.get("stage") or "") in REPLIED_STAGES:
            continue
        return False
    return True


def _recipients(args: dict[str, Any]) -> list[str]:
    raw = args.get("to") or args.get("recipientId") or args.get("contact") or args.get("providerEmail")
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def _prospect_for_address(table: Any, address: str) -> dict[str, Any] | None:
    key = board_store.get_prospect_by_dedupe(table, address.strip().lower())
    if not key:
        return None
    return board_store.get_prospect(table, key)


def _content_channel(table: Any, args: dict[str, Any]) -> str:
    cid = str(args.get("contentId") or "")
    if not cid:
        return ""
    row = board_store.get_content(table, cid)
    return str((row or {}).get("channel") or "")


def _prospect_type_for_args(table: Any, args: dict[str, Any]) -> str:
    pid = str(args.get("prospectId") or "")
    if pid:
        row = board_store.get_prospect(table, pid)
        if row:
            return str(row.get("type") or "")
    for addr in _recipients(args):
        row = _prospect_for_address(table, addr)
        if row:
            return str(row.get("type") or "")
    return ""


def hold_hours(table: Any, settings: dict[str, Any], action_class: str, class_key: str) -> int:
    holds = ((settings.get("boundaries") or {}).get("holds") or {})
    overrides = ((settings.get("boundaries") or {}).get("holdOverrides") or {})
    default = int(holds.get(action_class, BOARD_STAFF_HOLD_DEFAULT_HOURS) or 0)
    breaker = (
        board_store.get_breaker(table, f"class:{class_key}")
        or board_store.get_breaker(table, f"class:{action_class}")
        or board_store.get_breaker(table, action_class)
        or board_store.get_breaker(table, class_key)
    )
    if breaker and breaker.get("tripped"):
        return default
    if class_key in overrides:
        try:
            return max(0, min(168, int(overrides[class_key])))
        except (TypeError, ValueError):
            return default
    return max(0, default)


def _shift_quiet(execute_at: datetime, settings: dict[str, Any]) -> datetime:
    hours = ((settings.get("boundaries") or {}).get("reply") or {}).get("quietHoursHkt") or [22, 8]
    try:
        start, end = int(hours[0]), int(hours[1])
    except (TypeError, ValueError, IndexError):
        start, end = 22, 8
    if board_hk.in_quiet_hours(execute_at, start, end):
        return board_hk.next_hour_hkt(execute_at, end)
    return execute_at


def create_hold(
    ctx: board_tools.ToolContext,
    op: board_tools.ToolOp,
    arguments: dict[str, Any],
    *,
    action_class: str,
    class_key: str,
    hours: int,
    summary: str,
    execute_at: datetime | str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    if execute_at:
        target = board_hk.parse_iso(execute_at) if isinstance(execute_at, str) else execute_at
        execute_dt = _shift_quiet(board_hk.as_hkt(target), ctx.settings)
    else:
        execute_dt = _shift_quiet(now + timedelta(hours=max(0, hours)), ctx.settings)
    execute_iso = board_hk.to_iso(execute_dt)
    preview = board_tools.render_preview(ctx, op, arguments)
    hold_id = board_store.new_id()
    stored_args = dict(arguments)
    thread_cursor = _thread_cursor(ctx.table, op.name, stored_args)
    if thread_cursor:
        stored_args["threadLastMessageAt"] = thread_cursor
    doc = {
        "holdId": hold_id,
        "status": "scheduled",
        "actionClass": action_class,
        "classKey": class_key,
        "personaId": ctx.persona_id,
        "seatId": ctx.seat_id,
        "taskId": ctx.task_id,
        "displayName": ctx.display_name,
        "op": op.name,
        "toolId": op.tool_id,
        "arguments": stored_args,
        "preview": preview,
        "summary": summary,
        "createdAt": board_store.now_iso(),
        "executeAt": execute_iso,
        "executedAt": None,
        "vetoedAt": None,
        "vetoBy": "",
        "vetoReason": "",
        "result": {},
        "threadLastMessageAt": thread_cursor,
    }
    board_store.put_hold(ctx.table, doc)
    _log_event("info", tag="board_hold_created", holdId=hold_id, op=op.name, executeAt=execute_iso, classKey=class_key)
    return doc


def maybe_hold(
    ctx: board_tools.ToolContext,
    op: board_tools.ToolOp,
    arguments: dict[str, Any],
    *,
    summary: str,
) -> dict[str, Any] | None:
    """If this act-level write should wait, persist a hold and return its public view."""
    if ctx.actor == "hold":
        return None
    if not op.is_write:
        return None
    if not board_staff.enabled(ctx.settings):
        return None
    action_class, class_key = classify(op, ctx, arguments, ctx.settings)
    hours = hold_hours(ctx.table, ctx.settings, action_class, class_key)
    quiet_reply = False
    try:
        import board_policy

        quiet_reply = op.name in board_policy.REPLY_OPS and board_policy.is_quiet_now(ctx.settings)
        quiet_outreach = op.name == "outreach_send" and board_policy.is_quiet_now(ctx.settings)
    except Exception:
        quiet_reply = False
        quiet_outreach = False
    slot_at = str(arguments.get("slotAt") or "") if op.name == "content_publish" else ""
    if hours <= 0 and not quiet_reply and not quiet_outreach and not slot_at:
        return None
    return create_hold(
        ctx,
        op,
        arguments,
        action_class=action_class,
        class_key=class_key,
        hours=hours,
        summary=summary,
        execute_at=slot_at or None,
    )


def execute_due(table: Any, settings: dict[str, Any], now_iso: str, *, limit: int = 25) -> int:
    if not board_staff.enabled(settings):
        return 0
    due = [
        h
        for h in board_store.list_holds(table, "scheduled", limit=200)
        if str(h.get("executeAt") or "") <= now_iso
    ]
    due.sort(key=lambda h: str(h.get("executeAt") or ""))
    ran = 0
    for hold in due[:limit]:
        if _execute_one(table, settings, hold):
            ran += 1
    return ran


def _execute_one(table: Any, settings: dict[str, Any], hold: dict[str, Any]) -> bool:
    hold_id = str(hold.get("holdId") or "")
    if not hold_id or not board_store.claim_hold(table, hold_id, from_status="scheduled", to_status="executing"):
        return False
    op = board_tools.REGISTRY.get(str(hold.get("op") or ""))
    now = board_store.now_iso()
    if op is None:
        _finish_hold(table, hold, "failed", now, error="This operation no longer exists.")
        return True
    if hold.get("actionClass") == "inbound_reply" and str(hold.get("op") or "") == "mail_reply":
        if _thread_changed(table, hold):
            _finish_hold(table, hold, "failed", now, error="thread changed")
            return True
    ctx = board_tools.ToolContext(
        table=table,
        settings=settings,
        persona_id=str(hold.get("personaId") or ""),
        display_name=str(hold.get("displayName") or ""),
        kind="hold",
        task_id=str(hold.get("taskId") or ""),
        seat_id=str(hold.get("seatId") or ""),
        actor="hold",
    )
    try:
        outcome = board_tools.execute_call(ctx, op, dict(hold.get("arguments") or {}))
    except Exception as exc:
        _finish_hold(table, hold, "failed", now, error=str(exc)[:400])
        return True
    if outcome.status == "error":
        _finish_hold(table, hold, "failed", now, error=str(outcome.result.get("error") or "error")[:400], call_id=outcome.call_id)
        return True
    _finish_hold(table, hold, "executed", now, call_id=outcome.call_id)
    record_ramp(table, settings, str(hold.get("classKey") or ""), vetoed=False)
    return True


def _thread_cursor(table: Any, op_name: str, arguments: dict[str, Any]) -> str:
    if op_name != "mail_reply":
        return str(arguments.get("threadLastMessageAt") or "")
    thread_id = str(arguments.get("threadId") or "")
    if not thread_id:
        return str(arguments.get("threadLastMessageAt") or "")
    thread = board_store.get_mail_thread(table, thread_id) or {}
    return str(thread.get("lastInboundAt") or thread.get("lastMessageAt") or arguments.get("threadLastMessageAt") or "")


def _thread_changed(table: Any, hold: dict[str, Any]) -> bool:
    expected = str(hold.get("threadLastMessageAt") or (hold.get("arguments") or {}).get("threadLastMessageAt") or "")
    if not expected:
        return False
    thread_id = str((hold.get("arguments") or {}).get("threadId") or "")
    if not thread_id:
        return False
    thread = board_store.get_mail_thread(table, thread_id) or {}
    latest = str(thread.get("lastInboundAt") or "")
    return bool(latest and latest > expected)


def _finish_hold(table: Any, hold: dict[str, Any], status: str, now: str, *, error: str = "", call_id: str = "") -> None:
    hold["status"] = status
    hold["updatedAt"] = now
    if status == "executed":
        hold["executedAt"] = now
    hold["result"] = {"callId": call_id, "error": error}
    hold["expiresAt"] = int(datetime.now(timezone.utc).timestamp()) + BOARD_STAFF_RETENTION_DAYS * 86400
    board_store.put_hold(table, hold)


def veto(table: Any, hold_id: str, by_sub: str, reason: str) -> dict[str, Any]:
    hold = board_store.get_hold(table, hold_id)
    if not hold:
        raise HoldError("Hold not found")
    if hold.get("status") != "scheduled":
        raise HoldError(f"Hold is already {hold.get('status')}")
    now = board_store.now_iso()
    hold["status"] = "vetoed"
    hold["vetoedAt"] = now
    hold["vetoBy"] = by_sub
    hold["vetoReason"] = reason[:400]
    hold["updatedAt"] = now
    hold["expiresAt"] = int(datetime.now(timezone.utc).timestamp()) + BOARD_STAFF_RETENTION_DAYS * 86400
    board_store.put_hold(table, hold)
    settings = board_store.load_settings(table)
    record_ramp(table, settings, str(hold.get("classKey") or ""), vetoed=True)
    try:
        import board_lessons

        board_lessons.create_from_veto(table, hold)
    except Exception as exc:
        _log_event("warning", tag="board_lesson_from_veto_failed", error=str(exc)[:200])
    if hold.get("op") == "content_publish":
        content_id = str((hold.get("arguments") or {}).get("contentId") or "")
        if content_id:
            row = board_store.get_content(table, content_id)
            if row:
                row["status"] = "vetoed"
                row["updatedAt"] = now
                board_store.put_content(table, row)
    return hold


def veto_class_today(table: Any, class_key: str, by_sub: str) -> list[dict[str, Any]]:
    cutoff = board_hk.to_iso(datetime.now(timezone.utc) + timedelta(hours=24))
    out: list[dict[str, Any]] = []
    for hold in board_store.list_holds(table, "scheduled", limit=400):
        if hold.get("classKey") != class_key:
            continue
        if str(hold.get("executeAt") or "") > cutoff:
            continue
        out.append(veto(table, str(hold["holdId"]), by_sub, f"class veto {class_key}"))
    return out


def record_ramp(table: Any, settings: dict[str, Any], class_key: str, *, vetoed: bool) -> dict[str, Any]:
    if not class_key:
        return {}
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    current = board_store.load_ramp(table, class_key)
    days = dict(current.get("days") or {})
    slot = dict(days.get(day) or {"actions": 0, "vetoes": 0})
    slot["actions"] = int(slot.get("actions") or 0) + 1
    if vetoed:
        slot["vetoes"] = int(slot.get("vetoes") or 0) + 1
    days[day] = slot
    recent = list(current.get("recent") or [])
    recent.append("veto" if vetoed else "action")
    recent = recent[-BOARD_STAFF_RAMP_DEMOTE_WINDOW_ACTIONS :]
    doc = {
        "classKey": class_key,
        "actions": int(current.get("actions") or 0) + 1,
        "vetoes": int(current.get("vetoes") or 0) + (1 if vetoed else 0),
        "days": days,
        "recent": recent,
    }
    board_store.save_ramp(table, class_key, doc)
    state = ramp_state(table, class_key)
    if state.get("shouldDemote"):
        _demote(table, settings, class_key)
    return state


def ramp_state(table: Any, class_key: str) -> dict[str, Any]:
    current = board_store.load_ramp(table, class_key)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=BOARD_STAFF_RAMP_WINDOW_DAYS)).strftime("%Y-%m-%d")
    window_actions = 0
    window_vetoes = 0
    for day, slot in (current.get("days") or {}).items():
        if str(day) >= cutoff:
            window_actions += int((slot or {}).get("actions") or 0)
            window_vetoes += int((slot or {}).get("vetoes") or 0)
    rate = (window_vetoes / window_actions) if window_actions else 0.0
    recent = list(current.get("recent") or [])
    recent_vetoes = sum(1 for x in recent if x == "veto")
    recent_rate = (recent_vetoes / len(recent)) if recent else 0.0
    return {
        "classKey": class_key,
        "actions": window_actions,
        "vetoes": window_vetoes,
        "rate": rate,
        "eligibleForPromotion": window_actions >= BOARD_STAFF_RAMP_MIN_ACTIONS and rate <= BOARD_STAFF_RAMP_PROMOTE_MAX_VETO_RATE,
        "shouldDemote": len(recent) >= BOARD_STAFF_RAMP_DEMOTE_WINDOW_ACTIONS and recent_rate > BOARD_STAFF_RAMP_DEMOTE_VETO_RATE,
        "totals": {"actions": current.get("actions") or 0, "vetoes": current.get("vetoes") or 0},
    }


def _demote(table: Any, settings: dict[str, Any], class_key: str) -> None:
    boundaries = dict(settings.get("boundaries") or {})
    overrides = dict(boundaries.get("holdOverrides") or {})
    if class_key not in overrides:
        return
    overrides.pop(class_key, None)
    boundaries["holdOverrides"] = overrides
    settings["boundaries"] = board_store.normalize_boundaries(boundaries)
    board_store.save_settings(table, settings)
    try:
        import board_breakers

        board_breakers.trip(table, f"class:{class_key}", "ramp demote — hold restored")
    except Exception as exc:
        _log_event("warning", tag="board_breaker_demote_failed", error=str(exc)[:200], classKey=class_key)
    _log_event("warning", tag="board_ramp_demoted", classKey=class_key)


def promote(table: Any, class_key: str) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    boundaries = dict(settings.get("boundaries") or {})
    overrides = dict(boundaries.get("holdOverrides") or {})
    overrides[class_key] = 0
    boundaries["holdOverrides"] = overrides
    settings["boundaries"] = board_store.normalize_boundaries(boundaries)
    saved = board_store.save_settings(table, settings)
    try:
        import board_breakers

        if board_breakers.is_tripped(table, f"class:{class_key}"):
            board_breakers.reset(table, f"class:{class_key}", "ramp-promote")
    except Exception as exc:
        _log_event("warning", tag="board_breaker_promote_reset_failed", error=str(exc)[:200], classKey=class_key)
    _log_event("info", tag="board_ramp_promoted", classKey=class_key)
    return {"classKey": class_key, "holdOverrides": (saved.get("boundaries") or {}).get("holdOverrides") or {}}


def list_ramp(table: Any) -> list[dict[str, Any]]:
    # Ramp rows are state keys; scan known keys from recent holds plus stored ramps via list of hold classKeys.
    keys: set[str] = set()
    for status in ("scheduled", "executed", "vetoed"):
        for hold in board_store.list_holds(table, status, limit=200):
            if hold.get("classKey"):
                keys.add(str(hold["classKey"]))
    return [ramp_state(table, key) for key in sorted(keys)]


def public_hold(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in ("pk", "sk", "gsi1pk", "gsi1sk")}
