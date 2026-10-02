"""RDS Data API client for Aurora clusters this admin reads.

Used by ``board_receivables``, ``board_product``, and the Evolve Sprouts
statement-book mirror. No VPC: IAM auth against the cluster ARN + DB
secret imported as stack parameters. When those are blank the caller
returns a clear "not configured" error.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

import boto3
from botocore.exceptions import ClientError

from http_common import _log_event

_executor: Callable[[str, list[dict[str, Any]] | None], list[dict[str, Any]]] | None = None
_MAX_RESULT_PAGES = 100

# Postgres-side substrings that mark a unique-constraint violation (SQLSTATE 23505).
_UNIQUE_VIOLATION_MARKERS = ("duplicate key", "23505")


class DataApiError(RuntimeError):
    """User-facing Data API failure."""


def is_unique_violation(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _UNIQUE_VIOLATION_MARKERS)


@dataclass(frozen=True)
class Typed:
    """A parameter that needs an RDS Data API ``typeHint``.

    The Data API sends every non-numeric value as text; Postgres will not
    coerce text into ``uuid``, ``date``, ``timestamp`` or ``numeric`` bind
    parameters unless the hint is present (``WHERE id = :id`` fails with
    "operator does not exist: uuid = text").
    """

    value: Any
    hint: str

    def unwrap(self) -> Any:
        return self.value


def Uuid(value: Any) -> Typed:  # noqa: N802 - constructor-like helper
    return Typed(None if value in (None, "") else str(value), "UUID")


def Date(value: Any) -> Typed:  # noqa: N802
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        value = value.isoformat()
    return Typed(None if value in (None, "") else str(value)[:10], "DATE")


def Timestamp(value: Any) -> Typed:  # noqa: N802
    if isinstance(value, datetime):
        value = value.strftime("%Y-%m-%d %H:%M:%S")
    return Typed(None if value in (None, "") else str(value), "TIMESTAMP")


def Numeric(value: Any) -> Typed:  # noqa: N802
    """``numeric``/``decimal`` columns; the value is sent as its decimal text."""
    if value is None or value == "":
        return Typed(None, "DECIMAL")
    if isinstance(value, float):
        return Typed(f"{value:.2f}", "DECIMAL")
    return Typed(str(value), "DECIMAL")


@dataclass(frozen=True)
class DataApiTarget:
    """One Aurora cluster reached through the RDS Data API."""

    cluster_arn: str
    secret_arn: str
    database: str
    label: str

    @property
    def configured(self) -> bool:
        return bool(self.cluster_arn and self.secret_arn)


def target_from_env(prefix: str, *, default_database: str, label: str) -> DataApiTarget:
    database = (os.environ.get(f"{prefix}_DB_NAME") or default_database).strip() or default_database
    return DataApiTarget(
        cluster_arn=(os.environ.get(f"{prefix}_CLUSTER_ARN") or "").strip(),
        secret_arn=(os.environ.get(f"{prefix}_DB_SECRET_ARN") or "").strip(),
        database=database,
        label=label,
    )


def siutindei_target() -> DataApiTarget:
    return target_from_env("SIUTINDEI", default_database="siutindei", label="siutindei")


def evolvesprouts_target() -> DataApiTarget:
    return target_from_env(
        "EVOLVESPROUTS", default_database="evolvesprouts", label="Evolve Sprouts"
    )


def configured() -> bool:
    return siutindei_target().configured


def cluster_arn() -> str:
    return siutindei_target().cluster_arn


def secret_arn() -> str:
    return siutindei_target().secret_arn


def database_name() -> str:
    return siutindei_target().database


def set_executor_for_tests(fn: Callable[[str, list[dict[str, Any]] | None], list[dict[str, Any]]] | None) -> None:
    global _executor
    _executor = fn


def _param(name: str, value: Any) -> dict[str, Any]:
    if isinstance(value, Typed):
        if value.value is None:
            return {"name": name, "value": {"isNull": True}}
        return {"name": name, "value": {"stringValue": str(value.value)}, "typeHint": value.hint}
    if value is None:
        return {"name": name, "value": {"isNull": True}}
    if isinstance(value, bool):
        return {"name": name, "value": {"booleanValue": value}}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"name": name, "value": {"longValue": value}}
    if isinstance(value, float):
        return {"name": name, "value": {"doubleValue": value}}
    return {"name": name, "value": {"stringValue": str(value)}}


def params(**kwargs: Any) -> list[dict[str, Any]]:
    return [_param(k, v) for k, v in kwargs.items()]


def _unwrap_field(field: dict[str, Any]) -> Any:
    if "isNull" in field:
        return None
    for key in ("stringValue", "longValue", "doubleValue", "booleanValue", "uuidValue"):
        if key in field:
            return field[key]
    return None


def _rows_from_rds(resp: dict[str, Any]) -> list[dict[str, Any]]:
    meta = resp.get("columnMetadata") or []
    names = [str(c.get("name") or f"c{i}") for i, c in enumerate(meta)]
    out: list[dict[str, Any]] = []
    for record in resp.get("records") or []:
        row: dict[str, Any] = {}
        for i, field in enumerate(record):
            name = names[i] if i < len(names) else f"c{i}"
            row[name] = _unwrap_field(field) if isinstance(field, dict) else field
        out.append(row)
    return out


def statement_kwargs(
    sql: str,
    parameters: list[dict[str, Any]] | None = None,
    *,
    resource_arn: str | None = None,
    secret: str | None = None,
    database: str | None = None,
    transaction_id: str = "",
) -> dict[str, Any]:
    """Build the ``execute_statement`` request (shared with the smoke CLI)."""
    kwargs: dict[str, Any] = {
        "resourceArn": resource_arn or cluster_arn(),
        "secretArn": secret or secret_arn(),
        "database": database or database_name(),
        "sql": sql,
        "includeResultMetadata": True,
    }
    if parameters:
        kwargs["parameters"] = parameters
    if transaction_id:
        kwargs["transactionId"] = transaction_id
    return kwargs


def _not_configured_message(target: DataApiTarget) -> str:
    if target.label == "siutindei":
        return (
            "siutindei Data API is not configured. Set SiutindeiClusterArn and "
            "redeploy so CDK can enable the HTTP endpoint, resolve the DB secret, "
            "and apply scripts/siutindei/receivables.sql."
        )
    return (
        f"{target.label} Data API is not configured. Set the cluster ARN and "
        "database secret, then redeploy so CDK can enable the HTTP endpoint."
    )


def execute(
    sql: str,
    parameters: list[dict[str, Any]] | None = None,
    *,
    target: DataApiTarget | None = None,
) -> list[dict[str, Any]]:
    chosen = target or siutindei_target()
    if _executor is not None:
        return _executor(sql, parameters)
    if not chosen.configured:
        raise DataApiError(_not_configured_message(chosen))
    client = boto3.client("rds-data")
    rows: list[dict[str, Any]] = []
    next_token = ""
    pages = 0
    try:
        while True:
            pages += 1
            if pages > _MAX_RESULT_PAGES:
                raise DataApiError(
                    f"Data API: {chosen.label} returned more than {_MAX_RESULT_PAGES} pages"
                )
            kwargs = statement_kwargs(
                sql,
                parameters,
                resource_arn=chosen.cluster_arn,
                secret=chosen.secret_arn,
                database=chosen.database,
            )
            if next_token:
                kwargs["nextToken"] = next_token
            resp = client.execute_statement(**kwargs)
            rows.extend(_rows_from_rds(resp))
            next_token = str(resp.get("nextToken") or "")
            if not next_token:
                break
    except ClientError as exc:
        raise DataApiError(f"Data API: {exc.response.get('Error', {}).get('Message', exc)}") from exc
    _log_event("info", tag="board_data_api", rows=len(rows), pages=pages, database=chosen.database)
    return rows
