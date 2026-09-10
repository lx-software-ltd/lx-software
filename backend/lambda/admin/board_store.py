"""Executive Board: DynamoDB persistence.

All board state lives in the records table under ``BOARD#<boardKey>#…``
partition keys so it can be excluded from the generic ``/records`` scan.

Key layout (``pk`` / ``sk``):

- ``BOARD#<b>#settings`` / ``STATE``            — board settings
- ``BOARD#<b>#charter`` / ``STATE``             — company vision + mission
- ``BOARD#<b>#members`` / ``MEMBER#<personaId>`` — per-member overrides
- ``BOARD#<b>#brief`` / ``STATE``               — company brief (Markdown)
- ``BOARD#<b>#updates`` / ``UPDATE#<ts>#<id>``  — owner updates
- ``BOARD#<b>#meeting#<id>`` / ``META``         — meeting document
  (``gsi1pk=BOARD#<b>#meetings``, ``gsi1sk=<createdAt>`` for listing)
- ``BOARD#<b>#meeting#<id>`` / ``TURN#<seq>``   — one persona statement
- ``BOARD#<b>#actions`` / ``ACTION#<id>``       — action items
- ``BOARD#<b>#chat#<personaId>`` / ``MSG#<ts>#<id>`` — chat threads
- ``BOARD#<b>#chatjob#<jobId>`` / ``META``      — chat jobs (TTL)
- ``BOARD#<b>#repo-snapshot`` / ``STATE``       — cached GitHub context
- ``BOARD#<b>#usage#<yyyy-mm-dd>`` / ``STATE``  — daily token / cost totals
- ``BOARD#<b>#usage#ads#<yyyy-mm-dd>`` / ``STATE`` — daily recorded Meta ads commitment
- ``BOARD#<b>#usage#ads#<yyyy-mm>`` / ``STATE`` — monthly recorded Meta ads commitment
- ``BOARD#<b>#approvals`` / ``APPROVAL#<id>``   — proposed tool actions awaiting the owner
- ``BOARD#<b>#toolcalls`` / ``CALL#<ts>#<id>``  — audit log of every tool call (TTL)
- ``BOARD#<b>#mail#threads`` / ``THREAD#<id>``  — email thread summaries (TTL)
- ``BOARD#<b>#mail#thread#<id>`` / ``MSG#<ts>#<id>`` — messages in a thread (TTL)
- ``BOARD#<b>#mail#msgids`` / ``MSGID#<digest>`` — RFC Message-ID → thread (TTL)
- ``BOARD#<b>#mail#pii`` / ``STATE``             — contact pseudonym map
- ``BOARD#<b>#cache`` / ``ITEM#<key>``          — cached research / AWS / security reads (TTL)
- ``BOARD#<b>#meta#threads`` / ``THREAD#<id>``  — WhatsApp / Page / IG thread summaries (TTL)
- ``BOARD#<b>#meta#thread#<id>`` / ``MSG#<ts>#<id>`` — inbound Meta messages (masked, TTL)
"""

from __future__ import annotations

import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from botocore.exceptions import ClientError

import runtime
from contract_constants import (
    BOARD_APPROVAL_TTL_DAYS,
    BOARD_CHAIR_DEFAULT,
    BOARD_CHAT_JOB_TTL_SECONDS,
    BOARD_DEFAULT_DAILY_BUDGET_USD,
    BOARD_KEY,
    BOARD_CACHE_REFRESH_TTL_HOURS,
    BOARD_MAIL_ALLOW_LIST_MAX_ENTRIES,
    BOARD_MAIL_MESSAGE_TTL_DAYS,
    BOARD_PERSONA_IDS,
    BOARD_STAFF_ACTION_CLASSES,
    BOARD_STAFF_DAILY_BUDGET_DEFAULT_USD,
    BOARD_STAFF_DAILY_BUDGET_MAX_USD,
    BOARD_STAFF_HOLD_CODE_STAGING_HOURS,
    BOARD_STAFF_MAX_RUNNING_TASKS_DEFAULT,
    BOARD_STAFF_OUTREACH_DAILY_CAP_START,
    BOARD_STAFF_PROSPECT_TYPES,
    BOARD_STAFF_RETENTION_DAYS,
    BOARD_STAFF_REVIEW_SAMPLE_SIZE,
    BOARD_STAFF_TASK_STATUSES,
    BOARD_TOOL_CALL_LOG_TTL_DAYS,
    BOARD_TOOL_DEFAULT_GLOBAL_MODE,
    BOARD_TOOL_DEFINITIONS,
    BOARD_TOOL_GLOBAL_MODES,
    BOARD_TOOL_LEVELS,
)
from ddb_convert import _from_ddb_nested, _to_ddb_nested
from http_common import _utc_iso_z

BOARD_PK_PREFIX = "BOARD#"


def board_pk(suffix: str) -> str:
    return f"{BOARD_PK_PREFIX}{BOARD_KEY}#{suffix}"


def event_targets_this_board(event: dict[str, Any] | None) -> bool:
    """True when a Scheduler / internal event is for this board.

    Missing or blank ``boardKey`` means this board (legacy payloads). A
    different key belongs to a sibling board — skip it.
    """
    if not event:
        return True
    key = event.get("boardKey")
    if key is None or str(key).strip() == "":
        return True
    return str(key) == BOARD_KEY


def records_table() -> Any:
    return runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])


def now_iso() -> str:
    return _utc_iso_z(datetime.now(timezone.utc))


def new_id() -> str:
    return uuid.uuid4().hex


def _strip_keys(item: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in item.items()
        if k not in ("pk", "sk", "gsi1pk", "gsi1sk")
    }


def _get_state(table: Any, suffix: str) -> dict[str, Any] | None:
    res = table.get_item(Key={"pk": board_pk(suffix), "sk": "STATE"})
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = _from_ddb_nested(_strip_keys(item))
    return doc if isinstance(doc, dict) else None


def _put_state(table: Any, suffix: str, doc: dict[str, Any]) -> None:
    table.put_item(
        Item={"pk": board_pk(suffix), "sk": "STATE", **_to_ddb_nested(doc)}
    )


def _put_state_if_version(table: Any, suffix: str, doc: dict[str, Any], *, attr: str, expected: Any) -> bool:
    """Optimistic write: succeed only when the stored ``attr`` still equals ``expected``.

    ``expected=None`` means "no item yet". Returns False on a version conflict.
    """
    kwargs: dict[str, Any] = {"ConditionExpression": "attribute_not_exists(pk)"}
    if expected is not None:
        kwargs = {
            "ConditionExpression": "attribute_not_exists(pk) OR #v = :expected",
            "ExpressionAttributeNames": {"#v": attr},
            "ExpressionAttributeValues": {":expected": expected},
        }
    try:
        table.put_item(Item={"pk": board_pk(suffix), "sk": "STATE", **_to_ddb_nested(doc)}, **kwargs)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    return True


def _query_all(table: Any, **kwargs: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    start_key: dict[str, Any] | None = None
    while True:
        params = dict(kwargs)
        if start_key:
            params["ExclusiveStartKey"] = start_key
        res = table.query(**params)
        for raw in res.get("Items", []) or []:
            doc = _from_ddb_nested(raw)
            if isinstance(doc, dict):
                items.append(doc)
        start_key = res.get("LastEvaluatedKey")
        if not start_key or ("Limit" in kwargs and len(items) >= kwargs["Limit"]):
            break
    return items


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def default_tool_matrix() -> dict[str, dict[str, str]]:
    """Contract defaults: ``{toolId: {personaId: level}}``."""
    out: dict[str, dict[str, str]] = {}
    for tool in BOARD_TOOL_DEFINITIONS:
        defaults = tool.get("defaults") or {}
        out[str(tool["id"])] = {
            pid: str(defaults.get(pid) or "off") for pid in BOARD_PERSONA_IDS
        }
    return out


ADS_DAILY_CAP_MAX = 500.0
ADS_MONTHLY_CAP_MAX = 2000.0


def _env_cap(name: str, fallback: float, ceiling: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return fallback
    try:
        value = float(raw)
    except ValueError:
        return fallback
    if value < 0:
        value = 0.0
    return min(value, ceiling)


def default_spend_caps() -> dict[str, float]:
    from contract_constants import BOARD_META_ADS_DAILY_CAP_USD, BOARD_META_ADS_MONTHLY_CAP_USD

    return {
        "metaAdsDailyUsd": _env_cap(
            "META_ADS_DAILY_CAP_USD", float(BOARD_META_ADS_DAILY_CAP_USD), ADS_DAILY_CAP_MAX
        ),
        "metaAdsMonthlyUsd": _env_cap(
            "META_ADS_MONTHLY_CAP_USD", float(BOARD_META_ADS_MONTHLY_CAP_USD), ADS_MONTHLY_CAP_MAX
        ),
    }


def default_tools_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "globalMode": BOARD_TOOL_DEFAULT_GLOBAL_MODE,
        "matrix": default_tool_matrix(),
        "allowList": [],
        "spendCaps": default_spend_caps(),
    }


_PHONE_ALLOW_RE = re.compile(r"^\+?\d{8,15}$")


def normalize_allow_list(raw: Any) -> list[str]:
    """De-duplicated emails, ``@domain`` wildcards, or E.164 / HK phone numbers."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str):
            continue
        compact = "".join(entry.split()).strip("<>")
        if not compact:
            continue
        if _PHONE_ALLOW_RE.fullmatch(compact):
            import board_pii

            raw_phone = board_pii.normalize_phone(compact)
            digits = re.sub(r"\D", "", raw_phone)
            value = f"+{digits}" if raw_phone.startswith("+") else digits
        else:
            value = compact.lower()
            if "@" not in value or value.count("@") != 1:
                continue
            local, host = value.split("@")
            if not host or "." not in host:
                continue
            value = value if local else f"@{host}"
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
        if len(out) >= BOARD_MAIL_ALLOW_LIST_MAX_ENTRIES:
            break
    return out


def normalize_spend_caps(raw: Any) -> dict[str, float]:
    out = default_spend_caps()
    if not isinstance(raw, dict):
        return out
    for key, ceiling in (("metaAdsDailyUsd", ADS_DAILY_CAP_MAX), ("metaAdsMonthlyUsd", ADS_MONTHLY_CAP_MAX)):
        if key not in raw:
            continue
        try:
            value = float(raw[key])
        except (TypeError, ValueError):
            continue
        if value < 0:
            value = 0.0
        out[key] = min(value, ceiling)
    return out


def normalize_tools_config(raw: Any) -> dict[str, Any]:
    """Merge a stored / submitted tools block over the contract defaults.

    Unknown tools and personas are dropped; unknown levels fall back to the
    default for that cell; levels above a tool's ``maxLevel`` are clamped.
    """
    out = default_tools_config()
    if not isinstance(raw, dict):
        return out
    if "enabled" in raw:
        out["enabled"] = bool(raw.get("enabled"))
    mode = raw.get("globalMode")
    if isinstance(mode, str) and mode in BOARD_TOOL_GLOBAL_MODES:
        out["globalMode"] = mode
    out["allowList"] = normalize_allow_list(raw.get("allowList"))
    out["spendCaps"] = normalize_spend_caps(raw.get("spendCaps"))
    matrix = raw.get("matrix")
    if isinstance(matrix, dict):
        max_levels = {str(t["id"]): str(t.get("maxLevel") or "act") for t in BOARD_TOOL_DEFINITIONS}
        for tool_id, cells in matrix.items():
            if tool_id not in out["matrix"] or not isinstance(cells, dict):
                continue
            cap = BOARD_TOOL_LEVELS.index(max_levels[tool_id])
            for pid, level in cells.items():
                if pid not in out["matrix"][tool_id]:
                    continue
                if isinstance(level, str) and level in BOARD_TOOL_LEVELS:
                    idx = min(BOARD_TOOL_LEVELS.index(level), cap)
                    out["matrix"][tool_id][pid] = BOARD_TOOL_LEVELS[idx]
    return out


DEFAULT_FIT_RUBRIC = (
    "Score 0–100. Start at 50. +20 if the organisation runs or hosts activities "
    "for children aged 0–12 in Hong Kong. +10 if it has a physical venue "
    "parents can visit. +10 if it publishes prices or a schedule. +10 if it is "
    "in one of the priority districts. −30 if it is adults-only, a tutoring "
    "centre focused on exams, or a franchise HQ with no local venue. −50 if the "
    "website or listing is dead or the business appears closed. Restaurants: "
    "+15 if they advertise a kids' menu, high chairs or a play corner; "
    "otherwise −20. Never score above 70 without a working website or a "
    "Google rating with at least 10 reviews."
)

DEFAULT_ESCALATION_KEYWORDS = [
    "refund",
    "lawyer",
    "legal",
    "police",
    "injury",
    "hurt",
    "abuse",
    "complaint",
    "media",
    "journalist",
    "PDPO",
    "delete my data",
    "unsubscribe me from everything",
    "退款",
    "律师",
    "律師",
    "警察",
    "受伤",
    "受傷",
    "投诉",
    "投訴",
]


def default_staff_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "maxRunningTasks": BOARD_STAFF_MAX_RUNNING_TASKS_DEFAULT,
        "dailyBudgetUsd": BOARD_STAFF_DAILY_BUDGET_DEFAULT_USD,
        "dutiesEnabled": False,
        "seniorPaused": False,
        "disabledReason": "",
    }


def default_review_config() -> dict[str, Any]:
    return {"digestTo": "", "digestHourHkt": 7, "sampleSize": BOARD_STAFF_REVIEW_SAMPLE_SIZE}


def default_boundaries() -> dict[str, Any]:
    return {
        "reply": {
            "languages": ["en", "zh-HK"],
            "tone": (
                "Warm, plain, brief. Never promise refunds, legal positions, "
                "or availability the catalog does not show."
            ),
            "quietHoursHkt": [22, 8],
            "maxOutboundPerChannelPerDay": {"mail": 60, "whatsapp": 60, "meta": 100},
            "maxMessagesPerThreadPerDay": 3,
            "sensitiveTemplatesOnly": [
                "payment_dispute",
                "cancellation",
                "safeguarding",
                "data_request",
            ],
        },
        "escalation": {
            "keywords": list(DEFAULT_ESCALATION_KEYWORDS),
            "refundThresholdHkd": 0,
            "ackTemplateId": "ack_escalation",
        },
        "holds": {
            "internal": 0,
            "inbound_reply": 0,
            "outbound_known": 0,
            "cold_outreach": 24,
            "publish": 24,
            "spend": 24,
            "code_staging": BOARD_STAFF_HOLD_CODE_STAGING_HOURS,
        },
        "holdOverrides": {},
        "outreach": {
            "fitRubric": DEFAULT_FIT_RUBRIC,
            "typesEnabled": ["provider", "venue", "community", "school"],
            "districtsFirst": [
                "Sha Tin",
                "Tai Po",
                "Kwun Tong",
                "Tsuen Wan",
                "Tseung Kwan O",
                "Yuen Long",
            ],
            "dailyCap": BOARD_STAFF_OUTREACH_DAILY_CAP_START,
            "capRaisedAt": "",
            "targets": {"qualifiedPerWeek": 50},
            "personalAddressesAllowed": False,
            "webFormsAllowed": False,
        },
        "content": {
            "pillars": [
                "activity spotlight",
                "district guide",
                "seasonal guide",
                "parenting tip",
                "provider story",
                "product news",
            ],
            "voice": "Helpful neighbour, not a brand. Specific places, dates and prices. No superlatives.",
            "languages": ["en", "zh-HK"],
            "perWeek": {"facebook": 7, "instagram": 7, "instagram_story": 7, "seo": 2},
            "windowsHkt": [10, 20],
            "assistedChannels": ["assisted_xiaohongshu", "assisted_fb_group"],
        },
        "intel": {"newsletterMailbox": "market@siutindei.com"},
    }


def normalize_staff_config(raw: Any) -> dict[str, Any]:
    out = default_staff_config()
    if not isinstance(raw, dict):
        return out
    if "enabled" in raw:
        out["enabled"] = bool(raw.get("enabled"))
    if "dutiesEnabled" in raw:
        out["dutiesEnabled"] = bool(raw.get("dutiesEnabled"))
    if "seniorPaused" in raw:
        out["seniorPaused"] = bool(raw.get("seniorPaused"))
    if isinstance(raw.get("disabledReason"), str):
        out["disabledReason"] = raw["disabledReason"].strip()[:200]
    try:
        running = int(raw.get("maxRunningTasks") or out["maxRunningTasks"])
        out["maxRunningTasks"] = max(1, min(20, running))
    except (TypeError, ValueError):
        pass
    try:
        budget = float(raw.get("dailyBudgetUsd") or out["dailyBudgetUsd"])
        out["dailyBudgetUsd"] = max(0.0, min(BOARD_STAFF_DAILY_BUDGET_MAX_USD, budget))
    except (TypeError, ValueError):
        pass
    return out


def normalize_review_config(raw: Any) -> dict[str, Any]:
    out = default_review_config()
    if not isinstance(raw, dict):
        return out
    digest = raw.get("digestTo")
    if isinstance(digest, str):
        out["digestTo"] = digest.strip()[:200]
    try:
        hour = int(raw.get("digestHourHkt") if raw.get("digestHourHkt") is not None else out["digestHourHkt"])
        out["digestHourHkt"] = max(0, min(23, hour))
    except (TypeError, ValueError):
        pass
    try:
        sample = int(raw.get("sampleSize") or out["sampleSize"])
        out["sampleSize"] = max(1, min(40, sample))
    except (TypeError, ValueError):
        pass
    return out


def normalize_boundaries(raw: Any) -> dict[str, Any]:
    out = default_boundaries()
    if not isinstance(raw, dict):
        return out
    reply = raw.get("reply")
    if isinstance(reply, dict):
        if isinstance(reply.get("tone"), str):
            out["reply"]["tone"] = reply["tone"].strip()[:2000]
        hours = reply.get("quietHoursHkt")
        if isinstance(hours, list) and len(hours) == 2:
            try:
                out["reply"]["quietHoursHkt"] = [int(hours[0]) % 24, int(hours[1]) % 24]
            except (TypeError, ValueError):
                pass
        langs = reply.get("languages")
        if isinstance(langs, list):
            out["reply"]["languages"] = [str(x) for x in langs if isinstance(x, str)][:8]
        caps = reply.get("maxOutboundPerChannelPerDay")
        if isinstance(caps, dict):
            merged = dict(out["reply"]["maxOutboundPerChannelPerDay"])
            for k, v in caps.items():
                try:
                    merged[str(k)] = max(0, min(1000, int(v)))
                except (TypeError, ValueError):
                    continue
            out["reply"]["maxOutboundPerChannelPerDay"] = merged
        try:
            out["reply"]["maxMessagesPerThreadPerDay"] = max(
                1, min(20, int(reply.get("maxMessagesPerThreadPerDay") or 3))
            )
        except (TypeError, ValueError):
            pass
        if isinstance(reply.get("sensitiveTemplatesOnly"), list):
            out["reply"]["sensitiveTemplatesOnly"] = [
                str(x) for x in reply["sensitiveTemplatesOnly"] if isinstance(x, str)
            ][:20]
    esc = raw.get("escalation")
    if isinstance(esc, dict):
        if isinstance(esc.get("keywords"), list):
            out["escalation"]["keywords"] = [
                str(x).strip() for x in esc["keywords"] if isinstance(x, str) and str(x).strip()
            ][:80]
        try:
            out["escalation"]["refundThresholdHkd"] = max(0, float(esc.get("refundThresholdHkd") or 0))
        except (TypeError, ValueError):
            pass
        if isinstance(esc.get("ackTemplateId"), str):
            out["escalation"]["ackTemplateId"] = esc["ackTemplateId"].strip()[:80]
    holds = raw.get("holds")
    if isinstance(holds, dict):
        for cls in BOARD_STAFF_ACTION_CLASSES:
            if cls in holds:
                try:
                    out["holds"][cls] = max(0, min(168, int(holds[cls])))
                except (TypeError, ValueError):
                    continue
    overrides = raw.get("holdOverrides")
    if isinstance(overrides, dict):
        cleaned: dict[str, int] = {}
        for key, hours in overrides.items():
            if not isinstance(key, str):
                continue
            try:
                cleaned[key[:80]] = max(0, min(168, int(hours)))
            except (TypeError, ValueError):
                continue
        out["holdOverrides"] = cleaned
    outreach = raw.get("outreach")
    if isinstance(outreach, dict):
        if isinstance(outreach.get("fitRubric"), str):
            out["outreach"]["fitRubric"] = outreach["fitRubric"].strip()[:8000]
        types = outreach.get("typesEnabled")
        if isinstance(types, list):
            out["outreach"]["typesEnabled"] = [
                t for t in (str(x) for x in types) if t in BOARD_STAFF_PROSPECT_TYPES
            ]
        districts = outreach.get("districtsFirst")
        if isinstance(districts, list):
            out["outreach"]["districtsFirst"] = [str(x) for x in districts if isinstance(x, str)][:20]
        try:
            out["outreach"]["dailyCap"] = max(1, min(200, int(outreach.get("dailyCap") or 20)))
        except (TypeError, ValueError):
            pass
        if isinstance(outreach.get("capRaisedAt"), str):
            out["outreach"]["capRaisedAt"] = outreach["capRaisedAt"]
        targets = outreach.get("targets")
        if isinstance(targets, dict):
            try:
                out["outreach"]["targets"]["qualifiedPerWeek"] = max(
                    1, min(500, int(targets.get("qualifiedPerWeek") or 50))
                )
            except (TypeError, ValueError):
                pass
        if "personalAddressesAllowed" in outreach:
            out["outreach"]["personalAddressesAllowed"] = bool(outreach.get("personalAddressesAllowed"))
        if "webFormsAllowed" in outreach:
            out["outreach"]["webFormsAllowed"] = bool(outreach.get("webFormsAllowed"))
    content = raw.get("content")
    if isinstance(content, dict):
        if isinstance(content.get("voice"), str):
            out["content"]["voice"] = content["voice"].strip()[:2000]
        if isinstance(content.get("pillars"), list):
            out["content"]["pillars"] = [str(x) for x in content["pillars"] if isinstance(x, str)][:20]
        if isinstance(content.get("languages"), list):
            out["content"]["languages"] = [str(x) for x in content["languages"] if isinstance(x, str)][:8]
        per_week = content.get("perWeek")
        if isinstance(per_week, dict):
            merged = dict(out["content"]["perWeek"])
            for k, v in per_week.items():
                try:
                    merged[str(k)] = max(0, min(50, int(v)))
                except (TypeError, ValueError):
                    continue
            out["content"]["perWeek"] = merged
        windows = content.get("windowsHkt")
        if isinstance(windows, list) and windows:
            try:
                out["content"]["windowsHkt"] = [int(x) % 24 for x in windows[:4]]
            except (TypeError, ValueError):
                pass
        if isinstance(content.get("assistedChannels"), list):
            out["content"]["assistedChannels"] = [
                str(x) for x in content["assistedChannels"] if isinstance(x, str)
            ][:8]
    intel = raw.get("intel")
    if isinstance(intel, dict) and isinstance(intel.get("newsletterMailbox"), str):
        out["intel"]["newsletterMailbox"] = intel["newsletterMailbox"].strip()[:200]
    return out


def default_settings() -> dict[str, Any]:
    return {
        "schedule": {"morningEnabled": False, "eveningEnabled": False},
        "defaultMode": "standup",
        "defaultChair": BOARD_CHAIR_DEFAULT,
        "shareFinanceSummary": False,
        "shareRepoSnapshot": False,
        "models": {"chat": "", "standup": "", "deepDive": ""},
        "dailyBudgetUsd": BOARD_DEFAULT_DAILY_BUDGET_USD,
        "tools": default_tools_config(),
        "staff": default_staff_config(),
        "review": default_review_config(),
        "boundaries": default_boundaries(),
        "updatedAt": None,
        "version": 0,
    }


def load_settings(table: Any) -> dict[str, Any]:
    stored = _get_state(table, "settings") or {}
    merged = default_settings()
    for key in ("defaultMode", "defaultChair", "dailyBudgetUsd", "updatedAt"):
        if key in stored:
            merged[key] = stored[key]
    for key in ("shareFinanceSummary", "shareRepoSnapshot"):
        merged[key] = bool(stored.get(key, merged[key]))
    schedule = stored.get("schedule")
    if isinstance(schedule, dict):
        merged["schedule"] = {
            "morningEnabled": bool(schedule.get("morningEnabled", False)),
            "eveningEnabled": bool(schedule.get("eveningEnabled", False)),
        }
    models = stored.get("models")
    if isinstance(models, dict):
        merged["models"] = {
            k: str(models.get(k) or "") for k in ("chat", "standup", "deepDive")
        }
    merged["tools"] = normalize_tools_config(stored.get("tools"))
    merged["staff"] = normalize_staff_config(stored.get("staff"))
    merged["review"] = normalize_review_config(stored.get("review"))
    merged["boundaries"] = normalize_boundaries(stored.get("boundaries"))
    try:
        merged["version"] = int(stored.get("version") or 0)
    except (TypeError, ValueError):
        merged["version"] = 0
    return merged


def save_settings(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    try:
        version = int(doc.get("version") or 0) + 1
    except (TypeError, ValueError):
        version = 1
    out = {**doc, "updatedAt": now_iso(), "version": version}
    _put_state(table, "settings", out)
    return out


# ---------------------------------------------------------------------------
# Charter, member overrides, brief
# ---------------------------------------------------------------------------

def load_charter(table: Any) -> dict[str, Any]:
    stored = _get_state(table, "charter") or {}
    return {
        "vision": str(stored.get("vision") or ""),
        "mission": str(stored.get("mission") or ""),
        "updatedAt": stored.get("updatedAt"),
    }


def save_charter(table: Any, *, vision: str, mission: str, owner_sub: str | None) -> dict[str, Any]:
    doc = {
        "vision": vision,
        "mission": mission,
        "updatedAt": now_iso(),
        "updatedBySub": owner_sub or "",
    }
    _put_state(table, "charter", doc)
    return {k: v for k, v in doc.items() if k != "updatedBySub"}


def load_member_overrides(table: Any) -> dict[str, dict[str, Any]]:
    items = _query_all(
        table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": board_pk("members"), ":prefix": "MEMBER#"},
    )
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        sk = str(item.get("sk") or "")
        persona_id = sk[len("MEMBER#"):] if sk.startswith("MEMBER#") else ""
        if persona_id:
            out[persona_id] = _strip_keys(item)
    return out


def save_member_override(table: Any, persona_id: str, doc: dict[str, Any]) -> None:
    table.put_item(
        Item={
            "pk": board_pk("members"),
            "sk": f"MEMBER#{persona_id}",
            **_to_ddb_nested(doc),
        }
    )


def delete_member_override(table: Any, persona_id: str) -> None:
    table.delete_item(Key={"pk": board_pk("members"), "sk": f"MEMBER#{persona_id}"})


def load_brief(table: Any) -> dict[str, Any]:
    stored = _get_state(table, "brief") or {}
    return {
        "markdown": str(stored.get("markdown") or ""),
        "updatedAt": stored.get("updatedAt"),
    }


def save_brief(table: Any, *, markdown: str, owner_sub: str | None) -> dict[str, Any]:
    doc = {"markdown": markdown, "updatedAt": now_iso(), "updatedBySub": owner_sub or ""}
    _put_state(table, "brief", doc)
    return {"markdown": markdown, "updatedAt": doc["updatedAt"]}


# ---------------------------------------------------------------------------
# Owner updates
# ---------------------------------------------------------------------------

def add_update(table: Any, *, text: str, owner_sub: str | None) -> dict[str, Any]:
    created = now_iso()
    update_id = new_id()
    doc = {
        "updateId": update_id,
        "text": text,
        "createdAt": created,
        "ownerSub": owner_sub or "",
    }
    table.put_item(
        Item={
            "pk": board_pk("updates"),
            "sk": f"UPDATE#{created}#{update_id}",
            **_to_ddb_nested(doc),
        }
    )
    return {k: v for k, v in doc.items() if k != "ownerSub"}


def list_updates(table: Any, *, limit: int = 20) -> list[dict[str, Any]]:
    items = _query_all(
        table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": board_pk("updates"), ":prefix": "UPDATE#"},
        ScanIndexForward=False,
        Limit=limit,
    )
    return [
        {k: v for k, v in _strip_keys(i).items() if k != "ownerSub"}
        for i in items[:limit]
    ]


# ---------------------------------------------------------------------------
# Meetings
# ---------------------------------------------------------------------------

def meeting_key(meeting_id: str) -> dict[str, str]:
    return {"pk": board_pk(f"meeting#{meeting_id}"), "sk": "META"}


def put_meeting(table: Any, doc: dict[str, Any]) -> None:
    meeting_id = str(doc["meetingId"])
    table.put_item(
        Item={
            **meeting_key(meeting_id),
            "gsi1pk": board_pk("meetings"),
            "gsi1sk": str(doc.get("createdAt") or now_iso()),
            **_to_ddb_nested(doc),
        }
    )


def get_meeting(table: Any, meeting_id: str) -> dict[str, Any] | None:
    res = table.get_item(Key=meeting_key(meeting_id))
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = _from_ddb_nested(_strip_keys(item))
    return doc if isinstance(doc, dict) else None


def list_meetings(table: Any, *, limit: int = 30) -> list[dict[str, Any]]:
    items = _query_all(
        table,
        IndexName="gsi1",
        KeyConditionExpression="gsi1pk = :pk",
        ExpressionAttributeValues={":pk": board_pk("meetings")},
        ScanIndexForward=False,
        Limit=limit,
    )
    return [_strip_keys(i) for i in items[:limit]]


def claim_meeting_phase(
    table: Any,
    meeting_id: str,
    *,
    expected_phase: str,
    stale_before_iso: str,
) -> bool:
    """Atomically mark a phase as running. False when another worker owns it."""
    now = now_iso()
    try:
        table.update_item(
            Key=meeting_key(meeting_id),
            UpdateExpression="SET phaseState = :running, phaseStartedAt = :now, updatedAt = :now",
            ConditionExpression=(
                "#st = :active AND phase = :expected AND "
                "(phaseState <> :running OR phaseStartedAt < :stale)"
            ),
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":running": "running",
                ":now": now,
                ":active": "running",
                ":expected": expected_phase,
                ":stale": stale_before_iso,
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    return True


def put_turn(table: Any, meeting_id: str, turn: dict[str, Any]) -> None:
    seq = int(turn["seq"])
    table.put_item(
        Item={
            "pk": board_pk(f"meeting#{meeting_id}"),
            "sk": f"TURN#{seq:04d}",
            **_to_ddb_nested(turn),
        }
    )


def list_turns(table: Any, meeting_id: str) -> list[dict[str, Any]]:
    items = _query_all(
        table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={
            ":pk": board_pk(f"meeting#{meeting_id}"),
            ":prefix": "TURN#",
        },
    )
    return [_strip_keys(i) for i in items]


# ---------------------------------------------------------------------------
# Action items
# ---------------------------------------------------------------------------

def put_action(table: Any, doc: dict[str, Any]) -> None:
    table.put_item(
        Item={
            "pk": board_pk("actions"),
            "sk": f"ACTION#{doc['actionId']}",
            **_to_ddb_nested(doc),
        }
    )


def get_action(table: Any, action_id: str) -> dict[str, Any] | None:
    res = table.get_item(Key={"pk": board_pk("actions"), "sk": f"ACTION#{action_id}"})
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = _from_ddb_nested(_strip_keys(item))
    return doc if isinstance(doc, dict) else None


def list_actions(table: Any) -> list[dict[str, Any]]:
    items = _query_all(
        table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": board_pk("actions"), ":prefix": "ACTION#"},
    )
    return [_strip_keys(i) for i in items]


# ---------------------------------------------------------------------------
# Chat threads and jobs
# ---------------------------------------------------------------------------

def chat_pk(persona_id: str) -> str:
    return board_pk(f"chat#{persona_id}")


def add_chat_message(
    table: Any,
    persona_id: str,
    *,
    role: str,
    text: str,
    usage: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    created = _utc_iso_z(now)
    message_id = new_id()
    doc: dict[str, Any] = {
        "messageId": message_id,
        "role": role,
        "text": text,
        "createdAt": created,
    }
    if usage:
        doc["usage"] = usage
    if extra:
        doc.update(extra)
    # Microsecond timestamp plus a role rank keeps a reply after its prompt
    # even when both land in the same millisecond.
    sort_stamp = now.strftime("%Y-%m-%dT%H:%M:%S.%f")
    role_rank = "1" if role == "assistant" else "0"
    table.put_item(
        Item={
            "pk": chat_pk(persona_id),
            "sk": f"MSG#{sort_stamp}#{role_rank}#{message_id}",
            **_to_ddb_nested(doc),
        }
    )
    return doc


def list_chat_messages(table: Any, persona_id: str, *, limit: int) -> list[dict[str, Any]]:
    """Latest ``limit`` messages, oldest first."""
    items = _query_all(
        table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": chat_pk(persona_id), ":prefix": "MSG#"},
        ScanIndexForward=False,
        Limit=limit,
    )
    ordered = list(reversed(items[:limit]))
    return [_strip_keys(i) for i in ordered]


def clear_chat_thread(table: Any, persona_id: str) -> int:
    items = _query_all(
        table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": chat_pk(persona_id), ":prefix": "MSG#"},
    )
    for item in items:
        table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
    return len(items)


def chat_job_key(job_id: str) -> dict[str, str]:
    return {"pk": board_pk(f"chatjob#{job_id}"), "sk": "META"}


def put_chat_job(table: Any, doc: dict[str, Any]) -> None:
    table.put_item(
        Item={
            **chat_job_key(str(doc["jobId"])),
            "expiresAt": int(time.time()) + BOARD_CHAT_JOB_TTL_SECONDS,
            **_to_ddb_nested(doc),
        }
    )


def get_chat_job(table: Any, job_id: str) -> dict[str, Any] | None:
    res = table.get_item(Key=chat_job_key(job_id))
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = _from_ddb_nested(_strip_keys(item))
    return doc if isinstance(doc, dict) else None


def claim_chat_job(table: Any, job_id: str, *, stale_before_iso: str) -> bool:
    now = now_iso()
    try:
        table.update_item(
            Key=chat_job_key(job_id),
            UpdateExpression="SET #st = :proc, updatedAt = :now",
            ConditionExpression="#st = :pend OR (#st = :proc AND updatedAt < :stale)",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":proc": "processing",
                ":pend": "pending",
                ":now": now,
                ":stale": stale_before_iso,
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    return True


# ---------------------------------------------------------------------------
# Decision log, repo snapshot and usage
# ---------------------------------------------------------------------------

MAX_DECISION_LOG_ENTRIES = 60


def load_decision_log(table: Any) -> list[dict[str, Any]]:
    stored = _get_state(table, "decision-log") or {}
    entries = stored.get("entries")
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def append_decision_log(table: Any, entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    merged = (load_decision_log(table) + entries)[-MAX_DECISION_LOG_ENTRIES:]
    _put_state(table, "decision-log", {"entries": merged, "updatedAt": now_iso()})

def load_repo_snapshot(table: Any) -> dict[str, Any] | None:
    return _get_state(table, "repo-snapshot")


def save_repo_snapshot(table: Any, doc: dict[str, Any]) -> None:
    _put_state(table, "repo-snapshot", doc)


def usage_day_key(date_iso: str | None = None) -> str:
    day = date_iso or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"usage#{day}"


def load_usage_day(table: Any, date_iso: str | None = None) -> dict[str, Any]:
    stored = _get_state(table, usage_day_key(date_iso)) or {}
    return {
        "promptTokens": int(stored.get("promptTokens") or 0),
        "completionTokens": int(stored.get("completionTokens") or 0),
        "totalTokens": int(stored.get("totalTokens") or 0),
        "cost": float(stored.get("cost") or 0.0),
        "calls": int(stored.get("calls") or 0),
    }


# ---------------------------------------------------------------------------
# Tool approvals and audit log
# ---------------------------------------------------------------------------

def approval_key(approval_id: str) -> dict[str, str]:
    return {"pk": board_pk("approvals"), "sk": f"APPROVAL#{approval_id}"}


def put_approval(table: Any, doc: dict[str, Any]) -> None:
    table.put_item(
        Item={
            **approval_key(str(doc["approvalId"])),
            "expiresAt": int(time.time()) + BOARD_APPROVAL_TTL_DAYS * 86400,
            **_to_ddb_nested(doc),
        }
    )


def get_approval(table: Any, approval_id: str) -> dict[str, Any] | None:
    res = table.get_item(Key=approval_key(approval_id))
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = _from_ddb_nested(_strip_keys(item))
    return doc if isinstance(doc, dict) else None


def list_approvals(table: Any) -> list[dict[str, Any]]:
    items = _query_all(
        table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": board_pk("approvals"), ":prefix": "APPROVAL#"},
    )
    out = [{k: v for k, v in _strip_keys(i).items() if k != "expiresAt"} for i in items]
    out.sort(key=lambda a: str(a.get("createdAt") or ""), reverse=True)
    return out


def claim_approval_decision(table: Any, approval_id: str, *, status: str) -> bool:
    """Move a pending approval to ``status`` exactly once."""
    try:
        table.update_item(
            Key=approval_key(approval_id),
            UpdateExpression="SET #st = :next, updatedAt = :now",
            ConditionExpression="#st = :pending",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":next": status,
                ":pending": "pending",
                ":now": now_iso(),
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    return True


def add_tool_call(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    created = str(doc.get("createdAt") or now_iso())
    call_id = str(doc.get("callId") or new_id())
    full = {**doc, "callId": call_id, "createdAt": created}
    table.put_item(
        Item={
            "pk": board_pk("toolcalls"),
            "sk": f"CALL#{created}#{call_id}",
            "expiresAt": int(time.time()) + BOARD_TOOL_CALL_LOG_TTL_DAYS * 86400,
            **_to_ddb_nested(full),
        }
    )
    return full


def list_tool_calls(table: Any, *, limit: int = 50) -> list[dict[str, Any]]:
    """Newest first."""
    items = _query_all(
        table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": board_pk("toolcalls"), ":prefix": "CALL#"},
        ScanIndexForward=False,
        Limit=limit,
    )
    return [{k: v for k, v in _strip_keys(i).items() if k != "expiresAt"} for i in items[:limit]]


# ---------------------------------------------------------------------------
# Mail index
# ---------------------------------------------------------------------------

def _mail_expires_at() -> int:
    return int(time.time()) + BOARD_MAIL_MESSAGE_TTL_DAYS * 86400


def _public_mail(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in _strip_keys(item).items() if k != "expiresAt"}


def mail_thread_key(thread_id: str) -> dict[str, str]:
    return {"pk": board_pk("mail#threads"), "sk": f"THREAD#{thread_id}"}


def put_mail_thread(table: Any, doc: dict[str, Any]) -> None:
    table.put_item(
        Item={
            **mail_thread_key(str(doc["threadId"])),
            "expiresAt": _mail_expires_at(),
            **_to_ddb_nested(doc),
        }
    )


def get_mail_thread(table: Any, thread_id: str) -> dict[str, Any] | None:
    res = table.get_item(Key=mail_thread_key(thread_id))
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = _public_mail(item)
    return doc if isinstance(doc, dict) else None


def list_mail_threads(table: Any) -> list[dict[str, Any]]:
    """Newest activity first."""
    items = _query_all(
        table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": board_pk("mail#threads"), ":prefix": "THREAD#"},
    )
    out = [_public_mail(i) for i in items]
    out.sort(key=lambda t: str(t.get("lastMessageAt") or ""), reverse=True)
    return out


def set_mail_thread_unread(table: Any, thread_id: str, *, unread: bool) -> None:
    table.update_item(
        Key=mail_thread_key(thread_id),
        UpdateExpression="SET unread = :u, updatedAt = :now",
        ConditionExpression="attribute_exists(threadId)",
        ExpressionAttributeValues={":u": bool(unread), ":now": now_iso()},
    )


def mail_message_key(thread_id: str, received_at: str, message_id: str) -> dict[str, str]:
    return {"pk": board_pk(f"mail#thread#{thread_id}"), "sk": f"MSG#{received_at}#{message_id}"}


def put_mail_message(table: Any, doc: dict[str, Any]) -> None:
    table.put_item(
        Item={
            **mail_message_key(str(doc["threadId"]), str(doc["receivedAt"]), str(doc["messageId"])),
            "expiresAt": _mail_expires_at(),
            **_to_ddb_nested(doc),
        }
    )


def delete_mail_message(table: Any, thread_id: str, received_at: str, message_id: str) -> None:
    table.delete_item(Key=mail_message_key(thread_id, received_at, message_id))


def list_mail_messages(table: Any, thread_id: str) -> list[dict[str, Any]]:
    """Oldest first."""
    items = _query_all(
        table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": board_pk(f"mail#thread#{thread_id}"), ":prefix": "MSG#"},
    )
    return [_public_mail(i) for i in items]


def _msgid_key(digest: str) -> dict[str, str]:
    return {"pk": board_pk("mail#msgids"), "sk": f"MSGID#{digest}"}


def delete_mail_msgid(table: Any, digest: str) -> None:
    """Undo :func:`put_mail_msgid` when the message it claimed could not be stored."""
    table.delete_item(Key=_msgid_key(digest))


def put_mail_msgid(table: Any, digest: str, *, thread_id: str, message_id: str) -> bool:
    """Record an RFC Message-ID; returns False when it was already indexed."""
    try:
        table.put_item(
            Item={
                **_msgid_key(digest),
                "threadId": thread_id,
                "messageId": message_id,
                "expiresAt": _mail_expires_at(),
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    return True


def get_mail_thread_for_msgid(table: Any, digest: str) -> str | None:
    res = table.get_item(Key=_msgid_key(digest))
    item = res.get("Item") if isinstance(res, dict) else None
    return str(item["threadId"]) if item and item.get("threadId") else None


def cache_key(name: str) -> dict[str, str]:
    return {"pk": board_pk("cache"), "sk": f"ITEM#{name}"}


def put_cache(table: Any, name: str, payload: dict[str, Any], *, ttl_seconds: int | None = None) -> dict[str, Any]:
    ttl = int(ttl_seconds if ttl_seconds is not None else BOARD_CACHE_REFRESH_TTL_HOURS * 3600)
    now = now_iso()
    doc = {
        "key": name,
        "payload": payload,
        "fetchedAt": now,
        "expiresAt": int(time.time()) + max(60, ttl),
    }
    table.put_item(Item={**cache_key(name), **_to_ddb_nested(doc)})
    return doc


def get_cache(table: Any, name: str) -> dict[str, Any] | None:
    res = table.get_item(Key=cache_key(name))
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = {k: v for k, v in _strip_keys(item).items()}
    expires = doc.get("expiresAt")
    try:
        if expires is not None and int(expires) < int(time.time()):
            return None
    except (TypeError, ValueError):
        return None
    return doc


def cache_digest(table: Any) -> dict[str, Any]:
    """Tiny summary of cached AWS / security reads for the context pack."""
    keys = ("aws:monthly_cost", "aws:alarms", "security:findings", "stores:metrics", "web:sessions")
    out: dict[str, Any] = {}
    for name in keys:
        hit = get_cache(table, name)
        if hit:
            out[name] = {"fetchedAt": hit.get("fetchedAt"), "payload": hit.get("payload")}
    return out


def add_usage_day(table: Any, usage: dict[str, Any], *, calls: int = 1) -> None:
    from decimal import Decimal

    table.update_item(
        Key={"pk": board_pk(usage_day_key()), "sk": "STATE"},
        UpdateExpression=(
            "ADD promptTokens :p, completionTokens :c, totalTokens :t, cost :cost, calls :calls"
        ),
        ExpressionAttributeValues={
            ":p": int(usage.get("promptTokens") or 0),
            ":c": int(usage.get("completionTokens") or 0),
            ":t": int(usage.get("totalTokens") or 0),
            ":cost": Decimal(str(round(float(usage.get("cost") or 0.0), 6))),
            ":calls": int(calls),
        },
    )


def external_usage_day_key(date_iso: str | None = None) -> str:
    day = date_iso or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"usage#external#{day}"


def add_external_usage_day(table: Any, field_name: str, amount: int = 1) -> None:
    """Count one third-party API call (e.g. ``searchCalls``) against today."""
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9:]{0,40}", field_name):
        raise ValueError("invalid usage field name")
    table.update_item(
        Key={"pk": board_pk(external_usage_day_key()), "sk": "STATE"},
        UpdateExpression="ADD #f :n",
        ExpressionAttributeNames={"#f": field_name},
        ExpressionAttributeValues={":n": int(amount)},
    )


def load_external_usage_day(table: Any, date_iso: str | None = None) -> dict[str, Any]:
    stored = _get_state(table, external_usage_day_key(date_iso)) or {}
    out = {"searchCalls": int(stored.get("searchCalls") or 0)}
    for key, value in stored.items():
        if str(key).startswith("reply"):
            try:
                out[str(key)] = int(value or 0)
            except (TypeError, ValueError):
                continue
    return out


def ads_usage_day_key(date_iso: str | None = None) -> str:
    day = date_iso or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"usage#ads#{day}"


def ads_usage_month_key(date_iso: str | None = None) -> str:
    day = date_iso or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"usage#ads#{day[:7]}"


def load_ads_spend(table: Any, date_iso: str | None = None) -> dict[str, float]:
    day = _get_state(table, ads_usage_day_key(date_iso)) or {}
    month = _get_state(table, ads_usage_month_key(date_iso)) or {}
    return {
        "dailyUsd": float(day.get("spendUsd") or 0.0),
        "monthlyUsd": float(month.get("spendUsd") or 0.0),
    }


def record_ads_spend(
    table: Any,
    *,
    daily_usd: float,
    monthly_usd: float,
    date_iso: str | None = None,
) -> None:
    from decimal import Decimal

    daily_amt = Decimal(str(round(max(0.0, float(daily_usd)), 6)))
    monthly_amt = Decimal(str(round(max(0.0, float(monthly_usd)), 6)))
    if daily_amt > 0:
        table.update_item(
            Key={"pk": board_pk(ads_usage_day_key(date_iso)), "sk": "STATE"},
            UpdateExpression="ADD spendUsd :s",
            ExpressionAttributeValues={":s": daily_amt},
        )
    if monthly_amt > 0:
        table.update_item(
            Key={"pk": board_pk(ads_usage_month_key(date_iso)), "sk": "STATE"},
            UpdateExpression="ADD spendUsd :s",
            ExpressionAttributeValues={":s": monthly_amt},
        )


# ---------------------------------------------------------------------------
# Meta (Page / Instagram / WhatsApp) index
# ---------------------------------------------------------------------------

def _meta_expires_at() -> int:
    return int(time.time()) + BOARD_MAIL_MESSAGE_TTL_DAYS * 86400


def meta_thread_key(thread_id: str) -> dict[str, str]:
    return {"pk": board_pk("meta#threads"), "sk": f"THREAD#{thread_id}"}


def put_meta_thread(table: Any, doc: dict[str, Any]) -> None:
    table.put_item(
        Item={
            **meta_thread_key(str(doc["threadId"])),
            "expiresAt": _meta_expires_at(),
            **_to_ddb_nested(doc),
        }
    )


def get_meta_thread(table: Any, thread_id: str) -> dict[str, Any] | None:
    res = table.get_item(Key=meta_thread_key(thread_id))
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = {k: v for k, v in _strip_keys(item).items() if k != "expiresAt"}
    return doc if isinstance(doc, dict) else None


def list_meta_threads(table: Any) -> list[dict[str, Any]]:
    items = _query_all(
        table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": board_pk("meta#threads"), ":prefix": "THREAD#"},
    )
    out = [{k: v for k, v in _strip_keys(i).items() if k != "expiresAt"} for i in items]
    out.sort(key=lambda t: str(t.get("lastMessageAt") or ""), reverse=True)
    return out


def put_meta_message(table: Any, doc: dict[str, Any]) -> None:
    table.put_item(
        Item={
            "pk": board_pk(f"meta#thread#{doc['threadId']}"),
            "sk": f"MSG#{doc['receivedAt']}#{doc['messageId']}",
            "expiresAt": _meta_expires_at(),
            **_to_ddb_nested(doc),
        }
    )


def put_meta_message_if_new(table: Any, doc: dict[str, Any]) -> bool:
    """Like :func:`put_meta_message` but returns False when the row already exists (webhook redelivery)."""
    item = {
        "pk": board_pk(f"meta#thread#{doc['threadId']}"),
        "sk": f"MSG#{doc['receivedAt']}#{doc['messageId']}",
        "expiresAt": _meta_expires_at(),
        **_to_ddb_nested(doc),
    }
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    return True


def list_meta_messages(table: Any, thread_id: str) -> list[dict[str, Any]]:
    items = _query_all(
        table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": board_pk(f"meta#thread#{thread_id}"), ":prefix": "MSG#"},
    )
    return [{k: v for k, v in _strip_keys(i).items() if k != "expiresAt"} for i in items]


# ---------------------------------------------------------------------------
# Staff overrides, tasks, holds, usage
# ---------------------------------------------------------------------------

def staff_override_suffix(seat_id: str) -> str:
    return f"staff#{seat_id}"


def load_staff_overrides(table: Any) -> dict[str, dict[str, Any]]:
    from contract_constants import BOARD_STAFF_SEAT_IDS

    out: dict[str, dict[str, Any]] = {}
    for seat_id in BOARD_STAFF_SEAT_IDS:
        stored = _get_state(table, staff_override_suffix(seat_id))
        if stored:
            out[seat_id] = stored
    return out


def save_staff_override(table: Any, seat_id: str, doc: dict[str, Any]) -> None:
    current = _get_state(table, staff_override_suffix(seat_id)) or {}
    _put_state(table, staff_override_suffix(seat_id), {**current, **doc, "updatedAt": now_iso()})


def delete_staff_override(table: Any, seat_id: str) -> None:
    table.delete_item(Key={"pk": board_pk(staff_override_suffix(seat_id)), "sk": "STATE"})


def task_key(task_id: str) -> dict[str, str]:
    return {"pk": board_pk(f"task#{task_id}"), "sk": "META"}


def _task_gsi(doc: dict[str, Any]) -> dict[str, str]:
    status = str(doc.get("status") or "queued")
    sla = str(doc.get("slaAt") or doc.get("createdAt") or "")
    return {"gsi1pk": board_pk(f"tasks#{status}"), "gsi1sk": f"{sla}#{doc.get('taskId') or ''}"}


def put_task(table: Any, doc: dict[str, Any]) -> None:
    table.put_item(Item={**task_key(str(doc["taskId"])), **_task_gsi(doc), **_to_ddb_nested(doc)})


def get_task(table: Any, task_id: str) -> dict[str, Any] | None:
    res = table.get_item(Key=task_key(task_id))
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = _from_ddb_nested(_strip_keys(item))
    return doc if isinstance(doc, dict) else None


def list_tasks(table: Any, status: str | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
    statuses = [status] if status else list(BOARD_STAFF_TASK_STATUSES)
    items: list[dict[str, Any]] = []
    for st in statuses:
        rows = _query_all(
            table,
            IndexName="gsi1",
            KeyConditionExpression="gsi1pk = :pk",
            ExpressionAttributeValues={":pk": board_pk(f"tasks#{st}")},
            ScanIndexForward=True,
            Limit=limit,
        )
        items.extend(_strip_keys(i) for i in rows)
    items.sort(key=lambda t: str(t.get("slaAt") or t.get("createdAt") or ""))
    return items[:limit]


def claim_task_step(table: Any, task_id: str, expected_step: int) -> bool:
    """Claim a queued task (expected_step=0) or confirm the next step is ours."""
    now = now_iso()
    try:
        if expected_step == 0:
            table.update_item(
                Key=task_key(task_id),
                UpdateExpression="SET #st = :running, startedAt = :now, updatedAt = :now, gsi1pk = :gpk, gsi1sk = :gsk",
                ConditionExpression="#st = :queued AND #step = :expected",
                ExpressionAttributeNames={"#st": "status", "#step": "step"},
                ExpressionAttributeValues={
                    ":running": "running",
                    ":queued": "queued",
                    ":expected": expected_step,
                    ":now": now,
                    ":gpk": board_pk("tasks#running"),
                    ":gsk": f"{now}#{task_id}",
                },
            )
        else:
            table.update_item(
                Key=task_key(task_id),
                UpdateExpression="SET updatedAt = :now",
                ConditionExpression="#st = :running AND #step = :expected",
                ExpressionAttributeNames={"#st": "status", "#step": "step"},
                ExpressionAttributeValues={
                    ":running": "running",
                    ":expected": expected_step,
                    ":now": now,
                },
            )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    return True


def put_task_step(table: Any, task_id: str, step: dict[str, Any]) -> None:
    seq = int(step["seq"])
    table.put_item(
        Item={
            "pk": board_pk(f"task#{task_id}"),
            "sk": f"STEP#{seq:03d}",
            **_to_ddb_nested(step),
        }
    )


def list_task_steps(table: Any, task_id: str) -> list[dict[str, Any]]:
    items = _query_all(
        table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": board_pk(f"task#{task_id}"), ":prefix": "STEP#"},
    )
    return [_strip_keys(i) for i in items]


def put_task_review(table: Any, task_id: str, review: dict[str, Any]) -> None:
    seq = int(review["seq"])
    table.put_item(
        Item={
            "pk": board_pk(f"task#{task_id}"),
            "sk": f"REVIEW#{seq:02d}",
            **_to_ddb_nested(review),
        }
    )


def list_task_reviews(table: Any, task_id: str) -> list[dict[str, Any]]:
    items = _query_all(
        table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": board_pk(f"task#{task_id}"), ":prefix": "REVIEW#"},
    )
    return [_strip_keys(i) for i in items]


def staff_usage_day_key(date_iso: str | None = None) -> str:
    day = date_iso or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"staffusage#{day}"


def load_staff_usage_day(table: Any, date_iso: str | None = None) -> dict[str, Any]:
    stored = _get_state(table, staff_usage_day_key(date_iso)) or {}
    return {
        "promptTokens": int(stored.get("promptTokens") or 0),
        "completionTokens": int(stored.get("completionTokens") or 0),
        "totalTokens": int(stored.get("totalTokens") or 0),
        "cost": float(stored.get("cost") or 0.0),
        "calls": int(stored.get("calls") or 0),
        "bySeat": dict(stored.get("bySeat") or {}),
    }


def add_staff_usage_day(table: Any, seat_or_persona: str, usage: dict[str, Any]) -> None:
    current = load_staff_usage_day(table)
    by_seat = dict(current.get("bySeat") or {})
    slot = dict(by_seat.get(seat_or_persona) or {"cost": 0.0, "calls": 0})
    cost = float(usage.get("cost") or 0.0)
    calls = int(usage.get("calls") or 1)
    slot["cost"] = float(slot.get("cost") or 0.0) + cost
    slot["calls"] = int(slot.get("calls") or 0) + calls
    by_seat[seat_or_persona] = slot
    doc = {
        "promptTokens": current["promptTokens"] + int(usage.get("promptTokens") or 0),
        "completionTokens": current["completionTokens"] + int(usage.get("completionTokens") or 0),
        "totalTokens": current["totalTokens"] + int(usage.get("totalTokens") or 0),
        "cost": current["cost"] + cost,
        "calls": current["calls"] + calls,
        "bySeat": by_seat,
        "expiresAt": int(time.time()) + 400 * 86400,
    }
    _put_state(table, staff_usage_day_key(), doc)


def hold_key(hold_id: str) -> dict[str, str]:
    return {"pk": board_pk(f"hold#{hold_id}"), "sk": "META"}


def put_hold(table: Any, doc: dict[str, Any]) -> None:
    status = str(doc.get("status") or "scheduled")
    execute_at = str(doc.get("executeAt") or "")
    table.put_item(
        Item={
            **hold_key(str(doc["holdId"])),
            "gsi1pk": board_pk(f"holds#{status}"),
            "gsi1sk": f"{execute_at}#{doc.get('holdId') or ''}",
            **_to_ddb_nested(doc),
        }
    )


def get_hold(table: Any, hold_id: str) -> dict[str, Any] | None:
    res = table.get_item(Key=hold_key(hold_id))
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = _from_ddb_nested(_strip_keys(item))
    return doc if isinstance(doc, dict) else None


def list_holds(table: Any, status: str = "scheduled", *, limit: int = 200) -> list[dict[str, Any]]:
    rows = _query_all(
        table,
        IndexName="gsi1",
        KeyConditionExpression="gsi1pk = :pk",
        ExpressionAttributeValues={":pk": board_pk(f"holds#{status}")},
        ScanIndexForward=True,
        Limit=limit,
    )
    return [_strip_keys(i) for i in rows[:limit]]


def claim_hold(table: Any, hold_id: str, *, from_status: str, to_status: str) -> bool:
    now = now_iso()
    try:
        table.update_item(
            Key=hold_key(hold_id),
            UpdateExpression="SET #st = :next, updatedAt = :now, gsi1pk = :gpk",
            ConditionExpression="#st = :from",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":next": to_status,
                ":from": from_status,
                ":now": now,
                ":gpk": board_pk(f"holds#{to_status}"),
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    return True


def ramp_key(class_key: str) -> str:
    return f"ramp#{class_key}"


def load_ramp(table: Any, class_key: str) -> dict[str, Any]:
    stored = _get_state(table, ramp_key(class_key)) or {}
    return {
        "classKey": class_key,
        "actions": int(stored.get("actions") or 0),
        "vetoes": int(stored.get("vetoes") or 0),
        "days": dict(stored.get("days") or {}),
        "recent": list(stored.get("recent") or []),
    }


def save_ramp(table: Any, class_key: str, doc: dict[str, Any]) -> None:
    _put_state(table, ramp_key(class_key), doc)


def lesson_key(lesson_id: str) -> dict[str, str]:
    return {"pk": board_pk(f"lesson#{lesson_id}"), "sk": "META"}


def put_lesson(table: Any, doc: dict[str, Any]) -> None:
    subject = str(doc.get("subject") or "")
    created = str(doc.get("createdAt") or now_iso())
    item: dict[str, Any] = {
        **lesson_key(str(doc["lessonId"])),
        "gsi1pk": board_pk(f"lessons#{subject}"),
        "gsi1sk": created,
        **_to_ddb_nested(doc),
    }
    if not doc.get("confirmed"):
        item["expiresAt"] = int(time.time()) + BOARD_STAFF_RETENTION_DAYS * 86400
    table.put_item(Item=item)


def get_lesson(table: Any, lesson_id: str) -> dict[str, Any] | None:
    res = table.get_item(Key=lesson_key(lesson_id))
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = _from_ddb_nested(_strip_keys(item))
    return doc if isinstance(doc, dict) else None


def list_lessons(table: Any, subject: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
    if subject:
        rows = _query_all(
            table,
            IndexName="gsi1",
            KeyConditionExpression="gsi1pk = :pk",
            ExpressionAttributeValues={":pk": board_pk(f"lessons#{subject}")},
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_strip_keys(i) for i in rows[:limit]]
    from contract_constants import BOARD_PERSONA_IDS, BOARD_STAFF_SEAT_IDS

    items: list[dict[str, Any]] = []
    for sid in list(BOARD_PERSONA_IDS) + list(BOARD_STAFF_SEAT_IDS):
        items.extend(list_lessons(table, sid, limit=limit))
    items.sort(key=lambda x: str(x.get("createdAt") or ""), reverse=True)
    return items[:limit]


def put_breaker(table: Any, name: str, doc: dict[str, Any]) -> None:
    _put_state(table, f"breaker#{name}", doc)
    idx = _get_state(table, "breaker-index") or {"names": []}
    names = [str(x) for x in (idx.get("names") or []) if x]
    if name not in names:
        names.append(name)
        _put_state(table, "breaker-index", {"names": names})


def get_breaker(table: Any, name: str) -> dict[str, Any] | None:
    return _get_state(table, f"breaker#{name}")


def list_breakers(table: Any) -> list[dict[str, Any]]:
    idx = _get_state(table, "breaker-index") or {"names": []}
    out: list[dict[str, Any]] = []
    for name in idx.get("names") or []:
        row = get_breaker(table, str(name))
        if row:
            out.append({"name": name, **row})
    return out


def get_tool_call(table: Any, call_id: str) -> dict[str, Any] | None:
    if not call_id:
        return None
    for row in list_tool_calls(table, limit=500):
        if str(row.get("callId") or "") == call_id:
            return row
    return None


def put_review_snapshot(table: Any, date_hkt: str, doc: dict[str, Any]) -> None:
    item = {
        "pk": board_pk(f"review#{date_hkt}"),
        "sk": "STATE",
        "expiresAt": int(time.time()) + BOARD_STAFF_RETENTION_DAYS * 86400,
        **_to_ddb_nested(doc),
    }
    table.put_item(Item=item)


def get_review_snapshot(table: Any, date_hkt: str) -> dict[str, Any] | None:
    res = table.get_item(Key={"pk": board_pk(f"review#{date_hkt}"), "sk": "STATE"})
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = _from_ddb_nested(_strip_keys(item))
    return doc if isinstance(doc, dict) else None


def prospect_key(prospect_id: str) -> dict[str, str]:
    return {"pk": board_pk(f"prospect#{prospect_id}"), "sk": "META"}


def put_prospect(table: Any, doc: dict[str, Any]) -> None:
    stage = str(doc.get("stage") or "discovered")
    sort = str(doc.get("nextTouchAt") or doc.get("updatedAt") or doc.get("createdAt") or "")
    table.put_item(
        Item={
            **prospect_key(str(doc["prospectId"])),
            "gsi1pk": board_pk(f"prospects#{stage}"),
            "gsi1sk": f"{sort}#{doc.get('prospectId') or ''}",
            **_to_ddb_nested(doc),
        }
    )


def get_prospect(table: Any, prospect_id: str) -> dict[str, Any] | None:
    res = table.get_item(Key=prospect_key(prospect_id))
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = _from_ddb_nested(_strip_keys(item))
    return doc if isinstance(doc, dict) else None


def list_prospects(table: Any, stage: str | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
    from contract_constants import BOARD_STAFF_PROSPECT_STAGES

    stages = [stage] if stage else list(BOARD_STAFF_PROSPECT_STAGES)
    items: list[dict[str, Any]] = []
    for st in stages:
        rows = _query_all(
            table,
            IndexName="gsi1",
            KeyConditionExpression="gsi1pk = :pk",
            ExpressionAttributeValues={":pk": board_pk(f"prospects#{st}")},
            ScanIndexForward=True,
            Limit=limit,
        )
        items.extend(_strip_keys(i) for i in rows)
    return items[:limit]


def put_prospect_key(table: Any, dedupe_key: str, prospect_id: str) -> None:
    _put_state(table, f"prospectkey#{dedupe_key}", {"prospectId": prospect_id})


def get_prospect_by_dedupe(table: Any, dedupe_key: str) -> str | None:
    stored = _get_state(table, f"prospectkey#{dedupe_key}")
    if not stored:
        return None
    pid = stored.get("prospectId")
    return str(pid) if pid else None


def put_suppress(table: Any, digest: str, doc: dict[str, Any]) -> None:
    _put_state(table, f"suppress#{digest}", doc)


def get_suppress(table: Any, digest: str) -> dict[str, Any] | None:
    return _get_state(table, f"suppress#{digest}")


def put_sequence(table: Any, sequence_id: str, doc: dict[str, Any]) -> None:
    _put_state(table, f"sequence#{sequence_id}", doc)


def get_sequence(table: Any, sequence_id: str) -> dict[str, Any] | None:
    return _get_state(table, f"sequence#{sequence_id}")


def watch_key(watch_id: str) -> dict[str, str]:
    return {"pk": board_pk(f"watch#{watch_id}"), "sk": "META"}


def put_watch(table: Any, doc: dict[str, Any]) -> None:
    table.put_item(
        Item={
            **watch_key(str(doc["watchId"])),
            "gsi1pk": board_pk(f"watch#{doc.get('kind') or 'competitor'}"),
            "gsi1sk": str(doc.get("name") or doc.get("watchId") or ""),
            **_to_ddb_nested(doc),
        }
    )


def get_watch(table: Any, watch_id: str) -> dict[str, Any] | None:
    res = table.get_item(Key=watch_key(watch_id))
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = _from_ddb_nested(_strip_keys(item))
    return doc if isinstance(doc, dict) else None


def list_watches(table: Any) -> list[dict[str, Any]]:
    from contract_constants import BOARD_STAFF_WATCH_KINDS

    kinds = list(BOARD_STAFF_WATCH_KINDS)
    if "candidate" not in kinds:
        kinds.append("candidate")
    items: list[dict[str, Any]] = []
    for kind in kinds:
        rows = _query_all(
            table,
            IndexName="gsi1",
            KeyConditionExpression="gsi1pk = :pk",
            ExpressionAttributeValues={":pk": board_pk(f"watch#{kind}")},
        )
        items.extend(_strip_keys(i) for i in rows)
    return items


def delete_watch(table: Any, watch_id: str) -> None:
    table.delete_item(Key=watch_key(watch_id))


def list_watch_pages(table: Any, watch_id: str) -> list[dict[str, Any]]:
    items = _query_all(
        table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": board_pk(f"watch#{watch_id}"), ":prefix": "PAGE#"},
    )
    return [_strip_keys(i) for i in items]


def put_watch_page(table: Any, watch_id: str, url_digest: str, doc: dict[str, Any]) -> None:
    table.put_item(
        Item={
            "pk": board_pk(f"watch#{watch_id}"),
            "sk": f"PAGE#{url_digest}",
            **_to_ddb_nested(doc),
        }
    )


def get_watch_page(table: Any, watch_id: str, url_digest: str) -> dict[str, Any] | None:
    res = table.get_item(Key={"pk": board_pk(f"watch#{watch_id}"), "sk": f"PAGE#{url_digest}"})
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = _from_ddb_nested(_strip_keys(item))
    return doc if isinstance(doc, dict) else None


def put_change(table: Any, doc: dict[str, Any]) -> None:
    created = str(doc.get("createdAt") or now_iso())
    change_id = str(doc.get("changeId") or new_id())
    day = created[:10]
    table.put_item(
        Item={
            "pk": board_pk(f"change#{day}#{change_id}"),
            "sk": "META",
            "gsi1pk": board_pk("changes"),
            "gsi1sk": created,
            "expiresAt": int(time.time()) + BOARD_STAFF_RETENTION_DAYS * 86400,
            **_to_ddb_nested({**doc, "changeId": change_id, "createdAt": created}),
        }
    )


def list_changes(table: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = _query_all(
        table,
        IndexName="gsi1",
        KeyConditionExpression="gsi1pk = :pk",
        ExpressionAttributeValues={":pk": board_pk("changes")},
        ScanIndexForward=False,
        Limit=limit,
    )
    return [_strip_keys(i) for i in rows[:limit]]


def content_key(content_id: str) -> dict[str, str]:
    return {"pk": board_pk(f"content#{content_id}"), "sk": "META"}


def put_content(table: Any, doc: dict[str, Any]) -> None:
    from contract_constants import BOARD_STAFF_RETENTION_DAYS_CONTENT

    status = str(doc.get("status") or "idea")
    slot = str(doc.get("slotAt") or "")
    table.put_item(
        Item={
            **content_key(str(doc["contentId"])),
            "gsi1pk": board_pk(f"content#{status}"),
            "gsi1sk": f"{slot}#{doc.get('contentId') or ''}",
            "expiresAt": int(time.time()) + BOARD_STAFF_RETENTION_DAYS_CONTENT * 86400,
            **_to_ddb_nested(doc),
        }
    )


def get_content(table: Any, content_id: str) -> dict[str, Any] | None:
    res = table.get_item(Key=content_key(content_id))
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = _from_ddb_nested(_strip_keys(item))
    return doc if isinstance(doc, dict) else None


def list_content(table: Any, status: str | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
    from contract_constants import BOARD_STAFF_CONTENT_STATUSES

    statuses = [status] if status else list(BOARD_STAFF_CONTENT_STATUSES)
    items: list[dict[str, Any]] = []
    for st in statuses:
        rows = _query_all(
            table,
            IndexName="gsi1",
            KeyConditionExpression="gsi1pk = :pk",
            ExpressionAttributeValues={":pk": board_pk(f"content#{st}")},
            ScanIndexForward=True,
            Limit=limit,
        )
        items.extend(_strip_keys(i) for i in rows)
    return items[:limit]


def put_newsletter_sub(table: Any, digest: str, list_name: str, doc: dict[str, Any]) -> None:
    table.put_item(
        Item={
            "pk": board_pk(f"newsletter#sub#{digest}"),
            "sk": "META",
            "gsi1pk": board_pk(f"newsletter#{list_name}"),
            "gsi1sk": str(doc.get("confirmedAt") or doc.get("createdAt") or ""),
            **_to_ddb_nested(doc),
        }
    )


def get_newsletter_sub(table: Any, digest: str) -> dict[str, Any] | None:
    res = table.get_item(Key={"pk": board_pk(f"newsletter#sub#{digest}"), "sk": "META"})
    item = res.get("Item") if isinstance(res, dict) else None
    if not item:
        return None
    doc = _from_ddb_nested(_strip_keys(item))
    return doc if isinstance(doc, dict) else None


def list_newsletter_subs(table: Any, list_name: str, *, limit: int = 500) -> list[dict[str, Any]]:
    rows = _query_all(
        table,
        IndexName="gsi1",
        KeyConditionExpression="gsi1pk = :pk",
        ExpressionAttributeValues={":pk": board_pk(f"newsletter#{list_name}")},
        Limit=limit,
    )
    return [_strip_keys(i) for i in rows[:limit]]


def outreach_day_key(date_iso: str | None = None) -> str:
    day = date_iso or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"outreachday#{day}"


def load_outreach_day(table: Any, date_iso: str | None = None) -> dict[str, Any]:
    stored = _get_state(table, outreach_day_key(date_iso)) or {}
    return {
        "sent": int(stored.get("sent") or 0),
        "bounces": int(stored.get("bounces") or 0),
        "complaints": int(stored.get("complaints") or 0),
    }


def save_outreach_day(table: Any, doc: dict[str, Any], date_iso: str | None = None) -> None:
    _put_state(table, outreach_day_key(date_iso), {**doc, "expiresAt": int(time.time()) + 400 * 86400})
