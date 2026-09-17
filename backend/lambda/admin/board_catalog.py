"""Catalog micro-batch duty: one remaining Hong Kong district per run."""

from __future__ import annotations

from typing import Any

import board_staff
import board_store
from contract_constants import (
    BOARD_CATALOG_ASSIGNEE,
    BOARD_CATALOG_BUDGET_USD,
    BOARD_CATALOG_DISTRICTS,
    BOARD_CATALOG_MAX_AWAITING_IMPORT,
    BOARD_CATALOG_OUTPUT_CONTRACT,
)
from http_common import _log_event

CATALOG_EVENT_KIND = "catalog-micro-batch"
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


def compose_brief(district: dict[str, Any]) -> str:
    name = str(district.get("name") or "")
    hint = str(district.get("hint") or "")
    contract = BOARD_CATALOG_OUTPUT_CONTRACT.strip()
    return (
        f"Founder directive — CATALOG MICRO-BATCH {name}: curate exactly 3 vetted "
        f"child/family organisations in Hong Kong's {name} district ({hint}). "
        f"Use research_search to find candidates, then research_fetch_page on the official page. "
        f"{contract}"
    )[:4000]


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


def next_district(table: Any) -> dict[str, Any] | None:
    claimed = claimed_district_ids(table)
    for row in BOARD_CATALOG_DISTRICTS:
        if not isinstance(row, dict):
            continue
        did = str(row.get("id") or "").strip().lower()
        if did and did not in claimed:
            return row
    return None


def create_next(table: Any, settings: dict[str, Any], *, created_by: str = "board_duties") -> dict[str, Any]:
    import board_catalog_import

    if board_catalog_import.at_awaiting_cap(table):
        raise board_staff.StaffError(
            f"catalog awaiting_import cap reached ({BOARD_CATALOG_MAX_AWAITING_IMPORT})"
        )
    district = next_district(table)
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
