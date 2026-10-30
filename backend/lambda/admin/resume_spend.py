"""Monthly resume spend with a compare-and-swap token, matching the LinkedIn ledger.

A job reserves an estimate, adds each model call as it returns, and settles to
that actual cost. The reserve, the calls, and the settle stay inside the
existing Lambda limit: the budget is 220 seconds and a poll finalizes a job
that is still running after 280 seconds.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import resume_store
from botocore.exceptions import ClientError
from ddb_convert import _to_ddb_nested
from resume_store import ResumeError
from timeutil import parse_iso_strict, utc_now

BUDGET_DEFAULT = 220
STALE_DEFAULT = 280
CALL_FLOOR = 10
HEADROOM = 5


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


def _limit(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        parsed = int(raw)
    except ValueError:
        parsed = default
    return max(CALL_FLOOR, parsed)


def job_budget_seconds() -> int:
    return _limit("RESUME_JOB_BUDGET_SECONDS", BUDGET_DEFAULT)


def job_stale_seconds() -> int:
    return _limit("RESUME_JOB_STALE_SECONDS", STALE_DEFAULT)


def bounded_timeout(started_at: str | None, preferred: int) -> int:
    """Seconds for one model call that still fits in the job budget."""
    elapsed = 0.0
    if started_at:
        try:
            started = parse_iso_strict(started_at)
        except ValueError:
            started = None
        if started is not None:
            elapsed = (utc_now() - started.astimezone(timezone.utc)).total_seconds()
    remaining = int(job_budget_seconds() - elapsed - HEADROOM)
    allowed = min(int(preferred), remaining)
    if allowed < CALL_FLOOR:
        raise ResumeError("This resume job ran out of time.")
    return allowed


def _usage_cost(usage: dict[str, Any] | None) -> float:
    if not isinstance(usage, dict):
        return 0.0
    try:
        return float(usage.get("cost") or 0)
    except (TypeError, ValueError):
        return 0.0


def _persist(table: Any, job: dict[str, Any]) -> None:
    if job.get("jobId"):
        resume_store.put_job(table, job)


def reserve_job(table: Any, job: dict[str, Any], cap: float) -> None:
    if job.get("spendSettled") or float(job.get("spendReservedUsd") or 0) > 0:
        return
    if not try_reserve_spend(table, resume_store.ESTIMATE_USD, cap):
        raise ResumeError("This month's resume spend cap has been reached.")
    job["spendReservedUsd"] = resume_store.ESTIMATE_USD
    job["spendActualUsd"] = float(job.get("spendActualUsd") or 0)
    job["spendSettled"] = False
    _persist(table, job)


def add_usage(table: Any, job: dict[str, Any], usage: dict[str, Any] | None) -> None:
    job["spendActualUsd"] = round(float(job.get("spendActualUsd") or 0) + _usage_cost(usage), 6)
    _persist(table, job)


def settle_job(table: Any, job: dict[str, Any]) -> None:
    if job.get("jobId"):
        fresh = resume_store.get_job(table, str(job["jobId"]))
        if fresh and fresh.get("spendSettled"):
            job["spendSettled"] = True
            return
        if fresh and "spendActualUsd" in fresh:
            job["spendActualUsd"] = fresh.get("spendActualUsd")
        if fresh and "spendReservedUsd" in fresh:
            job["spendReservedUsd"] = fresh.get("spendReservedUsd")
    if job.get("spendSettled"):
        return
    reserved = float(job.get("spendReservedUsd") or 0)
    actual = float(job.get("spendActualUsd") or 0)
    if not reserved and not actual:
        return
    adjust_spend(table, actual - reserved)
    job["spendSettled"] = True
    _persist(table, job)


def _age_seconds(job: dict[str, Any]) -> float | None:
    anchor = str(job.get("startedAt") or job.get("createdAt") or "")
    if not anchor:
        return None
    try:
        started = parse_iso_strict(anchor)
    except ValueError:
        return None
    return (utc_now() - started.astimezone(timezone.utc)).total_seconds()


def is_stale(job: dict[str, Any]) -> bool:
    if job.get("status") not in {"queued", "running"}:
        return False
    age = _age_seconds(job)
    return age is not None and age >= job_stale_seconds()


def finalize_stale(table: Any, job: dict[str, Any]) -> dict[str, Any]:
    if not is_stale(job):
        return job
    settle_job(table, job)
    job["status"] = "failed"
    if not str(job.get("error") or "").strip():
        job["error"] = "This resume job ran out of time."
    _persist(table, job)
    return job
