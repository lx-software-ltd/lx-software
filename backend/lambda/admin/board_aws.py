"""Executive Board ``aws`` tool: Cost Explorer, CloudWatch, Health.

Reads are cached under ``BOARD#…#cache`` and refreshed hourly by
``board_cache``. Results are filtered to resources tagged for the siutindei
stacks (``BOARD_AWS_STACK_PREFIX``, default ``siutindei``); when the tag
filter matches nothing the cost read falls back to the whole account and
says so (``scope: "account"``). Lambda health queries only the function
names listed in ``BOARD_AWS_LAMBDA_NAMES``. The board never
creates IAM, DNS or Cognito changes; ``aws_propose_budget_alert`` only
queues an action item for the founder.

Plan: docs/architecture/executive-board-tools-plan.md §4 ``aws``.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

import board_store
from http_common import _log_event, _utc_iso_z

STACK_PREFIX_DEFAULT = "siutindei"
COST_CACHE = "aws:monthly_cost"
ALARMS_CACHE = "aws:alarms"
LAMBDA_CACHE = "aws:lambda_health"
HEALTH_CACHE = "aws:health"
COST_SCOPE_STACK = "siutindei"
COST_SCOPE_ACCOUNT = "account"
COST_ACCOUNT_NOTE = (
    "The aws:cloudformation:stack-name tag filter matched no cost, so this is the whole account's spend, "
    "not just the siutindei stacks."
)
# The siutindei product stacks live in a separate repository, so their deployed
# Lambda function names are not known here. Operators set them with
# ``BOARD_AWS_LAMBDA_NAMES`` (comma-separated, real function names as shown in
# the Lambda console, not CloudFormation logical ids). An empty list means the
# health read reports "no functions configured" instead of guessing.
DEFAULT_LAMBDA_NAMES: tuple[str, ...] = ()
NO_FUNCTIONS_NOTE = "no functions configured; set BOARD_AWS_LAMBDA_NAMES to the deployed siutindei Lambda function names"


class AwsToolError(RuntimeError):
    """User-facing failure talking to an AWS read API."""


def stack_prefix() -> str:
    return (os.environ.get("BOARD_AWS_STACK_PREFIX") or STACK_PREFIX_DEFAULT).strip() or STACK_PREFIX_DEFAULT


def lambda_function_names() -> list[str]:
    """Real Lambda function names to query, from ``BOARD_AWS_LAMBDA_NAMES``."""
    raw = os.environ.get("BOARD_AWS_LAMBDA_NAMES")
    if raw is None:
        return list(DEFAULT_LAMBDA_NAMES)
    names: list[str] = []
    for part in raw.split(","):
        name = part.strip()
        if name and name not in names:
            names.append(name)
    return names


def _client(service: str, *, region: str | None = None) -> Any:
    kwargs: dict[str, Any] = {}
    if region:
        kwargs["region_name"] = region
    return boto3.client(service, **kwargs)  # noqa: S311 - AWS SDK


def _ce() -> Any:
    return _client("ce", region="us-east-1")


def _cw() -> Any:
    return _client("cloudwatch")


def _health() -> Any:
    return _client("health", region="us-east-1")


def _cached(table: Any, name: str) -> dict[str, Any] | None:
    hit = board_store.get_cache(table, name)
    if not hit:
        return None
    payload = hit.get("payload")
    if not isinstance(payload, dict):
        return None
    return {**payload, "cached": True, "fetchedAt": hit.get("fetchedAt")}


def _store(table: Any, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    doc = board_store.put_cache(table, name, payload)
    return {**payload, "cached": False, "fetchedAt": doc.get("fetchedAt")}


def _matches_prefix(name: str) -> bool:
    prefix = stack_prefix().lower()
    return prefix in name.lower()


def _cost_query(start: str, end: str, *, filtered: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "TimePeriod": {"Start": start, "End": end},
        "Granularity": "MONTHLY",
        "Metrics": ["UnblendedCost"],
        "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
    }
    if filtered:
        kwargs["Filter"] = {
            "Tags": {
                "Key": "aws:cloudformation:stack-name",
                "Values": [stack_prefix()],
                "MatchOptions": ["STARTS_WITH"],
            }
        }
    return _ce().get_cost_and_usage(**kwargs)


def _cost_rows(resp: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    results: list[dict[str, Any]] = []
    total = 0.0
    for period in resp.get("ResultsByTime") or []:
        for group in period.get("Groups") or []:
            keys = group.get("Keys") or ["unknown"]
            amount = float(((group.get("Metrics") or {}).get("UnblendedCost") or {}).get("Amount") or 0)
            if amount <= 0:
                continue
            total += amount
            results.append({"service": keys[0], "usd": round(amount, 2)})
    results.sort(key=lambda r: r["usd"], reverse=True)
    return results, total


def fetch_monthly_cost() -> dict[str, Any]:
    end = datetime.now(timezone.utc).date()
    start = (end.replace(day=1) - timedelta(days=1)).replace(day=1)
    end_month = end.replace(day=1)
    scope = COST_SCOPE_STACK
    note = ""
    results: list[dict[str, Any]] = []
    total = 0.0
    try:
        results, total = _cost_rows(_cost_query(start.isoformat(), end_month.isoformat(), filtered=True))
    except ClientError as exc:
        # The tag filter can fail on an account with no Cost Explorer tag data yet.
        if exc.response.get("Error", {}).get("Code") not in ("ValidationException", "DataUnavailableException"):
            raise AwsToolError(f"Cost Explorer: {exc.response.get('Error', {}).get('Message', exc)}") from exc
        scope = COST_SCOPE_ACCOUNT
    if scope == COST_SCOPE_STACK and not results:
        scope = COST_SCOPE_ACCOUNT
    if scope == COST_SCOPE_ACCOUNT:
        note = COST_ACCOUNT_NOTE
        _log_event("info", tag="board_aws_cost_account_fallback", stackPrefix=stack_prefix())
        try:
            results, total = _cost_rows(_cost_query(start.isoformat(), end_month.isoformat(), filtered=False))
        except ClientError as exc:
            raise AwsToolError(f"Cost Explorer: {exc.response.get('Error', {}).get('Message', exc)}") from exc
    return {
        "periodStart": start.isoformat(),
        "periodEnd": end_month.isoformat(),
        "stackPrefix": stack_prefix(),
        "scope": scope,
        "note": note,
        "totalUsd": round(total, 2),
        "byService": results[:15],
    }


def fetch_alarms() -> dict[str, Any]:
    try:
        resp = _cw().describe_alarms(StateValue="ALARM", MaxRecords=50)
    except ClientError as exc:
        raise AwsToolError(f"CloudWatch alarms: {exc.response.get('Error', {}).get('Message', exc)}") from exc
    alarms = []
    for a in resp.get("MetricAlarms") or []:
        name = str(a.get("AlarmName") or "")
        if not _matches_prefix(name) and not _matches_prefix(str(a.get("Namespace") or "")):
            # Keep alarms that mention the prefix in name/namespace; skip the rest
            # only when a prefix is set and the name is clearly unrelated.
            if stack_prefix() and stack_prefix().lower() not in name.lower():
                continue
        alarms.append(
            {
                "name": name,
                "namespace": a.get("Namespace"),
                "metric": a.get("MetricName"),
                "reason": str(a.get("StateReason") or "")[:240],
                "updatedAt": str(a.get("StateUpdatedTimestamp") or "")[:25],
            }
        )
    return {"stackPrefix": stack_prefix(), "count": len(alarms), "alarms": alarms}


def fetch_lambda_health() -> dict[str, Any]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=24)
    functions = lambda_function_names()
    if not functions:
        return {"windowHours": 24, "functionNames": [], "functions": [], "note": NO_FUNCTIONS_NOTE}
    out: list[dict[str, Any]] = []
    for fn in functions:
        try:
            resp = _cw().get_metric_data(
                MetricDataQueries=[
                    {
                        "Id": "errors",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": "AWS/Lambda",
                                "MetricName": "Errors",
                                "Dimensions": [{"Name": "FunctionName", "Value": fn}],
                            },
                            "Period": 86400,
                            "Stat": "Sum",
                        },
                    },
                    {
                        "Id": "duration",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": "AWS/Lambda",
                                "MetricName": "Duration",
                                "Dimensions": [{"Name": "FunctionName", "Value": fn}],
                            },
                            "Period": 86400,
                            "Stat": "Average",
                        },
                    },
                ],
                StartTime=start,
                EndTime=end,
            )
        except ClientError as exc:
            out.append({"function": fn, "error": str(exc.response.get("Error", {}).get("Message", exc))[:160]})
            continue
        values = {r.get("Id"): (r.get("Values") or [0]) for r in resp.get("MetricDataResults") or []}
        errors = float((values.get("errors") or [0])[-1] or 0)
        duration = float((values.get("duration") or [0])[-1] or 0)
        out.append({"function": fn, "errors24h": int(errors), "avgDurationMs": round(duration, 1)})
    return {"windowHours": 24, "functionNames": functions, "functions": out}


def fetch_health_events() -> dict[str, Any]:
    try:
        resp = _health().describe_events(
            filter={"eventStatusCodes": ["open", "upcoming"]},
            maxResults=20,
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("SubscriptionRequiredException", "AccessDeniedException"):
            return {"events": [], "note": "AWS Health is not enabled on this account (Business/Enterprise support)."}
        raise AwsToolError(f"AWS Health: {exc.response.get('Error', {}).get('Message', exc)}") from exc
    events = []
    for e in resp.get("events") or []:
        events.append(
            {
                "arn": e.get("arn"),
                "service": e.get("service"),
                "region": e.get("region"),
                "status": e.get("statusCode"),
                "type": e.get("eventTypeCode"),
                "start": str(e.get("startTime") or "")[:25],
            }
        )
    return {"count": len(events), "events": events}


def refresh_caches(table: Any) -> dict[str, str]:
    notes: dict[str, str] = {}
    for name, fn in (
        (COST_CACHE, fetch_monthly_cost),
        (ALARMS_CACHE, fetch_alarms),
        (LAMBDA_CACHE, fetch_lambda_health),
        (HEALTH_CACHE, fetch_health_events),
    ):
        try:
            _store(table, name, fn())
            notes[name] = "ok"
        except Exception as exc:
            notes[name] = str(exc)[:200]
            _log_event("warning", tag="board_aws_refresh_failed", key=name, error=str(exc)[:200])
    return notes


def _read(table: Any, name: str, fetcher: Any) -> dict[str, Any]:
    cached = _cached(table, name)
    if cached:
        return cached
    try:
        return _store(table, name, fetcher())
    except ClientError as exc:
        raise AwsToolError(str(exc)[:300]) from exc


def op_monthly_cost(ctx: Any, _args: dict[str, Any]) -> dict[str, Any]:
    return _read(ctx.table, COST_CACHE, fetch_monthly_cost)


def op_alarms(ctx: Any, _args: dict[str, Any]) -> dict[str, Any]:
    return _read(ctx.table, ALARMS_CACHE, fetch_alarms)


def op_lambda_health(ctx: Any, _args: dict[str, Any]) -> dict[str, Any]:
    return _read(ctx.table, LAMBDA_CACHE, fetch_lambda_health)


def op_health_events(ctx: Any, _args: dict[str, Any]) -> dict[str, Any]:
    return _read(ctx.table, HEALTH_CACHE, fetch_health_events)


def op_propose_budget_alert(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Owner-approved: record an action item. Never calls AWS Budgets."""
    amount = args.get("monthlyUsd")
    try:
        monthly = float(amount)
    except (TypeError, ValueError) as exc:
        raise AwsToolError("monthlyUsd must be a number") from exc
    if monthly <= 0 or monthly > 100_000:
        raise AwsToolError("monthlyUsd must be between 0 and 100000")
    threshold = args.get("thresholdPercent") or 80
    try:
        pct = float(threshold)
    except (TypeError, ValueError) as exc:
        raise AwsToolError("thresholdPercent must be a number") from exc
    title = f"Create an AWS budget alert at USD {monthly:.0f}/month ({pct:.0f}% threshold) for {stack_prefix()}"
    now = _utc_iso_z(datetime.now(timezone.utc))
    doc = {
        "actionId": board_store.new_id(),
        "title": title[:200],
        "detail": str(args.get("reason") or "Proposed by the board after reviewing Cost Explorer.")[:800],
        "persona": ctx.persona_id or "cto",
        "priority": "next",
        "effort": "S",
        "metric": f"Budget exists and alerts at {pct:.0f}% of USD {monthly:.0f}",
        "dependsOn": [],
        "status": "open",
        "note": "",
        "meetingId": getattr(ctx, "meeting_id", "") or "",
        "source": "tool",
        "reaffirmedByMeetingIds": [],
        "dueAt": None,
        "createdAt": now,
        "updatedAt": now,
    }
    board_store.put_action(ctx.table, doc)
    return {"ok": True, "actionId": doc["actionId"], "title": title, "monthlyUsd": monthly, "thresholdPercent": pct}


def digest_for_context(table: Any) -> dict[str, Any]:
    cost = _cached(table, COST_CACHE) or {}
    alarms = _cached(table, ALARMS_CACHE) or {}
    return {
        "totalUsd": (cost.get("totalUsd") if not cost.get("error") else None),
        "alarmCount": alarms.get("count"),
        "fetchedAt": cost.get("fetchedAt") or alarms.get("fetchedAt"),
    }
