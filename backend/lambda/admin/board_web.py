"""Executive Board ``web`` tools: GA4 Data API + GTM container status.

Reads (sessions, conversions, GTM live version) are cached under
``BOARD#…#cache`` and refreshed by the hourly ``board_cache`` schedule.
Several GA4 properties and GTM containers are supported (comma-separated
ids). There is no Admin API webhook. Uses a dedicated Analytics service
account — not the Play publisher key.

T8c will add ``gtm_propose_publish`` (always Approvals). Google Ads is a
separate ``ads`` tool (T8b).

Plan: docs/architecture/executive-board-tools-plan.md §5.8.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from admin_runtime import _get_secretsmanager_client
import board_pii
import board_store
import board_stores
from contract_constants import BOARD_WEB_CACHE_TTL_HOURS, BOARD_WEB_LIST_MAX
from http_common import _log_event
from openrouter_client import OpenRouterError, read_secret_raw

GA4_ORIGIN = "https://analyticsdata.googleapis.com"
GTM_ORIGIN = "https://tagmanager.googleapis.com"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = (
    "https://www.googleapis.com/auth/analytics.readonly "
    "https://www.googleapis.com/auth/tagmanager.readonly"
)
SESSIONS_CACHE = "web:sessions"
CONVERSIONS_CACHE = "web:conversions"
GTM_CACHE = "web:gtm"

_sa: dict[str, Any] | None = None
_sa_loaded_at = 0.0
_token: tuple[str, float] | None = None
# Re-read Secrets Manager so a console edit of propertyIds / gtmContainers is
# picked up without waiting for a Lambda cold start.
_SA_TTL_SECONDS = 30


class WebError(RuntimeError):
    """User-facing GA4 / GTM failure."""


def reset_caches_for_tests() -> None:
    global _sa, _sa_loaded_at, _token
    _sa = None
    _sa_loaded_at = 0.0
    _token = None


def _secret_json() -> dict[str, Any]:
    global _sa, _sa_loaded_at
    if _sa is not None and (time.time() - _sa_loaded_at) < _SA_TTL_SECONDS:
        return _sa
    plain = (os.environ.get("GOOGLE_ANALYTICS_SERVICE_ACCOUNT") or "").strip()
    raw = ""
    if plain:
        raw = plain
    else:
        arn = (os.environ.get("GOOGLE_ANALYTICS_SERVICE_ACCOUNT_SECRET_ARN") or "").strip()
        if arn:
            try:
                raw = read_secret_raw(
                    _get_secretsmanager_client(), arn, what="Google Analytics service account"
                ).strip()
            except OpenRouterError as exc:
                _log_event("warning", tag="board_web_secret_failed", error=str(exc)[:200])
                _sa = {}
                _sa_loaded_at = time.time()
                return _sa
    if not raw:
        _sa = {}
        _sa_loaded_at = time.time()
        return _sa
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        _sa = {}
        _sa_loaded_at = time.time()
        return _sa
    _sa = parsed if isinstance(parsed, dict) else {}
    _sa_loaded_at = time.time()
    return _sa


def _csv(env_name: str) -> list[str]:
    return _split_csv(os.environ.get(env_name) or "")


def _split_csv(raw: Any) -> list[str]:
    text = str(raw or "")
    return [p.strip() for p in text.replace("\n", ",").split(",") if p.strip()]


def _norm_property(raw: str) -> str:
    value = raw.strip()
    if value.startswith("properties/"):
        value = value.split("/", 1)[1]
    return value


def _gtm_pair(raw: str) -> dict[str, str] | None:
    if ":" not in raw:
        return None
    account, container = raw.split(":", 1)
    account, container = account.strip(), container.strip()
    if account and container:
        return {"accountId": account, "containerId": container}
    return None


def _properties_from_secret(secret: dict[str, Any]) -> list[str]:
    listed = secret.get("propertyIds") or secret.get("property_ids") or secret.get("properties")
    out: list[str] = []
    if isinstance(listed, list):
        out = [_norm_property(str(p)) for p in listed if str(p).strip()]
    elif listed is not None and str(listed).strip():
        out = [_norm_property(p) for p in _split_csv(listed)]
    if out:
        return out
    single = str(secret.get("propertyId") or secret.get("property_id") or "").strip()
    return [_norm_property(single)] if single else []


def _gtm_from_secret(secret: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    listed = secret.get("gtmContainers") or secret.get("gtm_containers")
    rows: list[Any]
    if isinstance(listed, list):
        rows = listed
    elif listed is not None and str(listed).strip():
        rows = _split_csv(listed)
    else:
        rows = []
    for row in rows:
        if isinstance(row, dict):
            acc = str(row.get("accountId") or row.get("account_id") or "").strip()
            cid = str(row.get("containerId") or row.get("container_id") or "").strip()
            if acc and cid:
                out.append({"accountId": acc, "containerId": cid})
            continue
        pair = _gtm_pair(str(row))
        if pair:
            out.append(pair)
    if out:
        return out
    account = str(secret.get("gtmAccountId") or secret.get("gtm_account_id") or "").strip()
    container = str(secret.get("gtmContainerId") or secret.get("gtm_container_id") or "").strip()
    if account and container:
        return [{"accountId": account, "containerId": container}]
    return []


def property_ids() -> list[str]:
    env = [_norm_property(p) for p in _csv("GA4_PROPERTY_IDS")]
    if env:
        return env
    return _properties_from_secret(_secret_json())


def gtm_containers() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for pair in _csv("GTM_CONTAINERS"):
        parsed = _gtm_pair(pair)
        if parsed:
            out.append(parsed)
    if out:
        return out
    account = (os.environ.get("GTM_ACCOUNT_ID") or "").strip()
    container = (os.environ.get("GTM_CONTAINER_ID") or "").strip()
    if account and container:
        return [{"accountId": account, "containerId": container}]
    return _gtm_from_secret(_secret_json())


def sa_configured() -> bool:
    if (os.environ.get("GOOGLE_ANALYTICS_ACCESS_TOKEN") or "").strip():
        return True
    secret = _secret_json()
    return bool(
        str(secret.get("client_email") or secret.get("clientEmail") or "").strip()
        and str(secret.get("private_key") or secret.get("privateKey") or "").strip()
    )


def configured() -> bool:
    return sa_configured() and (bool(property_ids()) or bool(gtm_containers()))


def status_summary() -> dict[str, Any]:
    return {
        "configured": configured(),
        "propertyCount": len(property_ids()),
        "gtmContainerCount": len(gtm_containers()),
        "cacheTtlHours": BOARD_WEB_CACHE_TTL_HOURS,
    }


def access_token() -> str:
    global _token
    injected = (os.environ.get("GOOGLE_ANALYTICS_ACCESS_TOKEN") or "").strip()
    if injected:
        return injected
    if _token and _token[1] > time.time() + 30:
        return _token[0]
    secret = _secret_json()
    email = str(secret.get("client_email") or secret.get("clientEmail") or "").strip()
    pem = str(secret.get("private_key") or secret.get("privateKey") or "").strip()
    if not email or not pem:
        raise WebError("GoogleAnalyticsServiceAccount is not configured.")
    now = int(time.time())
    try:
        assertion = board_stores.sign_jwt(
            {"alg": "RS256", "typ": "JWT"},
            {"iss": email, "scope": SCOPES, "aud": TOKEN_URL, "iat": now, "exp": now + 3600},
            pem,
        )
        data = board_stores.http_json(
            "POST",
            TOKEN_URL,
            form={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        )
    except board_stores.StoresError as exc:
        raise WebError(str(exc)) from exc
    token = str(data.get("access_token") or "")
    if not token:
        raise WebError("Google did not return an access_token")
    _token = (token, float(now + int(data.get("expires_in") or 3600)))
    return token


def _google(method: str, url: str, *, body: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return board_stores.http_json(
            method,
            url,
            headers={"Authorization": f"Bearer {access_token()}", "Accept": "application/json"},
            body=body,
        )
    except board_stores.StoresError as exc:
        raise WebError(str(exc)) from exc


def _mask_cell(value: str) -> str:
    return board_pii.EMAIL_RE.sub("contact#hidden", board_pii.PHONE_RE.sub("phone#hidden", value or ""))


def _limit(args: dict[str, Any]) -> int:
    try:
        n = int(args.get("limit") or 10)
    except (TypeError, ValueError):
        n = 10
    return max(1, min(n, BOARD_WEB_LIST_MAX))


def _wanted_properties(args: dict[str, Any]) -> list[str]:
    wanted = _norm_property(str(args.get("propertyId") or ""))
    ids = property_ids()
    if wanted:
        if wanted not in ids and ids:
            raise WebError(f"propertyId {wanted} is not in the configured GA4 property ids")
        return [wanted]
    if not ids:
        raise _missing_ids_error("ga4")
    return ids


def _wanted_containers(args: dict[str, Any]) -> list[dict[str, str]]:
    wanted = str(args.get("containerId") or "").strip()
    rows = gtm_containers()
    if wanted:
        match = [r for r in rows if r["containerId"] == wanted]
        if not match:
            raise WebError(f"containerId {wanted} is not in GTM_CONTAINERS")
        return match
    if not rows:
        raise _missing_ids_error("gtm")
    return rows


def _cached(table: Any, name: str) -> dict[str, Any] | None:
    hit = board_store.get_cache(table, name)
    if not hit:
        return None
    payload = hit.get("payload")
    if not isinstance(payload, dict):
        return None
    return {**payload, "cached": True, "fetchedAt": hit.get("fetchedAt")}


def _store(table: Any, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    doc = board_store.put_cache(table, name, payload, ttl_seconds=BOARD_WEB_CACHE_TTL_HOURS * 3600)
    return {**payload, "cached": False, "fetchedAt": doc.get("fetchedAt")}


def _read(table: Any, name: str, fetcher: Any) -> dict[str, Any]:
    cached = _cached(table, name)
    if cached:
        return cached
    return _store(table, name, fetcher())


def _run_report(property_id: str, *, dimensions: list[str], metrics: list[str], limit: int) -> dict[str, Any]:
    body = {
        "dateRanges": [{"startDate": "7daysAgo", "endDate": "today"}],
        "dimensions": [{"name": n} for n in dimensions],
        "metrics": [{"name": n} for n in metrics],
        "limit": limit,
    }
    data = _google("POST", f"{GA4_ORIGIN}/v1beta/properties/{property_id}:runReport", body=body)
    rows_out: list[dict[str, Any]] = []
    for row in data.get("rows") or []:
        dims = [_mask_cell(str((d or {}).get("value") or "")) for d in (row.get("dimensionValues") or [])]
        mets: dict[str, Any] = {}
        for name, cell in zip(metrics, row.get("metricValues") or []):
            raw = str((cell or {}).get("value") or "0")
            try:
                mets[name] = float(raw) if "." in raw else int(raw)
            except ValueError:
                mets[name] = raw
        item: dict[str, Any] = {"metrics": mets}
        for name, value in zip(dimensions, dims):
            item[name] = value
        rows_out.append(item)
    totals: dict[str, Any] = {}
    if data.get("totals"):
        for name, cell in zip(metrics, (data["totals"][0] or {}).get("metricValues") or []):
            raw = str((cell or {}).get("value") or "0")
            try:
                totals[name] = float(raw) if "." in raw else int(raw)
            except ValueError:
                totals[name] = raw
    return {
        "propertyId": property_id,
        "rows": rows_out,
        "totals": totals,
        "rowCount": data.get("rowCount") or len(rows_out),
    }


def fetch_sessions(*, property_filter: str = "", limit: int = 10) -> dict[str, Any]:
    ids = _wanted_properties({"propertyId": property_filter})
    properties = []
    for pid in ids:
        overview = _run_report(pid, dimensions=[], metrics=["sessions", "activeUsers", "screenPageViews"], limit=1)
        pages = _run_report(pid, dimensions=["pagePath"], metrics=["sessions", "screenPageViews"], limit=limit)
        refs = _run_report(pid, dimensions=["sessionSource", "sessionMedium"], metrics=["sessions"], limit=limit)
        properties.append(
            {
                "propertyId": pid,
                "totals": overview.get("totals") or {},
                "topPages": pages.get("rows") or [],
                "referrers": refs.get("rows") or [],
            }
        )
    return {"properties": properties, "count": len(properties)}


def fetch_conversions(*, property_filter: str = "", limit: int = 10) -> dict[str, Any]:
    ids = _wanted_properties({"propertyId": property_filter})
    properties = []
    for pid in ids:
        events = _run_report(
            pid,
            dimensions=["eventName"],
            # GA4 renamed ``conversions`` to ``keyEvents`` (2024); the old name is deprecated.
            metrics=["eventCount", "keyEvents"],
            limit=limit,
        )
        properties.append({"propertyId": pid, "events": events.get("rows") or [], "totals": events.get("totals") or {}})
    return {"properties": properties, "count": len(properties)}


def _live_version(doc: dict[str, Any]) -> dict[str, Any]:
    live = doc.get("containerVersion") or doc
    if not isinstance(live, dict):
        return {}
    return {
        "versionId": live.get("containerVersionId") or live.get("versionId"),
        "name": live.get("name"),
        "description": live.get("description"),
        "fingerprint": live.get("fingerprint"),
    }


def fetch_gtm(*, container_filter: str = "") -> dict[str, Any]:
    rows = _wanted_containers({"containerId": container_filter})
    containers = []
    for row in rows:
        acc, cid = row["accountId"], row["containerId"]
        info = _google("GET", f"{GTM_ORIGIN}/tagmanager/v2/accounts/{acc}/containers/{cid}")
        try:
            live_doc = _google(
                "GET",
                f"{GTM_ORIGIN}/tagmanager/v2/accounts/{acc}/containers/{cid}/versions:live",
            )
            live = _live_version(live_doc)
        except WebError:
            live = {}
        container = info.get("container") or info
        containers.append(
            {
                "accountId": acc,
                "containerId": cid,
                "name": container.get("name"),
                "publicId": container.get("publicId"),
                "live": live,
            }
        )
    return {"containers": containers, "count": len(containers)}


def refresh_caches(table: Any) -> dict[str, str]:
    notes: dict[str, str] = {}
    if not configured():
        return {"web:sessions": "skipped"}
    jobs: list[tuple[str, Any]] = []
    if property_ids():
        jobs.extend(((SESSIONS_CACHE, fetch_sessions), (CONVERSIONS_CACHE, fetch_conversions)))
    if gtm_containers():
        jobs.append((GTM_CACHE, fetch_gtm))
    for name, fn in jobs:
        try:
            _store(table, name, fn())
            notes[name] = "ok"
        except WebError as exc:
            notes[name] = str(exc)[:200]
            _log_event("warning", tag="board_web_refresh_failed", key=name, error=str(exc)[:200])
    return notes or {"web:sessions": "skipped"}


def _missing_ids_error(kind: str) -> WebError:
    secret = _secret_json()
    keys = sorted(str(k) for k in secret.keys())[:24]
    _log_event(
        "warning",
        tag="board_web_ids_missing",
        kind=kind,
        secretKeyCount=len(secret),
        secretKeys=",".join(keys),
    )
    if kind == "ga4":
        return WebError(
            "GA4 property ids are not set. Put numeric ids in GA4_PROPERTY_IDS "
            "or propertyIds on lxsoftware-admin-siutindei-board-google-analytics-sa."
        )
    return WebError(
        "GTM containers are not set. Put account:container pairs in GTM_CONTAINERS "
        "or gtmContainers on lxsoftware-admin-siutindei-board-google-analytics-sa."
    )


def op_sessions(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    if not property_ids():
        raise _missing_ids_error("ga4")
    if args.get("propertyId"):
        return fetch_sessions(property_filter=str(args.get("propertyId") or ""), limit=_limit(args))
    return _read(ctx.table, SESSIONS_CACHE, lambda: fetch_sessions(limit=_limit(args)))


def op_conversions(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    if not property_ids():
        raise _missing_ids_error("ga4")
    if args.get("propertyId"):
        return fetch_conversions(property_filter=str(args.get("propertyId") or ""), limit=_limit(args))
    return _read(ctx.table, CONVERSIONS_CACHE, lambda: fetch_conversions(limit=_limit(args)))


def op_gtm_status(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    if not gtm_containers():
        raise _missing_ids_error("gtm")
    if args.get("containerId"):
        return fetch_gtm(container_filter=str(args.get("containerId") or ""))
    return _read(ctx.table, GTM_CACHE, fetch_gtm)


def digest_for_context(table: Any) -> dict[str, Any]:
    if table is None:
        return {}
    hit = _cached(table, SESSIONS_CACHE)
    if not hit:
        return {}
    sessions = 0
    users = 0
    for prop in hit.get("properties") or []:
        totals = prop.get("totals") or {}
        try:
            sessions += int(totals.get("sessions") or 0)
            users += int(totals.get("activeUsers") or 0)
        except (TypeError, ValueError):
            pass
    return {
        "sessions": sessions,
        "users": users,
        "properties": hit.get("count") or 0,
        "fetchedAt": hit.get("fetchedAt"),
    }
