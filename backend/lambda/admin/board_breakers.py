"""WP4 breakers — class, channel, budget, tool. Evaluated on every staff tick."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import board_hk
import board_store
from http_common import _log_event


def trip(table: Any, name: str, reason: str) -> dict[str, Any]:
    existing = board_store.get_breaker(table, name) or {}
    if existing.get("tripped"):
        return existing
    now = board_store.now_iso()
    doc = {
        "name": name,
        "tripped": True,
        "reason": str(reason or "")[:400],
        "trippedAt": now,
        "resetBy": "",
        "resetAt": None,
    }
    board_store.put_breaker(table, name, doc)
    try:
        board_store.add_update(table, text=f"BREAKER {name} — {reason}", owner_sub=None)
    except Exception as exc:
        _log_event("warning", tag="board_breaker_update_failed", error=str(exc)[:200], name=name)
    _log_event("warning", tag="board_breaker_tripped", name=name, reason=str(reason)[:200])
    return doc


def reset(table: Any, name: str, by_sub: str) -> dict[str, Any]:
    existing = board_store.get_breaker(table, name) or {"name": name}
    doc = {
        **existing,
        "name": name,
        "tripped": False,
        "resetBy": by_sub,
        "resetAt": board_store.now_iso(),
    }
    board_store.put_breaker(table, name, doc)
    return doc


def is_tripped(table: Any, name: str) -> bool:
    row = board_store.get_breaker(table, name)
    return bool(row and row.get("tripped"))


def write_blocked(table: Any, op: Any) -> dict[str, Any] | None:
    """Structured error when a write op is stopped by a channel or tool breaker."""
    tool_id = str(getattr(op, "tool_id", "") or "")
    if tool_id and is_tripped(table, f"tool:{tool_id}"):
        return {"error": "breaker tripped", "breaker": f"tool:{tool_id}"}
    channel = _op_channel(op)
    if channel and is_tripped(table, f"channel:{channel}"):
        return {"error": "breaker tripped", "breaker": f"channel:{channel}"}
    name = str(getattr(op, "name", "") or "")
    if name == "outreach_send" and is_tripped(table, "outreach"):
        return {"error": "breaker tripped", "breaker": "outreach"}
    return None


def _op_channel(op: Any) -> str:
    name = str(getattr(op, "name", "") or "")
    try:
        import board_holds

        if name in board_holds.INBOUND_REPLY_OPS:
            return str(board_holds.INBOUND_REPLY_OPS[name])
        if name in board_holds.PUBLISH_OPS:
            return str(board_holds.PUBLISH_OPS[name])
    except Exception:
        pass
    return ""


def note_escalation_after_reply(table: Any, *, channel: str, thread_id: str) -> dict[str, Any] | None:
    """Trip channel:{channel} when a thread we already replied to escalates within 24 h."""
    if not channel or not thread_id:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    reply_ops = set()
    try:
        import board_holds

        reply_ops = set(board_holds.INBOUND_REPLY_OPS) | set(board_holds.PUBLISH_OPS)
    except Exception:
        reply_ops = {"mail_reply", "meta_reply_comment", "meta_reply_dm", "meta_reply_whatsapp", "stores_reply_review"}
    for call in board_store.list_tool_calls(table, limit=400):
        created = str(call.get("createdAt") or "")
        if created and created < cutoff_iso:
            continue
        if call.get("status") not in ("ok", "held", "pending_approval"):
            continue
        if str(call.get("op") or "") not in reply_ops:
            continue
        args = call.get("arguments") or {}
        if str(args.get("threadId") or args.get("reviewId") or "") != thread_id:
            continue
        return trip(table, f"channel:{channel}", f"escalation within 24h of {call.get('op')}")
    return None


def _fresh_save_staff(table: Any, **patch: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    staff = dict(settings.get("staff") or {})
    staff.update(patch)
    settings["staff"] = board_store.normalize_staff_config(staff)
    return board_store.save_settings(table, settings)


def evaluate(table: Any, settings: dict[str, Any]) -> list[str]:
    """Trip class / channel / budget / tool breakers. Returns newly tripped names."""
    tripped: list[str] = []

    try:
        import board_holds

        for row in board_holds.list_ramp(table):
            class_key = str(row.get("classKey") or "")
            if class_key and row.get("shouldDemote") and not is_tripped(table, f"class:{class_key}"):
                trip(table, f"class:{class_key}", "ramp demote — hold restored")
                tripped.append(f"class:{class_key}")
    except Exception as exc:
        _log_event("warning", tag="board_breaker_class_eval_failed", error=str(exc)[:200])

    staff_usage = board_store.load_staff_usage_day(table)
    daily = float((settings.get("staff") or {}).get("dailyBudgetUsd") or 0)
    spend = float(staff_usage.get("cost") or 0)
    if daily > 0:
        ratio = spend / daily
        hour = board_hk.now_hkt().hour
        if ratio >= 1.0:
            if not is_tripped(table, "budget"):
                trip(table, "budget", f"staff spend {spend:.2f} >= daily {daily:.2f}")
                tripped.append("budget")
            _fresh_save_staff(table, enabled=False, disabledReason=f"budget {spend:.2f}/{daily:.2f}")
        elif ratio >= 0.8 and hour < 12:
            if not is_tripped(table, "budget"):
                trip(table, "budget", f"80% staff budget before noon HKT ({spend:.2f}/{daily:.2f})")
                tripped.append("budget")
            _fresh_save_staff(table, seniorPaused=True)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    errors: dict[str, int] = {}
    for call in board_store.list_tool_calls(table, limit=400):
        created = str(call.get("createdAt") or "")
        if created and created < cutoff_iso:
            continue
        if call.get("status") != "error":
            continue
        tool_id = str(call.get("toolId") or "")
        if not tool_id:
            continue
        errors[tool_id] = errors.get(tool_id, 0) + 1
    for tool_id, count in errors.items():
        if count >= 10 and not is_tripped(table, f"tool:{tool_id}"):
            trip(table, f"tool:{tool_id}", f"{count} errors in the last hour")
            tripped.append(f"tool:{tool_id}")

    try:
        import board_outreach
        from contract_constants import BOARD_STAFF_BOUNCE_RATE_BREAKER, BOARD_STAFF_COMPLAINT_RATE_BREAKER

        rates = board_outreach.trailing_rates(table, days=7)
        if rates["sent"] >= 50 and not is_tripped(table, "outreach"):
            if rates["bounceRate"] > BOARD_STAFF_BOUNCE_RATE_BREAKER:
                trip(table, "outreach", f"7-day bounce rate {rates['bounceRate']:.3f} over {rates['sent']} sends")
                tripped.append("outreach")
            elif rates["complaintRate"] > BOARD_STAFF_COMPLAINT_RATE_BREAKER:
                trip(table, "outreach", f"7-day complaint rate {rates['complaintRate']:.4f} over {rates['sent']} sends")
                tripped.append("outreach")
    except Exception as exc:
        _log_event("warning", tag="board_breaker_outreach_eval_failed", error=str(exc)[:200])

    return tripped


def list_all(table: Any) -> list[dict[str, Any]]:
    return board_store.list_breakers(table)
