"""LX Software LinkedIn drafts, ideas, and settings.

Rows live in the records table under ``LINKEDIN#`` and stay out of ``/records``.
Posts are a personal presence queue: the default voice does not mention LX
Software or sibling products. Publishing to LinkedIn is a later step; this
module only stores drafts, assigns 08:30 HKT slots, and records a hand post.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import board_store
from ddb_convert import _from_ddb_nested, _to_ddb_nested

HKT = ZoneInfo("Asia/Hong_Kong")

PK_PREFIX = "LINKEDIN#"
BODY_MAX = 3000
COMMENT_MAX = 1250
HOOK_MAX = 210
HASHTAG_CAP_DEFAULT = 3
POSTS_PER_WEEK_DEFAULT = 2
# Tuesday and Thursday. Monday is 0.
WEEKDAYS_DEFAULT = (1, 3)
SLOT_HOUR_DEFAULT = 8
SLOT_MINUTE_DEFAULT = 30
DRAFTS_PER_GENERATION_DEFAULT = 4
MAX_USD_DEFAULT = 5.0

STATUSES = ("drafted", "approved", "published", "archived", "failed")
IDEA_STATUSES = ("new", "used")

# Built-in blocks. The owner adds an employer name in settings; it is not
# stored in source.
BUILTIN_FORBIDDEN = (
    "lx software",
    "lx-software",
    "lxsoftware",
    "interim",
    "available immediately",
    "open to work",
    "looking for work",
    "hire me",
)
PRODUCT_PHRASES = (
    "siu tin dei",
    "siutindei",
    "evolve sprouts",
    "evolvesprouts",
)

PILLARS: tuple[dict[str, str], ...] = (
    {
        "id": "architecture",
        "label": "Architecture decisions",
        "brief": "A trade-off in system design, and what you would repeat.",
    },
    {
        "id": "leadership",
        "label": "Engineering leadership",
        "brief": "How a team made a decision, ran a review, or handled a miss.",
    },
    {
        "id": "platforms",
        "label": "Cloud and platforms",
        "brief": "A platform, reliability, or delivery lesson. No vendor pitch.",
    },
    {
        "id": "ai-practice",
        "label": "AI in practice",
        "brief": "Where an AI tool helped or failed in real engineering work.",
    },
    {
        "id": "delivery",
        "label": "Lessons from delivery",
        "brief": "Something a project taught you about scope, risk, or quality.",
    },
    {
        "id": "questions",
        "label": "Questions I get asked",
        "brief": "A question a colleague or founder asked, and the answer you give.",
    },
)

_EMAIL = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
_PHONE = re.compile(r"(?:\+\d{8,15})|(?:\b\d{8,}\b)")
_URL = re.compile(r"(https?://|www\.)\S+", re.I)
_HASH = re.compile(r"#(\w+)")


class LinkedInError(ValueError):
    """Invalid LinkedIn input."""


def feature_enabled() -> bool:
    return os.environ.get("LINKEDIN_ENABLED", "").strip().lower() == "true"


def publish_enabled() -> bool:
    return os.environ.get("LINKEDIN_PUBLISH_ENABLED", "").strip().lower() == "true"


def pillar_ids() -> set[str]:
    return {row["id"] for row in PILLARS}


def pillar_label(pillar_id: str) -> str:
    for row in PILLARS:
        if row["id"] == pillar_id:
            return row["label"]
    return pillar_id


def default_settings() -> dict[str, Any]:
    return {
        "postsPerWeek": POSTS_PER_WEEK_DEFAULT,
        "weekdays": list(WEEKDAYS_DEFAULT),
        "slotHour": SLOT_HOUR_DEFAULT,
        "slotMinute": SLOT_MINUTE_DEFAULT,
        "draftsPerGeneration": DRAFTS_PER_GENERATION_DEFAULT,
        "voiceNotes": (
            "Senior architect writing in the first person. One lesson per post. "
            "No company name, no employer, no offer of availability."
        ),
        "forbiddenWords": [],
        "hashtagCap": HASHTAG_CAP_DEFAULT,
        "linksInFirstComment": False,
        "allowProductMentions": False,
        "maxUsdPerMonth": MAX_USD_DEFAULT,
        "notifyEmail": "",
        "pillars": [row["id"] for row in PILLARS],
    }


def _new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:12]


def _strip(item: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in item.items()
        if k not in ("pk", "sk", "gsi1pk", "gsi1sk", "expiresAt")
    }


def _put(table: Any, item: dict[str, Any]) -> None:
    table.put_item(Item=_to_ddb_nested(item))


def _get(table: Any, pk: str, sk: str = "META") -> dict[str, Any] | None:
    res = table.get_item(Key={"pk": pk, "sk": sk})
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = _from_ddb_nested(_strip(item))
    return doc if isinstance(doc, dict) else None


def _query(table: Any, gsi_pk: str, *, limit: int = 200) -> list[dict[str, Any]]:
    res = table.query(
        IndexName="gsi1",
        KeyConditionExpression="gsi1pk = :pk",
        ExpressionAttributeValues={":pk": gsi_pk},
        ScanIndexForward=True,
        Limit=limit,
    )
    rows = res.get("Items") if isinstance(res, dict) else None
    out: list[dict[str, Any]] = []
    for row in rows or []:
        doc = _from_ddb_nested(_strip(row))
        if isinstance(doc, dict):
            out.append(doc)
    out.sort(key=lambda doc: str(doc.get("slotAt") or doc.get("createdAt") or ""))
    return out


def state_key() -> dict[str, str]:
    return {"pk": "LINKEDIN#state", "sk": "STATE"}


def load_state(table: Any) -> dict[str, Any]:
    doc = _get(table, "LINKEDIN#state", "STATE")
    return doc or {}


def save_state(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    doc = {**doc, "updatedAt": board_store.now_iso()}
    _put(table, {**state_key(), **doc})
    return doc


def load_settings(table: Any) -> dict[str, Any]:
    stored = load_state(table).get("settings")
    merged = default_settings()
    if isinstance(stored, dict):
        merged.update({k: v for k, v in stored.items() if k in merged})
    merged["weekdays"] = _weekdays(merged.get("weekdays"))
    merged["pillars"] = _pillars(merged.get("pillars"))
    merged["forbiddenWords"] = _words(merged.get("forbiddenWords"))
    return merged


def _weekdays(value: Any) -> list[int]:
    if not isinstance(value, list):
        return list(WEEKDAYS_DEFAULT)
    out: list[int] = []
    for item in value:
        try:
            day = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6 and day not in out:
            out.append(day)
    return out or list(WEEKDAYS_DEFAULT)


def _pillars(value: Any) -> list[str]:
    known = pillar_ids()
    if not isinstance(value, list):
        return [row["id"] for row in PILLARS]
    out = [str(item) for item in value if str(item) in known]
    return out or [row["id"] for row in PILLARS]


def _words(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        word = str(item).strip().lower()
        if word and word not in out and len(word) <= 40:
            out.append(word)
        if len(out) >= 40:
            break
    return out


def validate_settings(body: dict[str, Any]) -> dict[str, Any]:
    """Merge a settings write onto defaults. Raises LinkedInError."""
    current = default_settings()
    if not isinstance(body, dict):
        raise LinkedInError("settings must be an object")
    try:
        posts = int(body.get("postsPerWeek", current["postsPerWeek"]))
        hour = int(body.get("slotHour", current["slotHour"]))
        minute = int(body.get("slotMinute", current["slotMinute"]))
        drafts = int(body.get("draftsPerGeneration", current["draftsPerGeneration"]))
        cap = int(body.get("hashtagCap", current["hashtagCap"]))
        budget = float(body.get("maxUsdPerMonth", current["maxUsdPerMonth"]))
    except (TypeError, ValueError) as exc:
        raise LinkedInError("settings numbers are invalid") from exc
    if not 1 <= posts <= 7:
        raise LinkedInError("postsPerWeek must be 1 to 7")
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise LinkedInError("slot time is invalid")
    if not 1 <= drafts <= 6:
        raise LinkedInError("draftsPerGeneration must be 1 to 6")
    if not 0 <= cap <= 5:
        raise LinkedInError("hashtagCap must be 0 to 5")
    if not 0 <= budget <= 50:
        raise LinkedInError("maxUsdPerMonth must be 0 to 50")
    weekdays = _weekdays(body.get("weekdays", current["weekdays"]))
    if len(weekdays) < 1:
        raise LinkedInError("pick at least one weekday")
    voice = str(body.get("voiceNotes", current["voiceNotes"]) or "").strip()
    if len(voice) > 1000:
        raise LinkedInError("voiceNotes is too long")
    notify = str(body.get("notifyEmail", current["notifyEmail"]) or "").strip()
    if notify and (notify.count("@") != 1 or notify.startswith("@") or notify.endswith("@")):
        raise LinkedInError("notifyEmail is invalid")
    pillars = _pillars(body.get("pillars", current["pillars"]))
    return {
        "postsPerWeek": posts,
        "weekdays": weekdays,
        "slotHour": hour,
        "slotMinute": minute,
        "draftsPerGeneration": drafts,
        "voiceNotes": voice or str(current["voiceNotes"]),
        "forbiddenWords": _words(body.get("forbiddenWords", current["forbiddenWords"])),
        "hashtagCap": cap,
        "linksInFirstComment": bool(body.get("linksInFirstComment", False)),
        "allowProductMentions": bool(body.get("allowProductMentions", False)),
        "maxUsdPerMonth": round(budget, 2),
        "notifyEmail": notify,
        "pillars": pillars,
    }


def save_settings(table: Any, body: dict[str, Any]) -> dict[str, Any]:
    settings = validate_settings(body)
    state = load_state(table)
    state["settings"] = settings
    save_state(table, state)
    return settings


def month_key(now: datetime | None = None) -> str:
    local = (now or datetime.now(HKT)).astimezone(HKT)
    return f"{local.year:04d}-{local.month:02d}"


def month_spend(table: Any, now: datetime | None = None) -> float:
    spend = load_state(table).get("spend")
    if not isinstance(spend, dict):
        return 0.0
    try:
        return float(spend.get(month_key(now)) or 0)
    except (TypeError, ValueError):
        return 0.0


def add_spend(table: Any, usd: float, now: datetime | None = None) -> float:
    if usd <= 0:
        return month_spend(table, now)
    state = load_state(table)
    spend = dict(state.get("spend") or {})
    key = month_key(now)
    try:
        current = float(spend.get(key) or 0)
    except (TypeError, ValueError):
        current = 0.0
    spend[key] = round(current + usd, 6)
    # Keep the trailing thirteen months.
    keys = sorted(spend)[-13:]
    state["spend"] = {k: spend[k] for k in keys}
    save_state(table, state)
    return float(state["spend"][key])


def hook_text(body: str) -> str:
    return body.strip().split("\n", 1)[0].strip()


def body_hash(body: str) -> str:
    folded = " ".join(body.lower().split())
    return hashlib.sha256(folded.encode("utf-8")).hexdigest()[:16]


def forbidden_terms(settings: dict[str, Any]) -> list[str]:
    extra = _words(settings.get("forbiddenWords"))
    out: list[str] = []
    for term in (*BUILTIN_FORBIDDEN, *extra):
        if term not in out:
            out.append(term)
    return out


def guardrails(body: str, comment: str, hashtags: list[str], settings: dict[str, Any]) -> list[dict[str, str]]:
    """Deterministic checks. ``error`` blocks approve; ``warn`` does not."""
    findings: list[dict[str, str]] = []
    text = body or ""
    hook = hook_text(text)
    if not hook:
        findings.append({"code": "hook", "severity": "error", "detail": "The first line is empty."})
    elif len(hook) > HOOK_MAX:
        findings.append(
            {
                "code": "hook",
                "severity": "error",
                "detail": f"The first line is {len(hook)} characters. Keep it within {HOOK_MAX}.",
            }
        )
    if len(text) > BODY_MAX:
        findings.append(
            {
                "code": "too_long",
                "severity": "error",
                "detail": f"The post is {len(text)} characters. The limit is {BODY_MAX}.",
            }
        )
    if len(comment or "") > COMMENT_MAX:
        findings.append(
            {
                "code": "comment",
                "severity": "error",
                "detail": f"The first comment is over {COMMENT_MAX} characters.",
            }
        )
    haystack = f"{text}\n{comment or ''}".lower()
    for term in forbidden_terms(settings):
        if term and term in haystack:
            findings.append(
                {
                    "code": "forbidden_word",
                    "severity": "error",
                    "detail": f"Remove “{term}”.",
                }
            )
    if not settings.get("allowProductMentions"):
        for term in PRODUCT_PHRASES:
            if term in haystack:
                findings.append(
                    {
                        "code": "product_mention",
                        "severity": "error",
                        "detail": f"Remove the product mention “{term}”.",
                    }
                )
    tags = [str(tag).lstrip("#").strip() for tag in hashtags if str(tag).strip()]
    inline = _HASH.findall(text)
    cap = int(settings.get("hashtagCap") or 0)
    if len(set(tags + inline)) > cap:
        findings.append(
            {
                "code": "hashtags",
                "severity": "error",
                "detail": f"Use at most {cap} hashtags.",
            }
        )
    if _EMAIL.search(text) or _EMAIL.search(comment or ""):
        findings.append({"code": "email", "severity": "error", "detail": "Remove the email address."})
    if _PHONE.search(text) or _PHONE.search(comment or ""):
        findings.append({"code": "phone", "severity": "error", "detail": "Remove the phone number."})
    if _URL.search(text):
        severity = "error" if settings.get("linksInFirstComment") else "warn"
        findings.append(
            {
                "code": "url_in_body",
                "severity": severity,
                "detail": "A link in the post body is easy to miss. Put it in the first comment.",
            }
        )
    return findings


def errors_block(findings: list[dict[str, str]]) -> bool:
    return any(row.get("severity") == "error" for row in findings)


def _as_hkt(now: datetime | None = None) -> datetime:
    current = now or datetime.now(HKT)
    if current.tzinfo is None:
        current = current.replace(tzinfo=HKT)
    return current.astimezone(HKT)


def slot_on(day: datetime, settings: dict[str, Any]) -> datetime:
    local = day.astimezone(HKT)
    return local.replace(
        hour=int(settings["slotHour"]),
        minute=int(settings["slotMinute"]),
        second=0,
        microsecond=0,
    )


def _iso_week(moment: datetime) -> tuple[int, int]:
    iso = moment.astimezone(HKT).isocalendar()
    return int(iso.year), int(iso.week)


def next_slots(
    settings: dict[str, Any],
    *,
    now: datetime | None = None,
    count: int = 12,
    taken: set[str] | None = None,
) -> list[str]:
    """Upcoming slot instants as UTC timestamps, respecting postsPerWeek."""
    taken = taken or set()
    weekdays = set(_weekdays(settings.get("weekdays")))
    per_week = int(settings.get("postsPerWeek") or 1)
    start = _as_hkt(now)
    used_weeks: dict[tuple[int, int], int] = {}
    for stamp in taken:
        parsed = _parse_slot(stamp)
        if parsed is None:
            continue
        key = _iso_week(parsed)
        used_weeks[key] = used_weeks.get(key, 0) + 1
    out: list[str] = []
    for offset in range(0, 120):
        day = (start + timedelta(days=offset)).replace(hour=12, minute=0, second=0, microsecond=0)
        if day.weekday() not in weekdays:
            continue
        slot = slot_on(day, settings)
        if slot <= start:
            continue
        key = _iso_week(slot)
        if used_weeks.get(key, 0) >= per_week:
            continue
        stamp = _format_slot(slot)
        if stamp in taken:
            continue
        used_weeks[key] = used_weeks.get(key, 0) + 1
        out.append(stamp)
        if len(out) >= count:
            break
    return out


def _format_slot(moment: datetime) -> str:
    from timeutil import format_iso_millis

    return format_iso_millis(moment)


def _parse_slot(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=HKT)
    return parsed


def taken_slots(table: Any) -> set[str]:
    taken: set[str] = set()
    for status in ("approved", "published"):
        for row in list_posts(table, status=status):
            slot = str(row.get("slotAt") or "")
            if slot:
                taken.add(slot)
    return taken


def assign_slot(table: Any, settings: dict[str, Any], *, now: datetime | None = None) -> str:
    slots = next_slots(settings, now=now, count=1, taken=taken_slots(table))
    if not slots:
        raise LinkedInError("No open slot in the next few months.")
    return slots[0]


def _post_item(doc: dict[str, Any]) -> dict[str, Any]:
    post_id = str(doc["postId"])
    status = str(doc.get("status") or "drafted")
    slot = str(doc.get("slotAt") or "")
    return {
        "pk": f"LINKEDIN#post#{post_id}",
        "sk": "META",
        "gsi1pk": f"LINKEDIN#posts#{status}",
        "gsi1sk": f"{slot or '9'}#{post_id}",
        **doc,
    }


def put_post(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    doc = {**doc, "updatedAt": board_store.now_iso()}
    _put(table, _post_item(doc))
    return doc


def get_post(table: Any, post_id: str) -> dict[str, Any] | None:
    return _get(table, f"LINKEDIN#post#{post_id}")


def list_posts(table: Any, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    statuses = (status,) if status else tuple(s for s in STATUSES if s != "archived")
    rows: list[dict[str, Any]] = []
    for name in statuses:
        rows.extend(_query(table, f"LINKEDIN#posts#{name}", limit=limit))
    rows.sort(key=lambda doc: (str(doc.get("slotAt") or "9"), str(doc.get("createdAt") or "")))
    return rows[:limit]


def recent_hashes(table: Any) -> set[str]:
    cutoff = _as_hkt() - timedelta(days=90)
    found: set[str] = set()
    for row in list_posts(table, limit=400):
        if str(row.get("status") or "") == "archived":
            continue
        created = _parse_slot(str(row.get("createdAt") or ""))
        if created is not None and created < cutoff:
            continue
        digest = str(row.get("bodyHash") or "")
        if digest:
            found.add(digest)
    return found


def recent_hooks(table: Any, *, limit: int = 12) -> list[str]:
    rows = [row for row in list_posts(table, limit=80) if str(row.get("status") or "") != "archived"]
    rows.sort(key=lambda doc: str(doc.get("createdAt") or ""), reverse=True)
    hooks: list[str] = []
    for row in rows:
        hook = hook_text(str(row.get("body") or ""))
        if hook:
            hooks.append(hook[:180])
        if len(hooks) >= limit:
            break
    return hooks


def _clean_hashtags(value: Any, cap: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise LinkedInError("hashtags must be a list")
    out: list[str] = []
    for item in value:
        tag = str(item).strip().lstrip("#")
        if not tag:
            continue
        if not re.fullmatch(r"[\w]{1,40}", tag):
            raise LinkedInError(f"hashtag “{tag[:40]}” is invalid")
        if tag not in out:
            out.append(tag)
    if len(out) > max(cap, 0):
        raise LinkedInError(f"Use at most {cap} hashtags.")
    return out


def _apply_copy(doc: dict[str, Any], body: str, comment: str, hashtags: list[str], settings: dict[str, Any]) -> None:
    doc["body"] = body
    doc["firstComment"] = comment
    doc["hashtags"] = hashtags
    doc["bodyHash"] = body_hash(body)
    doc["guardrails"] = guardrails(body, comment, hashtags, settings)


def create_post(
    table: Any,
    body: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
    generation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = settings or load_settings(table)
    text = str(body.get("body") or "").strip()
    if not text:
        raise LinkedInError("body is required")
    if len(text) > BODY_MAX:
        raise LinkedInError(f"body is over {BODY_MAX} characters")
    comment = str(body.get("firstComment") or "").strip()
    if len(comment) > COMMENT_MAX:
        raise LinkedInError(f"firstComment is over {COMMENT_MAX} characters")
    pillar = str(body.get("pillar") or settings["pillars"][0])
    if pillar not in pillar_ids():
        raise LinkedInError("unknown pillar")
    tags = _clean_hashtags(body.get("hashtags") or [], int(settings["hashtagCap"]))
    digest = body_hash(text)
    if digest in recent_hashes(table):
        raise LinkedInError("A similar post already exists.")
    now = board_store.now_iso()
    doc: dict[str, Any] = {
        "postId": _new_id("li_"),
        "status": "drafted",
        "channel": "profile",
        "pillar": pillar,
        "ideaId": str(body.get("ideaId") or ""),
        "lang": "en",
        "slotAt": "",
        "createdAt": now,
    }
    _apply_copy(doc, text, comment, tags, settings)
    if generation:
        doc["generation"] = generation
    if doc["ideaId"]:
        mark_idea_used(table, doc["ideaId"], doc["postId"])
    return put_post(table, doc)


def update_post(table: Any, post_id: str, body: dict[str, Any]) -> dict[str, Any]:
    doc = get_post(table, post_id)
    if not doc:
        raise LinkedInError("post not found")
    if str(doc.get("status") or "") in ("published", "archived"):
        raise LinkedInError("That post can no longer be edited.")
    settings = load_settings(table)
    text = str(body.get("body", doc.get("body") or "")).strip()
    comment = str(body.get("firstComment", doc.get("firstComment") or "")).strip()
    if "hashtags" in body:
        tags = _clean_hashtags(body.get("hashtags"), int(settings["hashtagCap"]))
    else:
        tags = list(doc.get("hashtags") or [])
    pillar = str(body.get("pillar", doc.get("pillar") or ""))
    if pillar not in pillar_ids():
        raise LinkedInError("unknown pillar")
    changed_copy = (
        text != str(doc.get("body") or "")
        or comment != str(doc.get("firstComment") or "")
        or tags != list(doc.get("hashtags") or [])
    )
    doc["pillar"] = pillar
    _apply_copy(doc, text, comment, tags, settings)
    if changed_copy and str(doc.get("status") or "") == "approved":
        doc["status"] = "drafted"
        doc["approvedAt"] = ""
        doc["slotAt"] = ""
    if "slotAt" in body and str(doc.get("status") or "") == "approved":
        slot = str(body.get("slotAt") or "").strip()
        if slot and _parse_slot(slot) is None:
            raise LinkedInError("slotAt is invalid")
        doc["slotAt"] = slot
    return put_post(table, doc)


def approve_post(table: Any, post_id: str, user_sub: str, *, now: datetime | None = None) -> dict[str, Any]:
    doc = get_post(table, post_id)
    if not doc:
        raise LinkedInError("post not found")
    if str(doc.get("status") or "") == "published":
        raise LinkedInError("That post is already published.")
    settings = load_settings(table)
    findings = guardrails(
        str(doc.get("body") or ""),
        str(doc.get("firstComment") or ""),
        list(doc.get("hashtags") or []),
        settings,
    )
    doc["guardrails"] = findings
    if errors_block(findings):
        put_post(table, doc)
        raise LinkedInError("Resolve the post checks before approving.")
    if not str(doc.get("slotAt") or ""):
        doc["slotAt"] = assign_slot(table, settings, now=now)
    doc["status"] = "approved"
    doc["approvedAt"] = board_store.now_iso()
    doc["approvedBy"] = user_sub or ""
    return put_post(table, doc)


def unapprove_post(table: Any, post_id: str) -> dict[str, Any]:
    doc = get_post(table, post_id)
    if not doc:
        raise LinkedInError("post not found")
    if str(doc.get("status") or "") != "approved":
        raise LinkedInError("Only an approved post can be unapproved.")
    doc["status"] = "drafted"
    doc["approvedAt"] = ""
    doc["slotAt"] = ""
    return put_post(table, doc)


def archive_post(table: Any, post_id: str) -> dict[str, Any]:
    doc = get_post(table, post_id)
    if not doc:
        raise LinkedInError("post not found")
    doc["status"] = "archived"
    return put_post(table, doc)


def mark_posted(table: Any, post_id: str, url: str) -> dict[str, Any]:
    doc = get_post(table, post_id)
    if not doc:
        raise LinkedInError("post not found")
    if str(doc.get("status") or "") == "archived":
        raise LinkedInError("That post is archived.")
    link = str(url or "").strip()
    if not link.startswith("https://www.linkedin.com/") and not link.startswith("https://linkedin.com/"):
        raise LinkedInError("Paste the linkedin.com URL of the live post.")
    now = board_store.now_iso()
    doc["status"] = "published"
    doc["manual"] = {"postedAt": now, "url": link}
    doc["platform"] = {"url": link, "publishedAt": now}
    return put_post(table, doc)


def public_post(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "postId": doc.get("postId"),
        "status": doc.get("status"),
        "channel": doc.get("channel") or "profile",
        "pillar": doc.get("pillar"),
        "ideaId": doc.get("ideaId") or "",
        "body": doc.get("body") or "",
        "firstComment": doc.get("firstComment") or "",
        "hashtags": list(doc.get("hashtags") or []),
        "lang": doc.get("lang") or "en",
        "slotAt": doc.get("slotAt") or "",
        "guardrails": list(doc.get("guardrails") or []),
        "generation": doc.get("generation") or None,
        "platform": doc.get("platform") or None,
        "manual": doc.get("manual") or None,
        "createdAt": doc.get("createdAt"),
        "updatedAt": doc.get("updatedAt"),
        "approvedAt": doc.get("approvedAt") or "",
    }


def put_idea(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    idea_id = str(doc["ideaId"])
    _put(
        table,
        {
            "pk": f"LINKEDIN#idea#{idea_id}",
            "sk": "META",
            "gsi1pk": "LINKEDIN#ideas",
            "gsi1sk": f"{doc.get('createdAt') or ''}#{idea_id}",
            **doc,
        },
    )
    return doc


def list_ideas(table: Any) -> list[dict[str, Any]]:
    rows = _query(table, "LINKEDIN#ideas", limit=200)
    rows.sort(key=lambda doc: str(doc.get("createdAt") or ""), reverse=True)
    return rows


def get_idea(table: Any, idea_id: str) -> dict[str, Any] | None:
    return _get(table, f"LINKEDIN#idea#{idea_id}")


def create_idea(table: Any, text: str, pillar: str = "") -> dict[str, Any]:
    note = str(text or "").strip()
    if not note:
        raise LinkedInError("text is required")
    if len(note) > 500:
        raise LinkedInError("text is too long")
    if pillar and pillar not in pillar_ids():
        raise LinkedInError("unknown pillar")
    doc = {
        "ideaId": _new_id("idea_"),
        "text": note,
        "pillar": pillar,
        "status": "new",
        "usedBy": "",
        "createdAt": board_store.now_iso(),
    }
    return put_idea(table, doc)


def delete_idea(table: Any, idea_id: str) -> None:
    table.delete_item(Key={"pk": f"LINKEDIN#idea#{idea_id}", "sk": "META"})


def mark_idea_used(table: Any, idea_id: str, post_id: str) -> None:
    doc = get_idea(table, idea_id)
    if not doc:
        return
    doc["status"] = "used"
    doc["usedBy"] = post_id
    put_idea(table, doc)


def unused_ideas(table: Any) -> list[dict[str, Any]]:
    return [row for row in list_ideas(table) if str(row.get("status") or "") == "new"]


def put_job(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    import time

    job_id = str(doc["jobId"])
    _put(
        table,
        {
            "pk": f"LINKEDIN#job#{job_id}",
            "sk": "META",
            "expiresAt": int(time.time()) + 7 * 86400,
            **doc,
        },
    )
    return doc


def get_job(table: Any, job_id: str) -> dict[str, Any] | None:
    return _get(table, f"LINKEDIN#job#{job_id}")


def new_job(table: Any, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    doc = {
        "jobId": _new_id("job_"),
        "kind": kind,
        "status": "queued",
        "payload": payload,
        "postIds": [],
        "error": "",
        "createdAt": board_store.now_iso(),
    }
    return put_job(table, doc)


def counts(table: Any) -> dict[str, int]:
    posts = list_posts(table, limit=400)
    return {
        "drafted": sum(1 for row in posts if row.get("status") == "drafted"),
        "approved": sum(1 for row in posts if row.get("status") == "approved"),
        "published": sum(1 for row in posts if row.get("status") == "published"),
        "ideas": sum(1 for row in list_ideas(table) if row.get("status") == "new"),
    }


def overview(table: Any) -> dict[str, Any]:
    settings = load_settings(table)
    return {
        "enabled": feature_enabled(),
        "publishEnabled": publish_enabled(),
        "settings": settings,
        "pillars": [{"id": row["id"], "label": row["label"]} for row in PILLARS],
        "connection": {"status": "not_connected", "channel": "profile"},
        "counts": counts(table),
        "spendUsdMonth": round(month_spend(table), 4),
        "nextSlots": next_slots(settings, count=8, taken=taken_slots(table)),
        "builtinForbidden": list(BUILTIN_FORBIDDEN),
    }


def due_approved(table: Any, *, now_iso: str | None = None) -> list[dict[str, Any]]:
    now = now_iso or board_store.now_iso()
    due: list[dict[str, Any]] = []
    for row in list_posts(table, status="approved"):
        slot = str(row.get("slotAt") or "")
        if slot and slot <= now and not row.get("dueNotifiedAt"):
            due.append(row)
    return due


def stamp_due_notified(table: Any, post_id: str) -> None:
    doc = get_post(table, post_id)
    if not doc:
        return
    doc["dueNotifiedAt"] = board_store.now_iso()
    put_post(table, doc)
