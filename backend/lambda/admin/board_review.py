"""WP4 daily review snapshot and digest email."""

from __future__ import annotations

import html
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any

import board_hk
import board_mail
import board_staff
import board_store
from contract_constants import ADMIN_WEB_HOSTNAME, BOARD_STAFF_REVIEW_SAMPLE_SIZE, BOARD_STAFF_TASK_STATUSES
from http_common import _log_event

SECTION_IDS = (
    "headline",
    "holdsDue",
    "escalations",
    "assisted",
    "sample",
    "market",
    "breakers",
    "suggestions",
    "promotion",
)


def _origin() -> str:
    origin = (os.environ.get("ADMIN_WEB_ORIGIN") or "").strip().rstrip("/")
    if origin:
        return origin
    return f"https://{ADMIN_WEB_HOSTNAME}"


def spa_url(fragment: str) -> str:
    return f"{_origin()}/siu-tin-dei?tab=board&section=review#{fragment}"


def _hkt_day_bounds(date_hkt: str) -> tuple[str, str]:
    start = datetime.fromisoformat(f"{date_hkt}T00:00:00").replace(tzinfo=board_hk.HKT)
    end = start + timedelta(days=1)
    return board_hk.to_iso(start), board_hk.to_iso(end)


def _yesterday_hkt(date_hkt: str) -> str:
    day = datetime.fromisoformat(f"{date_hkt}T12:00:00").replace(tzinfo=board_hk.HKT)
    return (day - timedelta(days=1)).date().isoformat()


def headline_pack(table: Any, settings: dict[str, Any], date_hkt: str) -> dict[str, Any]:
    counts = {status: 0 for status in BOARD_STAFF_TASK_STATUSES}
    for status in BOARD_STAFF_TASK_STATUSES:
        counts[status] = len(board_store.list_tasks(table, status, limit=200))
    start, end = _hkt_day_bounds(_yesterday_hkt(date_hkt))
    messages: dict[str, int] = {}
    for call in board_store.list_tool_calls(table, limit=400):
        created = str(call.get("createdAt") or "")
        if created < start or created >= end:
            continue
        if call.get("status") not in ("ok", "held"):
            continue
        channel = str(call.get("toolId") or "other")
        messages[channel] = messages.get(channel, 0) + 1
    executed = 0
    vetoed = 0
    for status, bucket in (("executed", "executed"), ("vetoed", "vetoed")):
        for hold in board_store.list_holds(table, status, limit=200):
            stamp = str(hold.get("executedAt") or hold.get("vetoedAt") or hold.get("updatedAt") or "")
            if start <= stamp < end:
                if bucket == "executed":
                    executed += 1
                else:
                    vetoed += 1
    utc_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    board_usage = board_store.load_usage_day(table, utc_day)
    staff_usage = board_store.load_staff_usage_day(table, utc_day)
    hkt_usage = board_store.load_staff_usage_day(table, date_hkt)
    return {
        "tasks": {
            "delivered": counts.get("delivered") or 0,
            "running": counts.get("running") or 0,
            "blocked": counts.get("needs_owner") or 0,
        },
        "messagesByChannel": messages,
        "holds": {"executed": executed, "vetoed": vetoed},
        "spend": {
            "boardUsd": float(board_usage.get("cost") or 0),
            "staffUsd": float(staff_usage.get("cost") or hkt_usage.get("cost") or 0),
            "budgetUsd": float((settings.get("staff") or {}).get("dailyBudgetUsd") or 0),
        },
        "pipeline": {},
        "content": {},
        "market": {},
    }


def _holds_due(table: Any) -> list[dict[str, Any]]:
    cutoff = board_hk.to_iso(datetime.now(timezone.utc) + timedelta(hours=24))
    out: list[dict[str, Any]] = []
    for hold in board_store.list_holds(table, "scheduled", limit=200):
        if str(hold.get("executeAt") or "") <= cutoff:
            out.append(
                {
                    "holdId": hold.get("holdId"),
                    "classKey": hold.get("classKey"),
                    "actionClass": hold.get("actionClass"),
                    "summary": hold.get("summary"),
                    "preview": hold.get("preview"),
                    "executeAt": hold.get("executeAt"),
                    "op": hold.get("op"),
                }
            )
    out.sort(key=lambda h: str(h.get("executeAt") or ""))
    return out


def _first_suggested_reply(table: Any, task: dict[str, Any]) -> dict[str, Any] | None:
    task_id = str(task.get("taskId") or "")
    for call in board_store.list_tool_calls(table, limit=200):
        if str(call.get("taskId") or "") != task_id:
            continue
        if call.get("status") not in ("held", "pending_approval"):
            continue
        return {
            "callId": call.get("callId"),
            "status": call.get("status"),
            "summary": call.get("summary"),
            "preview": call.get("resultPreview") or call.get("arguments"),
        }
    return None


def _escalations(table: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for task in board_store.list_tasks(table, "needs_owner", limit=100):
        out.append(
            {
                "taskId": task.get("taskId"),
                "assignee": task.get("assignee"),
                "brief": task.get("brief"),
                "eventRef": task.get("eventRef"),
                "suggestedReply": _first_suggested_reply(table, task),
            }
        )
    return out


def _sample(table: Any, settings: dict[str, Any], date_hkt: str) -> list[dict[str, Any]]:
    yesterday = _yesterday_hkt(date_hkt)
    start, end = _hkt_day_bounds(yesterday)
    size = int((settings.get("review") or {}).get("sampleSize") or BOARD_STAFF_REVIEW_SAMPLE_SIZE)
    pool: list[dict[str, Any]] = []
    try:
        import board_holds
        import board_tools
    except Exception:
        return []
    for call in board_store.list_tool_calls(table, limit=400):
        created = str(call.get("createdAt") or "")
        if created < start or created >= end:
            continue
        if call.get("status") != "ok":
            continue
        op = board_tools.REGISTRY.get(str(call.get("op") or ""))
        if op is None or not op.is_write:
            continue
        ctx = board_tools.ToolContext(
            table=table,
            settings=settings,
            persona_id=str(call.get("personaId") or ""),
            display_name=str(call.get("displayName") or ""),
            kind="review",
        )
        action_class, class_key = board_holds.classify(op, ctx, dict(call.get("arguments") or {}), settings)
        hours = board_holds.hold_hours(table, settings, action_class, class_key)
        if hours > 0:
            continue
        pool.append(
            {
                "callId": call.get("callId"),
                "summary": call.get("summary"),
                "preview": call.get("resultPreview") or call.get("arguments"),
                "op": call.get("op"),
                "classKey": class_key,
            }
        )
    rng = random.Random(date_hkt)
    rng.shuffle(pool)
    return pool[: max(1, size)]


def _narrative(table: Any, date_hkt: str) -> str:
    duty_id = f"review-headline:{date_hkt}"
    task = None
    for status in ("delivered", "review", "running", "queued"):
        for row in board_store.list_tasks(table, status, limit=100):
            ref = row.get("eventRef") or {}
            if ref.get("kind") == "duty" and str(ref.get("id") or "") == duty_id:
                task = row
                break
        if task:
            break
    if not task or task.get("status") != "delivered":
        return ""
    finished = str(task.get("finishedAt") or "")
    if finished:
        try:
            done = board_hk.as_hkt(board_hk.parse_iso(finished))
            deadline = datetime.fromisoformat(f"{date_hkt}T07:25:00").replace(tzinfo=board_hk.HKT)
            if done > deadline:
                return ""
        except ValueError:
            pass
    text = board_staff.read_deliverable(task) if hasattr(board_staff, "read_deliverable") else ""
    return (text or str(task.get("summary") or "")).strip()[:2000]


def compile(table: Any, settings: dict[str, Any], date_hkt: str) -> dict[str, Any]:
    narrative = _narrative(table, date_hkt)
    try:
        import board_holds

        suggestions = [row for row in board_holds.list_ramp(table) if row.get("eligibleForPromotion")]
    except Exception:
        suggestions = []
    try:
        import board_breakers

        breakers = [row for row in board_breakers.list_all(table) if row.get("tripped")]
    except Exception:
        breakers = []
    doc = {
        "date": date_hkt,
        "compiledAt": board_store.now_iso(),
        "headline": headline_pack(table, settings, date_hkt),
        "narrative": narrative,
        "holdsDue": _holds_due(table),
        "escalations": _escalations(table),
        "sample": _sample(table, settings, date_hkt),
        "breakers": breakers,
        "suggestions": suggestions,
        "assisted": [],
        "market": [],
        "promotion": [],
    }
    board_store.put_review_snapshot(table, date_hkt, doc)
    return doc


def render_digest_html(review: dict[str, Any]) -> str:
    date = html.escape(str(review.get("date") or ""))
    narrative = html.escape(str(review.get("narrative") or "").strip())
    headline = review.get("headline") or {}
    rows = [
        ("headline", "Headline numbers"),
        ("holdsDue", "On hold, executing soon"),
        ("escalations", "Escalations"),
        ("assisted", "Assisted posts"),
        ("sample", "Sample of what ran"),
        ("market", "Market and ideas"),
        ("breakers", "Tripped breakers"),
        ("suggestions", "Boundary suggestions"),
        ("promotion", "Production promotion"),
    ]
    links = "".join(
        f'<tr><td style="padding:8px 0;"><a href="{html.escape(spa_url(sid))}">{html.escape(label)}</a></td></tr>'
        for sid, label in rows
    )
    tasks = headline.get("tasks") or {}
    spend = headline.get("spend") or {}
    summary = (
        f"Delivered {tasks.get('delivered') or 0} · running {tasks.get('running') or 0} · "
        f"blocked {tasks.get('blocked') or 0}. Staff spend "
        f"{spend.get('staffUsd') or 0} / {spend.get('budgetUsd') or 0} USD."
    )
    narrative_html = f"<p>{narrative}</p>" if narrative else ""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" width="100%" '
        'style="max-width:640px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#111;">'
        f"<tr><td style=\"padding:16px 0;\"><h1 style=\"font-size:18px;margin:0;\">Siu Tin Dei daily review {date}</h1></td></tr>"
        f"<tr><td style=\"padding:0 0 12px 0;\">{html.escape(summary)}</td></tr>"
        f"<tr><td>{narrative_html}</td></tr>"
        f"<tr><td><table width=\"100%\">{links}</table></td></tr>"
        "</table>"
    )


def render_digest_text(review: dict[str, Any]) -> str:
    date = str(review.get("date") or "")
    lines = [f"Siu Tin Dei daily review {date}", ""]
    if review.get("narrative"):
        lines.extend([str(review["narrative"]), ""])
    labels = {
        "headline": "Headline numbers",
        "holdsDue": "On hold, executing soon",
        "escalations": "Escalations",
        "assisted": "Assisted posts",
        "sample": "Sample of what ran",
        "market": "Market and ideas",
        "breakers": "Tripped breakers",
        "suggestions": "Boundary suggestions",
        "promotion": "Production promotion",
    }
    for sid in SECTION_IDS:
        lines.append(f"{labels[sid]}: {spa_url(sid)}")
    return "\n".join(lines)


def send_digest(table: Any, settings: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    digest_to = str((settings.get("review") or {}).get("digestTo") or "").strip()
    if not digest_to:
        _log_event("info", tag="board_review_digest_skipped", reason="empty digestTo")
        return {"ok": True, "skipped": "empty digestTo"}
    if not board_mail.sending_enabled():
        _log_event("info", tag="board_review_digest_skipped", reason="sending disabled")
        return {"ok": True, "skipped": "sending disabled"}
    html_body = render_digest_html(review)
    text = render_digest_text(review)
    date = str(review.get("date") or "")
    plan = {
        "fromMailbox": "board",
        "to": [digest_to],
        "cc": [],
        "subject": f"Siu Tin Dei daily review {date}",
        "text": text,
        "html": html_body,
        "inReplyTo": "",
        "references": [],
        "threadId": "",
    }
    sent = board_mail.send_plan(table, plan, sent_by="board_review")
    review = {**review, "digestHtml": html_body, "digestSentAt": board_store.now_iso()}
    if review.get("date"):
        board_store.put_review_snapshot(table, str(review["date"]), review)
    return {"ok": True, "sent": sent}


def maybe_create_headline_duty(table: Any, settings: dict[str, Any]) -> dict[str, Any] | None:
    now = board_hk.now_hkt()
    if now.hour != 7 or now.minute > 14:
        return None
    date_hkt = now.date().isoformat()
    duty_id = f"review-headline:{date_hkt}"
    try:
        import board_triage

        if board_triage.find_open_event_task(table, "duty", duty_id):
            return None
    except Exception:
        pass
    for status in ("delivered", "failed", "cancelled"):
        for row in board_store.list_tasks(table, status, limit=50):
            ref = row.get("eventRef") or {}
            if ref.get("kind") == "duty" and str(ref.get("id") or "") == duty_id:
                return None
    pack = headline_pack(table, settings, date_hkt)
    import json

    brief = (
        "Write the three-sentence headline for today's review from this JSON\n\n"
        + json.dumps(pack, ensure_ascii=False)[:3500]
    )
    try:
        return board_staff.create_task(
            table,
            settings,
            assignee="business-analyst",
            origin="duty",
            brief=brief,
            deliverable_type="markdown",
            sla_hours=1,
            event_ref={"kind": "duty", "id": duty_id},
            created_by="board_review",
        )
    except board_staff.StaffError as exc:
        _log_event("info", tag="board_review_headline_duty_skipped", error=str(exc)[:200])
        return None


def handle_compile(event: dict[str, Any]) -> dict[str, Any]:
    if not board_store.event_targets_this_board(event):
        return {"ok": True, "skipped": "other_board"}
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    if not board_staff.enabled(settings):
        return {"ok": True, "skipped": "disabled"}
    date_hkt = str(event.get("date") or board_hk.today_hkt())
    review = compile(table, settings, date_hkt)
    return {"ok": True, "date": date_hkt, "compiledAt": review.get("compiledAt")}


def handle_send(event: dict[str, Any]) -> dict[str, Any]:
    if not board_store.event_targets_this_board(event):
        return {"ok": True, "skipped": "other_board"}
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    if not board_staff.enabled(settings):
        return {"ok": True, "skipped": "disabled"}
    date_hkt = str(event.get("date") or board_hk.today_hkt())
    review = board_store.get_review_snapshot(table, date_hkt)
    if not review:
        review = compile(table, settings, date_hkt)
    else:
        narrative = _narrative(table, date_hkt)
        if narrative and not review.get("narrative"):
            review["narrative"] = narrative
            board_store.put_review_snapshot(table, date_hkt, review)
    return send_digest(table, settings, review)
