"""Evolve Sprouts statement book, mirrored from the product database.

Cash only: succeeded customer payments (income), refunds (expenditure) and
submitted or paid expenses (expenditure). Issued invoices that are still
unpaid stay on the summary and are not written as book lines.

The product database is read through the RDS Data API. This stack does not
write to it.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any

import board_data_api
import runtime
from contract_constants import SUPPORTED_FINANCE_CURRENCIES
from ddb_convert import _from_ddb_nested, _to_ddb_nested
from finance_store import MirroredBookError, mirror_state_key, upsert_mirrored_lines
from http_common import _log_event

BOOK = "evolveSprouts"
SOURCE = "evolvesprouts"
ID_PREFIXES = ("es-pay-", "es-ref-", "es-exp-")

PAYMENTS_SQL = (
    "SELECT id, direction, amount, currency, succeeded_at "
    "FROM customer_payments "
    "WHERE status = 'succeeded' AND direction IN ('inbound', 'refund')"
)
EXPENSES_SQL = (
    "SELECT id, status, total, currency, invoice_date, paid_at, vendor_name, invoice_number "
    "FROM expenses "
    "WHERE status IN ('submitted', 'paid')"
)
OUTSTANDING_SQL = (
    "SELECT currency, COALESCE(SUM(balance_due), 0) AS outstanding, COUNT(*) AS n "
    "FROM customer_invoices "
    "WHERE status = 'issued' AND balance_due > 0 "
    "GROUP BY currency"
)


class EvolveSproutsFinanceError(MirroredBookError):
    """User-facing Evolve Sprouts finance failure."""


def configured() -> bool:
    return board_data_api.evolvesprouts_target().configured


def _q(sql: str) -> list[dict[str, Any]]:
    try:
        return board_data_api.execute(sql, target=board_data_api.evolvesprouts_target())
    except board_data_api.DataApiError as exc:
        raise EvolveSproutsFinanceError(str(exc)) from exc


def _instant(value: Any) -> str:
    text = str(value or "").strip()
    day = text[:10] if len(text) >= 10 else date.today().isoformat()
    return f"{day}T00:00:00.000Z"


def _amount(value: Any) -> float | None:
    try:
        amount = round(float(value), 2)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return amount


def _currency(value: Any) -> str | None:
    code = str(value or "").strip().upper()[:3]
    if len(code) < 3 or code not in SUPPORTED_FINANCE_CURRENCIES:
        return None
    return code


def _line(*, line_id: str, day: Any, description: str, amount: float, currency: str, line_type: str) -> dict[str, Any]:
    return {
        "id": line_id,
        "dateUtc": _instant(day),
        "type": line_type,
        "description": description[:8000],
        "netAmount": amount,
        "vat": 0,
        "grossAmount": amount,
        "currency": currency,
        "source": SOURCE,
    }


def _expense_description(row: dict[str, Any]) -> str:
    vendor = " ".join(str(row.get("vendor_name") or "").split())
    number = " ".join(str(row.get("invoice_number") or "").split())
    parts = [part for part in (vendor, number) if part]
    detail = " ".join(parts) if parts else str(row.get("id") or "")
    return f"[evolve-sprouts] Expense {detail}"[:8000]


def desired_book_lines() -> tuple[list[dict[str, Any]], int, int, int]:
    """Lines, skipped-currency rows, submitted expense count, paid expense count.

    Counts are rows that became book lines. Draft, voided, and amended expenses
    are not selected. An unsupported currency is skipped, not counted.
    """
    skipped = 0
    submitted = 0
    paid = 0
    lines: list[dict[str, Any]] = []
    for row in _q(PAYMENTS_SQL):
        amount = _amount(row.get("amount"))
        currency = _currency(row.get("currency"))
        row_id = str(row.get("id") or "").strip()
        if not row_id or amount is None:
            continue
        if currency is None:
            skipped += 1
            continue
        direction = str(row.get("direction") or "")
        if direction == "refund":
            lines.append(
                _line(
                    line_id=f"es-ref-{row_id}",
                    day=row.get("succeeded_at"),
                    description=f"[evolve-sprouts] Refund {row_id}",
                    amount=amount,
                    currency=currency,
                    line_type="expenditure",
                )
            )
        else:
            lines.append(
                _line(
                    line_id=f"es-pay-{row_id}",
                    day=row.get("succeeded_at"),
                    description=f"[evolve-sprouts] Payment {row_id}",
                    amount=amount,
                    currency=currency,
                    line_type="income",
                )
            )
    for row in _q(EXPENSES_SQL):
        amount = _amount(row.get("total"))
        currency = _currency(row.get("currency"))
        row_id = str(row.get("id") or "").strip()
        if not row_id or amount is None:
            continue
        if currency is None:
            skipped += 1
            continue
        status = str(row.get("status") or "")
        if status == "paid":
            paid += 1
        else:
            submitted += 1
        lines.append(
            _line(
                line_id=f"es-exp-{row_id}",
                day=row.get("invoice_date") or row.get("paid_at"),
                description=_expense_description(row),
                amount=amount,
                currency=currency,
                line_type="expenditure",
            )
        )
    return lines, skipped, submitted, paid


def _outstanding() -> tuple[dict[str, float], int, int]:
    outstanding: dict[str, float] = {}
    open_invoices = 0
    skipped = 0
    for row in _q(OUTSTANDING_SQL):
        currency = _currency(row.get("currency"))
        try:
            count = int(row.get("n") or 0)
            amount = round(float(row.get("outstanding") or 0), 2)
        except (TypeError, ValueError):
            continue
        if count <= 0 or amount <= 0:
            continue
        if currency is None:
            skipped += count
            continue
        outstanding[currency] = amount
        open_invoices += count
    return outstanding, open_invoices, skipped


def empty_summary(*, configured_now: bool) -> dict[str, Any]:
    return {
        "configured": configured_now,
        "syncedAt": None,
        "outstandingByCurrency": {},
        "openInvoices": 0,
        "submittedExpenses": 0,
        "paidExpenses": 0,
        "skippedUnsupportedCurrency": 0,
    }


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _summary_from_item(item: dict[str, Any]) -> dict[str, Any]:
    payload = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    nested = _from_ddb_nested(payload)
    if not isinstance(nested, dict):
        return empty_summary(configured_now=configured())
    outstanding = nested.get("outstandingByCurrency")
    if not isinstance(outstanding, dict):
        outstanding = {}
    return {
        "configured": configured(),
        "syncedAt": nested.get("syncedAt"),
        "outstandingByCurrency": {str(k): float(v) for k, v in outstanding.items()},
        "openInvoices": _as_int(nested.get("openInvoices")),
        "submittedExpenses": _as_int(nested.get("submittedExpenses")),
        "paidExpenses": _as_int(nested.get("paidExpenses")),
        "skippedUnsupportedCurrency": _as_int(nested.get("skippedUnsupportedCurrency")),
    }


def load_summary(table: Any) -> dict[str, Any]:
    res = table.get_item(Key=mirror_state_key(BOOK))
    item = res.get("Item")
    if not item:
        return empty_summary(configured_now=configured())
    return _summary_from_item(item)


def _save_summary(table: Any, summary: dict[str, Any]) -> None:
    table.put_item(Item={**mirror_state_key(BOOK), **_to_ddb_nested(summary)})


def sync(table: Any) -> dict[str, Any]:
    """Read the product database and upsert the Evolve Sprouts book."""
    if not configured():
        summary = empty_summary(configured_now=False)
        return {"ok": True, "skipped": "not_configured", **summary}
    lines, skipped_lines, submitted, paid = desired_book_lines()
    outstanding, open_invoices, skipped_invoices = _outstanding()
    written, removed = upsert_mirrored_lines(
        table,
        BOOK,
        lines,
        id_prefixes=ID_PREFIXES,
        source=SOURCE,
    )
    summary = {
        "configured": True,
        "syncedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "outstandingByCurrency": outstanding,
        "openInvoices": open_invoices,
        "submittedExpenses": submitted,
        "paidExpenses": paid,
        "skippedUnsupportedCurrency": skipped_lines + skipped_invoices,
    }
    _save_summary(table, summary)
    _log_event(
        "info",
        tag="evolvesprouts_finance_mirrored",
        lines=written,
        removed=removed,
        openInvoices=open_invoices,
    )
    return {"ok": True, "linesWritten": written, "linesRemoved": removed, **summary}


def handle_mirror_trigger(_event: dict[str, Any]) -> dict[str, Any]:
    if not configured():
        return {"ok": True, "skipped": "not_configured"}
    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
    return sync(table)
