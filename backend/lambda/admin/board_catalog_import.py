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
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

from admin_runtime import _get_secretsmanager_client
from contract_constants import (
    BOARD_CATALOG_IMPORT_ENABLED_DEFAULT,
    BOARD_CATALOG_MAX_ORGS_PER_IMPORT,
    BOARD_CATALOG_TYPE_TO_CATEGORY,
)
from http_common import _log_event
from openrouter_client import read_secret_raw

CATALOG_EVENT_KIND = "catalog-micro-batch"

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

    note_bits: list[str] = []
    for field in _NOTE_FIELDS:
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

    return out, {
        "index": index,
        "skipped": False,
        "name": out["name"],
        "copiedFields": sorted(set(copied)),
        "skippedFields": sorted(set(skipped_fields)),
    }


def transform_sheet(sheet: dict[str, Any], *, manager_id: str | None = None) -> dict[str, Any]:
    district = str(sheet.get("district") or "").strip()
    orgs = sheet.get("organisations")
    if orgs is None:
        orgs = sheet.get("organizations")
    if not isinstance(orgs, list):
        raise CatalogImportError("sheet must include organisations[]")
    mid = (manager_id if manager_id is not None else catalog_manager_id()).strip()
    payload_orgs: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    for i, org in enumerate(orgs):
        row, report = transform_org(org if isinstance(org, dict) else {}, district=district, manager_id=mid, index=i)
        reports.append(report)
        if row:
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
    return str(ref.get("kind") or "") == CATALOG_EVENT_KIND


def require_catalog_sheet(task: dict[str, Any]) -> None:
    if not is_catalog_sheet(task):
        raise CatalogImportError("task is not a catalog micro-batch sheet")


def require_importable_task(task: dict[str, Any], *, force: bool = False) -> None:
    require_catalog_sheet(task)
    if str(task.get("status") or "") != "delivered":
        raise CatalogImportError("catalog import requires a delivered (accepted) sheet")
    imported_at = task.get("importedAt")
    if imported_at and not force:
        raise CatalogImportError(f"already imported at {imported_at}")


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

    resp = boto3.client("cognito-idp").admin_initiate_auth(
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


def _presign_and_put(orgs: list[dict[str, Any]], token: str, *, filename: str) -> str:
    base = admin_api_base()
    if not base:
        raise CatalogImportError("SiutindeiAdminApiBaseUrl is not set")
    blob = json.dumps({"organizations": orgs}).encode("utf-8")
    presign = _http(
        "POST",
        urljoin(base + "/", "admin/imports/presign"),
        headers=_auth_headers(token),
        body=json.dumps({"filename": filename, "content_type": "application/json"}).encode("utf-8"),
    )
    upload_url = str(presign.get("upload_url") or presign.get("url") or "").strip()
    object_key = str(presign.get("object_key") or presign.get("key") or "").strip()
    if not upload_url or not object_key:
        raise CatalogImportError("presign did not return upload_url and object_key")
    put_headers = {"Content-Type": "application/json"}
    extra = presign.get("headers")
    if isinstance(extra, dict):
        put_headers.update({str(k): str(v) for k, v in extra.items()})
    _http("PUT", upload_url, headers=put_headers, body=blob, timeout=25)
    return object_key


def _imports_post(token: str, body: dict[str, Any]) -> dict[str, Any]:
    base = admin_api_base()
    if not base:
        raise CatalogImportError("SiutindeiAdminApiBaseUrl is not set")
    return _http(
        "POST",
        urljoin(base + "/", "admin/imports"),
        headers=_auth_headers(token),
        body=json.dumps(body).encode("utf-8"),
    )


def _importer_accepted(resp: dict[str, Any]) -> int | None:
    for key in ("imported", "accepted", "created", "upserted", "count"):
        val = resp.get(key)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        return int(val)
    return None


def _remote_dry_run(payload: dict[str, Any], token: str) -> dict[str, Any]:
    orgs = payload.get("organizations") or []
    object_key = _presign_and_put(orgs, token, filename="board-catalog-dry-run.json")
    resp = _imports_post(token, {"object_key": object_key, "dry_run": True})
    return {
        "ok": True,
        "mode": "remote",
        "objectKey": object_key,
        "response": resp,
        "payload": {"organizations": orgs},
    }


def _run_remote_import(payload: dict[str, Any], token: str) -> dict[str, Any]:
    orgs = payload.get("organizations") or []
    object_key = _presign_and_put(orgs, token, filename="board-catalog.json")
    imported = _imports_post(token, {"object_key": object_key})
    sent = len(orgs)
    return {
        "ok": True,
        "mode": "remote",
        "objectKey": object_key,
        "response": imported,
        "sent": sent,
        "accepted": _importer_accepted(imported),
    }


def preview_from_text(text: str, *, remote: bool = False) -> dict[str, Any]:
    sheet = parse_sheet(text)
    transformed = transform_sheet(sheet)
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
            out["dryRun"] = {**local, **_remote_dry_run(transformed, token), "local": local}
        except CatalogImportError as exc:
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
    preview = preview_from_text(text, remote=remote)
    preview["taskId"] = task.get("taskId")
    ref = task.get("eventRef") or {}
    if not preview.get("district") and ref.get("district"):
        preview["district"] = ref.get("district")
    return preview


def run_import(table: Any, task: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    if not import_enabled():
        raise CatalogImportError("catalog import is switched off (SiutindeiBoardCatalogImportEnabled)")
    if not configured():
        raise CatalogImportError("catalog import is not configured (admin API, user pool, client, manager id)")
    require_importable_task(task, force=force)
    preview = preview_task(table, task, remote=False)
    if not preview.get("ok"):
        errors = (preview.get("dryRun") or {}).get("errors") or ["sheet failed local dry-run"]
        raise CatalogImportError("; ".join(str(e) for e in errors)[:300])
    token = _id_token()
    imported = _run_remote_import(preview.get("payload") or {}, token)
    now = ""
    try:
        import board_store

        now = board_store.now_iso()
    except Exception:
        now = ""
    task["importedAt"] = now
    task["importResult"] = {
        "ok": True,
        "objectKey": imported.get("objectKey"),
        "sent": imported.get("sent"),
        "accepted": imported.get("accepted"),
        "at": now,
    }
    task["importPreview"] = preview
    if table is not None:
        try:
            import board_store

            board_store.put_task(table, task)
        except Exception as exc:
            _log_event("warning", tag="board_catalog_import_save_failed", error=str(exc)[:200])
    return {"ok": True, "taskId": task.get("taskId"), "import": imported, "preview": preview}


def attach_accept_preview(table: Any, task: dict[str, Any]) -> dict[str, Any]:
    """Accept-hook: transform + dry-run only. Never imports."""
    try:
        preview = preview_task(table, task, remote=False)
    except CatalogImportError as exc:
        preview = {"ok": False, "error": str(exc)[:300], "taskId": task.get("taskId")}
    except Exception as exc:
        preview = {"ok": False, "error": str(exc)[:300], "taskId": task.get("taskId")}
    task["importPreview"] = preview
    return preview


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


def owner_preview(table: Any, body: dict[str, Any]) -> dict[str, Any]:
    task_id = str(body.get("taskId") or "").strip()
    if not task_id:
        raise CatalogImportError("taskId is required")
    import board_store

    task = board_store.get_task(table, task_id)
    if not task:
        raise CatalogImportError("Task not found")
    preview = preview_task(table, task, sheet_text=str(body.get("sheet") or "") or None, remote=bool(body.get("remote")))
    task["importPreview"] = preview
    board_store.put_task(table, task)
    return preview


def owner_import(table: Any, body: dict[str, Any]) -> dict[str, Any]:
    task_id = str(body.get("taskId") or "").strip()
    if not task_id:
        raise CatalogImportError("taskId is required")
    import board_store

    task = board_store.get_task(table, task_id)
    if not task:
        raise CatalogImportError("Task not found")
    return run_import(table, task, force=bool(body.get("force")))


def ready_sheets(table: Any) -> list[dict[str, Any]]:
    """Delivered catalog sheets that have not been imported yet (digest)."""
    out: list[dict[str, Any]] = []
    for task in board_store_list_delivered(table):
        ref = task.get("eventRef") or {}
        if str(ref.get("kind") or "") != CATALOG_EVENT_KIND:
            continue
        if task.get("importedAt"):
            continue
        preview = task.get("importPreview") or {}
        out.append(
            {
                "taskId": task.get("taskId"),
                "district": ref.get("district") or preview.get("district") or "",
                "ok": bool(preview.get("ok")),
                "accepted": (preview.get("dryRun") or {}).get("accepted") or 0,
            }
        )
    return out[:20]


def board_store_list_delivered(table: Any) -> list[dict[str, Any]]:
    import board_store

    return list(board_store.list_tasks(table, "delivered", limit=200))
