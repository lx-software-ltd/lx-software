"""Ground catalog verified_fields in pages this task actually fetched."""

from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib.parse import urlparse

import board_crawl
import board_store

_EVIDENCE_FIELDS = {
    "address": "address",
    "address_en": "address",
    "phone": "phone",
    "opening_hours": "hours",
    "price_note": "price",
    "free_or_paid": "price",
}
_STREET_SKIP = frozenset({"the", "and", "hong", "kong"})
_UNIT_WORDS = frozenset({"shop", "flat", "unit", "room", "floor", "block", "podium", "ground", "level", "tower"})
_CLOCK_RE = re.compile(r"\d{1,2}:\d{2}")
_AMPM_RE = re.compile(r"\d{1,2}\s*(?:am|pm)", re.I)
_PRICE_RE = re.compile(r"(?:hk\$|hkd|usd|\$|£|€)\s*(\d{1,6})|(\d{1,6})\s*(?:hkd|元)", re.I)


def commit_validated(
    table: Any,
    task: dict[str, Any],
    now: str,
    set_awaiting: Callable[..., dict[str, Any]],
    park: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Validate, or park when a verified fact is not on that org's page or coordinates disagree.

    An evidence miss is ``unverified`` immediately. Retrying the same deliverable
    cannot add the missing page, and it does not spend ``revalidateAttempts``.
    """
    questions = ground_sheet(table, task)
    if questions:
        return park(table, task, now, phase="unverified", questions=questions)
    return set_awaiting(table, task, now, phase="validated")


def ground_sheet(table: Any, task: dict[str, Any]) -> list[str]:
    """Demote unsupported fields. Return park questions, or none when the sheet can validate.

    No successful ``research_fetch_page`` means there is nothing to compare, so
    verified fields stay as the seat marked them. Duplicate coordinates are
    refused either way. Each organisation is checked against its own official URL.
    Address and phone that match the imported record count as supported.
    """
    import board_catalog_import
    import board_staff

    questions: list[str] = []
    key = str(task.get("deliverableKey") or "")
    raw = board_staff.read_deliverable(task) if key else ""
    sheet: dict[str, Any] | None = None
    if raw.strip():
        try:
            sheet = board_catalog_import.parse_sheet(raw)
        except board_catalog_import.CatalogImportError:
            sheet = None
    pages = _fetched_pages(table, str(task.get("taskId") or ""))
    changed = False
    if sheet is not None and pages is not None:
        changed = _demote(table, sheet, pages, questions)
        if changed and key:
            board_staff._blob_put(key, json.dumps(sheet, ensure_ascii=False).encode("utf-8"))
        questions.extend(board_catalog_import.sheet_quality_issues(sheet))
    if sheet is not None:
        questions.extend(_duplicate_coordinates(sheet))
    return questions[:12]


def _demote(table: Any, sheet: dict[str, Any], pages: list[dict[str, str]], questions: list[str]) -> bool:
    orgs = _orgs(sheet)
    if orgs is None:
        return False
    records = _imported_records(table)
    changed = False
    for org in orgs:
        if not isinstance(org, dict):
            continue
        text = _text_for_org(org, pages)
        verified = [str(item).strip() for item in (org.get("verified_fields") or []) if str(item).strip()]
        keep: list[str] = []
        dropped: list[str] = []
        for field in verified:
            kind = _EVIDENCE_FIELDS.get(field)
            value = org.get(field)
            if (
                kind
                and value not in (None, "", "unverified")
                and not _supported(kind, str(value), text)
                and not _on_record(records, org, field, str(value))
            ):
                dropped.append(field)
            else:
                keep.append(field)
        if not dropped:
            continue
        changed = True
        org["verified_fields"] = keep
        unverified = [str(item) for item in (org.get("unverified_fields") or []) if str(item).strip()]
        for field in dropped:
            if field not in unverified:
                unverified.append(field)
        org["unverified_fields"] = unverified
        name = str(org.get("name_en") or org.get("name") or "organisation")[:80]
        for field in dropped:
            questions.append(f"{name}: {field} is not on a page fetched for this task")
    return changed


def _supported(kind: str, value: str, pages: str) -> bool:
    if kind == "phone":
        return _phone_in(value, pages)
    if kind == "address":
        return _address_in(value, pages)
    if kind == "hours":
        return _hours_in(value, pages)
    return _price_in(value, pages)


def _phone_in(value: str, pages: str) -> bool:
    want = re.sub(r"\D", "", value)
    have = re.sub(r"\D", "", pages)
    if len(want) >= 8:
        want = want[-8:]
    return bool(want) and want in have


def street_key(address: str) -> str:
    """Street number plus street name. Shop, floor and unit tokens are left out."""
    words = re.findall(r"[A-Za-z0-9]+", address.lower())
    names = [
        word
        for word in words
        if not word.isdigit() and len(word) > 2 and word not in _STREET_SKIP and word not in _UNIT_WORDS
    ]
    number = ""
    for index, word in enumerate(words):
        if word in names:
            for prev in reversed(words[:index]):
                if prev.isdigit():
                    number = prev
                    break
            break
    parts = ([number] if number else []) + names
    return " ".join(parts)


def _address_in(value: str, pages: str) -> bool:
    key = street_key(value)
    if not key:
        return False
    blob = pages.lower()
    return all(part in blob for part in key.split())


def _hours_in(value: str, pages: str) -> bool:
    clocks = _CLOCK_RE.findall(value)
    if clocks:
        return any(clock in pages for clock in clocks)
    ampm = [match.group(0).lower().replace(" ", "") for match in _AMPM_RE.finditer(value)]
    folded = pages.lower().replace(" ", "")
    if ampm:
        return any(token in folded for token in ampm)
    snippet = " ".join(value.lower().split())[:40]
    return bool(snippet) and snippet in pages.lower()


def _price_in(value: str, pages: str) -> bool:
    priced = [left or right for left, right in _PRICE_RE.findall(value)]
    if priced:
        return all(amount in pages for amount in priced)
    nums = [item for item in re.findall(r"\d{1,5}", value) if item != "0"]
    big = [item for item in nums if int(item) >= 10]
    amounts = big or nums
    if amounts:
        return all(amount in pages for amount in amounts)
    return value.strip().lower() in pages.lower()


def _duplicate_coordinates(sheet: dict[str, Any]) -> list[str]:
    orgs = _orgs(sheet)
    if orgs is None:
        return []
    seen: dict[tuple[str, str], str] = {}
    questions: list[str] = []
    for org in orgs:
        if not isinstance(org, dict):
            continue
        point = _point(org.get("lat"), org.get("lng"))
        if point is None:
            continue
        address = str(org.get("address_en") or org.get("address") or "")
        key = street_key(address)
        name = str(org.get("name_en") or org.get("name") or "organisation")[:80]
        previous = seen.get(point)
        if previous is None:
            seen[point] = key
            continue
        if previous == key and key:
            continue
        questions.append(f"{name}: same lat/lng as another organisation with a different address")
    return questions


def _point(lat: Any, lng: Any) -> tuple[str, str] | None:
    try:
        lat_f = round(float(lat), 5)
        lng_f = round(float(lng), 5)
    except (TypeError, ValueError):
        return None
    return (f"{lat_f:.5f}", f"{lng_f:.5f}")


def _orgs(sheet: dict[str, Any]) -> list[Any] | None:
    orgs = sheet.get("organisations")
    if orgs is None:
        orgs = sheet.get("organizations")
    return orgs if isinstance(orgs, list) else None


def _fetched_pages(table: Any, task_id: str) -> list[dict[str, str]] | None:
    if not task_id:
        return None
    pages: list[dict[str, str]] = []
    for call in board_store.list_tool_calls_for_task(table, task_id):
        if str(call.get("op") or "") != "research_fetch_page":
            continue
        if str(call.get("status") or "") != "ok":
            continue
        url = str((call.get("arguments") or {}).get("url") or "")
        preview = _preview_doc(call.get("resultPreview"))
        final = str(preview.get("finalUrl") or preview.get("final_url") or "")
        text = ""
        if url:
            text = board_crawl.page_text_cached(table, url)
        if not text and final:
            text = board_crawl.page_text_cached(table, final)
        if not text:
            text = str(preview.get("text") or "")
        pages.append({"url": url or final, "text": text})
    if not pages:
        return None
    return pages


def _preview_doc(preview: Any) -> dict[str, Any]:
    if isinstance(preview, dict):
        return preview
    try:
        doc = json.loads(str(preview or ""))
    except (TypeError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _text_for_org(org: dict[str, Any], pages: list[dict[str, str]]) -> str:
    wanted = _norm_url(str(org.get("official_url") or org.get("website") or org.get("source_url") or ""))
    if wanted:
        matched = [page["text"] for page in pages if _norm_url(page.get("url") or "") == wanted]
        return "\n".join(matched)
    name = str(org.get("name_en") or org.get("name") or "").strip().lower()
    matched = [page["text"] for page in pages if name and name in page["text"].lower()]
    return "\n".join(matched)


def _norm_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.netloc:
        return ""
    host = parsed.netloc.lower().removeprefix("www.")
    return f"{host}{parsed.path.rstrip('/')}"


def _imported_records(table: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(doc: dict[str, Any]) -> bool:
        found.append(doc)
        return False

    try:
        board_store.walk_candidates(table, "imported", visit, scan_cap=2000)
    except Exception:
        return []
    return found


def _on_record(records: list[dict[str, Any]], org: dict[str, Any], field: str, value: str) -> bool:
    kind = _EVIDENCE_FIELDS.get(field)
    if kind not in {"address", "phone"}:
        return False
    name = str(org.get("name_en") or org.get("name") or "").strip().casefold()
    if not name:
        return False
    for row in records:
        row_name = str(row.get("nameEn") or row.get("name") or "").strip().casefold()
        if row_name != name:
            continue
        if kind == "phone" and _same_phone(value, str(row.get("phone") or "")):
            return True
        if kind == "address":
            recorded = str(row.get("addressEn") or row.get("address") or "")
            if street_key(value) and street_key(value) == street_key(recorded):
                return True
    return False


def _same_phone(left: str, right: str) -> bool:
    a = re.sub(r"\D", "", left)
    b = re.sub(r"\D", "", right)
    if len(a) >= 8:
        a = a[-8:]
    if len(b) >= 8:
        b = b[-8:]
    return bool(a) and a == b
