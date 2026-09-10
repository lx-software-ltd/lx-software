"""Daily OpenRouter usage ledger, keyed by app and owner.

LX Software pays the OpenRouter invoice. These rows are the split used
to see which tagged app (and, for this admin, which book or house) drove
the spend. Sibling products share the same account via the app catalog
in ``contracts/openrouter-apps.json``.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs

from contract_constants import (
    BOARD_KEY,
    FINANCE_STATEMENT_OWNER_KEYS,
    OPENROUTER_APPS,
    OPENROUTER_PAYER,
)
from openrouter_client import (
    SERVICE_EXECUTIVE_BOARD,
    SERVICE_STATEMENT_PARSER,
    add_usage,
    normalize_usage,
)

USAGE_PK_PREFIX = "OPENROUTER#"

OWNER_LABELS: dict[str, str] = {
    "siuTinDei": "Siu Tin Dei",
    "lxSoftware": "LX Software",
    "hillmarton": "32 Hillmarton",
    "morrison": "The Morrison",
}

_MAX_RANGE_DAYS = 92


def usage_day_pk(date_iso: str) -> str:
    return f"{USAGE_PK_PREFIX}usage#{date_iso}"


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def cost_center_for(*, service: str, owner: str) -> str:
    """Which statement book / house this admin call ran against."""
    if service == SERVICE_EXECUTIVE_BOARD:
        return BOARD_KEY
    if owner in FINANCE_STATEMENT_OWNER_KEYS:
        return owner
    return "lxSoftware"


def owner_label(owner: str) -> str:
    return OWNER_LABELS.get(owner, owner)


def payer_payload() -> dict[str, str]:
    payer_id = str(OPENROUTER_PAYER or "lxSoftware")
    return {"id": payer_id, "label": OWNER_LABELS.get(payer_id, payer_id)}


def _catalog_row(service_id: str) -> dict[str, Any] | None:
    for row in OPENROUTER_APPS:
        if isinstance(row, dict) and str(row.get("id") or "") == service_id:
            return row
    return None


def service_label(service: str) -> str:
    row = _catalog_row(service)
    if row:
        return str(row.get("label") or service)
    return service


def _app_meta(service_id: str) -> dict[str, Any]:
    row = _catalog_row(service_id)
    if row:
        return {
            "id": service_id,
            "label": str(row.get("label") or service_id),
            "title": str(row.get("title") or ""),
            "referer": str(row.get("referer") or ""),
            "repo": str(row.get("repo") or ""),
            "keyName": str(row.get("keyName") or ""),
            "meteredHere": bool(row.get("meteredHere")),
        }
    return {
        "id": service_id,
        "label": service_label(service_id),
        "title": "",
        "referer": "",
        "repo": "",
        "keyName": "",
        "meteredHere": False,
    }


def _empty_app(service_id: str) -> dict[str, Any]:
    bucket = _app_meta(service_id)
    bucket.update(
        {
            "promptTokens": 0,
            "completionTokens": 0,
            "totalTokens": 0,
            "cost": 0.0,
            "calls": 0,
            "owners": {},
        }
    )
    return bucket


def add_usage_day(
    table: Any,
    *,
    service: str,
    owner: str,
    usage: dict[str, Any] | None,
    calls: int = 1,
    date_iso: str | None = None,
) -> None:
    """Increment today's (or ``date_iso``'s) usage for one service+owner."""
    day = date_iso or utc_today()
    owner_key = (owner or "").strip() or "unknown"
    service_id = (service or "").strip() or SERVICE_STATEMENT_PARSER
    center = cost_center_for(service=service_id, owner=owner_key)
    normalized = normalize_usage(
        {
            "prompt_tokens": (usage or {}).get("promptTokens", 0),
            "completion_tokens": (usage or {}).get("completionTokens", 0),
            "total_tokens": (usage or {}).get("totalTokens", 0),
            "cost": (usage or {}).get("cost", 0.0),
        }
    )
    table.update_item(
        Key={"pk": usage_day_pk(day), "sk": f"{service_id}#{owner_key}"},
        UpdateExpression=(
            "ADD promptTokens :p, completionTokens :c, totalTokens :t, cost :cost, calls :calls "
            "SET #svc = :svc, #own = :own, costCenter = :cc, #day = :day"
        ),
        ExpressionAttributeNames={
            "#svc": "service",
            "#own": "owner",
            "#day": "day",
        },
        ExpressionAttributeValues={
            ":p": int(normalized["promptTokens"]),
            ":c": int(normalized["completionTokens"]),
            ":t": int(normalized["totalTokens"]),
            ":cost": Decimal(str(round(float(normalized["cost"] or 0.0), 6))),
            ":calls": int(calls),
            ":svc": service_id,
            ":own": owner_key,
            ":cc": center,
            ":day": day,
        },
    )


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float, Decimal)):
        return int(value)
    return 0


def _as_float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    return 0.0


def _row_from_item(item: dict[str, Any]) -> dict[str, Any]:
    sk = str(item.get("sk") or "")
    service = str(item.get("service") or "")
    owner = str(item.get("owner") or "")
    if not service or not owner:
        parts = sk.split("#", 1)
        if len(parts) == 2:
            service = service or parts[0]
            owner = owner or parts[1]
    center = str(item.get("costCenter") or "") or cost_center_for(
        service=service, owner=owner
    )
    return {
        "day": str(item.get("day") or ""),
        "service": service,
        "serviceLabel": service_label(service),
        "owner": owner,
        "ownerLabel": owner_label(owner),
        "costCenter": center,
        "costCenterLabel": owner_label(center),
        "promptTokens": _as_int(item.get("promptTokens")),
        "completionTokens": _as_int(item.get("completionTokens")),
        "totalTokens": _as_int(item.get("totalTokens")),
        "cost": round(_as_float(item.get("cost")), 6),
        "calls": _as_int(item.get("calls")),
    }


def _parse_day(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _date_range(from_day: str, to_day: str) -> list[str]:
    start = _parse_day(from_day)
    end = _parse_day(to_day)
    if start is None or end is None or end < start:
        raise ValueError("from/to must be YYYY-MM-DD with from ≤ to")
    days = (end.date() - start.date()).days + 1
    if days > _MAX_RANGE_DAYS:
        raise ValueError(f"range cannot exceed {_MAX_RANGE_DAYS} days")
    out: list[str] = []
    cursor = start
    while cursor <= end:
        out.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    return out


def default_month_range(now: datetime | None = None) -> tuple[str, str]:
    today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = today.replace(day=1)
    return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def list_usage(
    table: Any, *, from_day: str, to_day: str
) -> dict[str, Any]:
    days = _date_range(from_day, to_day)
    rows: list[dict[str, Any]] = []
    for day in days:
        result = table.query(
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": usage_day_pk(day)},
        )
        items = result.get("Items") if isinstance(result, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            row = _row_from_item(item)
            if not row["day"]:
                row["day"] = day
            rows.append(row)
    rows.sort(key=lambda r: (r["service"], r["owner"], r["day"]))
    return summarize(rows, from_day=from_day, to_day=to_day)


def summarize(
    rows: list[dict[str, Any]], *, from_day: str, to_day: str
) -> dict[str, Any]:
    totals = add_usage(None, None)
    total_calls = 0
    apps: dict[str, dict[str, Any]] = {}

    def ensure_app(service_id: str) -> dict[str, Any]:
        bucket = apps.get(service_id)
        if bucket is None:
            bucket = _empty_app(service_id)
            apps[service_id] = bucket
        return bucket

    for row in OPENROUTER_APPS:
        if isinstance(row, dict) and row.get("id"):
            ensure_app(str(row["id"]))

    for row in rows:
        totals = add_usage(totals, row)
        row_calls = int(row.get("calls") or 0)
        total_calls += row_calls
        svc_id = str(row.get("service") or "") or "unknown"
        bucket = ensure_app(svc_id)
        merged = add_usage(bucket, row)
        bucket.update(merged)
        bucket["calls"] = int(bucket.get("calls") or 0) + row_calls
        owner_id = str(row.get("owner") or "unknown")
        owner = bucket["owners"].setdefault(
            owner_id,
            {
                "id": owner_id,
                "label": owner_label(owner_id),
                "promptTokens": 0,
                "completionTokens": 0,
                "totalTokens": 0,
                "cost": 0.0,
                "calls": 0,
            },
        )
        merged_owner = add_usage(owner, row)
        owner.update(merged_owner)
        owner["calls"] = int(owner.get("calls") or 0) + row_calls
    totals["calls"] = total_calls

    catalog_ids = [
        str(row["id"])
        for row in OPENROUTER_APPS
        if isinstance(row, dict) and row.get("id")
    ]
    extra_ids = sorted(k for k in apps if k not in catalog_ids)
    apps_out: list[dict[str, Any]] = []
    for app_id in catalog_ids + extra_ids:
        bucket = apps[app_id]
        owners = sorted(
            bucket.pop("owners").values(), key=lambda o: str(o["label"]).lower()
        )
        for owner in owners:
            owner["cost"] = round(float(owner["cost"]), 6)
        bucket["cost"] = round(float(bucket["cost"]), 6)
        bucket["owners"] = owners
        apps_out.append(bucket)

    totals["cost"] = round(float(totals["cost"]), 6)
    return {
        "from": from_day,
        "to": to_day,
        "currency": "USD",
        "payer": payer_payload(),
        "total": totals,
        "apps": apps_out,
        "rows": rows,
    }


def handle_usage_get(event: dict[str, Any]) -> dict[str, Any]:
    """GET /openrouter/usage?from=YYYY-MM-DD&to=YYYY-MM-DD (UTC month default)."""
    from http_common import _json_response
    import runtime

    qs = parse_qs(event.get("rawQueryString") or "")
    default_from, default_to = default_month_range()
    from_day = (qs.get("from", [default_from])[0] or default_from).strip()
    to_day = (qs.get("to", [default_to])[0] or default_to).strip()
    try:
        payload = list_usage(
            runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"]),
            from_day=from_day,
            to_day=to_day,
        )
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    return _json_response(200, payload)
