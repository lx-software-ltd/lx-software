"""Cold outreach send, unsubscribe, SES bounce/complaint handling."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any

import boto3

import board_breakers
import board_hk
import board_mail
import board_pii
import board_prospects
import board_sequences
import board_store
from contract_constants import (
    BOARD_STAFF_COMPLAINT_RATE_BREAKER,
    BOARD_STAFF_BOUNCE_RATE_BREAKER,
    BOARD_STAFF_OUTREACH_MAX_TOUCHES,
)
from http_common import _json_response, _log_event

CONFIG_SET = "lxsoftware-admin-siutindei-outreach"
REPLY_TO_LOCAL = "partnerships"
UNSUB_WORDS = re.compile(r"unsubscribe|取消|不要再|退訂", re.I)
IDENTITY_CACHE_TTL = 3600
_sesv2: Any = None
_identity_cache: tuple[float, bool] | None = None
_signing_secret: str | None = None


class OutreachError(ValueError):
    def __init__(self, message: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.payload = payload or {"error": message}


def sending_domain() -> str:
    return (os.environ.get("OUTREACH_SENDING_DOMAIN") or "partners.siutindei.com").strip()


def from_local_part() -> str:
    return (os.environ.get("OUTREACH_FROM_LOCAL_PART") or "partnerships").strip()


def from_address() -> str:
    return f"{from_local_part()}@{sending_domain()}"


def reply_to_address() -> str:
    return f"{REPLY_TO_LOCAL}@{board_mail.mail_domain()}"


def public_api_base() -> str:
    return (os.environ.get("PUBLIC_API_BASE_URL") or "").rstrip("/")


def signup_url() -> str:
    return (os.environ.get("PROVIDER_SIGNUP_URL") or "https://siutindei.com").strip()


def _ses_client() -> Any:
    global _sesv2
    if _sesv2 is None:
        _sesv2 = boto3.client("sesv2")
    return _sesv2


def reset_caches_for_tests() -> None:
    global _sesv2, _identity_cache, _signing_secret
    _sesv2 = None
    _identity_cache = None
    _signing_secret = None


def signing_secret() -> str:
    global _signing_secret
    if _signing_secret:
        return _signing_secret
    plain = (os.environ.get("BOARD_LINK_SIGNING_SECRET") or "").strip()
    if plain:
        _signing_secret = plain
        return plain
    arn = (os.environ.get("BOARD_LINK_SIGNING_SECRET_ARN") or "").strip()
    if not arn:
        raise OutreachError("link signing secret is not configured")
    from admin_runtime import _get_secretsmanager_client
    from openrouter_client import read_secret_string

    _signing_secret = read_secret_string(
        _get_secretsmanager_client(), arn, what="board link signing key"
    ).strip()
    return _signing_secret


def make_unsub_token(prospect_id: str) -> str:
    pid = str(prospect_id or "").encode("utf-8")
    mac = hmac.new(signing_secret().encode("utf-8"), pid, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(pid + mac).decode("ascii").rstrip("=")


def parse_unsub_token(token: str) -> str | None:
    text = str(token or "").strip()
    if not text:
        return None
    pad = "=" * ((4 - len(text) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(text + pad)
    except Exception:
        return None
    if len(raw) < 16:
        return None
    pid_bytes, mac = raw[:-16], raw[-16:]
    expected = hmac.new(signing_secret().encode("utf-8"), pid_bytes, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        return pid_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None


def unsubscribe_url(prospect_id: str) -> str:
    return f"{public_api_base()}/public/outreach/unsubscribe/{make_unsub_token(prospect_id)}"


def suppress_digest(value: str) -> str:
    return hashlib.sha256(str(value or "").strip().lower().encode("utf-8")).hexdigest()[:32]


def is_suppressed(table: Any, email: str) -> bool:
    addr = board_pii.normalize_email(email)
    if not addr:
        return False
    if board_store.get_suppress(table, suppress_digest(addr)):
        return True
    if "@" in addr and board_store.get_suppress(table, suppress_digest(addr.split("@", 1)[1])):
        return True
    return False


def suppress(table: Any, *, email: str = "", domain: str = "", prospect: dict[str, Any] | None = None, reason: str = "") -> None:
    now = board_store.now_iso()
    doc = {"reason": reason[:200], "createdAt": now, "prospectId": (prospect or {}).get("prospectId") or ""}
    addr = board_pii.normalize_email(email)
    if addr:
        board_store.put_suppress(table, suppress_digest(addr), doc)
    if domain:
        board_store.put_suppress(table, suppress_digest(domain.lower()), {**doc, "kind": "domain"})
    if prospect:
        prospect["stage"] = "suppressed"
        prospect["suppressReason"] = reason[:200]
        prospect["updatedAt"] = now
        board_store.put_prospect(table, prospect)


def identity_verified(force: bool = False) -> bool:
    global _identity_cache
    now = datetime.now(timezone.utc).timestamp()
    if not force and _identity_cache and now - _identity_cache[0] < IDENTITY_CACHE_TTL:
        return _identity_cache[1]
    flag = (os.environ.get("OUTREACH_IDENTITY_VERIFIED") or "").strip().lower()
    if flag == "true":
        _identity_cache = (now, True)
        return True
    if flag == "false":
        _identity_cache = (now, False)
        return False
    try:
        resp = _ses_client().get_email_identity(EmailIdentity=sending_domain())
        ok = bool(resp.get("VerifiedForSendingStatus"))
    except Exception as exc:
        _log_event("warning", tag="board_outreach_identity_check_failed", error=str(exc)[:200])
        ok = False
    _identity_cache = (now, ok)
    return ok


def language_for_name(name: str) -> str:
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in name)
    has_latin = any(ch.isascii() and ch.isalpha() for ch in name)
    if has_cjk and not has_latin:
        return "zh-HK"
    if has_latin and not has_cjk:
        return "en"
    return "both"


def _fill(template: str, mapping: dict[str, str]) -> str:
    out = template
    for key, value in mapping.items():
        out = out.replace("{" + key + "}", value)
    return out


def render_message(
    table: Any,
    prospect: dict[str, Any],
    step: dict[str, Any],
    *,
    personalisation: str = "",
) -> tuple[str, str]:
    name = str(prospect.get("name") or "")
    mapping = {
        "name": name,
        "fitNote": str(prospect.get("fitNote") or personalisation or "you host activities for children in Hong Kong"),
        "signupUrl": signup_url(),
        "unsubscribeUrl": unsubscribe_url(str(prospect.get("prospectId") or "")),
        "personalisation": personalisation[:400],
    }
    lang = language_for_name(name)
    subject_en = _fill(str(step.get("subjectEn") or ""), mapping)
    subject_zh = _fill(str(step.get("subjectZh") or ""), mapping)
    body_en = _fill(str(step.get("bodyEn") or ""), mapping)
    body_zh = _fill(str(step.get("bodyZh") or ""), mapping)
    if personalisation:
        extra = personalisation[:400]
        body_en = extra + "\n\n" + body_en
        body_zh = extra + "\n\n" + body_zh
    if lang == "zh-HK":
        return subject_zh or subject_en, body_zh or body_en
    if lang == "en":
        return subject_en or subject_zh, body_en or body_zh
    subject = subject_en or subject_zh
    body = (body_en or "") + ("\n\n----------\n\n" + body_zh if body_zh else "")
    return subject, body


def trailing_rates(table: Any, *, days: int = 7) -> dict[str, Any]:
    today = board_hk.now_hkt().date()
    sent = bounces = complaints = 0
    history: list[dict[str, Any]] = []
    for offset in range(days):
        day = (today - timedelta(days=offset)).isoformat()
        row = board_store.load_outreach_day(table, day)
        sent += int(row.get("sent") or 0)
        bounces += int(row.get("bounces") or 0)
        complaints += int(row.get("complaints") or 0)
        history.append({"date": day, **row})
    bounce_rate = (bounces / sent) if sent else 0.0
    complaint_rate = (complaints / sent) if sent else 0.0
    return {
        "days": days,
        "sent": sent,
        "bounces": bounces,
        "complaints": complaints,
        "bounceRate": bounce_rate,
        "complaintRate": complaint_rate,
        "history": history,
    }


def _refuse(message: str, **extra: Any) -> dict[str, Any]:
    return {"error": message, **extra}


def send(
    table: Any,
    settings: dict[str, Any],
    *,
    prospect_id: str,
    step_index: int = 0,
    personalisation: str = "",
) -> dict[str, Any]:
    if not board_mail.sending_enabled():
        return _refuse("email sending is switched off")
    if board_breakers.is_tripped(table, "outreach"):
        return _refuse("breaker tripped", breaker="outreach")
    if not identity_verified():
        return _refuse("sending identity not verified")
    prospect = board_store.get_prospect(table, prospect_id)
    if not prospect:
        return _refuse("prospect not found")
    stage = str(prospect.get("stage") or "")
    if stage == "replied":
        return _refuse("prospect replied")
    if stage == "suppressed":
        return _refuse("suppressed")
    if stage not in {"qualified", "contacted"}:
        return _refuse("stage not qualified or contacted", stage=stage)
    enabled = set(board_prospects.types_enabled(settings))
    if str(prospect.get("type") or "") not in enabled:
        return _refuse("type not enabled", type=prospect.get("type"))
    contact = board_pii.normalize_email(str(prospect.get("contact") or prospect.get("email") or ""))
    if not contact:
        return _refuse("no contact")
    if not board_prospects._is_business_address(  # noqa: SLF001
        contact, allow_personal=board_prospects._personal_allowed(settings)  # noqa: SLF001
    ):
        return _refuse("personal address not allowed")
    if is_suppressed(table, contact):
        return _refuse("suppressed")
    touches = list(prospect.get("touches") or [])
    if len(touches) >= BOARD_STAFF_OUTREACH_MAX_TOUCHES:
        return _refuse("touches exhausted")
    seq = board_sequences.get_or_default(table, str(prospect.get("type") or "provider"))
    steps = list(seq.get("steps") or [])
    if step_index < 0 or step_index >= len(steps):
        return _refuse("step out of range")
    if step_index < len(touches):
        return _refuse("step already sent")
    today = board_hk.today_hkt()
    cap = int(((settings.get("boundaries") or {}).get("outreach") or {}).get("dailyCap") or 20)
    if not board_store.reserve_outreach_sent(table, today, cap):
        return _refuse("daily cap reached", dailyCap=cap)
    note = str(personalisation or "")[:400]
    subject, body = render_message(table, prospect, steps[step_index], personalisation=note)
    unsub = unsubscribe_url(str(prospect.get("prospectId") or ""))
    msg = EmailMessage()
    sender = from_address()
    msg["From"] = formataddr(("Siu Tin Dei Partnerships", sender))
    msg["To"] = contact
    msg["Subject"] = board_mail._single_line(subject, 200) or "(no subject)"  # noqa: SLF001
    msg["Reply-To"] = reply_to_address()
    msg["Message-ID"] = make_msgid(domain=sending_domain())
    msg["List-Unsubscribe"] = f"<{unsub}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg["X-Siutindei-Prospect"] = str(prospect.get("prospectId") or "")
    msg.set_content(body)
    raw = msg.as_bytes()
    now = board_store.now_iso()
    pending = {
        "stepIndex": step_index,
        "sentAt": now,
        "subject": subject,
        "preview": body[:280],
        "threadId": "",
        "sesMessageId": "pending",
    }
    touches.append(pending)
    prospect["touches"] = touches
    prospect["contact"] = contact
    prospect["updatedAt"] = now
    board_store.put_prospect(table, prospect)
    try:
        response = _ses_client().send_email(
            FromEmailAddress=sender,
            Destination={"ToAddresses": [contact]},
            Content={"Raw": {"Data": raw}},
            ConfigurationSetName=CONFIG_SET,
            EmailTags=[{"Name": "prospectId", "Value": str(prospect.get("prospectId") or "none")}],
            ReplyToAddresses=[reply_to_address()],
        )
    except Exception as exc:
        board_store.release_outreach_sent(table, today)
        _log_event("warning", tag="board_outreach_ses_failed", error=str(exc)[:200])
        return _refuse("ses send failed")
    indexed = {"threadId": ""}
    try:
        indexed = board_mail.ingest_bytes(table, raw, direction="outbound", source="outreach")
        if indexed.get("threadId"):
            board_store.set_mail_thread_unread(table, str(indexed["threadId"]), unread=False)
    except Exception as exc:
        _log_event("warning", tag="board_outreach_index_failed", error=str(exc)[:200])
    latest = board_store.get_prospect(table, prospect_id) or prospect
    latest_touches = list(latest.get("touches") or touches)
    for touch in latest_touches:
        if int(touch.get("stepIndex") or -1) == step_index:
            touch["sesMessageId"] = str((response or {}).get("MessageId") or "")
            touch["threadId"] = indexed.get("threadId")
            touch["preview"] = body[:280]
            break
    else:
        latest_touches.append({**pending, "sesMessageId": str((response or {}).get("MessageId") or ""), "threadId": indexed.get("threadId")})
    latest["touches"] = latest_touches
    latest["lastThreadId"] = indexed.get("threadId") or latest.get("lastThreadId")
    latest["contact"] = contact
    started = str(latest.get("sequenceStartedAt") or now)
    if str(latest.get("stage") or stage) == "qualified":
        latest["stage"] = "contacted"
        latest["sequenceStartedAt"] = started
    next_index = step_index + 1
    if next_index >= len(steps) or len(latest_touches) >= BOARD_STAFF_OUTREACH_MAX_TOUCHES:
        latest["stage"] = "unresponsive"
        latest["nextTouchAt"] = ""
    else:
        next_offset = int((steps[next_index] or {}).get("dayOffset") or 0)
        latest["nextTouchAt"] = board_sequences.next_touch_at(started, next_offset)
    latest["updatedAt"] = board_store.now_iso()
    try:
        board_store.put_prospect(table, latest)
        board_prospects._index_keys(table, latest)  # noqa: SLF001
    except Exception as exc:
        _log_event("warning", tag="board_outreach_prospect_save_failed", error=str(exc)[:200])
    return {
        "ok": True,
        "prospectId": latest.get("prospectId"),
        "stage": latest.get("stage"),
        "threadId": indexed.get("threadId"),
        "sesMessageId": str((response or {}).get("MessageId") or ""),
        "to": contact,
        "subject": subject,
    }


def handle_ses_events(records: list[dict[str, Any]]) -> dict[str, Any]:
    table = board_store.records_table()
    handled = 0
    for record in records:
        body_raw = record.get("body") or ""
        try:
            body = json.loads(body_raw) if isinstance(body_raw, str) else body_raw
        except json.JSONDecodeError:
            continue
        if isinstance(body, dict) and body.get("Type") == "Notification" and body.get("Message"):
            try:
                body = json.loads(str(body["Message"]))
            except json.JSONDecodeError:
                continue
        if not isinstance(body, dict):
            continue
        event_type = str(body.get("eventType") or body.get("notificationType") or "").lower()
        mail = body.get("mail") or {}
        tags = mail.get("tags") or {}
        config = _ses_config_set(tags)
        if "newsletter" in config or tags.get("issueId") or tags.get("issueid"):
            continue
        pid = ""
        raw_tag = tags.get("prospectId") or tags.get("prospectid")
        if isinstance(raw_tag, list) and raw_tag:
            pid = str(raw_tag[0])
        destinations = [board_pii.normalize_email(str(x)) for x in (mail.get("destination") or []) if x]
        bounce = body.get("bounce") or {}
        bounce_type = str(bounce.get("bounceType") or "")
        hard = event_type == "bounce" and bounce_type.lower() == "permanent"
        complaint = event_type == "complaint"
        rejected = event_type == "reject"
        if not (hard or complaint or rejected):
            continue
        prospect = board_store.get_prospect(table, pid) if pid else None
        if prospect is None:
            for addr in destinations:
                found = board_prospects.lookup_by_address(table, addr)
                if found:
                    prospect = found
                    break
        email = destinations[0] if destinations else str((prospect or {}).get("contact") or "")
        reason = "complaint" if complaint else "hard bounce"
        suppress(table, email=email, prospect=prospect, reason=reason)
        today = board_hk.today_hkt()
        day = board_store.load_outreach_day(table, today)
        if complaint:
            day["complaints"] = int(day.get("complaints") or 0) + 1
        else:
            day["bounces"] = int(day.get("bounces") or 0) + 1
        board_store.save_outreach_day(table, day, today)
        handled += 1
    return {"ok": True, "handled": handled}


def _ses_config_set(tags: dict[str, Any]) -> str:
    raw = tags.get("ses:configuration-set") or tags.get("ses:configurationSet") or ""
    if isinstance(raw, list) and raw:
        return str(raw[0] or "").lower()
    return str(raw or "").lower()


def _rate_limited(table: Any, ip: str) -> bool:
    hour = board_hk.now_hkt().strftime("%Y-%m-%d-%H")
    name = f"unsub-ip:{ip}:{hour}"
    return board_store.bump_cache_count(table, name, ttl_seconds=3600) > 100


def handle_unsubscribe(event: dict[str, Any], method: str, token: str) -> dict[str, Any]:
    table = board_store.records_table()
    http = (event.get("requestContext") or {}).get("http") or {}
    ip = str(http.get("sourceIp") or "0.0.0.0")
    if _rate_limited(table, ip):
        if method == "GET":
            return _html_response(429, "<!doctype html><html><body><p>Too many requests.</p></body></html>")
        return {"statusCode": 429, "headers": {"content-type": "text/plain"}, "body": ""}
    try:
        pid = parse_unsub_token(token)
    except OutreachError:
        pid = None
    if not pid:
        if method == "GET":
            return _html_response(400, "<!doctype html><html><body><p>This unsubscribe link is not valid.</p></body></html>")
        return {"statusCode": 400, "headers": {"content-type": "text/plain"}, "body": ""}
    prospect = board_store.get_prospect(table, pid)
    email = str((prospect or {}).get("contact") or (prospect or {}).get("email") or "")
    suppress(table, email=email, prospect=prospect, reason="unsubscribe")
    if method == "POST":
        return {"statusCode": 200, "headers": {"content-type": "text/plain"}, "body": ""}
    return _html_response(
        200,
        "<!doctype html><html><body><p>You will not hear from us again.</p></body></html>",
    )


def _html_response(status: int, body: str) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "text/html; charset=utf-8"},
        "body": body,
    }


_QUOTE_START = re.compile(r"^(On .+ wrote:|-----Original Message-----|From:|寄件者:)", re.I)
_OWN_FOOTER = re.compile(
    r"Reply\s+[\"“']unsubscribe[\"”'].*|回覆[「\"“]退訂[」\"”].*|\{unsubscribeUrl\}",
    re.I,
)


def unquoted_reply_text(text: str) -> str:
    lines: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            break
        if _QUOTE_START.match(stripped):
            break
        if _OWN_FOOTER.search(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def is_unsubscribe_reply(text: str) -> bool:
    body = unquoted_reply_text(text)
    return bool(body and UNSUB_WORDS.search(body))


def maybe_handle_reply(table: Any, settings: dict[str, Any], sender: str, text: str) -> dict[str, Any] | None:
    """If the sender is a prospect: suppress on unsubscribe words, else mark replied."""
    addr = board_pii.normalize_email(sender)
    if not addr:
        return None
    prospect = board_prospects.lookup_by_address(table, addr)
    if not prospect:
        return None
    if is_unsubscribe_reply(text or ""):
        suppress(table, email=addr, prospect=prospect, reason="unsubscribe reply")
        return {"prospect": prospect, "suppressed": True}
    prospect["stage"] = "replied"
    prospect["repliedAt"] = board_store.now_iso()
    prospect["updatedAt"] = prospect["repliedAt"]
    if UNSUB_WORDS.search(text or "") and not is_unsubscribe_reply(text or ""):
        prospect["replyNote"] = "unsubscribe keyword appeared only in quoted text"
    board_store.put_prospect(table, prospect)
    return {"prospect": prospect, "suppressed": False}


def stats(table: Any, settings: dict[str, Any], *, days: int = 28) -> dict[str, Any]:
    rates = trailing_rates(table, days=max(1, min(90, days)))
    replies = 0
    for stage in ("replied", "onboarding", "listed"):
        replies += len(board_store.list_prospects(table, stage, limit=400))
    outreach = (settings.get("boundaries") or {}).get("outreach") or {}
    return {
        **rates,
        "replies": replies,
        "dailyCap": int(outreach.get("dailyCap") or 20),
        "capRaisedAt": outreach.get("capRaisedAt") or "",
        "breaker": board_store.get_breaker(table, "outreach") or {"name": "outreach", "tripped": False},
        "identityVerified": identity_verified(),
    }


# ---------------------------------------------------------------------------
# Tool ops
# ---------------------------------------------------------------------------

def op_search_places(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    import board_places

    query = str(args.get("query") or "").strip()
    district = str(args.get("district") or "").strip()
    if district:
        query = f"{query} {district}".strip()
    try:
        places = board_places.text_search(ctx.table, query, settings=ctx.settings)
    except board_places.PlacesError as exc:
        return exc.payload
    return {"places": places}


def op_open_data(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    try:
        rows = board_prospects.open_data_rows(ctx.table, str(args.get("kind") or ""), str(args.get("district") or ""))
    except board_prospects.ProspectError as exc:
        return {"error": str(exc)}
    return {"rows": rows}


def op_list_prospects(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    try:
        limit = min(max(1, int(args.get("limit") or 20)), 50)
    except (TypeError, ValueError):
        limit = 20
    try:
        page = board_prospects.list_for_api(
            ctx.table,
            stage=str(args.get("stage") or "") or None,
            ptype=str(args.get("type") or "") or None,
            limit=limit,
        )
    except board_prospects.ProspectError as exc:
        return {"error": str(exc)}
    return {"prospects": [board_prospects.mask_row(ctx.table, r) for r in page["prospects"]]}


def op_get_prospect(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    row = board_store.get_prospect(ctx.table, str(args.get("id") or args.get("prospectId") or ""))
    if not row:
        return {"error": "prospect not found"}
    public = board_prospects.public_row(row, duplicates=board_prospects.possible_duplicates(ctx.table, row))
    return {"prospect": board_prospects.mask_row(ctx.table, public)}


def op_upsert_prospect(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    try:
        row, created = board_prospects.upsert(
            ctx.table,
            name=str(args.get("name") or ""),
            type=str(args.get("type") or "provider"),
            district=str(args.get("district") or ""),
            source=str(args.get("source") or "staff"),
            website=str(args.get("website") or ""),
            phone=str(args.get("phone") or ""),
            email=str(args.get("email") or ""),
            place_id=str(args.get("placeId") or args.get("place_id") or ""),
        )
    except board_prospects.ProspectError as exc:
        return {"error": str(exc)}
    return {"prospect": board_prospects.mask_row(ctx.table, row), "created": created}


def op_score_prospect(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    row = board_store.get_prospect(ctx.table, str(args.get("id") or args.get("prospectId") or ""))
    if not row:
        return {"error": "prospect not found"}
    score_n, note = board_prospects.score(ctx.table, ctx.settings, row)
    row = board_prospects.qualify(ctx.table, ctx.settings, row)
    board_prospects.find_contact(ctx.table, ctx.settings, row)
    row = board_store.get_prospect(ctx.table, str(row.get("prospectId") or "")) or row
    return {"score": score_n, "note": note, "prospect": board_prospects.mask_row(ctx.table, row)}


def op_start_sequence(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    row = board_store.get_prospect(ctx.table, str(args.get("id") or args.get("prospectId") or ""))
    if not row:
        return {"error": "prospect not found"}
    if str(row.get("stage") or "") not in {"qualified", "contacted"}:
        return {"error": "prospect is not qualified"}
    if not row.get("contact"):
        return {"error": "no contact"}
    row = board_sequences.start(ctx.table, row)
    return {"prospect": board_prospects.mask_row(ctx.table, row)}


def op_send(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    try:
        step = int(args.get("stepIndex") or 0)
    except (TypeError, ValueError):
        step = 0
    return send(
        ctx.table,
        ctx.settings,
        prospect_id=str(args.get("prospectId") or args.get("id") or ""),
        step_index=step,
        personalisation=str(args.get("personalisation") or "")[:400],
    )


def op_suppress(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    row = board_store.get_prospect(ctx.table, str(args.get("id") or args.get("prospectId") or ""))
    if not row:
        return {"error": "prospect not found"}
    suppress(
        ctx.table,
        email=str(row.get("contact") or row.get("email") or ""),
        prospect=row,
        reason=str(args.get("reason") or "staff"),
    )
    return {"ok": True, "prospectId": row.get("prospectId")}
