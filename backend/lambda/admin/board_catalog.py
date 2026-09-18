"""Catalog micro-batch and enrich duties: one Hong Kong district per run."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import board_staff
import board_store
from contract_constants import (
    BOARD_CATALOG_ASSIGNEE,
    BOARD_CATALOG_BUDGET_USD,
    BOARD_CATALOG_DESCRIBE_BATCH_SIZE,
    BOARD_CATALOG_DESCRIBE_BUDGET_USD,
    BOARD_CATALOG_DISTRICTS,
    BOARD_CATALOG_MAX_AWAITING_IMPORT,
    BOARD_CATALOG_MAX_LOW_COMPLETENESS,
    BOARD_CATALOG_MICRO_BATCH_ENABLED_DEFAULT,
    BOARD_CATALOG_OUTPUT_CONTRACT,
)
from http_common import _log_event

CATALOG_EVENT_KIND = "catalog-micro-batch"
CATALOG_ENRICH_KIND = "catalog-enrich"
LOW_COMPLETENESS = 0.5
_OPEN_STATUSES = (
    "queued",
    "running",
    "waiting_approval",
    "waiting_subtask",
    "review",
    "awaiting_import",
    "delivered",
    "needs_owner",
)
_ENRICH_OPEN = (
    "queued",
    "running",
    "waiting_approval",
    "waiting_subtask",
    "review",
    "awaiting_import",
    "needs_owner",
)
_GOV_HOST_SUFFIXES = (
    "lcsd.gov.hk",
    "gov.hk",
    "edb.gov.hk",
    "fehd.gov.hk",
    "hab.gov.hk",
)
_NON_COMMERCIAL_HOST_SUFFIXES = (".org.hk", ".edu.hk")
_NON_COMMERCIAL_MARKERS = (
    "ngo",
    "charity",
    "church",
    "chapel",
    "temple",
    "mosque",
    "synagogue",
    "community centre",
    "community center",
    "community hall",
    "youth centre",
    "youth center",
    "志願",
    "慈善",
    "教會",
    "教堂",
    "廟",
    "清真寺",
    "社區中心",
    "青年中心",
)


def compose_brief(district: dict[str, Any]) -> str:
    name = str(district.get("name") or "")
    hint = str(district.get("hint") or "")
    contract = BOARD_CATALOG_OUTPUT_CONTRACT.strip()
    return (
        f"Founder directive — CATALOG MICRO-BATCH {name}: curate exactly 3 vetted "
        f"child/family organisations in Hong Kong's {name} district ({hint}). "
        f"Use research_search to find candidates, then research_fetch_page on the official "
        f"LCSD or provider page (one page often has address, hours, phone and free entry). "
        f"{contract}"
    )[:4000]


def compose_enrich_brief(district: dict[str, Any], names: list[str]) -> str:
    name = str(district.get("name") or "")
    hint = str(district.get("hint") or "")
    listed = ", ".join(names[:8]) if names else "the organisations already imported for this district"
    contract = BOARD_CATALOG_OUTPUT_CONTRACT.strip()
    return (
        f"Founder directive — CATALOG DESCRIBE {name}: write 40-word EN + 繁中 descriptions, "
        f"age_range and price_note for {listed} in {name} ({hint}). "
        f"Read only the official page. Leave unverified fields as unverified. "
        f"{contract}"
    )[:4000]


def micro_batch_enabled(settings: dict[str, Any] | None) -> bool:
    catalog = (settings or {}).get("catalog") if isinstance(settings, dict) else None
    if isinstance(catalog, dict) and "microBatchEnabled" in catalog:
        return bool(catalog.get("microBatchEnabled"))
    return bool(BOARD_CATALOG_MICRO_BATCH_ENABLED_DEFAULT)


def claimed_district_ids(table: Any) -> set[str]:
    found: set[str] = set()
    for status in _OPEN_STATUSES:
        for task in board_store.list_tasks(table, status, limit=200):
            ref = task.get("eventRef") or {}
            if str(ref.get("kind") or "") != CATALOG_EVENT_KIND:
                continue
            did = str(ref.get("districtId") or "").strip().lower()
            if did:
                found.add(did)
    return found


def open_enrich_district_ids(table: Any) -> set[str]:
    found: set[str] = set()
    for status in _ENRICH_OPEN:
        for task in board_store.list_tasks(table, status, limit=200):
            ref = task.get("eventRef") or {}
            if str(ref.get("kind") or "") != CATALOG_ENRICH_KIND:
                continue
            did = str(ref.get("districtId") or "").strip().lower()
            if did:
                found.add(did)
    return found


def district_completeness(table: Any) -> dict[str, float]:
    """Average completeness by district label from the cached product view.

    Cache-only: never hits the Data API (review compile and the duty gate
    stay offline when the hourly refresh has not run).
    """
    try:
        import board_product

        hit = board_product.cached_catalog_health(table)
    except Exception as exc:
        _log_event("info", tag="board_catalog_health_unavailable", error=str(exc)[:200])
        return {}
    scores: dict[str, list[float]] = {}
    for row in hit.get("rows") or []:
        if not isinstance(row, dict):
            continue
        label = str(row.get("district") or "").strip()
        if not label or row.get("completeness") is None:
            continue
        try:
            scores.setdefault(label, []).append(float(row["completeness"]))
        except (TypeError, ValueError):
            continue
    return {label: sum(vals) / len(vals) for label, vals in scores.items() if vals}


def low_completeness_imported_count(table: Any) -> int:
    imported = claimed_district_ids(table)
    scores = district_completeness(table)
    count = 0
    for row in BOARD_CATALOG_DISTRICTS:
        if not isinstance(row, dict):
            continue
        did = str(row.get("id") or "").strip().lower()
        name = str(row.get("name") or "")
        if did not in imported:
            continue
        score = scores.get(name)
        if score is not None and score < LOW_COMPLETENESS:
            count += 1
    return count


def next_district(table: Any, *, enforce_completeness_gate: bool = True) -> dict[str, Any] | None:
    if enforce_completeness_gate:
        low = low_completeness_imported_count(table)
        if low > BOARD_CATALOG_MAX_LOW_COMPLETENESS:
            return None
    claimed = claimed_district_ids(table)
    for row in BOARD_CATALOG_DISTRICTS:
        if not isinstance(row, dict):
            continue
        did = str(row.get("id") or "").strip().lower()
        if did and did not in claimed:
            return row
    return None


def imported_org_names(table: Any, district_id: str) -> list[str]:
    did = str(district_id or "").strip().lower()
    district_name = ""
    for row in BOARD_CATALOG_DISTRICTS:
        if isinstance(row, dict) and str(row.get("id") or "").strip().lower() == did:
            district_name = str(row.get("name") or "")
            break
    names: list[str] = []
    for status in ("delivered", "awaiting_import", "needs_owner"):
        for task in board_store.list_tasks(table, status, limit=200):
            ref = task.get("eventRef") or {}
            if str(ref.get("kind") or "") != CATALOG_EVENT_KIND:
                continue
            if str(ref.get("districtId") or "").strip().lower() != did:
                continue
            preview = task.get("importPreview") if isinstance(task.get("importPreview"), dict) else {}
            payload = preview.get("payload") if isinstance(preview.get("payload"), dict) else {}
            for org in payload.get("organizations") or []:
                if not isinstance(org, dict):
                    continue
                name = str(org.get("name") or "").strip()
                if name and name not in names:
                    names.append(name)
    for cand in board_store.list_candidates(table, "imported", limit=400):
        if district_name and str(cand.get("district") or "") != district_name:
            continue
        if str(cand.get("descriptionSource") or "") not in ("", "template"):
            continue
        name = str(cand.get("nameEn") or cand.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names[:BOARD_CATALOG_DESCRIBE_BATCH_SIZE]


def next_enrich_district(table: Any) -> dict[str, Any] | None:
    imported = claimed_district_ids(table)
    busy = open_enrich_district_ids(table)
    scores = district_completeness(table)
    for row in BOARD_CATALOG_DISTRICTS:
        if not isinstance(row, dict):
            continue
        did = str(row.get("id") or "").strip().lower()
        name = str(row.get("name") or "")
        if did not in imported or did in busy:
            continue
        score = scores.get(name)
        if score is None or score < LOW_COMPLETENESS:
            return row
    return None


def create_next(table: Any, settings: dict[str, Any], *, created_by: str = "board_duties") -> dict[str, Any]:
    import board_catalog_import

    if not micro_batch_enabled(settings):
        raise board_staff.StaffError("catalog micro-batch paused")
    if board_catalog_import.at_awaiting_cap(table):
        raise board_staff.StaffError(
            f"catalog awaiting_import cap reached ({BOARD_CATALOG_MAX_AWAITING_IMPORT})"
        )
    low = low_completeness_imported_count(table)
    if low > BOARD_CATALOG_MAX_LOW_COMPLETENESS:
        raise board_staff.StaffError(
            f"pause new districts: {low} imported districts below 50% completeness"
        )
    district = next_district(table, enforce_completeness_gate=False)
    if not district:
        raise board_staff.StaffError("all catalog districts already have a sheet")
    did = str(district.get("id") or "")
    name = str(district.get("name") or did)
    return board_staff.create_task(
        table,
        settings,
        assignee=BOARD_CATALOG_ASSIGNEE,
        origin="duty",
        brief=compose_brief(district),
        deliverable_type="json",
        budget_usd=BOARD_CATALOG_BUDGET_USD,
        sla_hours=24,
        event_ref={"kind": CATALOG_EVENT_KIND, "id": f"catalog:{did}", "districtId": did, "district": name},
        created_by=created_by,
    )


def create_enrich(table: Any, settings: dict[str, Any], *, created_by: str = "board_duties") -> dict[str, Any]:
    import board_catalog_import

    if board_catalog_import.at_awaiting_cap(table):
        raise board_staff.StaffError(
            f"catalog awaiting_import cap reached ({BOARD_CATALOG_MAX_AWAITING_IMPORT})"
        )
    district = next_enrich_district(table)
    if not district:
        raise board_staff.StaffError("no district needs enrich")
    did = str(district.get("id") or "")
    name = str(district.get("name") or did)
    names = imported_org_names(table, did)[:BOARD_CATALOG_DESCRIBE_BATCH_SIZE]
    return board_staff.create_task(
        table,
        settings,
        assignee=BOARD_CATALOG_ASSIGNEE,
        origin="duty",
        brief=compose_enrich_brief(district, names),
        deliverable_type="json",
        budget_usd=BOARD_CATALOG_DESCRIBE_BUDGET_USD,
        sla_hours=24,
        event_ref={"kind": CATALOG_ENRICH_KIND, "id": f"catalog-enrich:{did}", "districtId": did, "district": name},
        created_by=created_by,
    )


def _has_non_commercial_marker(blob: str, marker: str) -> bool:
    if any(ord(ch) > 127 for ch in marker):
        return marker in blob
    return re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", blob) is not None


def is_commercial_org(org: dict[str, Any]) -> bool:
    url = str(org.get("official_url") or org.get("website") or org.get("source_url") or "")
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host and any(host == suffix or host.endswith("." + suffix) for suffix in _GOV_HOST_SUFFIXES):
        return False
    if host and any(host.endswith(suffix) for suffix in _NON_COMMERCIAL_HOST_SUFFIXES):
        return False
    org_type = str(org.get("type") or org.get("category_name") or "").strip().lower()
    if org_type in ("playground", "outdoor", "outdoor activity"):
        return False
    blob = " ".join(
        (
            str(org.get("name_en") or ""),
            str(org.get("name") or ""),
            str(org.get("name_zh") or ""),
            org_type,
            url,
            host,
        )
    ).casefold()
    if any(_has_non_commercial_marker(blob, marker) for marker in _NON_COMMERCIAL_MARKERS):
        return False
    return True


def handoff_commercial_providers(
    table: Any,
    settings: dict[str, Any],
    task: dict[str, Any],
    sheet: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Open provider-success tasks for commercial orgs on an enrich sheet."""
    ref = task.get("eventRef") or {}
    if str(ref.get("kind") or "") != CATALOG_ENRICH_KIND:
        return []
    if not board_staff.enabled(settings):
        return []
    roster = board_staff.seats_by_id(table, settings)
    if not (roster.get("provider-success") or {}).get("isActive"):
        return []
    orgs = []
    if isinstance(sheet, dict):
        raw = sheet.get("organisations")
        if raw is None:
            raw = sheet.get("organizations")
        if isinstance(raw, list):
            orgs = [row for row in raw if isinstance(row, dict)]
    created: list[dict[str, Any]] = []
    district = str(ref.get("district") or "")
    from board_triage import find_open_event_task

    for org in orgs:
        if not is_commercial_org(org):
            continue
        name = str(org.get("name_en") or org.get("name") or "").strip()
        if not name:
            continue
        event_id = f"handoff:{_slug(name)}"
        if find_open_event_task(table, "catalog-handoff", event_id):
            continue
        try:
            created.append(
                board_staff.create_task(
                    table,
                    settings,
                    assignee="provider-success",
                    origin="duty",
                    brief=(
                        f"Send the Siu Tin Dei provider onboarding link to {name} in {district} "
                        f"and ask them to add photos, prices and opening hours on their listing. "
                        f"Do not write the listing yourself."
                    )[:4000],
                    deliverable_type="markdown",
                    sla_hours=24,
                    event_ref={
                        "kind": "catalog-handoff",
                        "id": event_id,
                        "district": district,
                        "name": name,
                    },
                    created_by="board_catalog",
                )
            )
        except board_staff.StaffError as exc:
            _log_event("info", tag="board_catalog_handoff_skipped", name=name[:80], error=str(exc)[:200])
    return created


def _slug(value: str) -> str:
    return "-".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())[:60]
