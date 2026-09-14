"""Public API-key board/finance path classes, redaction, and use-notify."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from contract_constants import BOARD_KEY
from http_common import _log_event, _request_id

SCOPE_FINANCE = "finance"
SCOPE_BOARD_OPS = "siutindei-board-ops"
SCOPE_BOARD_FULL = "siutindei-board-full"
SCOPE_PII = "siutindei-pii"
SCOPE_ASSETS = "siutindei-assets"

ALL_SCOPES = frozenset(
    {
        SCOPE_FINANCE,
        SCOPE_BOARD_OPS,
        SCOPE_BOARD_FULL,
        SCOPE_PII,
        SCOPE_ASSETS,
    }
)

PUBLIC_BOARD_PREFIX = "/public/siu-tin-dei/board"
FINANCE_PATHS = frozenset(
    {
        "/public/finance",
        "/public/finance/quotes",
        "/public/records",
        "/public/fx/v2/rates",
    }
)
BOARD_OPS_HEADS = frozenset(
    {"staff", "tasks", "breakers", "review", "holds", "ramp", "tools"}
)
# Third-party contact / billing data that has no alias layer, so it cannot be
# masked like mail; these heads need `siutindei-pii` on top of board-full.
PII_HEADS = frozenset({"prospects", "outreach", "receivables"})
WRITE_METHODS = frozenset({"PUT", "POST", "DELETE"})
NOTIFY_COALESCE_SECONDS = 60
NOTIFY_ROW_TTL = timedelta(days=1)
NOTIFY_SUBJECT = "Public API key used"


def parse_scopes(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return sorted({str(s).strip() for s in raw if str(s).strip() in ALL_SCOPES})
    text = str(raw or "").strip()
    if not text:
        return []
    return sorted({part.strip() for part in text.split(",") if part.strip() in ALL_SCOPES})


def scopes_from_key_context(key_ctx: dict[str, Any]) -> list[str]:
    scopes = parse_scopes(key_ctx.get("scopes"))
    if scopes:
        return scopes
    if key_ctx.get("scope") == "read":
        return [SCOPE_FINANCE]
    return []


def _board_rest(path: str) -> list[str]:
    if path == PUBLIC_BOARD_PREFIX:
        return []
    if not path.startswith(PUBLIC_BOARD_PREFIX + "/"):
        return []
    return [p for p in path[len(PUBLIC_BOARD_PREFIX) + 1 :].split("/") if p]


def path_class(path: str) -> str | None:
    if path in FINANCE_PATHS:
        return SCOPE_FINANCE
    if path != PUBLIC_BOARD_PREFIX and not path.startswith(PUBLIC_BOARD_PREFIX + "/"):
        return None
    rest = _board_rest(path)
    if not rest:
        return SCOPE_BOARD_OPS
    head = rest[0]
    if head in BOARD_OPS_HEADS:
        if head == "tools" and len(rest) == 2 and rest[1] != "calls":
            return SCOPE_BOARD_FULL
        if head == "review" and len(rest) > 1:
            return SCOPE_BOARD_FULL
        return SCOPE_BOARD_OPS
    return SCOPE_BOARD_FULL


def path_allowed(path: str, scopes: list[str]) -> bool:
    needed = path_class(path)
    if needed is None:
        return False
    have = set(scopes)
    if needed == SCOPE_FINANCE:
        return SCOPE_FINANCE in have
    if needed == SCOPE_BOARD_OPS:
        return SCOPE_BOARD_OPS in have or SCOPE_BOARD_FULL in have
    if SCOPE_BOARD_FULL not in have:
        return False
    rest = _board_rest(path)
    if rest[:1] and rest[0] in PII_HEADS:
        return SCOPE_PII in have
    return True


def writes_enabled() -> bool:
    """Fail-closed stack kill switch (``PublicApiWritesEnabled``)."""
    return (os.environ.get("PUBLIC_API_WRITES_ENABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def key_context_allows_write(key_ctx: dict[str, Any]) -> bool:
    """Authorizer forwards ``write`` as ``1``/``0`` (API Gateway context is strings)."""
    raw = key_ctx.get("write")
    if raw in (True, 1, "1"):
        return True
    if isinstance(raw, str) and raw.strip().lower() in ("true", "yes", "on"):
        return True
    return False


def write_blocked(method: str, path: str) -> bool:
    """Owner-only (JWT) writes even when the key has allowWrite.

    Cost/safety knobs (settings, boundaries, tools), production promote,
    approvals, mail selftest, and non-reversible live-state mutations
    (chat wipe, meeting/task cancel, staff tick, ramp pause).
    """
    rest = _board_rest(path)
    if not rest:
        return True
    head = rest[0]
    tail = rest[-1]
    if method == "PUT" and rest in (["settings"], ["boundaries"], ["tools"]):
        return True
    if method == "POST" and rest in (["code", "promote"], ["mail", "selftest"], ["staff", "tick"]):
        return True
    if method == "POST" and head == "approvals" and len(rest) == 3 and tail in ("approve", "reject"):
        return True
    if method == "POST" and head == "ramp" and len(rest) == 3 and tail in ("promote", "pause"):
        return True
    if method == "POST" and head == "meetings" and len(rest) == 3 and tail == "cancel":
        return True
    if method == "POST" and head == "tasks" and len(rest) == 3 and tail == "cancel":
        return True
    if method == "DELETE" and head == "chat" and len(rest) == 2:
        return True
    return False


def write_deny_reason(
    method: str, path: str, key_ctx: dict[str, Any], scopes: list[str]
) -> str | None:
    """None when the write is allowed; otherwise a stable ``public_api_denied`` reason."""
    if method not in WRITE_METHODS:
        return "not_write"
    if not writes_enabled():
        return "writes_disabled"
    if not key_context_allows_write(key_ctx):
        return "key_read_only"
    needed = path_class(path)
    if needed is None:
        return "not_allowlisted"
    if needed == SCOPE_FINANCE:
        return "finance_read_only"
    if write_blocked(method, path):
        return "owner_only"
    if not path_allowed(path, scopes):
        return "scope"
    return None


def write_allowed(
    method: str, path: str, key_ctx: dict[str, Any], scopes: list[str]
) -> bool:
    return write_deny_reason(method, path, key_ctx, scopes) is None


def _source_ip(event: dict[str, Any]) -> str:
    http = (event.get("requestContext") or {}).get("http") or {}
    return str(http.get("sourceIp") or "").strip()


def _user_agent(event: dict[str, Any]) -> str:
    headers = event.get("headers") or {}
    for key, value in headers.items():
        if str(key).lower() == "user-agent":
            return str(value or "")[:200]
    http = (event.get("requestContext") or {}).get("http") or {}
    return str(http.get("userAgent") or "")[:200]


def redact_board_response(
    path: str, response: dict[str, Any], scopes: list[str]
) -> dict[str, Any]:
    """Strip owner PII and presigned URLs unless the key has the extra scopes."""
    have = set(scopes)
    try:
        body = json.loads(response.get("body") or "{}")
    except json.JSONDecodeError:
        return response
    if not isinstance(body, dict):
        return response
    changed = False
    if SCOPE_PII not in have:
        if _redact_owner_pii(body):
            changed = True
    rest = _board_rest(path)
    if rest[:1] == ["mail"] and SCOPE_PII not in have:
        body = _mask_mail_payload(body)
        changed = True
    if (
        len(rest) == 4
        and rest[0] == "content"
        and rest[2] == "creative"
        and SCOPE_ASSETS not in have
        and "url" in body
    ):
        body = {k: v for k, v in body.items() if k != "url"}
        changed = True
    if not changed:
        return response
    return {**response, "body": json.dumps(body, default=str)}


def _strip_allow_list(tools: Any) -> bool:
    if not isinstance(tools, dict) or not tools.get("allowList"):
        return False
    raw = tools["allowList"]
    if isinstance(raw, dict):
        tools["allowList"] = {k: [] if isinstance(v, list) else v for k, v in raw.items()}
    else:
        tools["allowList"] = []
    return True


def _strip_digest_to(review: Any) -> bool:
    if not isinstance(review, dict) or not review.get("digestTo"):
        return False
    review["digestTo"] = ""
    return True


def _redact_owner_pii(body: dict[str, Any]) -> bool:
    """Strip allow-list / digest mailbox from overview, settings, and GET /tools."""
    changed = False
    settings = body.get("settings")
    if isinstance(settings, dict):
        changed = _strip_allow_list(settings.get("tools")) or changed
        changed = _strip_digest_to(settings.get("review")) or changed
    # GET /tools puts the same config under ``config``, not ``settings``.
    changed = _strip_allow_list(body.get("config")) or changed
    changed = _strip_allow_list(body.get("tools")) or changed
    changed = _strip_digest_to(body.get("review")) or changed
    return changed


def _mask_mail_payload(body: dict[str, Any]) -> dict[str, Any]:
    import board_mail
    import board_pii
    import board_store

    table = board_store.records_table()
    pseud = board_pii.Pseudonymizer(table, own_domains=board_mail.own_domains())
    out = dict(body)
    if isinstance(out.get("threads"), list):
        out["threads"] = [
            board_mail.masked_thread(pseud, t) if isinstance(t, dict) else t
            for t in out["threads"]
        ]
    if isinstance(out.get("thread"), dict):
        out["thread"] = board_mail.masked_thread(pseud, out["thread"])
    if isinstance(out.get("messages"), list):
        out["messages"] = [
            board_mail.masked_message(pseud, m) if isinstance(m, dict) else m
            for m in out["messages"]
        ]
    try:
        pseud.save()
    except Exception as exc:
        _log_event("warning", tag="public_api_mail_mask_save_failed", error=str(exc)[:200])
    return out


def _notify_sk(key_id: str, path_cls: str, source_ip: str) -> str:
    ip = source_ip or "unknown"
    return f"{key_id}#{path_cls}#{ip}"[:400]


def try_claim_notify_slot(
    table: Any, *, key_id: str, path_cls: str, source_ip: str, now: datetime | None = None
) -> bool:
    """True when this (key, class, ip) has not mailed within the coalesce window."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(seconds=NOTIFY_COALESCE_SECONDS)).isoformat()
    now_iso = now.isoformat()
    # `expiresAt` is the table TTL attribute (epoch seconds); one row per
    # (key, class, ip) would otherwise accumulate for every client address.
    ttl_epoch = int((now + NOTIFY_ROW_TTL).timestamp())
    try:
        table.update_item(
            Key={
                "pk": f"BOARD#{BOARD_KEY}#publicapi#notify",
                "sk": _notify_sk(key_id, path_cls, source_ip),
            },
            UpdateExpression=(
                "SET lastSentAt = :now, sourceIp = :ip, pathClass = :cls, expiresAt = :ttl"
            ),
            ConditionExpression="attribute_not_exists(lastSentAt) OR lastSentAt < :cutoff",
            ExpressionAttributeValues={
                ":now": now_iso,
                ":ip": source_ip or "unknown",
                ":cls": path_cls,
                ":cutoff": cutoff,
                ":ttl": ttl_epoch,
            },
        )
        return True
    except Exception as exc:
        code = ""
        response = getattr(exc, "response", None)
        if isinstance(response, dict):
            code = str((response.get("Error") or {}).get("Code") or "")
        if code == "ConditionalCheckFailedException" or "ConditionalCheckFailed" in type(exc).__name__:
            return False
        # FakeTable raises ClientError-like; also treat condition failures from _evaluate
        if "conditional" in str(exc).lower():
            return False
        _log_event("warning", tag="public_api_notify_claim_failed", error=str(exc)[:200])
        return False


def notify_key_use(
    event: dict[str, Any],
    *,
    key_ctx: dict[str, Any],
    path: str,
    method: str,
    kind: str = "allowed",
    reason: str = "",
    path_cls: str | None = None,
) -> None:
    """Mail settings.review.digestTo. Fail open. Coalesce 60s per key/class/ip."""
    import board_mail
    import board_store

    key_id = str(key_ctx.get("keyId") or "").strip()
    if not key_id:
        return
    path_cls = path_cls or path_class(path) or "unknown"
    source_ip = _source_ip(event) or str(key_ctx.get("sourceIp") or "")
    table = board_store.records_table()
    # Every write mails digestTo; reads stay coalesced 60s per (key, class, ip).
    coalesce = kind not in ("write",)
    if coalesce and not try_claim_notify_slot(
        table, key_id=key_id, path_cls=f"{kind}:{path_cls}", source_ip=source_ip
    ):
        _log_event(
            "info",
            tag="public_api_notify_coalesced",
            key_id=key_id,
            path_class=path_cls,
            kind=kind,
        )
        return
    settings = board_store.load_settings(table)
    digest_to = str((settings.get("review") or {}).get("digestTo") or "").strip()
    if not digest_to:
        _log_event("info", tag="public_api_notify_skipped", reason="no_digest_to", key_id=key_id)
        return
    if not board_mail.sending_enabled():
        _log_event("info", tag="public_api_notify_skipped", reason="sending_off", key_id=key_id)
        return
    scopes = scopes_from_key_context(key_ctx)
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        f"A public API key was used ({kind}).",
        "",
        f"time: {now}",
        f"keyId: {key_id}",
        f"label: {key_ctx.get('label') or ''}",
        f"scopes: {','.join(scopes)}",
        f"method: {method}",
        f"path: {path}",
        f"pathClass: {path_cls}",
        f"sourceIp: {source_ip or 'unknown'}",
        f"userAgent: {_user_agent(event)}",
        f"requestId: {_request_id(event)}",
    ]
    if reason:
        lines.append(f"reason: {reason}")
    try:
        board_mail.send_plan(
            table,
            {
                "fromMailbox": "hello",
                "to": [digest_to],
                "cc": [],
                "subject": NOTIFY_SUBJECT,
                "text": "\n".join(lines) + "\n",
            },
            sent_by="public-api-key",
            index=False,
        )
        _log_event("info", tag="public_api_notify_sent", key_id=key_id, path_class=path_cls, kind=kind)
    except Exception as exc:
        _log_event("warning", tag="public_api_notify_failed", key_id=key_id, error=str(exc)[:200])


def handle_internal_notify(event: dict[str, Any]) -> dict[str, Any]:
    notify_key_use(
        event,
        key_ctx={
            "keyId": event.get("keyId"),
            "label": event.get("label"),
            "scopes": event.get("scopes"),
            "sourceIp": event.get("sourceIp"),
        },
        path=str(event.get("path") or ""),
        method=str(event["method"]) if "method" in event else "GET",
        kind=str(event.get("kind") or "denied"),
        reason=str(event.get("reason") or ""),
        path_cls=str(event.get("pathClass") or "denied"),
    )
    return {}
