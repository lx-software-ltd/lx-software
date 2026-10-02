"""Admin API: finance store."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import runtime
from botocore.exceptions import ClientError
from contract_constants import (
    ASSET_TYPES,
    DEFAULT_EXPENSE_INCOME_ALLOCATION_PERCENTAGES,
    DEFAULT_FINANCE_CURRENCY,
    EXPENSE_RECORD_CATEGORIES,
    FINANCE_ACCOUNT_TYPES,
    FINANCE_HOUSE_KEYS,
    FINANCE_LIABILITY_TYPES,
    FINANCE_LINE_TYPES,
    FINANCE_STATEMENT_BOOK_KEYS,
    FINANCE_STATEMENT_OWNER_KEYS,
    INCOME_RECORD_CATEGORIES,
    INVESTMENT_RECORD_CATEGORIES,
    LEDGER_RECORD_AMOUNT_PERIODS,
    MAX_FINANCE_DESCRIPTION,
    MAX_FINANCE_LINES,
    MAX_INVESTMENT_CRYPTO_CURRENCY_LEN,
    MAX_INVESTMENT_PROVIDER_LEN,
    MAX_INVESTMENT_TICKER_LEN,
    MAX_LEDGER_RECORDS,
    MAX_SOURCE_ASSET_KEY_LEN,
    MAX_SOURCE_ASSET_KEYS_PER_LINE,
    SUPPORTED_FINANCE_CURRENCIES,
)
from ddb_convert import _from_ddb_nested, _to_ddb, _to_ddb_nested
from http_common import _log_event, _utc_iso_z
from runtime import RECORD_PK_PREFIX


def _default_finance_house() -> dict[str, Any]:
    return {
        "defaultCurrency": DEFAULT_FINANCE_CURRENCY,
        "float": {"amount": 0, "currency": DEFAULT_FINANCE_CURRENCY},
        "lines": [],
    }


def _line_source_asset_keys_raw(line: dict[str, Any]) -> list[str]:
    """Collect source S3 keys from ``sourceAssetKeys`` and legacy ``sourceAssetKey``."""
    keys: list[str] = []
    raw_arr = line.get("sourceAssetKeys")
    if isinstance(raw_arr, list):
        for x in raw_arr:
            if isinstance(x, str) and x.strip():
                keys.append(x.strip())
    legacy = line.get("sourceAssetKey")
    if isinstance(legacy, str) and legacy.strip():
        keys.append(legacy.strip())
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _validated_line_source_asset_keys(raw: dict[str, Any], i: int) -> list[str]:
    """Strict validation for finance writes; merges legacy ``sourceAssetKey``."""
    if "sourceAssetKeys" in raw:
        sa = raw["sourceAssetKeys"]
        if sa is not None:
            if not isinstance(sa, list):
                raise ValueError(f"lines[{i}].sourceAssetKeys must be an array")
            for j, x in enumerate(sa):
                if not isinstance(x, str) or not x.strip():
                    raise ValueError(
                        f"lines[{i}].sourceAssetKeys[{j}] must be a non-empty string"
                    )
    if "sourceAssetKey" in raw:
        sk = raw["sourceAssetKey"]
        if sk is not None and (not isinstance(sk, str) or not sk.strip()):
            raise ValueError(
                f"lines[{i}].sourceAssetKey must be a non-empty string when provided"
            )
    return _line_source_asset_keys_raw(raw)


def _coerce_finance_currency_value(raw: Any, fallback: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return fallback
    c = raw.strip().upper()[:3]
    if len(c) < 3 or c not in SUPPORTED_FINANCE_CURRENCIES:
        return fallback
    return c


def _sanitize_finance_house(stored: dict[str, Any]) -> dict[str, Any]:
    """Fill missing keys and coerce legacy currency strings for GET responses."""
    base = _default_finance_house()
    dc = _coerce_finance_currency_value(stored.get("defaultCurrency"), DEFAULT_FINANCE_CURRENCY)
    fl = stored.get("float")
    if isinstance(fl, dict):
        amt = fl.get("amount", 0)
        if not isinstance(amt, (int, float)) or isinstance(amt, bool):
            amt = 0
        cur = _coerce_finance_currency_value(fl.get("currency"), dc)
        float_out: dict[str, Any] = {"amount": float(amt), "currency": cur}
    else:
        float_out = dict(base["float"])
        float_out["currency"] = dc

    lines_out: list[dict[str, Any]] = []
    lines_raw = stored.get("lines")
    if isinstance(lines_raw, list):
        for raw in lines_raw:
            if not isinstance(raw, dict):
                continue
            cur_line = _coerce_finance_currency_value(raw.get("currency"), dc)
            row = dict(raw)
            row["currency"] = cur_line
            merged = _line_source_asset_keys_raw(row)
            row.pop("sourceAssetKey", None)
            row.pop("sourceAssetKeys", None)
            if merged:
                row["sourceAssetKeys"] = merged[:MAX_SOURCE_ASSET_KEYS_PER_LINE]
            lines_out.append(row)

    return {"defaultCurrency": dc, "float": float_out, "lines": lines_out}


def _require_supported_currency(raw: Any, field_label: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{field_label} is required")
    c = raw.strip().upper()[:3]
    if len(c) < 3:
        raise ValueError(f"{field_label} must be a 3-letter ISO currency code")
    if c not in SUPPORTED_FINANCE_CURRENCIES:
        allowed = ", ".join(sorted(SUPPORTED_FINANCE_CURRENCIES))
        raise ValueError(f"{field_label} must be one of: {allowed}")
    return c


def _valid_iso_instant(s: str) -> bool:
    try:
        datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _normalize_finance_payload(body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("Body must be a JSON object")

    if "defaultCurrency" in body:
        default_currency = _require_supported_currency(
            body["defaultCurrency"], "defaultCurrency"
        )
    else:
        default_currency = DEFAULT_FINANCE_CURRENCY

    fl = body.get("float")
    if not isinstance(fl, dict):
        raise ValueError("float is required")
    amt = fl.get("amount")
    if not isinstance(amt, (int, float)) or isinstance(amt, bool):
        raise ValueError("float.amount must be a number")
    if abs(float(amt)) > 1e15:
        raise ValueError("float.amount out of range")
    cur = _require_supported_currency(
        fl.get("currency", default_currency), "float.currency"
    )

    lines_raw = body.get("lines")
    if not isinstance(lines_raw, list):
        raise ValueError("lines must be an array")
    if len(lines_raw) > MAX_FINANCE_LINES:
        raise ValueError(f"At most {MAX_FINANCE_LINES} lines allowed")

    lines_out: list[dict[str, Any]] = []
    for i, raw in enumerate(lines_raw):
        if not isinstance(raw, dict):
            raise ValueError(f"lines[{i}] must be an object")
        lid = raw.get("id")
        if not isinstance(lid, str) or not lid.strip():
            raise ValueError(f"lines[{i}].id is required")
        date_utc = raw.get("dateUtc")
        if not isinstance(date_utc, str) or not _valid_iso_instant(date_utc):
            raise ValueError(f"lines[{i}].dateUtc must be a valid ISO-8601 instant")
        typ = raw.get("type")
        if typ not in FINANCE_LINE_TYPES:
            raise ValueError(
                f"lines[{i}].type must be income, expenditure, or mortgage"
            )
        desc = raw.get("description")
        if not isinstance(desc, str) or not desc.strip():
            raise ValueError(f"lines[{i}].description is required")
        if len(desc) > MAX_FINANCE_DESCRIPTION:
            raise ValueError(f"lines[{i}].description is too long")

        for key in ("netAmount", "vat", "grossAmount"):
            val = raw.get(key)
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise ValueError(f"lines[{i}].{key} must be a number")
            if abs(float(val)) > 1e15:
                raise ValueError(f"lines[{i}].{key} out of range")

        c = _require_supported_currency(
            raw.get("currency", default_currency), f"lines[{i}].currency"
        )

        line_out: dict[str, Any] = {
            "id": lid.strip(),
            "dateUtc": date_utc.strip(),
            "type": typ,
            "description": desc.strip(),
            "netAmount": float(raw["netAmount"]),
            "vat": float(raw["vat"]),
            "grossAmount": float(raw["grossAmount"]),
            "currency": c,
        }
        sort_utc = raw.get("sortUtc")
        if isinstance(sort_utc, str) and _valid_iso_instant(sort_utc):
            line_out["sortUtc"] = sort_utc.strip()

        merged_keys = _validated_line_source_asset_keys(raw, i)
        if len(merged_keys) > MAX_SOURCE_ASSET_KEYS_PER_LINE:
            raise ValueError(
                f"lines[{i}] must have at most {MAX_SOURCE_ASSET_KEYS_PER_LINE} "
                "source asset keys"
            )
        for k in merged_keys:
            if len(k) > MAX_SOURCE_ASSET_KEY_LEN:
                raise ValueError(f"lines[{i}] source asset key is too long")
        if merged_keys:
            line_out["sourceAssetKeys"] = merged_keys

        lines_out.append(line_out)

    return {
        "defaultCurrency": default_currency,
        "float": {"amount": float(amt), "currency": cur},
        "lines": lines_out,
    }


def _sanitize_ledger_records_list(
    raw: Any,
    categories: frozenset[str],
    *,
    include_income_flags: bool = False,
    include_expense_flags: bool = False,
) -> list[dict[str, Any]]:
    """Best-effort coercion for GET responses (drops invalid rows)."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        if not isinstance(rid, str) or not rid.strip():
            continue
        cat = row.get("category")
        if cat not in categories:
            continue
        desc = row.get("description")
        if not isinstance(desc, str) or not desc.strip():
            continue
        amt = row.get("amount")
        if isinstance(amt, Decimal):
            amt_f = float(amt)
        elif isinstance(amt, (int, float)) and not isinstance(amt, bool):
            amt_f = float(amt)
        elif isinstance(amt, str):
            try:
                amt_f = float(amt)
            except ValueError:
                continue
        else:
            continue
        if abs(amt_f) > 1e15:
            continue
        cur = _coerce_finance_currency_value(
            row.get("currency"), DEFAULT_FINANCE_CURRENCY
        )
        d = desc.strip()
        if len(d) > MAX_FINANCE_DESCRIPTION:
            d = d[:MAX_FINANCE_DESCRIPTION]
        period_raw = row.get("amountPeriod")
        period = "year" if period_raw == "year" else "month"
        rec: dict[str, Any] = {
            "id": rid.strip(),
            "category": cat,
            "description": d,
            "amount": amt_f,
            "currency": cur,
            "amountPeriod": period,
        }
        rh = row.get("relatedHouse")
        if rh in FINANCE_HOUSE_KEYS:
            rec["relatedHouse"] = rh
        if include_income_flags:
            for fk in ("isTax", "isSaving", "isInvestment"):
                rec[fk] = row.get(fk) is True
        if include_expense_flags:
            rec["isAllocate"] = row.get("isAllocate") is True
        out.append(rec)
    return out


def _sanitize_expense_income_allocation_percentages(raw: Any) -> dict[str, float]:
    """Coerce persisted expense-sheet allocation rates to 0–100 (inclusive)."""
    out = {**DEFAULT_EXPENSE_INCOME_ALLOCATION_PERCENTAGES}
    if not isinstance(raw, dict):
        return out
    for key in (
        "taxOnIncomePercent",
        "investmentOnIncomePercent",
        "savingOnIncomePercent",
    ):
        val = raw.get(key, 0)
        if isinstance(val, Decimal):
            val = float(val)
        if isinstance(val, bool):
            continue
        if isinstance(val, (int, float)):
            v = float(val)
        elif isinstance(val, str):
            try:
                v = float(val)
            except ValueError:
                continue
        else:
            continue
        if v < 0.0:
            v = 0.0
        if v > 100.0:
            v = 100.0
        out[key] = v
    return out


def _normalize_ledger_sheet_payload(
    body: dict[str, Any],
    *,
    body_key: str,
    categories: frozenset[str],
) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ValueError("Body must be a JSON object")
    raw = body.get(body_key)
    if not isinstance(raw, list):
        raise ValueError(f"{body_key} must be an array")
    if len(raw) > MAX_LEDGER_RECORDS:
        raise ValueError(f"At most {MAX_LEDGER_RECORDS} records allowed in {body_key}")
    allowed = ", ".join(sorted(categories))
    out: list[dict[str, Any]] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"{body_key}[{i}] must be an object")
        rid = row.get("id")
        if not isinstance(rid, str) or not rid.strip():
            raise ValueError(f"{body_key}[{i}].id is required")
        cat = row.get("category")
        if cat not in categories:
            raise ValueError(f"{body_key}[{i}].category must be one of: {allowed}")
        desc = row.get("description")
        if not isinstance(desc, str) or not desc.strip():
            raise ValueError(f"{body_key}[{i}].description is required")
        if len(desc) > MAX_FINANCE_DESCRIPTION:
            raise ValueError(f"{body_key}[{i}].description is too long")
        amt = row.get("amount")
        if isinstance(amt, Decimal):
            amt = float(amt)
        if not isinstance(amt, (int, float)) or isinstance(amt, bool):
            raise ValueError(f"{body_key}[{i}].amount must be a number")
        if abs(float(amt)) > 1e15:
            raise ValueError(f"{body_key}[{i}].amount out of range")
        cur = _require_supported_currency(
            row.get("currency", DEFAULT_FINANCE_CURRENCY),
            f"{body_key}[{i}].currency",
        )
        period_raw = row.get("amountPeriod", "month")
        if period_raw not in LEDGER_RECORD_AMOUNT_PERIODS:
            allowed_p = ", ".join(sorted(LEDGER_RECORD_AMOUNT_PERIODS))
            raise ValueError(
                f"{body_key}[{i}].amountPeriod must be one of: {allowed_p}"
            )
        period = str(period_raw)
        rec: dict[str, Any] = {
            "id": rid.strip(),
            "category": cat,
            "description": desc.strip(),
            "amount": float(amt),
            "currency": cur,
            "amountPeriod": period,
        }
        house_raw = row.get("relatedHouse")
        if house_raw is not None and house_raw != "":
            if not isinstance(house_raw, str) or house_raw not in FINANCE_HOUSE_KEYS:
                houses = ", ".join(sorted(FINANCE_HOUSE_KEYS))
                raise ValueError(
                    f"{body_key}[{i}].relatedHouse must be one of: {houses}"
                )
            rec["relatedHouse"] = house_raw
        if body_key == "incomeRecords":
            for fk in ("isTax", "isSaving", "isInvestment"):
                v = row.get(fk)
                if v is None:
                    rec[fk] = False
                elif isinstance(v, bool):
                    rec[fk] = v
                else:
                    raise ValueError(f"{body_key}[{i}].{fk} must be a boolean")
        if body_key == "expenseRecords":
            v = row.get("isAllocate")
            if v is None:
                rec["isAllocate"] = False
            elif isinstance(v, bool):
                rec["isAllocate"] = v
            else:
                raise ValueError(f"{body_key}[{i}].isAllocate must be a boolean")
        out.append(rec)
    return out


def _investment_non_empty_strip(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        s = str(raw).strip()
    elif isinstance(raw, str):
        s = raw.strip()
    else:
        return None
    return s if s else None


def _sanitize_investment_detail_str(raw: Any, max_len: int) -> str | None:
    s = _investment_non_empty_strip(raw)
    if s is None:
        return None
    if len(s) > max_len:
        return s[:max_len]
    return s


def _sanitize_investment_records_list(raw: Any) -> list[dict[str, Any]]:
    """Best-effort coercion for GET responses (drops invalid rows)."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        if not isinstance(rid, str) or not rid.strip():
            continue
        cat = row.get("category")
        if cat not in INVESTMENT_RECORD_CATEGORIES:
            continue
        at = row.get("assetType")
        if at not in ASSET_TYPES:
            continue
        prov = row.get("provider")
        if not isinstance(prov, str) or not prov.strip():
            continue
        p = prov.strip()
        if len(p) > MAX_INVESTMENT_PROVIDER_LEN:
            p = p[:MAX_INVESTMENT_PROVIDER_LEN]
        amt = row.get("principalAmount")
        if isinstance(amt, Decimal):
            amt_f = float(amt)
        elif isinstance(amt, (int, float)) and not isinstance(amt, bool):
            amt_f = float(amt)
        elif isinstance(amt, str):
            try:
                amt_f = float(amt)
            except ValueError:
                continue
        else:
            continue
        if amt_f != amt_f or abs(amt_f) > 1e15:
            continue
        cur = _coerce_finance_currency_value(
            row.get("currency"), DEFAULT_FINANCE_CURRENCY
        )
        item: dict[str, Any] = {
            "id": rid.strip(),
            "category": cat,
            "assetType": at,
            "provider": p,
            "principalAmount": amt_f,
            "currency": cur,
        }
        if cat == "Real Estate":
            rh = row.get("relatedHouse")
            if rh in FINANCE_HOUSE_KEYS:
                item["relatedHouse"] = rh
            cv = row.get("currentValue")
            if cv is not None and not isinstance(cv, bool):
                if isinstance(cv, Decimal):
                    cv_f = float(cv)
                elif isinstance(cv, (int, float)):
                    cv_f = float(cv)
                elif isinstance(cv, str):
                    s = cv.strip()
                    if not s:
                        cv_f = None
                    else:
                        try:
                            cv_f = float(s)
                        except ValueError:
                            cv_f = None
                else:
                    cv_f = None
                if cv_f is not None and cv_f == cv_f and abs(cv_f) <= 1e15:
                    item["currentValue"] = cv_f
        elif cat == "ETF":
            tk = _sanitize_investment_detail_str(
                row.get("ticker"), MAX_INVESTMENT_TICKER_LEN
            )
            if tk:
                item["ticker"] = tk
        elif cat == "Crypto":
            cc = _sanitize_investment_detail_str(
                row.get("cryptoCurrency"), MAX_INVESTMENT_CRYPTO_CURRENCY_LEN
            )
            if cc:
                item["cryptoCurrency"] = cc
        unit_raw = row.get("unit")
        if cat != "Real Estate" and unit_raw is not None and not isinstance(unit_raw, bool):
            if isinstance(unit_raw, Decimal):
                unit_f = float(unit_raw)
            elif isinstance(unit_raw, (int, float)):
                unit_f = float(unit_raw)
            elif isinstance(unit_raw, str):
                s = unit_raw.strip()
                if not s:
                    unit_f = None
                else:
                    try:
                        unit_f = float(s)
                    except ValueError:
                        unit_f = None
            else:
                unit_f = None
            if unit_f is not None and unit_f == unit_f and abs(unit_f) <= 1e15:
                item["unit"] = unit_f
        lu_raw = row.get("lastUpdated")
        if isinstance(lu_raw, str) and _is_calendar_date_string(lu_raw.strip()):
            item["lastUpdated"] = lu_raw.strip()
        out.append(item)
    return out


def _investment_row_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    """Comparable fields for detecting edits (excludes id and lastUpdated)."""
    u = row.get("unit")
    if isinstance(u, Decimal):
        u_f: float | None = float(u)
    elif isinstance(u, (int, float)) and not isinstance(u, bool):
        u_f = float(u)
    else:
        u_f = None
    cv = row.get("currentValue")
    if isinstance(cv, Decimal):
        cv_f: float | None = float(cv)
    elif isinstance(cv, (int, float)) and not isinstance(cv, bool):
        cv_f = float(cv)
    else:
        cv_f = None
    return (
        row["category"],
        row["assetType"],
        row["provider"],
        float(row["principalAmount"]),
        row["currency"],
        row.get("relatedHouse"),
        row.get("ticker"),
        row.get("cryptoCurrency"),
        u_f,
        cv_f,
    )


def _merge_sheet_last_updated(
    normalized: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    signature: Callable[[dict[str, Any]], Any],
    *,
    id_field: str = "id",
    today_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Stamp lastUpdated: new or changed rows get today; unchanged rows keep a valid prior date."""
    today = today_iso or datetime.now(timezone.utc).date().isoformat()
    by_id = {r[id_field]: r for r in existing}
    out: list[dict[str, Any]] = []
    for row in normalized:
        merged = dict(row)
        prev = by_id.get(merged[id_field])
        if prev is None:
            merged["lastUpdated"] = today
        elif signature(prev) == signature(merged):
            lu = prev.get("lastUpdated")
            if isinstance(lu, str) and _is_calendar_date_string(lu):
                merged["lastUpdated"] = lu
        else:
            merged["lastUpdated"] = today
        out.append(merged)
    return out


@dataclass(frozen=True)
class SheetSpec:
    """One finance sheet: slug plus the id field used when merging lastUpdated."""

    slug: str
    id_field: str = "id"


def put_finance_sheet(
    table: Any,
    slug: str,
    records: list[dict[str, Any]],
    extra: dict[str, Any] | None = None,
) -> None:
    """Write a sheet document. Callers keep their own normalize/merge wrappers."""
    doc: dict[str, Any] = {"records": records}
    if extra:
        doc.update(extra)
    table.put_item(Item={**_finance_sheet_ddb_key(slug), **_to_ddb_nested(doc)})


def _merge_investment_last_updated(
    normalized: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    *,
    today_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Attach `lastUpdated` (UTC calendar date) per row: new/changed rows get today; unchanged keep prior."""
    return _merge_sheet_last_updated(
        normalized,
        existing,
        _investment_row_signature,
        today_iso=today_iso,
    )


def _reject_investment_detail_fields(
    *,
    index: int,
    allowed: frozenset[str],
    house_raw: Any,
    ticker_raw: Any,
    crypto_raw: Any,
    current_value_raw: Any,
) -> None:
    """Reject investment fields that the category does not use.

    Hoisted out of the record loop so it does not close over loop variables.
    """
    checks: tuple[tuple[str, Any], ...] = (
        ("relatedHouse", house_raw),
        ("ticker", ticker_raw),
        ("cryptoCurrency", crypto_raw),
        ("currentValue", current_value_raw),
    )
    for field, raw in checks:
        if field in allowed:
            continue
        if field == "relatedHouse":
            if house_raw is not None and str(house_raw).strip() != "":
                raise ValueError(
                    f"investmentRecords[{index}].relatedHouse is only allowed when "
                    "category is Real Estate"
                )
        elif field == "currentValue":
            if raw is None:
                continue
            if isinstance(raw, bool) or isinstance(raw, (int, float)) or isinstance(raw, Decimal):
                raise ValueError(
                    f"investmentRecords[{index}].currentValue is only allowed when "
                    "category is Real Estate"
                )
            if isinstance(raw, str) and raw.strip() != "":
                raise ValueError(
                    f"investmentRecords[{index}].currentValue is only allowed when "
                    "category is Real Estate"
                )
        elif _investment_non_empty_strip(raw) is not None:
            raise ValueError(
                f"investmentRecords[{index}].{field} is only allowed when category "
                "uses this field"
            )


def _normalize_investment_sheet_payload(body: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ValueError("Body must be a JSON object")
    raw = body.get("investmentRecords")
    if not isinstance(raw, list):
        raise ValueError("investmentRecords must be an array")
    if len(raw) > MAX_LEDGER_RECORDS:
        raise ValueError(
            f"At most {MAX_LEDGER_RECORDS} records allowed in investmentRecords"
        )
    allowed_cat = ", ".join(sorted(INVESTMENT_RECORD_CATEGORIES))
    allowed_at = ", ".join(sorted(ASSET_TYPES))
    out: list[dict[str, Any]] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"investmentRecords[{i}] must be an object")
        rid = row.get("id")
        if not isinstance(rid, str) or not rid.strip():
            raise ValueError(f"investmentRecords[{i}].id is required")
        cat = row.get("category")
        if cat not in INVESTMENT_RECORD_CATEGORIES:
            raise ValueError(
                f"investmentRecords[{i}].category must be one of: {allowed_cat}"
            )
        at = row.get("assetType")
        if at not in ASSET_TYPES:
            raise ValueError(
                f"investmentRecords[{i}].assetType must be one of: {allowed_at}"
            )
        prov = row.get("provider")
        if not isinstance(prov, str) or not prov.strip():
            raise ValueError(f"investmentRecords[{i}].provider is required")
        if len(prov.strip()) > MAX_INVESTMENT_PROVIDER_LEN:
            raise ValueError(f"investmentRecords[{i}].provider is too long")
        amt = row.get("principalAmount")
        if isinstance(amt, Decimal):
            amt = float(amt)
        if not isinstance(amt, (int, float)) or isinstance(amt, bool):
            raise ValueError(
                f"investmentRecords[{i}].principalAmount must be a number"
            )
        amt_f = float(amt)
        if amt_f != amt_f or abs(amt_f) > 1e15:
            raise ValueError(
                f"investmentRecords[{i}].principalAmount out of range"
            )
        cur = _require_supported_currency(
            row.get("currency", DEFAULT_FINANCE_CURRENCY),
            f"investmentRecords[{i}].currency",
        )
        rec: dict[str, Any] = {
            "id": rid.strip(),
            "category": cat,
            "assetType": at,
            "provider": prov.strip(),
            "principalAmount": amt_f,
            "currency": cur,
        }
        house_raw = row.get("relatedHouse")
        ticker_raw = row.get("ticker")
        crypto_raw = row.get("cryptoCurrency")
        current_value_raw = row.get("currentValue")

        if cat == "Real Estate":
            _reject_investment_detail_fields(
                index=i,
                allowed=frozenset({"relatedHouse", "currentValue"}),
                house_raw=house_raw,
                ticker_raw=ticker_raw,
                crypto_raw=crypto_raw,
                current_value_raw=current_value_raw,
            )
            if house_raw is not None and str(house_raw).strip() != "":
                if not isinstance(house_raw, str) or house_raw not in FINANCE_HOUSE_KEYS:
                    houses = ", ".join(sorted(FINANCE_HOUSE_KEYS))
                    raise ValueError(
                        f"investmentRecords[{i}].relatedHouse must be one of: {houses}"
                    )
                rec["relatedHouse"] = house_raw
            cv_raw = row.get("currentValue")
            if cv_raw is not None and not (
                isinstance(cv_raw, str) and not cv_raw.strip()
            ):
                if isinstance(cv_raw, bool):
                    raise ValueError(
                        f"investmentRecords[{i}].currentValue must be a number"
                    )
                if isinstance(cv_raw, Decimal):
                    cv_f = float(cv_raw)
                elif isinstance(cv_raw, (int, float)):
                    cv_f = float(cv_raw)
                elif isinstance(cv_raw, str):
                    try:
                        cv_f = float(cv_raw.strip())
                    except ValueError as exc:
                        raise ValueError(
                            f"investmentRecords[{i}].currentValue must be a number"
                        ) from exc
                else:
                    raise ValueError(
                        f"investmentRecords[{i}].currentValue must be a number"
                    )
                if cv_f != cv_f or abs(cv_f) > 1e15:
                    raise ValueError(
                        f"investmentRecords[{i}].currentValue out of range"
                    )
                rec["currentValue"] = cv_f
        elif cat == "ETF":
            _reject_investment_detail_fields(
                index=i,
                allowed=frozenset({"ticker"}),
                house_raw=house_raw,
                ticker_raw=ticker_raw,
                crypto_raw=crypto_raw,
                current_value_raw=current_value_raw,
            )
            if ticker_raw is not None and str(ticker_raw).strip() != "":
                if not isinstance(ticker_raw, str):
                    raise ValueError(
                        f"investmentRecords[{i}].ticker must be a string"
                    )
                t_st = ticker_raw.strip()
                if len(t_st) > MAX_INVESTMENT_TICKER_LEN:
                    raise ValueError(f"investmentRecords[{i}].ticker is too long")
                rec["ticker"] = t_st
        elif cat == "Crypto":
            _reject_investment_detail_fields(
                index=i,
                allowed=frozenset({"cryptoCurrency"}),
                house_raw=house_raw,
                ticker_raw=ticker_raw,
                crypto_raw=crypto_raw,
                current_value_raw=current_value_raw,
            )
            if crypto_raw is not None and str(crypto_raw).strip() != "":
                if not isinstance(crypto_raw, str):
                    raise ValueError(
                        f"investmentRecords[{i}].cryptoCurrency must be a string"
                    )
                c_st = crypto_raw.strip()
                if len(c_st) > MAX_INVESTMENT_CRYPTO_CURRENCY_LEN:
                    raise ValueError(
                        f"investmentRecords[{i}].cryptoCurrency is too long"
                    )
                rec["cryptoCurrency"] = c_st
        elif cat == "Fixed Term Deposit":
            _reject_investment_detail_fields(
                index=i,
                allowed=frozenset(),
                house_raw=house_raw,
                ticker_raw=ticker_raw,
                crypto_raw=crypto_raw,
                current_value_raw=current_value_raw,
            )
        if cat != "Real Estate":
            unit_raw = row.get("unit")
            if unit_raw is not None and not (
                isinstance(unit_raw, str) and not unit_raw.strip()
            ):
                if isinstance(unit_raw, bool):
                    raise ValueError(f"investmentRecords[{i}].unit must be a number")
                if isinstance(unit_raw, Decimal):
                    uf = float(unit_raw)
                elif isinstance(unit_raw, (int, float)):
                    uf = float(unit_raw)
                elif isinstance(unit_raw, str):
                    try:
                        uf = float(unit_raw.strip())
                    except ValueError as exc:
                        raise ValueError(
                            f"investmentRecords[{i}].unit must be a number"
                        ) from exc
                else:
                    raise ValueError(f"investmentRecords[{i}].unit must be a number")
                if uf != uf or abs(uf) > 1e15:
                    raise ValueError(f"investmentRecords[{i}].unit out of range")
                rec["unit"] = uf
        out.append(rec)
    return out


def _load_investment_records(table: Any) -> list[dict[str, Any]]:
    res = table.get_item(Key=_finance_sheet_ddb_key("investments"))
    item = res.get("Item")
    if not item:
        return []
    payload = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    nested = _from_ddb_nested(payload)
    if not isinstance(nested, dict):
        return []
    return _sanitize_investment_records_list(nested.get("records"))


def _sanitize_savings_records_list(raw: Any) -> list[dict[str, Any]]:
    """Best-effort coercion for GET responses (drops invalid rows)."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        if not isinstance(rid, str) or not rid.strip():
            continue
        dep = row.get("deposit")
        if not isinstance(dep, str) or not dep.strip():
            continue
        d = dep.strip()
        if len(d) > MAX_INVESTMENT_PROVIDER_LEN:
            d = d[:MAX_INVESTMENT_PROVIDER_LEN]
        amt = row.get("value")
        if isinstance(amt, Decimal):
            amt_f = float(amt)
        elif isinstance(amt, (int, float)) and not isinstance(amt, bool):
            amt_f = float(amt)
        elif isinstance(amt, str):
            try:
                amt_f = float(amt)
            except ValueError:
                continue
        else:
            continue
        if amt_f != amt_f or abs(amt_f) > 1e15:
            continue
        cur = _coerce_finance_currency_value(
            row.get("currency"), DEFAULT_FINANCE_CURRENCY
        )
        desc_raw = row.get("description")
        desc = ""
        if isinstance(desc_raw, str):
            desc = desc_raw.strip()
            if len(desc) > MAX_FINANCE_DESCRIPTION:
                desc = desc[:MAX_FINANCE_DESCRIPTION]
        at_raw = row.get("assetType")
        if at_raw in ASSET_TYPES:
            at = str(at_raw)
        else:
            at = "Fixed"
        out.append(
            {
                "id": rid.strip(),
                "deposit": d,
                "assetType": at,
                "description": desc,
                "value": amt_f,
                "currency": cur,
            }
        )
    return out


def _is_calendar_date_string(s: str) -> bool:
    """True if `s` is a valid ISO calendar date `YYYY-MM-DD`."""
    if not isinstance(s, str) or len(s) != 10:
        return False
    try:
        date.fromisoformat(s)
    except ValueError:
        return False
    return True


def _pension_row_signature(row: dict[str, Any]) -> tuple[str, str, float, str]:
    return (
        row["fund"],
        row["description"],
        float(row["value"]),
        row["currency"],
    )


def _merge_pension_last_updated(
    normalized: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    *,
    today_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Attach `lastUpdated` (UTC calendar date) per row: new/changed rows get today; unchanged keep prior."""
    return _merge_sheet_last_updated(
        normalized,
        existing,
        _pension_row_signature,
        today_iso=today_iso,
    )


def _account_row_signature(row: dict[str, Any]) -> tuple[str, str, int, float, str, float | None]:
    at = str(row["accountType"])
    last_stmt: float | None
    if at == "Credit Card":
        raw = row.get("lastStatementAmount", 0.0)
        if isinstance(raw, Decimal):
            last_stmt = float(raw)
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
            last_stmt = float(raw)
        elif isinstance(raw, str):
            try:
                last_stmt = float(raw)
            except ValueError:
                last_stmt = 0.0
        else:
            last_stmt = 0.0
        if last_stmt != last_stmt or abs(last_stmt) > 1e15:
            last_stmt = 0.0
    else:
        last_stmt = None
    return (
        str(row.get("description", "")),
        at,
        int(row["billingCycleDay"]),
        float(row["recordedValue"]),
        str(row["currency"]),
        last_stmt,
    )


def _merge_accounts_last_updated(
    normalized: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    *,
    today_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Attach `lastUpdated` (UTC calendar date) when account fields change."""
    return _merge_sheet_last_updated(
        normalized,
        existing,
        _account_row_signature,
        today_iso=today_iso,
    )


def _parse_account_billing_cycle_day(raw: Any, field_label: str) -> int:
    if isinstance(raw, bool):
        raise ValueError(f"{field_label} must be an integer from 1 to 31")
    if isinstance(raw, int):
        d = raw
    elif isinstance(raw, Decimal):
        as_int = int(raw)
        if Decimal(as_int) != raw:
            raise ValueError(f"{field_label} must be an integer from 1 to 31")
        d = as_int
    elif isinstance(raw, float):
        if not raw.is_integer():
            raise ValueError(f"{field_label} must be an integer from 1 to 31")
        d = int(raw)
    elif isinstance(raw, str):
        t = raw.strip()
        if not t:
            raise ValueError(f"{field_label} is required")
        try:
            d = int(t, 10)
        except ValueError as exc:
            raise ValueError(f"{field_label} must be an integer from 1 to 31") from exc
    else:
        raise ValueError(f"{field_label} must be an integer from 1 to 31")
    if d < 1 or d > 31:
        raise ValueError(f"{field_label} must be between 1 and 31")
    return d


def _ledger_row_monthly_amount(row: dict[str, Any]) -> float:
    amt = float(row["amount"])
    return amt / 12.0 if row.get("amountPeriod") == "year" else amt


_FINANCE_LEDGER_RELATED_HOUSE_LABELS: dict[str, str] = {
    "hillmarton": "32 Hillmarton",
    "morrison": "The Morrison",
}

_DERIVED_TAGGED_INCOME_SPECS: tuple[dict[str, str], ...] = (
    {
        "id_segment": "tax-on-income",
        "category": "Tax",
        "title": "Tax on Income",
        "income_flag": "isTax",
        "percent_key": "taxOnIncomePercent",
    },
    {
        "id_segment": "investment-on-income",
        "category": "Investment",
        "title": "Investments on Income",
        "income_flag": "isInvestment",
        "percent_key": "investmentOnIncomePercent",
    },
    {
        "id_segment": "saving-on-income",
        "category": "Saving",
        "title": "Savings on Income",
        "income_flag": "isSaving",
        "percent_key": "savingOnIncomePercent",
    },
)


def _sum_monthly_tagged_income_by_house_currency(
    income_rows: list[dict[str, Any]],
    house_key: str,
    income_flag: str,
) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in income_rows:
        if r.get("amountPeriod") != "month" or r.get("relatedHouse") != house_key:
            continue
        if not r.get(income_flag):
            continue
        cur = str(r.get("currency") or DEFAULT_FINANCE_CURRENCY)
        amt = r.get("amount")
        if isinstance(amt, Decimal):
            amt_f = float(amt)
        elif isinstance(amt, (int, float)) and not isinstance(amt, bool):
            amt_f = float(amt)
        else:
            continue
        if amt_f != amt_f or abs(amt_f) > 1e15:
            continue
        out[cur] = out.get(cur, 0.0) + amt_f
    return out


def _sum_monthly_tagged_income_without_related_house_by_currency(
    income_rows: list[dict[str, Any]],
    income_flag: str,
) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in income_rows:
        if r.get("amountPeriod") != "month" or not r.get(income_flag):
            continue
        rh = r.get("relatedHouse")
        if rh in FINANCE_HOUSE_KEYS:
            continue
        cur = str(r.get("currency") or DEFAULT_FINANCE_CURRENCY)
        amt = r.get("amount")
        if isinstance(amt, Decimal):
            amt_f = float(amt)
        elif isinstance(amt, (int, float)) and not isinstance(amt, bool):
            amt_f = float(amt)
        else:
            continue
        if amt_f != amt_f or abs(amt_f) > 1e15:
            continue
        out[cur] = out.get(cur, 0.0) + amt_f
    return out


def _derived_expense_rows_from_tagged_income(
    income_rows: list[dict[str, Any]],
    percents: dict[str, float],
) -> list[dict[str, Any]]:
    """Synthetic expense rows from allocation % × tagged monthly income (matches admin web)."""
    out: list[dict[str, Any]] = []
    houses_order = ("hillmarton", "morrison")
    for house_key in houses_order:
        house_label = _FINANCE_LEDGER_RELATED_HOUSE_LABELS.get(house_key, house_key)
        for spec in _DERIVED_TAGGED_INCOME_SPECS:
            pct = float(percents.get(spec["percent_key"], 0.0))
            if pct <= 0:
                continue
            by_ccy = _sum_monthly_tagged_income_by_house_currency(
                income_rows, house_key, spec["income_flag"]
            )
            for currency, base in by_ccy.items():
                if base <= 0:
                    continue
                amount = base * (pct / 100.0)
                if amount != amount or abs(amount) > 1e15 or amount == 0:
                    continue
                rid = f"__derived__{spec['id_segment']}__{house_key}__{currency}"
                out.append(
                    {
                        "id": rid,
                        "category": spec["category"],
                        "description": f"{spec['title']} ({house_label})",
                        "amount": amount,
                        "currency": currency,
                        "amountPeriod": "month",
                        "relatedHouse": house_key,
                    }
                )
    for spec in _DERIVED_TAGGED_INCOME_SPECS:
        pct = float(percents.get(spec["percent_key"], 0.0))
        if pct <= 0:
            continue
        by_ccy = _sum_monthly_tagged_income_without_related_house_by_currency(
            income_rows, spec["income_flag"]
        )
        for currency, base in by_ccy.items():
            if base <= 0:
                continue
            amount = base * (pct / 100.0)
            if amount != amount or abs(amount) > 1e15 or amount == 0:
                continue
            rid = f"__derived__{spec['id_segment']}__unallocated__{currency}"
            out.append(
                {
                    "id": rid,
                    "category": spec["category"],
                    "description": f"{spec['title']} (no related property)",
                    "amount": amount,
                    "currency": currency,
                    "amountPeriod": "month",
                }
            )
    return out


def _allocated_expense_ids_for_allocations(table: Any) -> frozenset[str]:
    """Real expense rows tagged Allocate plus synthetic derived allocation lines."""
    exp_rows, perc = _load_finance_expenses_ledger_with_allocation(table)
    inc = _load_finance_sheet(table, "income", INCOME_RECORD_CATEGORIES)
    derived = _derived_expense_rows_from_tagged_income(inc, perc)
    ids: set[str] = {
        str(r["id"]) for r in exp_rows if isinstance(r, dict) and r.get("isAllocate")
    }
    ids |= {str(r["id"]) for r in derived}
    return frozenset(ids)


_CUSTOM_ALLOCATION_EXPENSE_ID_PREFIX = "__custom__"


def _is_custom_allocation_expense_id(eid: str) -> bool:
    if not isinstance(eid, str) or not eid.strip():
        return False
    s = eid.strip()
    if not s.startswith(_CUSTOM_ALLOCATION_EXPENSE_ID_PREFIX):
        return False
    rest = s[len(_CUSTOM_ALLOCATION_EXPENSE_ID_PREFIX) :].strip()
    if len(rest) < 32:
        return False
    try:
        uuid.UUID(rest)
    except ValueError:
        return False
    return True


def _sanitize_allocation_stored_list(raw: Any) -> list[dict[str, Any]]:
    """Coerce persisted allocation rows (linked expense/derived or custom)."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        eid_raw = row.get("expenseId")
        if not isinstance(eid_raw, str) or not eid_raw.strip():
            continue
        eid = eid_raw.strip()
        amt = row.get("accumulatedAmount")
        if isinstance(amt, Decimal):
            amt_f = float(amt)
        elif isinstance(amt, (int, float)) and not isinstance(amt, bool):
            amt_f = float(amt)
        elif isinstance(amt, str):
            try:
                amt_f = float(amt)
            except ValueError:
                continue
        else:
            continue
        if abs(amt_f) > 1e15:
            continue
        lu = row.get("lastUpdated")
        last_u: str | None = lu if isinstance(lu, str) and _is_calendar_date_string(lu) else None
        if _is_custom_allocation_expense_id(eid):
            desc_raw = row.get("description")
            if not isinstance(desc_raw, str) or not desc_raw.strip():
                continue
            d = desc_raw.strip()
            if len(d) > MAX_FINANCE_DESCRIPTION:
                d = d[:MAX_FINANCE_DESCRIPTION]
            cur = _coerce_finance_currency_value(
                row.get("currency"), DEFAULT_FINANCE_CURRENCY
            )
            rec: dict[str, Any] = {
                "expenseId": eid,
                "description": d,
                "currency": cur,
                "accumulatedAmount": amt_f,
            }
            if row.get("isIncome") is True:
                rec["isIncome"] = True
                aim = row.get("allocationIncomeMonthly")
                aim_f: float | None = None
                if isinstance(aim, Decimal):
                    aim_f = float(aim)
                elif isinstance(aim, (int, float)) and not isinstance(aim, bool):
                    aim_f = float(aim)
                elif isinstance(aim, str):
                    try:
                        aim_f = float(aim)
                    except ValueError:
                        aim_f = None
                if aim_f is not None and aim_f == aim_f and abs(aim_f) <= 1e15:
                    rec["allocationIncomeMonthly"] = aim_f
            if row.get("isPension") is True:
                rec["isPension"] = True
            if last_u is not None:
                rec["lastUpdated"] = last_u
            out.append(rec)
        else:
            rec = {"expenseId": eid, "accumulatedAmount": amt_f}
            if row.get("isIncome") is True:
                rec["isIncome"] = True
            if row.get("isPension") is True:
                rec["isPension"] = True
            if last_u is not None:
                rec["lastUpdated"] = last_u
            out.append(rec)
    return out


def _load_allocation_stored_records(table: Any) -> list[dict[str, Any]]:
    res = table.get_item(Key=_finance_sheet_ddb_key("allocations"))
    item = res.get("Item")
    if not item:
        return []
    payload = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    nested = _from_ddb_nested(payload)
    if not isinstance(nested, dict):
        return []
    return _sanitize_allocation_stored_list(nested.get("records"))


def _custom_allocation_row_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    desc = row.get("description")
    d = desc.strip() if isinstance(desc, str) else ""
    cur = str(row.get("currency") or DEFAULT_FINANCE_CURRENCY)
    inc = row.get("isIncome") is True
    aim: float | None = None
    if inc:
        raw = row.get("allocationIncomeMonthly")
        if isinstance(raw, Decimal):
            aim = float(raw)
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
            aim = float(raw)
        elif isinstance(raw, str):
            try:
                aim = float(raw)
            except ValueError:
                aim = None
    return (d, cur, float(row.get("accumulatedAmount", 0.0)), inc, aim, row.get("isPension") is True)


def _merge_allocation_stored_last_updated(
    normalized: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    *,
    today_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Persisted shape: linked rows have expenseId + accumulatedAmount; custom rows add description + currency."""
    today = today_iso or datetime.now(timezone.utc).date().isoformat()
    by_id = {r["expenseId"]: r for r in existing}
    out: list[dict[str, Any]] = []
    for row in normalized:
        eid = row["expenseId"]
        amt = float(row["accumulatedAmount"])
        if _is_custom_allocation_expense_id(eid):
            desc = str(row.get("description", "")).strip()
            cur = _coerce_finance_currency_value(
                row.get("currency"), DEFAULT_FINANCE_CURRENCY
            )
            merged: dict[str, Any] = {
                "expenseId": eid,
                "description": desc,
                "currency": cur,
                "accumulatedAmount": amt,
            }
            if row.get("isIncome") is True:
                merged["isIncome"] = True
                aim_raw = row.get("allocationIncomeMonthly")
                if isinstance(aim_raw, Decimal):
                    merged["allocationIncomeMonthly"] = float(aim_raw)
                elif isinstance(aim_raw, (int, float)) and not isinstance(aim_raw, bool):
                    merged["allocationIncomeMonthly"] = float(aim_raw)
                elif isinstance(aim_raw, str):
                    try:
                        merged["allocationIncomeMonthly"] = float(aim_raw)
                    except ValueError:
                        pass
            if row.get("isPension") is True:
                merged["isPension"] = True
            prev = by_id.get(eid)
            if prev is None:
                merged["lastUpdated"] = today
            elif _custom_allocation_row_signature(prev) == _custom_allocation_row_signature(
                merged
            ):
                lu = prev.get("lastUpdated")
                if isinstance(lu, str) and _is_calendar_date_string(lu):
                    merged["lastUpdated"] = lu
            else:
                merged["lastUpdated"] = today
            out.append(merged)
        else:
            merged = {"expenseId": eid, "accumulatedAmount": amt}
            if row.get("isIncome") is True:
                merged["isIncome"] = True
            if row.get("isPension") is True:
                merged["isPension"] = True
            prev = by_id.get(eid)
            prev_inc = prev.get("isIncome") is True if prev else False
            new_inc = merged.get("isIncome") is True
            prev_pen = prev.get("isPension") is True if prev else False
            new_pen = merged.get("isPension") is True
            if prev is None:
                if amt != 0.0 or new_inc or new_pen:
                    merged["lastUpdated"] = today
            else:
                prev_amt = float(prev.get("accumulatedAmount", 0.0))
                amt_same = abs(prev_amt - amt) < 1e-9
                inc_same = prev_inc == new_inc
                pen_same = prev_pen == new_pen
                if amt_same and inc_same and pen_same:
                    lu = prev.get("lastUpdated")
                    if isinstance(lu, str) and _is_calendar_date_string(lu):
                        merged["lastUpdated"] = lu
                else:
                    merged["lastUpdated"] = today
            out.append(merged)
    return out


def _normalize_allocations_sheet_payload(
    body: dict[str, Any],
    allocated_expense_ids: frozenset[str],
) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ValueError("Body must be a JSON object")
    raw = body.get("allocationRecords")
    if not isinstance(raw, list):
        raise ValueError("allocationRecords must be an array")
    if len(raw) > MAX_LEDGER_RECORDS:
        raise ValueError(
            f"At most {MAX_LEDGER_RECORDS} records allowed in allocationRecords"
        )
    seen: set[str] = set()
    linked_out: list[dict[str, Any]] = []
    custom_out: list[dict[str, Any]] = []
    linked_seen: set[str] = set()
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"allocationRecords[{i}] must be an object")
        eid_raw = row.get("expenseId")
        if not isinstance(eid_raw, str) or not eid_raw.strip():
            raise ValueError(f"allocationRecords[{i}].expenseId is required")
        eid = eid_raw.strip()
        if eid in seen:
            raise ValueError(f"allocationRecords[{i}].expenseId is duplicated")
        seen.add(eid)
        amt_raw = row.get("accumulatedAmount")
        if isinstance(amt_raw, Decimal):
            amt_f = float(amt_raw)
        elif isinstance(amt_raw, (int, float)) and not isinstance(amt_raw, bool):
            amt_f = float(amt_raw)
        elif isinstance(amt_raw, str):
            try:
                amt_f = float(amt_raw)
            except ValueError as exc:
                raise ValueError(
                    f"allocationRecords[{i}].accumulatedAmount must be a number"
                ) from exc
        else:
            raise ValueError(
                f"allocationRecords[{i}].accumulatedAmount must be a number"
            )
        if abs(amt_f) > 1e15:
            raise ValueError(
                f"allocationRecords[{i}].accumulatedAmount out of range"
            )
        if _is_custom_allocation_expense_id(eid):
            desc = row.get("description")
            if not isinstance(desc, str) or not desc.strip():
                raise ValueError(
                    f"allocationRecords[{i}].description is required for custom allocations"
                )
            d = desc.strip()
            if len(d) > MAX_FINANCE_DESCRIPTION:
                raise ValueError(
                    f"allocationRecords[{i}].description is too long"
                )
            cur = _require_supported_currency(
                row.get("currency", DEFAULT_FINANCE_CURRENCY),
                f"allocationRecords[{i}].currency",
            )
            is_inc = row.get("isIncome") is True
            rec_c: dict[str, Any] = {
                "expenseId": eid,
                "description": d,
                "currency": cur,
                "accumulatedAmount": amt_f,
            }
            if is_inc:
                aim_raw = row.get("allocationIncomeMonthly")
                if isinstance(aim_raw, Decimal):
                    aim_f = float(aim_raw)
                elif isinstance(aim_raw, (int, float)) and not isinstance(aim_raw, bool):
                    aim_f = float(aim_raw)
                elif isinstance(aim_raw, str):
                    try:
                        aim_f = float(aim_raw)
                    except ValueError as exc:
                        raise ValueError(
                            f"allocationRecords[{i}].allocationIncomeMonthly must be a number"
                        ) from exc
                else:
                    raise ValueError(
                        f"allocationRecords[{i}].allocationIncomeMonthly is required when isIncome is true"
                    )
                if aim_f != aim_f or abs(aim_f) > 1e15:
                    raise ValueError(
                        f"allocationRecords[{i}].allocationIncomeMonthly out of range"
                    )
                if aim_f <= 0:
                    raise ValueError(
                        f"allocationRecords[{i}].allocationIncomeMonthly must be positive when isIncome is true"
                    )
                rec_c["isIncome"] = True
                rec_c["allocationIncomeMonthly"] = aim_f
            if row.get("isPension") is True:
                rec_c["isPension"] = True
            custom_out.append(rec_c)
        else:
            if eid not in allocated_expense_ids:
                raise ValueError(
                    f"allocationRecords[{i}].expenseId is not an allocated or derived allocation line"
                )
            linked_seen.add(eid)
            rec_l: dict[str, Any] = {"expenseId": eid, "accumulatedAmount": amt_f}
            if row.get("isIncome") is True:
                rec_l["isIncome"] = True
            if row.get("isPension") is True:
                rec_l["isPension"] = True
            linked_out.append(rec_l)
    if linked_seen != allocated_expense_ids:
        missing = allocated_expense_ids - linked_seen
        extra = linked_seen - allocated_expense_ids
        parts: list[str] = []
        if missing:
            parts.append(f"missing expenseIds: {', '.join(sorted(missing))}")
        if extra:
            parts.append(f"unexpected expenseIds: {', '.join(sorted(extra))}")
        raise ValueError(
            "allocationRecords must include exactly one entry per allocated expense "
            "and derived allocation line"
            + (f" ({'; '.join(parts)})" if parts else "")
        )
    return linked_out + custom_out


def _build_allocation_records_for_response(
    expense_rows: list[dict[str, Any]],
    stored: list[dict[str, Any]],
    income_rows: list[dict[str, Any]],
    expense_allocation_percents: dict[str, float],
) -> list[dict[str, Any]]:
    """Merge tagged expenses, derived lines, and custom allocation rows."""
    by_stored = {r["expenseId"]: r for r in stored}
    out: list[dict[str, Any]] = []

    def append_linked_allocation_row(er: dict[str, Any]) -> None:
        eid = str(er["id"])
        st = by_stored.get(eid, {})
        acc = float(st.get("accumulatedAmount", 0.0))
        lu = st.get("lastUpdated")
        last_u: str | None = lu if isinstance(lu, str) and _is_calendar_date_string(lu) else None
        row_out: dict[str, Any] = {
            "expenseId": eid,
            "description": er["description"],
            "monthlyAmount": _ledger_row_monthly_amount(er),
            "accumulatedAmount": acc,
            "currency": er["currency"],
            "isCustomAllocation": False,
        }
        rh = er.get("relatedHouse")
        if rh in FINANCE_HOUSE_KEYS:
            row_out["relatedHouse"] = rh
        if st.get("isIncome") is True:
            row_out["isIncome"] = True
        if st.get("isPension") is True:
            row_out["isPension"] = True
        if last_u is not None:
            row_out["lastUpdated"] = last_u
        out.append(row_out)

    for er in expense_rows:
        if not er.get("isAllocate"):
            continue
        append_linked_allocation_row(er)
    derived = _derived_expense_rows_from_tagged_income(
        income_rows, expense_allocation_percents
    )
    for er in derived:
        append_linked_allocation_row(er)
    for st in stored:
        eid = str(st.get("expenseId", ""))
        if not _is_custom_allocation_expense_id(eid):
            continue
        desc = st.get("description")
        if not isinstance(desc, str) or not desc.strip():
            continue
        cur = _coerce_finance_currency_value(
            st.get("currency"), DEFAULT_FINANCE_CURRENCY
        )
        acc = float(st.get("accumulatedAmount", 0.0))
        lu = st.get("lastUpdated")
        last_u: str | None = lu if isinstance(lu, str) and _is_calendar_date_string(lu) else None
        is_inc = st.get("isIncome") is True
        aim = 0.0
        if is_inc:
            raw_aim = st.get("allocationIncomeMonthly")
            if isinstance(raw_aim, Decimal):
                aim = float(raw_aim)
            elif isinstance(raw_aim, (int, float)) and not isinstance(raw_aim, bool):
                aim = float(raw_aim)
            elif isinstance(raw_aim, str):
                try:
                    aim = float(raw_aim)
                except ValueError:
                    aim = 0.0
            else:
                aim = 0.0
        row_out: dict[str, Any] = {
            "expenseId": eid,
            "description": desc.strip(),
            "monthlyAmount": 0.0,
            "accumulatedAmount": acc,
            "currency": cur,
            "isCustomAllocation": True,
        }
        if is_inc:
            row_out["isIncome"] = True
            row_out["allocationIncomeMonthly"] = aim
        if st.get("isPension") is True:
            row_out["isPension"] = True
        if last_u is not None:
            row_out["lastUpdated"] = last_u
        out.append(row_out)
    out.sort(key=lambda r: (str(r["description"]).lower(), str(r["expenseId"])))
    return out


def _sanitize_pension_records_list(raw: Any) -> list[dict[str, Any]]:
    """Best-effort coercion for GET responses (drops invalid rows)."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        if not isinstance(rid, str) or not rid.strip():
            continue
        fund = row.get("fund")
        if not isinstance(fund, str) or not fund.strip():
            continue
        f = fund.strip()
        if len(f) > MAX_INVESTMENT_PROVIDER_LEN:
            f = f[:MAX_INVESTMENT_PROVIDER_LEN]
        amt = row.get("value")
        if isinstance(amt, Decimal):
            amt_f = float(amt)
        elif isinstance(amt, (int, float)) and not isinstance(amt, bool):
            amt_f = float(amt)
        elif isinstance(amt, str):
            try:
                amt_f = float(amt)
            except ValueError:
                continue
        else:
            continue
        if amt_f != amt_f or abs(amt_f) > 1e15:
            continue
        cur = _coerce_finance_currency_value(
            row.get("currency"), DEFAULT_FINANCE_CURRENCY
        )
        desc_raw = row.get("description")
        d = ""
        if isinstance(desc_raw, str):
            d = desc_raw.strip()
            if len(d) > MAX_FINANCE_DESCRIPTION:
                d = d[:MAX_FINANCE_DESCRIPTION]
        entry: dict[str, Any] = {
            "id": rid.strip(),
            "fund": f,
            "description": d,
            "value": amt_f,
            "currency": cur,
        }
        lu_raw = row.get("lastUpdated")
        if isinstance(lu_raw, str) and _is_calendar_date_string(lu_raw.strip()):
            entry["lastUpdated"] = lu_raw.strip()
        out.append(entry)
    return out


def _sanitize_accounts_records_list(raw: Any) -> list[dict[str, Any]]:
    """Best-effort coercion for GET responses (drops invalid rows)."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        if not isinstance(rid, str) or not rid.strip():
            continue
        at_raw = row.get("accountType")
        if not isinstance(at_raw, str) or at_raw.strip() not in FINANCE_ACCOUNT_TYPES:
            continue
        account_type = at_raw.strip()
        try:
            bd = _parse_account_billing_cycle_day(row.get("billingCycleDay"), "billingCycleDay")
        except ValueError:
            continue
        amt = row.get("recordedValue")
        if isinstance(amt, Decimal):
            amt_f = float(amt)
        elif isinstance(amt, (int, float)) and not isinstance(amt, bool):
            amt_f = float(amt)
        elif isinstance(amt, str):
            try:
                amt_f = float(amt)
            except ValueError:
                continue
        else:
            continue
        if amt_f != amt_f or abs(amt_f) > 1e15:
            continue
        cur = _coerce_finance_currency_value(
            row.get("currency"), DEFAULT_FINANCE_CURRENCY
        )
        desc_raw = row.get("description", "")
        if desc_raw is None:
            desc_raw = ""
        if not isinstance(desc_raw, str):
            continue
        d = desc_raw.strip()
        if len(d) > MAX_FINANCE_DESCRIPTION:
            d = d[:MAX_FINANCE_DESCRIPTION]
        entry: dict[str, Any] = {
            "id": rid.strip(),
            "description": d,
            "accountType": account_type,
            "billingCycleDay": bd,
            "recordedValue": amt_f,
            "currency": cur,
        }
        if account_type == "Credit Card":
            lsa_raw = row.get("lastStatementAmount", 0.0)
            if isinstance(lsa_raw, Decimal):
                lsa_f = float(lsa_raw)
            elif isinstance(lsa_raw, (int, float)) and not isinstance(lsa_raw, bool):
                lsa_f = float(lsa_raw)
            elif isinstance(lsa_raw, str):
                try:
                    lsa_f = float(lsa_raw)
                except ValueError:
                    lsa_f = 0.0
            else:
                lsa_f = 0.0
            if lsa_f != lsa_f or abs(lsa_f) > 1e15:
                lsa_f = 0.0
            entry["lastStatementAmount"] = lsa_f
        lu_raw = row.get("lastUpdated")
        if isinstance(lu_raw, str) and _is_calendar_date_string(lu_raw.strip()):
            entry["lastUpdated"] = lu_raw.strip()
        out.append(entry)
    return out


def _normalize_accounts_sheet_payload(body: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ValueError("Body must be a JSON object")
    raw = body.get("accountRecords")
    if not isinstance(raw, list):
        raise ValueError("accountRecords must be an array")
    if len(raw) > MAX_LEDGER_RECORDS:
        raise ValueError(
            f"At most {MAX_LEDGER_RECORDS} records allowed in accountRecords"
        )
    allowed_at = ", ".join(sorted(FINANCE_ACCOUNT_TYPES))
    out: list[dict[str, Any]] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"accountRecords[{i}] must be an object")
        rid = row.get("id")
        if not isinstance(rid, str) or not rid.strip():
            raise ValueError(f"accountRecords[{i}].id is required")
        at_raw = row.get("accountType")
        if not isinstance(at_raw, str) or not at_raw.strip():
            raise ValueError(f"accountRecords[{i}].accountType is required")
        at_st = at_raw.strip()
        if at_st not in FINANCE_ACCOUNT_TYPES:
            raise ValueError(
                f"accountRecords[{i}].accountType must be one of: {allowed_at}"
            )
        bd = _parse_account_billing_cycle_day(
            row.get("billingCycleDay"), f"accountRecords[{i}].billingCycleDay"
        )
        amt = row.get("recordedValue")
        if isinstance(amt, Decimal):
            amt = float(amt)
        if not isinstance(amt, (int, float)) or isinstance(amt, bool):
            raise ValueError(f"accountRecords[{i}].recordedValue must be a number")
        amt_f = float(amt)
        if amt_f != amt_f or abs(amt_f) > 1e15:
            raise ValueError(f"accountRecords[{i}].recordedValue out of range")
        cur = _require_supported_currency(
            row.get("currency", DEFAULT_FINANCE_CURRENCY),
            f"accountRecords[{i}].currency",
        )
        desc_raw = row.get("description", "")
        if desc_raw is None:
            desc_raw = ""
        if not isinstance(desc_raw, str):
            raise ValueError(f"accountRecords[{i}].description must be a string")
        d = desc_raw.strip()
        if len(d) > MAX_FINANCE_DESCRIPTION:
            raise ValueError(f"accountRecords[{i}].description is too long")
        rec_out: dict[str, Any] = {
            "id": rid.strip(),
            "description": d,
            "accountType": at_st,
            "billingCycleDay": bd,
            "recordedValue": amt_f,
            "currency": cur,
        }
        if at_st == "Credit Card":
            lsa_raw = row.get("lastStatementAmount", 0.0)
            if isinstance(lsa_raw, Decimal):
                lsa_raw = float(lsa_raw)
            if not isinstance(lsa_raw, (int, float)) or isinstance(lsa_raw, bool):
                raise ValueError(
                    f"accountRecords[{i}].lastStatementAmount must be a number"
                )
            lsa_f = float(lsa_raw)
            if lsa_f != lsa_f or abs(lsa_f) > 1e15:
                raise ValueError(
                    f"accountRecords[{i}].lastStatementAmount out of range"
                )
            rec_out["lastStatementAmount"] = lsa_f
        out.append(rec_out)
    return out


def _normalize_savings_sheet_payload(body: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ValueError("Body must be a JSON object")
    raw = body.get("savingsRecords")
    if not isinstance(raw, list):
        raise ValueError("savingsRecords must be an array")
    if len(raw) > MAX_LEDGER_RECORDS:
        raise ValueError(
            f"At most {MAX_LEDGER_RECORDS} records allowed in savingsRecords"
        )
    out: list[dict[str, Any]] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"savingsRecords[{i}] must be an object")
        rid = row.get("id")
        if not isinstance(rid, str) or not rid.strip():
            raise ValueError(f"savingsRecords[{i}].id is required")
        dep = row.get("deposit")
        if not isinstance(dep, str) or not dep.strip():
            raise ValueError(f"savingsRecords[{i}].deposit is required")
        if len(dep.strip()) > MAX_INVESTMENT_PROVIDER_LEN:
            raise ValueError(f"savingsRecords[{i}].deposit is too long")
        amt = row.get("value")
        if isinstance(amt, Decimal):
            amt = float(amt)
        if not isinstance(amt, (int, float)) or isinstance(amt, bool):
            raise ValueError(f"savingsRecords[{i}].value must be a number")
        amt_f = float(amt)
        if amt_f != amt_f or abs(amt_f) > 1e15:
            raise ValueError(f"savingsRecords[{i}].value out of range")
        cur = _require_supported_currency(
            row.get("currency", DEFAULT_FINANCE_CURRENCY),
            f"savingsRecords[{i}].currency",
        )
        desc_raw = row.get("description", "")
        if desc_raw is None:
            desc_raw = ""
        if not isinstance(desc_raw, str):
            raise ValueError(f"savingsRecords[{i}].description must be a string")
        d = desc_raw.strip()
        if len(d) > MAX_FINANCE_DESCRIPTION:
            raise ValueError(f"savingsRecords[{i}].description is too long")
        allowed_at = ", ".join(sorted(ASSET_TYPES))
        at_raw = row.get("assetType")
        if at_raw is None or at_raw == "":
            at = "Fixed"
        elif not isinstance(at_raw, str):
            raise ValueError(f"savingsRecords[{i}].assetType must be a string")
        else:
            at_st = at_raw.strip()
            if not at_st:
                at = "Fixed"
            elif at_st not in ASSET_TYPES:
                raise ValueError(
                    f"savingsRecords[{i}].assetType must be one of: {allowed_at}"
                )
            else:
                at = at_st
        out.append(
            {
                "id": rid.strip(),
                "deposit": dep.strip(),
                "assetType": at,
                "description": d,
                "value": amt_f,
                "currency": cur,
            }
        )
    return out


def _normalize_pension_sheet_payload(body: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ValueError("Body must be a JSON object")
    raw = body.get("pensionRecords")
    if not isinstance(raw, list):
        raise ValueError("pensionRecords must be an array")
    if len(raw) > MAX_LEDGER_RECORDS:
        raise ValueError(
            f"At most {MAX_LEDGER_RECORDS} records allowed in pensionRecords"
        )
    out: list[dict[str, Any]] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"pensionRecords[{i}] must be an object")
        rid = row.get("id")
        if not isinstance(rid, str) or not rid.strip():
            raise ValueError(f"pensionRecords[{i}].id is required")
        fund = row.get("fund")
        if not isinstance(fund, str) or not fund.strip():
            raise ValueError(f"pensionRecords[{i}].fund is required")
        if len(fund.strip()) > MAX_INVESTMENT_PROVIDER_LEN:
            raise ValueError(f"pensionRecords[{i}].fund is too long")
        desc_raw = row.get("description", "")
        if desc_raw is None:
            desc_raw = ""
        if not isinstance(desc_raw, str):
            raise ValueError(f"pensionRecords[{i}].description must be a string")
        d = desc_raw.strip()
        if len(d) > MAX_FINANCE_DESCRIPTION:
            raise ValueError(f"pensionRecords[{i}].description is too long")
        amt = row.get("value")
        if isinstance(amt, Decimal):
            amt = float(amt)
        if not isinstance(amt, (int, float)) or isinstance(amt, bool):
            raise ValueError(f"pensionRecords[{i}].value must be a number")
        amt_f = float(amt)
        if amt_f != amt_f or abs(amt_f) > 1e15:
            raise ValueError(f"pensionRecords[{i}].value out of range")
        cur = _require_supported_currency(
            row.get("currency", DEFAULT_FINANCE_CURRENCY),
            f"pensionRecords[{i}].currency",
        )
        out.append(
            {
                "id": rid.strip(),
                "fund": fund.strip(),
                "description": d,
                "value": amt_f,
                "currency": cur,
            }
        )
    return out


def _load_savings_records(table: Any) -> list[dict[str, Any]]:
    res = table.get_item(Key=_finance_sheet_ddb_key("savings"))
    item = res.get("Item")
    if not item:
        return []
    payload = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    nested = _from_ddb_nested(payload)
    if not isinstance(nested, dict):
        return []
    return _sanitize_savings_records_list(nested.get("records"))


def _load_pension_records(table: Any) -> list[dict[str, Any]]:
    res = table.get_item(Key=_finance_sheet_ddb_key("pension"))
    item = res.get("Item")
    if not item:
        return []
    payload = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    nested = _from_ddb_nested(payload)
    if not isinstance(nested, dict):
        return []
    return _sanitize_pension_records_list(nested.get("records"))


def _load_accounts_records(table: Any) -> list[dict[str, Any]]:
    res = table.get_item(Key=_finance_sheet_ddb_key("accounts"))
    item = res.get("Item")
    if not item:
        return []
    payload = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    nested = _from_ddb_nested(payload)
    if not isinstance(nested, dict):
        return []
    return _sanitize_accounts_records_list(nested.get("records"))


def _coerce_liability_amount(raw: Any) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, Decimal):
        f = float(raw)
    elif isinstance(raw, (int, float)):
        f = float(raw)
    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            f = float(s)
        except ValueError:
            return None
    else:
        return None
    if f != f or abs(f) > 1e15:
        return None
    return f


def _normalize_liabilities_sheet_payload(body: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ValueError("Body must be a JSON object")
    raw = body.get("liabilityRecords")
    if not isinstance(raw, list):
        raise ValueError("liabilityRecords must be an array")
    if len(raw) > MAX_LEDGER_RECORDS:
        raise ValueError(
            f"At most {MAX_LEDGER_RECORDS} records allowed in liabilityRecords"
        )
    allowed_lt = ", ".join(sorted(FINANCE_LIABILITY_TYPES))
    out: list[dict[str, Any]] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"liabilityRecords[{i}] must be an object")
        rid = row.get("id")
        if not isinstance(rid, str) or not rid.strip():
            raise ValueError(f"liabilityRecords[{i}].id is required")
        desc = row.get("description")
        if not isinstance(desc, str) or not desc.strip():
            raise ValueError(f"liabilityRecords[{i}].description is required")
        if len(desc.strip()) > MAX_INVESTMENT_PROVIDER_LEN:
            raise ValueError(f"liabilityRecords[{i}].description is too long")
        lt_raw = row.get("liabilityType")
        if not isinstance(lt_raw, str) or not lt_raw.strip():
            raise ValueError(f"liabilityRecords[{i}].liabilityType is required")
        lt = lt_raw.strip()
        if lt not in FINANCE_LIABILITY_TYPES:
            raise ValueError(
                f"liabilityRecords[{i}].liabilityType must be one of: {allowed_lt}"
            )
        amt = row.get("outstandingBalance")
        if isinstance(amt, Decimal):
            amt = float(amt)
        if not isinstance(amt, (int, float)) or isinstance(amt, bool):
            raise ValueError(
                f"liabilityRecords[{i}].outstandingBalance must be a number"
            )
        amt_f = float(amt)
        if amt_f != amt_f or amt_f < 0 or amt_f > 1e15:
            raise ValueError(
                f"liabilityRecords[{i}].outstandingBalance out of range"
            )
        cur = _require_supported_currency(
            row.get("currency", DEFAULT_FINANCE_CURRENCY),
            f"liabilityRecords[{i}].currency",
        )
        rec: dict[str, Any] = {
            "id": rid.strip(),
            "description": desc.strip(),
            "liabilityType": lt,
            "outstandingBalance": amt_f,
            "currency": cur,
        }
        rate_raw = row.get("interestRatePercent")
        if rate_raw is not None and rate_raw != "":
            if isinstance(rate_raw, bool):
                raise ValueError(
                    f"liabilityRecords[{i}].interestRatePercent must be a number"
                )
            if isinstance(rate_raw, Decimal):
                rate_f = float(rate_raw)
            elif isinstance(rate_raw, (int, float)):
                rate_f = float(rate_raw)
            elif isinstance(rate_raw, str):
                try:
                    rate_f = float(rate_raw.strip())
                except ValueError as exc:
                    raise ValueError(
                        f"liabilityRecords[{i}].interestRatePercent must be a number"
                    ) from exc
            else:
                raise ValueError(
                    f"liabilityRecords[{i}].interestRatePercent must be a number"
                )
            if rate_f != rate_f or rate_f < 0 or rate_f > 100:
                raise ValueError(
                    f"liabilityRecords[{i}].interestRatePercent must be between 0 and 100"
                )
            rec["interestRatePercent"] = rate_f
        house_raw = row.get("relatedHouse")
        if house_raw is not None and house_raw != "":
            if not isinstance(house_raw, str) or house_raw not in FINANCE_HOUSE_KEYS:
                houses = ", ".join(sorted(FINANCE_HOUSE_KEYS))
                raise ValueError(
                    f"liabilityRecords[{i}].relatedHouse must be one of: {houses}"
                )
            rec["relatedHouse"] = house_raw
        out.append(rec)
    return out


def _sanitize_liabilities_records_list(raw: Any) -> list[dict[str, Any]]:
    """Best-effort coercion for GET responses (drops invalid rows)."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        if not isinstance(rid, str) or not rid.strip():
            continue
        desc = row.get("description")
        if not isinstance(desc, str) or not desc.strip():
            continue
        d = desc.strip()
        if len(d) > MAX_INVESTMENT_PROVIDER_LEN:
            d = d[:MAX_INVESTMENT_PROVIDER_LEN]
        lt_raw = row.get("liabilityType")
        if not isinstance(lt_raw, str) or lt_raw.strip() not in FINANCE_LIABILITY_TYPES:
            continue
        amt_f = _coerce_liability_amount(row.get("outstandingBalance"))
        if amt_f is None or amt_f < 0:
            continue
        cur = _coerce_finance_currency_value(
            row.get("currency"), DEFAULT_FINANCE_CURRENCY
        )
        entry: dict[str, Any] = {
            "id": rid.strip(),
            "description": d,
            "liabilityType": lt_raw.strip(),
            "outstandingBalance": amt_f,
            "currency": cur,
        }
        rate_f = _coerce_liability_amount(row.get("interestRatePercent"))
        if rate_f is not None and 0 <= rate_f <= 100:
            entry["interestRatePercent"] = rate_f
        rh = row.get("relatedHouse")
        if rh in FINANCE_HOUSE_KEYS:
            entry["relatedHouse"] = rh
        lu = row.get("lastUpdated")
        if isinstance(lu, str) and _is_calendar_date_string(lu):
            entry["lastUpdated"] = lu
        out.append(entry)
    return out


def _liability_row_signature(
    row: dict[str, Any],
) -> tuple[str, str, float, str, float | None, str | None]:
    rate = _coerce_liability_amount(row.get("interestRatePercent"))
    rh = row.get("relatedHouse")
    return (
        str(row.get("description", "")),
        str(row["liabilityType"]),
        float(row["outstandingBalance"]),
        str(row["currency"]),
        rate,
        rh if isinstance(rh, str) else None,
    )


def _merge_liabilities_last_updated(
    normalized: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    *,
    today_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Attach `lastUpdated` (UTC calendar date) when liability fields change."""
    return _merge_sheet_last_updated(
        normalized,
        existing,
        _liability_row_signature,
        today_iso=today_iso,
    )


def _load_liabilities_records(table: Any) -> list[dict[str, Any]]:
    res = table.get_item(Key=_finance_sheet_ddb_key("liabilities"))
    item = res.get("Item")
    if not item:
        return []
    payload = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    nested = _from_ddb_nested(payload)
    if not isinstance(nested, dict):
        return []
    return _sanitize_liabilities_records_list(nested.get("records"))


def _finance_ddb_key(house: str) -> dict[str, str]:
    return {"pk": f"FINANCE#house#{house}", "sk": "STATE"}


def _statement_book_ddb_key(book: str) -> dict[str, str]:
    return {"pk": f"FINANCE#book#{book}", "sk": "STATE"}


def _finance_owner_ddb_key(owner: str) -> dict[str, str]:
    """DynamoDB key for a house statement or a named statement book."""
    if owner in FINANCE_STATEMENT_BOOK_KEYS:
        return _statement_book_ddb_key(owner)
    return _finance_ddb_key(owner)


class MirroredBookError(RuntimeError):
    """User-facing failure while reading a product database into a statement book."""


def mirror_state_key(book: str) -> dict[str, str]:
    """Snapshot row for a product-database mirror (summary, not statement lines)."""
    return {"pk": f"FINANCE#book#{book}", "sk": "MIRROR"}


def _mirrored_line(line: dict[str, Any], prefixes: tuple[str, ...], source: str) -> bool:
    lid = str(line.get("id") or "")
    return lid.startswith(prefixes) or str(line.get("source") or "") == source


def _mirrored_line_same(prev: dict[str, Any], line: dict[str, Any]) -> bool:
    try:
        return (
            str(prev.get("description") or "") == str(line.get("description") or "")
            and str(prev.get("dateUtc") or "") == str(line.get("dateUtc") or "")
            and str(prev.get("sortUtc") or "") == str(line.get("sortUtc") or "")
            and float(prev.get("netAmount") or 0) == float(line.get("netAmount") or 0)
            and float(prev.get("vat") or 0) == float(line.get("vat") or 0)
            and float(prev.get("grossAmount") or 0) == float(line.get("grossAmount") or 0)
            and str(prev.get("currency") or "") == str(line.get("currency") or "")
            and str(prev.get("type") or "") == str(line.get("type") or "")
        )
    except (TypeError, ValueError):
        return False


# DynamoDB items are capped at 400 KB; type tags make the on-wire size larger
# than the JSON we send, so fail before the write when we are already close.
_MIRROR_ITEM_SOFT_LIMIT = 350_000


def _put_finance_owner_payload(table: Any, book: str, payload: dict[str, Any]) -> None:
    item = {**_finance_owner_ddb_key(book), **_to_ddb_nested(payload)}
    encoded = json.dumps(item, default=str).encode("utf-8")
    if len(encoded) > _MIRROR_ITEM_SOFT_LIMIT:
        raise MirroredBookError(
            f"The {book} statement book is too large to store "
            f"({len(payload.get('lines') or [])} lines). Split the history or raise the store."
        )
    try:
        table.put_item(Item=item)
    except ClientError as exc:
        response = getattr(exc, "response", None)
        error = response.get("Error", {}) if isinstance(response, dict) else {}
        code = str(error.get("Code") or "")
        message = str(error.get("Message") or exc)
        if code == "ValidationException" or "400 KB" in message or "item size" in message.lower():
            raise MirroredBookError(
                f"The {book} statement book is too large to store "
                f"({len(payload.get('lines') or [])} lines)."
            ) from exc
        raise


def upsert_mirrored_lines(
    table: Any,
    book: str,
    desired: list[dict[str, Any]],
    *,
    id_prefixes: tuple[str, ...],
    source: str,
) -> tuple[int, int]:
    """Replace one mirror's lines on a statement book.

    Lines this mirror wrote earlier that are no longer desired are removed.
    Lines from other mirrors and manually entered lines are left in place.
    Returns ``(written, removed)``.
    """
    data = _load_finance_owner(table, book)
    existing = [ln for ln in (data.get("lines") or []) if isinstance(ln, dict)]
    desired_by_id = {str(ln["id"]): ln for ln in desired}
    kept: list[dict[str, Any]] = []
    written = 0
    removed = 0
    seen: set[str] = set()
    for prev in existing:
        lid = str(prev.get("id") or "")
        if not _mirrored_line(prev, id_prefixes, source):
            kept.append(prev)
            continue
        line = desired_by_id.get(lid)
        if line is None:
            removed += 1
            continue
        seen.add(lid)
        if _mirrored_line_same(prev, line) and str(prev.get("source") or "") == source:
            kept.append(prev)
        else:
            kept.append(line)
            written += 1
    for lid, line in desired_by_id.items():
        if lid not in seen:
            kept.append(line)
            written += 1
    if not written and not removed:
        return 0, 0
    try:
        payload = _normalize_finance_payload(
            {
                "defaultCurrency": data.get("defaultCurrency") or DEFAULT_FINANCE_CURRENCY,
                "float": data.get("float") or {"amount": 0, "currency": DEFAULT_FINANCE_CURRENCY},
                "lines": kept,
            }
        )
    except ValueError as exc:
        raise MirroredBookError(str(exc)) from exc
    # Normalisation drops unknown keys; re-tag mirrored lines so a later read
    # can tell them from manual entries.
    for line in payload["lines"]:
        if str(line.get("id") or "").startswith(id_prefixes):
            line["source"] = source
    _put_finance_owner_payload(table, book, payload)
    return written, removed


def _load_finance_owner(table: Any, owner: str) -> dict[str, Any]:
    res = table.get_item(Key=_finance_owner_ddb_key(owner))
    item = res.get("Item")
    if not item:
        return _default_finance_house()
    payload = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    nested = _from_ddb_nested(payload)
    if not isinstance(nested, dict):
        return _default_finance_house()
    return _sanitize_finance_house(nested)


def _load_finance_house(table: Any, house: str) -> dict[str, Any]:
    return _load_finance_owner(table, house)


def _source_key_to_house_map(table: Any) -> dict[str, str]:
    """Map S3 object keys to finance house keys using imported statement lines."""
    out: dict[str, str] = {}
    for owner in sorted(FINANCE_STATEMENT_OWNER_KEYS):
        data = _load_finance_owner(table, owner)
        for ln in data.get("lines") or []:
            if not isinstance(ln, dict):
                continue
            for raw_key in _line_source_asset_keys_raw(ln):
                out.setdefault(raw_key, owner)
    return out


def _enrich_scan_items_asset_meta(
    items: list[dict[str, Any]],
    *,
    table: Any,
    bucket: str,
) -> list[dict[str, Any]]:
    """Augment ASSET# / META rows for admin list views.

    Older items may omit ``uploadedAt`` / ``house``; we recover ``house`` from
    finance statement lines and timestamps from S3 ``LastModified`` when needed.
    """
    asset_spans: list[tuple[int, str]] = []
    for idx, it in enumerate(items):
        pk = it.get("pk")
        sk = it.get("sk")
        if not isinstance(pk, str) or not pk.startswith("ASSET#"):
            continue
        if sk != "META":
            continue
        s3_key = pk.removeprefix("ASSET#")
        if not (
            s3_key.startswith("uploads/") or s3_key.startswith("inbound/")
        ):
            continue
        asset_spans.append((idx, s3_key))

    if not asset_spans:
        return items

    key_to_house: dict[str, str] = {}
    if any(
        not str(items[i].get("house") or "").strip() for i, _ in asset_spans
    ):
        key_to_house = _source_key_to_house_map(table)

    out = list(items)
    for idx, s3_key in asset_spans:
        merged = dict(out[idx])
        if not str(merged.get("house") or "").strip():
            inferred = key_to_house.get(s3_key)
            if inferred:
                merged["house"] = inferred
        if not str(merged.get("uploadedAt") or "").strip() and bucket:
            try:
                head = runtime._s3.head_object(Bucket=bucket, Key=s3_key)
            except ClientError:
                head = {}
            lm = head.get("LastModified")
            if isinstance(lm, datetime):
                merged["uploadedAt"] = _utc_iso_z(lm)
        if not str(merged.get("fileName") or "").strip():
            merged["fileName"] = os.path.basename(s3_key)
        out[idx] = merged
    return out


def _persist_asset_meta_after_parse(
    *,
    table: Any,
    s3_key: str,
    house: str,
    head: dict[str, Any],
    file_name: str,
    request_id: str,
    owner_sub: str | None = None,
) -> None:
    """Ensure ASSET META reflects the house and timestamps after a successful import.

    Browser uploads call ``/assets/confirm`` first, so META usually exists and
    we merge. Inbound-email imports write PDFs directly under ``inbound/…``;
    when no META row exists yet, we create one (same visibility as confirm).
    """
    asset_pk = f"ASSET#{s3_key}"
    last_mod = head.get("LastModified")
    if isinstance(last_mod, datetime):
        uploaded_at = _utc_iso_z(last_mod)
    else:
        uploaded_at = _utc_iso_z(datetime.now(timezone.utc))
    size = int(head.get("ContentLength") or 0)
    etag = str(head.get("ETag") or "").strip().strip('"')
    try:
        table.update_item(
            Key={"pk": asset_pk, "sk": "META"},
            UpdateExpression=(
                "SET house = :house, "
                "uploadedAt = if_not_exists(uploadedAt, :ua), "
                "fileName = if_not_exists(fileName, :fn)"
            ),
            ExpressionAttributeValues={
                ":house": house,
                ":ua": uploaded_at,
                ":fn": file_name,
            },
            ConditionExpression="attribute_exists(pk)",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ConditionalCheckFailedException":
            item: dict[str, Any] = {
                "pk": asset_pk,
                "sk": "META",
                "house": house,
                "uploadedAt": uploaded_at,
                "fileName": file_name,
                "size": size,
                "s3Etag": etag,
                "note": (
                    "metadata from statement import (no prior /assets/confirm; "
                    "e.g. inbound email)"
                ),
            }
            if owner_sub:
                item["ownerSub"] = owner_sub
            table.put_item(Item=_to_ddb(item))
            _log_event(
                "info",
                tag="asset_meta_parse_created",
                key=s3_key[:512],
                house=house,
                request_id=request_id,
            )
            return
        raise


def _finance_sheet_ddb_key(sheet_slug: str) -> dict[str, str]:
    return {"pk": f"FINANCE#sheet#{sheet_slug}", "sk": "STATE"}


def _load_finance_sheet(
    table: Any, sheet_slug: str, categories: frozenset[str]
) -> list[dict[str, Any]]:
    res = table.get_item(Key=_finance_sheet_ddb_key(sheet_slug))
    item = res.get("Item")
    if not item:
        return []
    payload = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    nested = _from_ddb_nested(payload)
    if not isinstance(nested, dict):
        return []
    return _sanitize_ledger_records_list(
        nested.get("records"),
        categories,
        include_income_flags=(sheet_slug == "income"),
        include_expense_flags=False,
    )


def _load_finance_expenses_ledger_with_allocation(
    table: Any,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Expense ledger rows plus optional income-allocation percentages."""
    res = table.get_item(Key=_finance_sheet_ddb_key("expenses"))
    item = res.get("Item")
    if not item:
        return [], _sanitize_expense_income_allocation_percentages(None)
    payload = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    nested = _from_ddb_nested(payload)
    if not isinstance(nested, dict):
        return [], _sanitize_expense_income_allocation_percentages(None)
    records = _sanitize_ledger_records_list(
        nested.get("records"),
        EXPENSE_RECORD_CATEGORIES,
        include_income_flags=False,
        include_expense_flags=True,
    )
    perc = _sanitize_expense_income_allocation_percentages(
        nested.get("expenseIncomeAllocationPercents")
    )
    return records, perc


def _load_existing_expense_income_allocation_percentages(table: Any) -> dict[str, float]:
    """Allocation rates currently stored on the expenses sheet item (if any)."""
    res = table.get_item(Key=_finance_sheet_ddb_key("expenses"))
    item = res.get("Item")
    if not item:
        return _sanitize_expense_income_allocation_percentages(None)
    payload = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    nested = _from_ddb_nested(payload)
    if not isinstance(nested, dict):
        return _sanitize_expense_income_allocation_percentages(None)
    return _sanitize_expense_income_allocation_percentages(
        nested.get("expenseIncomeAllocationPercents")
    )


def _path_finance_house(event: dict[str, Any], path: str) -> str | None:
    pp = (event.get("pathParameters") or {}).get("house")
    if isinstance(pp, str) and pp.strip():
        return pp.strip().lower()
    parts = [p for p in path.split("/") if p]
    if len(parts) == 2 and parts[0] == "finance":
        return parts[1].lower()
    return None


def _validate_record_pk(pk: str) -> bool:
    return isinstance(pk, str) and pk.startswith(RECORD_PK_PREFIX)

