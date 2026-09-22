"""Catalog micro-batch and enrich duties: one Hong Kong district per run."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

import board_hk
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
ENRICH_COOLDOWN_HOURS = 48
ENRICH_FAIL_GAP = 3
# EDB rows are kindergartens (deny-list), so they must not crowd the describe queue.
ENRICH_SKIP_SOURCES = frozenset({"edb"})
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


def compose_enrich_brief(
    district: dict[str, Any],
    names: list[str],
    pages: list[dict[str, str]] | None = None,
) -> str:
    name = str(district.get("name") or "")
    hint = str(district.get("hint") or "")
    listed = ", ".join(names[:8]) if names else "the organisations already imported for this district"
    contract = BOARD_CATALOG_OUTPUT_CONTRACT.strip()
    page_bits = []
    for page in pages or []:
        org = str(page.get("name") or "").strip()
        url = str(page.get("url") or "").strip()
        if org and url:
            page_bits.append(f"{org}: {url}")
    pages_note = ""
    if page_bits:
        pages_note = (
            "Official pages (research_fetch_page only these URLs; any other URL is refused): "
            + "; ".join(page_bits)
            + ". "
        )
    return (
        f"Founder directive — CATALOG DESCRIBE {name}: write 40-word EN + 繁中 descriptions, "
        f"age_range and price_note for {listed} in {name} ({hint}). "
        f"The organisation names below are already verified — copy each name_en into verified_fields. "
        f"{pages_note}"
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


def _org_page_url(row: dict[str, Any]) -> str:
    for key in ("official_url", "website", "source_url", "officialUrl", "sourceUrl"):
        url = str(row.get(key) or "").strip()
        if url.startswith("http://") or url.startswith("https://"):
            return url[:400]
    return ""


def _enrich_district_names() -> set[str]:
    names: set[str] = set()
    for row in BOARD_CATALOG_DISTRICTS:
        if not isinstance(row, dict):
            continue
        label = board_hk.canonical_district(str(row.get("name") or ""))
        if label != "unknown":
            names.add(label)
    return names


def _index_imported_candidates(table: Any) -> dict[str, list[dict[str, str]]]:
    """One walk of imported candidates, grouped by canonical district.

    Stops once every catalog district has a full describe batch, so a duty
    does not re-read the index once per district.
    """
    targets = _enrich_district_names()
    buckets: dict[str, list[dict[str, str]]] = {}
    seen: dict[str, set[str]] = {}

    def full() -> bool:
        return bool(targets) and all(
            len(buckets.get(name) or []) >= BOARD_CATALOG_DESCRIBE_BATCH_SIZE for name in targets
        )

    def visit(cand: dict[str, Any]) -> bool:
        if full():
            return True
        if str(cand.get("source") or "") in ENRICH_SKIP_SOURCES:
            return False
        if str(cand.get("descriptionSource") or "") not in ("", "template"):
            return False
        district = board_hk.canonical_district(str(cand.get("district") or ""))
        if district not in targets:
            return False
        bucket = buckets.setdefault(district, [])
        if len(bucket) >= BOARD_CATALOG_DESCRIBE_BATCH_SIZE:
            return full()
        cleaned = " ".join(str(cand.get("nameEn") or cand.get("name") or "").split()).strip()
        if not cleaned:
            return False
        names = seen.setdefault(district, set())
        if cleaned.casefold() in names:
            return False
        names.add(cleaned.casefold())
        bucket.append({"name": cleaned, "url": _org_page_url(cand)})
        return full()

    board_store.walk_candidates(table, "imported", visit)
    return buckets


def imported_orgs(
    table: Any,
    district_id: str,
    *,
    imported_index: dict[str, list[dict[str, str]]] | None = None,
) -> list[dict[str, str]]:
    """Imported organisations in a district, with an official URL when we have one."""
    did = str(district_id or "").strip().lower()
    district_name = ""
    for row in BOARD_CATALOG_DISTRICTS:
        if isinstance(row, dict) and str(row.get("id") or "").strip().lower() == did:
            district_name = str(row.get("name") or "")
            break
    found: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(name: str, url: str) -> None:
        cleaned = " ".join(str(name or "").split()).strip()
        if not cleaned or cleaned.casefold() in seen:
            return
        seen.add(cleaned.casefold())
        found.append({"name": cleaned, "url": url})

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
                if isinstance(org, dict):
                    add(str(org.get("name") or ""), _org_page_url(org))
    if len(found) >= BOARD_CATALOG_DESCRIBE_BATCH_SIZE:
        return found[:BOARD_CATALOG_DESCRIBE_BATCH_SIZE]
    index = imported_index if imported_index is not None else _index_imported_candidates(table)
    if district_name:
        rows = index.get(board_hk.canonical_district(district_name), [])
    else:
        rows = [item for bucket in index.values() for item in bucket]
    for item in rows:
        add(item.get("name") or "", item.get("url") or "")
        if len(found) >= BOARD_CATALOG_DESCRIBE_BATCH_SIZE:
            break
    return found[:BOARD_CATALOG_DESCRIBE_BATCH_SIZE]


def imported_org_names(table: Any, district_id: str) -> list[str]:
    return [row["name"] for row in imported_orgs(table, district_id)]


def parked_enrich_count(table: Any) -> int:
    """needs_owner catalog-enrich sheets. Three of these pause the enrich duty."""
    count = 0
    for task in board_store.list_tasks(table, "needs_owner", limit=200):
        ref = task.get("eventRef") or {}
        if str(ref.get("kind") or "") == CATALOG_ENRICH_KIND:
            count += 1
    return count


def _task_district_id(task: dict[str, Any]) -> str:
    return str((task.get("eventRef") or {}).get("districtId") or "").strip().lower()


def _task_when(task: dict[str, Any]):
    raw = str(task.get("createdAt") or "")
    if not raw:
        return None
    try:
        when = board_hk.parse_iso(raw)
    except ValueError:
        return None
    if when.tzinfo is None:
        from datetime import timezone

        when = when.replace(tzinfo=timezone.utc)
    return when


def enrich_recently_blocked_ids(table: Any, *, hours: int = ENRICH_COOLDOWN_HOURS) -> set[str]:
    cutoff = board_hk.now_hkt() - timedelta(hours=max(1, int(hours)))
    found: set[str] = set()
    for status in ("failed", "needs_owner", "awaiting_import"):
        for task in board_store.list_tasks(table, status, limit=200):
            ref = task.get("eventRef") or {}
            if str(ref.get("kind") or "") != CATALOG_ENRICH_KIND:
                continue
            did = _task_district_id(task)
            when = _task_when(task)
            if did and when is not None and when >= cutoff:
                found.add(did)
    return found


def enrich_failed_count(table: Any, district_id: str) -> int:
    did = str(district_id or "").strip().lower()
    n = 0
    for status in ("failed", "needs_owner"):
        for task in board_store.list_tasks(table, status, limit=200):
            ref = task.get("eventRef") or {}
            if str(ref.get("kind") or "") != CATALOG_ENRICH_KIND:
                continue
            if _task_district_id(task) != did:
                continue
            n += 1
    return n


def next_enrich_district(
    table: Any,
    *,
    imported_index: dict[str, list[dict[str, str]]] | None = None,
) -> dict[str, Any] | None:
    busy = open_enrich_district_ids(table)
    cooling = enrich_recently_blocked_ids(table)
    scores = district_completeness(table)
    index = imported_index if imported_index is not None else _index_imported_candidates(table)
    for row in BOARD_CATALOG_DISTRICTS:
        if not isinstance(row, dict):
            continue
        did = str(row.get("id") or "").strip().lower()
        name = str(row.get("name") or "")
        if not did or did in busy or did in cooling:
            continue
        names = [item["name"] for item in imported_orgs(table, did, imported_index=index)]
        if not names:
            continue
        if enrich_failed_count(table, did) >= ENRICH_FAIL_GAP:
            try:
                import board_duties

                board_duties.note_config_gap(
                    table,
                    gap_id=f"catalog-enrich:{did}",
                    reason=f"{name} enrich failed {ENRICH_FAIL_GAP} times; skip new sheets until an owner retries",
                )
            except Exception as exc:
                _log_event("info", tag="board_catalog_enrich_gap_failed", error=str(exc)[:200])
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
    parked = parked_enrich_count(table)
    if parked >= BOARD_CATALOG_MAX_AWAITING_IMPORT:
        raise board_staff.StaffError(
            f"catalog enrich paused: {parked} needs_owner sheets "
            f"(cap {BOARD_CATALOG_MAX_AWAITING_IMPORT})"
        )
    index = _index_imported_candidates(table)
    district = next_enrich_district(table, imported_index=index)
    if not district:
        raise board_staff.StaffError("no district needs enrich")
    did = str(district.get("id") or "")
    name = str(district.get("name") or did)
    orgs = imported_orgs(table, did, imported_index=index)[:BOARD_CATALOG_DESCRIBE_BATCH_SIZE]
    names = [row["name"] for row in orgs]
    pages = [row for row in orgs if row.get("url")]
    if not names:
        raise board_staff.StaffError("no district needs enrich")
    return board_staff.create_task(
        table,
        settings,
        assignee=BOARD_CATALOG_ASSIGNEE,
        origin="duty",
        brief=compose_enrich_brief(district, names, pages),
        deliverable_type="json",
        budget_usd=BOARD_CATALOG_DESCRIBE_BUDGET_USD,
        sla_hours=24,
        event_ref={
            "kind": CATALOG_ENRICH_KIND,
            "id": f"catalog-enrich:{did}",
            "districtId": did,
            "district": name,
            "orgNames": names,
            "orgUrls": pages,
        },
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
