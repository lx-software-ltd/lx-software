"""Pull OpenRouter spend that this admin does not meter itself.

LX Software pays one OpenRouter invoice. Statement parser and Executive
Board calls are metered in this Lambda. Evolve Sprouts and Siu Tin Dei
call OpenRouter from their own stacks with a named key. Any other key on
the account, and spend that is not on a key (OpenRouter Chat), is on the
same invoice.

Activity covers the last 30 completed UTC days. One
``GET /api/v1/activity`` returns the whole account; ``api_key_hash``
limits that to one key. Rows are grouped by ``date``. A completed day
missing from the response is stored as zero and replaced when a later
pull includes it. The current UTC day often is not in that window yet,
so a key's today cost falls back to ``usage_daily`` (call count stays 0
until Activity includes the day). Account-level Chat for today waits
until Activity includes that day. A later poll overwrites a day; it does
not add it again. Days older than 30 stay as last written. A failed
request writes nothing for that series, so the previous days stay.

``Other`` is account activity minus every key. Catalog keys that are
metered here are subtracted so they are not counted again, and their
dashboard line stays the in-admin meter.

The management key lives in the admin OpenRouter secret JSON as
``management``. Inference keys stay under ``statement-parser`` and
``executive-board``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlencode

from contract_constants import OPENROUTER_APPS
from openrouter_usage import put_pull_status, replace_usage_day

logger = logging.getLogger(__name__)

KEYS_URL = "https://openrouter.ai/api/v1/keys"
ACTIVITY_URL = "https://openrouter.ai/api/v1/activity"
MANAGEMENT_FIELD = "management"
ACTIVITY_LOOKBACK_DAYS = 30
OTHER_SERVICE_ID = "openrouter-other"
OTHER_LABEL = "Other"
_EXTRA_PREFIX = "or-key:"
_KEY_PAGE_SIZE = 100
_MAX_KEY_OFFSET = 5000
_HTTP_TIMEOUT_SECONDS = 20

Fetch = Callable[[str, str], dict[str, Any]]


class PullHttpError(Exception):
    def __init__(self, status: int, detail: str = "") -> None:
        super().__init__(f"OpenRouter HTTP {status}: {detail[:200]}")
        self.status = int(status)
        self.detail = detail


class ManagementKeyRejected(Exception):
    """The management key was rejected (401/403)."""


def management_key_from_secret(raw: str) -> str:
    text = (raw or "").strip()
    if not text.startswith("{"):
        return ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    value = payload.get(MANAGEMENT_FIELD)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def ingest_targets() -> list[dict[str, str]]:
    """Catalog apps whose spend is pulled, not metered in this admin."""
    out: list[dict[str, str]] = []
    for row in OPENROUTER_APPS:
        if not isinstance(row, dict):
            continue
        if row.get("meteredHere") or not row.get("ingestUsage"):
            continue
        app_id = str(row.get("id") or "").strip()
        key_name = str(row.get("keyName") or "").strip()
        if not app_id or not key_name:
            continue
        out.append({"id": app_id, "keyName": key_name})
    return out


def activity_days(now: datetime, lookback: int = ACTIVITY_LOOKBACK_DAYS) -> list[str]:
    today = now.astimezone(timezone.utc).date()
    count = max(1, int(lookback))
    start = today - timedelta(days=count - 1)
    out: list[str] = []
    cursor = start
    while cursor <= today:
        out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


def sum_activity_rows(rows: list[Any]) -> dict[str, Any]:
    prompt = completion = reasoning = calls = 0
    cost = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        prompt += _num_int(row.get("prompt_tokens"))
        completion += _num_int(row.get("completion_tokens"))
        reasoning += _num_int(row.get("reasoning_tokens"))
        calls += _num_int(row.get("requests"))
        cost += _num_float(row.get("usage"))
    return {
        "promptTokens": prompt,
        "completionTokens": completion,
        "totalTokens": prompt + completion + reasoning,
        "cost": round(cost, 6),
        "calls": calls,
    }


def http_get_json(url: str, token: str) -> dict[str, Any]:
    req = urlrequest.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urlrequest.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise PullHttpError(exc.code, detail) from exc
    except urlerror.URLError as exc:
        raise PullHttpError(0, str(exc.reason)) from exc
    if not isinstance(payload, dict):
        raise PullHttpError(0, "response was not a JSON object")
    return payload


def pull_sibling_usage(
    table: Any,
    *,
    token: str,
    fetch: Fetch | None = None,
    now: datetime | None = None,
    lookback_days: int = ACTIVITY_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """Write pulled daily spend. Raises ``ManagementKeyRejected`` on 401/403."""
    getter = fetch or http_get_json
    moment = now or datetime.now(timezone.utc)
    days = activity_days(moment, lookback_days)
    today = days[-1]
    keys = _list_keys(getter, token)
    by_name: dict[str, list[dict[str, Any]]] = {}
    for key in keys:
        name = str(key.get("name") or "").strip()
        if name:
            by_name.setdefault(name, []).append(key)

    apps_out: list[dict[str, Any]] = []
    partial = False
    subtraction_ok = True
    used_by_day = {day: _blank_totals() for day in days}
    catalog = _catalog_by_key_name()

    account_grouped = _try_activity(getter, token, key_hash=None, app_id="account")
    if account_grouped is None:
        partial = True
        subtraction_ok = False

    for target in ingest_targets():
        matched = by_name.get(target["keyName"], [])
        if not matched:
            apps_out.append({"id": target["id"], "status": "key_not_found", "days": 0})
            continue
        if not _keys_have_usage(matched):
            apps_out.append({"id": target["id"], "status": "no_usage", "days": 0})
            continue
        written, failed, totals = _write_key_days(
            table,
            getter,
            token,
            app_id=target["id"],
            keys=matched,
            days=days,
            today=today,
            usage_daily=_usage_daily(matched),
        )
        if failed:
            partial = True
            subtraction_ok = False
        else:
            _add_days(used_by_day, totals)
        apps_out.append(
            {
                "id": target["id"],
                "status": "error" if failed and written == 0 else "updated",
                "days": written,
            }
        )

    for name, row in catalog.items():
        if not row.get("meteredHere"):
            continue
        matched = by_name.get(name, [])
        if not _keys_have_usage(matched):
            continue
        _written, failed, totals = _write_key_days(
            table,
            getter,
            token,
            app_id=str(row.get("id") or name),
            keys=matched,
            days=days,
            today=today,
            usage_daily=_usage_daily(matched),
            write=False,
        )
        if failed:
            partial = True
            subtraction_ok = False
        else:
            _add_days(used_by_day, totals)

    for group in _extra_groups(keys, set(catalog)):
        if not _keys_have_usage(group["keys"]):
            continue
        written, failed, totals = _write_key_days(
            table,
            getter,
            token,
            app_id=group["id"],
            keys=group["keys"],
            days=days,
            today=today,
            usage_daily=_usage_daily(group["keys"]),
            label=group["label"],
        )
        if failed:
            partial = True
            subtraction_ok = False
        else:
            _add_days(used_by_day, totals)
        apps_out.append(
            {
                "id": group["id"],
                "status": "error" if failed and written == 0 else "updated",
                "days": written,
            }
        )

    if subtraction_ok and account_grouped is not None:
        account_totals = _totals_by_day([account_grouped], days, today, 0.0)
        for day in days:
            remainder = _remainder(account_totals[day], used_by_day[day])
            replace_usage_day(
                table,
                service=OTHER_SERVICE_ID,
                owner=OTHER_SERVICE_ID,
                usage=remainder,
                calls=int(remainder["calls"]),
                date_iso=day,
                label=OTHER_LABEL,
            )
        apps_out.append({"id": OTHER_SERVICE_ID, "status": "updated", "days": len(days)})
    else:
        apps_out.append({"id": OTHER_SERVICE_ID, "status": "error", "days": 0})
    return _result(ok=not partial, reason="partial" if partial else "", apps=apps_out)


def handle_pull(event: dict[str, Any]) -> dict[str, Any]:
    """EventBridge Scheduler entry: ``internal=openrouter_usage_pull``."""
    del event  # payload is only a schedule marker
    import runtime
    from admin_runtime import _get_secretsmanager_client
    from openrouter_client import OpenRouterError, read_secret_raw

    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
    arn = os.getenv("OPENROUTER_API_KEY_SECRET_ARN", "").strip()
    token = ""
    if arn:
        try:
            raw = read_secret_raw(
                _get_secretsmanager_client(), arn, what="OpenRouter API key"
            )
        except OpenRouterError:
            raw = ""
        token = management_key_from_secret(raw)
    if not token:
        result = _result(ok=False, reason="management_key_missing", apps=[])
        put_pull_status(table, result)
        logger.warning(
            "OpenRouter usage pull skipped; secret JSON has no %s field",
            MANAGEMENT_FIELD,
        )
        return result
    try:
        result = pull_sibling_usage(table, token=token)
    except ManagementKeyRejected:
        result = _result(ok=False, reason="management_key_rejected", apps=[])
        logger.warning("OpenRouter usage pull rejected the management key")
    except PullHttpError as exc:
        result = _result(ok=False, reason="http_error", apps=[])
        logger.warning("OpenRouter usage pull failed status=%s", exc.status)
    put_pull_status(table, result)
    return result


def _write_key_days(
    table: Any,
    fetch: Fetch,
    token: str,
    *,
    app_id: str,
    keys: list[dict[str, Any]],
    days: list[str],
    today: str,
    usage_daily: float,
    write: bool = True,
    label: str | None = None,
) -> tuple[int, bool, dict[str, dict[str, Any]]]:
    hashes = [str(key.get("hash") or "") for key in keys if str(key.get("hash") or "")]
    if not hashes:
        return 0, True, {}
    grouped: list[dict[str, list[Any]]] = []
    for key_hash in hashes:
        by_date = _try_activity(fetch, token, key_hash=key_hash, app_id=app_id)
        if by_date is None:
            return 0, True, {}
        grouped.append(by_date)
    totals_by_day = _totals_by_day(grouped, days, today, usage_daily)
    if write:
        for day in days:
            replace_usage_day(
                table,
                service=app_id,
                owner=app_id,
                usage=totals_by_day[day],
                calls=int(totals_by_day[day]["calls"]),
                date_iso=day,
                label=label,
            )
    return len(days), False, totals_by_day


def _try_activity(
    fetch: Fetch,
    token: str,
    *,
    key_hash: str | None,
    app_id: str,
) -> dict[str, list[Any]] | None:
    url = (
        ACTIVITY_URL
        if not key_hash
        else f"{ACTIVITY_URL}?{urlencode({'api_key_hash': key_hash})}"
    )
    try:
        payload = fetch(url, token)
    except PullHttpError as exc:
        if exc.status in (401, 403):
            raise ManagementKeyRejected(str(exc)) from exc
        logger.warning(
            "OpenRouter activity pull failed app=%s status=%s",
            app_id,
            exc.status,
        )
        return None
    data = payload.get("data")
    if not isinstance(data, list):
        logger.warning("OpenRouter activity response missing data app=%s", app_id)
        return None
    return _rows_by_date(data)


def _totals_by_day(
    grouped: list[dict[str, list[Any]]],
    days: list[str],
    today: str,
    usage_daily: float,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for day in days:
        rows: list[Any] = []
        for by_date in grouped:
            rows.extend(by_date.get(day, []))
        totals = sum_activity_rows(rows)
        if (
            day == today
            and totals["cost"] <= 0
            and int(totals["calls"]) == 0
            and usage_daily > 0
        ):
            totals = {
                "promptTokens": 0,
                "completionTokens": 0,
                "totalTokens": 0,
                "cost": round(usage_daily, 6),
                "calls": 0,
            }
        out[day] = totals
    return out


def _blank_totals() -> dict[str, Any]:
    return {
        "promptTokens": 0,
        "completionTokens": 0,
        "totalTokens": 0,
        "cost": 0.0,
        "calls": 0,
    }


def _add_days(
    dest: dict[str, dict[str, Any]],
    extra: dict[str, dict[str, Any]],
) -> None:
    for day, totals in extra.items():
        base = dest.get(day) or _blank_totals()
        dest[day] = {
            "promptTokens": int(base["promptTokens"]) + int(totals["promptTokens"]),
            "completionTokens": int(base["completionTokens"]) + int(totals["completionTokens"]),
            "totalTokens": int(base["totalTokens"]) + int(totals["totalTokens"]),
            "cost": round(float(base["cost"]) + float(totals["cost"]), 6),
            "calls": int(base["calls"]) + int(totals["calls"]),
        }


def _remainder(account: dict[str, Any], used: dict[str, Any]) -> dict[str, Any]:
    return {
        "promptTokens": max(0, int(account["promptTokens"]) - int(used["promptTokens"])),
        "completionTokens": max(
            0, int(account["completionTokens"]) - int(used["completionTokens"])
        ),
        "totalTokens": max(0, int(account["totalTokens"]) - int(used["totalTokens"])),
        "cost": round(max(0.0, float(account["cost"]) - float(used["cost"])), 6),
        "calls": max(0, int(account["calls"]) - int(used["calls"])),
    }


def _keys_have_usage(keys: list[dict[str, Any]]) -> bool:
    return _usage_daily(keys) > 0 or sum(_num_float(key.get("usage")) for key in keys) > 0


def _usage_daily(keys: list[dict[str, Any]]) -> float:
    return sum(_num_float(key.get("usage_daily")) for key in keys)


def _catalog_by_key_name() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in OPENROUTER_APPS:
        if not isinstance(row, dict):
            continue
        name = str(row.get("keyName") or "").strip()
        if name:
            out[name] = row
    return out


def extra_service_id(name: str) -> str:
    raw = name.strip()
    cleaned = []
    for char in raw:
        if char.isalnum() or char in "-_:.":
            cleaned.append(char)
        else:
            cleaned.append("-")
    slug = "".join(cleaned).strip("-")[:80] or "unnamed"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:6]
    return f"{_EXTRA_PREFIX}{slug}-{digest}"


def _extra_groups(
    keys: list[dict[str, Any]],
    catalog_names: set[str],
) -> list[dict[str, Any]]:
    named: dict[str, list[dict[str, Any]]] = {}
    unnamed: list[dict[str, Any]] = []
    for key in keys:
        name = str(key.get("name") or "").strip()
        if name in catalog_names:
            continue
        if name:
            named.setdefault(name, []).append(key)
        elif str(key.get("hash") or ""):
            unnamed.append(key)
    groups: list[dict[str, Any]] = []
    for name in sorted(named):
        groups.append({"id": extra_service_id(name), "label": name, "keys": named[name]})
    for key in unnamed:
        digest = str(key.get("hash") or "")[:8]
        masked = str(key.get("label") or "").strip() or "Unnamed key"
        groups.append(
            {
                "id": f"{_EXTRA_PREFIX}unnamed-{digest}",
                "label": masked,
                "keys": [key],
            }
        )
    return groups


def _rows_by_date(rows: list[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        day = str(row.get("date") or "")[:10]
        if len(day) != 10:
            continue
        grouped.setdefault(day, []).append(row)
    return grouped


def _list_keys(fetch: Fetch, token: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    offset = 0
    while offset <= _MAX_KEY_OFFSET:
        url = f"{KEYS_URL}?{urlencode({'include_disabled': 'true', 'offset': str(offset)})}"
        try:
            payload = fetch(url, token)
        except PullHttpError as exc:
            if exc.status in (401, 403):
                raise ManagementKeyRejected(str(exc)) from exc
            raise
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise PullHttpError(0, "keys response missing data")
        out.extend(row for row in rows if isinstance(row, dict))
        if len(rows) < _KEY_PAGE_SIZE:
            break
        offset += _KEY_PAGE_SIZE
    return out


def _result(*, ok: bool, reason: str, apps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": ok,
        "reason": reason,
        "pulledAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "apps": apps,
    }


def _num_int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return 0


def _num_float(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return 0.0
    return 0.0
