"""Catalog sheet → siutindei importer JSON (Cognito importer user).

This stack never writes Aurora. Import calls the siutindei admin HTTP API
after ``AdminInitiateAuth`` (ADMIN_USER_PASSWORD_AUTH) for a dedicated
importer user. The kill switch ``BOARD_CATALOG_IMPORT_ENABLED`` is
fail-closed. There is no LLM in this path.

See docs/deployment/admin-website.md → Catalog import.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

from admin_runtime import _get_secretsmanager_client
from contract_constants import (
    BOARD_CATALOG_AUTO_IMPORT_DEFAULT,
    BOARD_CATALOG_EVENT_KINDS,
    BOARD_CATALOG_IMPORT_ENABLED_DEFAULT,
    BOARD_CATALOG_MAX_AWAITING_IMPORT,
    BOARD_CATALOG_MAX_ORGS_PER_IMPORT,
    BOARD_CATALOG_QUALITY_MIN_FACTS,
    BOARD_CATALOG_TYPE_TO_CATEGORY,
)
from http_common import _log_event
from openrouter_client import read_secret_raw

CATALOG_EVENT_KIND = "catalog-micro-batch"
CATALOG_ENRICH_KIND = "catalog-enrich"
CATALOG_SHEET_KINDS = frozenset(BOARD_CATALOG_EVENT_KINDS) or frozenset(
    {CATALOG_EVENT_KIND, CATALOG_ENRICH_KIND}
)

# Sheet field → importer field. Only copied when listed in verified_fields.
_SHEET_TO_IMPORTER = {
    "name_en": "name",
    "name": "name",
    "name_zh": "name_zh",
    "address_en": "address",
    "address": "address",
    "official_url": "website",
    "website": "website",
    "phone": "phone",
    "lat": "lat",
    "lng": "lng",
    "description_en": "description",
    "description": "description",
    "source_url": "source_url",
}

_NOTE_FIELDS = ("opening_hours", "price_note", "age_range", "free_or_paid", "description_zh")
_NUMERIC_FIELDS = frozenset({"lat", "lng"})
# HTTP API integrations cap at 30s. Preview is 3 hops + Cognito; keep the
# worst case under that so a slow importer fails here (and is stored) instead
# of as an empty API Gateway 504.
_COGNITO_TIMEOUT = 5
_PREVIEW_HTTP_TIMEOUT = 7
_IMPORT_HTTP_TIMEOUT = 8


def _importer_dests() -> list[tuple[str, list[str]]]:
    dests: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for _sheet_key, dest in _SHEET_TO_IMPORTER.items():
        if dest == "name" or dest in seen:
            continue
        seen.add(dest)
        dests.append((dest, [k for k, v in _SHEET_TO_IMPORTER.items() if v == dest]))
    return dests


_IMPORTER_DESTS = _importer_dests()

_auth_fn: Callable[..., str] | None = None
_http_fn: Callable[..., dict[str, Any]] | None = None
_secret_fn: Callable[[], dict[str, str]] | None = None


class CatalogImportError(ValueError):
    """User-facing catalog import failure."""


def set_auth_for_tests(fn: Callable[..., str] | None) -> None:
    global _auth_fn
    _auth_fn = fn


def set_http_for_tests(fn: Callable[..., dict[str, Any]] | None) -> None:
    global _http_fn
    _http_fn = fn


def set_secret_for_tests(fn: Callable[[], dict[str, str]] | None) -> None:
    global _secret_fn
    _secret_fn = fn


def import_enabled() -> bool:
    raw = (os.environ.get("BOARD_CATALOG_IMPORT_ENABLED") or "").strip().lower()
    if raw:
        return raw in ("1", "true", "yes", "on")
    return bool(BOARD_CATALOG_IMPORT_ENABLED_DEFAULT)


def admin_api_base() -> str:
    return (os.environ.get("SIUTINDEI_ADMIN_API_BASE_URL") or "").strip().rstrip("/")


def user_pool_id() -> str:
    return (os.environ.get("SIUTINDEI_USER_POOL_ID") or "").strip()


def importer_client_id() -> str:
    return (os.environ.get("BOARD_IMPORTER_CLIENT_ID") or "").strip()


def catalog_manager_id() -> str:
    return (os.environ.get("BOARD_CATALOG_MANAGER_ID") or "").strip()


def configured() -> bool:
    return bool(admin_api_base() and user_pool_id() and importer_client_id() and catalog_manager_id())


def config_gap() -> dict[str, Any] | None:
    missing: list[str] = []
    if not admin_api_base():
        missing.append("SiutindeiAdminApiBaseUrl")
    if not user_pool_id():
        missing.append("SiutindeiUserPoolId")
    if not importer_client_id():
        missing.append("SiutindeiBoardImporterClientId")
    if not catalog_manager_id():
        missing.append("SiutindeiBoardCatalogManagerId")
    if not (os.environ.get("BOARD_IMPORTER_CREDENTIALS_SECRET_ARN") or "").strip() and _secret_fn is None:
        missing.append("importer credentials secret")
    if not missing and import_enabled():
        return None
    reason = "Catalog import is off until the founder sets " + ", ".join(missing or ["SiutindeiBoardCatalogImportEnabled"])
    if not import_enabled():
        reason = "Catalog import kill switch is off (SiutindeiBoardCatalogImportEnabled)."
        if missing:
            reason += " Also missing: " + ", ".join(missing) + "."
    return {"id": "catalog-import", "reason": reason}


def parse_sheet(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise CatalogImportError("deliverable is empty")
    fence = raw
    if "```" in raw:
        parts = raw.split("```")
        for part in parts[1:]:
            body = part.split("\n", 1)[-1] if part.startswith("json") or part.startswith("JSON") else part
            body = body.strip()
            if body.startswith("{"):
                fence = body
                break
    idx = fence.find("{")
    if idx < 0:
        raise CatalogImportError("deliverable has no JSON object")
    try:
        data, _end = json.JSONDecoder().raw_decode(fence[idx:])
    except json.JSONDecodeError as exc:
        raise CatalogImportError(f"deliverable JSON does not parse: {exc}") from exc
    if not isinstance(data, dict):
        raise CatalogImportError("sheet JSON must be an object")
    return data


def _verified_set(org: dict[str, Any]) -> set[str]:
    raw = org.get("verified_fields")
    if not isinstance(raw, list):
        return set()
    return {str(x).strip() for x in raw if str(x).strip()}


def _field_verified(verified: set[str], *names: str) -> bool:
    return any(name in verified for name in names)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


_FREE_RE = re.compile(r"^(free|免費|免费)$", re.I)
_PRICE_RE = re.compile(
    r"(?:(?P<cur>hk\$|hkd)|(?P<dol>\$))\s*(?P<amt>\d{1,5}(?:\.\d{1,2})?)",
    re.I,
)
_PRICE_PREFERRED = ("per class", "per session", "per lesson", "每堂", "每節", "每节")
_PRICE_TRIAL = ("trial", "體驗", "体验", "first class", "試堂", "试堂")
_TIME_RE = re.compile(
    r"(?:(?P<pre>上午|下午|早上|晚上)\s*)?"
    r"(?P<h>\d{1,2})"
    r"(?:[:.：](?P<m>\d{2}))?"
    r"\s*"
    r"(?P<post>a\.?m\.?|p\.?m\.?|時|点|點)?",
    re.I,
)
_RANGE_SEP = re.compile(r"\s*(?:-|–|—|to|至)\s*", re.I)
_DAILY_HOURS_RE = re.compile(
    r"(daily|everyday|every\s+day|mon(?:day)?\s*(?:-|–|—|to)\s*sun(?:day)?|每日|每天)",
    re.I,
)
_CLOSED_RE = re.compile(r"(?:closed(?:\s+on)?|休息)\s*:?\s*(?P<body>[^.;|]*)", re.I)
_DAY_ALTS: tuple[tuple[str, int], ...] = (
    ("sunday", 0),
    ("monday", 1),
    ("tuesday", 2),
    ("wednesday", 3),
    ("thursday", 4),
    ("friday", 5),
    ("saturday", 6),
    ("tues", 2),
    ("thurs", 4),
    ("thur", 4),
    ("sun", 0),
    ("mon", 1),
    ("tue", 2),
    ("wed", 3),
    ("thu", 4),
    ("fri", 5),
    ("sat", 6),
    ("星期日", 0),
    ("星期一", 1),
    ("星期二", 2),
    ("星期三", 3),
    ("星期四", 4),
    ("星期五", 5),
    ("星期六", 6),
    ("週日", 0),
    ("週一", 1),
    ("週二", 2),
    ("週三", 3),
    ("週四", 4),
    ("週五", 5),
    ("週六", 6),
)
_DAY_ALT = "|".join(re.escape(tok) for tok, _ in sorted(_DAY_ALTS, key=lambda kv: -len(kv[0])))
_DAY_TOKEN_RE = re.compile(rf"(?<![a-zA-Z])(?:{_DAY_ALT})(?![a-zA-Z])", re.I)
_DAY_RANGE_RE = re.compile(
    rf"(?<![a-zA-Z])(?P<a>{_DAY_ALT})\s*(?:-|–|—|to|至)\s*(?P<b>{_DAY_ALT})(?![a-zA-Z])",
    re.I,
)
_DAY_INDEX = {tok.casefold(): idx for tok, idx in _DAY_ALTS}


def parse_pricing(free_or_paid: Any, price_note: Any) -> dict[str, Any] | None:
    """Turn verified free/paid + price_note into a siutindei pricing row (no location yet)."""
    status = str(free_or_paid or "").strip()
    note = str(price_note or "").strip()
    if status and _FREE_RE.match(status):
        return {"pricing_type": "free"}
    if note and _FREE_RE.match(note):
        return {"pricing_type": "free"}
    matches = list(_PRICE_RE.finditer(note))
    if not matches:
        return None

    def _score(match: re.Match[str]) -> float:
        window = note[max(0, match.start() - 28) : min(len(note), match.end() + 28)].casefold()
        score = 0.0
        if match.group("cur"):
            score += 3
        if any(token in window for token in _PRICE_PREFERRED):
            score += 5
        if any(token in window for token in _PRICE_TRIAL):
            score -= 4
        try:
            score += float(match.group("amt")) / 1_000_000
        except (TypeError, ValueError):
            pass
        return score

    best = max(matches, key=_score)
    try:
        amount = float(best.group("amt"))
    except (TypeError, ValueError):
        return None
    if amount < 0:
        return None
    return {"pricing_type": "per_class", "amount": amount, "currency": "HKD"}


def _hour_to_hhmm(hour: str, minute: str | None, meridiem: str | None) -> str | None:
    try:
        hours = int(hour)
        mins = int(minute or 0)
    except (TypeError, ValueError):
        return None
    stamp = (meridiem or "").lower().replace(".", "")
    if stamp == "pm" and hours < 12:
        hours += 12
    if stamp == "am" and hours == 12:
        hours = 0
    if hours > 23 or mins > 59:
        return None
    return f"{hours:02d}:{mins:02d}"


def _meridiem_from_time(match: re.Match[str]) -> str | None:
    pre = str(match.group("pre") or "").strip()
    post = str(match.group("post") or "").strip().lower().replace(".", "")
    if pre in ("下午", "晚上") or post == "pm":
        return "pm"
    if pre in ("上午", "早上") or post == "am":
        return "am"
    return None


def _is_clock_match(match: re.Match[str]) -> bool:
    return bool(match.group("m") or match.group("pre") or match.group("post"))


def _clock_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for match in _TIME_RE.finditer(text):
        if not _is_clock_match(match):
            continue
        hhmm = _hour_to_hhmm(match.group("h"), match.group("m"), _meridiem_from_time(match))
        if hhmm:
            spans.append((match.start(), match.end(), hhmm))
    return spans


def _token_day(token: str) -> int | None:
    return _DAY_INDEX.get(str(token or "").casefold())


def _days_from_open_text(text: str) -> set[int]:
    days: set[int] = set()
    used: list[tuple[int, int]] = []
    for match in _DAY_RANGE_RE.finditer(text):
        start = _token_day(match.group("a"))
        end = _token_day(match.group("b"))
        if start is None or end is None:
            continue
        if start <= end:
            days.update(range(start, end + 1))
        else:
            days.update(range(start, 7))
            days.update(range(0, end + 1))
        used.append((match.start(), match.end()))
    for match in _DAY_TOKEN_RE.finditer(text):
        if any(lo <= match.start() < hi for lo, hi in used):
            continue
        index = _token_day(match.group(0))
        if index is not None:
            days.add(index)
    return days


def _parse_hours_days(text: str) -> set[int] | None:
    closed: set[int] = set()
    stripped = text
    for match in _CLOSED_RE.finditer(text):
        closed |= _days_from_open_text(match.group(0))
        stripped = stripped[: match.start()] + " " * (match.end() - match.start()) + stripped[match.end() :]
    if _DAILY_HOURS_RE.search(stripped):
        opened = set(range(7))
    else:
        opened = _days_from_open_text(stripped)
    if not opened and closed:
        opened = set(range(7))
    if not opened:
        return None
    remaining = opened - closed
    return remaining or None


def parse_opening_hours(raw: Any) -> list[dict[str, str]] | None:
    """Parse a verified hours string into Sunday-first weekly_entries, or None."""
    text = str(raw or "").strip()
    if not text or text.lower() == "unverified":
        return None
    clocks = _clock_spans(text)
    start = end = None
    for index in range(len(clocks) - 1):
        _a_start, a_end, start_hh = clocks[index]
        b_start, _b_end, end_hh = clocks[index + 1]
        sep = text[a_end:b_start]
        if _RANGE_SEP.fullmatch(sep):
            start, end = start_hh, end_hh
            break
    if not start or not end:
        return None
    days = _parse_hours_days(text)
    if days is None:
        return None
    return [{"day_of_week": day, "start_time": start, "end_time": end} for day in sorted(days)]


def sheet_quality_issues(sheet: dict[str, Any], *, min_facts: int | None = None) -> list[str]:
    """Return reviewer notes when an org is missing first-class verified facts."""
    needed = BOARD_CATALOG_QUALITY_MIN_FACTS if min_facts is None else int(min_facts)
    orgs = sheet.get("organisations")
    if orgs is None:
        orgs = sheet.get("organizations")
    if not isinstance(orgs, list) or not orgs:
        return ["sheet has no organisations"]
    issues: list[str] = []
    groups = (
        ("address_en", "address"),
        ("opening_hours",),
        ("free_or_paid", "price_note"),
    )
    for org in orgs:
        if not isinstance(org, dict):
            continue
        verified = _verified_set(org)
        name = str(org.get("name_en") or org.get("name") or "organisation")[:80]
        hits = sum(1 for aliases in groups if _field_verified(verified, *aliases))
        if hits < needed:
            issues.append(
                f"{name}: only {hits} of address / opening_hours / free_or_paid (or price_note) "
                f"are in verified_fields (need {needed})"
            )
    return issues


def transform_org(
    org: dict[str, Any],
    *,
    district: str,
    manager_id: str,
    index: int,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not isinstance(org, dict):
        return None, {"index": index, "skipped": True, "reason": "not an object"}
    verified = _verified_set(org)
    skipped_fields: list[str] = []
    copied: list[str] = []
    out: dict[str, Any] = {}

    if not _field_verified(verified, "name_en", "name"):
        return None, {
            "index": index,
            "skipped": True,
            "reason": "name is not in verified_fields",
            "name": str(org.get("name_en") or org.get("name") or "")[:80],
        }
    name = str(org.get("name_en") or org.get("name") or "").strip()
    if not name:
        return None, {"index": index, "skipped": True, "reason": "verified name is blank"}
    out["name"] = name[:200]
    copied.append("name")

    if not manager_id:
        return None, {"index": index, "skipped": True, "reason": "BOARD_CATALOG_MANAGER_ID is not set"}
    out["manager_id"] = manager_id
    copied.append("manager_id")

    area = district or str(org.get("district") or "").strip()
    if not area:
        return None, {"index": index, "skipped": True, "reason": "district / area_name is missing"}
    out["area_name"] = area[:80]
    copied.append("area_name")

    org_type = str(org.get("type") or "").strip().lower()
    # type is the seat's classification (playground|indoor_play|…), not a
    # page fact. Always map it; do not require it in verified_fields.
    if org_type in ("", "unverified"):
        return None, {
            "index": index,
            "skipped": True,
            "reason": "type is missing",
            "name": name[:80],
        }
    category = BOARD_CATALOG_TYPE_TO_CATEGORY.get(org_type) or ""
    if not category:
        return None, {
            "index": index,
            "skipped": True,
            "reason": f"unknown type {org_type or '(blank)'}",
            "name": name[:80],
        }
    out["category_name"] = category
    copied.append("category_name")

    for dest, aliases in _IMPORTER_DESTS:
        verified_aliases = [alias for alias in aliases if alias in verified]
        if not verified_aliases:
            for alias in aliases:
                if org.get(alias) not in (None, "", "unverified"):
                    skipped_fields.append(alias)
            continue
        picked = False
        for alias in verified_aliases:
            value = org.get(alias)
            if value in (None, "", "unverified"):
                continue
            if dest in _NUMERIC_FIELDS:
                number = _as_number(value)
                if number is None:
                    skipped_fields.append(alias)
                    continue
                out[dest] = number
            else:
                out[dest] = str(value).strip()[:500]
            copied.append(dest)
            picked = True
            break
        if picked:
            for alias in aliases:
                if alias not in verified_aliases and org.get(alias) not in (None, "", "unverified"):
                    skipped_fields.append(alias)
            continue
        for alias in aliases:
            if org.get(alias) not in (None, "", "unverified"):
                skipped_fields.append(alias)

    pricing = None
    if _field_verified(verified, "free_or_paid", "price_note"):
        pricing = parse_pricing(org.get("free_or_paid"), org.get("price_note"))
        if pricing is None and org.get("price_note") not in (None, "", "unverified"):
            skipped_fields.append("price_note")
    elif org.get("free_or_paid") not in (None, "", "unverified") or org.get("price_note") not in (
        None,
        "",
        "unverified",
    ):
        skipped_fields.append("price_note" if org.get("price_note") not in (None, "", "unverified") else "free_or_paid")

    weekly = None
    if _field_verified(verified, "opening_hours"):
        weekly = parse_opening_hours(org.get("opening_hours"))
        if weekly is None and org.get("opening_hours") not in (None, "", "unverified"):
            skipped_fields.append("opening_hours")
    elif org.get("opening_hours") not in (None, "", "unverified"):
        skipped_fields.append("opening_hours")

    structured_notes = {"opening_hours", "price_note", "free_or_paid"}
    note_bits: list[str] = []
    for field in _NOTE_FIELDS:
        if field in structured_notes and (
            (field == "opening_hours" and weekly) or (field in ("price_note", "free_or_paid") and pricing)
        ):
            continue
        if _field_verified(verified, field):
            raw = org.get(field)
            if raw not in (None, "", "unverified"):
                note_bits.append(f"{field}={str(raw).strip()[:80]}")
        elif org.get(field) not in (None, "", "unverified"):
            skipped_fields.append(field)
    unverified = org.get("unverified_fields")
    if isinstance(unverified, list) and unverified:
        note_bits.append("unverified=" + ",".join(str(x) for x in unverified[:12]))
    if skipped_fields:
        note_bits.append("skipped=" + ",".join(sorted(set(skipped_fields))))
    out["vetting_note"] = ("; ".join(note_bits) or "verified-fields-only")[:500]
    copied.append("vetting_note")
    if not out.get("source_url") and out.get("website"):
        out["source_url"] = out["website"]

    location_name = str(out.get("address") or out.get("name") or "").strip()
    activity: dict[str, Any] | None = None
    if pricing or weekly:
        activity = {
            "name": out["name"],
            "category_name": out.get("category_name"),
            "vetting_note": out.get("vetting_note"),
        }
        if out.get("description"):
            activity["description"] = out["description"]
        if out.get("source_url"):
            activity["source_url"] = out["source_url"]
        if pricing and location_name:
            row = {"location_name": location_name[:200], **pricing}
            activity["pricing"] = [row]
            copied.append("pricing")
        if weekly and location_name:
            activity["schedules"] = [
                {
                    "location_name": location_name[:200],
                    "timezone": "Asia/Hong_Kong",
                    "weekly_entries": weekly,
                }
            ]
            copied.append("schedules")
        out["activities"] = [activity]

    return out, {
        "index": index,
        "skipped": False,
        "name": out["name"],
        "copiedFields": sorted(set(copied)),
        "skippedFields": sorted(set(skipped_fields)),
    }


def transform_sheet(
    sheet: dict[str, Any],
    *,
    manager_id: str | None = None,
    table: Any = None,
) -> dict[str, Any]:
    district = str(sheet.get("district") or "").strip()
    orgs = sheet.get("organisations")
    if orgs is None:
        orgs = sheet.get("organizations")
    if not isinstance(orgs, list):
        raise CatalogImportError("sheet must include organisations[]")
    mid = (manager_id if manager_id is not None else catalog_manager_id()).strip()
    payload_orgs: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    als_budget = None
    if table is not None:
        import board_geocode

        als_budget = board_geocode.AlsBudget()
    for i, org in enumerate(orgs):
        row, report = transform_org(org if isinstance(org, dict) else {}, district=district, manager_id=mid, index=i)
        reports.append(report)
        if row:
            if table is not None:
                import board_geocode

                board_geocode.fill_org_coords(
                    row,
                    district=district or str(row.get("area_name") or ""),
                    table=table,
                    budget=als_budget,
                )
            payload_orgs.append(row)
    if len(payload_orgs) > BOARD_CATALOG_MAX_ORGS_PER_IMPORT:
        raise CatalogImportError(
            f"import would send {len(payload_orgs)} organisations; max is {BOARD_CATALOG_MAX_ORGS_PER_IMPORT}"
        )
    return {
        "district": district,
        "organizations": payload_orgs,
        "accepted": len(payload_orgs),
        "skipped": sum(1 for r in reports if r.get("skipped")),
        "orgReports": reports,
    }


def local_dry_run(transformed: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    orgs = transformed.get("organizations") or []
    if not orgs:
        errors.append("no organisations with a verified name, a mapped type and a district")
    if not catalog_manager_id() and not any((o or {}).get("manager_id") for o in orgs):
        errors.append("BOARD_CATALOG_MANAGER_ID is not set")
    for org in orgs:
        for req in ("name", "manager_id", "area_name", "category_name"):
            if not str((org or {}).get(req) or "").strip():
                errors.append(f"{org.get('name') or '?'}: missing {req}")
    return {
        "ok": not errors,
        "mode": "local",
        "accepted": transformed.get("accepted") or 0,
        "skipped": transformed.get("skipped") or 0,
        "errors": errors,
        "orgReports": transformed.get("orgReports") or [],
        "payload": {"organizations": orgs},
    }


def is_catalog_sheet(task: dict[str, Any]) -> bool:
    ref = task.get("eventRef") or {}
    return str(ref.get("kind") or "") in CATALOG_SHEET_KINDS


def allows_existing_org_updates(task: dict[str, Any]) -> bool:
    """Enrich sheets re-list imported orgs; updates are the point, not a collision."""
    return str((task.get("eventRef") or {}).get("kind") or "") == CATALOG_ENRICH_KIND


def require_catalog_sheet(task: dict[str, Any]) -> None:
    if not is_catalog_sheet(task):
        raise CatalogImportError("task is not a catalog sheet")


def require_importable_task(task: dict[str, Any], *, force: bool = False) -> None:
    require_catalog_sheet(task)
    status = str(task.get("status") or "")
    phase = str(task.get("importPhase") or "")
    imported_at = task.get("importedAt")
    if imported_at and not force:
        raise CatalogImportError(f"already imported at {imported_at}")
    if status == "awaiting_import":
        if phase == "collision" and not force and not allows_existing_org_updates(task):
            raise CatalogImportError("import would update existing organisations; pass force to proceed")
        return
    if status == "needs_owner" and phase in ("collision", "rejected", "partial", "failed", "invalid"):
        if phase == "collision" and not force and not allows_existing_org_updates(task):
            raise CatalogImportError("import would update existing organisations; pass force to proceed")
        return
    if status == "delivered" and force:
        return
    raise CatalogImportError("catalog import requires a sheet waiting to import")


def _safe_url(url: str) -> str:
    """Host + path only — never include a presigned query string."""
    parts = urlsplit(url or "")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _load_credentials() -> dict[str, str]:
    if _secret_fn is not None:
        return _secret_fn()
    arn = (os.environ.get("BOARD_IMPORTER_CREDENTIALS_SECRET_ARN") or "").strip()
    if not arn:
        raise CatalogImportError("importer credentials secret is not configured")
    raw = read_secret_raw(_get_secretsmanager_client(), arn, what="importer credentials")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CatalogImportError("importer credentials secret must be JSON {username, password}") from exc
    if not isinstance(payload, dict):
        raise CatalogImportError("importer credentials secret must be a JSON object")
    username = str(payload.get("username") or payload.get("user") or "").strip()
    password = str(payload.get("password") or "").strip()
    if not username or not password or username == "replace-me":
        raise CatalogImportError("importer credentials secret still has the dummy username/password")
    return {"username": username, "password": password}


def _id_token() -> str:
    if _auth_fn is not None:
        creds = _load_credentials()
        return _auth_fn(creds["username"], creds["password"])
    pool = user_pool_id()
    client_id = importer_client_id()
    if not pool or not client_id:
        raise CatalogImportError("SiutindeiUserPoolId / SiutindeiBoardImporterClientId are not set")
    creds = _load_credentials()
    import boto3
    from botocore.config import Config

    resp = boto3.client(
        "cognito-idp",
        config=Config(
            connect_timeout=2,
            read_timeout=_COGNITO_TIMEOUT,
            retries={"max_attempts": 1},
        ),
    ).admin_initiate_auth(
        UserPoolId=pool,
        ClientId=client_id,
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": creds["username"], "PASSWORD": creds["password"]},
    )
    token = str(((resp.get("AuthenticationResult") or {}).get("IdToken") or "")).strip()
    if not token:
        raise CatalogImportError("Cognito AdminInitiateAuth did not return an IdToken")
    return token


def _http(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    if _http_fn is not None:
        return _http_fn(method, url, headers or {}, body)
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = int(getattr(resp, "status", 200) or 200)
            text = raw.decode("utf-8", errors="replace") if raw else ""
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise CatalogImportError(
            f"siutindei admin {method} {_safe_url(url)} failed: {exc.code} {err_body[:240]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise CatalogImportError(f"siutindei admin {method} {_safe_url(url)} failed: {exc.reason}") from exc
    parsed: Any = {}
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"raw": text[:500]}
    if not isinstance(parsed, dict):
        parsed = {"data": parsed}
    parsed.setdefault("status", status)
    return parsed


def _presign_and_put(orgs: list[dict[str, Any]], token: str, *, filename: str, timeout: int = _IMPORT_HTTP_TIMEOUT) -> str:
    base = admin_api_base()
    if not base:
        raise CatalogImportError("SiutindeiAdminApiBaseUrl is not set")
    blob = json.dumps({"organizations": orgs}).encode("utf-8")
    presign = _http(
        "POST",
        urljoin(base + "/", "admin/imports/presign"),
        headers=_auth_headers(token),
        body=json.dumps({"file_name": filename, "content_type": "application/json"}).encode("utf-8"),
        timeout=timeout,
    )
    upload_url = str(presign.get("upload_url") or presign.get("url") or "").strip()
    object_key = str(presign.get("object_key") or presign.get("key") or "").strip()
    if not upload_url or not object_key:
        raise CatalogImportError("presign did not return upload_url and object_key")
    put_headers = {"Content-Type": "application/json"}
    extra = presign.get("headers")
    if isinstance(extra, dict):
        put_headers.update({str(k): str(v) for k, v in extra.items()})
    _http("PUT", upload_url, headers=put_headers, body=blob, timeout=timeout)
    return object_key


def _imports_post(token: str, body: dict[str, Any], *, timeout: int = _IMPORT_HTTP_TIMEOUT) -> dict[str, Any]:
    base = admin_api_base()
    if not base:
        raise CatalogImportError("SiutindeiAdminApiBaseUrl is not set")
    return _http(
        "POST",
        urljoin(base + "/", "admin/imports"),
        headers=_auth_headers(token),
        body=json.dumps(body).encode("utf-8"),
        timeout=timeout,
    )


def _as_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _org_counts(resp: dict[str, Any]) -> dict[str, int]:
    """Read siutindei ``summary.organizations`` counts, with flat fallbacks."""
    summary = resp.get("summary") if isinstance(resp.get("summary"), dict) else {}
    orgs = summary.get("organizations") if isinstance(summary.get("organizations"), dict) else {}
    created = _as_count(orgs.get("created") if orgs else None)
    updated = _as_count(orgs.get("updated") if orgs else None)
    skipped = _as_count(orgs.get("skipped") if orgs else None)
    if not created:
        for key in ("created", "imported", "accepted", "upserted", "count"):
            created = _as_count(summary.get(key) if summary else None) or _as_count(resp.get(key))
            if created:
                break
    if not updated:
        updated = _as_count(summary.get("updated") if summary else None) or _as_count(resp.get("updated"))
    if not skipped:
        skipped = _as_count(summary.get("skipped") if summary else None) or _as_count(resp.get("skipped"))
    return {
        "created": created,
        "updated": updated,
        "failed": _failed_row_count(resp, summary),
        "skipped": skipped,
    }


def _failed_row_count(resp: dict[str, Any], summary: dict[str, Any] | None = None) -> int:
    """Count failed importer rows across orgs, venues and activities.

    Siutindei returns per-type counters. A sheet that creates organisations
    but rejects every activity used to look clean because only
    ``summary.organizations.failed`` was read.
    """
    packed = summary if isinstance(summary, dict) else (
        resp.get("summary") if isinstance(resp.get("summary"), dict) else {}
    )
    total = 0
    for key in ("organizations", "locations", "activities", "pricing", "schedules"):
        counts = packed.get(key) if isinstance(packed.get(key), dict) else {}
        total += _as_count(counts.get("failed") if counts else None)
    if total:
        return total
    from_rows = sum(
        1
        for row in _importer_results(resp)
        if str(row.get("status") or "").lower() == "failed"
    )
    if from_rows:
        return from_rows
    return _as_count(packed.get("failed") if packed else None) or _as_count(resp.get("failed"))


def _importer_results(resp: dict[str, Any]) -> list[dict[str, Any]]:
    raw = resp.get("results")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if isinstance(row, dict):
            out.append(row)
    return out


def _org_result_names(results: list[dict[str, Any]], status: str) -> list[str]:
    names: list[str] = []
    for row in results:
        row_type = str(row.get("type") or "").lower()
        if row_type and row_type not in ("organizations", "organization", "organisations"):
            continue
        if str(row.get("status") or "").lower() != status:
            continue
        name = str(row.get("key") or row.get("name") or "").strip()
        if name:
            names.append(name[:80])
    return names


def _importer_accepted(resp: dict[str, Any]) -> int:
    """Count created+updated orgs, venues and activities.

    A matching-manager reimport skips every organisation and only
    creates the missing activities; those still count as accepted.
    """
    packed = resp.get("summary") if isinstance(resp.get("summary"), dict) else {}
    total = 0
    for key in ("organizations", "locations", "activities"):
        counts = packed.get(key) if isinstance(packed.get(key), dict) else {}
        total += _as_count(counts.get("created") if counts else None)
        total += _as_count(counts.get("updated") if counts else None)
    if total:
        return total
    counts = _org_counts(resp)
    return counts["created"] + counts["updated"]


def _remote_dry_run(payload: dict[str, Any], token: str) -> dict[str, Any]:
    orgs = payload.get("organizations") or []
    object_key = _presign_and_put(orgs, token, filename="board-catalog-dry-run.json", timeout=_PREVIEW_HTTP_TIMEOUT)
    resp = _imports_post(token, {"object_key": object_key, "dry_run": True}, timeout=_PREVIEW_HTTP_TIMEOUT)
    counts = _org_counts(resp)
    results = _importer_results(resp)
    would_update = _org_result_names(results, "updated")
    return {
        "ok": counts["failed"] == 0,
        "mode": "remote",
        "objectKey": object_key,
        "response": resp,
        "summary": counts,
        "results": results,
        "fileWarnings": list(resp.get("file_warnings") or []),
        "wouldUpdate": would_update,
        "payload": {"organizations": orgs},
    }


def _run_remote_import(payload: dict[str, Any], token: str) -> dict[str, Any]:
    orgs = payload.get("organizations") or []
    object_key = _presign_and_put(orgs, token, filename="board-catalog.json", timeout=_IMPORT_HTTP_TIMEOUT)
    imported = _imports_post(token, {"object_key": object_key}, timeout=_IMPORT_HTTP_TIMEOUT)
    counts = _org_counts(imported)
    results = _importer_results(imported)
    sent = len(orgs)
    return {
        "ok": counts["failed"] == 0,
        "mode": "remote",
        "objectKey": object_key,
        "response": imported,
        "summary": counts,
        "results": results,
        "wouldUpdate": _org_result_names(results, "updated"),
        "sent": sent,
        "accepted": _importer_accepted(imported),
    }


def preview_from_text(text: str, *, remote: bool = False, table: Any = None) -> dict[str, Any]:
    sheet = parse_sheet(text)
    transformed = transform_sheet(sheet, table=table)
    local = local_dry_run(transformed)
    out: dict[str, Any] = {
        "ok": local["ok"],
        "district": transformed.get("district") or "",
        "importEnabled": import_enabled(),
        "configured": configured(),
        "dryRun": local,
        "payload": local["payload"],
    }
    if remote and configured() and local["ok"]:
        try:
            token = _id_token()
            remote_dry = _remote_dry_run(transformed, token)
            out["dryRun"] = {**local, **remote_dry, "local": local}
            out["ok"] = bool(local["ok"] and remote_dry.get("ok"))
        except Exception as exc:
            out["dryRun"] = {**local, "remoteError": str(exc)[:300]}
    return out


def _task_text(table: Any, task: dict[str, Any], explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit
    import board_staff

    return board_staff.read_deliverable(task, limit=12000)


def preview_task(table: Any, task: dict[str, Any], *, sheet_text: str | None = None, remote: bool = False) -> dict[str, Any]:
    require_catalog_sheet(task)
    text = _task_text(table, task, sheet_text)
    preview = preview_from_text(text, remote=remote, table=table)
    preview["taskId"] = task.get("taskId")
    ref = task.get("eventRef") or {}
    if not preview.get("district") and ref.get("district"):
        preview["district"] = ref.get("district")
    return preview


def _now_iso() -> str:
    try:
        import board_store

        return board_store.now_iso()
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_questions(task: dict[str, Any], lines: list[str]) -> None:
    existing = [str(q) for q in (task.get("openQuestions") or []) if q]
    for line in lines:
        text = str(line or "").strip()[:300]
        if text and text not in existing:
            existing.append(text)
    task["openQuestions"] = existing[:20]


def _clear_handoff_ttl(task: dict[str, Any]) -> None:
    task["finishedAt"] = None
    task.pop("expiresAt", None)


def _park_needs_owner(table: Any, task: dict[str, Any], now: str, *, phase: str, questions: list[str]) -> dict[str, Any]:
    task["status"] = "needs_owner"
    task["importPhase"] = phase
    task["acceptedAt"] = task.get("acceptedAt") or now
    task["lastValidatedAt"] = now
    task["updatedAt"] = now
    _clear_handoff_ttl(task)
    _append_questions(task, questions)
    if table is not None:
        import board_store

        board_store.put_task(table, task)
        try:
            import board_staff

            board_staff.note_parent_if_child_needs_owner(table, task)
        except Exception:
            pass
    return task


def _set_awaiting(table: Any, task: dict[str, Any], now: str, *, phase: str) -> dict[str, Any]:
    task["status"] = "awaiting_import"
    task["importPhase"] = phase
    task["acceptedAt"] = task.get("acceptedAt") or now
    task["lastValidatedAt"] = now
    task["updatedAt"] = now
    _clear_handoff_ttl(task)
    if table is not None:
        import board_store

        board_store.put_task(table, task)
    return task


def _save_task(table: Any, task: dict[str, Any]) -> None:
    if table is None:
        return
    try:
        import board_store

        board_store.put_task(table, task)
    except Exception as exc:
        _log_event("warning", tag="board_catalog_import_save_failed", error=str(exc)[:200])


def _preview_dry(preview: Any) -> dict[str, Any]:
    dry = preview.get("dryRun") if isinstance(preview, dict) else None
    return dry if isinstance(dry, dict) else {}


def _preview_would_update(dry: dict[str, Any]) -> list[str]:
    names = [str(n) for n in (dry.get("wouldUpdate") or []) if n]
    if names:
        return names
    if (dry.get("summary") or {}).get("updated"):
        return _org_result_names(dry.get("results") or [], "updated")
    return []


def _in_import_handoff(task: dict[str, Any]) -> bool:
    if task.get("importedAt") or task.get("importSkipped"):
        return False
    status = str(task.get("status") or "")
    if status == "awaiting_import":
        return True
    return status == "needs_owner" and bool(task.get("importPhase"))


def _fresh_remote_preview(task: dict[str, Any], now: str) -> bool:
    dry = _preview_dry(task.get("importPreview"))
    if dry.get("mode") != "remote" or dry.get("remoteError"):
        return False
    return not _revalidate_due(task, now)


def _apply_preview_outcome(
    table: Any,
    task: dict[str, Any],
    preview: dict[str, Any],
    now: str,
    *,
    promote: bool,
) -> dict[str, Any]:
    """Store a dry-run and, when promote=True, park / validate like accept."""
    task["importPreview"] = preview
    task["lastValidatedAt"] = now
    task["updatedAt"] = now
    dry = _preview_dry(preview)
    remote_ok = dry.get("mode") == "remote" and not dry.get("remoteError")
    if remote_ok:
        task["importError"] = ""
    elif dry.get("remoteError"):
        task["importError"] = str(dry.get("remoteError"))[:300]
    if not promote:
        if table is not None:
            import board_store

            board_store.put_task(table, task)
        return task
    if not preview.get("ok") and not dry.get("remoteError"):
        errors = list(dry.get("errors") or [])
        if preview.get("error"):
            errors.append(str(preview.get("error")))
        return _park_needs_owner(
            table,
            task,
            now,
            phase="invalid",
            questions=errors or ["catalog sheet failed local dry-run"],
        )
    if dry.get("mode") == "remote":
        would_update = _preview_would_update(dry)
        updating = bool(would_update or (dry.get("summary") or {}).get("updated"))
        if updating and not allows_existing_org_updates(task):
            names = ", ".join(would_update) or "existing organisation"
            return _park_needs_owner(
                table,
                task,
                now,
                phase="collision",
                questions=[f"siutindei would update existing organisations: {names}"[:300]],
            )
        if not dry.get("ok"):
            failed = (dry.get("summary") or {}).get("failed") or 0
            return _park_needs_owner(
                table,
                task,
                now,
                phase="rejected",
                questions=[f"siutindei dry-run rejected {failed} organisation(s)"] + _result_errors(dry.get("results") or []),
            )
        return _set_awaiting(table, task, now, phase="validated")
    if dry.get("remoteError"):
        return _set_awaiting(table, task, now, phase="pending")
    # Local-only: do not un-park a collision or downgrade a validated sheet.
    if _in_import_handoff(task) and task.get("importPhase"):
        if table is not None:
            import board_store

            board_store.put_task(table, task)
        return task
    return _set_awaiting(table, task, now, phase="pending")


def accept_catalog_task(table: Any, task: dict[str, Any], now: str) -> dict[str, Any]:
    """Accept-hook: validate the sheet. Never imports. Never marks delivered."""
    require_catalog_sheet(task)
    try:
        preview = preview_task(table, task, remote=configured())
    except CatalogImportError as exc:
        preview = {"ok": False, "error": str(exc)[:300], "taskId": task.get("taskId")}
    except Exception as exc:
        preview = {"ok": False, "error": str(exc)[:300], "taskId": task.get("taskId")}
    return _apply_preview_outcome(table, task, preview, now, promote=True)


def attach_accept_preview(table: Any, task: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible local preview. Prefer ``accept_catalog_task``."""
    try:
        preview = preview_task(table, task, remote=False)
    except CatalogImportError as exc:
        preview = {"ok": False, "error": str(exc)[:300], "taskId": task.get("taskId")}
    except Exception as exc:
        preview = {"ok": False, "error": str(exc)[:300], "taskId": task.get("taskId")}
    task["importPreview"] = preview
    return preview


def _result_errors(results: list[Any]) -> list[str]:
    lines: list[str] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        errors = row.get("errors") or []
        if not errors:
            continue
        key = str(row.get("key") or row.get("name") or "?")[:80]
        for err in errors[:3]:
            if isinstance(err, dict):
                msg = str(err.get("message") or err)[:160]
            else:
                msg = str(err)[:160]
            lines.append(f"{key}: {msg}")
    return lines[:12]


_IMPORT_PARK_PHASES = ("collision", "rejected", "partial", "failed", "invalid")


def _payload_orgs(task: dict[str, Any], payload: dict[str, Any], *, force: bool) -> list[dict[str, Any]]:
    orgs = [o for o in (payload.get("organizations") or []) if isinstance(o, dict)]
    if force or str(task.get("importPhase") or "") != "partial":
        return orgs
    failed = set(_org_result_names((task.get("importResult") or {}).get("results") or [], "failed"))
    if not failed:
        return orgs
    return [o for o in orgs if str(o.get("name") or "") in failed]


def _drop_open_hold(table: Any, task_id: str, *, reason: str) -> None:
    if table is None or not task_id:
        return
    hold = _open_catalog_hold(table, task_id)
    if not hold:
        return
    hold_id = str(hold.get("holdId") or "")
    if not hold_id:
        return
    import board_store

    if not board_store.claim_hold(table, hold_id, from_status="scheduled", to_status="vetoed"):
        return
    latest = board_store.get_hold(table, hold_id) or hold
    now = board_store.now_iso()
    latest["status"] = "vetoed"
    latest["vetoedAt"] = now
    latest["vetoBy"] = "catalog"
    latest["vetoReason"] = reason[:400]
    latest["updatedAt"] = now
    board_store.put_hold(table, latest)


def _catalog_tasks(table: Any, status: str) -> list[dict[str, Any]]:
    import board_store

    return [t for t in board_store.list_all_tasks(table, status) if is_catalog_sheet(t)]


def _deliver_imported(table: Any, task: dict[str, Any], now: str) -> None:
    if table is not None:
        try:
            import board_staff

            board_staff._mark_delivered(table, task, now)
        except Exception as exc:
            _save_task(table, task)
            _log_event("warning", tag="board_catalog_import_deliver_failed", error=str(exc)[:200])
    else:
        task["status"] = "delivered"
        task["finishedAt"] = now


def run_import(table: Any, task: dict[str, Any], *, force: bool = False, live_after_refresh: bool = True) -> dict[str, Any]:
    if not import_enabled():
        raise CatalogImportError("catalog import is switched off (SiutindeiBoardCatalogImportEnabled)")
    if not configured():
        raise CatalogImportError("catalog import is not configured (admin API, user pool, client, manager id)")
    require_importable_task(task, force=force)
    now = _now_iso()
    task_id = str(task.get("taskId") or "")
    if not force:
        stored = task.get("importPreview") if isinstance(task.get("importPreview"), dict) else {}
        stored_dry = _preview_dry(stored)
        if (
            _preview_would_update(stored_dry) or (stored_dry.get("summary") or {}).get("updated")
        ) and not allows_existing_org_updates(task):
            _apply_preview_outcome(table, task, stored, now, promote=True)
            return {"ok": False, "collision": True, "taskId": task_id, "preview": stored, "task": task}
        if not _fresh_remote_preview(task, now):
            preview = preview_task(table, task, remote=configured())
            _apply_preview_outcome(table, task, preview, now, promote=True)
            if str(task.get("importPhase") or "") != "validated" or str(task.get("status") or "") != "awaiting_import":
                return {"ok": False, "previewed": True, "taskId": task_id, "preview": preview, "task": task}
            if not live_after_refresh:
                return {"ok": False, "previewed": True, "taskId": task_id, "preview": preview, "task": task}
    preview = preview_task(table, task, remote=False)
    if not preview.get("ok"):
        errors = (preview.get("dryRun") or {}).get("errors") or ["sheet failed local dry-run"]
        raise CatalogImportError("; ".join(str(e) for e in errors)[:300])
    payload = dict(preview.get("payload") or {})
    payload["organizations"] = _payload_orgs(task, payload, force=force)
    preview = {**preview, "payload": payload}
    try:
        token = _id_token()
        imported = _run_remote_import(payload, token)
    except CatalogImportError:
        task["importAttempts"] = int(task.get("importAttempts") or 0) + 1
        task["lastImportAttemptAt"] = now
        task["importPhase"] = "failed"
        task["importError"] = "siutindei import request failed"
        task["updatedAt"] = now
        _save_task(table, task)
        raise
    task["importAttempts"] = int(task.get("importAttempts") or 0) + 1
    task["lastImportAttemptAt"] = now
    task["importPreview"] = preview
    summary = imported.get("summary") or {}
    result = {
        "ok": bool(imported.get("ok")),
        "objectKey": imported.get("objectKey"),
        "sent": imported.get("sent"),
        "accepted": imported.get("accepted"),
        "created": summary.get("created"),
        "updated": summary.get("updated"),
        "failed": summary.get("failed"),
        "summary": summary,
        "results": imported.get("results") or [],
        "at": now,
    }
    task_id = str(task.get("taskId") or "")
    if summary.get("failed"):
        task["importResult"] = {**result, "partial": True}
        task["importError"] = f"siutindei rejected {summary.get('failed')} row(s)"
        _park_needs_owner(
            table,
            task,
            now,
            phase="partial",
            questions=[task["importError"]] + _result_errors(imported.get("results") or []),
        )
        return {"ok": False, "partial": True, "taskId": task_id, "import": imported, "preview": preview, "task": task}
    if summary.get("updated") and not force:
        names = imported.get("wouldUpdate") or _org_result_names(imported.get("results") or [], "updated")
        label = ", ".join(str(n) for n in names) or "existing organisation"
        task["importResult"] = result
        _park_needs_owner(
            table,
            task,
            now,
            phase="collision",
            questions=[f"siutindei updated existing organisations: {label}"[:300]],
        )
        return {
            "ok": False,
            "collision": True,
            "taskId": task_id,
            "import": imported,
            "preview": preview,
            "task": task,
        }
    task["importedAt"] = now
    task["importResult"] = result
    task["importPhase"] = "imported"
    task["importError"] = ""
    _drop_open_hold(table, task_id, reason="imported")
    _deliver_imported(table, task, now)
    return {"ok": True, "taskId": task_id, "import": imported, "preview": preview}


def skip_import(table: Any, task: dict[str, Any]) -> dict[str, Any]:
    require_catalog_sheet(task)
    if task.get("importedAt"):
        raise CatalogImportError(f"already imported at {task.get('importedAt')}")
    status = str(task.get("status") or "")
    if status not in ("awaiting_import", "needs_owner"):
        raise CatalogImportError("skip requires a catalog sheet waiting to import")
    now = _now_iso()
    task["importSkipped"] = True
    task["importPhase"] = "skipped"
    task["updatedAt"] = now
    _drop_open_hold(table, str(task.get("taskId") or ""), reason="skipped")
    import board_staff

    delivered = board_staff._mark_delivered(table, task, now)
    return {"ok": True, "skipped": True, "task": delivered}


def requeue_for_import(table: Any, task: dict[str, Any]) -> dict[str, Any]:
    require_catalog_sheet(task)
    status = str(task.get("status") or "")
    phase = str(task.get("importPhase") or "")
    if status != "needs_owner" or phase not in ("collision", "rejected", "partial", "failed", "invalid"):
        raise CatalogImportError("requeue requires a catalog sheet parked after an import check")
    now = _now_iso()
    task["importError"] = ""
    task["openQuestions"] = []
    task["importPhase"] = "pending"
    _clear_handoff_ttl(task)
    _drop_open_hold(table, str(task.get("taskId") or ""), reason="requeued")
    updated = _set_awaiting(table, task, now, phase="pending")
    return {"ok": True, "task": updated, "taskId": updated.get("taskId")}


def op_preview(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    task_id = str(args.get("taskId") or "").strip()
    if not task_id:
        raise CatalogImportError("taskId is required")
    import board_store

    task = board_store.get_task(ctx.table, task_id)
    if not task:
        raise CatalogImportError("Task not found")
    return preview_task(ctx.table, task, sheet_text=str(args.get("sheet") or "") or None, remote=False)


def op_dry_run(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    task_id = str(args.get("taskId") or "").strip()
    if not task_id:
        raise CatalogImportError("taskId is required")
    import board_store

    task = board_store.get_task(ctx.table, task_id)
    if not task:
        raise CatalogImportError("Task not found")
    return preview_task(ctx.table, task, sheet_text=str(args.get("sheet") or "") or None, remote=True)


def op_import(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    task_id = str(args.get("taskId") or "").strip()
    if not task_id:
        raise CatalogImportError("taskId is required")
    import board_store

    task = board_store.get_task(ctx.table, task_id)
    if not task:
        raise CatalogImportError("Task not found")
    return run_import(ctx.table, task)


def _wants_remote(body: dict[str, Any]) -> bool:
    value = body.get("remote", True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return value is not False and value != 0


def owner_preview(table: Any, body: dict[str, Any]) -> dict[str, Any]:
    task_id = str(body.get("taskId") or "").strip()
    if not task_id:
        raise CatalogImportError("taskId is required")
    import board_store

    task = board_store.get_task(table, task_id)
    if not task:
        raise CatalogImportError("Task not found")
    # Owner Preview import is a siutindei dry-run. Pass remote=false for local-only.
    preview = preview_task(
        table,
        task,
        sheet_text=str(body.get("sheet") or "") or None,
        remote=_wants_remote(body),
    )
    _apply_preview_outcome(table, task, preview, _now_iso(), promote=_in_import_handoff(task))
    return preview


def owner_import(table: Any, body: dict[str, Any]) -> dict[str, Any]:
    task_id = str(body.get("taskId") or "").strip()
    if not task_id:
        raise CatalogImportError("taskId is required")
    import board_store

    task = board_store.get_task(table, task_id)
    if not task:
        raise CatalogImportError("Task not found")
    # HTTP API is 30s: refresh a stale dry-run in this request, live-import on the next click.
    return run_import(table, task, force=bool(body.get("force")), live_after_refresh=False)


def owner_skip(table: Any, body: dict[str, Any]) -> dict[str, Any]:
    task_id = str(body.get("taskId") or "").strip()
    if not task_id:
        raise CatalogImportError("taskId is required")
    import board_store

    task = board_store.get_task(table, task_id)
    if not task:
        raise CatalogImportError("Task not found")
    return skip_import(table, task)


def owner_requeue(table: Any, body: dict[str, Any]) -> dict[str, Any]:
    task_id = str(body.get("taskId") or "").strip()
    if not task_id:
        raise CatalogImportError("taskId is required")
    import board_store

    task = board_store.get_task(table, task_id)
    if not task:
        raise CatalogImportError("Task not found")
    return requeue_for_import(table, task)


def _task_row(task: dict[str, Any]) -> dict[str, Any]:
    ref = task.get("eventRef") or {}
    preview = task.get("importPreview") or {}
    return {
        "taskId": task.get("taskId"),
        "district": ref.get("district") or preview.get("district") or "",
        "ok": bool(preview.get("ok")),
        "accepted": (preview.get("dryRun") or {}).get("accepted") or 0,
        "phase": task.get("importPhase") or "",
        "status": task.get("status") or "",
    }


def ready_sheets(table: Any) -> list[dict[str, Any]]:
    """Sheets waiting to import (digest)."""
    out: list[dict[str, Any]] = []
    for task in _catalog_tasks(table, "awaiting_import"):
        if task.get("importedAt"):
            continue
        out.append(_task_row(task))
    return out[:20]


def catalog_headline(table: Any) -> dict[str, Any]:
    awaiting = [t for t in _catalog_tasks(table, "awaiting_import") if not t.get("importedAt")]
    parked = [
        t
        for t in _catalog_tasks(table, "needs_owner")
        if t.get("importPhase") in _IMPORT_PARK_PHASES and not t.get("importedAt")
    ]
    validated = [t for t in awaiting if str(t.get("importPhase") or "") == "validated"]
    pending = [t for t in awaiting if str(t.get("importPhase") or "") != "validated"]
    collisions = [t for t in parked if str(t.get("importPhase") or "") == "collision"]
    rejected = [t for t in parked if str(t.get("importPhase") or "") in ("rejected", "partial", "invalid", "failed")]
    coverage = catalog_coverage(table)
    return {
        "ready": len(awaiting),
        "validated": len(validated),
        "pending": len(pending),
        "collisions": len(collisions),
        "rejected": len(rejected),
        "importedDistricts": coverage.get("importedDistricts") or 0,
        "completeDistricts": coverage.get("completeDistricts") or 0,
        "nextDistrict": coverage.get("nextDistrict") or "",
        "failedActivityRows": coverage.get("failedActivityRows") or 0,
        "sheets": [_task_row(t) for t in awaiting[:20]],
    }


def catalog_coverage(table: Any) -> dict[str, Any]:
    """Owner-facing district coverage for the daily review Catalog line."""
    import board_catalog
    from contract_constants import BOARD_CATALOG_DISTRICTS

    imported = board_catalog.claimed_district_ids(table)
    scores = board_catalog.district_completeness(table)
    complete = 0
    for row in BOARD_CATALOG_DISTRICTS:
        if not isinstance(row, dict):
            continue
        did = str(row.get("id") or "").strip().lower()
        name = str(row.get("name") or "")
        if did not in imported:
            continue
        score = scores.get(name)
        if score is not None and score >= 0.5:
            complete += 1
    nxt = board_catalog.next_district(table, enforce_completeness_gate=False)
    failed = 0
    for status in ("delivered", "awaiting_import", "needs_owner"):
        for task in _catalog_tasks(table, status):
            result = task.get("importResult") if isinstance(task.get("importResult"), dict) else {}
            for row in result.get("results") or []:
                if not isinstance(row, dict):
                    continue
                if str(row.get("type") or "").lower() == "activities" and str(row.get("status") or "").lower() == "failed":
                    failed += 1
    return {
        "importedDistricts": len(imported),
        "completeDistricts": complete,
        "nextDistrict": str((nxt or {}).get("name") or ""),
        "failedActivityRows": failed,
    }


def auto_import_enabled(settings: dict[str, Any] | None) -> bool:
    catalog = (settings or {}).get("catalog") if isinstance(settings, dict) else None
    if isinstance(catalog, dict) and "autoImport" in catalog:
        return bool(catalog.get("autoImport"))
    return bool(BOARD_CATALOG_AUTO_IMPORT_DEFAULT)


def awaiting_import_count(table: Any) -> int:
    awaiting = [t for t in _catalog_tasks(table, "awaiting_import") if not t.get("importedAt")]
    parked = [
        t
        for t in _catalog_tasks(table, "needs_owner")
        if t.get("importPhase") in _IMPORT_PARK_PHASES and not t.get("importedAt")
    ]
    return len(awaiting) + len(parked)


def at_awaiting_cap(table: Any) -> bool:
    return awaiting_import_count(table) >= BOARD_CATALOG_MAX_AWAITING_IMPORT


def _open_catalog_hold(table: Any, task_id: str) -> dict[str, Any] | None:
    import board_store

    for hold in board_store.list_holds(table, "scheduled", limit=400):
        args = hold.get("arguments") or {}
        hid = str(args.get("taskId") or hold.get("taskId") or "")
        if str(hold.get("op") or "") == "catalog_import" and hid == task_id:
            return hold
    return None


def _schedule_or_run(table: Any, settings: dict[str, Any], task: dict[str, Any]) -> str:
    import board_holds
    import board_tools

    task_id = str(task.get("taskId") or "")
    if not task_id:
        return "skip"
    if _open_catalog_hold(table, task_id):
        return "held"
    hours = board_holds.hold_hours(table, settings, "catalog_import", "catalog_import")
    if hours <= 0:
        hours = 24
    op = board_tools.REGISTRY.get("catalog_import")
    if op is None:
        return "skip"
    ctx = board_tools.ToolContext(
        table=table,
        settings=settings,
        persona_id="",
        display_name="catalog sweep",
        kind="internal",
        actor="internal",
        task_id=task_id,
        internal=True,
    )
    district = str((task.get("eventRef") or {}).get("district") or "")
    board_holds.create_hold(
        ctx,
        op,
        {"taskId": task_id, "reason": "auto-import sweep"},
        action_class="catalog_import",
        class_key="catalog_import",
        hours=hours,
        summary=f"Import catalog sheet{f' ({district})' if district else ''}",
    )
    return "scheduled"


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _revalidate_due(task: dict[str, Any], now: str) -> bool:
    last = str(task.get("lastValidatedAt") or "")
    if not last:
        return True
    try:
        then = _parse_iso(last)
        now_dt = _parse_iso(now)
        return then < now_dt - timedelta(hours=1)
    except ValueError:
        return True


def handle_tick(table: Any, settings: dict[str, Any]) -> dict[str, Any]:
    """Backfill, re-validate pending sheets, and schedule auto-import holds."""
    import board_store

    now = board_store.now_iso()
    backfilled = 0
    for task in _catalog_tasks(table, "delivered"):
        if task.get("importedAt") or task.get("importSkipped"):
            continue
        accept_catalog_task(table, task, now)
        backfilled += 1
    revalidated = 0
    for task in _catalog_tasks(table, "awaiting_import"):
        if str(task.get("importPhase") or "") != "pending":
            continue
        if not _revalidate_due(task, now):
            continue
        accept_catalog_task(table, task, now)
        revalidated += 1
    scheduled = 0
    imported = 0
    if auto_import_enabled(settings) and import_enabled() and configured():
        for task in _catalog_tasks(table, "awaiting_import"):
            latest = board_store.get_task(table, str(task.get("taskId") or "")) or task
            if str(latest.get("importPhase") or "") != "validated":
                continue
            try:
                action = _schedule_or_run(table, settings, latest)
            except CatalogImportError as exc:
                _log_event("warning", tag="board_catalog_import_sweep_failed", error=str(exc)[:200])
                continue
            if action == "scheduled":
                scheduled += 1
            elif action == "imported":
                imported += 1
    return {
        "ok": True,
        "backfilled": backfilled,
        "revalidated": revalidated,
        "scheduled": scheduled,
        "imported": imported,
    }
