"""Executive Board ``meta`` tools: Facebook Page, Instagram, WhatsApp Cloud API.

Webhook (``GET/POST /webhooks/meta/siutindei``, plus the legacy
``/webhooks/meta`` path) is the first unauthenticated admin-API route:
Meta's verify handshake plus ``X-Hub-Signature-256``. Inbound payloads
are masked and stored under ``BOARD#…#meta#``; no LLM work happens here.

Writes execute after approval, or at ``act`` when the global mode allows it
and the call is inside caps / allow-lists (T7). WhatsApp ``act`` is honoured
only inside the 24-hour customer-service window and only for allow-listed
recipients; otherwise the call is downgraded to propose. Ad writes that would
breach the owner-set daily or monthly spend caps are forced to propose.

Plan: docs/architecture/executive-board-tools-plan.md §5.3.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest
from urllib.parse import parse_qs

from admin_runtime import _get_secretsmanager_client
import board_deadline
import board_mail
import board_pii
import board_store
from contract_constants import (
    BOARD_META_ADS_DAILY_CAP_USD,
    BOARD_META_ADS_MONTHLY_CAP_USD,
    BOARD_META_LIST_MAX,
)
from http_common import _log_event, _utc_iso_z
from openrouter_client import read_secret_string

GRAPH_ORIGIN = "https://graph.facebook.com/v21.0"
HTTP_TIMEOUT_SECONDS = 12
HTTP_TIMEOUT_SLOW_SECONDS = 25
WINDOW_HOURS = 24
GRAPH_PAGES_MAX = 3

_token_cache: str | None = None
_token_checked = False
_app_secret_cache: str | None = None
_app_secret_checked = False


class MetaError(RuntimeError):
    """User-facing Meta / webhook failure. ``status`` is the Graph HTTP code, if any."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def configured() -> bool:
    return bool(
        (os.environ.get("META_BOARD_TOKEN") or "").strip()
        or (os.environ.get("META_BOARD_TOKEN_SECRET_ARN") or "").strip()
    )


def verify_token() -> str:
    return (os.environ.get("META_VERIFY_TOKEN") or "").strip()


def page_id() -> str:
    return (os.environ.get("META_PAGE_ID") or "").strip()


def ig_user_id() -> str:
    return (os.environ.get("META_IG_USER_ID") or "").strip()


def wa_phone_id() -> str:
    return (os.environ.get("META_WA_PHONE_NUMBER_ID") or "").strip()


def waba_id() -> str:
    return (os.environ.get("META_WABA_ID") or "").strip()


def ad_account_id() -> str:
    raw = (os.environ.get("META_AD_ACCOUNT_ID") or "").strip()
    if raw and not raw.startswith("act_"):
        return f"act_{raw}"
    return raw


def ads_daily_cap_usd() -> float:
    raw = (os.environ.get("META_ADS_DAILY_CAP_USD") or "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return float(BOARD_META_ADS_DAILY_CAP_USD)


def ads_monthly_cap_usd() -> float:
    raw = (os.environ.get("META_ADS_MONTHLY_CAP_USD") or "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return float(BOARD_META_ADS_MONTHLY_CAP_USD)


def ads_caps(settings: dict[str, Any] | None = None) -> tuple[float, float]:
    """Owner-set caps from settings, else env / contract defaults."""
    daily = ads_daily_cap_usd()
    monthly = ads_monthly_cap_usd()
    raw = ((settings or {}).get("tools") or {}).get("spendCaps")
    if isinstance(raw, dict):
        normalized = board_store.normalize_spend_caps(raw)
        if "metaAdsDailyUsd" in raw:
            daily = normalized["metaAdsDailyUsd"]
        if "metaAdsMonthlyUsd" in raw:
            monthly = normalized["metaAdsMonthlyUsd"]
    return daily, monthly


def graph_month_spend_detail() -> dict[str, Any]:
    """Month-to-date ad account spend from Graph: ``{"spend", "currency", "available"}``.

    Graph reports spend in the ad account's own currency; callers must not
    label it USD unless ``currency`` says so. Any Graph failure yields
    ``available=False`` rather than an exception.
    """
    aid = ad_account_id()
    if not aid or not board_token():
        return {"spend": 0.0, "currency": "", "available": False}
    try:
        data = graph(
            "GET",
            f"{aid}/insights",
            params={"fields": "spend,account_currency", "date_preset": "this_month", "level": "account"},
        )
    except MetaError as exc:
        _log_event("warning", tag="board_meta_spend_unavailable", error=str(exc)[:200])
        return {"spend": 0.0, "currency": "", "available": False}
    rows = data.get("data") or []
    if not rows or not isinstance(rows[0], dict):
        return {"spend": 0.0, "currency": "", "available": True}
    try:
        spend = float(rows[0].get("spend") or 0)
    except (TypeError, ValueError):
        spend = 0.0
    return {"spend": spend, "currency": str(rows[0].get("account_currency") or ""), "available": True}


def graph_month_spend(detail: dict[str, Any] | None = None) -> float:
    return float((detail or graph_month_spend_detail())["spend"])


def ads_spend_snapshot(table: Any, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    recorded = board_store.load_ads_spend(table) if table is not None else {"dailyUsd": 0.0, "monthlyUsd": 0.0}
    detail = graph_month_spend_detail()
    graph_month = graph_month_spend(detail)
    daily_cap, monthly_cap = ads_caps(settings)
    recorded_daily = float(recorded.get("dailyUsd") or 0.0)
    recorded_month = float(recorded.get("monthlyUsd") or 0.0)
    return {
        "recordedDailyUsd": recorded_daily,
        "recordedMonthlyUsd": recorded_month,
        "graphMonthlyUsd": graph_month,
        "graphCurrency": detail["currency"],
        "graphAvailable": bool(detail["available"]),
        "dailyUsd": recorded_daily,
        # Cap check stays conservative: commitments the board made this month
        # plus what Graph has already billed.
        "monthlyUsd": recorded_month + graph_month,
        "dailyCapUsd": daily_cap,
        "monthlyCapUsd": monthly_cap,
    }


def reset_caches_for_tests() -> None:
    global _token_cache, _token_checked, _app_secret_cache, _app_secret_checked
    _waba_resolved.clear()
    _token_cache = None
    _token_checked = False
    _app_secret_cache = None
    _app_secret_checked = False


def _secret(env_plain: str, env_arn: str) -> str:
    plain = (os.environ.get(env_plain) or "").strip()
    if plain:
        return plain
    arn = (os.environ.get(env_arn) or "").strip()
    if not arn:
        return ""
    return (read_secret_string(_get_secretsmanager_client(), arn) or "").strip()


def board_token() -> str:
    global _token_cache, _token_checked
    if _token_checked:
        return _token_cache or ""
    _token_checked = True
    _token_cache = _secret("META_BOARD_TOKEN", "META_BOARD_TOKEN_SECRET_ARN")
    return _token_cache or ""


def app_secret() -> str:
    global _app_secret_cache, _app_secret_checked
    if _app_secret_checked:
        return _app_secret_cache or ""
    _app_secret_checked = True
    _app_secret_cache = _secret("META_APP_SECRET", "META_APP_SECRET_SECRET_ARN")
    return _app_secret_cache or ""


def status_summary(table: Any) -> dict[str, Any]:
    threads = board_store.list_meta_threads(table) if table is not None else []
    unread = sum(1 for t in threads if t.get("unread"))
    return {
        "configured": configured(),
        "pageSet": bool(page_id()),
        "whatsappSet": bool(wa_phone_id()),
        "threadCount": len(threads),
        "unreadCount": unread,
        "adsDailyCapUsd": ads_caps(None)[0],
        "adsMonthlyCapUsd": ads_caps(None)[1],
    }


# ---------------------------------------------------------------------------
# Graph API
# ---------------------------------------------------------------------------

def _urlopen(req: urlrequest.Request, timeout: float | None = None) -> Any:
    return urlrequest.urlopen(req, timeout=board_deadline.remaining(timeout or HTTP_TIMEOUT_SECONDS))


def graph(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    token = board_token()
    if not token:
        raise MetaError("MetaBoardToken is not configured.")
    # Token travels in the Authorization header so it never lands in access
    # logs / referrers; ``appsecret_proof`` (if the caller set it) stays a param.
    query = dict(params or {})
    query.pop("access_token", None)
    url = f"{GRAPH_ORIGIN}/{path.lstrip('/')}"
    if query:
        url = f"{url}?{urlparse.urlencode(query, doseq=True)}"
    data = None
    headers = {"User-Agent": "lxsoftware-board-meta", "Authorization": f"Bearer {token}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urlrequest.Request(url, data=data, method=method.upper(), headers=headers)
    try:
        with _urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urlerror.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except (OSError, AttributeError):
            detail = ""
        raise MetaError(f"Meta Graph {exc.code}: {detail or exc.reason}", status=int(exc.code)) from exc
    except urlerror.URLError as exc:
        raise MetaError(f"Meta Graph unreachable: {exc.reason}") from exc
    except OSError as exc:  # socket.timeout while reading the body is not a URLError
        raise MetaError(f"Meta Graph unreachable: {exc}") from exc
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise MetaError("Meta Graph returned non-JSON") from exc
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def graph_pages(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    *,
    max_pages: int = GRAPH_PAGES_MAX,
    limit: int = BOARD_META_LIST_MAX,
    timeout: float | None = None,
) -> list[dict[str, Any]]:
    """``data[]`` rows across cursor pages (``paging.cursors.after``), capped at ``limit``."""
    rows: list[dict[str, Any]] = []
    after = ""
    for _page in range(max(1, max_pages)):
        query = dict(params or {})
        if after:
            query["after"] = after
        data = graph(method, path, params=query, timeout=timeout)
        for row in data.get("data") or []:
            if isinstance(row, dict):
                rows.append(row)
            if len(rows) >= limit:
                return rows[:limit]
        paging = data.get("paging") or {}
        after = str(((paging.get("cursors") or {}).get("after") if isinstance(paging, dict) else "") or "")
        if not after or not (isinstance(paging, dict) and paging.get("next")):
            break
    return rows[:limit]


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

def _raw_body(event: dict[str, Any]) -> bytes:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        import base64

        return base64.b64decode(raw)
    return raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)


def _header(event: dict[str, Any], name: str) -> str:
    headers = event.get("headers") or {}
    wanted = name.lower()
    for key, value in headers.items():
        if str(key).lower() == wanted:
            return str(value or "")
    return ""


def verify_signature(event: dict[str, Any], body: bytes) -> bool:
    secret = app_secret()
    if not secret:
        return False
    header = _header(event, "X-Hub-Signature-256")
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[7:], expected)


def handle_http(event: dict[str, Any], method: str) -> dict[str, Any]:
    """Unauthenticated Meta webhook. GET = verify handshake; POST = ingest."""
    if method == "GET":
        qs = parse_qs(event.get("rawQueryString") or "")
        params = event.get("queryStringParameters") or {}
        mode = (qs.get("hub.mode") or [params.get("hub.mode") or ""])[0]
        token = (qs.get("hub.verify_token") or [params.get("hub.verify_token") or ""])[0]
        challenge = (qs.get("hub.challenge") or [params.get("hub.challenge") or ""])[0]
        expected = verify_token()
        if mode == "subscribe" and expected and hmac.compare_digest(str(token), expected):
            return {"statusCode": 200, "headers": {"Content-Type": "text/plain"}, "body": str(challenge)}
        return {"statusCode": 403, "headers": {"Content-Type": "text/plain"}, "body": "forbidden"}

    if method != "POST":
        return {"statusCode": 405, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"message": "Method not allowed"})}

    body = _raw_body(event)
    if not verify_signature(event, body):
        _log_event("warning", tag="board_meta_webhook_bad_sig")
        return {"statusCode": 403, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"message": "invalid signature"})}
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 400, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"message": "invalid json"})}
    ingested = ingest_webhook(board_store.records_table(), payload if isinstance(payload, dict) else {})
    return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"ok": True, **ingested})}


def ingest_webhook(table: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Store masked inbound messages. Must stay well under Meta's 20 s ack."""
    obj = str(payload.get("object") or "")
    entries = payload.get("entry") or []
    stored = 0
    duplicates = 0
    pseud = board_pii.Pseudonymizer(table)
    now = _utc_iso_z(datetime.now(timezone.utc))
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        channel = "whatsapp" if obj == "whatsapp_business_account" else ("instagram" if obj == "instagram" else "page")
        for msg in _iter_inbound(entry, channel=channel):
            if _store_inbound(table, pseud, msg, received_at=now):
                stored += 1
            else:
                duplicates += 1
    pseud.save()
    _log_event("info", tag="board_meta_ingested", stored=stored, duplicates=duplicates, object=obj)
    return {"stored": stored, "duplicates": duplicates}


def _iter_inbound(entry: dict[str, Any], *, channel: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    messaging = entry.get("messaging") or entry.get("standby") or []
    for item in messaging:
        if not isinstance(item, dict):
            continue
        message = item.get("message") or {}
        if not isinstance(message, dict):
            continue
        if message.get("is_echo"):
            # Our own outbound messages come back through the webhook too.
            continue
        sender = _sender_id(item.get("sender")) or _sender_id(item.get("from"))
        text = str(message.get("text") or message.get("body") or "")
        mid = str(message.get("mid") or message.get("id") or board_store.new_id())
        ts = item.get("timestamp") or entry.get("time") or int(time.time() * 1000)
        out.append(
            {
                "channel": channel,
                "threadKey": str(sender or mid),
                "senderId": str(sender),
                "messageId": mid,
                "text": text,
                "timestampMs": int(ts) if str(ts).isdigit() else int(time.time() * 1000),
            }
        )
    for change in entry.get("changes") or []:
        if not isinstance(change, dict):
            continue
        value = change.get("value") or {}
        if not isinstance(value, dict):
            continue
        if change.get("field") in ("messages", "whatsapp_business_account"):
            contacts = value.get("contacts") or []
            contact_wa_id = str((contacts[0] or {}).get("wa_id") or "") if contacts and isinstance(contacts[0], dict) else ""
            for m in value.get("messages") or []:
                if not isinstance(m, dict):
                    continue
                sender = _phone_digits(str(m.get("from") or contact_wa_id or ""))
                text = str((m.get("text") or {}).get("body") or m.get("body") or "")
                mid = str(m.get("id") or board_store.new_id())
                out.append(
                    {
                        "channel": "whatsapp",
                        "threadKey": sender or mid,
                        "senderId": sender,
                        "messageId": mid,
                        "text": text,
                        "timestampMs": _int_or(m.get("timestamp"), int(time.time())),
                    }
                )
        if change.get("field") in ("comments", "feed"):
            comment = value.get("comment") or value
            if not isinstance(comment, dict):
                continue
            text = str(comment.get("message") or comment.get("text") or "")
            cid = str(comment.get("id") or board_store.new_id())
            sender = _sender_id(comment.get("from"))
            out.append(
                {
                    "channel": "instagram" if channel == "instagram" else "page",
                    "threadKey": f"comment:{cid}",
                    "senderId": sender,
                    "messageId": cid,
                    "text": text,
                    "timestampMs": _int_or(comment.get("created_time"), int(time.time() * 1000)),
                    "kind": "comment",
                }
            )
    return out


def _sender_id(raw: Any) -> str:
    """Graph ``from`` / ``sender`` is usually ``{"id": ...}`` but can be a bare id string."""
    if isinstance(raw, dict):
        return str(raw.get("id") or "")
    return str(raw or "")


def _int_or(raw: Any, default: int) -> int:
    text = str(raw or "").strip()
    return int(text) if text.isdigit() else default


def thread_id_for(channel: str, thread_key: str) -> str:
    return hashlib.sha256(f"{channel}:{thread_key}".encode()).hexdigest()[:20]


def whatsapp_thread_id(number: str) -> str:
    """Stored thread id for a WhatsApp number; the same derivation the webhook uses."""
    return thread_id_for("whatsapp", _phone_digits(number))


def _store_inbound(table: Any, pseud: board_pii.Pseudonymizer, msg: dict[str, Any], *, received_at: str) -> bool:
    """Store one inbound message; returns False when Meta redelivered a known message."""
    thread_id = thread_id_for(str(msg.get("channel")), str(msg.get("threadKey")))
    text = str(msg.get("text") or "")
    masked = pseud.mask_text(text)
    ts_ms = int(msg.get("timestampMs") or 0)
    received = received_at
    if ts_ms > 10_000_000_000:
        received = _utc_iso_z(datetime.fromtimestamp(ts_ms / 1000, timezone.utc))
    elif ts_ms > 1_000_000_000:
        received = _utc_iso_z(datetime.fromtimestamp(ts_ms, timezone.utc))
    is_new = board_store.put_meta_message_if_new(
        table,
        {
            "threadId": thread_id,
            "messageId": str(msg.get("messageId")),
            "receivedAt": received,
            "direction": "in",
            "textMasked": masked[:4000],
            "channel": msg.get("channel"),
        },
    )
    if not is_new:
        _log_event("info", tag="board_meta_duplicate_delivery", threadId=thread_id, messageId=str(msg.get("messageId")))
        return False
    existing = board_store.get_meta_thread(table, thread_id) or {}
    board_store.put_meta_thread(
        table,
        {
            "threadId": thread_id,
            "channel": msg.get("channel"),
            "kind": msg.get("kind") or "message",
            "senderId": msg.get("senderId"),
            "lastTextMasked": masked[:240],
            "lastMessageAt": received,
            "lastInboundAt": received,
            "unread": True,
            "messageCount": int(existing.get("messageCount") or 0) + 1,
        },
    )
    return True


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def op_page_insights(_ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    pid = str(args.get("pageId") or page_id())
    if not pid:
        raise MetaError("META_PAGE_ID is not set.")
    metric = str(args.get("metric") or "page_impressions,page_engaged_users")
    rows = graph_pages(
        "GET",
        f"{pid}/insights",
        {"metric": metric, "period": "day"},
        timeout=HTTP_TIMEOUT_SLOW_SECONDS,
    )
    return {"pageId": pid, "insights": rows, "count": len(rows)}


def op_ig_insights(_ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    iid = str(args.get("igUserId") or ig_user_id())
    if not iid:
        raise MetaError("META_IG_USER_ID is not set.")
    metric = str(args.get("metric") or "impressions,reach,profile_views")
    rows = graph_pages(
        "GET",
        f"{iid}/insights",
        {"metric": metric, "period": "day"},
        timeout=HTTP_TIMEOUT_SLOW_SECONDS,
    )
    return {"igUserId": iid, "insights": rows, "count": len(rows)}


def op_list_comments(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    pid = str(args.get("pageId") or page_id())
    if not pid:
        raise MetaError("META_PAGE_ID is not set.")
    limit = max(1, min(int(args.get("limit") or 10), BOARD_META_LIST_MAX))
    rows = graph_pages(
        "GET",
        f"{pid}/feed",
        {"fields": "id,message,comments.limit(10){from,message,created_time}", "limit": limit},
        limit=limit,
        timeout=HTTP_TIMEOUT_SLOW_SECONDS,
    )
    table = getattr(ctx, "table", None)
    pseud = board_pii.Pseudonymizer(table, own_domains=board_mail.own_domains()) if table is not None else None
    posts = []
    for post in rows:
        comments = ((post.get("comments") or {}).get("data") or [])
        posts.append(
            {
                "id": post.get("id"),
                "message": _mask_text(str(post.get("message") or ""), pseud),
                "comments": [
                    {
                        "id": c.get("id"),
                        "from": _mask_sender(c.get("from"), pseud),
                        "message": _mask_text(str(c.get("message") or ""), pseud),
                    }
                    for c in comments
                ],
            }
        )
    if pseud is not None:
        pseud.save()
    return {"posts": posts, "count": len(posts)}


def op_list_dms(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    return _list_stored(ctx.table, channel="page", limit=int(args.get("limit") or 20))


def op_list_whatsapp(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    return _list_stored(ctx.table, channel="whatsapp", limit=int(args.get("limit") or 20))


def op_ad_spend(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    aid = str(args.get("adAccountId") or ad_account_id())
    if not aid:
        raise MetaError("META_AD_ACCOUNT_ID is not set.")
    data = graph(
        "GET",
        f"{aid}/insights",
        params={"fields": "spend,impressions,clicks,actions", "date_preset": "this_month", "level": "account"},
        timeout=HTTP_TIMEOUT_SLOW_SECONDS,
    )
    rows = data.get("data") or []
    spend = 0.0
    if rows:
        try:
            spend = float(rows[0].get("spend") or 0)
        except (TypeError, ValueError):
            spend = 0.0
    daily_cap, monthly_cap = ads_caps(getattr(ctx, "settings", None))
    snapshot = ads_spend_snapshot(getattr(ctx, "table", None), getattr(ctx, "settings", None))
    return {
        "adAccountId": aid,
        "spendUsd": spend,
        "capUsd": monthly_cap,
        "dailyCapUsd": daily_cap,
        "recordedDailyUsd": snapshot["recordedDailyUsd"],
        "recordedMonthlyUsd": snapshot["recordedMonthlyUsd"],
        "rows": rows[:5],
    }


def _list_stored(table: Any, *, channel: str, limit: int) -> dict[str, Any]:
    threads = [t for t in board_store.list_meta_threads(table) if t.get("channel") == channel]
    threads = threads[: max(1, min(limit, BOARD_META_LIST_MAX))]
    return {
        "threads": [
            {
                "threadId": t.get("threadId"),
                "lastTextMasked": t.get("lastTextMasked"),
                "lastMessageAt": t.get("lastMessageAt"),
                "unread": bool(t.get("unread")),
                "inWindow": _in_window(t),
            }
            for t in threads
        ],
        "count": len(threads),
    }


def _mask_text(text: str, pseud: board_pii.Pseudonymizer | None) -> str:
    if pseud is not None:
        return pseud.mask_text(text)
    return board_pii.EMAIL_RE.sub("contact#hidden", board_pii.PHONE_RE.sub("phone#hidden", text))


def _mask_sender(raw: Any, pseud: board_pii.Pseudonymizer | None) -> str:
    """Alias a Graph ``from`` object. Display names never reach the model."""
    if isinstance(raw, dict):
        ident = str(raw.get("id") or "")
        display = str(raw.get("name") or raw.get("username") or "")
    else:
        ident, display = str(raw or ""), ""
    if not ident and not display:
        return "contact#unknown"
    if pseud is None:
        return "contact#hidden"
    if ident:
        return pseud.alias_for_external("fb", ident, display=display)
    return pseud.alias_for_external("fbname", display, display=display)


def _mask_for_model(text: str) -> str:
    return _mask_text(text, None)


_waba_resolved: dict[str, str] = {}
TEMPLATE_PAGES_MAX = 3


def resolve_waba_id() -> str:
    explicit = waba_id()
    if explicit:
        return explicit
    phone = wa_phone_id()
    if not phone:
        raise MetaError("META_WABA_ID or META_WA_PHONE_NUMBER_ID is not set.")
    cached = _waba_resolved.get(phone)
    if cached:
        return cached
    data = graph("GET", phone, params={"fields": "whatsapp_business_account"}, timeout=HTTP_TIMEOUT_SLOW_SECONDS)
    account = data.get("whatsapp_business_account")
    resolved = ""
    if isinstance(account, dict) and account.get("id"):
        resolved = str(account["id"])
    elif isinstance(account, str) and account:
        resolved = account
    if not resolved:
        raise MetaError("Could not resolve the WhatsApp Business Account id from the phone-number id.")
    _waba_resolved[phone] = resolved
    return resolved


def op_list_whatsapp_templates(_ctx: Any, _args: dict[str, Any]) -> dict[str, Any]:
    """Approved templates only (the ones a reply outside the 24h window may use)."""
    account = resolve_waba_id()
    status = "APPROVED"
    rows: list[dict[str, Any]] = []
    after = ""
    for _page in range(TEMPLATE_PAGES_MAX):
        params: dict[str, Any] = {
            "fields": "name,status,language,category",
            "status": status,
            "limit": BOARD_META_LIST_MAX,
        }
        if after:
            params["after"] = after
        data = graph("GET", f"{account}/message_templates", params=params, timeout=HTTP_TIMEOUT_SLOW_SECONDS)
        for row in data.get("data") or []:
            if not isinstance(row, dict):
                continue
            # Graph applies the status filter server-side; re-check for older API versions.
            if str(row.get("status") or "").upper() != status:
                continue
            rows.append(
                {
                    "name": row.get("name"),
                    "status": row.get("status"),
                    "language": row.get("language"),
                    "category": row.get("category"),
                }
            )
            if len(rows) >= BOARD_META_LIST_MAX:
                break
        if len(rows) >= BOARD_META_LIST_MAX:
            break
        after = str(((data.get("paging") or {}).get("cursors") or {}).get("after") or "")
        if not after or not (data.get("paging") or {}).get("next"):
            break
    return {"wabaId": account, "status": status, "templates": rows, "count": len(rows)}


def _in_window(thread: dict[str, Any]) -> bool:
    raw = str(thread.get("lastInboundAt") or "")
    if not raw:
        return False
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - ts <= timedelta(hours=WINDOW_HOURS)


# ---------------------------------------------------------------------------
# Writes (execute after approval)
# ---------------------------------------------------------------------------

def op_propose_post(_ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    pid = str(args.get("pageId") or page_id())
    message = str(args.get("message") or "").strip()
    if not pid or not message:
        raise MetaError("pageId and message are required")
    data = graph("POST", f"{pid}/feed", body={"message": message})
    return {"ok": True, "postId": data.get("id"), "pageId": pid}


def op_propose_story(_ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    iid = str(args.get("igUserId") or ig_user_id())
    caption = str(args.get("caption") or "").strip()
    image_url = str(args.get("imageUrl") or "").strip()
    if not iid or not image_url:
        raise MetaError("igUserId and imageUrl are required")
    created = graph("POST", f"{iid}/media", body={"image_url": image_url, "caption": caption, "media_type": "STORIES"})
    creation_id = created.get("id")
    if not creation_id:
        raise MetaError("Instagram did not return a creation id")
    published = graph("POST", f"{iid}/media_publish", body={"creation_id": creation_id})
    return {"ok": True, "mediaId": published.get("id"), "igUserId": iid}


def op_reply_comment(_ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    comment_id = str(args.get("commentId") or "").strip()
    message = str(args.get("message") or "").strip()
    if not comment_id or not message:
        raise MetaError("commentId and message are required")
    data = graph("POST", f"{comment_id}/comments", body={"message": message})
    return {"ok": True, "commentId": data.get("id"), "parent": comment_id}


def _stored_thread(table: Any, args: dict[str, Any], *, channels: tuple[str, ...]) -> dict[str, Any] | None:
    """The stored inbound thread named by ``args.threadId`` when it is a message thread on ``channels``."""
    thread_id = str(args.get("threadId") or "").strip()
    if not thread_id or table is None:
        return None
    thread = board_store.get_meta_thread(table, thread_id)
    if not thread or thread.get("channel") not in channels or (thread.get("kind") or "message") != "message":
        return None
    return thread


def resolve_dm_recipient(table: Any, args: dict[str, Any]) -> str:
    """Page-scoped recipient id: from the stored thread when ``threadId`` is given, else ``recipientId``.

    Raises when both are supplied and disagree, so a thread can never be used to reach someone else.
    """
    explicit = str(args.get("recipientId") or "").strip()
    thread = _stored_thread(table, args, channels=("page", "instagram"))
    stored = str((thread or {}).get("senderId") or "").strip()
    if stored and explicit and stored != explicit:
        raise MetaError(f"threadId {args.get('threadId')} does not belong to recipientId {explicit}")
    return stored or explicit


def resolve_whatsapp_recipient(table: Any, args: dict[str, Any]) -> str:
    """WhatsApp number: from the stored thread when ``threadId`` is given, else ``to``.

    Raises when both are supplied and disagree. The 24-hour window is never
    read from this thread; callers re-derive it from the number (:func:`whatsapp_thread_id`).
    """
    explicit = str(args.get("to") or "").strip()
    thread = _stored_thread(table, args, channels=("whatsapp",))
    stored = str((thread or {}).get("senderId") or "").strip()
    if stored and explicit and _phone_digits(stored) != _phone_digits(explicit):
        raise MetaError(f"threadId {args.get('threadId')} does not belong to {explicit}")
    return stored or explicit


def op_reply_dm(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    recipient = resolve_dm_recipient(getattr(ctx, "table", None), args)
    message = str(args.get("message") or "").strip()
    pid = str(args.get("pageId") or page_id())
    if not recipient or not message or not pid:
        raise MetaError("threadId (or recipientId), message and pageId are required")
    data = graph("POST", f"{pid}/messages", body={"recipient": {"id": recipient}, "message": {"text": message}})
    return {"ok": True, "messageId": data.get("message_id"), "recipientId": recipient, "threadId": str(args.get("threadId") or "")}


def _send_whatsapp(to: str, *, message: str = "", template: str = "", language: str = "en") -> dict[str, Any]:
    """Session text (inside the window) or a pre-approved template (any time)."""
    phone = wa_phone_id()
    if not phone:
        raise MetaError("META_WA_PHONE_NUMBER_ID is not set.")
    to = _phone_digits(to)
    if not to:
        raise MetaError("a WhatsApp number is required")
    if template:
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {"name": template, "language": {"code": language or "en"}},
        }
    elif message:
        payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": message}}
    else:
        raise MetaError("message or template is required")
    data = graph("POST", f"{phone}/messages", body=payload)
    return {"ok": True, "messageId": (data.get("messages") or [{}])[0].get("id"), "to": to}


def op_reply_whatsapp(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    to = resolve_whatsapp_recipient(getattr(ctx, "table", None), args)
    message = str(args.get("message") or "").strip()
    template = str(args.get("template") or "").strip()
    if not to or not (message or template):
        raise MetaError("threadId (or to) and message or template are required")
    out = _send_whatsapp(to, message=message, template=template, language=str(args.get("language") or "en"))
    out["threadId"] = whatsapp_thread_id(to)
    return out


def _parse_daily_budget(args: dict[str, Any]) -> float:
    try:
        daily = float(args.get("dailyBudgetUsd"))
    except (TypeError, ValueError) as exc:
        raise MetaError("dailyBudgetUsd must be a number") from exc
    if daily <= 0:
        raise MetaError("dailyBudgetUsd must be positive")
    return daily


def _parse_boost_days(args: dict[str, Any]) -> int:
    raw = args.get("days", 7)
    try:
        days = int(raw)
    except (TypeError, ValueError) as exc:
        raise MetaError("days must be an integer") from exc
    if days < 1 or days > 30:
        raise MetaError("days must be between 1 and 30")
    return days


def _object_story_id(post_id: str) -> str:
    if "_" in post_id:
        return post_id
    pid = page_id()
    return f"{pid}_{post_id}" if pid else post_id


def _record_ads_commitment(ctx: Any, *, daily: float, days: int) -> None:
    table = getattr(ctx, "table", None)
    if table is None:
        return
    board_store.record_ads_spend(table, daily_usd=daily, monthly_usd=daily * days)


def op_create_ad_set(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    aid = str(args.get("adAccountId") or ad_account_id())
    name = str(args.get("name") or "").strip()
    daily = _parse_daily_budget(args)
    if not aid or not name:
        raise MetaError("adAccountId, name and a positive dailyBudgetUsd are required")
    monthly = daily * 30
    if daily > board_store.ADS_DAILY_CAP_MAX:
        raise MetaError(f"dailyBudgetUsd exceeds the hard daily ceiling of USD {board_store.ADS_DAILY_CAP_MAX:.0f}")
    if monthly > board_store.ADS_MONTHLY_CAP_MAX:
        raise MetaError(
            f"dailyBudgetUsd * 30 ({monthly:.2f}) exceeds the hard monthly ceiling of USD {board_store.ADS_MONTHLY_CAP_MAX:.0f}"
        )
    data = graph(
        "POST",
        f"{aid}/adsets",
        body={
            "name": name,
            "daily_budget": int(round(daily * 100)),
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "REACH",
            "status": "PAUSED",
            "campaign_id": str(args.get("campaignId") or ""),
        },
    )
    _record_ads_commitment(ctx, daily=daily, days=30)
    return {"ok": True, "adSetId": data.get("id"), "dailyBudgetUsd": daily, "status": "PAUSED"}


def op_boost_post(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    post_id = str(args.get("postId") or "").strip()
    daily = _parse_daily_budget(args)
    days = _parse_boost_days(args)
    aid = str(args.get("adAccountId") or ad_account_id())
    if not post_id or not aid:
        raise MetaError("postId and META_AD_ACCOUNT_ID are required")
    monthly = daily * days
    if daily > board_store.ADS_DAILY_CAP_MAX:
        raise MetaError(f"dailyBudgetUsd exceeds the hard daily ceiling of USD {board_store.ADS_DAILY_CAP_MAX:.0f}")
    if monthly > board_store.ADS_MONTHLY_CAP_MAX:
        raise MetaError(
            f"dailyBudgetUsd * days ({monthly:.2f}) exceeds the hard monthly ceiling of USD {board_store.ADS_MONTHLY_CAP_MAX:.0f}"
        )
    story_id = _object_story_id(post_id)
    end = datetime.now(timezone.utc) + timedelta(days=days)
    campaign = graph(
        "POST",
        f"{aid}/campaigns",
        body={
            "name": f"Boost {post_id}"[:80],
            "objective": "OUTCOME_ENGAGEMENT",
            "status": "ACTIVE",
            "special_ad_categories": [],
        },
    )
    campaign_id = campaign.get("id")
    if not campaign_id:
        raise MetaError("Meta did not return a campaign id")
    adset = graph(
        "POST",
        f"{aid}/adsets",
        body={
            "name": f"Boost {post_id}"[:80],
            "campaign_id": campaign_id,
            "daily_budget": int(round(daily * 100)),
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "POST_ENGAGEMENT",
            "status": "ACTIVE",
            "end_time": end.strftime("%Y-%m-%dT%H:%M:%S+0000"),
            "targeting": {"geo_locations": {"countries": ["HK"]}},
        },
    )
    adset_id = adset.get("id")
    if not adset_id:
        raise MetaError("Meta did not return an ad set id")
    ad = graph(
        "POST",
        f"{aid}/ads",
        body={
            "name": f"Boost {post_id}"[:80],
            "adset_id": adset_id,
            "status": "ACTIVE",
            "creative": {"object_story_id": story_id},
        },
    )
    _record_ads_commitment(ctx, daily=daily, days=days)
    return {
        "ok": True,
        "postId": post_id,
        "objectStoryId": story_id,
        "campaignId": campaign_id,
        "adSetId": adset_id,
        "adId": ad.get("id"),
        "dailyBudgetUsd": daily,
        "days": days,
        "status": "ACTIVE",
    }


def _relay_lead_action(ctx: Any, *, provider: str, provider_phone: str, parent: str, summary: str) -> dict[str, Any]:
    """Open action so the founder can see the hand-off was made and chase the provider."""
    now = datetime.now(timezone.utc)
    who = provider or provider_phone
    doc = {
        "actionId": board_store.new_id(),
        "title": f"Lead hand-off: {who}"[:200],
        "detail": (summary or f"Parent {parent} introduced to {who}.")[:800],
        "persona": getattr(ctx, "persona_id", None) or "coo",
        "priority": "now",
        "effort": "S",
        "metric": "Provider replied to the parent within one working day",
        "dependsOn": [],
        "status": "open",
        "note": "",
        "meetingId": getattr(ctx, "meeting_id", "") or "",
        # Reachable only via act to allow-listed contacts or after founder approval.
        "source": "approval",
        "reaffirmedByMeetingIds": [],
        "dueAt": _utc_iso_z(now + timedelta(days=1)),
        "createdAt": _utc_iso_z(now),
        "updatedAt": _utc_iso_z(now),
        "providerEmail": provider,
        "providerPhone": provider_phone,
        "parentEmail": parent,
    }
    board_store.put_action(ctx.table, doc)
    return doc


def op_relay_lead(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Hand a parent lead to the provider (email and/or WhatsApp template), confirm to the parent, record an action."""
    provider = str(args.get("providerEmail") or "").strip()
    provider_phone = str(args.get("providerPhone") or "").strip()
    template = str(args.get("template") or "").strip()
    parent = str(args.get("parentEmail") or "").strip()
    summary = str(args.get("summary") or args.get("reason") or "").strip()
    if not parent or not (provider or provider_phone):
        raise MetaError("parentEmail and providerEmail or providerPhone are required")
    if provider_phone and not template:
        raise MetaError("template is required for a WhatsApp hand-off (providerPhone)")
    action = _relay_lead_action(ctx, provider=provider, provider_phone=provider_phone, parent=parent, summary=summary)
    out: dict[str, Any] = {
        "ok": True,
        "actionId": action["actionId"],
        "providerEmail": provider,
        "providerPhone": provider_phone,
        "parentEmail": parent,
    }
    if provider_phone:
        out["whatsapp"] = _send_whatsapp(provider_phone, template=template, language=str(args.get("language") or "en"))
    if not board_mail.sending_enabled():
        out["sent"] = False
        out["note"] = "Mail sending is off; the hand-off is recorded as a board action" + (
            " and sent to the provider on WhatsApp." if provider_phone else " only."
        )
        return out
    sent_by = getattr(ctx, "persona_id", "coo")
    if provider:
        handoff = board_mail.outgoing_plan(
            ctx.table,
            op="mail_send",
            args={
                "fromMailbox": "hello",
                "to": [provider],
                "subject": "New parent lead from siutindei",
                "body": summary or "A parent asked to be introduced. Please reply within one working day.",
            },
        )
        out["provider"] = board_mail.send_plan(ctx.table, handoff, sent_by=sent_by)
    confirm = board_mail.outgoing_plan(
        ctx.table,
        op="mail_send",
        args={
            "fromMailbox": "hello",
            "to": [parent],
            "subject": "We have passed your request to the provider",
            "body": "Thanks — we have introduced you to the provider. They will contact you shortly.",
        },
    )
    out["parent"] = board_mail.send_plan(ctx.table, confirm, sent_by=sent_by)
    out["sent"] = True
    return out


def act_guard_whatsapp(ctx: Any, args: dict[str, Any]) -> str | None:
    """Act only to an allow-listed number whose *own* thread is inside the 24-hour window.

    The window is looked up by the recipient number, never by a model-supplied
    ``threadId``. A template outside the window is a proposal (plan §5.3).
    """
    try:
        to = resolve_whatsapp_recipient(ctx.table, args)
    except MetaError as exc:
        return str(exc)
    if not to:
        return "to or threadId is required"
    if not _recipient_allowed(ctx.settings, to):
        return f"{to} is not on the allow-list"
    thread = board_store.get_meta_thread(ctx.table, whatsapp_thread_id(to))
    if thread and _in_window(thread):
        return None
    if args.get("template"):
        return "the 24-hour WhatsApp window is closed for this recipient; template messages outside it need approval"
    if thread:
        return "the 24-hour WhatsApp customer-service window is closed; use a pre-approved template"
    return "no open WhatsApp window for this recipient"


def act_guard_allow_list(ctx: Any, args: dict[str, Any], *, field: str) -> str | None:
    if field == "recipientId":
        try:
            value = resolve_dm_recipient(ctx.table, args)
        except MetaError as exc:
            return str(exc)
    else:
        value = str(args.get(field) or "").strip()
    if not value:
        return f"{field} is required"
    if not _recipient_allowed(ctx.settings, value):
        return f"{value} is not on the allow-list"
    return None


def act_guard_relay(ctx: Any, args: dict[str, Any]) -> str | None:
    fields = ["parentEmail"]
    if str(args.get("providerPhone") or "").strip():
        fields.append("providerPhone")
    if str(args.get("providerEmail") or "").strip() or not str(args.get("providerPhone") or "").strip():
        fields.append("providerEmail")
    for field in fields:
        reason = act_guard_allow_list(ctx, args, field=field)
        if reason:
            return reason
    return None


def _phone_digits(value: str) -> str:
    return re.sub(r"\D", "", board_pii.normalize_phone(value) or "")


def act_guard_ads(ctx: Any, args: dict[str, Any], *, days: int | None = None) -> str | None:
    try:
        daily = float(args.get("dailyBudgetUsd"))
    except (TypeError, ValueError):
        return "dailyBudgetUsd must be a number"
    if daily <= 0:
        return "dailyBudgetUsd must be positive"
    span = days
    if span is None:
        raw_days = args.get("days")
        if raw_days is None:
            span = 30
        else:
            try:
                span = int(raw_days)
            except (TypeError, ValueError):
                return "days must be an integer"
    if span < 1 or span > 30:
        return "days must be between 1 and 30"
    daily_cap, monthly_cap = ads_caps(getattr(ctx, "settings", None))
    monthly = daily * span
    if daily > daily_cap:
        return f"the daily budget exceeds the USD {daily_cap:.0f} daily cap"
    if monthly > monthly_cap:
        return f"the proposed monthly spend exceeds the USD {monthly_cap:.0f} cap"
    snapshot = ads_spend_snapshot(getattr(ctx, "table", None), getattr(ctx, "settings", None))
    if snapshot["dailyUsd"] + daily > daily_cap:
        return f"today's ads spend would exceed the USD {daily_cap:.0f} daily cap"
    if snapshot["monthlyUsd"] + monthly > monthly_cap:
        return f"this month's ads spend would exceed the USD {monthly_cap:.0f} cap"
    return None


def act_guard_ad_set(ctx: Any, args: dict[str, Any]) -> str | None:
    return act_guard_ads(ctx, args, days=30)


def act_guard_boost_post(ctx: Any, args: dict[str, Any]) -> str | None:
    if not str(args.get("postId") or "").strip():
        return "postId is required"
    return act_guard_ads(ctx, args)


def _recipient_allowed(settings: dict[str, Any], value: str) -> bool:
    if "@" in value:
        return board_mail.recipient_allowed(settings, value)
    entries = (settings.get("tools") or {}).get("allowList") or []
    digits = _phone_digits(value)
    if not digits:
        return False
    return any(_phone_digits(str(e)) == digits for e in entries if isinstance(e, str) and "@" not in str(e))


def owner_preview_message(ctx: Any, args: dict[str, Any], *, op: str) -> dict[str, Any]:
    """Owner-facing payload: real recipients (resolved from the stored thread), never aliases."""
    table = getattr(ctx, "table", None)
    recipients: list[str] = []
    error = ""
    try:
        if op == "meta_reply_whatsapp":
            recipients = [resolve_whatsapp_recipient(table, args)]
        elif op == "meta_reply_dm":
            recipients = [resolve_dm_recipient(table, args)]
        elif op == "meta_relay_lead":
            recipients = [
                str(args.get(k) or "").strip()
                for k in ("providerEmail", "providerPhone", "parentEmail")
            ]
        else:
            recipients = [str(args.get("to") or args.get("recipientId") or "").strip()]
    except MetaError as exc:
        error = str(exc)
    recipients = [r for r in recipients if r]
    first = recipients[0] if recipients else ""
    out = {
        "kind": "email" if "@" in first else "meta",
        "from": "whatsapp" if "whatsapp" in op else ("instagram" if "story" in op else "facebook"),
        "to": recipients,
        "cc": [],
        "subject": str(args.get("name") or args.get("postId") or args.get("template") or op),
        "text": str(args.get("message") or args.get("caption") or args.get("summary") or args.get("reason") or ""),
        "threadId": str(args.get("threadId") or ""),
        "sendEnabled": configured(),
    }
    if error:
        out["error"] = error
    return out


def digest_for_context(table: Any) -> dict[str, Any]:
    if table is None:
        return {}
    threads = board_store.list_meta_threads(table)
    unread = sum(1 for t in threads if t.get("unread"))
    wa = sum(1 for t in threads if t.get("channel") == "whatsapp")
    return {"unread": unread, "threads": len(threads), "whatsappThreads": wa}
