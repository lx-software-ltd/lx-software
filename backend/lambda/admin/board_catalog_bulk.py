"""Bulk catalog import from open data, Places and the candidate queue."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import board_async
import board_catalog_candidates
import board_catalog_import
import board_hk
import board_opendata
import board_store
from contract_constants import (
    BOARD_CATALOG_BULK_SOURCES,
    BOARD_CATALOG_LAUNCH_LISTING_TARGET,
    BOARD_CATALOG_MAX_ORGS_PER_BULK_IMPORT,
    BOARD_CATALOG_SOURCE_CATEGORY,
    BOARD_KEY,
)
from http_common import _log_event

INGEST_BATCH = 500
JOB_STALE_SECONDS = 360
OPEN_DATA_SOURCES = tuple(sorted(board_catalog_candidates.OFFICIAL_SOURCES))
_TERMINAL_CANDIDATE = frozenset({"imported", "rejected", "closed"})

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


def load_source_rows(table: Any, source: str, *, force: bool = False) -> list[dict[str, Any]]:
    if source == "lcsd":
        return list((board_opendata.lcsd_facilities(table, force=force).get("rows") or []))
    if source == "edb":
        return list((board_opendata.edb_kindergartens(table, force=force).get("rows") or []))
    if source == "swd":
        return list((board_opendata.swd_child_care_centres(table, force=force).get("rows") or []))
    if source in ("places", "competitor"):
        return [
            row
            for row in board_store.list_candidates(table, per_status_limit=10_000)
            if str(row.get("source") or "") == source and str(row.get("status") or "") in ("new", "approved")
        ]
    raise BulkImportError(f"unknown catalog source {source}")


def ingest_source(
    table: Any,
    source: str,
    *,
    force: bool = False,
    offset: int = 0,
    limit: int | None = None,
) -> dict[str, Any]:
    board_catalog_candidates.seed_listing_mirror(table)
    rows = load_source_rows(table, source, force=force)
    start = max(0, int(offset or 0))
    batch = rows[start:] if limit is None else rows[start : start + max(0, int(limit))]
    created = 0
    skipped = 0
    official = source in board_catalog_candidates.OFFICIAL_SOURCES
    for raw in batch:
        cand = row_to_candidate(raw, source=source)
        if source not in ("places", "competitor") and board_catalog_candidates.is_duplicate(table, cand):
            skipped += 1
            continue
        doc = board_catalog_candidates.upsert_candidate(table, cand)
        if official and str(doc.get("status") or "") in _TERMINAL_CANDIDATE:
            skipped += 1
            continue
        created += 1
    remaining = max(0, len(rows) - start - len(batch))
    return {
        "source": source,
        "fetched": len(rows),
        "upserted": created,
        "skippedDuplicates": skipped,
        "offset": start,
        "processed": len(batch),
        "remaining": remaining,
    }


def needs_chunked_ingest(row_count: int) -> bool:
    """True when a source will not finish in one ingest batch."""
    return int(row_count or 0) > INGEST_BATCH


def _batches(orgs: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    size = max(1, int(size))
    return [orgs[i : i + size] for i in range(0, len(orgs), size)]


def _approved_for_source(table: Any, source: str) -> list[dict[str, Any]]:
    return [
        row
        for row in board_store.list_candidates(table, "approved", limit=10_000)
        if str(row.get("source") or "") == source
    ]


def _put_job(table: Any, source: str, doc: dict[str, Any]) -> None:
    board_store.put_cache(table, f"catalog:bulk:{source}:job", doc, ttl_seconds=7 * 86400)


def _job(table: Any, source: str) -> dict[str, Any] | None:
    hit = board_store.get_cache(table, f"catalog:bulk:{source}:job")
    payload = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else None
    return payload if isinstance(payload, dict) else None


def _job_age_seconds(job: dict[str, Any] | None) -> float | None:
    if not job or not job.get("at"):
        return None
    try:
        when = board_hk.parse_iso(str(job.get("at") or ""))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - when.astimezone(timezone.utc)).total_seconds())


def _job_is_active(job: dict[str, Any] | None) -> bool:
    if not job or str(job.get("phase") or "") not in ("queued", "running"):
        return False
    age = _job_age_seconds(job)
    if age is None:
        return True
    return age < JOB_STALE_SECONDS


def _ingest_summary_from_job(table: Any, source: str) -> dict[str, Any]:
    job = _job(table, source) or {}
    return {
        "source": source,
        "fetched": int(job.get("fetched") or 0),
        "upserted": int(job.get("upserted") or 0),
        "skippedDuplicates": int(job.get("skippedDuplicates") or 0),
        "processed": int(job.get("processed") or 0),
        "remaining": int(job.get("remaining") or 0),
    }


def preview_source(
    table: Any,
    source: str,
    *,
    remote: bool = False,
    limit: int | None = None,
    skip_ingest: bool = False,
) -> dict[str, Any]:
    if source not in BOARD_CATALOG_BULK_SOURCES:
        raise BulkImportError(f"unknown catalog source {source}")
    if not board_catalog_import.import_enabled():
        raise BulkImportError("catalog import is switched off (SiutindeiBoardCatalogImportEnabled)")
    ingest = _ingest_summary_from_job(table, source) if skip_ingest else ingest_source(table, source)
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


def _org_name_key(name: Any) -> str:
    """Match siutindei ``results[].key`` (truncated to 80) against our 200-char names."""
    return str(name or "").strip()[:80]


def _succeeded_org_names(imported: dict[str, Any], batch: list[dict[str, Any]]) -> set[str]:
    created = set(board_catalog_import._org_result_names(imported.get("results") or [], "created"))  # noqa: SLF001
    updated = set(board_catalog_import._org_result_names(imported.get("results") or [], "updated"))  # noqa: SLF001
    named = {_org_name_key(n) for n in (created | updated) if n}
    failed = int((imported.get("summary") or {}).get("failed") or 0)
    batch_names = {_org_name_key(org.get("name")) for org in batch if org.get("name")}
    if failed == 0:
        return batch_names
    if named:
        return named & batch_names
    return set()


def import_source(
    table: Any,
    source: str,
    *,
    remote: bool = True,
    limit: int | None = None,
    skip_ingest: bool = False,
) -> dict[str, Any]:
    board_catalog_candidates.seed_listing_mirror(table)
    preview = preview_source(table, source, remote=False, limit=limit, skip_ingest=skip_ingest)
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
        try:
            imported = board_catalog_import._run_remote_import({"organizations": batch}, token)  # noqa: SLF001
        except board_catalog_import.CatalogImportError as exc:
            results.append({"ok": False, "error": str(exc)[:300]})
            continue
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
        succeeded = _succeeded_org_names(imported, batch)
        for row, org in zip(rows, batch):
            if _org_name_key(org.get("name")) not in succeeded:
                continue
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
                "job": _job(table, source),
            }
        )
    return {
        "sources": sources,
        "launchTarget": BOARD_CATALOG_LAUNCH_LISTING_TARGET,
        "candidateCounts": counts,
    }


def queue_action(
    table: Any,
    action: str,
    source: str,
    *,
    remote: bool = True,
    limit: int | None = None,
    requested_by: str = "owner",
    offset: int = 0,
    force: bool = False,
) -> dict[str, Any]:
    if action not in ("preview", "import", "ingest"):
        raise BulkImportError(f"unknown catalog bulk action {action}")
    if source not in BOARD_CATALOG_BULK_SOURCES:
        raise BulkImportError(f"unknown catalog source {source}")
    if action in ("preview", "import") and not board_catalog_import.import_enabled():
        raise BulkImportError("catalog import is switched off (SiutindeiBoardCatalogImportEnabled)")
    if action == "import" and not board_catalog_import.configured():
        raise BulkImportError("catalog import is not configured")
    existing = _job(table, source)
    if _job_is_active(existing):
        return {
            "ok": True,
            "queued": True,
            "invoked": False,
            "alreadyRunning": True,
            "source": source,
            "action": str((existing or {}).get("action") or action),
            "job": existing,
        }
    _put_job(
        table,
        source,
        {
            "phase": "queued",
            "action": action,
            "at": board_store.now_iso(),
            "requestedBy": requested_by,
            "offset": int(offset or 0),
        },
    )
    payload = {
        "internal": "board_catalog_bulk",
        "boardKey": BOARD_KEY,
        "action": action,
        "source": source,
        "remote": remote,
        "limit": limit,
        "requestedBy": requested_by,
        "offset": int(offset or 0),
        "force": bool(force),
    }
    invoked = board_async.try_invoke_event(payload)
    if not invoked:
        _log_event("warning", tag="board_catalog_bulk_enqueue_deferred", action=action, source=source)
    return {"ok": True, "queued": True, "invoked": invoked, "source": source, "action": action}


def _job_payload(event: dict[str, Any], **updates: Any) -> dict[str, Any]:
    payload = {
        "internal": "board_catalog_bulk",
        "boardKey": event.get("boardKey") or BOARD_KEY,
        "action": str(event.get("action") or ""),
        "source": str(event.get("source") or ""),
        "remote": event.get("remote") is not False,
        "limit": event.get("limit"),
        "requestedBy": event.get("requestedBy") or "owner",
        "offset": int(event.get("offset") or 0),
        "force": bool(event.get("force")),
        "ingestDone": bool(event.get("ingestDone")),
        "upserted": int(event.get("upserted") or 0),
        "skippedDuplicates": int(event.get("skippedDuplicates") or 0),
        "processed": int(event.get("processed") or 0),
        "fetched": int(event.get("fetched") or 0),
    }
    payload.update(updates)
    return payload


def _add_ingest_totals(event: dict[str, Any], chunk: dict[str, Any]) -> dict[str, int]:
    return {
        "upserted": int(event.get("upserted") or 0) + int(chunk.get("upserted") or 0),
        "skippedDuplicates": int(event.get("skippedDuplicates") or 0) + int(chunk.get("skippedDuplicates") or 0),
        "processed": int(event.get("processed") or 0) + int(chunk.get("processed") or 0),
        "fetched": int(chunk.get("fetched") or event.get("fetched") or 0),
    }


def _continue_job(table: Any, event: dict[str, Any], **updates: Any) -> bool:
    invoked = board_async.try_invoke_event(_job_payload(event, **updates))
    if invoked:
        return True
    source = str(event.get("source") or "")
    action = str(event.get("action") or "")
    _log_event("warning", tag="board_catalog_bulk_enqueue_deferred", action=action, source=source)
    _put_job(
        table,
        source,
        {
            "phase": "error",
            "action": action,
            "at": board_store.now_iso(),
            "error": "failed to enqueue next ingest chunk",
            "offset": updates.get("offset", event.get("offset") or 0),
            "remaining": updates.get("remaining"),
            "upserted": updates.get("upserted", event.get("upserted") or 0),
            "skippedDuplicates": updates.get("skippedDuplicates", event.get("skippedDuplicates") or 0),
            "processed": updates.get("processed", event.get("processed") or 0),
            "fetched": updates.get("fetched", event.get("fetched") or 0),
        },
    )
    return False


def handle_job(event: dict[str, Any]) -> dict[str, Any]:
    if not board_store.event_targets_this_board(event):
        return {"ok": True, "skipped": "other-board"}
    table = board_store.records_table()
    action = str(event.get("action") or "")
    source = str(event.get("source") or "")
    limit = event.get("limit")
    remote = event.get("remote") is not False
    offset = max(0, int(event.get("offset") or 0))
    _put_job(table, source, {"phase": "running", "action": action, "at": board_store.now_iso(), "offset": offset})
    try:
        already_ingested = False
        needs_chunk = action == "ingest" or (action in ("preview", "import") and not event.get("ingestDone"))
        if needs_chunk:
            already_ingested = True
            force = bool(event.get("force")) if "force" in event else offset == 0
            out = ingest_source(table, source, force=force, offset=offset, limit=INGEST_BATCH)
            remaining = int(out.get("remaining") or 0)
            processed = int(out.get("processed") or 0)
            next_offset = offset + processed
            totals = _add_ingest_totals(event, out)
            job_progress = {
                "phase": "running",
                "action": action,
                "at": board_store.now_iso(),
                "offset": next_offset,
                "remaining": remaining,
                **totals,
            }
            _put_job(table, source, job_progress)
            if remaining > 0:
                if not _continue_job(table, event, offset=next_offset, force=False, remaining=remaining, **totals):
                    return {**out, **totals, "ok": False, "error": "failed to enqueue next ingest chunk", "continued": False}
                return {**out, **totals, "ok": True, "continued": True}
            if action == "ingest":
                _put_job(
                    table,
                    source,
                    {
                        "phase": "done",
                        "action": action,
                        "at": board_store.now_iso(),
                        "ok": True,
                        "offset": next_offset,
                        "remaining": 0,
                        **totals,
                    },
                )
                return {**out, **totals, "ok": True}
            if processed >= INGEST_BATCH or offset > 0:
                if not _continue_job(
                    table, event, ingestDone=True, offset=0, force=False, remaining=0, **totals
                ):
                    return {**out, **totals, "ok": False, "error": "failed to enqueue next ingest chunk", "ingestDone": False}
                return {**out, **totals, "ok": True, "ingestDone": True}
        skip_ingest = already_ingested or bool(event.get("ingestDone"))
        if action == "preview":
            out = preview_source(
                table,
                source,
                remote=remote,
                limit=limit,
                skip_ingest=skip_ingest,
            )
        elif action == "import":
            out = import_source(table, source, limit=limit, skip_ingest=skip_ingest)
        else:
            raise BulkImportError(f"unknown catalog bulk action {action}")
        prior = _job(table, source) or {}
        _put_job(
            table,
            source,
            {
                "phase": "done",
                "action": action,
                "at": board_store.now_iso(),
                "ok": out.get("ok"),
                "imported": out.get("imported"),
                "approved": out.get("approved") or (out.get("preview") or {}).get("approved"),
                "fetched": prior.get("fetched") or event.get("fetched") or (out.get("ingest") or {}).get("fetched"),
                "upserted": prior.get("upserted") or event.get("upserted") or (out.get("ingest") or {}).get("upserted"),
                "skippedDuplicates": prior.get("skippedDuplicates")
                or event.get("skippedDuplicates")
                or (out.get("ingest") or {}).get("skippedDuplicates"),
                "processed": prior.get("processed") or event.get("processed") or (out.get("ingest") or {}).get("processed"),
                "remaining": 0,
            },
        )
        return out
    except (BulkImportError, board_catalog_import.CatalogImportError) as exc:
        _put_job(
            table,
            source,
            {"phase": "error", "action": action, "at": board_store.now_iso(), "error": str(exc)[:300]},
        )
        return {"ok": False, "error": str(exc)[:300], "source": source, "action": action}
    except Exception as exc:
        _log_event(
            "error",
            tag="board_catalog_bulk_job_failed",
            action=action,
            source=source,
            error=str(exc)[:300],
        )
        _put_job(
            table,
            source,
            {"phase": "error", "action": action, "at": board_store.now_iso(), "error": str(exc)[:300]},
        )
        return {"ok": False, "error": str(exc)[:300], "source": source, "action": action}
