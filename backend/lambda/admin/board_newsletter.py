"""Fortnightly parent/provider newsletter (WP8). Double opt-in, SES bulk send."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from email.message import EmailMessage
from typing import Any
import board_hk
import board_mail
import board_outreach
import board_pii
import board_staff
import board_store
from contract_constants import BOARD_STAFF_NEWSLETTER_LISTS
from http_common import _json_response, _log_event, _parse_json_body

LISTS = tuple(BOARD_STAFF_NEWSLETTER_LISTS)
BATCH = 50
TEMPLATE_NAME = "lxsoftware-siutindei-newsletter-issue"
CONFIG_SET = (os.environ.get("NEWSLETTER_CONFIG_SET") or "lxsoftware-admin-siutindei-newsletter").strip()
FROM_LOCAL = (os.environ.get("NEWSLETTER_FROM_LOCAL_PART") or "news").strip() or "news"


class NewsletterError(ValueError):
    """Invalid newsletter input or state."""


def from_address() -> str:
    return f"{FROM_LOCAL}@{board_mail.mail_domain()}"


def _html_response(status: int, body: str) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "text/html; charset=utf-8"},
        "body": body,
    }


def _rate_limited(table: Any, ip: str, prefix: str) -> bool:
    hour = board_hk.now_hkt().strftime("%Y-%m-%d-%H")
    name = f"{prefix}:{ip}:{hour}"
    return board_store.bump_cache_count(table, name, ttl_seconds=3600) > 100


def _confirm_over_daily(table: Any, digest: str) -> bool:
    name = f"nl-confirm:{digest}:{board_hk.today_hkt()}"
    return board_store.bump_cache_count(table, name, ttl_seconds=86400) > 3


def make_token(kind: str, list_name: str, digest: str) -> str:
    return board_outreach.make_unsub_token(f"{kind}:{list_name}:{digest}")


def parse_token(token: str) -> tuple[str, str, str] | None:
    raw = board_outreach.parse_unsub_token(token)
    if not raw or raw.count(":") < 2:
        return None
    kind, list_name, digest = raw.split(":", 2)
    if kind not in {"c", "u"} or list_name not in LISTS or not digest:
        return None
    return kind, list_name, digest


def confirm_url(list_name: str, digest: str) -> str:
    return f"{board_outreach.public_api_base()}/public/newsletter/confirm/{make_token('c', list_name, digest)}"


def unsubscribe_url(list_name: str, digest: str) -> str:
    return f"{board_outreach.public_api_base()}/public/newsletter/unsubscribe/{make_token('u', list_name, digest)}"


def _sub_row(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict) and "email" in raw:
        return raw
    unwrapped = board_store._from_ddb_nested(raw)  # noqa: SLF001
    return unwrapped if isinstance(unwrapped, dict) else {}


def handle_subscribe(event: dict[str, Any]) -> dict[str, Any]:
    table = board_store.records_table()
    http = (event.get("requestContext") or {}).get("http") or {}
    ip = str(http.get("sourceIp") or "0.0.0.0")
    if _rate_limited(table, ip, "nl-sub-ip"):
        return _json_response(429, {"message": "Too many requests"})
    body = _parse_json_body(event)
    list_name = str(body.get("list") or "").strip()
    email = board_pii.normalize_email(str(body.get("email") or ""))
    lang = str(body.get("lang") or "en").strip() or "en"
    if lang not in {"en", "zh-HK"}:
        lang = "en"
    generic = {"ok": True, "message": "If that address can be added, we sent a confirmation email."}
    if list_name not in LISTS or not email or "@" not in email:
        return _json_response(200, generic)
    digest = board_outreach.suppress_digest(email)
    now = board_store.now_iso()
    for other in LISTS:
        other_row = _sub_row(board_store.get_newsletter_sub(table, digest, other))
        if other != list_name and other_row.get("confirmedAt") and not other_row.get("unsubscribedAt"):
            return _json_response(200, generic)
    existing = _sub_row(board_store.get_newsletter_sub(table, digest, list_name))
    if existing.get("confirmedAt") and not existing.get("unsubscribedAt"):
        return _json_response(200, generic)
    if existing.get("confirmSentAt") and not existing.get("confirmedAt") and not existing.get("unsubscribedAt"):
        return _json_response(200, generic)
    if _confirm_over_daily(table, digest):
        return _json_response(200, generic)
    doc = {
        **existing,
        "digest": digest,
        "email": email,
        "list": list_name,
        "lang": lang,
        "source": "public",
        "confirmedAt": existing.get("confirmedAt") or "",
        "unsubscribedAt": existing.get("unsubscribedAt") or "",
        "createdAt": existing.get("createdAt") or now,
        "updatedAt": now,
        "confirmSentAt": now,
    }
    board_store.put_newsletter_sub(table, digest, list_name, doc)
    _send_confirm(table, email, list_name, digest, lang)
    return _json_response(200, generic)


def _send_confirm(table: Any, email: str, list_name: str, digest: str, lang: str) -> None:
    if not board_mail.sending_enabled():
        _log_event("info", tag="board_newsletter_confirm_skipped", reason="sending off")
        return
    url = confirm_url(list_name, digest)
    if lang.startswith("zh"):
        subject = "確認訂閱 Siu Tin Dei 電子報"
        text = (
            "請開啟此連結確認訂閱（家長／機構資訊，可隨時取消）：\n"
            f"{url}\n\n用途：發送活動與產品更新。取消：同一封郵件的確認頁或日後電子報內的連結。"
        )
    else:
        subject = "Confirm your Siu Tin Dei newsletter"
        text = (
            "Open this link to confirm your subscription (activity and product updates; you can unsubscribe any time):\n"
            f"{url}\n\nPurpose: send activity and product updates. Unsubscribe: the link in every issue, or this confirm page."
        )
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_address()
    msg["To"] = email
    msg.set_content(text)
    raw = msg.as_bytes()
    try:
        board_outreach._ses_client().send_email(  # noqa: SLF001
            FromEmailAddress=from_address(),
            Destination={"ToAddresses": [email]},
            Content={"Raw": {"Data": raw}},
            ConfigurationSetName=CONFIG_SET,
        )
        board_mail.ingest_bytes(table, raw, direction="outbound", source="newsletter-confirm")
    except Exception as exc:
        _log_event("warning", tag="board_newsletter_confirm_failed", error=str(exc)[:200])


def handle_confirm(event: dict[str, Any], token: str) -> dict[str, Any]:
    table = board_store.records_table()
    http = (event.get("requestContext") or {}).get("http") or {}
    ip = str(http.get("sourceIp") or "0.0.0.0")
    if _rate_limited(table, ip, "nl-confirm-ip"):
        return _html_response(429, "<!doctype html><html><body><p>Too many requests.</p></body></html>")
    parsed = parse_token(token)
    if not parsed or parsed[0] != "c":
        return _html_response(400, "<!doctype html><html><body><p>This confirmation link is not valid.</p></body></html>")
    _, list_name, digest = parsed
    row = _sub_row(board_store.get_newsletter_sub(table, digest, list_name))
    if not row or row.get("list") != list_name:
        return _html_response(400, "<!doctype html><html><body><p>This confirmation link is not valid.</p></body></html>")
    now = board_store.now_iso()
    row["confirmedAt"] = row.get("confirmedAt") or now
    row["unsubscribedAt"] = ""
    row["updatedAt"] = now
    board_store.put_newsletter_sub(table, digest, list_name, row)
    return _html_response(200, "<!doctype html><html><body><p>You are subscribed. Thank you.</p></body></html>")


def handle_unsubscribe(event: dict[str, Any], method: str, token: str) -> dict[str, Any]:
    table = board_store.records_table()
    http = (event.get("requestContext") or {}).get("http") or {}
    ip = str(http.get("sourceIp") or "0.0.0.0")
    if _rate_limited(table, ip, "nl-unsub-ip"):
        if method == "POST":
            return {"statusCode": 429, "headers": {"content-type": "text/plain"}, "body": ""}
        return _html_response(429, "<!doctype html><html><body><p>Too many requests.</p></body></html>")
    parsed = parse_token(token)
    if not parsed or parsed[0] != "u":
        if method == "POST":
            return {"statusCode": 400, "headers": {"content-type": "text/plain"}, "body": ""}
        return _html_response(400, "<!doctype html><html><body><p>This unsubscribe link is not valid.</p></body></html>")
    _, list_name, digest = parsed
    row = _sub_row(board_store.get_newsletter_sub(table, digest, list_name))
    email = str((row or {}).get("email") or "")
    if row:
        now = board_store.now_iso()
        row["unsubscribedAt"] = now
        row["updatedAt"] = now
        board_store.put_newsletter_sub(table, digest, list_name or str(row.get("list") or "parents"), row)
    if method == "POST":
        return {"statusCode": 200, "headers": {"content-type": "text/plain"}, "body": ""}
    return _html_response(200, "<!doctype html><html><body><p>You are unsubscribed.</p></body></html>")


def recipients(table: Any, list_name: str, *, cursor: str | None = None, limit: int = 200) -> tuple[list[dict[str, Any]], str | None]:
    raw_rows, next_cursor = board_store.list_newsletter_subs(table, list_name, limit=limit, cursor=cursor)
    out: list[dict[str, Any]] = []
    for raw in raw_rows:
        row = _sub_row(raw)
        email = board_pii.normalize_email(str(row.get("email") or ""))
        if not row.get("confirmedAt") or row.get("unsubscribedAt") or not email:
            continue
        out.append(row)
    return out, next_cursor


def _issue_key(issue_id: str) -> dict[str, str]:
    return {"pk": board_store.board_pk(f"newsletter#issue#{issue_id}"), "sk": "META"}


def put_issue(table: Any, doc: dict[str, Any]) -> None:
    table.put_item(
        Item={
            **_issue_key(str(doc["issueId"])),
            "gsi1pk": board_store.board_pk("newsletter#issues"),
            "gsi1sk": str(doc.get("createdAt") or ""),
            **board_store._to_ddb_nested(doc),  # noqa: SLF001
        }
    )


def get_issue(table: Any, issue_id: str) -> dict[str, Any] | None:
    res = table.get_item(Key=_issue_key(issue_id))
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = board_store._from_ddb_nested(board_store._strip_keys(item))  # noqa: SLF001
    return doc if isinstance(doc, dict) else None


def render_html(markdown: str) -> str:
    body = []
    for line in str(markdown or "").splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("# "):
            body.append(f"<h1>{_esc(text[2:])}</h1>")
        elif text.startswith("## "):
            body.append(f"<h2>{_esc(text[3:])}</h2>")
        else:
            body.append(f"<p>{_esc(text)}</p>")
    inner = "".join(body) or f"<p>{_esc(markdown)}</p>"
    return (
        "<!doctype html><html><body style=\"font-family:system-ui,sans-serif;color:#1a1a1a;"
        f"background:#fff8f0;padding:24px\">{inner}</body></html>"
    )


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def draft_issue(table: Any, settings: dict[str, Any], *, list_name: str, markdown: str = "") -> dict[str, Any]:
    if list_name not in LISTS:
        raise NewsletterError(f"list must be one of {', '.join(LISTS)}")
    if not markdown.strip():
        markdown = _default_markdown(table, settings, list_name)
    now = board_store.now_iso()
    issue_id = board_store.new_id()
    html = render_html(markdown)
    doc = {
        "issueId": issue_id,
        "list": list_name,
        "status": "draft",
        "markdown": markdown[:20000],
        "html": html[:80000],
        "subject": _subject_from_markdown(markdown, list_name),
        "metrics": {"sent": 0, "opens": 0, "clicks": 0, "bounces": 0, "complaints": 0},
        "createdAt": now,
        "updatedAt": now,
    }
    put_issue(table, doc)
    return doc


def _subject_from_markdown(markdown: str, list_name: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()[:120]
    return f"Siu Tin Dei — {list_name} update"


def _default_markdown(table: Any, settings: dict[str, Any], list_name: str) -> str:
    cutoff = board_hk.to_iso(board_hk.now_hkt() - timedelta(days=14))
    items = []
    for row in board_store.list_content(table, "published", limit=80):
        if str(row.get("publishedAt") or row.get("slotAt") or "") >= cutoff:
            items.append(f"- {row.get('copyEn') or row.get('copyZh') or row.get('pillar')}")
    catalog = ""
    try:
        import board_product

        catalog = json.dumps(
            board_product.op_catalog_health(type("Ctx", (), {"table": table, "settings": settings})(), {}),
            default=str,
        )[:800]
    except Exception:
        catalog = ""
    lines = [
        f"# Siu Tin Dei fortnightly ({list_name})",
        "",
        "## From the last two weeks",
        *(items[:12] or ["- New activities this fortnight — see the site."]),
        "",
        "## Catalogue",
        catalog or "See siutindei.com for listings.",
    ]
    return "\n".join(lines)


def _ensure_template(ses: Any) -> None:
    try:
        ses.get_email_template(TemplateName=TEMPLATE_NAME)
        return
    except Exception:
        pass
    ses.create_email_template(
        TemplateName=TEMPLATE_NAME,
        TemplateContent={
            "Subject": "{{subject}}",
            "Text": "{{text}}\n\nUnsubscribe: {{unsub}}",
            "Html": "{{html}}<p style=\"font-size:12px\"><a href=\"{{unsub}}\">Unsubscribe</a></p>",
        },
    )


def _claim_issue_sending(table: Any, issue_id: str) -> bool:
    try:
        table.update_item(
            Key=_issue_key(issue_id),
            UpdateExpression="SET #st = :sending, updatedAt = :now",
            ConditionExpression="attribute_not_exists(#st) OR #st = :draft OR #st = :sending",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":sending": "sending",
                ":draft": "draft",
                ":now": board_store.now_iso(),
            },
        )
        return True
    except Exception as exc:
        _log_event("warning", tag="board_newsletter_claim_failed", error=str(exc)[:200])
        return False


def send_issue(table: Any, settings: dict[str, Any], *, issue_id: str, list_name: str) -> dict[str, Any]:
    if not board_staff.enabled(settings):
        return {"error": "staff disabled"}
    if not board_mail.sending_enabled():
        return {"error": "email sending is switched off"}
    if list_name not in LISTS:
        return {"error": f"list must be one of {', '.join(LISTS)}"}
    issue = get_issue(table, issue_id)
    if not issue:
        return {"error": "issue not found"}
    if issue.get("status") == "sent":
        return {"ok": True, "sent": 0, "issueId": issue_id, "noop": True}
    if not _claim_issue_sending(table, issue_id):
        latest = get_issue(table, issue_id)
        if latest and latest.get("status") == "sent":
            return {"ok": True, "sent": 0, "issueId": issue_id, "noop": True}
        return {"error": "could not claim issue"}
    issue = get_issue(table, issue_id) or issue
    ses = board_outreach._ses_client()  # noqa: SLF001
    _ensure_template(ses)
    sent_through = int(issue.get("sentThrough") or 0)
    metrics = dict(issue.get("metrics") or {})
    sent = int(metrics.get("sent") or 0)
    offset = 0
    cursor = None
    saw_any = False
    while True:
        people, cursor = recipients(table, list_name, cursor=cursor, limit=BATCH)
        if not people and not cursor:
            break
        saw_any = saw_any or bool(people)
        if offset + len(people) <= sent_through:
            offset += len(people)
            if not cursor:
                break
            continue
        start = max(0, sent_through - offset)
        chunk = people[start:]
        entries = []
        for row in chunk:
            digest = str(row.get("digest") or board_outreach.suppress_digest(str(row.get("email") or "")))
            unsub = unsubscribe_url(list_name, digest)
            entries.append(
                {
                    "Destination": {"ToAddresses": [row["email"]]},
                    "ReplacementEmailContent": {
                        "ReplacementTemplate": {
                            "ReplacementTemplateData": json.dumps(
                                {
                                    "subject": issue.get("subject") or "Siu Tin Dei",
                                    "html": issue.get("html") or "",
                                    "text": issue.get("markdown") or "",
                                    "unsub": unsub,
                                }
                            )
                        }
                    },
                }
            )
        if entries:
            result = ses.send_bulk_email(
                FromEmailAddress=from_address(),
                DefaultContent={"Template": {"TemplateName": TEMPLATE_NAME, "TemplateData": json.dumps({"subject": "", "html": "", "text": "", "unsub": ""})}},
                BulkEmailEntries=entries,
                ConfigurationSetName=CONFIG_SET,
                DefaultEmailTags=[{"Name": "issueId", "Value": str(issue_id)}],
            )
            results = (result or {}).get("BulkEmailEntryResults") or []
            if results:
                success = sum(1 for row in results if str(row.get("Status") or "").upper() == "SUCCESS")
                failures = [row for row in results if str(row.get("Status") or "").upper() != "SUCCESS"]
                if failures:
                    _log_event("warning", tag="board_newsletter_bulk_failed", count=len(failures))
            else:
                success = len(entries)
            sent += success
        offset += len(people)
        sent_through = offset
        issue["sentThrough"] = sent_through
        issue["metrics"] = {**metrics, "sent": sent}
        issue["status"] = "sending"
        issue["updatedAt"] = board_store.now_iso()
        put_issue(table, issue)
        if not cursor:
            break
    if not saw_any and sent == 0:
        issue["status"] = "draft"
        put_issue(table, issue)
        return {"error": "no confirmed subscribers"}
    metrics["sent"] = sent
    issue["metrics"] = metrics
    issue["status"] = "sent"
    issue["sentAt"] = board_store.now_iso()
    issue["sentList"] = list_name
    issue["updatedAt"] = issue["sentAt"]
    put_issue(table, issue)
    return {"ok": True, "sent": sent, "issueId": issue_id}


def handle_ses_events(records: list[dict[str, Any]]) -> dict[str, Any]:
    table = board_store.records_table()
    handled = 0
    for record in records:
        body = record.get("body")
        if not isinstance(body, str):
            continue
        try:
            envelope = json.loads(body)
        except json.JSONDecodeError:
            continue
        if envelope.get("Type") == "Notification" and envelope.get("Message"):
            try:
                envelope = json.loads(envelope["Message"])
            except json.JSONDecodeError:
                continue
        event_type = str(envelope.get("eventType") or envelope.get("notificationType") or "").lower()
        mail = envelope.get("mail") or {}
        tags = mail.get("tags") or {}
        raw_issue = tags.get("issueId") or tags.get("issueid")
        issue_id = str(raw_issue[0] if isinstance(raw_issue, list) and raw_issue else raw_issue or "")
        destinations = [board_pii.normalize_email(str(x)) for x in (mail.get("destination") or []) if x]
        if event_type in {"open", "click"} and issue_id:
            issue = get_issue(table, issue_id)
            if issue:
                metrics = dict(issue.get("metrics") or {})
                key = "opens" if event_type == "open" else "clicks"
                metrics[key] = int(metrics.get(key) or 0) + 1
                issue["metrics"] = metrics
                put_issue(table, issue)
                handled += 1
        bounce = envelope.get("bounce") or {}
        hard = event_type == "bounce" and str(bounce.get("bounceType") or "").lower() == "permanent"
        complaint = event_type == "complaint"
        if (hard or complaint) and destinations:
            for addr in destinations:
                board_outreach.suppress(table, email=addr, reason="newsletter bounce" if hard else "newsletter complaint")
            if issue_id:
                issue = get_issue(table, issue_id)
                if issue:
                    metrics = dict(issue.get("metrics") or {})
                    key = "complaints" if complaint else "bounces"
                    metrics[key] = int(metrics.get(key) or 0) + 1
                    issue["metrics"] = metrics
                    put_issue(table, issue)
            handled += 1
    return {"ok": True, "handled": handled}


def op_draft_issue(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    try:
        doc = draft_issue(
            ctx.table,
            ctx.settings,
            list_name=str(args.get("list") or ""),
            markdown=str(args.get("markdown") or ""),
        )
    except NewsletterError as exc:
        return {"error": str(exc)}
    return {"issue": {k: doc.get(k) for k in ("issueId", "list", "subject", "status", "createdAt")}}


def op_send(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    return send_issue(
        ctx.table,
        ctx.settings,
        issue_id=str(args.get("issueId") or ""),
        list_name=str(args.get("list") or ""),
    )
