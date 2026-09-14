"""Executive Board: aggregated finance summary and cash snapshot.

Only totals are produced (Siu Tin Dei statement book, fiscal year and trailing
three months, by currency; cash by account type and currency). No individual
lines, payees or account names leave the table. The LX Software statement book
is company overhead and is not on this board.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from finance_store import _load_accounts_records, _load_finance_owner

BOOKS = ("siuTinDei",)
BOOK_LABELS = {"siuTinDei": "Siu Tin Dei"}
STATEMENT_BOOK_SCOPE_NOTE = (
    "Siu Tin Dei product P&L only. The LX Software statement book is company "
    "overhead (admin, public site, untagged) and is not on this board."
)
ACCOUNTS_SHEET_NOTE = (
    "Liquid cash is Bank Account + Debit Card recordedValue from the owner's "
    "accounts sheet (all houses, not Siu Tin Dei operating cash). "
    "Credit cards are outstanding balances, not cash. "
    "Account names and numbers are omitted."
)


def _fiscal_year_start(now: datetime) -> datetime:
    year = now.year if now.month >= 4 else now.year - 1
    return datetime(year, 4, 1, tzinfo=timezone.utc)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def summarize_book(data: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    fy_start = _fiscal_year_start(now)
    trailing_start = now - timedelta(days=90)
    fy: dict[str, dict[str, float]] = defaultdict(lambda: {"income": 0.0, "expenditure": 0.0})
    trailing: dict[str, dict[str, float]] = defaultdict(
        lambda: {"income": 0.0, "expenditure": 0.0}
    )
    fy_count = 0
    total_count = 0
    latest: datetime | None = None
    for line in data.get("lines") or []:
        if not isinstance(line, dict):
            continue
        total_count += 1
        dt = _parse_iso(line.get("dateUtc"))
        if dt is None:
            continue
        if latest is None or dt > latest:
            latest = dt
        line_type = str(line.get("type") or "")
        if line_type not in ("income", "expenditure"):
            continue
        currency = str(line.get("currency") or "HKD").upper()
        amount = line.get("grossAmount")
        try:
            value = abs(float(amount))
        except (TypeError, ValueError):
            continue
        if dt >= fy_start:
            fy[currency][line_type] += value
            fy_count += 1
        if dt >= trailing_start:
            trailing[currency][line_type] += value

    def _rows(bucket: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
        out = []
        for currency in sorted(bucket):
            inc = round(bucket[currency]["income"], 2)
            exp = round(bucket[currency]["expenditure"], 2)
            out.append(
                {
                    "currency": currency,
                    "income": inc,
                    "expenditure": exp,
                    "net": round(inc - exp, 2),
                }
            )
        return out

    return {
        "fiscalYearStart": fy_start.strftime("%Y-%m-%d"),
        "fiscalYear": _rows(fy),
        "trailing90Days": _rows(trailing),
        "lineCountFiscalYear": fy_count,
        "lineCountTotal": total_count,
        "latestLineDate": latest.strftime("%Y-%m-%d") if latest else None,
    }


def build_finance_summary(table: Any, *, now: datetime | None = None) -> dict[str, Any]:
    books: dict[str, Any] = {}
    for book in BOOKS:
        try:
            data = _load_finance_owner(table, book)
        except Exception:  # pragma: no cover - defensive: summary is optional
            continue
        books[book] = summarize_book(data, now=now)
    return {
        "generatedAt": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d"),
        "scope": "siuTinDei",
        "note": STATEMENT_BOOK_SCOPE_NOTE,
        "books": books,
    }


def cash_snapshot(table: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Aggregated cash position and statement-book flow for month-end memos.

    Account names, numbers and payees are omitted. Liquid cash is Bank Account
    plus Debit Card ``recordedValue``; credit-card balances are outstanding debt.
    """
    now = now or datetime.now(timezone.utc)
    records = _load_accounts_records(table) if table is not None else []
    by_type: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"amount": 0.0, "count": 0, "latestUpdated": None}
    )
    liquid: dict[str, float] = defaultdict(float)
    credit: dict[str, float] = defaultdict(float)
    for row in records:
        account_type = str(row.get("accountType") or "")
        currency = str(row.get("currency") or "HKD").upper()
        try:
            amount = float(row.get("recordedValue") or 0)
        except (TypeError, ValueError):
            continue
        bucket = by_type[(account_type, currency)]
        bucket["amount"] = round(bucket["amount"] + amount, 2)
        bucket["count"] += 1
        last_updated = row.get("lastUpdated")
        if isinstance(last_updated, str) and (
            bucket["latestUpdated"] is None or last_updated > str(bucket["latestUpdated"])
        ):
            bucket["latestUpdated"] = last_updated
        if account_type == "Credit Card":
            credit[currency] += amount
        else:
            liquid[currency] += amount

    def _currency_rows(values: dict[str, float]) -> list[dict[str, Any]]:
        return [{"currency": code, "amount": round(total, 2)} for code, total in sorted(values.items())]

    return {
        "asOf": now.strftime("%Y-%m-%d"),
        "cash": {
            "liquidByCurrency": _currency_rows(liquid),
            "creditCardByCurrency": _currency_rows(credit),
            "byType": [
                {
                    "accountType": account_type,
                    "currency": currency,
                    "amount": data["amount"],
                    "count": data["count"],
                    "latestUpdated": data["latestUpdated"],
                }
                for (account_type, currency), data in sorted(by_type.items())
            ],
            "accountCount": len(records),
            "note": ACCOUNTS_SHEET_NOTE,
        },
        "statementBooks": build_finance_summary(table, now=now)
        if table is not None
        else {
            "generatedAt": now.strftime("%Y-%m-%d"),
            "scope": "siuTinDei",
            "note": STATEMENT_BOOK_SCOPE_NOTE,
            "books": {},
        },
    }


def op_cash_snapshot(ctx: Any, _args: dict[str, Any]) -> dict[str, Any]:
    return cash_snapshot(getattr(ctx, "table", None))


def render_finance_summary(summary: dict[str, Any]) -> str:
    books = summary.get("books") or {}
    if not books:
        return ""
    lines = [
        "Finance summary (aggregated totals from the Siu Tin Dei statement book):"
    ]
    for book, data in books.items():
        label = BOOK_LABELS.get(book, book)
        lines.append(
            f"- {label}: {data.get('lineCountTotal', 0)} recorded lines, "
            f"latest {data.get('latestLineDate') or 'n/a'}."
        )
        fy_rows = data.get("fiscalYear") or []
        if fy_rows:
            for row in fy_rows:
                lines.append(
                    f"  - Fiscal year from {data.get('fiscalYearStart')}: "
                    f"income {row['income']:.2f} {row['currency']}, "
                    f"expenditure {row['expenditure']:.2f} {row['currency']}, "
                    f"net {row['net']:.2f} {row['currency']}."
                )
        else:
            lines.append("  - No lines in the current fiscal year.")
        for row in data.get("trailing90Days") or []:
            lines.append(
                f"  - Last 90 days: income {row['income']:.2f} {row['currency']}, "
                f"expenditure {row['expenditure']:.2f} {row['currency']}, "
                f"net {row['net']:.2f} {row['currency']}."
            )
    return "\n".join(lines)
