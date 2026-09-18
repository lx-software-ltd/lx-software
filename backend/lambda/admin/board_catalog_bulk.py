"""Bulk catalog import from open data, Places and the candidate queue."""

from __future__ import annotations

from typing import Any

import board_catalog_candidates
import board_catalog_import
import board_opendata
import board_store
from contract_constants import (
    BOARD_CATALOG_BULK_SOURCES,
    BOARD_CATALOG_LAUNCH_LISTING_TARGET,
    BOARD_CATALOG_MAX_ORGS_PER_BULK_IMPORT,
    BOARD_CATALOG_SOURCE_CATEGORY,
)
from http_common import _log_event

TEMPLATE_EN = "{name} is a {kind} in {district} for children and families."
TEMPLATE_ZH = "{name}係{district}嘅{kind}，適合小朋友同家庭。"
KIND_EN = {
    "Outdoor activity": "public outdoor venue",
    "Indoor fun": "indoor family venue",
    "Sport": "sports venue",
    "Class": "class or early-years centre",
    "Workshop": "workshop venue",
}
KIND_ZH = {
    "Outdoor activity": "戶外場地",
    "Indoor fun": "室內親子場地",
    "Sport": "運動場地",
    "Class": "幼兒或興趣班",
    "Workshop": "工作坊場地",
}


class BulkImportError(board_catalog_import.CatalogImportError):
    """Owner-facing bulk import failure."""


def _kind_label(category: str, zh: bool = False) -> str:
    table = KIND_ZH if zh else KIND_EN
    return table.get(category, "family venue" if not zh else "親子場地")


def _template_descriptions(name_en: str, name_zh: str, district: str, category: str) -> tuple[str, str]:
    en = TEMPLATE_EN.format(name=name_en or name_zh, kind=_kind_label(category), district=district)
    zh_name = name_zh or name_en
    zh = TEMPLATE_ZH.format(name=zh_name, kind=_kind_label(category, zh=True), district=district)
    return en[:240], zh[:240]


def row_to_candidate(row: dict[str, Any], *, source: str) -> dict[str, Any]:
    category = board_catalog_candidates.category_for({**row, "source": source})
    name_en = str(row.get("nameEn") or row.get("name") or "").strip()
    name_zh = str(row.get("nameZh") or "").strip()
    district = str(row.get("district") or "")
    desc_en, desc_zh = _template_descriptions(name_en, name_zh, district, category)
    return {
        **row,
        "source": source,
        "nameEn": name_en,
        "nameZh": name_zh,
        "district": district,
        "category": category,
        "descriptionEn": desc_en,
        "descriptionZh": desc_zh,
        "descriptionSource": "template",
        "officialUrl": str(row.get("officialUrl") or row.get("website") or ""),
        "addressEn": str(row.get("addressEn") or row.get("address") or ""),
    }


def candidate_to_org(row: dict[str, Any], *, manager_id: str) -> dict[str, Any]:
    name = str(row.get("nameEn") or row.get("name") or "").strip()
    district = str(row.get("district") or "unknown")
    category = str(row.get("category") or BOARD_CATALOG_SOURCE_CATEGORY.get(str(row.get("facilityKind") or ""), "Class"))
    desc_en = str(row.get("descriptionEn") or "")
    desc_zh = str(row.get("descriptionZh") or "")
    if not desc_en:
        desc_en, desc_zh = _template_descriptions(name, str(row.get("nameZh") or ""), district, category)
    website = str(row.get("officialUrl") or row.get("website") or "")
    address = str(row.get("addressEn") or row.get("address") or name)
    org: dict[str, Any] = {
        "name": name[:200],
        "name_zh": str(row.get("nameZh") or "")[:200],
        "manager_id": manager_id,
        "area_name": district[:80],
        "category_name": category,
        "address": address[:300],
        "description": desc_en[:400],
        "description_zh": desc_zh[:400],
        "vetting_note": (
            f"source={row.get('source')}; sourceId={row.get('sourceId') or row.get('placeId') or ''}; "
            f"descriptionSource={row.get('descriptionSource') or 'template'}"
        )[:500],
    }
    if website:
        org["website"] = website[:400]
        org["source_url"] = website[:400]
    if row.get("lat") not in (None, ""):
        try:
            org["lat"] = float(row["lat"])
        except (TypeError, ValueError):
            pass
    if row.get("lng") not in (None, ""):
        try:
            org["lng"] = float(row["lng"])
        except (TypeError, ValueError):
            pass
    if row.get("phone"):
        org["phone"] = str(row["phone"])[:40]
    if row.get("placeId"):
        org["place_id"] = str(row["placeId"])[:80]
    activity: dict[str, Any] = {
        "name": org["name"],
        "category_name": category,
        "description": desc_en[:400],
        "vetting_note": org["vetting_note"],
    }
    if org.get("source_url"):
        activity["source_url"] = org["source_url"]
    weekly = None
    if row.get("openingHours"):
        weekly = board_catalog_import.parse_opening_hours(row.get("openingHours"))
    if weekly:
        activity["schedules"] = [
            {"location_name": address[:200], "timezone": "Asia/Hong_Kong", "weekly_entries": weekly}
        ]
    org["activities"] = [activity]
    return org


def load_source_rows(table: Any, source: str) -> list[dict[str, Any]]:
    if source == "lcsd":
        return list((board_opendata.lcsd_facilities(table).get("rows") or []))
    if source == "edb":
        return list((board_opendata.edb_kindergartens(table).get("rows") or []))
    if source == "swd":
        return list((board_opendata.swd_child_care_centres(table).get("rows") or []))
    if source in ("places", "competitor"):
        return [
            row
            for row in board_store.list_candidates(table, limit=2000)
            if str(row.get("source") or "") == source and str(row.get("status") or "") in ("new", "approved")
        ]
    raise BulkImportError(f"unknown catalog source {source}")


def ingest_source(table: Any, source: str) -> dict[str, Any]:
    rows = load_source_rows(table, source)
    created = 0
    skipped = 0
    for raw in rows:
        cand = row_to_candidate(raw, source=source)
        if board_catalog_candidates.is_duplicate(table, cand) and source not in ("places", "competitor"):
            skipped += 1
            continue
        board_catalog_candidates.upsert_candidate(table, cand)
        created += 1
    return {"source": source, "fetched": len(rows), "upserted": created, "skippedDuplicates": skipped}


def _batches(orgs: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    size = max(1, int(size))
    return [orgs[i : i + size] for i in range(0, len(orgs), size)]


def _approved_for_source(table: Any, source: str) -> list[dict[str, Any]]:
    return [
        row
        for row in board_store.list_candidates(table, "approved", limit=2000)
        if str(row.get("source") or "") == source
    ]


def preview_source(table: Any, source: str, *, remote: bool = False, limit: int | None = None) -> dict[str, Any]:
    if source not in BOARD_CATALOG_BULK_SOURCES:
        raise BulkImportError(f"unknown catalog source {source}")
    if not board_catalog_import.import_enabled():
        raise BulkImportError("catalog import is switched off (SiutindeiBoardCatalogImportEnabled)")
    ingest = ingest_source(table, source)
    approved = _approved_for_source(table, source)
    mid = board_catalog_import.catalog_manager_id()
    if not mid:
        raise BulkImportError("BOARD_CATALOG_MANAGER_ID is not set")
    orgs = [candidate_to_org(row, manager_id=mid) for row in approved]
    if limit is not None:
        orgs = orgs[: max(0, int(limit))]
    batches = _batches(orgs, BOARD_CATALOG_MAX_ORGS_PER_BULK_IMPORT)
    dry_runs: list[dict[str, Any]] = []
    for batch in batches[:8]:
        payload = {"organizations": batch, "accepted": len(batch)}
        local = board_catalog_import.local_dry_run(payload)
        entry: dict[str, Any] = {"ok": local.get("ok"), "accepted": local.get("accepted"), "errors": local.get("errors") or []}
        if remote and board_catalog_import.configured() and local.get("ok"):
            try:
                token = board_catalog_import._id_token()  # noqa: SLF001
                remote_dry = board_catalog_import._remote_dry_run(payload, token)  # noqa: SLF001
                entry = {**entry, **{k: remote_dry.get(k) for k in ("ok", "summary", "wouldUpdate", "mode")}}
                entry["objectKey"] = board_catalog_import._safe_url(str(remote_dry.get("objectKey") or ""))  # noqa: SLF001
            except Exception as exc:
                entry["remoteError"] = str(exc)[:300]
        dry_runs.append(entry)
    board_store.put_cache(
        table,
        f"catalog:bulk:{source}:preview",
        {"at": board_store.now_iso(), "count": len(orgs), "batches": len(batches)},
        ttl_seconds=7 * 86400,
    )
    return {
        "source": source,
        "ingest": ingest,
        "approved": len(approved),
        "wouldSend": len(orgs),
        "batches": len(batches),
        "batchSize": BOARD_CATALOG_MAX_ORGS_PER_BULK_IMPORT,
        "dryRuns": dry_runs,
        "ok": all(d.get("ok") for d in dry_runs) if dry_runs else True,
    }


def import_source(table: Any, source: str, *, remote: bool = True, limit: int | None = None) -> dict[str, Any]:
    preview = preview_source(table, source, remote=False, limit=limit)
    if not board_catalog_import.import_enabled() or not board_catalog_import.configured():
        raise BulkImportError("catalog import is not configured")
    approved = _approved_for_source(table, source)
    mid = board_catalog_import.catalog_manager_id()
    orgs = [candidate_to_org(row, manager_id=mid) for row in approved]
    if limit is not None:
        orgs = orgs[: max(0, int(limit))]
        approved = approved[: len(orgs)]
    token = board_catalog_import._id_token()  # noqa: SLF001
    results: list[dict[str, Any]] = []
    imported_ids: list[str] = []
    for batch, rows in zip(_batches(orgs, BOARD_CATALOG_MAX_ORGS_PER_BULK_IMPORT), _batches(approved, BOARD_CATALOG_MAX_ORGS_PER_BULK_IMPORT)):
        imported = board_catalog_import._run_remote_import({"organizations": batch}, token)  # noqa: SLF001
        failed = int((imported.get("summary") or {}).get("failed") or 0)
        compact = {
            "ok": bool(imported.get("ok")) and failed == 0,
            "sent": imported.get("sent"),
            "accepted": imported.get("accepted"),
            "summary": imported.get("summary"),
            "failedActivities": sum(
                1
                for row in (imported.get("results") or [])
                if str(row.get("type") or "").lower() == "activities" and str(row.get("status") or "").lower() == "failed"
            ),
            "objectKey": board_catalog_import._safe_url(str(imported.get("objectKey") or "")),  # noqa: SLF001
        }
        results.append(compact)
        if compact["ok"]:
            for row, org in zip(rows, batch):
                board_catalog_candidates.set_status(table, str(row["candidateId"]), "imported")
                board_catalog_candidates.remember_listing(table, org)
                imported_ids.append(str(row["candidateId"]))
    board_store.put_cache(
        table,
        f"catalog:bulk:{source}:last",
        {"at": board_store.now_iso(), "imported": len(imported_ids), "batches": len(results)},
        ttl_seconds=40 * 86400,
    )
    _log_event("info", tag="board_catalog_bulk_import", source=source, imported=len(imported_ids), batches=len(results))
    return {
        "ok": all(r.get("ok") for r in results) if results else True,
        "source": source,
        "imported": len(imported_ids),
        "batches": results,
        "preview": {k: preview.get(k) for k in ("approved", "wouldSend", "ingest")},
    }


def sources_status(table: Any) -> dict[str, Any]:
    counts = board_catalog_candidates.counts_by_source(table)
    sources = []
    for source in BOARD_CATALOG_BULK_SOURCES:
        last = board_store.get_cache(table, f"catalog:bulk:{source}:last")
        preview = board_store.get_cache(table, f"catalog:bulk:{source}:preview")
        bucket = counts.get(source) or {}
        sources.append(
            {
                "id": source,
                "counts": bucket,
                "available": sum(int(bucket.get(k) or 0) for k in ("new", "approved", "imported")),
                "lastImport": (last or {}).get("payload") if last else None,
                "lastPreview": (preview or {}).get("payload") if preview else None,
            }
        )
    return {
        "sources": sources,
        "launchTarget": BOARD_CATALOG_LAUNCH_LISTING_TARGET,
        "candidateCounts": counts,
    }
