"""Ground catalog verified_fields in pages this task actually fetched."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

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
_CLOCK_RE = re.compile(r"\d{1,2}:\d{2}")
_AMPM_RE = re.compile(r"\d{1,2}\s*(?:am|pm)", re.I)


def commit_validated(
    table: Any,
    task: dict[str, Any],
    now: str,
    set_awaiting: Callable[..., dict[str, Any]],
    park: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Validate, or park when a verified fact is not on a fetched page or coordinates repeat."""
    questions = ground_sheet(table, task)
    if questions:
        try:
            previous = int(task.get("revalidateAttempts") or 0)
        except (TypeError, ValueError):
            previous = 0
        task["revalidateAttempts"] = previous + 1
        phase = "unverified" if previous >= 1 else "invalid"
        return park(table, task, now, phase=phase, questions=questions)
    return set_awaiting(table, task, now, phase="validated")


def ground_sheet(table: Any, task: dict[str, Any]) -> list[str]:
    """Demote unsupported fields. Return park questions, or none when the sheet can validate.

    No successful ``research_fetch_page`` means there is nothing to compare, so
    verified fields stay as the seat marked them. Duplicate coordinates are
    refused either way.
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
    pages = _fetched_text(table, str(task.get("taskId") or ""))
    changed = False
    if sheet is not None and pages is not None:
        changed = _demote(sheet, pages, questions)
        if changed and key:
            board_staff._blob_put(key, json.dumps(sheet, ensure_ascii=False).encode("utf-8"))
        questions.extend(board_catalog_import.sheet_quality_issues(sheet))
    if sheet is not None:
        questions.extend(_duplicate_coordinates(sheet))
    return questions[:12]


def _demote(sheet: dict[str, Any], pages: str, questions: list[str]) -> bool:
    orgs = sheet.get("organisations")
    if orgs is None:
        orgs = sheet.get("organizations")
    if not isinstance(orgs, list):
        return False
    changed = False
    for org in orgs:
        if not isinstance(org, dict):
            continue
        verified = [str(item).strip() for item in (org.get("verified_fields") or []) if str(item).strip()]
        keep: list[str] = []
        dropped: list[str] = []
        for field in verified:
            kind = _EVIDENCE_FIELDS.get(field)
            value = org.get(field)
            if kind and value not in (None, "", "unverified") and not _supported(kind, str(value), pages):
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


def _address_in(value: str, pages: str) -> bool:
    words = re.findall(r"[A-Za-z0-9]+", value)
    number = next((word for word in words if word.isdigit()), "")
    names = [
        word.lower() for word in words if not word.isdigit() and len(word) > 2 and word.lower() not in _STREET_SKIP
    ]
    if number and number not in pages:
        return False
    blob = pages.lower()
    if not names:
        return bool(number)
    return all(word in blob for word in names)


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
    amounts = [item for item in re.findall(r"\d{1,5}", value) if item != "0"]
    if amounts:
        return any(amount in pages for amount in amounts)
    return value.strip().lower() in pages.lower()


def _duplicate_coordinates(sheet: dict[str, Any]) -> list[str]:
    orgs = sheet.get("organisations")
    if orgs is None:
        orgs = sheet.get("organizations")
    if not isinstance(orgs, list):
        return []
    seen: dict[tuple[str, str], str] = {}
    questions: list[str] = []
    for org in orgs:
        if not isinstance(org, dict):
            continue
        point = _point(org.get("lat"), org.get("lng"))
        if point is None:
            continue
        address = " ".join(str(org.get("address_en") or org.get("address") or "").lower().split())
        name = str(org.get("name_en") or org.get("name") or "organisation")[:80]
        previous = seen.get(point)
        if previous is None:
            seen[point] = address
            continue
        if previous != address:
            questions.append(f"{name}: same lat/lng as another organisation with a different address")
    return questions


def _point(lat: Any, lng: Any) -> tuple[str, str] | None:
    try:
        lat_f = round(float(lat), 5)
        lng_f = round(float(lng), 5)
    except (TypeError, ValueError):
        return None
    return (f"{lat_f:.5f}", f"{lng_f:.5f}")


def _fetched_text(table: Any, task_id: str) -> str | None:
    if not task_id:
        return None
    chunks: list[str] = []
    found = False
    for call in board_store.list_tool_calls_for_task(table, task_id):
        if str(call.get("op") or "") != "research_fetch_page":
            continue
        if str(call.get("status") or "") != "ok":
            continue
        found = True
        url = str((call.get("arguments") or {}).get("url") or "")
        cached = board_crawl.page_text_cached(table, url) if url else ""
        chunks.append(cached or _preview_text(call.get("resultPreview")))
    if not found:
        return None
    return "\n".join(chunk for chunk in chunks if chunk)


def _preview_text(preview: Any) -> str:
    if isinstance(preview, dict):
        return str(preview.get("text") or "")
    text = str(preview or "")
    try:
        doc = json.loads(text)
    except (TypeError, ValueError):
        return text
    if isinstance(doc, dict):
        return str(doc.get("text") or text)
    return text
