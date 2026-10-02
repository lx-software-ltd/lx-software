"""Evolve Sprouts statement book, mirrored from the product database.

Cash only: succeeded customer payments (income), refunds (expenditure) and
submitted or paid expenses (expenditure). Issued invoices that are still
unpaid stay on the summary and are not written as book lines.

Dates use the Asia/Hong_Kong calendar day, stored as that day at 00:00 UTC
(the same convention as a date typed into the other books). Expenses use
the vendor invoice issued date (``invoice_date``). Gains use the customer
invoice ``paid_at`` when the payment is allocated to a settled invoice,
otherwise the payment ``succeeded_at``.

The product database is read through the RDS Data API. This stack does not
write to it.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo

    _HKT = ZoneInfo("Asia/Hong_Kong")
except Exception:  # pragma: no cover - Lambda images ship tzdata
    _HKT = timezone(timedelta(hours=8))

import board_async
import board_data_api
import runtime
from contract_constants import SUPPORTED_FINANCE_CURRENCIES
from ddb_convert import _from_ddb_nested, _to_ddb_nested
from finance_store import MirroredBookError, mirror_state_key, upsert_mirrored_lines
from http_common import _log_event

BOOK = "evolveSprouts"
SOURCE = "evolvesprouts"
ID_PREFIXES = ("es-pay-", "es-ref-", "es-exp-")
MIRROR_INTERNAL = "evolvesprouts_finance_mirror"

PAYMENTS_SQL = (
    "SELECT id, direction, amount, currency, succeeded_at "
    "FROM customer_payments "
    "WHERE status = 'succeeded' AND direction IN ('inbound', 'refund') "
    "ORDER BY succeeded_at, id"
)
INVOICE_PAID_SQL = (
    "SELECT a.payment_id, MAX(i.paid_at) AS invoice_paid_at "
    "FROM payment_allocations a "
    "JOIN customer_invoices i ON i.id = a.invoice_id "
    "WHERE i.paid_at IS NOT NULL "
    "GROUP BY a.payment_id"
)
# Vendor names live on organizations (expenses.vendor_name was dropped in
# evolvesprouts migration 0016).
EXPENSES_SQL = (
    "SELECT e.id, e.status, e.total, e.subtotal, e.tax, e.currency, "
    "e.invoice_date, o.name AS vendor_name, e.invoice_number "
    "FROM expenses e "
    "LEFT JOIN organizations o ON o.id = e.vendor_id "
    "WHERE e.status IN ('submitted', 'paid') "
    "ORDER BY e.invoice_date, e.id"
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


def _hkt_day(value: Any) -> str | None:
    """Calendar day in Asia/Hong_Kong, or None when the value is missing."""
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            return text[:10]
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_HKT)
    return parsed.astimezone(_HKT).date().isoformat()


def _book_instant(day: str) -> str:
    return f"{day}T00:00:00.000Z"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"


def _money(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _positive(value: Any) -> float | None:
    amount = _money(value)
    if amount is None or amount <= 0:
        return None
    return amount


def _currency(value: Any) -> str | None:
    code = str(value or "").strip().upper()[:3]
    if len(code) < 3:
        return None
    if code not in SUPPORTED_FINANCE_CURRENCIES:
        return None
    return code


def _currency_present(value: Any) -> bool:
    return len(str(value or "").strip()) >= 3


def _line(
    *,
    line_id: str,
    day: str,
    description: str,
    net: float,
    vat: float,
    gross: float,
    currency: str,
    line_type: str,
) -> dict[str, Any]:
    return {
        "id": line_id,
        "dateUtc": _book_instant(day),
        "type": line_type,
        "description": description[:8000],
        "netAmount": net,
        "vat": vat,
        "grossAmount": gross,
        "currency": currency,
        "source": SOURCE,
    }


def _expense_description(row: dict[str, Any]) -> str:
    vendor = " ".join(str(row.get("vendor_name") or "").split())
    number = " ".join(str(row.get("invoice_number") or "").split())
    parts = [part for part in (vendor, number) if part]
    detail = " ".join(parts) if parts else str(row.get("id") or "")
    return detail[:8000]


def _expense_amounts(row: dict[str, Any]) -> tuple[float, float, float] | None:
    gross = _positive(row.get("total"))
    if gross is None:
        return None
    vat = _money(row.get("tax"))
    if vat is None or vat < 0:
        vat = 0.0
    net = _money(row.get("subtotal"))
    if net is None:
        net = round(gross - vat, 2)
    if net < 0:
        net = 0.0
    return net, vat, gross


def _invoice_paid_at_by_payment() -> dict[str, Any]:
    """payment_id → customer invoice paid_at. Empty when the lookup is unavailable."""
    try:
        rows = _q(INVOICE_PAID_SQL)
    except EvolveSproutsFinanceError:
        _log_event("warning", tag="evolvesprouts_invoice_paid_at_unavailable")
        return {}
    paid_at: dict[str, Any] = {}
    for row in rows:
        payment_id = str(row.get("payment_id") or "").strip()
        value = row.get("invoice_paid_at")
        if payment_id and value:
            paid_at[payment_id] = value
    return paid_at


def desired_book_lines() -> tuple[list[dict[str, Any]], int, int, int, int]:
    """Lines, unsupported-currency rows, incomplete rows, submitted count, paid count.

    Counts are rows that became book lines. Draft, voided, and amended expenses
    are not selected. An unsupported currency is skipped, not counted as
    submitted or paid. A missing amount, currency, or date is incomplete.
    """
    skipped_currency = 0
    skipped_incomplete = 0
    submitted = 0
    paid = 0
    lines: list[dict[str, Any]] = []
    invoice_paid_at = _invoice_paid_at_by_payment()
    for row in _q(PAYMENTS_SQL):
        amount = _positive(row.get("amount"))
        row_id = str(row.get("id") or "").strip()
        direction = str(row.get("direction") or "")
        if direction == "refund":
            day = _hkt_day(row.get("succeeded_at"))
        else:
            day = _hkt_day(invoice_paid_at.get(row_id) or row.get("succeeded_at"))
        if not row_id or amount is None:
            continue
        if not _currency_present(row.get("currency")) or day is None:
            skipped_incomplete += 1
            continue
        currency = _currency(row.get("currency"))
        if currency is None:
            skipped_currency += 1
            continue
        if direction == "refund":
            lines.append(
                _line(
                    line_id=f"es-ref-{row_id}",
                    day=day,
                    description=f"[evolve-sprouts] Refund {row_id}",
                    net=amount,
                    vat=0,
                    gross=amount,
                    currency=currency,
                    line_type="expenditure",
                )
            )
        else:
            lines.append(
                _line(
                    line_id=f"es-pay-{row_id}",
                    day=day,
                    description=row_id[:8000],
                    net=amount,
                    vat=0,
                    gross=amount,
                    currency=currency,
                    line_type="income",
                )
            )
    for row in _q(EXPENSES_SQL):
        amounts = _expense_amounts(row)
        row_id = str(row.get("id") or "").strip()
        status = str(row.get("status") or "")
        day = _hkt_day(row.get("invoice_date"))
        if not row_id or amounts is None:
            if row_id and amounts is None:
                skipped_incomplete += 1
            continue
        if not _currency_present(row.get("currency")) or day is None:
            skipped_incomplete += 1
            continue
        currency = _currency(row.get("currency"))
        if currency is None:
            skipped_currency += 1
            continue
        net, vat, gross = amounts
        if status == "paid":
            paid += 1
        else:
            submitted += 1
        lines.append(
            _line(
                line_id=f"es-exp-{row_id}",
                day=day,
                description=_expense_description(row),
                net=net,
                vat=vat,
                gross=gross,
                currency=currency,
                line_type="expenditure",
            )
        )
    return lines, skipped_currency, skipped_incomplete, submitted, paid


def _outstanding() -> tuple[dict[str, float], int, int, int]:
    outstanding: dict[str, float] = {}
    open_invoices = 0
    skipped_currency = 0
    skipped_incomplete = 0
    for row in _q(OUTSTANDING_SQL):
        try:
            count = int(row.get("n") or 0)
            amount = round(float(row.get("outstanding") or 0), 2)
        except (TypeError, ValueError):
            continue
        if count <= 0 or amount <= 0:
            continue
        if not _currency_present(row.get("currency")):
            skipped_incomplete += count
            continue
        currency = _currency(row.get("currency"))
        if currency is None:
            skipped_currency += count
            continue
        outstanding[currency] = amount
        open_invoices += count
    return outstanding, open_invoices, skipped_currency, skipped_incomplete


def empty_summary(*, configured_now: bool) -> dict[str, Any]:
    return {
        "configured": configured_now,
        "syncedAt": None,
        "lastAttemptAt": None,
        "pendingSince": None,
        "syncError": None,
        "outstandingByCurrency": {},
        "openInvoices": 0,
        "submittedExpenses": 0,
        "paidExpenses": 0,
        "skippedUnsupportedCurrency": 0,
        "skippedIncomplete": 0,
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
        "lastAttemptAt": nested.get("lastAttemptAt"),
        "pendingSince": nested.get("pendingSince"),
        "syncError": nested.get("syncError"),
        "outstandingByCurrency": {str(k): float(v) for k, v in outstanding.items()},
        "openInvoices": _as_int(nested.get("openInvoices")),
        "submittedExpenses": _as_int(nested.get("submittedExpenses")),
        "paidExpenses": _as_int(nested.get("paidExpenses")),
        "skippedUnsupportedCurrency": _as_int(nested.get("skippedUnsupportedCurrency")),
        "skippedIncomplete": _as_int(nested.get("skippedIncomplete")),
    }


def load_summary(table: Any) -> dict[str, Any]:
    res = table.get_item(Key=mirror_state_key(BOOK))
    item = res.get("Item")
    if not item:
        return empty_summary(configured_now=configured())
    return _summary_from_item(item)


def _save_summary(table: Any, summary: dict[str, Any]) -> None:
    table.put_item(Item={**mirror_state_key(BOOK), **_to_ddb_nested(summary)})


def mark_sync_requested(table: Any) -> dict[str, Any]:
    summary = load_summary(table)
    requested = _now()
    summary["pendingSince"] = requested
    summary["syncError"] = None
    _save_summary(table, summary)
    return summary


def _record_sync_failure(table: Any, message: str) -> None:
    try:
        summary = load_summary(table)
        summary["pendingSince"] = None
        summary["lastAttemptAt"] = _now()
        summary["syncError"] = str(message)[:800]
        _save_summary(table, summary)
    except Exception:
        _log_event("error", tag="evolvesprouts_finance_mirror_error_unrecorded")


def sync(table: Any) -> dict[str, Any]:
    """Read the product database and upsert the Evolve Sprouts book."""
    if not configured():
        summary = empty_summary(configured_now=False)
        return {"ok": True, "skipped": "not_configured", **summary}
    lines, skipped_currency, skipped_incomplete, submitted, paid = desired_book_lines()
    outstanding, open_invoices, skipped_invoice_currency, skipped_invoice_incomplete = _outstanding()
    written, removed = upsert_mirrored_lines(
        table,
        BOOK,
        lines,
        id_prefixes=ID_PREFIXES,
        source=SOURCE,
    )
    now = _now()
    summary = {
        "configured": True,
        "syncedAt": now,
        "lastAttemptAt": now,
        "pendingSince": None,
        "syncError": None,
        "outstandingByCurrency": outstanding,
        "openInvoices": open_invoices,
        "submittedExpenses": submitted,
        "paidExpenses": paid,
        "skippedUnsupportedCurrency": skipped_currency + skipped_invoice_currency,
        "skippedIncomplete": skipped_incomplete + skipped_invoice_incomplete,
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


def queue_sync(table: Any) -> dict[str, Any]:
    """Stamp a pending snapshot and Event-invoke the mirror (API Gateway path)."""
    if not configured():
        return {"ok": True, "skipped": "not_configured", **empty_summary(configured_now=False)}
    summary = mark_sync_requested(table)
    invoked = board_async.try_invoke_event({"internal": MIRROR_INTERNAL})
    if not invoked:
        _log_event("warning", tag="evolvesprouts_finance_enqueue_deferred")
        summary["pendingSince"] = None
        summary["syncError"] = "Could not start the sync. Try again."
        _save_summary(table, summary)
        return {"ok": False, "queued": False, "invoked": False, **summary}
    return {"ok": True, "queued": True, "invoked": True, "requestedAt": summary["pendingSince"], **summary}


def handle_mirror_trigger(_event: dict[str, Any]) -> dict[str, Any]:
    if not configured():
        return {"ok": True, "skipped": "not_configured"}
    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
    try:
        return sync(table)
    except Exception as exc:
        _record_sync_failure(table, str(exc))
        raise
