"""WP4 daily review snapshot and digest email."""

from __future__ import annotations

import html
import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any

import board_hk
import board_mail
import board_staff
import board_store
from contract_constants import BOARD_STAFF_REVIEW_SAMPLE_SIZE, BOARD_STAFF_TASK_STATUSES
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
    "configGaps",
    "engineering",
    "promotion",
)


DIGEST_LIST_LIMIT = 12
DIGEST_TEXT_LIMIT = 280
SECTION_LABELS = {
    "headline": "Headline numbers",
    "holdsDue": "On hold, executing soon",
    "escalations": "Escalations",
    "assisted": "Assisted posts",
    "sample": "Sample of what ran",
    "market": "Market and ideas",
    "breakers": "Tripped breakers",
    "suggestions": "Boundary suggestions",
    "configGaps": "Unconfigured integrations",
    "engineering": "Engineering",
    "promotion": "Production promotion",
}


def _hkt_day_bounds(date_hkt: str) -> tuple[str, str]:
    start = datetime.fromisoformat(f"{date_hkt}T00:00:00").replace(tzinfo=board_hk.HKT)
    end = start + timedelta(days=1)
    return board_hk.to_iso(start), board_hk.to_iso(end)


def _yesterday_hkt(date_hkt: str) -> str:
    day = datetime.fromisoformat(f"{date_hkt}T12:00:00").replace(tzinfo=board_hk.HKT)
    return (day - timedelta(days=1)).date().isoformat()


_HEADLINE_OPEN = frozenset(
    {"queued", "running", "waiting_approval", "waiting_subtask", "review", "needs_owner"}
)


def _mail_disposition_counts(table: Any) -> dict[str, int]:
    replied = 0
    archived = 0
    open_n = 0
    for thread in board_store.list_mail_threads(table):
        disposition = str(thread.get("disposition") or "")
        if disposition == "archived":
            archived += 1
        elif disposition == "replied" or str(thread.get("lastDirection") or "") == "out":
            replied += 1
        else:
            open_n += 1
    return {"replied": replied, "archived": archived, "open": open_n}


def headline_pack(table: Any, settings: dict[str, Any], date_hkt: str) -> dict[str, Any]:
    day_start, day_end = _hkt_day_bounds(date_hkt)
    counts = {status: 0 for status in BOARD_STAFF_TASK_STATUSES}
    for status in BOARD_STAFF_TASK_STATUSES:
        rows = board_store.list_tasks(table, status, limit=200)
        if status in _HEADLINE_OPEN:
            counts[status] = len(rows)
            continue
        n = 0
        for task in rows:
            stamp = str(task.get("finishedAt") or task.get("updatedAt") or "")
            if day_start <= stamp < day_end:
                n += 1
        counts[status] = n
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
    out = {
        "tasks": {
            "delivered": counts.get("delivered") or 0,
            "running": (counts.get("running") or 0)
            + (counts.get("waiting_approval") or 0)
            + (counts.get("waiting_subtask") or 0),
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
        "mail": _mail_disposition_counts(table),
    }
    try:
        import board_progress

        out.update(board_progress.headline_pack(table, settings))
    except Exception as exc:
        _log_event("warning", tag="board_progress_headline_failed", error=str(exc)[:200])
    return out


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
    for status in ("delivered", "needs_owner", "review", "running", "queued"):
        for row in board_store.list_tasks(table, status, limit=100):
            ref = row.get("eventRef") or {}
            if ref.get("kind") == "duty" and str(ref.get("id") or "") == duty_id:
                task = row
                break
        if task:
            break
    if not task:
        return ""
    if task.get("status") != "delivered":
        last = task.get("lastReview") or {}
        if str(last.get("verdict") or "") != "accept":
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


def _assisted_section(table: Any, settings: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        import board_content

        return board_content.assisted_due(table, settings)
    except Exception:
        return []


def _market_section(table: Any) -> dict[str, Any]:
    try:
        import board_intel

        changes = board_intel.list_changes(table, 7)[:12]
        brief = board_intel.latest_brief(table)
    except Exception:
        changes = []
        brief = None
    return {"changes": changes, "latestBrief": brief}


def _cached_promotion(table: Any) -> dict[str, Any] | list[Any]:
    try:
        import board_code

        preview = board_code.cached_staging_preview(table)
    except Exception:
        return []
    return preview if isinstance(preview, dict) and preview else []


def _config_gaps_section(table: Any) -> list[dict[str, Any]]:
    try:
        import board_duties

        return board_duties.list_config_gaps(table)
    except Exception:
        return []


def _promotion_section() -> dict[str, Any]:
    """Live GitHub compare; only called from ``send_digest`` so ``compile`` (GET /review) stays a table read."""
    try:
        import board_code

        preview = board_code.staging_preview()
    except Exception as exc:
        return {"error": f"staging check failed: {str(exc)[:160]}", "fetchedAt": board_store.now_iso()}
    if isinstance(preview, dict):
        return {**preview, "fetchedAt": board_store.now_iso()}
    return {"error": "staging check returned no data", "fetchedAt": board_store.now_iso()}


def compile(table: Any, settings: dict[str, Any], date_hkt: str) -> dict[str, Any]:
    narrative = _narrative(table, date_hkt)
    try:
        import board_holds

        suggestions = [row for row in board_holds.list_ramp(table) if row.get("eligibleForPromotion")]
    except Exception:
        suggestions = []
    standup = board_store.get_cache(table, "standup:boundary-suggestions")
    if standup and isinstance(standup.get("payload"), dict):
        suggestions = list(standup["payload"].get("items") or []) + suggestions
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
        "assisted": _assisted_section(table, settings),
        "market": _market_section(table),
        "configGaps": _config_gaps_section(table),
        "engineering": _engineering_section(table),
        "promotion": _cached_promotion(table),
    }
    doc["digestHtml"] = render_digest_html(doc)
    board_store.put_review_snapshot(table, date_hkt, doc)
    return doc


def _clip(text: Any, limit: int = DIGEST_TEXT_LIMIT) -> str:
    raw = " ".join(str(text or "").split())
    if len(raw) <= limit:
        return raw
    return raw[: limit - 1].rstrip() + "…"


def _preview_blob(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _clip(value)
    if isinstance(value, dict):
        for key in ("summary", "text", "body", "message", "preview"):
            if value.get(key):
                return _clip(value.get(key))
        try:
            return _clip(json.dumps(value, ensure_ascii=False, default=str))
        except TypeError:
            return _clip(str(value))
    return _clip(str(value))


def _as_list(value: Any) -> list[Any]:
    return [row for row in value] if isinstance(value, list) else []


def _headline_lines(review: dict[str, Any]) -> list[str]:
    headline = review.get("headline") or {}
    tasks = headline.get("tasks") or {}
    holds = headline.get("holds") or {}
    spend = headline.get("spend") or {}
    lines = [
        (
            f"Delivered {tasks.get('delivered') or 0} · running {tasks.get('running') or 0} · "
            f"blocked {tasks.get('blocked') or 0}."
        ),
        f"Holds executed/vetoed {holds.get('executed') or 0}/{holds.get('vetoed') or 0}.",
        f"Staff spend {spend.get('staffUsd') or 0} / {spend.get('budgetUsd') or 0} USD.",
    ]
    pipeline = headline.get("pipeline") or {}
    if pipeline.get("weeklyTarget"):
        lines.append(
            f"Partnerships this week {pipeline.get('qualifiedThisWeek') or 0} / {pipeline.get('weeklyTarget')}."
        )
    content = headline.get("content") or {}
    if content:
        lines.append(
            f"Content next 7 days {content.get('scheduledNext7') or 0}; "
            f"{content.get('emptyChannels') or 0} empty channel(s)."
        )
    mail = headline.get("mail") or {}
    if mail:
        lines.append(
            f"Mail: {mail.get('replied') or 0} replied / {mail.get('archived') or 0} archived / "
            f"{mail.get('open') or 0} open."
        )
    narrative = str(review.get("narrative") or "").strip()
    if narrative:
        lines.insert(0, _clip(narrative, 2000))
    channels = headline.get("messagesByChannel") or {}
    if isinstance(channels, dict) and channels:
        bits = [f"{k} {v}" for k, v in channels.items()]
        lines.append("Messages: " + " · ".join(bits))
    return lines


def _hold_line(row: dict[str, Any]) -> str:
    parts = [
        _clip(row.get("summary") or row.get("op") or "Hold", 160),
        str(row.get("classKey") or row.get("actionClass") or "").strip(),
        str(row.get("executeAt") or "").strip(),
    ]
    line = " · ".join(p for p in parts if p)
    preview = _preview_blob(row.get("preview"))
    if preview:
        line = f"{line} — {preview}"
    return line


def _escalation_line(row: dict[str, Any]) -> str:
    brief = _clip(row.get("brief") or row.get("taskId") or "Escalation", 200)
    assignee = str(row.get("assignee") or "").strip()
    line = f"{brief} ({assignee})" if assignee else brief
    reply = row.get("suggestedReply") or {}
    if isinstance(reply, dict) and (reply.get("summary") or reply.get("preview")):
        line = f"{line} Suggested: {_preview_blob(reply.get('summary') or reply.get('preview'))}"
    return line


def _assisted_line(row: dict[str, Any]) -> str:
    slot = str(row.get("slotAt") or "")[:16]
    copy = _clip(row.get("copyZh") or row.get("copyEn") or "", 160)
    head = " · ".join(p for p in (str(row.get("channel") or "").strip(), slot) if p)
    return " — ".join(p for p in (head, copy) if p) or str(row.get("contentId") or "Post")


def _sample_line(row: dict[str, Any]) -> str:
    return _clip(row.get("summary") or row.get("op") or row.get("callId") or "Action", 200)


def _market_lines(review: dict[str, Any]) -> list[str]:
    market = review.get("market")
    if not isinstance(market, dict):
        return ["No market notes yet."]
    lines: list[str] = []
    changes = _as_list(market.get("changes"))[:DIGEST_LIST_LIMIT]
    if not changes:
        lines.append("No watchlist changes this week.")
    else:
        for change in changes:
            if isinstance(change, dict):
                lines.append(_clip(change.get("summary") or change.get("url") or "Change", 200))
    brief = market.get("latestBrief")
    if isinstance(brief, dict):
        lines.append(
            "Latest brief: " + _clip(brief.get("summary") or brief.get("taskId") or "available", 200)
        )
    return lines


def _breaker_line(row: dict[str, Any]) -> str:
    name = str(row.get("name") or "breaker")
    reason = _clip(row.get("reason") or "tripped", 200)
    return f"{name}: {reason}"


def _suggestion_line(row: dict[str, Any]) -> str:
    key = str(row.get("classKey") or "class")
    try:
        rate = float(row.get("rate") or 0) * 100
    except (TypeError, ValueError):
        rate = 0.0
    return f"{key}: {row.get('actions') or 0} actions, {rate:.1f}% veto"


def _config_gap_lines(review: dict[str, Any]) -> list[str]:
    items = [row for row in _as_list(review.get("configGaps")) if isinstance(row, dict)]
    if not items:
        return ["None."]
    lines: list[str] = []
    for row in items[:DIGEST_LIST_LIMIT]:
        gap = str(row.get("gapId") or "gap")
        reason = _clip(row.get("reason") or "", 200)
        lines.append(f"{gap}: {reason}" if reason else gap)
    return lines


def _engineering_section(table: Any) -> list[dict[str, Any]]:
    """Table-only open runner rows. Never fetch GitHub from compile."""
    try:
        import board_code

        return board_code.list_open_run_summaries(table)
    except Exception:
        return []


def _engineering_lines(review: dict[str, Any]) -> list[str]:
    rows = [row for row in _as_list(review.get("engineering")) if isinstance(row, dict)]
    if not rows:
        return ["No open board pull requests."]
    lines: list[str] = []
    for row in rows[:DIGEST_LIST_LIMIT]:
        pr = row.get("prNumber")
        ci = str(row.get("ciState") or "unknown")
        line = f"PR #{pr} CI {ci}"
        if ci == "failure":
            fail = _clip(row.get("failureLine") or "", 160)
            if fail:
                line = f"{line}: {fail}"
            line = f"{line} (ci-fix {row.get('ciFixRounds') or 0}/{row.get('ciFixMax') or 2})"
        can = row.get("canRevise")
        if can is False:
            line = f"{line} — runner cannot revise (Appendix A patch)."
        elif can is None:
            line = f"{line} — revise capability not cached yet."
        lines.append(line)
    return lines


def _promotion_lines(review: dict[str, Any]) -> list[str]:
    promo = review.get("promotion")
    if isinstance(promo, list):
        promo = promo[0] if promo and isinstance(promo[0], dict) else {}
    if not isinstance(promo, dict) or not promo:
        return ["Staging status is checked against GitHub when the digest is sent."]
    if promo.get("error"):
        return [_clip(promo.get("error"), 200)]
    lines: list[str] = []
    behind = promo.get("behindBy") or 0
    can_promote = bool(promo.get("canPromote"))
    if behind:
        lines.append(f"staging is {behind} commit(s) behind main. Rebase before promoting.")
    elif can_promote:
        lines.append("staging is current with main and has commits to promote.")
    else:
        lines.append("staging is current with main.")
    commits = [c for c in _as_list(promo.get("commits")) if isinstance(c, dict)]
    for commit in commits[:DIGEST_LIST_LIMIT]:
        sha = str(commit.get("sha") or "")[:8]
        msg = _clip(commit.get("message") or "", 160)
        lines.append(" ".join(p for p in (sha, msg) if p))
    fetched = str(promo.get("fetchedAt") or "").strip()
    if fetched:
        lines.append(f"Fetched at {fetched}.")
    return lines


def digest_section_lines(review: dict[str, Any]) -> list[tuple[str, str, list[str]]]:
    """(section id, title, body lines) — same data the Daily review page shows."""
    holds = [_hold_line(row) for row in _as_list(review.get("holdsDue"))[:DIGEST_LIST_LIMIT] if isinstance(row, dict)]
    escalations = [
        _escalation_line(row) for row in _as_list(review.get("escalations"))[:DIGEST_LIST_LIMIT] if isinstance(row, dict)
    ]
    assisted = [
        _assisted_line(row) for row in _as_list(review.get("assisted"))[:DIGEST_LIST_LIMIT] if isinstance(row, dict)
    ]
    sample = [_sample_line(row) for row in _as_list(review.get("sample"))[:DIGEST_LIST_LIMIT] if isinstance(row, dict)]
    breakers = [
        _breaker_line(row)
        for row in _as_list(review.get("breakers"))[:DIGEST_LIST_LIMIT]
        if isinstance(row, dict) and row.get("tripped")
    ]
    suggestions = [
        _suggestion_line(row) for row in _as_list(review.get("suggestions"))[:DIGEST_LIST_LIMIT] if isinstance(row, dict)
    ]
    return [
        ("headline", SECTION_LABELS["headline"], _headline_lines(review)),
        ("holdsDue", SECTION_LABELS["holdsDue"], holds or ["None waiting."]),
        ("escalations", SECTION_LABELS["escalations"], escalations or ["None waiting."]),
        ("assisted", SECTION_LABELS["assisted"], assisted or ["No assisted packs are due."]),
        ("sample", SECTION_LABELS["sample"], sample or ["No hold-0 actions yesterday."]),
        ("market", SECTION_LABELS["market"], _market_lines(review)),
        ("breakers", SECTION_LABELS["breakers"], breakers or ["None tripped."]),
        ("suggestions", SECTION_LABELS["suggestions"], suggestions or ["No class is eligible to drop its hold yet."]),
        ("configGaps", SECTION_LABELS["configGaps"], _config_gap_lines(review)),
        ("engineering", SECTION_LABELS["engineering"], _engineering_lines(review)),
        ("promotion", SECTION_LABELS["promotion"], _promotion_lines(review)),
    ]


def render_digest_html(review: dict[str, Any]) -> str:
    date = html.escape(str(review.get("date") or ""))
    blocks: list[str] = []
    for _sid, title, lines in digest_section_lines(review):
        items = "".join(f"<li>{html.escape(line)}</li>" for line in lines)
        blocks.append(
            "<tr><td style=\"padding:12px 0 4px 0;\">"
            f"<h2 style=\"font-size:15px;margin:0 0 6px 0;\">{html.escape(title)}</h2>"
            f"<ul style=\"margin:0;padding-left:18px;\">{items}</ul>"
            "</td></tr>"
        )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" width="100%" '
        'style="max-width:640px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#111;">'
        f"<tr><td style=\"padding:16px 0;\"><h1 style=\"font-size:18px;margin:0;\">Siu Tin Dei daily review {date}</h1></td></tr>"
        f"{''.join(blocks)}"
        "</table>"
    )


def render_digest_text(review: dict[str, Any]) -> str:
    date = str(review.get("date") or "")
    lines = [f"Siu Tin Dei daily review {date}", ""]
    for _sid, title, body in digest_section_lines(review):
        lines.append(title)
        for item in body:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def send_digest(table: Any, settings: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    digest_to = str((settings.get("review") or {}).get("digestTo") or "").strip()
    if not digest_to:
        _log_event("info", tag="board_review_digest_skipped", reason="empty digestTo")
        return {"ok": True, "skipped": "empty digestTo"}
    if not board_mail.sending_enabled():
        _log_event("info", tag="board_review_digest_skipped", reason="sending disabled")
        return {"ok": True, "skipped": "sending disabled"}
    review = {**review, "promotion": _promotion_section()}
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
    date_hkt = board_hk.today_hkt()
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
    try:
        maybe_create_headline_duty(table, settings)
    except Exception as exc:
        _log_event("warning", tag="board_review_headline_duty_failed", error=str(exc)[:200])
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
