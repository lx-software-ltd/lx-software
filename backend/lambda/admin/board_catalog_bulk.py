"""Bulk catalog import from open data, Places and the candidate queue."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import board_async
import board_catalog_candidates
import board_catalog_import
import board_hk
import board_opendata
import board_store
from contract_constants import (
    BOARD_CATALOG_AUTO_BULK_MIN_APPROVED,
    BOARD_CATALOG_BULK_SOURCES,
    BOARD_CATALOG_LAUNCH_LISTING_TARGET,
    BOARD_CATALOG_MAX_ORGS_PER_BULK_IMPORT,
    BOARD_CATALOG_SOURCE_CATEGORY,
    BOARD_KEY,
)
from http_common import _log_event

INGEST_BATCH = 500
JOB_STALE_SECONDS = 360
_BISECT_MAX_CALLS = 8
_HTTP_500_RE = re.compile(r"(?:failed:\s*500\b|\bHTTP/?\s*500\b|\bstatus(?:\s+code)?\s*500\b)", re.IGNORECASE)
BULK_500_EVENT = "catalog-bulk-500"
IMPORTER_ISSUE_TITLE = "Make activity_schedule_entries inserts idempotent"
SCHEDULES_DROPPED_NOTE = "schedules dropped after HTTP 500"
_REQUEST_ID_RE = re.compile(r"requestId=([0-9a-fA-F-]{8,})")
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


def load_source_payload(table: Any, source: str, *, force: bool = False) -> dict[str, Any]:
    if source == "lcsd":
        return board_opendata.lcsd_facilities(table, force=force)
    if source == "edb":
        return board_opendata.edb_kindergartens(table, force=force)
    if source == "swd":
        return board_opendata.swd_child_care_centres(table, force=force)
    if source in ("places", "competitor"):
        rows = [
            row
            for row in board_store.list_candidates(table, per_status_limit=10_000)
            if str(row.get("source") or "") == source and str(row.get("status") or "") in ("new", "approved")
        ]
        return {"rows": rows, "fetchedAt": board_store.now_iso(), "rowCount": len(rows)}
    raise BulkImportError(f"unknown catalog source {source}")


def load_source_rows(table: Any, source: str, *, force: bool = False) -> list[dict[str, Any]]:
    return list(load_source_payload(table, source, force=force).get("rows") or [])


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
        if doc.get("skipped") or (official and str(doc.get("status") or "") in _TERMINAL_CANDIDATE):
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


def _is_http_500(message: str) -> bool:
    return bool(_HTTP_500_RE.search(message or ""))


def _http500_key(source: str) -> str:
    return f"catalog:bulk:{source}:http500"


def _http500_counts(table: Any, source: str) -> dict[str, int]:
    hit = board_store.get_cache(table, _http500_key(source))
    payload = hit.get("payload") if isinstance(hit, dict) else None
    raw = payload.get("counts") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in raw.items():
        try:
            out[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def _source_pause_key(source: str) -> str:
    return f"catalog:bulk:{source}:paused"


def _other_source_imported_recently(table: Any, source: str, *, hours: int = 24) -> bool:
    """True when another bulk source imported successfully in the last ``hours``."""
    cut = datetime.now(timezone.utc).timestamp() - max(1, int(hours)) * 3600
    for other in BOARD_CATALOG_BULK_SOURCES:
        if other == source:
            continue
        last = board_store.get_cache(table, f"catalog:bulk:{other}:last")
        payload = (last or {}).get("payload") if isinstance(last, dict) else None
        if not isinstance(payload, dict):
            continue
        try:
            imported = int(payload.get("imported") or 0)
        except (TypeError, ValueError):
            imported = 0
        if imported <= 0:
            continue
        at = str(payload.get("at") or "")
        try:
            stamp = datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        if stamp >= cut:
            return True
    return False


def _probe_remote_dry_run(
    token: str,
    org: dict[str, Any] | None,
    *,
    budget: list[int],
    results: list[dict[str, Any]],
) -> bool:
    """One-row remote dry-run as a 'server is up' signal. False on failure/budget."""
    if not org or budget[0] <= 0:
        return False
    budget[0] -= 1
    try:
        dry = board_catalog_import._remote_dry_run(  # noqa: SLF001
            {"organizations": [org]},
            token,
        )
    except board_catalog_import.CatalogImportError as exc:
        results.append({"ok": False, "error": str(exc)[:300], "probe": "dry_run"})
        return False
    ok = bool(dry.get("ok"))
    results.append({"ok": ok, "probe": "dry_run", "summary": dry.get("summary")})
    return ok


def _importer_server_up(
    table: Any,
    source: str,
    token: str,
    org: dict[str, Any] | None,
    *,
    budget: list[int],
    results: list[dict[str, Any]],
) -> bool:
    """Distinguish a total outage from a systematic importer bug."""
    if _other_source_imported_recently(table, source):
        return True
    return _probe_remote_dry_run(token, org, budget=budget, results=results)


def _pause_source_until_issue(table: Any, source: str) -> None:
    """Block auto re-holds for this source until the GitHub issue Approval is decided."""
    board_store.put_cache(
        table,
        _source_pause_key(source),
        {"pausedAt": board_store.now_iso(), "reason": "systematic_http_500"},
        ttl_seconds=14 * 86400,
    )


def source_is_paused(table: Any, source: str) -> bool:
    """True while a systematic-500 pause is active and its Approval is still open."""
    hit = board_store.get_cache(table, _source_pause_key(source))
    if not hit:
        return False
    if _importer_issue_already_decided(table):
        board_store.put_cache(table, _source_pause_key(source), {}, ttl_seconds=1)
        return False
    return True


def _last_import_older_than(table: Any, source: str, *, hours: int = 24) -> bool:
    last = board_store.get_cache(table, f"catalog:bulk:{source}:last")
    payload = (last or {}).get("payload") if isinstance(last, dict) else None
    at = str((payload or {}).get("at") or "") if isinstance(payload, dict) else ""
    if not at:
        return True
    try:
        stamp = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) - stamp >= timedelta(hours=max(1, int(hours)))


def _propose_systematic_500_issue(
    table: Any,
    settings: dict[str, Any],
    source: str,
    error: str,
    request_id: str,
) -> None:
    """Founder Approval: importer returns 500 on every half while the server answers dry-runs."""
    import board_github
    import board_tools

    if _importer_issue_already_decided(table):
        return
    title = IMPORTER_ISSUE_TITLE
    body = (
        "A catalog bulk import of source "
        f"`{source}` received HTTP 500 on both bisect halves with no successful "
        "batch, while a one-row remote dry-run (or another source's recent import) "
        "showed the importer is reachable. That points at a systematic bug rather "
        "than a total outage.\n\n"
        "Bisect continues across runs via persisted sub-batch fingerprints; auto "
        f"re-holds for `{source}` are paused until this Approval is decided.\n\n"
        f"requestId: {request_id or 'unknown'}\n"
        f"Latest client error: {error or 'unknown'}"
    )[:4000]
    arguments = {
        "title": title,
        "body": body,
        "labels": ["bug"],
        "reason": "Catalog bulk import both-halves HTTP 500 with server-up signal.",
    }
    try:
        blocked = board_github.validate_create_issue(arguments)
    except Exception as exc:
        _log_event("info", tag="board_catalog_bulk_500_issue_skipped", error=str(exc)[:200])
        blocked = None
    if blocked:
        return
    ctx = board_tools.ToolContext(
        table=table,
        settings=settings,
        persona_id="cto",
        display_name="CTO",
        kind="internal",
        actor="persona",
        task_id="catalog-bulk-500",
    )
    try:
        board_tools.create_approval(
            ctx,
            board_tools.REGISTRY["github_create_issue"],
            arguments,
            summary=f"Open GitHub issue: {title}",
        )
    except Exception as exc:
        _log_event("info", tag="board_catalog_bulk_500_issue_skipped", error=str(exc)[:200])


def _batch_fingerprint(ids: list[str]) -> str:
    """Stable id for a batch. Sorting means candidate order cannot move the key."""
    cleaned = sorted({str(item) for item in ids if item})
    if not cleaned:
        return ""
    return hashlib.sha256("\n".join(cleaned).encode()).hexdigest()[:16]


def _note_http500(table: Any, source: str, batch_key: str) -> None:
    counts = _http500_counts(table, source)
    counts[batch_key] = int(counts.get(batch_key) or 0) + 1
    board_store.put_cache(table, _http500_key(source), {"counts": counts}, ttl_seconds=7 * 86400)


def _clear_http500(table: Any, source: str, batch_key: str) -> None:
    counts = _http500_counts(table, source)
    if batch_key not in counts:
        return
    counts.pop(batch_key, None)
    board_store.put_cache(table, _http500_key(source), {"counts": counts}, ttl_seconds=7 * 86400)


def _close_server_error_row(table: Any, row: dict[str, Any], error: str) -> None:
    doc = board_catalog_candidates.set_status(table, str(row["candidateId"]), "closed")
    doc["closeReason"] = error[:300]
    board_store.put_candidate(table, doc)


def _note_schedules_dropped(table: Any, row: dict[str, Any]) -> None:
    """The row imported only after weekly hours were removed."""
    candidate_id = str(row.get("candidateId") or "")
    if not candidate_id:
        return
    doc = board_store.get_candidate(table, candidate_id) or dict(row)
    doc["importNote"] = SCHEDULES_DROPPED_NOTE
    doc["updatedAt"] = board_store.now_iso()
    board_store.put_candidate(table, doc)


def _request_id(error: str) -> str:
    match = _REQUEST_ID_RE.search(error or "")
    return match.group(1) if match else ""


def _org_has_schedules(org: dict[str, Any]) -> bool:
    for activity in org.get("activities") or []:
        if isinstance(activity, dict) and activity.get("schedules"):
            return True
    return bool(org.get("schedules"))


def _without_schedules(org: dict[str, Any]) -> dict[str, Any]:
    """Same organisation with weekly hours removed, for one retry after a schedule 500."""
    clone = dict(org)
    clone.pop("schedules", None)
    activities = []
    for activity in org.get("activities") or []:
        if isinstance(activity, dict):
            activities.append({k: v for k, v in activity.items() if k != "schedules"})
        else:
            activities.append(activity)
    if activities:
        clone["activities"] = activities
    return clone


def _mark_imported(table: Any, rows: list[dict[str, Any]], batch: list[dict[str, Any]], imported: dict[str, Any]) -> list[str]:
    succeeded = _succeeded_org_names(imported, batch)
    ids: list[str] = []
    for row, org in zip(rows, batch):
        if _org_name_key(org.get("name")) not in succeeded:
            continue
        board_catalog_candidates.set_status(table, str(row["candidateId"]), "imported")
        board_catalog_candidates.remember_listing(table, org)
        ids.append(str(row["candidateId"]))
    return ids


def _call_import(
    table: Any,
    source: str,
    batch: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    token: str,
    *,
    budget: list[int],
    results: list[dict[str, Any]],
    imported_ids: list[str],
) -> tuple[str, str]:
    """One remote import. ``ok`` means the server answered; ``http500`` is the bisect signal."""
    if budget[0] <= 0:
        return "budget", ""
    budget[0] -= 1
    try:
        imported = board_catalog_import._run_remote_import(  # noqa: SLF001
            {"organizations": batch},
            token,
            timeout=board_catalog_import._BULK_IMPORT_HTTP_TIMEOUT,
        )
    except board_catalog_import.CatalogImportError as exc:
        message = str(exc)[:300]
        if _is_http_500(message):
            return "http500", message
        return "error", message
    failed = int((imported.get("summary") or {}).get("failed") or 0)
    results.append(
        {
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
    )
    imported_ids.extend(_mark_imported(table, rows, batch, imported))
    ids = [str(row.get("candidateId") or "") for row in rows if row.get("candidateId")]
    fingerprint = _batch_fingerprint(ids)
    if fingerprint:
        _clear_http500(table, source, fingerprint)
    return "ok", ""


def _import_group(
    table: Any,
    source: str,
    batch: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    token: str,
    *,
    bisecting: bool,
    budget: list[int],
    results: list[dict[str, Any]],
    imported_ids: list[str],
    closed: list[dict[str, str]],
    remaining: list[str],
    saw_success: list[bool],
    schedules_dropped: list[dict[str, str]],
    known: tuple[str, str] | None = None,
) -> None:
    """Import one batch.

    A repeated HTTP 500 is split only after some other batch in this run has
    succeeded. Both halves returning 500 with no success is an outage when the
    importer is unreachable (rows stay approved; the next hold retries). When a
    dry-run or another source's recent import shows the server is up, sub-batch
    fingerprints are persisted, remaining ids continue across runs, a GitHub
    issue is proposed, and the source is paused until that Approval is decided.
    A single row is closed only when a sibling batch in the same run succeeded.
    """
    ids = [str(row.get("candidateId") or "") for row in rows if row.get("candidateId")]
    if not batch or not rows:
        return
    if known is None:
        if budget[0] <= 0:
            remaining.extend(ids)
            return
        status, message = _call_import(
            table,
            source,
            batch,
            rows,
            token,
            budget=budget,
            results=results,
            imported_ids=imported_ids,
        )
    else:
        status, message = known
    if status == "budget":
        remaining.extend(ids)
        return
    if status == "ok":
        saw_success[0] = True
        return
    if status != "http500":
        results.append({"ok": False, "error": message})
        return
    fingerprint = _batch_fingerprint(ids)
    if not fingerprint:
        results.append({"ok": False, "error": message})
        return
    repeated = bisecting or int(_http500_counts(table, source).get(fingerprint) or 0) >= 1
    if not repeated:
        _note_http500(table, source, fingerprint)
        results.append({"ok": False, "error": message, "batch": fingerprint})
        return
    if len(batch) <= 1:
        if saw_success[0]:
            if _org_has_schedules(batch[0]):
                if budget[0] <= 0:
                    remaining.extend(ids)
                    return
                retry_status, retry_message = _call_import(
                    table,
                    source,
                    [_without_schedules(batch[0])],
                    rows,
                    token,
                    budget=budget,
                    results=results,
                    imported_ids=imported_ids,
                )
                if retry_status == "ok":
                    _note_schedules_dropped(table, rows[0])
                    schedules_dropped.append(
                        {
                            "candidateId": ids[0],
                            "name": str(rows[0].get("nameEn") or rows[0].get("name") or ""),
                            "error": message,
                        }
                    )
                    return
                if retry_status == "budget":
                    remaining.extend(ids)
                    return
                if retry_status != "http500":
                    results.append({"ok": False, "error": retry_message, "candidateId": ids[0]})
                    return
                message = retry_message or message
            _close_server_error_row(table, rows[0], message)
            closed.append(
                {
                    "candidateId": ids[0],
                    "name": str(rows[0].get("nameEn") or rows[0].get("name") or ""),
                    "error": message,
                }
            )
            results.append({"ok": False, "error": message, "closed": ids[0]})
        else:
            results.append({"ok": False, "error": message, "candidateId": ids[0]})
        return
    mid = len(batch) // 2
    left_batch, left_rows = batch[:mid], rows[:mid]
    right_batch, right_rows = batch[mid:], rows[mid:]
    if saw_success[0]:
        _import_group(
            table, source, left_batch, left_rows, token,
            bisecting=True, budget=budget, results=results, imported_ids=imported_ids,
            closed=closed, remaining=remaining, saw_success=saw_success,
            schedules_dropped=schedules_dropped,
        )
        _import_group(
            table, source, right_batch, right_rows, token,
            bisecting=True, budget=budget, results=results, imported_ids=imported_ids,
            closed=closed, remaining=remaining, saw_success=saw_success,
            schedules_dropped=schedules_dropped,
        )
        return
    left_ids = [str(row.get("candidateId") or "") for row in left_rows if row.get("candidateId")]
    right_ids = [str(row.get("candidateId") or "") for row in right_rows if row.get("candidateId")]
    left_status, left_message = _call_import(
        table, source, left_batch, left_rows, token,
        budget=budget, results=results, imported_ids=imported_ids,
    )
    if left_status == "ok":
        saw_success[0] = True
    elif left_status == "budget":
        remaining.extend(left_ids)
    elif left_status == "error":
        results.append({"ok": False, "error": left_message})
    right_status, right_message = _call_import(
        table, source, right_batch, right_rows, token,
        budget=budget, results=results, imported_ids=imported_ids,
    )
    if right_status == "ok":
        saw_success[0] = True
    elif right_status == "budget":
        remaining.extend(right_ids)
    elif right_status == "error":
        results.append({"ok": False, "error": right_message})
    if not saw_success[0]:
        if left_status == "http500":
            results.append({"ok": False, "error": left_message})
        if right_status == "http500":
            results.append({"ok": False, "error": right_message})
        # Both halves 500 with no success: outage vs systematic bug.
        probe_org = left_batch[0] if left_batch else (right_batch[0] if right_batch else None)
        if _importer_server_up(table, source, token, probe_org, budget=budget, results=results):
            error = left_message or right_message
            for half_rows, half_status in ((left_rows, left_status), (right_rows, right_status)):
                if half_status != "http500":
                    continue
                half_ids = [str(row.get("candidateId") or "") for row in half_rows if row.get("candidateId")]
                fingerprint = _batch_fingerprint(half_ids)
                if fingerprint:
                    _note_http500(table, source, fingerprint)
                remaining.extend(half_ids)
            try:
                _propose_systematic_500_issue(
                    table,
                    board_store.load_settings(table),
                    source,
                    error,
                    _request_id(error),
                )
            except Exception as exc:
                _log_event("info", tag="board_catalog_bulk_500_issue_skipped", source=source, error=str(exc)[:200])
            _pause_source_until_issue(table, source)
        return
    if left_status == "http500":
        _import_group(
            table, source, left_batch, left_rows, token,
            bisecting=True, budget=budget, results=results, imported_ids=imported_ids,
            closed=closed, remaining=remaining, saw_success=saw_success,
            schedules_dropped=schedules_dropped,
            known=("http500", left_message),
        )
    if right_status == "http500":
        _import_group(
            table, source, right_batch, right_rows, token,
            bisecting=True, budget=budget, results=results, imported_ids=imported_ids,
            closed=closed, remaining=remaining, saw_success=saw_success,
            schedules_dropped=schedules_dropped,
            known=("http500", right_message),
        )


def import_source(
    table: Any,
    source: str,
    *,
    remote: bool = True,
    limit: int | None = None,
    skip_ingest: bool = False,
    only_ids: list[str] | None = None,
    bisect: bool = False,
) -> dict[str, Any]:
    board_catalog_candidates.seed_listing_mirror(table)
    preview = preview_source(table, source, remote=False, limit=limit, skip_ingest=skip_ingest)
    if not board_catalog_import.import_enabled() or not board_catalog_import.configured():
        raise BulkImportError("catalog import is not configured")
    approved = _approved_for_source(table, source)
    if only_ids:
        wanted = {str(item) for item in only_ids if item}
        approved = [row for row in approved if str(row.get("candidateId") or "") in wanted]
    mid = board_catalog_import.catalog_manager_id()
    orgs = [candidate_to_org(row, manager_id=mid) for row in approved]
    if limit is not None:
        orgs = orgs[: max(0, int(limit))]
        approved = approved[: len(orgs)]
    token = board_catalog_import._id_token()  # noqa: SLF001
    results: list[dict[str, Any]] = []
    imported_ids: list[str] = []
    closed: list[dict[str, str]] = []
    remaining: list[str] = []
    schedules_dropped: list[dict[str, str]] = []
    budget = [_BISECT_MAX_CALLS]
    saw_success = [False]
    for batch, rows in zip(_batches(orgs, BOARD_CATALOG_MAX_ORGS_PER_BULK_IMPORT), _batches(approved, BOARD_CATALOG_MAX_ORGS_PER_BULK_IMPORT)):
        _import_group(
            table,
            source,
            batch,
            rows,
            token,
            bisecting=bool(bisect),
            budget=budget,
            results=results,
            imported_ids=imported_ids,
            closed=closed,
            remaining=remaining,
            saw_success=saw_success,
            schedules_dropped=schedules_dropped,
        )
    board_store.put_cache(
        table,
        f"catalog:bulk:{source}:last",
        {"at": board_store.now_iso(), "imported": len(imported_ids), "batches": len(results)},
        ttl_seconds=40 * 86400,
    )
    _log_event(
        "info",
        tag="board_catalog_bulk_import",
        source=source,
        imported=len(imported_ids),
        batches=len(results),
        closed=len(closed),
    )
    if schedules_dropped:
        try:
            names = ", ".join(str(row.get("name") or row.get("candidateId") or "") for row in schedules_dropped[:12])
            error = str(schedules_dropped[0].get("error") or "")[:300]
            _propose_importer_issue(
                table,
                board_store.load_settings(table),
                source,
                names,
                error,
                _request_id(error),
            )
        except Exception as exc:
            _log_event("info", tag="board_catalog_importer_issue_skipped", source=source, error=str(exc)[:200])
    return {
        "ok": all(r.get("ok") for r in results) if results else True,
        "source": source,
        "imported": len(imported_ids),
        "batches": results,
        "closed": closed,
        "schedulesDropped": schedules_dropped,
        "bisectRemaining": remaining,
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
    settings = board_store.load_settings(table)
    return {
        "sources": sources,
        "launchTarget": launch_listing_target(settings),
        "candidateCounts": counts,
    }


def launch_listing_target(settings: dict[str, Any] | None) -> int:
    """Owner ``settings.catalog.launchListingTarget``, else the contract constant."""
    catalog = (settings or {}).get("catalog") if isinstance(settings, dict) else None
    if isinstance(catalog, dict) and catalog.get("launchListingTarget") not in (None, ""):
        try:
            value = int(catalog.get("launchListingTarget"))
        except (TypeError, ValueError):
            value = -1
        if 0 <= value <= 100_000:
            return value
    return BOARD_CATALOG_LAUNCH_LISTING_TARGET


def venue_linked_providers(listings: dict[str, Any] | None) -> int:
    """Providers that have a venue.

    Prefers ``providersWithVenue`` from ``v_catalog_provider_counts`` (one
    organisation, and only when it has a named district). A payload without
    that field keeps the provider total.
    """
    payload = listings or {}
    linked = payload.get("providersWithVenue")
    if linked is not None:
        try:
            return max(0, int(linked))
        except (TypeError, ValueError):
            pass
    try:
        return max(0, int(payload.get("providers") or 0))
    except (TypeError, ValueError):
        return 0


def auto_import_row_limit(table: Any, settings: dict[str, Any] | None = None) -> int:
    """Approved rows still allowed before venue-linked providers hit the launch target.

    A missing cache counts as zero providers, so the first auto-import is still
    capped at the target. ``providersWithVenue`` is the distinct count from
    ``v_catalog_provider_counts`` when that view is cached; otherwise it is the
    sum of district cells that are not "No venue linked". A payload without
    the field keeps using the provider total.
    """
    providers = 0
    try:
        import board_progress

        providers = venue_linked_providers(board_progress._listings(table, {}))  # noqa: SLF001
    except Exception as exc:
        _log_event("info", tag="board_catalog_auto_bulk_cap_unavailable", error=str(exc)[:200])
        providers = 0
    return max(0, launch_listing_target(settings) - providers)


def maybe_queue_auto_imports(table: Any, settings: dict[str, Any]) -> dict[str, Any]:
    """When auto-import is on, schedule one catalog_import hold for a ready source."""
    if not board_catalog_import.auto_import_enabled(settings):
        return {"queued": []}
    if not board_catalog_import.import_enabled() or not board_catalog_import.configured():
        return {"queued": []}
    room = auto_import_row_limit(table, settings)
    if room <= 0:
        return {"queued": [], "reason": "launch target reached"}
    counts = board_catalog_candidates.counts_by_source(table)
    held_sources = _held_bulk_sources(table)
    ready: list[tuple[int, str]] = []
    for source in BOARD_CATALOG_BULK_SOURCES:
        approved = int((counts.get(source) or {}).get("approved") or 0)
        if approved <= 0:
            continue
        if approved < BOARD_CATALOG_AUTO_BULK_MIN_APPROVED and not _last_import_older_than(
            table, source, hours=24
        ):
            continue
        if source in held_sources or _job_is_active(_job(table, source)):
            continue
        if source_is_paused(table, source):
            continue
        ready.append((approved, source))
    if not ready:
        return {"queued": []}
    ready.sort(reverse=True)
    source = ready[0][1]
    limit = min(int(ready[0][0]), room)
    out = _schedule_or_run_bulk(table, settings, source, approved=limit, limit=limit)
    return {"queued": [source], "limit": limit, **out}


def _held_bulk_sources(table: Any) -> set[str]:
    out: set[str] = set()
    for hold in board_store.list_holds(table, "scheduled", limit=400):
        if str(hold.get("op") or "") != "catalog_bulk_import":
            continue
        source = str((hold.get("arguments") or {}).get("source") or "")
        if source:
            out.add(source)
    return out


def _schedule_or_run_bulk(
    table: Any, settings: dict[str, Any], source: str, *, approved: int, limit: int | None = None
) -> dict[str, Any]:
    import board_holds
    import board_tools

    hours = board_holds.hold_hours(table, settings, "catalog_import", "catalog_import")
    if hours <= 0:
        job = queue_action(table, "import", source, requested_by="auto", limit=limit)
        _log_event("info", tag="board_catalog_auto_bulk_queued", source=source, approved=approved, limit=limit)
        return {"job": job, "held": False}
    op = board_tools.REGISTRY.get("catalog_bulk_import")
    if op is None:
        return {"held": False}
    ctx = board_tools.ToolContext(
        table=table,
        settings=settings,
        persona_id="",
        display_name="catalog sweep",
        kind="internal",
        actor="internal",
        internal=True,
    )
    hold = board_holds.create_hold(
        ctx,
        op,
        {"source": source, "reason": "auto bulk-import", "limit": int(limit or approved)},
        action_class="catalog_import",
        class_key="catalog_import",
        hours=hours,
        summary=f"Import catalog source {source} ({approved} approved)",
    )
    _log_event(
        "info",
        tag="board_catalog_auto_bulk_held",
        source=source,
        approved=approved,
        holdId=hold.get("holdId"),
        executeAt=hold.get("executeAt"),
    )
    return {"hold": hold, "held": True}


def op_import_source(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    source = str(args.get("source") or "").strip()
    requested = "auto" if getattr(ctx, "internal", False) or getattr(ctx, "actor", "") in ("hold", "internal") else str(
        getattr(ctx, "actor", "") or "owner"
    )
    limit = None
    if args.get("limit") is not None:
        try:
            limit = max(1, int(args.get("limit")))
        except (TypeError, ValueError):
            limit = None
    return queue_action(ctx.table, "import", source, requested_by=requested, limit=limit)


def _open_bulk_500_task(table: Any, settings: dict[str, Any], source: str, closed: list[dict[str, str]]) -> None:
    """One CTO task per source while rows closed by a repeated HTTP 500 are outstanding."""
    if not closed:
        return
    from board_triage import find_open_event_task

    event_id = f"{BULK_500_EVENT}:{source}"
    names = ", ".join(str(row.get("name") or row.get("candidateId") or "") for row in closed[:12])
    error = str(closed[0].get("error") or "")[:300]
    request_id = _request_id(error)
    id_note = f" requestId={request_id}." if request_id else ""
    if not find_open_event_task(table, "ops", event_id):
        _create_bulk_500_task(
            table, settings, source, names, error, request_id, event_id, id_note, len(closed)
        )


def _create_bulk_500_task(
    table: Any,
    settings: dict[str, Any],
    source: str,
    names: str,
    error: str,
    request_id: str,
    event_id: str,
    id_note: str,
    closed_count: int,
) -> None:
    import board_staff

    try:
        board_staff.create_task(
            table,
            settings,
            assignee="cto",
            origin="duty",
            brief=(
                f"siutindei POST /v1/admin/imports returned HTTP 500 twice for catalog source {source}. "
                f"The offending rows were closed and will not be retried: {names}.{id_note} Latest: {error}."
            )[:4000],
            deliverable_type="markdown",
            sla_hours=24,
            event_ref={
                "kind": "ops",
                "id": event_id,
                "source": source,
                "closed": closed_count,
                "requestId": request_id,
            },
            created_by="board_catalog_bulk",
        )
    except board_staff.StaffError as exc:
        _log_event("info", tag="board_catalog_bulk_500_task_skipped", source=source, error=str(exc)[:200])


def _importer_issue_already_decided(table: Any) -> bool:
    """True once a founder has approved or rejected this importer issue."""
    wanted = " ".join(IMPORTER_ISSUE_TITLE.lower().split())
    for row in board_store.list_approvals(table):
        if str(row.get("op") or "") != "github_create_issue":
            continue
        if str(row.get("status") or "") == "pending":
            continue
        title = " ".join(str((row.get("arguments") or {}).get("title") or "").lower().split())
        if title == wanted:
            return True
    return False


def _propose_importer_issue(
    table: Any,
    settings: dict[str, Any],
    source: str,
    names: str,
    error: str,
    request_id: str,
) -> None:
    """One founder Approval after a row imported only once schedules were omitted.

    A rejected or already-executed Approval with this title is not opened again.
    A still-pending one is refreshed by ``create_approval``.
    """
    import board_github
    import board_tools

    if _importer_issue_already_decided(table):
        _log_event("info", tag="board_catalog_importer_issue_skipped", reason="already decided")
        return
    title = IMPORTER_ISSUE_TITLE
    body = (
        "A catalog bulk import of source "
        f"`{source}` received HTTP 500 from `POST /v1/admin/imports` on a row that "
        "included weekly schedules. The same row imported when those schedules were "
        "omitted, so the listing is live without opening hours "
        f"(`importNote`: {SCHEDULES_DROPPED_NOTE}).\n\n"
        "Make `activity_schedule_entries` inserts idempotent "
        "(`ON CONFLICT DO NOTHING`, or replace the schedule's entries in one "
        "transaction) so a name-collision update does not fail on unique constraint "
        "`schedule_entry_unique`.\n\n"
        f"Imported without schedules: {names or '(none)'}\n"
        f"requestId: {request_id or 'unknown'}\n"
        f"Latest client error: {error or 'unknown'}"
    )[:4000]
    arguments = {
        "title": title,
        "body": body,
        "labels": ["bug"],
        "reason": "Catalog bulk import closed rows after a repeated HTTP 500 from the importer.",
    }
    try:
        blocked = board_github.validate_create_issue(arguments)
    except Exception as exc:
        _log_event("info", tag="board_catalog_importer_issue_skipped", error=str(exc)[:200])
        blocked = None
    if blocked:
        _log_event("info", tag="board_catalog_importer_issue_skipped", reason=str(blocked)[:200])
        return
    ctx = board_tools.ToolContext(
        table=table,
        settings=settings,
        persona_id="cto",
        display_name="CTO",
        kind="internal",
        actor="persona",
        task_id="catalog-bulk-500",
    )
    try:
        board_tools.create_approval(
            ctx,
            board_tools.REGISTRY["github_create_issue"],
            arguments,
            summary=f"Open GitHub issue: {title}",
        )
    except Exception as exc:
        _log_event("info", tag="board_catalog_importer_issue_skipped", error=str(exc)[:200])


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
        "onlyCandidateIds": event.get("onlyCandidateIds") or None,
        "bisect": bool(event.get("bisect")),
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


def _first_partial_error(out: dict[str, Any]) -> str | None:
    """First human-readable failure from a job that finished with ``ok: False``.

    ``import`` returns ``batches`` as a list of per-batch results; ``preview``
    returns ``batches`` as an int and per-batch dry-run failures under
    ``dryRuns``. A partially failed job stays ``phase: done`` (so the buttons
    unlock) but the owner still needs to see why a batch was skipped.
    """
    for key in ("batches", "dryRuns"):
        rows = out.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for field in ("error", "remoteError"):
                if row.get(field):
                    return str(row[field])
            errors = row.get("errors")
            if isinstance(errors, list) and errors:
                return str(errors[0])
    if out.get("error"):
        return str(out["error"])
    return None


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
            only_ids = event.get("onlyCandidateIds")
            out = import_source(
                table,
                source,
                limit=limit,
                skip_ingest=skip_ingest,
                only_ids=list(only_ids) if isinstance(only_ids, list) else None,
                bisect=bool(event.get("bisect")),
            )
        else:
            raise BulkImportError(f"unknown catalog bulk action {action}")
        prior = _job(table, source) or {}
        job_doc: dict[str, Any] = {
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
        }
        if out.get("ok") is False:
            first_error = _first_partial_error(out)
            if first_error:
                job_doc["error"] = first_error[:300]
        closed = out.get("closed") if isinstance(out.get("closed"), list) else []
        if closed:
            try:
                _open_bulk_500_task(table, board_store.load_settings(table), source, closed)
            except Exception as exc:
                _log_event("info", tag="board_catalog_bulk_500_task_skipped", source=source, error=str(exc)[:200])
        remaining_ids = out.get("bisectRemaining") if isinstance(out.get("bisectRemaining"), list) else []
        if remaining_ids:
            if _continue_job(
                table,
                event,
                ingestDone=True,
                offset=0,
                onlyCandidateIds=remaining_ids,
                bisect=True,
                limit=limit,
            ):
                _put_job(
                    table,
                    source,
                    {**job_doc, "phase": "running", "bisectRemaining": len(remaining_ids)},
                )
                return {**out, "continued": True}
        _put_job(table, source, job_doc)
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
