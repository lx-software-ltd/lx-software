"""LX Software LinkedIn drafts, ideas, and settings.

Rows live in the records table under ``LINKEDIN#`` and stay out of ``/records``.
Posts are a personal presence queue: the default voice does not mention LX
Software or sibling products. This module stores drafts, assigns 08:30 HKT
slots, records a hand post, and keeps the LinkedIn connection.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import board_store
from botocore.exceptions import ClientError
from ddb_convert import _from_ddb_nested, _to_ddb_nested

HKT = ZoneInfo("Asia/Hong_Kong")

PK_PREFIX = "LINKEDIN#"
BODY_MAX = 3000
COMMENT_MAX = 1250
PUBLISH_GRACE = timedelta(hours=3)
PUBLISH_ATTEMPTS = 3
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
_MODEL = re.compile(r"[A-Za-z0-9_./:-]+")
MODEL_MAX = 120
_PHONE_PLUS = re.compile(r"\+\d{8,15}")
_PHONE_GROUP = re.compile(r"(?:\d[\s.\-()]*){8,}")
_URL = re.compile(r"(https?://|www\.)\S+", re.I)
# A hashtag starts with a letter. "#42" is a number, not a tag.
_HASH = re.compile(r"#([A-Za-z][\w]{0,39})")


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


# The first default restated the safety rules and was not a voice. A stored
# copy is replaced by the recommended voice on load.
_RETIRED_DEFAULT_VOICE = (
    "Senior architect writing in the first person. One lesson per post. "
    "No company name, no employer, no offer of availability."
)

# Shown in Settings as "Use recommended voice" and used until the owner writes
# their own. Kept under the 1000-character voice limit. Derived from a post the
# owner wrote: a plain opening line, a story told in order, honest hedging, an
# answered objection at the end.
RECOMMENDED_VOICE = (
    "First person singular, always I, never we. Conversational, as if I were telling a "
    "former colleague over lunch what I have been building. No hook: the first line is "
    "plain and specific to this story, not a question, not a claim. Tell it in the order it "
    "happened: what I noticed, what I decided, what I built, where it broke, where it "
    "stands now. Name the real constraint (a full-time job, nights and weekends, a month of "
    "evenings) and real figures when I have them. Plain dashes for a short list. One-line "
    "paragraphs are fine. Dry, understated, a little self-deprecating; an aside now and "
    "then. Admit what is unfinished and what might fail. No sensationalism, no wow, no "
    "lesson headline, no moral, no call to action. Each post has its own shape: a "
    "different way in and a different way out from the last one, no stock opening line, no "
    "stock closing line, no catchphrase carried from post to post. Usually 200 to 450 words."
)

STYLE_EXAMPLE_MAX = 3000

# Pictures. Seedream is the default; Qwen-Image is the documented alternative.
# The style describes a magazine gag cartoon and quotes no scene, so the model
# does not redraw the same panel for every post.
DEFAULT_IMAGE_MODEL = "bytedance-seed/seedream-4.5"
IMAGE_MODEL_ALTERNATIVE = "qwen/qwen-image-3"
IMAGE_FORMATS = ("square", "portrait", "wide")
IMAGE_STYLE_MAX = 600
IMAGE_CHARACTER_MAX = 400
IMAGE_CAPTION_MAX = 140
IMAGE_SCENE_MAX = 400
IMAGE_EXPRESSION_MAX = 80
IMAGE_PENDING_SECONDS = 600
# Two 25 s model attempts plus the Event invoke; past this the worker is gone.
BRIEF_PENDING_SECONDS = 120
# A character draw that is still queued or running after this is the Lambda
# timing out (300s) without writing the job row.
CHARACTER_JOB_STALE_SECONDS = 360
CANDIDATE_IDS = frozenset({"c1", "c2", "c3", "c4"})
IMAGE_BYTE_MAX = 1_500_000
RECOMMENDED_IMAGE_STYLE = (
    "Single-panel magazine gag cartoon, light and a little silly, never serious. Black ink "
    "line art on white paper, dense cross-hatching for shadow, no grey wash, no colour. "
    "Faces are caricatures, not portraits: simplified features, bold outlines, flat white "
    "skin with hatching only in shadow, a slightly oversized head. Exaggerated body "
    "language, one man mid-action in a detailed room. No lettering and no logos. One "
    "two-word label is allowed when the scene needs it, such as a door sign or a folder "
    "tab; screens show scribbled nonsense symbols, never real words."
)
DEFAULT_IMAGE_CHARACTER = (
    "A man in his thirties with short dark hair, side-parted, clean-shaven, a round face, "
    "wearing a light striped button-down shirt with an open collar."
)
FALLBACK_IMAGE_CAPTION = "This took longer than I expected."
FALLBACK_IMAGE_EXPRESSION = "baffled, scratching his head"

# A post the owner wrote, shown to the model for its register only. Its
# structure, opening, closing and phrases are not to be reused; the draft loop
# checks new posts against it and against each other.
STYLE_EXAMPLE = """Here is about building my AI exec board and its AI staff.

Some time ago, I had lunch with a former colleague, and we found ourselves wondering why there wasn't a single place to find activities for children in Hong Kong, sorted by location, price, and other useful criteria. In reality, these lists already exist, but they're rarely curated and often out of date.

A couple of months ago, I decided to build a solution myself. Backend, frontend, admin portal... the whole thing.

Then I hit a major issue: when was I actually going to find the time to run it?

I've got a full-time job, and I'd already spent nights and weekends building the platform. Now I needed to:

- Manage the finances
- Build partnerships
- Add new features
- Run marketing campaigns

...and all the other great things they teach you in an MBA. The problem is, they all take time. Maybe I needed to focus on just a few priorities first.

Then I had another thought: why not build an executive board made up of AI personas that could help me decide what to focus on? Full CEO, CIO, CMO, CFO etc.

So I built it.

The problem was that the board kept generating more ideas and more tasks, and I still couldn't keep up.

Then came the next idea.

If I could build an executive board, why couldn't I build the staff that would actually execute what the board recommended?

And ta-da! Well, that "ta-da" is still a work in progress after a month of development.

Today, I have an AI executive board that generates tasks, prioritizes them, and assigns them to a team of AI staff members that execute them. A new insight from a competitor? The system analyzes it, generates ideas (such as a new website feature), develops a solution, tests it, and delivers it. All automatically. The machine is still far from perfect, but on a good day, it runs without supervision for 15-20 hours.

I still keep human oversight over certain activities, particularly customer and partner communications, but for the first time, I'm genuinely starting to feel like launch day is within reach.

For the techies out there, all of the code is open source and available on my GitHub.

What started as a simple idea to help parents find activities for their children has evolved into something much bigger: an experiment in building a business that can largely run itself. Whether it's a brilliant idea or a terrible one remains to be seen, but it's certainly been one of the most interesting projects I've ever worked on.

I know what you're thinking - AI is going to mess up some decisions and deliver something poor to my customers. Yes, maybe, or maybe not. I'm happy to gamble, and put as many guardrails as possible. Eventually done is better than perfect."""


def default_settings() -> dict[str, Any]:
    return {
        "postsPerWeek": POSTS_PER_WEEK_DEFAULT,
        "weekdays": list(WEEKDAYS_DEFAULT),
        "slotHour": SLOT_HOUR_DEFAULT,
        "slotMinute": SLOT_MINUTE_DEFAULT,
        "draftsPerGeneration": DRAFTS_PER_GENERATION_DEFAULT,
        # Blank uses the tone defaults in the draft prompt. A stored note overrides them.
        "voiceNotes": RECOMMENDED_VOICE,
        # Blank sends no example. The owner can paste a newer post here.
        "styleExample": STYLE_EXAMPLE,
        "forbiddenWords": [],
        "hashtagCap": HASHTAG_CAP_DEFAULT,
        "linksInFirstComment": False,
        "allowProductMentions": False,
        "maxUsdPerMonth": MAX_USD_DEFAULT,
        "notifyEmail": "",
        "model": "",
        "pillars": [row["id"] for row in PILLARS],
        "imagesEnabled": True,
        "imageModel": DEFAULT_IMAGE_MODEL,
        "imageFormat": "square",
        "imageStyle": RECOMMENDED_IMAGE_STYLE,
        "imageCharacter": DEFAULT_IMAGE_CHARACTER,
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


def _get(table: Any, pk: str, sk: str = "META", *, consistent: bool = False) -> dict[str, Any] | None:
    kwargs: dict[str, Any] = {"Key": {"pk": pk, "sk": sk}}
    if consistent:
        kwargs["ConsistentRead"] = True
    res = table.get_item(**kwargs)
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


def _state_key(sk: str) -> dict[str, str]:
    return {"pk": "LINKEDIN#state", "sk": sk}


def _load_sk(table: Any, sk: str) -> dict[str, Any]:
    return _get(table, "LINKEDIN#state", sk) or {}


def load_settings(table: Any) -> dict[str, Any]:
    stored = _load_sk(table, "SETTINGS").get("settings")
    merged = default_settings()
    if isinstance(stored, dict):
        merged.update({k: v for k, v in stored.items() if k in merged})
    merged["weekdays"] = _weekdays(merged.get("weekdays"))
    merged["pillars"] = _pillars(merged.get("pillars"))
    merged["forbiddenWords"] = _words(merged.get("forbiddenWords"))
    if str(merged.get("voiceNotes") or "").strip() == _RETIRED_DEFAULT_VOICE:
        merged["voiceNotes"] = RECOMMENDED_VOICE
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


def validate_settings(body: dict[str, Any], *, stored: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge a settings write onto defaults. Raises LinkedInError.

    ``imagesEnabled`` is kept from ``stored`` when the body omits it, so a
    partial write does not turn pictures back on.
    """
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
    example = str(body.get("styleExample", current["styleExample"]) or "").strip()
    if len(example) > STYLE_EXAMPLE_MAX:
        raise LinkedInError(f"styleExample is over {STYLE_EXAMPLE_MAX} characters")
    notify = str(body.get("notifyEmail", current["notifyEmail"]) or "").strip()
    if notify and (notify.count("@") != 1 or notify.startswith("@") or notify.endswith("@")):
        raise LinkedInError("notifyEmail is invalid")
    model = str(body.get("model", current["model"]) or "").strip()
    if model:
        if len(model) > MODEL_MAX:
            raise LinkedInError("model is too long")
        if not _MODEL.fullmatch(model):
            raise LinkedInError("model is invalid")
    image_model = str(body.get("imageModel", current["imageModel"]) or "").strip()
    if image_model:
        if len(image_model) > MODEL_MAX:
            raise LinkedInError("imageModel is too long")
        if not _MODEL.fullmatch(image_model):
            raise LinkedInError("imageModel is invalid")
    image_format = str(body.get("imageFormat", current["imageFormat"]) or "").strip()
    if image_format not in IMAGE_FORMATS:
        raise LinkedInError("imageFormat is invalid")
    image_style = str(body.get("imageStyle", current["imageStyle"]) or "").strip()
    if len(image_style) > IMAGE_STYLE_MAX:
        raise LinkedInError(f"imageStyle is over {IMAGE_STYLE_MAX} characters")
    image_character = str(body.get("imageCharacter", current["imageCharacter"]) or "").strip()
    if len(image_character) > IMAGE_CHARACTER_MAX:
        raise LinkedInError(f"imageCharacter is over {IMAGE_CHARACTER_MAX} characters")
    pillars = _pillars(body.get("pillars", current["pillars"]))
    if "imagesEnabled" in body:
        images_enabled = bool(body.get("imagesEnabled"))
    elif isinstance(stored, dict) and "imagesEnabled" in stored:
        images_enabled = bool(stored.get("imagesEnabled"))
    else:
        images_enabled = bool(current["imagesEnabled"])
    return {
        "postsPerWeek": posts,
        "weekdays": weekdays,
        "slotHour": hour,
        "slotMinute": minute,
        "draftsPerGeneration": drafts,
        "voiceNotes": voice,
        "styleExample": example,
        "forbiddenWords": _words(body.get("forbiddenWords", current["forbiddenWords"])),
        "hashtagCap": cap,
        "linksInFirstComment": bool(body.get("linksInFirstComment", False)),
        "allowProductMentions": bool(body.get("allowProductMentions", False)),
        "maxUsdPerMonth": round(budget, 2),
        "notifyEmail": notify,
        "model": model,
        "pillars": pillars,
        "imagesEnabled": images_enabled,
        "imageModel": image_model or DEFAULT_IMAGE_MODEL,
        "imageFormat": image_format,
        "imageStyle": image_style or RECOMMENDED_IMAGE_STYLE,
        "imageCharacter": image_character or DEFAULT_IMAGE_CHARACTER,
    }


def save_settings(table: Any, body: dict[str, Any]) -> dict[str, Any]:
    settings = validate_settings(body, stored=load_settings(table))
    _put(
        table,
        {
            **_state_key("SETTINGS"),
            "settings": settings,
            "updatedAt": board_store.now_iso(),
        },
    )
    return settings


def month_key(now: datetime | None = None) -> str:
    local = (now or datetime.now(HKT)).astimezone(HKT)
    return f"{local.year:04d}-{local.month:02d}"


def month_spend(table: Any, now: datetime | None = None) -> float:
    spend = _load_sk(table, "SPEND").get("spend")
    if not isinstance(spend, dict):
        return 0.0
    try:
        return float(spend.get(month_key(now)) or 0)
    except (TypeError, ValueError):
        return 0.0


class _SpendConflict(Exception):
    """Another writer updated the monthly spend row between read and write."""


def _spend_conflict(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    return str(response.get("Error", {}).get("Code") or "") == "ConditionalCheckFailedException"


def _put_spend_cas(table: Any, previous: dict[str, Any], spend_map: dict[str, Any]) -> None:
    """Replace the spend row only when ``spendToken`` is unchanged."""
    item = _to_ddb_nested(
        {
            **_state_key("SPEND"),
            "spend": spend_map,
            "spendToken": uuid.uuid4().hex,
            "updatedAt": board_store.now_iso(),
        }
    )
    if not previous:
        condition = "attribute_not_exists(pk)"
        values = None
    elif "spendToken" not in previous:
        condition = "attribute_not_exists(spendToken)"
        values = None
    else:
        condition = "spendToken = :prev"
        values = {":prev": previous.get("spendToken")}
    kwargs: dict[str, Any] = {"Item": item, "ConditionExpression": condition}
    if values is not None:
        kwargs["ExpressionAttributeValues"] = values
    try:
        table.put_item(**kwargs)
    except ClientError as exc:
        if _spend_conflict(exc):
            raise _SpendConflict from exc
        raise


def _trim_spend(spend: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(str(key) for key in spend)[-13:]
    return {key: spend[key] for key in keys}


def adjust_spend(table: Any, usd: float, now: datetime | None = None) -> float:
    """Add ``usd`` to this month. A negative amount releases a reservation and never goes below zero."""
    key = month_key(now)
    updated = month_spend(table, now)
    for _attempt in range(5):
        doc = _load_sk(table, "SPEND")
        spend = dict(doc.get("spend") or {})
        try:
            current = float(spend.get(key) or 0)
        except (TypeError, ValueError):
            current = 0.0
        updated = round(max(0.0, current + usd), 6)
        spend[key] = updated
        try:
            _put_spend_cas(table, doc, _trim_spend(spend))
            return updated
        except _SpendConflict:
            continue
    doc = _load_sk(table, "SPEND")
    spend = dict(doc.get("spend") or {})
    try:
        current = float(spend.get(key) or 0)
    except (TypeError, ValueError):
        current = 0.0
    updated = round(max(0.0, current + usd), 6)
    spend[key] = updated
    trimmed = _trim_spend(spend)
    _put(table, {**_state_key("SPEND"), "spend": trimmed, "updatedAt": board_store.now_iso()})
    return float(updated)


def try_reserve_spend(table: Any, usd: float, cap: float, now: datetime | None = None) -> bool:
    """Reserve ``usd`` against ``cap``. False when this month would go over, or the write keeps losing."""
    if usd <= 0:
        return True
    key = month_key(now)
    for _attempt in range(5):
        doc = _load_sk(table, "SPEND")
        spend = dict(doc.get("spend") or {})
        try:
            current = float(spend.get(key) or 0)
        except (TypeError, ValueError):
            current = 0.0
        if current + usd > cap + 1e-9:
            return False
        spend[key] = round(current + usd, 6)
        try:
            _put_spend_cas(table, doc, _trim_spend(spend))
            return True
        except _SpendConflict:
            continue
    return False


def add_spend(table: Any, usd: float, now: datetime | None = None) -> float:
    if usd <= 0:
        return month_spend(table, now)
    return adjust_spend(table, usd, now)


def load_plan_date(table: Any) -> str:
    return str(_load_sk(table, "PLAN").get("lastPlanDate") or "")


def save_plan_date(table: Any, day: str) -> None:
    _put(
        table,
        {
            **_state_key("PLAN"),
            "lastPlanDate": day,
            "updatedAt": board_store.now_iso(),
        },
    )


def hook_text(body: str) -> str:
    return body.strip().split("\n", 1)[0].strip()


def closing_text(body: str) -> str:
    """Last non-empty line, so a draft can be told not to end the same way twice."""
    for line in reversed(body.strip().split("\n")):
        if line.strip():
            return line.strip()
    return ""


def body_hash(body: str) -> str:
    folded = " ".join(body.lower().split())
    return hashlib.sha256(folded.encode("utf-8")).hexdigest()[:16]


def contains_term(haystack: str, term: str) -> bool:
    """Whole word or phrase. ``hire me`` does not match ``hire mentors``."""
    if not term:
        return False
    return re.search(r"(?<![\w])" + re.escape(term) + r"(?![\w])", haystack) is not None


def has_phone(text: str) -> bool:
    """A plus-prefixed number, or digits with a separator between them.

    A bare integer is not a phone, even when a space or period follows it.
    """
    if _PHONE_PLUS.search(text or ""):
        return True
    for match in _PHONE_GROUP.finditer(text or ""):
        chunk = match.group(0)
        digits = re.sub(r"\D", "", chunk)
        if 8 <= len(digits) <= 15 and re.search(r"\d[\s.\-()]+\d", chunk):
            return True
    return False


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
    elif text.strip():
        import linkedin_api

        try:
            linkedin_api.commentary(text, [str(tag) for tag in hashtags])
        except linkedin_api.LinkedInApiError as exc:
            findings.append({"code": "too_long", "severity": "error", "detail": str(exc)})
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
        if contains_term(haystack, term):
            findings.append(
                {
                    "code": "forbidden_word",
                    "severity": "error",
                    "detail": f"Remove “{term}”.",
                }
            )
    if not settings.get("allowProductMentions"):
        for term in PRODUCT_PHRASES:
            if contains_term(haystack, term):
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
    if has_phone(text) or has_phone(comment or ""):
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


def normalize_slot(value: str) -> str:
    """Store every slot as UTC millis with a Z suffix so string compare matches ``now_iso``."""
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = _parse_slot(text)
    if parsed is None:
        raise LinkedInError("slotAt is invalid")
    return _format_slot(parsed)


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


def get_post(table: Any, post_id: str, *, consistent: bool = False) -> dict[str, Any] | None:
    return _get(table, f"LINKEDIN#post#{post_id}", consistent=consistent)


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


def recent_bodies(table: Any, *, limit: int = 12) -> list[str]:
    """Newest post bodies first, archived rows excluded."""
    rows = [row for row in list_posts(table, limit=80) if str(row.get("status") or "") != "archived"]
    rows.sort(key=lambda doc: str(doc.get("createdAt") or ""), reverse=True)
    bodies: list[str] = []
    for row in rows:
        body = str(row.get("body") or "").strip()
        if body:
            bodies.append(body)
        if len(bodies) >= limit:
            break
    return bodies


def recent_hooks(table: Any, *, limit: int = 12) -> list[str]:
    return [hook_text(body)[:180] for body in recent_bodies(table, limit=limit)]


def recent_captions(table: Any, *, limit: int = 12) -> list[str]:
    """Spoken lines under recent pictures, newest first."""
    return _recent_image_text(table, "caption", limit=limit)


def recent_scenes(table: Any, *, limit: int = 12) -> list[str]:
    """Picture scenes on recent posts, newest first."""
    return _recent_image_text(table, "scene", limit=limit)


def _recent_image_text(table: Any, field: str, *, limit: int) -> list[str]:
    rows = [row for row in list_posts(table, limit=80) if str(row.get("status") or "") != "archived"]
    rows.sort(key=lambda doc: str(doc.get("createdAt") or ""), reverse=True)
    found: list[str] = []
    for row in rows:
        image = row.get("image") if isinstance(row.get("image"), dict) else {}
        text = str(image.get(field) or "").strip()
        if text and text not in found:
            found.append(text)
        if len(found) >= limit:
            break
    return found


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
        "seedId": str(body.get("seedId") or ""),
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
        doc["slotAt"] = normalize_slot(str(body.get("slotAt") or ""))
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
    image = doc.get("image") if isinstance(doc.get("image"), dict) else None
    return {
        "postId": doc.get("postId"),
        "status": doc.get("status"),
        "channel": doc.get("channel") or "profile",
        "pillar": doc.get("pillar"),
        "ideaId": doc.get("ideaId") or "",
        "seedId": doc.get("seedId") or "",
        "body": doc.get("body") or "",
        "firstComment": doc.get("firstComment") or "",
        "hashtags": list(doc.get("hashtags") or []),
        "lang": doc.get("lang") or "en",
        "slotAt": doc.get("slotAt") or "",
        "guardrails": list(doc.get("guardrails") or []),
        "generation": doc.get("generation") or None,
        "platform": doc.get("platform") or None,
        "manual": doc.get("manual") or None,
        "image": public_image(image),
        "imageNote": doc.get("imageNote") or "",
        "metrics": doc.get("metrics") or None,
        "publishError": doc.get("publishError") or "",
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


def expire_character_job(table: Any, job: dict[str, Any] | None, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Mark a character draw that outlived the Lambda as failed, so the row does not stay running."""
    if not isinstance(job, dict) or str(job.get("kind") or "") != "character":
        return job
    if str(job.get("status") or "") not in ("queued", "running"):
        return job
    started = _parse_slot(str(job.get("startedAt") or job.get("createdAt") or ""))
    if started is None:
        return job
    moment = now or datetime.now(ZoneInfo("UTC"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("UTC"))
    if (moment - started).total_seconds() <= CHARACTER_JOB_STALE_SECONDS:
        return job
    job["status"] = "failed"
    job["error"] = "The character sheet timed out. Draw it again."
    return put_job(table, job)


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
        "connection": public_connection(load_connection(table)),
        "counts": counts(table),
        "spendUsdMonth": round(month_spend(table), 4),
        "nextSlots": next_slots(settings, count=8, taken=taken_slots(table)),
        "builtinForbidden": list(BUILTIN_FORBIDDEN),
        "defaultModel": (os.environ.get("OPENROUTER_MODEL") or "").strip(),
        "recommendedVoice": RECOMMENDED_VOICE,
        "styleExampleMax": STYLE_EXAMPLE_MAX,
        "defaultImageModel": DEFAULT_IMAGE_MODEL,
        "imageModelAlternative": IMAGE_MODEL_ALTERNATIVE,
        "recommendedImageStyle": RECOMMENDED_IMAGE_STYLE,
        "imageStyleMax": IMAGE_STYLE_MAX,
        "imageCharacterMax": IMAGE_CHARACTER_MAX,
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


def load_connection(table: Any) -> dict[str, Any]:
    stored = _load_sk(table, "CONNECTION")
    return stored if stored.get("accessToken") else {}


def save_connection(table: Any, doc: dict[str, Any]) -> None:
    _put(
        table,
        {
            **_state_key("CONNECTION"),
            **doc,
            "updatedAt": board_store.now_iso(),
        },
    )


def clear_connection(table: Any) -> None:
    _put(table, {**_state_key("CONNECTION"), "updatedAt": board_store.now_iso()})


def public_connection(doc: dict[str, Any]) -> dict[str, Any]:
    import linkedin_api

    organizations = [
        {"id": str(row.get("id") or ""), "name": str(row.get("name") or "")}
        for row in (doc.get("organizations") or [])
        if isinstance(row, dict) and row.get("id")
    ]
    if not doc.get("accessToken"):
        status = linkedin_api.credentials_status()
        return {
            "status": "not_connected",
            "channel": "profile",
            "memberName": "",
            "organizationId": "",
            "organizationName": "",
            "organizations": [],
            "tokenExpiresAt": "",
            "includeOrganizations": False,
            "appConfigured": status == "ready",
            "appStatus": status,
        }
    return {
        "status": "connected",
        "channel": "page" if doc.get("channel") == "page" else "profile",
        "memberName": str(doc.get("memberName") or ""),
        "organizationId": str(doc.get("organizationId") or ""),
        "organizationName": str(doc.get("organizationName") or ""),
        "organizations": organizations,
        "tokenExpiresAt": str(doc.get("tokenExpiresAt") or ""),
        "includeOrganizations": bool(doc.get("includeOrganizations")),
        "appConfigured": True,
        "appStatus": "ready",
    }


def save_oauth_state(table: Any, state: str, user_sub: str, *, include_organizations: bool = False) -> None:
    _put(
        table,
        {
            "pk": f"LINKEDIN#oauth#{state}",
            "sk": "META",
            "userSub": user_sub,
            "includeOrganizations": bool(include_organizations),
            "createdAt": board_store.now_iso(),
            "expiresAt": int(time.time()) + 15 * 60,
        },
    )


def consume_oauth_state(table: Any, state: str) -> tuple[str, bool]:
    pk = f"LINKEDIN#oauth#{state}"
    row = _get(table, pk)
    table.delete_item(Key={"pk": pk, "sk": "META"})
    if not row:
        raise LinkedInError("That LinkedIn sign-in expired. Connect again.")
    created = _parse_slot(str(row.get("createdAt") or ""))
    if created is None or created < datetime.now(HKT) - timedelta(minutes=15):
        raise LinkedInError("That LinkedIn sign-in expired. Connect again.")
    return str(row.get("userSub") or ""), bool(row.get("includeOrganizations"))


def set_connection_target(table: Any, channel: str, organization_id: str) -> dict[str, Any]:
    doc = load_connection(table)
    if not doc:
        raise LinkedInError("LinkedIn is not connected.")
    if channel not in ("profile", "page"):
        raise LinkedInError("channel is invalid")
    if channel == "page":
        match = next(
            (
                row
                for row in (doc.get("organizations") or [])
                if isinstance(row, dict) and str(row.get("id") or "") == organization_id
            ),
            None,
        )
        if not match:
            raise LinkedInError("Choose a company page you administer.")
        doc["organizationId"] = str(match.get("id") or "")
        doc["organizationName"] = str(match.get("name") or "")
    doc["channel"] = channel
    save_connection(table, doc)
    return public_connection(doc)


_IMAGE_MEMORY: dict[str, tuple[str, bytes]] = {}
_CHARACTER_MEMORY: dict[str, tuple[str, bytes]] = {}
_IMAGE_MAX = IMAGE_BYTE_MAX


def public_image(image: dict[str, Any] | None) -> dict[str, Any] | None:
    """Picture state for the SPA. Bytes stay in S3."""
    if not isinstance(image, dict):
        return None
    content = str(image.get("contentType") or "")
    status = str(image.get("status") or "")
    if not content and not status:
        return None
    if content and not status:
        status = "ready"
    out: dict[str, Any] = {
        "status": status,
        "scene": str(image.get("scene") or ""),
        "caption": str(image.get("caption") or ""),
        "expression": str(image.get("expression") or ""),
        "error": str(image.get("error") or ""),
        "model": str(image.get("model") or ""),
    }
    if content:
        out["contentType"] = content
    brief = public_brief(image)
    if brief:
        out["brief"] = brief
    return out


def publishable_image(image: dict[str, Any] | None) -> dict[str, Any] | None:
    """Metadata for the bytes that can go out now.

    A ready picture publishes as itself. A redraw that is still pending or that
    failed keeps the previous ready picture (``held``) until the new panel is saved.
    A first picture that is pending or failed publishes as text.
    """
    if not isinstance(image, dict):
        return None
    status = str(image.get("status") or "")
    if image.get("contentType") and status in ("", "ready"):
        return image
    held = image.get("held")
    if status in ("pending", "failed") and isinstance(held, dict) and held.get("contentType"):
        return held
    return None


def image_publishable(image: dict[str, Any] | None) -> bool:
    """True when publish should attach the stored PNG."""
    return publishable_image(image) is not None


def brief_pending(image: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    """A scene rewrite is queued or running and not older than the worker could still be."""
    brief = image.get("brief") if isinstance(image, dict) else None
    if not isinstance(brief, dict) or str(brief.get("status") or "") != "pending":
        return False
    requested = _parse_slot(str(brief.get("requestedAt") or ""))
    if requested is None:
        return False
    moment = now or datetime.now(ZoneInfo("UTC"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("UTC"))
    return (moment - requested).total_seconds() <= BRIEF_PENDING_SECONDS


def public_brief(image: dict[str, Any] | None) -> dict[str, str] | None:
    """Scene-rewrite state for the SPA. A pending rewrite that is too old is shown as failed."""
    brief = image.get("brief") if isinstance(image, dict) else None
    if not isinstance(brief, dict):
        return None
    status = str(brief.get("status") or "")
    if not status:
        return None
    error = str(brief.get("error") or "")
    if status == "pending" and not brief_pending(image):
        status, error = "failed", "The scene took too long to write. Try again."
    return {"status": status, "error": error}


def image_pending_stale(image: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    if not isinstance(image, dict) or str(image.get("status") or "") != "pending":
        return False
    requested = _parse_slot(str(image.get("requestedAt") or ""))
    if requested is None:
        return True
    moment = now or datetime.now(ZoneInfo("UTC"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("UTC"))
    return (moment - requested).total_seconds() > IMAGE_PENDING_SECONDS


_CAPTION_ENDINGS = (".", "?", "!", "…")


def finish_caption(caption: str) -> str:
    """The spoken line as it is drawn and read: no wrapping quotes, and it ends with a mark.

    A question mark or an exclamation mark is kept; anything else gets a full stop.
    An apostrophe inside the line stays.
    """
    text = str(caption or "").strip().strip("'\"“”‘’").strip()
    if not text:
        return ""
    text = text[:IMAGE_CAPTION_MAX].rstrip()
    while text and text[-1] in ",;:-—–":
        text = text[:-1].rstrip()
    if not text:
        return ""
    if text.endswith(_CAPTION_ENDINGS):
        return text
    return text + "."


def caption_alt(caption: str) -> str:
    """The caption as alt text: the same line that is drawn in the picture."""
    return finish_caption(caption)[:300]


def _image_key(post_id: str) -> str:
    return f"linkedin/posts/{post_id}/image"


def _check_image(content_type: str, data: bytes) -> None:
    if content_type not in ("image/png", "image/jpeg"):
        raise LinkedInError("Use a PNG or JPEG image.")
    if not data or len(data) > _IMAGE_MAX:
        raise LinkedInError("The image must be under 1.5 MB.")
    if content_type == "image/png" and not data.startswith(b"\x89PNG"):
        raise LinkedInError("That file is not a PNG.")
    if content_type == "image/jpeg" and not data.startswith(b"\xff\xd8"):
        raise LinkedInError("That file is not a JPEG.")


def save_post_image(table: Any, post_id: str, content_type: str, data: bytes) -> dict[str, Any]:
    doc = get_post(table, post_id, consistent=True)
    if not doc:
        raise LinkedInError("post not found")
    if str(doc.get("status") or "") in ("published", "archived"):
        raise LinkedInError("That post can no longer be edited.")
    _check_image(content_type, data)
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if bucket:
        import boto3

        boto3.client("s3").put_object(
            Bucket=bucket,
            Key=_image_key(post_id),
            Body=data,
            ContentType=content_type,
        )
    else:
        _IMAGE_MEMORY[post_id] = (content_type, data)
    previous = doc.get("image") if isinstance(doc.get("image"), dict) else {}
    doc["image"] = {
        **previous,
        "contentType": content_type,
        "bytes": len(data),
        "status": "ready",
        "error": "",
    }
    return put_post(table, doc)


def delete_post_image(table: Any, post_id: str) -> dict[str, Any]:
    doc = get_post(table, post_id)
    if not doc:
        raise LinkedInError("post not found")
    if str(doc.get("status") or "") in ("published", "archived"):
        raise LinkedInError("That post can no longer be edited.")
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if bucket:
        import boto3

        boto3.client("s3").delete_object(Bucket=bucket, Key=_image_key(post_id))
    _IMAGE_MEMORY.pop(post_id, None)
    doc["image"] = None
    return put_post(table, doc)


def load_post_image(post_id: str) -> tuple[str, bytes] | None:
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if not bucket:
        return _IMAGE_MEMORY.get(post_id)
    import boto3

    try:
        response = boto3.client("s3").get_object(Bucket=bucket, Key=_image_key(post_id))
    except Exception as exc:  # noqa: BLE001 — NoSuchKey is a missing image, anything else propagates
        response_payload = getattr(exc, "response", None)
        code = ""
        if isinstance(response_payload, dict):
            code = str(response_payload.get("Error", {}).get("Code") or "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            return None
        raise
    body = response["Body"].read()
    return str(response.get("ContentType") or "image/png"), body


def _character_key(name: str) -> str:
    return f"linkedin/character/{name}"


def _put_named_bytes(name: str, content_type: str, data: bytes) -> None:
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if bucket:
        import boto3

        boto3.client("s3").put_object(
            Bucket=bucket,
            Key=_character_key(name),
            Body=data,
            ContentType=content_type,
        )
        return
    _CHARACTER_MEMORY[name] = (content_type, data)


def _load_named_bytes(name: str) -> tuple[str, bytes] | None:
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if not bucket:
        return _CHARACTER_MEMORY.get(name)
    import boto3

    try:
        response = boto3.client("s3").get_object(Bucket=bucket, Key=_character_key(name))
    except Exception as exc:  # noqa: BLE001 — a missing object is an empty slot
        response_payload = getattr(exc, "response", None)
        code = ""
        if isinstance(response_payload, dict):
            code = str(response_payload.get("Error", {}).get("Code") or "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            return None
        raise
    return str(response.get("ContentType") or "image/png"), response["Body"].read()


def _delete_named_bytes(name: str) -> None:
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if bucket:
        import boto3

        boto3.client("s3").delete_object(Bucket=bucket, Key=_character_key(name))
    _CHARACTER_MEMORY.pop(name, None)


def load_character(table: Any) -> dict[str, Any]:
    return _load_sk(table, "CHARACTER")


def _save_character(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    _put(table, {**_state_key("CHARACTER"), **doc, "updatedAt": board_store.now_iso()})
    return doc


def public_character(doc: dict[str, Any] | None) -> dict[str, Any]:
    stored = doc or {}
    photo = stored.get("photo") if isinstance(stored.get("photo"), dict) else None
    sheet = stored.get("sheet") if isinstance(stored.get("sheet"), dict) else None
    candidates = []
    for row in stored.get("candidates") or []:
        if isinstance(row, dict) and row.get("id"):
            candidates.append({"id": str(row["id"]), "contentType": str(row.get("contentType") or "image/png")})
    return {
        "photo": {"contentType": photo.get("contentType")} if photo and photo.get("contentType") else None,
        "sheet": {"contentType": sheet.get("contentType")} if sheet and sheet.get("contentType") else None,
        "candidates": candidates,
    }


def save_character_photo(table: Any, content_type: str, data: bytes) -> dict[str, Any]:
    _check_image(content_type, data)
    _put_named_bytes("photo", content_type, data)
    doc = load_character(table)
    doc["photo"] = {"contentType": content_type, "bytes": len(data)}
    return public_character(_save_character(table, doc))


def delete_character_photo(table: Any) -> dict[str, Any]:
    _delete_named_bytes("photo")
    doc = load_character(table)
    doc["photo"] = None
    return public_character(_save_character(table, doc))


def load_character_photo(table: Any) -> tuple[str, bytes] | None:
    del table
    return _load_named_bytes("photo")


def load_character_sheet() -> tuple[str, bytes] | None:
    return _load_named_bytes("sheet")


def valid_candidate_id(candidate_id: str) -> bool:
    return str(candidate_id or "") in CANDIDATE_IDS


def save_character_candidate(table: Any, candidate_id: str, content_type: str, data: bytes) -> None:
    if not valid_candidate_id(candidate_id):
        raise LinkedInError("That candidate is not one of the four drawings.")
    _check_image(content_type, data)
    _put_named_bytes(f"candidates/{candidate_id}", content_type, data)
    doc = load_character(table)
    rows = [row for row in (doc.get("candidates") or []) if isinstance(row, dict)]
    rows = [row for row in rows if str(row.get("id") or "") != candidate_id]
    rows.append({"id": candidate_id, "contentType": content_type, "bytes": len(data)})
    doc["candidates"] = rows
    _save_character(table, doc)


def clear_character_candidates(table: Any) -> None:
    doc = load_character(table)
    for row in doc.get("candidates") or []:
        if isinstance(row, dict) and valid_candidate_id(str(row.get("id") or "")):
            _delete_named_bytes(f"candidates/{row['id']}")
    doc["candidates"] = []
    _save_character(table, doc)


def load_character_candidate(candidate_id: str) -> tuple[str, bytes] | None:
    if not valid_candidate_id(candidate_id):
        return None
    return _load_named_bytes(f"candidates/{candidate_id}")


def choose_character(table: Any, candidate_id: str) -> dict[str, Any]:
    if not valid_candidate_id(candidate_id):
        raise LinkedInError("That candidate is not one of the four drawings.")
    loaded = load_character_candidate(candidate_id)
    if not loaded:
        raise LinkedInError("That candidate is gone. Draw the character again.")
    content_type, data = loaded
    _put_named_bytes("sheet", content_type, data)
    doc = load_character(table)
    doc["sheet"] = {"contentType": content_type, "bytes": len(data), "candidateId": candidate_id}
    return public_character(_save_character(table, doc))


def posts_ready_to_publish(table: Any, *, now_iso: str | None = None) -> list[dict[str, Any]]:
    """The oldest approved slot still inside the grace window. One post per tick."""
    now = _parse_slot(now_iso or board_store.now_iso()) or _as_hkt()
    ready: list[dict[str, Any]] = []
    for row in list_posts(table, status="approved"):
        slot = _parse_slot(str(row.get("slotAt") or ""))
        attempts = int(row.get("publishAttempts") or 0)
        if slot is None or slot > now or now - slot > PUBLISH_GRACE or attempts >= PUBLISH_ATTEMPTS:
            continue
        ready.append(row)
    ready.sort(key=lambda doc: str(doc.get("slotAt") or ""))
    return ready[:1]


def posts_given_up(table: Any) -> list[dict[str, Any]]:
    given_up: list[dict[str, Any]] = []
    for row in list_posts(table, status="approved"):
        if int(row.get("publishAttempts") or 0) >= PUBLISH_ATTEMPTS and not row.get("gaveUpNotifiedAt"):
            given_up.append(row)
    return given_up


def stamp_gave_up(table: Any, post_id: str) -> None:
    doc = get_post(table, post_id)
    if not doc:
        return
    doc["gaveUpNotifiedAt"] = board_store.now_iso()
    put_post(table, doc)


def record_publish_failure(table: Any, post_id: str, message: str, *, count_attempt: bool = True) -> dict[str, Any]:
    doc = get_post(table, post_id)
    if not doc:
        raise LinkedInError("post not found")
    if count_attempt:
        doc["publishAttempts"] = int(doc.get("publishAttempts") or 0) + 1
    doc["publishError"] = message[:300]
    return put_post(table, doc)


def remember_publish_urn(table: Any, post_id: str, urn: str) -> dict[str, Any]:
    """Store the LinkedIn id before the status flip so a later failure does not post twice."""
    doc = get_post(table, post_id)
    if not doc:
        raise LinkedInError("post not found")
    platform = dict(doc.get("platform") or {}) if isinstance(doc.get("platform"), dict) else {}
    platform["urn"] = urn
    doc["platform"] = platform
    return put_post(table, doc)


def mark_api_published(
    table: Any,
    post_id: str,
    urn: str,
    channel: str,
    organization_id: str = "",
) -> dict[str, Any]:
    doc = get_post(table, post_id)
    if not doc:
        raise LinkedInError("post not found")
    now = board_store.now_iso()
    doc["status"] = "published"
    doc["channel"] = "page" if channel == "page" else "profile"
    doc["publishError"] = ""
    doc["publishAttempts"] = int(doc.get("publishAttempts") or 0)
    platform = {
        "url": f"https://www.linkedin.com/feed/update/{urn}",
        "publishedAt": now,
        "urn": urn,
    }
    if channel == "page" and organization_id:
        platform["organizationId"] = organization_id
    doc["platform"] = platform
    return put_post(table, doc)


def save_post_metrics(table: Any, post_id: str, metrics: dict[str, Any]) -> None:
    doc = get_post(table, post_id)
    if not doc:
        return
    doc["metrics"] = metrics
    put_post(table, doc)
