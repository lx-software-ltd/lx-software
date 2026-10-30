"""Monthly resume spend with a compare-and-swap token, matching the LinkedIn ledger."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import resume_store
from botocore.exceptions import ClientError
from ddb_convert import _to_ddb_nested


class _SpendConflict(Exception):
    pass


def month_key(now: datetime | None = None) -> str:
    local = (now or datetime.now(resume_store.HKT)).astimezone(resume_store.HKT)
    return f"{local.year:04d}-{local.month:02d}"


def month_spend(table: Any, now: datetime | None = None) -> float:
    spend = resume_store._load_sk(table, "SPEND").get("spend")
    if not isinstance(spend, dict):
        return 0.0
    try:
        return float(spend.get(month_key(now)) or 0)
    except (TypeError, ValueError):
        return 0.0


def _conflict(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    return str(response.get("Error", {}).get("Code") or "") == "ConditionalCheckFailedException"


def _put_spend(table: Any, previous: dict[str, Any], spend_map: dict[str, Any]) -> None:
    item = _to_ddb_nested(
        {
            **resume_store._state_key("SPEND"),
            "spend": spend_map,
            "spendToken": uuid.uuid4().hex,
            "updatedAt": resume_store._now(),
        }
    )
    if not previous:
        condition = "attribute_not_exists(pk)"
        values = None
    elif "spendToken" not in previous:
        condition = "attribute_not_exists(spendToken)"
        values = None
    else:
        condition = "spendToken = :prev"
        values = {":prev": previous.get("spendToken")}
    kwargs: dict[str, Any] = {"Item": item, "ConditionExpression": condition}
    if values is not None:
        kwargs["ExpressionAttributeValues"] = values
    try:
        table.put_item(**kwargs)
    except ClientError as exc:
        if _conflict(exc):
            raise _SpendConflict from exc
        raise


def _trim(spend: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(str(key) for key in spend)[-13:]
    return {key: spend[key] for key in keys}


def adjust_spend(table: Any, usd: float, now: datetime | None = None) -> float:
    key = month_key(now)
    updated = 0.0
    for _attempt in range(5):
        doc = resume_store._load_sk(table, "SPEND")
        spend = dict(doc.get("spend") or {})
        try:
            current = float(spend.get(key) or 0)
        except (TypeError, ValueError):
            current = 0.0
        updated = round(max(0.0, current + usd), 6)
        spend[key] = updated
        try:
            _put_spend(table, doc, _trim(spend))
            return updated
        except _SpendConflict:
            continue
    return updated


def try_reserve_spend(table: Any, usd: float, cap: float, now: datetime | None = None) -> bool:
    if usd <= 0:
        return True
    key = month_key(now)
    for _attempt in range(5):
        doc = resume_store._load_sk(table, "SPEND")
        spend = dict(doc.get("spend") or {})
        try:
            current = float(spend.get(key) or 0)
        except (TypeError, ValueError):
            current = 0.0
        if current + usd > cap + 1e-9:
            return False
        spend[key] = round(current + usd, 6)
        try:
            _put_spend(table, doc, _trim(spend))
            return True
        except _SpendConflict:
            continue
    return False
