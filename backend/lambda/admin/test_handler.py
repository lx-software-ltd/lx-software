"""Unit tests for admin API helpers (host has no boto3; stub deps before import)."""

import json
import sys
import types
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _install_stubs() -> None:
    mock_boto = MagicMock()
    sys.modules["boto3"] = mock_boto

    class ClientError(Exception):
        pass

    botocore = types.ModuleType("botocore")
    exceptions = types.ModuleType("botocore.exceptions")
    exceptions.ClientError = ClientError
    botocore.exceptions = exceptions
    sys.modules["botocore"] = botocore
    sys.modules["botocore.exceptions"] = exceptions


_install_stubs()

from handler import (  # noqa: E402
    DEFAULT_EXPENSE_INCOME_ALLOCATION_PERCENTAGES,
    EXPENSE_RECORD_CATEGORIES,
    INCOME_RECORD_CATEGORIES,
    _groups_include_admin,
    _is_allowed_upload_content_type,
    _build_allocation_records_for_response,
    _derived_expense_rows_from_tagged_income,
    _merge_allocation_stored_last_updated,
    _merge_accounts_last_updated,
    _merge_investment_last_updated,
    _merge_liabilities_last_updated,
    _merge_pension_last_updated,
    _normalize_allocations_sheet_payload,
    _normalize_accounts_sheet_payload,
    _normalize_finance_payload,
    _normalize_investment_sheet_payload,
    _normalize_ledger_sheet_payload,
    _normalize_liabilities_sheet_payload,
    _normalize_pension_sheet_payload,
    _normalize_public_asset_key,
    _normalize_savings_sheet_payload,
    _normalize_finance_quote_symbol,
    _normalize_yahoo_price_currency,
    _parse_finance_quotes_query,
    _parse_fx_v2_rates_query,
    _path_finance_house_for_parse,
    _path_finance_parse_job,
    _sanitize_accounts_records_list,
    _sanitize_expense_income_allocation_percentages,
    _sanitize_liabilities_records_list,
    _sanitize_investment_records_list,
    _sanitize_ledger_records_list,
    _sanitize_pension_records_list,
    _sanitize_savings_records_list,
    _load_investment_records,
    _statement_basename_already_imported,
    _utc_iso_z,
)
from dispatch import lambda_handler  # noqa: E402


class TestNormalizePublicAssetKey(unittest.TestCase):
    def test_accepts_uploads_prefix(self) -> None:
        self.assertEqual(
            _normalize_public_asset_key("uploads/sub/x/file.pdf"),
            "uploads/sub/x/file.pdf",
        )

    def test_rejects_traversal(self) -> None:
        self.assertIsNone(_normalize_public_asset_key("uploads/../etc/passwd"))
        self.assertIsNone(_normalize_public_asset_key("../x"))

    def test_rejects_other_prefix(self) -> None:
        self.assertIsNone(_normalize_public_asset_key("other/key"))

    def test_accepts_inbound_email_asset_key(self) -> None:
        batch = "a" * 32
        key = f"inbound/hillmarton/{batch}/00_stmt.pdf"
        self.assertEqual(_normalize_public_asset_key(key), key)

    def test_accepts_inbound_statement_book_key(self) -> None:
        batch = "b" * 32
        key = f"inbound/lxSoftware/{batch}/00_invoice.pdf"
        self.assertEqual(_normalize_public_asset_key(key), key)

    def test_rejects_inbound_bad_house_or_batch(self) -> None:
        batch = "a" * 32
        self.assertIsNone(
            _normalize_public_asset_key(f"inbound/unknown/{batch}/00_x.pdf")
        )
        self.assertIsNone(
            _normalize_public_asset_key(f"inbound/hillmarton/short/00_x.pdf")
        )
        self.assertIsNone(
            _normalize_public_asset_key(f"inbound/hillmarton/{'g' * 32}/x.pdf")
        )

    def test_empty(self) -> None:
        self.assertIsNone(_normalize_public_asset_key(None))
        self.assertIsNone(_normalize_public_asset_key(""))
        self.assertIsNone(_normalize_public_asset_key("   "))


class TestGroups(unittest.TestCase):
    def test_admin_present(self) -> None:
        self.assertTrue(_groups_include_admin({"cognito:groups": "admin"}))
        self.assertTrue(_groups_include_admin({"cognito:groups": "viewer,admin"}))
        self.assertTrue(_groups_include_admin({"cognito:groups": ["admin"]}))
        self.assertTrue(
            _groups_include_admin({"cognito:groups": ["viewer", "admin"]})
        )

    def test_admin_present_httpapi_bracketed(self) -> None:
        # API Gateway HTTP API JWT authorizer passes array claims as a
        # Java toString() string, with literal brackets and ", " separators.
        self.assertTrue(_groups_include_admin({"cognito:groups": "[admin]"}))
        self.assertTrue(
            _groups_include_admin({"cognito:groups": "[viewer, admin]"})
        )
        self.assertTrue(
            _groups_include_admin({"cognito:groups": "[admin, viewer]"})
        )

    def test_admin_absent(self) -> None:
        self.assertFalse(_groups_include_admin({"cognito:groups": "viewer"}))
        self.assertFalse(_groups_include_admin({"cognito:groups": "[viewer]"}))
        self.assertFalse(
            _groups_include_admin({"cognito:groups": "[viewer, editor]"})
        )
        self.assertFalse(_groups_include_admin({"cognito:groups": []}))
        self.assertFalse(_groups_include_admin({}))


class TestFinancePayload(unittest.TestCase):
    def test_valid_minimal(self) -> None:
        body = {
            "defaultCurrency": "EUR",
            "float": {"amount": 100.5, "currency": "gbp"},
            "lines": [
                {
                    "id": "a",
                    "dateUtc": "2026-05-08T12:00:00.000Z",
                    "type": "income",
                    "description": "Rent",
                    "netAmount": 100,
                    "vat": 20,
                    "grossAmount": 120,
                    "currency": "GBP",
                }
            ],
        }
        out = _normalize_finance_payload(body)
        self.assertEqual(out["defaultCurrency"], "EUR")
        self.assertEqual(out["float"]["currency"], "GBP")
        self.assertEqual(len(out["lines"]), 1)
        self.assertEqual(out["lines"][0]["netAmount"], 100.0)

    def test_omitted_default_currency_is_hkd(self) -> None:
        body = {"float": {"amount": 0, "currency": "USD"}, "lines": []}
        out = _normalize_finance_payload(body)
        self.assertEqual(out["defaultCurrency"], "HKD")

    def test_unsupported_currency_rejected(self) -> None:
        body = {
            "defaultCurrency": "JPY",
            "float": {"amount": 0, "currency": "HKD"},
            "lines": [],
        }
        with self.assertRaises(ValueError):
            _normalize_finance_payload(body)

    def test_invalid_type(self) -> None:
        body = {
            "float": {"amount": 0, "currency": "GBP"},
            "lines": [
                {
                    "id": "a",
                    "dateUtc": "2026-05-08T12:00:00.000Z",
                    "type": "other",
                    "description": "x",
                    "netAmount": 1,
                    "vat": 0,
                    "grossAmount": 1,
                    "currency": "GBP",
                }
            ],
        }
        with self.assertRaises(ValueError):
            _normalize_finance_payload(body)


    def test_source_asset_key_persisted(self) -> None:
        body = {
            "defaultCurrency": "GBP",
            "float": {"amount": 0, "currency": "GBP"},
            "lines": [
                {
                    "id": "a",
                    "dateUtc": "2026-05-08T12:00:00.000Z",
                    "type": "expenditure",
                    "description": "Coffee",
                    "netAmount": 2.5,
                    "vat": 0.5,
                    "grossAmount": 3.0,
                    "currency": "GBP",
                    "sourceAssetKey": "uploads/abc/123/statement.pdf",
                }
            ],
        }
        out = _normalize_finance_payload(body)
        self.assertEqual(
            out["lines"][0]["sourceAssetKeys"], ["uploads/abc/123/statement.pdf"]
        )
        self.assertNotIn("sourceAssetKey", out["lines"][0])

    def test_source_asset_keys_multiple(self) -> None:
        body = {
            "defaultCurrency": "GBP",
            "float": {"amount": 0, "currency": "GBP"},
            "lines": [
                {
                    "id": "a",
                    "dateUtc": "2026-05-08T12:00:00.000Z",
                    "type": "expenditure",
                    "description": "Coffee",
                    "netAmount": 2.5,
                    "vat": 0.5,
                    "grossAmount": 3.0,
                    "currency": "GBP",
                    "sourceAssetKeys": [
                        "uploads/abc/1/a.pdf",
                        "uploads/abc/2/b.pdf",
                    ],
                }
            ],
        }
        out = _normalize_finance_payload(body)
        self.assertEqual(
            out["lines"][0]["sourceAssetKeys"],
            ["uploads/abc/1/a.pdf", "uploads/abc/2/b.pdf"],
        )

    def test_source_asset_key_legacy_merges_with_keys(self) -> None:
        body = {
            "defaultCurrency": "GBP",
            "float": {"amount": 0, "currency": "GBP"},
            "lines": [
                {
                    "id": "a",
                    "dateUtc": "2026-05-08T12:00:00.000Z",
                    "type": "expenditure",
                    "description": "Coffee",
                    "netAmount": 2.5,
                    "vat": 0.5,
                    "grossAmount": 3.0,
                    "currency": "GBP",
                    "sourceAssetKey": "uploads/legacy/x.pdf",
                    "sourceAssetKeys": ["uploads/new/y.pdf"],
                }
            ],
        }
        out = _normalize_finance_payload(body)
        self.assertEqual(
            out["lines"][0]["sourceAssetKeys"],
            ["uploads/new/y.pdf", "uploads/legacy/x.pdf"],
        )

    def test_source_asset_key_optional(self) -> None:
        body = {
            "defaultCurrency": "GBP",
            "float": {"amount": 0, "currency": "GBP"},
            "lines": [
                {
                    "id": "a",
                    "dateUtc": "2026-05-08T12:00:00.000Z",
                    "type": "income",
                    "description": "Rent",
                    "netAmount": 1.0,
                    "vat": 0,
                    "grossAmount": 1.0,
                    "currency": "GBP",
                }
            ],
        }
        out = _normalize_finance_payload(body)
        self.assertNotIn("sourceAssetKey", out["lines"][0])
        self.assertNotIn("sourceAssetKeys", out["lines"][0])


class TestInvestmentSheetPayload(unittest.TestCase):
    def test_normalize_valid(self) -> None:
        body = {
            "investmentRecords": [
                {
                    "id": "x1",
                    "category": "ETF",
                    "assetType": "Liquid",
                    "provider": "Broker A",
                    "principalAmount": 10000.5,
                    "currency": "USD",
                }
            ]
        }
        out = _normalize_investment_sheet_payload(body)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["category"], "ETF")
        self.assertEqual(out[0]["assetType"], "Liquid")
        self.assertEqual(out[0]["principalAmount"], 10000.5)

    def test_sanitize_drops_unknown_category(self) -> None:
        raw = [
            {
                "id": "a",
                "category": "Stocks",
                "assetType": "Liquid",
                "provider": "X",
                "principalAmount": 1,
                "currency": "HKD",
            },
            {
                "id": "b",
                "category": "Crypto",
                "assetType": "Fixed",
                "provider": "Vault",
                "principalAmount": 2,
                "currency": "HKD",
            },
        ]
        out = _sanitize_investment_records_list(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "b")

    def test_invalid_asset_type_rejected(self) -> None:
        body = {
            "investmentRecords": [
                {
                    "id": "x1",
                    "category": "ETF",
                    "assetType": "Cash",
                    "provider": "Broker A",
                    "principalAmount": 1,
                    "currency": "USD",
                }
            ]
        }
        with self.assertRaises(ValueError):
            _normalize_investment_sheet_payload(body)

    def test_real_estate_related_house(self) -> None:
        body = {
            "investmentRecords": [
                {
                    "id": "x1",
                    "category": "Real Estate",
                    "assetType": "Fixed",
                    "provider": "Bank",
                    "principalAmount": 1,
                    "currency": "HKD",
                    "relatedHouse": "hillmarton",
                }
            ]
        }
        out = _normalize_investment_sheet_payload(body)
        self.assertEqual(out[0]["relatedHouse"], "hillmarton")

    def test_related_house_rejected_for_non_real_estate(self) -> None:
        body = {
            "investmentRecords": [
                {
                    "id": "x1",
                    "category": "ETF",
                    "assetType": "Liquid",
                    "provider": "X",
                    "principalAmount": 1,
                    "currency": "HKD",
                    "relatedHouse": "morrison",
                }
            ]
        }
        with self.assertRaises(ValueError):
            _normalize_investment_sheet_payload(body)

    def test_etf_ticker_persisted(self) -> None:
        body = {
            "investmentRecords": [
                {
                    "id": "x1",
                    "category": "ETF",
                    "assetType": "Liquid",
                    "provider": "X",
                    "principalAmount": 1,
                    "currency": "HKD",
                    "ticker": "VWRA",
                }
            ]
        }
        out = _normalize_investment_sheet_payload(body)
        self.assertEqual(out[0]["ticker"], "VWRA")

    def test_crypto_currency_persisted(self) -> None:
        body = {
            "investmentRecords": [
                {
                    "id": "x1",
                    "category": "Crypto",
                    "assetType": "Liquid",
                    "provider": "X",
                    "principalAmount": 1,
                    "currency": "HKD",
                    "cryptoCurrency": "Bitcoin",
                }
            ]
        }
        out = _normalize_investment_sheet_payload(body)
        self.assertEqual(out[0]["cryptoCurrency"], "Bitcoin")

    def test_real_estate_rejects_ticker(self) -> None:
        body = {
            "investmentRecords": [
                {
                    "id": "x1",
                    "category": "Real Estate",
                    "assetType": "Fixed",
                    "provider": "B",
                    "principalAmount": 1,
                    "currency": "HKD",
                    "ticker": "X",
                }
            ]
        }
        with self.assertRaises(ValueError):
            _normalize_investment_sheet_payload(body)

    def test_fixed_term_deposit_rejects_detail_fields(self) -> None:
        body = {
            "investmentRecords": [
                {
                    "id": "x1",
                    "category": "Fixed Term Deposit",
                    "assetType": "Fixed",
                    "provider": "B",
                    "principalAmount": 1,
                    "currency": "HKD",
                    "cryptoCurrency": "BTC",
                }
            ]
        }
        with self.assertRaises(ValueError):
            _normalize_investment_sheet_payload(body)

    def test_unit_optional_and_persisted(self) -> None:
        body = {
            "investmentRecords": [
                {
                    "id": "x1",
                    "category": "ETF",
                    "assetType": "Liquid",
                    "provider": "X",
                    "principalAmount": 1,
                    "currency": "HKD",
                    "unit": 42.5,
                }
            ]
        }
        out = _normalize_investment_sheet_payload(body)
        self.assertEqual(out[0]["unit"], 42.5)

    def test_invalid_unit_rejected(self) -> None:
        body = {
            "investmentRecords": [
                {
                    "id": "x1",
                    "category": "ETF",
                    "assetType": "Liquid",
                    "provider": "X",
                    "principalAmount": 1,
                    "currency": "HKD",
                    "unit": "x",
                }
            ]
        }
        with self.assertRaises(ValueError):
            _normalize_investment_sheet_payload(body)

    def test_real_estate_current_value_persisted(self) -> None:
        body = {
            "investmentRecords": [
                {
                    "id": "x1",
                    "category": "Real Estate",
                    "assetType": "Fixed",
                    "provider": "B",
                    "principalAmount": 100,
                    "currency": "HKD",
                    "currentValue": 2_000_000,
                }
            ]
        }
        out = _normalize_investment_sheet_payload(body)
        self.assertEqual(out[0]["currentValue"], 2_000_000.0)

    def test_real_estate_ignores_unit(self) -> None:
        body = {
            "investmentRecords": [
                {
                    "id": "x1",
                    "category": "Real Estate",
                    "assetType": "Fixed",
                    "provider": "B",
                    "principalAmount": 100,
                    "currency": "HKD",
                    "unit": 3,
                }
            ]
        }
        out = _normalize_investment_sheet_payload(body)
        self.assertNotIn("unit", out[0])

    def test_current_value_rejected_for_etf(self) -> None:
        body = {
            "investmentRecords": [
                {
                    "id": "x1",
                    "category": "ETF",
                    "assetType": "Liquid",
                    "provider": "X",
                    "principalAmount": 1,
                    "currency": "HKD",
                    "currentValue": 5,
                }
            ]
        }
        with self.assertRaises(ValueError):
            _normalize_investment_sheet_payload(body)


class TestMergeInvestmentLastUpdated(unittest.TestCase):
    def test_new_id_gets_today(self) -> None:
        normalized = [
            {
                "id": "n1",
                "category": "ETF",
                "assetType": "Liquid",
                "provider": "P",
                "principalAmount": 1.0,
                "currency": "HKD",
            }
        ]
        out = _merge_investment_last_updated(normalized, [], today_iso="2026-01-10")
        self.assertEqual(out[0]["lastUpdated"], "2026-01-10")

    def test_unchanged_preserves_last_updated(self) -> None:
        normalized = [
            {
                "id": "i1",
                "category": "ETF",
                "assetType": "Liquid",
                "provider": "P",
                "principalAmount": 1.0,
                "currency": "HKD",
            }
        ]
        existing = [
            {
                **normalized[0],
                "lastUpdated": "2025-03-01",
            }
        ]
        out = _merge_investment_last_updated(normalized, existing, today_iso="2026-01-10")
        self.assertEqual(out[0]["lastUpdated"], "2025-03-01")

    def test_changed_row_gets_today(self) -> None:
        normalized = [
            {
                "id": "i1",
                "category": "ETF",
                "assetType": "Liquid",
                "provider": "P",
                "principalAmount": 2.0,
                "currency": "HKD",
            }
        ]
        existing = [
            {
                "id": "i1",
                "category": "ETF",
                "assetType": "Liquid",
                "provider": "P",
                "principalAmount": 1.0,
                "currency": "HKD",
                "lastUpdated": "2025-03-01",
            }
        ]
        out = _merge_investment_last_updated(normalized, existing, today_iso="2026-01-10")
        self.assertEqual(out[0]["lastUpdated"], "2026-01-10")

    def test_unchanged_legacy_omits_last_updated(self) -> None:
        normalized = [
            {
                "id": "i1",
                "category": "ETF",
                "assetType": "Liquid",
                "provider": "P",
                "principalAmount": 1.0,
                "currency": "HKD",
            }
        ]
        existing = [
            {
                "id": "i1",
                "category": "ETF",
                "assetType": "Liquid",
                "provider": "P",
                "principalAmount": 1.0,
                "currency": "HKD",
            }
        ]
        out = _merge_investment_last_updated(normalized, existing, today_iso="2026-01-10")
        self.assertNotIn("lastUpdated", out[0])


class TestSavingsPensionSheetPayload(unittest.TestCase):
    def test_savings_normalize_valid(self) -> None:
        body = {
            "savingsRecords": [
                {
                    "id": "s1",
                    "deposit": "HSBC Time Deposit",
                    "value": 50000,
                    "currency": "HKD",
                }
            ]
        }
        out = _normalize_savings_sheet_payload(body)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["deposit"], "HSBC Time Deposit")
        self.assertEqual(out[0]["description"], "")
        self.assertEqual(out[0]["assetType"], "Fixed")
        self.assertEqual(out[0]["value"], 50000.0)

    def test_savings_normalize_with_description(self) -> None:
        body = {
            "savingsRecords": [
                {
                    "id": "s1",
                    "deposit": "HSBC",
                    "description": "12-month fixed",
                    "value": 100,
                    "currency": "HKD",
                }
            ]
        }
        out = _normalize_savings_sheet_payload(body)
        self.assertEqual(out[0]["description"], "12-month fixed")
        self.assertEqual(out[0]["assetType"], "Fixed")
        body = {
            "pensionRecords": [
                {
                    "id": "p1",
                    "fund": "Global Equity",
                    "description": "DC scheme",
                    "value": 120000.5,
                    "currency": "USD",
                }
            ]
        }
        out = _normalize_pension_sheet_payload(body)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["fund"], "Global Equity")
        self.assertEqual(out[0]["description"], "DC scheme")
        self.assertEqual(out[0]["currency"], "USD")

    def test_savings_normalize_accepts_asset_type_liquid(self) -> None:
        body = {
            "savingsRecords": [
                {
                    "id": "s1",
                    "deposit": "Instant access",
                    "assetType": "Liquid",
                    "value": 1,
                    "currency": "HKD",
                }
            ]
        }
        out = _normalize_savings_sheet_payload(body)
        self.assertEqual(out[0]["assetType"], "Liquid")

    def test_savings_normalize_rejects_invalid_asset_type(self) -> None:
        body = {
            "savingsRecords": [
                {
                    "id": "s1",
                    "deposit": "X",
                    "assetType": "Volatile",
                    "value": 1,
                    "currency": "HKD",
                }
            ]
        }
        with self.assertRaises(ValueError):
            _normalize_savings_sheet_payload(body)

    def test_savings_sanitize_drops_empty_deposit(self) -> None:
        raw = [
            {"id": "a", "deposit": "", "value": 1, "currency": "HKD"},
            {"id": "b", "deposit": "OK", "value": 2, "currency": "HKD"},
        ]
        out = _sanitize_savings_records_list(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "b")
        self.assertEqual(out[0]["assetType"], "Fixed")

    def test_pension_rejects_bad_currency(self) -> None:
        body = {
            "pensionRecords": [
                {"id": "p1", "fund": "X", "value": 1, "currency": "XXX"},
            ]
        }
        with self.assertRaises(ValueError):
            _normalize_pension_sheet_payload(body)

    def test_pension_sanitize_keeps_last_updated(self) -> None:
        raw = [
            {
                "id": "p1",
                "fund": "Plan",
                "description": "x",
                "value": 1,
                "currency": "HKD",
                "lastUpdated": "2024-06-15",
            }
        ]
        out = _sanitize_pension_records_list(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["lastUpdated"], "2024-06-15")

    def test_pension_sanitize_drops_invalid_last_updated(self) -> None:
        raw = [
            {
                "id": "p1",
                "fund": "Plan",
                "description": "",
                "value": 1,
                "currency": "HKD",
                "lastUpdated": "not-a-date",
            }
        ]
        out = _sanitize_pension_records_list(raw)
        self.assertEqual(len(out), 1)
        self.assertNotIn("lastUpdated", out[0])


class TestMergePensionLastUpdated(unittest.TestCase):
    def test_new_id_gets_today(self) -> None:
        normalized = [
            {
                "id": "n1",
                "fund": "F",
                "description": "",
                "value": 1.0,
                "currency": "HKD",
            }
        ]
        out = _merge_pension_last_updated(normalized, [], today_iso="2026-01-10")
        self.assertEqual(out[0]["lastUpdated"], "2026-01-10")

    def test_unchanged_preserves_last_updated(self) -> None:
        normalized = [
            {
                "id": "p1",
                "fund": "F",
                "description": "d",
                "value": 1.0,
                "currency": "HKD",
            }
        ]
        existing = [
            {
                "id": "p1",
                "fund": "F",
                "description": "d",
                "value": 1.0,
                "currency": "HKD",
                "lastUpdated": "2025-03-01",
            }
        ]
        out = _merge_pension_last_updated(normalized, existing, today_iso="2026-01-10")
        self.assertEqual(out[0]["lastUpdated"], "2025-03-01")

    def test_unchanged_legacy_omits_last_updated(self) -> None:
        normalized = [
            {
                "id": "p1",
                "fund": "F",
                "description": "",
                "value": 1.0,
                "currency": "HKD",
            }
        ]
        existing = [
            {
                "id": "p1",
                "fund": "F",
                "description": "",
                "value": 1.0,
                "currency": "HKD",
            }
        ]
        out = _merge_pension_last_updated(normalized, existing, today_iso="2026-01-10")
        self.assertNotIn("lastUpdated", out[0])

    def test_changed_row_gets_today(self) -> None:
        normalized = [
            {
                "id": "p1",
                "fund": "F",
                "description": "new",
                "value": 1.0,
                "currency": "HKD",
            }
        ]
        existing = [
            {
                "id": "p1",
                "fund": "F",
                "description": "old",
                "value": 1.0,
                "currency": "HKD",
                "lastUpdated": "2025-03-01",
            }
        ]
        out = _merge_pension_last_updated(normalized, existing, today_iso="2026-01-10")
        self.assertEqual(out[0]["lastUpdated"], "2026-01-10")


class TestAccountsSheetPayload(unittest.TestCase):
    def test_normalize_valid(self) -> None:
        body = {
            "accountRecords": [
                {
                    "id": "a1",
                    "description": "Household Visa",
                    "accountType": "Credit Card",
                    "billingCycleDay": 15,
                    "recordedValue": -1200.5,
                    "currency": "HKD",
                }
            ]
        }
        out = _normalize_accounts_sheet_payload(body)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["description"], "Household Visa")
        self.assertEqual(out[0]["accountType"], "Credit Card")
        self.assertEqual(out[0]["billingCycleDay"], 15)
        self.assertEqual(out[0]["recordedValue"], -1200.5)
        self.assertEqual(out[0]["currency"], "HKD")
        self.assertEqual(out[0]["lastStatementAmount"], 0.0)

    def test_normalize_credit_card_last_statement_amount(self) -> None:
        body = {
            "accountRecords": [
                {
                    "id": "a1",
                    "description": "Household Visa",
                    "accountType": "Credit Card",
                    "billingCycleDay": 15,
                    "recordedValue": -1200.5,
                    "lastStatementAmount": 2500.0,
                    "currency": "HKD",
                }
            ]
        }
        out = _normalize_accounts_sheet_payload(body)
        self.assertEqual(out[0]["lastStatementAmount"], 2500.0)

    def test_normalize_rejects_bad_credit_card_last_statement(self) -> None:
        body = {
            "accountRecords": [
                {
                    "id": "a1",
                    "accountType": "Credit Card",
                    "billingCycleDay": 15,
                    "recordedValue": 1,
                    "lastStatementAmount": "not-a-number",
                    "currency": "HKD",
                }
            ]
        }
        with self.assertRaises(ValueError):
            _normalize_accounts_sheet_payload(body)

    def test_normalize_rejects_bad_account_type(self) -> None:
        body = {
            "accountRecords": [
                {
                    "id": "a1",
                    "accountType": "Loan",
                    "billingCycleDay": 1,
                    "recordedValue": 1,
                    "currency": "HKD",
                }
            ]
        }
        with self.assertRaises(ValueError):
            _normalize_accounts_sheet_payload(body)

    def test_normalize_description_defaults_empty(self) -> None:
        body = {
            "accountRecords": [
                {
                    "id": "a1",
                    "accountType": "Bank Account",
                    "billingCycleDay": 1,
                    "recordedValue": 1,
                    "currency": "HKD",
                }
            ]
        }
        out = _normalize_accounts_sheet_payload(body)
        self.assertEqual(out[0]["description"], "")

    def test_normalize_bank_omits_last_statement_amount(self) -> None:
        body = {
            "accountRecords": [
                {
                    "id": "a1",
                    "accountType": "Bank Account",
                    "billingCycleDay": 1,
                    "recordedValue": 1,
                    "currency": "HKD",
                }
            ]
        }
        out = _normalize_accounts_sheet_payload(body)
        self.assertNotIn("lastStatementAmount", out[0])

    def test_normalize_rejects_non_string_description(self) -> None:
        body = {
            "accountRecords": [
                {
                    "id": "a1",
                    "description": 99,
                    "accountType": "Bank Account",
                    "billingCycleDay": 1,
                    "recordedValue": 1,
                    "currency": "HKD",
                }
            ]
        }
        with self.assertRaises(ValueError):
            _normalize_accounts_sheet_payload(body)

    def test_normalize_rejects_billing_day_zero(self) -> None:
        body = {
            "accountRecords": [
                {
                    "id": "a1",
                    "accountType": "Bank Account",
                    "billingCycleDay": 0,
                    "recordedValue": 1,
                    "currency": "HKD",
                }
            ]
        }
        with self.assertRaises(ValueError):
            _normalize_accounts_sheet_payload(body)

    def test_sanitize_keeps_last_updated(self) -> None:
        raw = [
            {
                "id": "a1",
                "accountType": "Debit Card",
                "billingCycleDay": 3,
                "recordedValue": 50,
                "currency": "USD",
                "lastUpdated": "2024-06-15",
            }
        ]
        out = _sanitize_accounts_records_list(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["lastUpdated"], "2024-06-15")
        self.assertEqual(out[0]["description"], "")
        self.assertNotIn("lastStatementAmount", out[0])

    def test_sanitize_credit_card_includes_last_statement_amount(self) -> None:
        raw = [
            {
                "id": "a1",
                "accountType": "Credit Card",
                "billingCycleDay": 3,
                "recordedValue": 50,
                "lastStatementAmount": 120.5,
                "currency": "USD",
            }
        ]
        out = _sanitize_accounts_records_list(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["lastStatementAmount"], 120.5)


class TestLiabilitiesSheetPayload(unittest.TestCase):
    def _row(self, **overrides: object) -> dict:
        base: dict = {
            "id": "l1",
            "description": "HSBC UK mortgage",
            "liabilityType": "Mortgage",
            "outstandingBalance": 150000.0,
            "currency": "GBP",
        }
        base.update(overrides)
        return base

    def test_normalize_valid(self) -> None:
        out = _normalize_liabilities_sheet_payload({"liabilityRecords": [self._row()]})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["description"], "HSBC UK mortgage")
        self.assertEqual(out[0]["liabilityType"], "Mortgage")
        self.assertEqual(out[0]["outstandingBalance"], 150000.0)
        self.assertEqual(out[0]["currency"], "GBP")
        self.assertNotIn("interestRatePercent", out[0])
        self.assertNotIn("relatedHouse", out[0])

    def test_normalize_optional_rate_and_house(self) -> None:
        out = _normalize_liabilities_sheet_payload(
            {
                "liabilityRecords": [
                    self._row(interestRatePercent=4.25, relatedHouse="hillmarton")
                ]
            }
        )
        self.assertEqual(out[0]["interestRatePercent"], 4.25)
        self.assertEqual(out[0]["relatedHouse"], "hillmarton")

    def test_normalize_rejects_bad_liability_type(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_liabilities_sheet_payload(
                {"liabilityRecords": [self._row(liabilityType="IOU")]}
            )

    def test_normalize_requires_description(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_liabilities_sheet_payload(
                {"liabilityRecords": [self._row(description="  ")]}
            )

    def test_normalize_rejects_negative_balance(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_liabilities_sheet_payload(
                {"liabilityRecords": [self._row(outstandingBalance=-1.0)]}
            )

    def test_normalize_rejects_bad_rate(self) -> None:
        for bad in (-0.1, 100.5, "abc", True):
            with self.assertRaises(ValueError):
                _normalize_liabilities_sheet_payload(
                    {"liabilityRecords": [self._row(interestRatePercent=bad)]}
                )

    def test_normalize_rejects_unknown_house(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_liabilities_sheet_payload(
                {"liabilityRecords": [self._row(relatedHouse="atlantis")]}
            )

    def test_normalize_rejects_unsupported_currency(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_liabilities_sheet_payload(
                {"liabilityRecords": [self._row(currency="JPY")]}
            )

    def test_normalize_ignores_client_last_updated(self) -> None:
        out = _normalize_liabilities_sheet_payload(
            {"liabilityRecords": [self._row(lastUpdated="2020-01-01")]}
        )
        self.assertNotIn("lastUpdated", out[0])

    def test_sanitize_keeps_valid_rows_and_last_updated(self) -> None:
        rows = [
            self._row(lastUpdated="2026-01-05", interestRatePercent=3.5),
            {"id": "", "description": "x", "liabilityType": "Loan"},
            self._row(id="l2", liabilityType="IOU"),
        ]
        out = _sanitize_liabilities_records_list(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["lastUpdated"], "2026-01-05")
        self.assertEqual(out[0]["interestRatePercent"], 3.5)

    def test_sanitize_drops_negative_balance(self) -> None:
        out = _sanitize_liabilities_records_list([self._row(outstandingBalance=-5)])
        self.assertEqual(out, [])


class TestMergeLiabilitiesLastUpdated(unittest.TestCase):
    def _row(self, **overrides: object) -> dict:
        base: dict = {
            "id": "l1",
            "description": "Citi HK mortgage",
            "liabilityType": "Mortgage",
            "outstandingBalance": 4000000.0,
            "currency": "HKD",
        }
        base.update(overrides)
        return base

    def test_new_id_gets_today(self) -> None:
        out = _merge_liabilities_last_updated([self._row()], [], today_iso="2026-01-10")
        self.assertEqual(out[0]["lastUpdated"], "2026-01-10")

    def test_unchanged_preserves_last_updated(self) -> None:
        existing = [self._row(lastUpdated="2025-03-01")]
        out = _merge_liabilities_last_updated(
            [self._row()], existing, today_iso="2026-01-10"
        )
        self.assertEqual(out[0]["lastUpdated"], "2025-03-01")

    def test_balance_change_gets_today(self) -> None:
        existing = [self._row(lastUpdated="2025-03-01")]
        out = _merge_liabilities_last_updated(
            [self._row(outstandingBalance=3900000.0)],
            existing,
            today_iso="2026-01-10",
        )
        self.assertEqual(out[0]["lastUpdated"], "2026-01-10")

    def test_rate_change_gets_today(self) -> None:
        existing = [self._row(lastUpdated="2025-03-01", interestRatePercent=2.0)]
        out = _merge_liabilities_last_updated(
            [self._row(interestRatePercent=2.5)], existing, today_iso="2026-01-10"
        )
        self.assertEqual(out[0]["lastUpdated"], "2026-01-10")


class TestMergeAccountsLastUpdated(unittest.TestCase):
    def test_new_id_gets_today(self) -> None:
        normalized = [
            {
                "id": "n1",
                "accountType": "Bank Account",
                "billingCycleDay": 1,
                "recordedValue": 100.0,
                "currency": "HKD",
            }
        ]
        out = _merge_accounts_last_updated(normalized, [], today_iso="2026-01-10")
        self.assertEqual(out[0]["lastUpdated"], "2026-01-10")

    def test_unchanged_preserves_last_updated(self) -> None:
        normalized = [
            {
                "id": "a1",
                "accountType": "Credit Card",
                "billingCycleDay": 10,
                "recordedValue": 1.0,
                "currency": "HKD",
            }
        ]
        existing = [
            {
                "id": "a1",
                "accountType": "Credit Card",
                "billingCycleDay": 10,
                "recordedValue": 1.0,
                "currency": "HKD",
                "lastUpdated": "2025-03-01",
            }
        ]
        out = _merge_accounts_last_updated(normalized, existing, today_iso="2026-01-10")
        self.assertEqual(out[0]["lastUpdated"], "2025-03-01")

    def test_changed_row_gets_today(self) -> None:
        normalized = [
            {
                "id": "a1",
                "accountType": "Credit Card",
                "billingCycleDay": 11,
                "recordedValue": 1.0,
                "currency": "HKD",
            }
        ]
        existing = [
            {
                "id": "a1",
                "accountType": "Credit Card",
                "billingCycleDay": 10,
                "recordedValue": 1.0,
                "currency": "HKD",
                "lastUpdated": "2025-03-01",
            }
        ]
        out = _merge_accounts_last_updated(normalized, existing, today_iso="2026-01-10")
        self.assertEqual(out[0]["lastUpdated"], "2026-01-10")

    def test_description_change_updates_last_updated(self) -> None:
        normalized = [
            {
                "id": "a1",
                "description": "Renamed account",
                "accountType": "Credit Card",
                "billingCycleDay": 10,
                "recordedValue": 1.0,
                "currency": "HKD",
            }
        ]
        existing = [
            {
                "id": "a1",
                "description": "",
                "accountType": "Credit Card",
                "billingCycleDay": 10,
                "recordedValue": 1.0,
                "currency": "HKD",
                "lastUpdated": "2025-03-01",
            }
        ]
        out = _merge_accounts_last_updated(normalized, existing, today_iso="2026-01-10")
        self.assertEqual(out[0]["lastUpdated"], "2026-01-10")

    def test_last_statement_change_updates_last_updated(self) -> None:
        normalized = [
            {
                "id": "a1",
                "accountType": "Credit Card",
                "billingCycleDay": 10,
                "recordedValue": 1.0,
                "lastStatementAmount": 500.0,
                "currency": "HKD",
            }
        ]
        existing = [
            {
                "id": "a1",
                "accountType": "Credit Card",
                "billingCycleDay": 10,
                "recordedValue": 1.0,
                "lastStatementAmount": 0.0,
                "currency": "HKD",
                "lastUpdated": "2025-03-01",
            }
        ]
        out = _merge_accounts_last_updated(normalized, existing, today_iso="2026-01-10")
        self.assertEqual(out[0]["lastUpdated"], "2026-01-10")


class TestLoadInvestmentRecords(unittest.TestCase):
    def test_returns_rows_when_dynamo_item_has_records(self) -> None:
        table = MagicMock()
        table.get_item.return_value = {
            "Item": {
                "pk": "FINANCE#sheet#investments",
                "sk": "STATE",
                "records": [
                    {
                        "id": "x1",
                        "category": "ETF",
                        "assetType": "Liquid",
                        "provider": "Broker",
                        "principalAmount": 42.5,
                        "currency": "HKD",
                    }
                ],
            }
        }
        out = _load_investment_records(table)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "x1")
        self.assertEqual(out[0]["principalAmount"], 42.5)


class TestLedgerSheetPayload(unittest.TestCase):
    def test_income_valid(self) -> None:
        body = {
            "incomeRecords": [
                {
                    "id": "a",
                    "category": "Rent",
                    "description": "Room sublet",
                    "amount": 500.5,
                    "currency": "GBP",
                }
            ]
        }
        out = _normalize_ledger_sheet_payload(
            body,
            body_key="incomeRecords",
            categories=INCOME_RECORD_CATEGORIES,
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["category"], "Rent")
        self.assertEqual(out[0]["amount"], 500.5)
        self.assertEqual(out[0]["amountPeriod"], "month")
        self.assertNotIn("relatedHouse", out[0])

    def test_income_amount_period_year(self) -> None:
        body = {
            "incomeRecords": [
                {
                    "id": "a",
                    "category": "Rent",
                    "description": "Annual",
                    "amount": 12000,
                    "currency": "GBP",
                    "amountPeriod": "year",
                }
            ]
        }
        out = _normalize_ledger_sheet_payload(
            body,
            body_key="incomeRecords",
            categories=INCOME_RECORD_CATEGORIES,
        )
        self.assertEqual(out[0]["amountPeriod"], "year")

    def test_income_related_house(self) -> None:
        body = {
            "incomeRecords": [
                {
                    "id": "a",
                    "category": "Rent",
                    "description": "Room sublet",
                    "amount": 500.5,
                    "currency": "GBP",
                    "relatedHouse": "morrison",
                }
            ]
        }
        out = _normalize_ledger_sheet_payload(
            body,
            body_key="incomeRecords",
            categories=INCOME_RECORD_CATEGORIES,
        )
        self.assertEqual(out[0]["relatedHouse"], "morrison")
        self.assertEqual(out[0]["amountPeriod"], "month")

    def test_income_invalid_amount_period(self) -> None:
        body = {
            "incomeRecords": [
                {
                    "id": "a",
                    "category": "Rent",
                    "description": "x",
                    "amount": 1,
                    "currency": "HKD",
                    "amountPeriod": "weekly",
                }
            ]
        }
        with self.assertRaises(ValueError) as ctx:
            _normalize_ledger_sheet_payload(
                body, body_key="incomeRecords", categories=INCOME_RECORD_CATEGORIES
            )
        self.assertIn("amountPeriod", str(ctx.exception))

    def test_income_invalid_related_house(self) -> None:
        body = {
            "incomeRecords": [
                {
                    "id": "a",
                    "category": "Rent",
                    "description": "x",
                    "amount": 1,
                    "currency": "HKD",
                    "relatedHouse": "villa",
                }
            ]
        }
        with self.assertRaises(ValueError) as ctx:
            _normalize_ledger_sheet_payload(
                body, body_key="incomeRecords", categories=INCOME_RECORD_CATEGORIES
            )
        self.assertIn("relatedHouse", str(ctx.exception))

    def test_income_invalid_category(self) -> None:
        body = {
            "incomeRecords": [
                {
                    "id": "a",
                    "category": "Bonus",
                    "description": "x",
                    "amount": 1,
                    "currency": "HKD",
                }
            ]
        }
        with self.assertRaises(ValueError):
            _normalize_ledger_sheet_payload(
                body, body_key="incomeRecords", categories=INCOME_RECORD_CATEGORIES
            )

    def test_income_missing_body_key(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_ledger_sheet_payload(
                {}, body_key="incomeRecords", categories=INCOME_RECORD_CATEGORIES
            )

    def test_expense_valid(self) -> None:
        body = {
            "expenseRecords": [
                {
                    "id": "e1",
                    "category": "Utility",
                    "description": "Electric",
                    "amount": 88,
                    "currency": "HKD",
                }
            ]
        }
        out = _normalize_ledger_sheet_payload(
            body,
            body_key="expenseRecords",
            categories=EXPENSE_RECORD_CATEGORIES,
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["category"], "Utility")
        self.assertEqual(out[0]["amountPeriod"], "month")
        self.assertNotIn("isTax", out[0])
        self.assertFalse(out[0].get("isAllocate"))

    def test_income_classification_flags(self) -> None:
        body = {
            "incomeRecords": [
                {
                    "id": "a",
                    "category": "Salary",
                    "description": "Pay",
                    "amount": 100,
                    "currency": "HKD",
                    "isTax": True,
                    "isSaving": False,
                    "isInvestment": True,
                }
            ]
        }
        out = _normalize_ledger_sheet_payload(
            body,
            body_key="incomeRecords",
            categories=INCOME_RECORD_CATEGORIES,
        )
        self.assertTrue(out[0]["isTax"])
        self.assertFalse(out[0]["isSaving"])
        self.assertTrue(out[0]["isInvestment"])

    def test_income_classification_flag_invalid_type(self) -> None:
        body = {
            "incomeRecords": [
                {
                    "id": "a",
                    "category": "Salary",
                    "description": "Pay",
                    "amount": 100,
                    "currency": "HKD",
                    "isTax": "yes",
                }
            ]
        }
        with self.assertRaises(ValueError) as ctx:
            _normalize_ledger_sheet_payload(
                body,
                body_key="incomeRecords",
                categories=INCOME_RECORD_CATEGORIES,
            )
        self.assertIn("isTax", str(ctx.exception))

    def test_expense_allocate_flag_true(self) -> None:
        body = {
            "expenseRecords": [
                {
                    "id": "e1",
                    "category": "Utility",
                    "description": "Electric",
                    "amount": 88,
                    "currency": "HKD",
                    "isAllocate": True,
                }
            ]
        }
        out = _normalize_ledger_sheet_payload(
            body,
            body_key="expenseRecords",
            categories=EXPENSE_RECORD_CATEGORIES,
        )
        self.assertTrue(out[0]["isAllocate"])

    def test_expense_allocate_flag_invalid_type(self) -> None:
        body = {
            "expenseRecords": [
                {
                    "id": "e1",
                    "category": "Utility",
                    "description": "Electric",
                    "amount": 88,
                    "currency": "HKD",
                    "isAllocate": "yes",
                }
            ]
        }
        with self.assertRaises(ValueError) as ctx:
            _normalize_ledger_sheet_payload(
                body,
                body_key="expenseRecords",
                categories=EXPENSE_RECORD_CATEGORIES,
            )
        self.assertIn("isAllocate", str(ctx.exception))

    def test_normalize_allocations_empty_when_none_tagged(self) -> None:
        out = _normalize_allocations_sheet_payload(
            {"allocationRecords": []}, frozenset()
        )
        self.assertEqual(out, [])

    def test_normalize_allocations_rejects_nonempty_when_none_tagged(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_allocations_sheet_payload(
                {"allocationRecords": [{"expenseId": "x", "accumulatedAmount": 0}]},
                frozenset(),
            )

    def test_normalize_allocations_full_match(self) -> None:
        body = {
            "allocationRecords": [
                {"expenseId": "a", "accumulatedAmount": 0},
                {"expenseId": "b", "accumulatedAmount": 12.5},
            ]
        }
        out = _normalize_allocations_sheet_payload(body, frozenset({"a", "b"}))
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1]["accumulatedAmount"], 12.5)

    def test_normalize_allocations_rejects_missing_row(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_allocations_sheet_payload(
                {"allocationRecords": [{"expenseId": "a", "accumulatedAmount": 0}]},
                frozenset({"a", "b"}),
            )

    def test_normalize_allocations_rejects_unknown_expense_id(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_allocations_sheet_payload(
                {
                    "allocationRecords": [
                        {"expenseId": "a", "accumulatedAmount": 0},
                        {"expenseId": "z", "accumulatedAmount": 0},
                    ]
                },
                frozenset({"a"}),
            )

    def test_normalize_allocations_custom_only(self) -> None:
        eid = f"__custom__{uuid.uuid4()}"
        body = {
            "allocationRecords": [
                {
                    "expenseId": eid,
                    "description": "Slush fund",
                    "currency": "HKD",
                    "accumulatedAmount": 50,
                }
            ]
        }
        out = _normalize_allocations_sheet_payload(body, frozenset())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["description"], "Slush fund")
        self.assertEqual(out[0]["currency"], "HKD")

    def test_normalize_allocations_rejects_bad_custom_id(self) -> None:
        body = {
            "allocationRecords": [
                {
                    "expenseId": "__custom__not-a-uuid",
                    "description": "x",
                    "currency": "HKD",
                    "accumulatedAmount": 1,
                }
            ]
        }
        with self.assertRaises(ValueError):
            _normalize_allocations_sheet_payload(body, frozenset())

    def test_normalize_allocations_custom_is_income_requires_monthly(self) -> None:
        eid = f"__custom__{uuid.uuid4()}"
        with self.assertRaises(ValueError) as ctx:
            _normalize_allocations_sheet_payload(
                {
                    "allocationRecords": [
                        {
                            "expenseId": eid,
                            "description": "Side",
                            "currency": "HKD",
                            "accumulatedAmount": 1,
                            "isIncome": True,
                        }
                    ]
                },
                frozenset(),
            )
        self.assertIn("allocationIncomeMonthly", str(ctx.exception))

    def test_normalize_allocations_custom_is_income_ok(self) -> None:
        eid = f"__custom__{uuid.uuid4()}"
        body = {
            "allocationRecords": [
                {
                    "expenseId": eid,
                    "description": "Side",
                    "currency": "HKD",
                    "accumulatedAmount": 1,
                    "isIncome": True,
                    "allocationIncomeMonthly": 40,
                }
            ]
        }
        out = _normalize_allocations_sheet_payload(body, frozenset())
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].get("isIncome"))
        self.assertEqual(out[0].get("allocationIncomeMonthly"), 40.0)

    def test_normalize_allocations_linked_is_income_flag(self) -> None:
        body = {
            "allocationRecords": [
                {"expenseId": "a", "accumulatedAmount": 0, "isIncome": True},
                {"expenseId": "b", "accumulatedAmount": 0},
            ]
        }
        out = _normalize_allocations_sheet_payload(body, frozenset({"a", "b"}))
        by_id = {r["expenseId"]: r for r in out}
        self.assertTrue(by_id["a"].get("isIncome"))
        self.assertFalse(by_id["b"].get("isIncome", False))

    def test_normalize_allocations_linked_is_pension_flag(self) -> None:
        body = {
            "allocationRecords": [
                {"expenseId": "a", "accumulatedAmount": 0, "isPension": True},
                {"expenseId": "b", "accumulatedAmount": 0},
            ]
        }
        out = _normalize_allocations_sheet_payload(body, frozenset({"a", "b"}))
        by_id = {r["expenseId"]: r for r in out}
        self.assertTrue(by_id["a"].get("isPension"))
        self.assertFalse(by_id["b"].get("isPension", False))

    def test_merge_allocation_linked_updates_last_updated_on_is_income_toggle(self) -> None:
        existing = [{"expenseId": "a", "accumulatedAmount": 1.0, "lastUpdated": "2026-01-01"}]
        normalized = [{"expenseId": "a", "accumulatedAmount": 1.0, "isIncome": True}]
        out = _merge_allocation_stored_last_updated(
            normalized, existing, today_iso="2026-02-02"
        )
        self.assertEqual(out[0]["lastUpdated"], "2026-02-02")
        self.assertTrue(out[0].get("isIncome"))

    def test_merge_allocation_linked_updates_last_updated_on_is_pension_toggle(self) -> None:
        existing = [{"expenseId": "a", "accumulatedAmount": 1.0, "lastUpdated": "2026-01-01"}]
        normalized = [{"expenseId": "a", "accumulatedAmount": 1.0, "isPension": True}]
        out = _merge_allocation_stored_last_updated(
            normalized, existing, today_iso="2026-02-02"
        )
        self.assertEqual(out[0]["lastUpdated"], "2026-02-02")
        self.assertTrue(out[0].get("isPension"))

    def test_normalize_allocations_mixed_linked_and_custom(self) -> None:
        eid = f"__custom__{uuid.uuid4()}"
        body = {
            "allocationRecords": [
                {"expenseId": "a", "accumulatedAmount": 0},
                {
                    "expenseId": eid,
                    "description": "Extra",
                    "currency": "USD",
                    "accumulatedAmount": 10,
                },
            ]
        }
        out = _normalize_allocations_sheet_payload(body, frozenset({"a"}))
        self.assertEqual(len(out), 2)

    def test_merge_allocation_updates_last_updated_on_amount_change(self) -> None:
        existing = [{"expenseId": "a", "accumulatedAmount": 1.0, "lastUpdated": "2026-01-01"}]
        normalized = [{"expenseId": "a", "accumulatedAmount": 2.0}]
        out = _merge_allocation_stored_last_updated(
            normalized, existing, today_iso="2026-02-02"
        )
        self.assertEqual(out[0]["lastUpdated"], "2026-02-02")

    def test_merge_allocation_keeps_last_updated_when_amount_unchanged(self) -> None:
        out = _merge_allocation_stored_last_updated(
            [{"expenseId": "a", "accumulatedAmount": 2.0}],
            [{"expenseId": "a", "accumulatedAmount": 2.0, "lastUpdated": "2026-01-01"}],
            today_iso="2026-02-02",
        )
        self.assertEqual(out[0]["lastUpdated"], "2026-01-01")

    def test_sanitize_expense_allocate_flag(self) -> None:
        raw = [
            {
                "id": "e1",
                "category": "Utility",
                "description": "x",
                "amount": 1,
                "currency": "HKD",
                "isAllocate": True,
            }
        ]
        out = _sanitize_ledger_records_list(
            raw, EXPENSE_RECORD_CATEGORIES, include_expense_flags=True
        )
        self.assertTrue(out[0]["isAllocate"])

    def test_derived_expense_tax_on_income_row(self) -> None:
        income = [
            {
                "id": "1",
                "category": "Salary",
                "description": "Pay",
                "amount": 1000,
                "currency": "HKD",
                "amountPeriod": "month",
                "relatedHouse": "hillmarton",
                "isTax": True,
                "isSaving": False,
                "isInvestment": False,
            }
        ]
        perc = {
            **DEFAULT_EXPENSE_INCOME_ALLOCATION_PERCENTAGES,
            "taxOnIncomePercent": 10.0,
        }
        rows = _derived_expense_rows_from_tagged_income(income, perc)
        match = [r for r in rows if r["id"] == "__derived__tax-on-income__hillmarton__HKD"]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["amount"], 100.0)

    def test_build_allocation_response_includes_derived(self) -> None:
        income = [
            {
                "id": "1",
                "category": "Salary",
                "description": "Pay",
                "amount": 800,
                "currency": "USD",
                "amountPeriod": "month",
                "relatedHouse": "morrison",
                "isTax": False,
                "isSaving": True,
                "isInvestment": False,
            }
        ]
        perc = {
            **DEFAULT_EXPENSE_INCOME_ALLOCATION_PERCENTAGES,
            "savingOnIncomePercent": 25.0,
        }
        out = _build_allocation_records_for_response([], [], income, perc)
        match = [
            r
            for r in out
            if r["expenseId"] == "__derived__saving-on-income__morrison__USD"
        ]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["monthlyAmount"], 200.0)
        self.assertEqual(match[0]["accumulatedAmount"], 0.0)

    def test_expense_helper_category(self) -> None:
        body = {
            "expenseRecords": [
                {
                    "id": "e1",
                    "category": "Helper",
                    "description": "Domestic help",
                    "amount": 5000,
                    "currency": "HKD",
                }
            ]
        }
        out = _normalize_ledger_sheet_payload(
            body,
            body_key="expenseRecords",
            categories=EXPENSE_RECORD_CATEGORIES,
        )
        self.assertEqual(out[0]["category"], "Helper")

    def test_sanitize_income_flags_coerces_non_bool(self) -> None:
        raw = [
            {
                "id": "a",
                "category": "Salary",
                "description": "Pay",
                "amount": 1,
                "currency": "HKD",
                "isTax": True,
                "isSaving": "no",
            }
        ]
        out = _sanitize_ledger_records_list(
            raw, INCOME_RECORD_CATEGORIES, include_income_flags=True
        )
        self.assertTrue(out[0]["isTax"])
        self.assertFalse(out[0]["isSaving"])
        self.assertFalse(out[0]["isInvestment"])
    def test_image_types_allowed(self) -> None:
        self.assertTrue(_is_allowed_upload_content_type("image/png"))
        self.assertTrue(_is_allowed_upload_content_type("image/jpeg"))
        self.assertTrue(_is_allowed_upload_content_type("IMAGE/WEBP"))

    def test_pdf_allowed(self) -> None:
        self.assertTrue(_is_allowed_upload_content_type("application/pdf"))
        self.assertTrue(_is_allowed_upload_content_type("Application/PDF"))

    def test_other_types_rejected(self) -> None:
        self.assertFalse(_is_allowed_upload_content_type("application/json"))
        self.assertFalse(_is_allowed_upload_content_type("text/plain"))
        self.assertFalse(_is_allowed_upload_content_type(""))
        self.assertFalse(_is_allowed_upload_content_type(None))  # type: ignore[arg-type]


class TestExpenseIncomeAllocationPercents(unittest.TestCase):
    def test_clamps_and_defaults(self) -> None:
        out = _sanitize_expense_income_allocation_percentages(
            {
                "taxOnIncomePercent": -1,
                "investmentOnIncomePercent": 150,
                "savingOnIncomePercent": 12.5,
            }
        )
        self.assertEqual(out["taxOnIncomePercent"], 0.0)
        self.assertEqual(out["investmentOnIncomePercent"], 100.0)
        self.assertEqual(out["savingOnIncomePercent"], 12.5)

    def test_non_object_returns_defaults(self) -> None:
        out = _sanitize_expense_income_allocation_percentages(None)
        self.assertEqual(out["taxOnIncomePercent"], 0.0)
        self.assertEqual(out["investmentOnIncomePercent"], 0.0)
        self.assertEqual(out["savingOnIncomePercent"], 0.0)


class TestUtcIsoZ(unittest.TestCase):
    def test_naive_treated_as_utc(self) -> None:
        self.assertEqual(
            _utc_iso_z(datetime(2026, 5, 9, 12, 0, 0, 123000)),
            "2026-05-09T12:00:00.123Z",
        )

    def test_offset_converts_to_utc(self) -> None:
        dt = datetime(
            2026,
            5,
            9,
            14,
            30,
            0,
            0,
            tzinfo=timezone(timedelta(hours=2)),
        )
        self.assertEqual(_utc_iso_z(dt), "2026-05-09T12:30:00.000Z")


class TestStatementBasenameDuplicate(unittest.TestCase):
    def test_empty_lines(self) -> None:
        self.assertFalse(
            _statement_basename_already_imported({"lines": []}, "jan.pdf")
        )

    def test_matches_basename_only(self) -> None:
        house = {
            "lines": [
                {
                    "id": "a",
                    "sourceAssetKey": "uploads/u1/x/BankStmt.pdf",
                }
            ]
        }
        self.assertTrue(
            _statement_basename_already_imported(house, "BankStmt.pdf")
        )
        self.assertFalse(
            _statement_basename_already_imported(house, "Other.pdf")
        )

    def test_basename_in_source_asset_keys_array(self) -> None:
        house = {
            "lines": [
                {
                    "id": "a",
                    "sourceAssetKeys": [
                        "uploads/u1/x/BankStmt.pdf",
                        "uploads/u2/y/Other.pdf",
                    ],
                }
            ]
        }
        self.assertTrue(
            _statement_basename_already_imported(house, "Other.pdf")
        )

    def test_case_sensitive(self) -> None:
        house = {
            "lines": [{"id": "a", "sourceAssetKey": "uploads/u/x/report.PDF"}]
        }
        self.assertTrue(
            _statement_basename_already_imported(house, "report.PDF")
        )
        self.assertFalse(
            _statement_basename_already_imported(house, "report.pdf")
        )

    def test_ignores_manual_lines(self) -> None:
        house = {
            "lines": [
                {
                    "id": "a",
                    "dateUtc": "2026-05-08T12:00:00.000Z",
                    "type": "income",
                    "description": "Rent",
                    "netAmount": 1,
                    "vat": 0,
                    "grossAmount": 1,
                    "currency": "GBP",
                }
            ]
        }
        self.assertFalse(
            _statement_basename_already_imported(house, "Rent.pdf")
        )


class TestParseStatementHousePath(unittest.TestCase):
    def test_path_param(self) -> None:
        ev = {"pathParameters": {"house": "Hillmarton"}}
        self.assertEqual(
            _path_finance_house_for_parse(ev, "/finance/hillmarton/parse-statement"),
            "hillmarton",
        )

    def test_path_split(self) -> None:
        self.assertEqual(
            _path_finance_house_for_parse(
                {}, "/finance/morrison/parse-statement"
            ),
            "morrison",
        )

    def test_invalid_path(self) -> None:
        self.assertIsNone(
            _path_finance_house_for_parse({}, "/finance/morrison")
        )
        self.assertIsNone(_path_finance_house_for_parse({}, "/something"))


class TestParseJobPath(unittest.TestCase):
    def test_path_params(self) -> None:
        ev = {
            "pathParameters": {
                "house": "Morrison",
                "jobId": "abc123",
            }
        }
        h, j = _path_finance_parse_job(
            ev, "/finance/morrison/parse-statement/jobs/abc123"
        )
        self.assertEqual((h, j), ("morrison", "abc123"))

    def test_path_split(self) -> None:
        h, j = _path_finance_parse_job(
            {},
            "/finance/hillmarton/parse-statement/jobs/j1",
        )
        self.assertEqual((h, j), ("hillmarton", "j1"))

    def test_invalid(self) -> None:
        self.assertEqual(_path_finance_parse_job({}, "/finance/morrison"), (None, None))


class TestParseJobPublicDoc(unittest.TestCase):
    def test_pending_and_failed_message(self) -> None:
        from handler import _parse_job_public_doc

        self.assertEqual(_parse_job_public_doc({"status": "pending"}), {"status": "pending"})
        self.assertEqual(
            _parse_job_public_doc({"status": "failed", "errorMessage": "bad"})[
                "message"
            ],
            "bad",
        )


class TestFinalizeStuckProcessing(unittest.TestCase):
    def test_skips_finalize_when_processing_recent(self) -> None:
        from handler import _finalize_stuck_processing_job

        table = MagicMock()
        doc = {"status": "processing", "updatedAt": "2099-01-01T00:00:00.000Z"}
        out = _finalize_stuck_processing_job(
            table, {"pk": "PARSE_JOB#x", "sk": "META"}, doc
        )
        self.assertEqual(out["status"], "processing")
        table.put_item.assert_not_called()

    def test_finalizes_stuck_processing_job(self) -> None:
        from handler import _finalize_stuck_processing_job

        table = MagicMock()
        stale = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3] + "Z"
        doc = {"status": "processing", "updatedAt": stale}
        out = _finalize_stuck_processing_job(
            table, {"pk": "PARSE_JOB#y", "sk": "META"}, doc
        )
        self.assertEqual(out["status"], "failed")
        table.put_item.assert_called_once()


class TestParseJobsImportBindings(unittest.TestCase):
    """Guard against import-hygiene cleanups dropping in-use names.

    ``timedelta``, ``ClientError`` and ``_log_event`` are referenced inside
    ``parse_jobs`` but only on code paths the worker hits at runtime, so a stray
    "unused import" removal silently breaks every async parse job until it runs.
    """

    def test_runtime_names_are_bound(self) -> None:
        import parse_jobs as parse_jobs_mod

        for name in ("timedelta", "ClientError", "_log_event"):
            self.assertTrue(
                hasattr(parse_jobs_mod, name),
                f"parse_jobs must import {name}",
            )

    def test_stale_cutoff_uses_timedelta(self) -> None:
        import parse_jobs as parse_jobs_mod

        with patch.dict("os.environ", {"PARSE_JOB_STALE_SECONDS": "120"}):
            cutoff = parse_jobs_mod._parse_job_stale_cutoff_iso()
        self.assertTrue(cutoff.endswith("Z"))


class TestLambdaInternalAsyncDispatch(unittest.TestCase):
    def test_dispatches_internal_worker(self) -> None:
        import handler as handler_mod

        captured: list[dict] = []

        def capture(payload: dict) -> None:
            captured.append(payload)

        import parse_jobs as parse_jobs_mod

        with patch.object(
            parse_jobs_mod, "_handle_parse_statement_async_worker", side_effect=capture
        ):
            out = handler_mod.lambda_handler(
                {"internal": "parse_statement_async", "jobId": "jid"},
                None,
            )
        self.assertEqual(out, {})
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].get("jobId"), "jid")


class TestFxV2RatesQuery(unittest.TestCase):
    def test_requires_base(self) -> None:
        self.assertEqual(_parse_fx_v2_rates_query(None), "base is required")
        self.assertEqual(_parse_fx_v2_rates_query({}), "base is required")
        self.assertEqual(
            _parse_fx_v2_rates_query({"quotes": "USD"}), "base is required"
        )

    def test_supported_and_sorted(self) -> None:
        base, need = _parse_fx_v2_rates_query({"base": "hkd", "quotes": "USD,EUR"})
        self.assertEqual(base, "HKD")
        self.assertEqual(need, ["EUR", "USD"])

    def test_drops_base_from_quotes(self) -> None:
        base, need = _parse_fx_v2_rates_query({"base": "HKD", "quotes": "HKD,USD"})
        self.assertEqual(base, "HKD")
        self.assertEqual(need, ["USD"])

    def test_accepts_any_three_letter_code(self) -> None:
        # Codes outside SUPPORTED_FINANCE_CURRENCIES (e.g. JPY, BTC) are
        # passed through; Frankfurter validates upstream.
        base, need = _parse_fx_v2_rates_query({"base": "HKD", "quotes": "JPY,BTC"})
        self.assertEqual(base, "HKD")
        self.assertEqual(need, ["BTC", "JPY"])

    def test_rejects_invalid_code_format(self) -> None:
        err = _parse_fx_v2_rates_query({"base": "HKD", "quotes": "US"})
        self.assertIsInstance(err, str)
        err2 = _parse_fx_v2_rates_query({"base": "HK1", "quotes": "USD"})
        self.assertIsInstance(err2, str)


class TestNormalizeFinanceQuoteSymbol(unittest.TestCase):
    def test_returns_none_for_empty(self) -> None:
        self.assertIsNone(_normalize_finance_quote_symbol(""))
        self.assertIsNone(_normalize_finance_quote_symbol("   "))

    def test_us_prefix_strips_to_bare_symbol(self) -> None:
        self.assertEqual(_normalize_finance_quote_symbol("US:TQQQ"), "TQQQ")
        self.assertEqual(
            _normalize_finance_quote_symbol("nasdaq:msft"), "MSFT"
        )
        self.assertEqual(_normalize_finance_quote_symbol("NYSE:SPY"), "SPY")

    def test_lse_maps_to_dot_l(self) -> None:
        self.assertEqual(_normalize_finance_quote_symbol("LON:VWRA"), "VWRA.L")
        self.assertEqual(_normalize_finance_quote_symbol("LSE:vwra"), "VWRA.L")

    def test_hkex_maps_to_dot_hk(self) -> None:
        self.assertEqual(_normalize_finance_quote_symbol("HK:0700"), "0700.HK")
        self.assertEqual(_normalize_finance_quote_symbol("HKG:0700"), "0700.HK")
        self.assertEqual(
            _normalize_finance_quote_symbol("HKEX:0700"), "0700.HK"
        )

    def test_other_exchange_prefixes(self) -> None:
        self.assertEqual(
            _normalize_finance_quote_symbol("TYO:7203"), "7203.T"
        )
        self.assertEqual(_normalize_finance_quote_symbol("ASX:CBA"), "CBA.AX")
        self.assertEqual(_normalize_finance_quote_symbol("TSX:RY"), "RY.TO")
        self.assertEqual(_normalize_finance_quote_symbol("SGX:D05"), "D05.SI")
        self.assertEqual(_normalize_finance_quote_symbol("PAR:MC"), "MC.PA")
        self.assertEqual(
            _normalize_finance_quote_symbol("XETRA:SAP"), "SAP.DE"
        )

    def test_unknown_prefix_passes_through_bare_symbol(self) -> None:
        self.assertEqual(
            _normalize_finance_quote_symbol("FOO:BAR"), "BAR"
        )

    def test_empty_after_prefix_is_invalid(self) -> None:
        self.assertIsNone(_normalize_finance_quote_symbol("US:"))

    def test_already_yahoo_native_passes_through(self) -> None:
        self.assertEqual(_normalize_finance_quote_symbol("VWRA.L"), "VWRA.L")
        self.assertEqual(
            _normalize_finance_quote_symbol("BTC-USD"), "BTC-USD"
        )

    def test_bare_short_token_treated_as_crypto(self) -> None:
        # 2-6 alpha letters with no separators → assume crypto and append -USD
        self.assertEqual(_normalize_finance_quote_symbol("BTC"), "BTC-USD")
        self.assertEqual(_normalize_finance_quote_symbol("eth"), "ETH-USD")
        self.assertEqual(_normalize_finance_quote_symbol("DOGE"), "DOGE-USD")

    def test_bare_long_or_mixed_token_passed_through(self) -> None:
        # 7+ chars or non-alpha → pass through uppercased
        self.assertEqual(
            _normalize_finance_quote_symbol("MICROSOFT"), "MICROSOFT"
        )
        self.assertEqual(_normalize_finance_quote_symbol("0700"), "0700")


class TestNormalizeYahooPriceCurrency(unittest.TestCase):
    def test_passes_through_normal_currency(self) -> None:
        self.assertEqual(
            _normalize_yahoo_price_currency(123.45, "USD"), (123.45, "USD")
        )
        self.assertEqual(
            _normalize_yahoo_price_currency(789.0, "hkd"), (789.0, "HKD")
        )

    def test_gbp_pence_normalized(self) -> None:
        # GBp / GBX → divide by 100 and report GBP
        price, ccy = _normalize_yahoo_price_currency(11750.0, "GBp")
        self.assertAlmostEqual(price, 117.5)
        self.assertEqual(ccy, "GBP")
        price2, ccy2 = _normalize_yahoo_price_currency(11750.0, "GBX")
        self.assertAlmostEqual(price2, 117.5)
        self.assertEqual(ccy2, "GBP")

    def test_zar_cents_and_ils_agorot_normalized(self) -> None:
        self.assertEqual(
            _normalize_yahoo_price_currency(1000.0, "ZAc"), (10.0, "ZAR")
        )
        self.assertEqual(
            _normalize_yahoo_price_currency(500.0, "ILA"), (5.0, "ILS")
        )

    def test_blank_currency_passes_through(self) -> None:
        self.assertEqual(
            _normalize_yahoo_price_currency(1.0, ""), (1.0, "")
        )


class TestParseFinanceQuotesQuery(unittest.TestCase):
    def test_requires_symbols(self) -> None:
        self.assertEqual(
            _parse_finance_quotes_query(None), "symbols is required"
        )
        self.assertEqual(
            _parse_finance_quotes_query({}), "symbols is required"
        )
        self.assertEqual(
            _parse_finance_quotes_query({"symbols": "  ,, "}),
            "symbols is required",
        )

    def test_normalizes_and_dedupes(self) -> None:
        out = _parse_finance_quotes_query(
            {"symbols": "US:TQQQ, BTC, BTC-USD ,LON:VWRA"}
        )
        self.assertIsInstance(out, tuple)
        pairs, _ = out  # type: ignore[misc]
        # BTC normalizes to BTC-USD which is already present, so dedup
        # keeps only the first occurrence.
        self.assertEqual(
            pairs,
            [
                ("US:TQQQ", "TQQQ"),
                ("BTC", "BTC-USD"),
                ("LON:VWRA", "VWRA.L"),
            ],
        )

    def test_rejects_too_many_symbols(self) -> None:
        symbols = ",".join(f"SYM{i}" for i in range(60))
        out = _parse_finance_quotes_query({"symbols": symbols})
        self.assertIsInstance(out, str)
        self.assertIn("At most", out)  # type: ignore[arg-type]

    def test_rejects_too_long_symbol(self) -> None:
        out = _parse_finance_quotes_query({"symbols": "X" * 64})
        self.assertIsInstance(out, str)


class TestPublicReadRoutes(unittest.TestCase):
    """Dispatch of /public/* routes guarded by the API key authorizer."""

    def setUp(self) -> None:
        import runtime

        self.table = MagicMock()
        self.table.get_item.return_value = {}
        self.table.scan.return_value = {"Items": []}
        patcher_ddb = patch.object(runtime, "_ddb")
        mock_ddb = patcher_ddb.start()
        self.addCleanup(patcher_ddb.stop)
        mock_ddb.Table.return_value = self.table
        patcher_env = patch.dict(
            "os.environ",
            {
                "RECORDS_TABLE_NAME": "records-test",
                "AUDIT_LOG_TABLE_NAME": "audit-test",
                "ASSETS_BUCKET_NAME": "assets-test",
            },
        )
        patcher_env.start()
        self.addCleanup(patcher_env.stop)

    @staticmethod
    def _event(
        path: str,
        method: str = "GET",
        key_ctx: dict | None = None,
    ) -> dict:
        request_context: dict = {
            "http": {"method": method, "path": path},
            "requestId": "req-public-1",
        }
        if key_ctx is not None:
            request_context["authorizer"] = {"lambda": key_ctx}
        return {"requestContext": request_context, "rawQueryString": ""}

    @staticmethod
    def _key_ctx() -> dict:
        return {"keyId": "k123", "label": "test", "scope": "read"}

    def test_missing_key_context_unauthorized(self) -> None:
        out = lambda_handler(self._event("/public/finance"), None)
        self.assertEqual(out["statusCode"], 401)

    def test_wrong_scope_unauthorized(self) -> None:
        ctx = {"keyId": "k123", "scope": "write"}
        out = lambda_handler(self._event("/public/finance", key_ctx=ctx), None)
        self.assertEqual(out["statusCode"], 401)

    def test_public_finance_returns_overview(self) -> None:
        out = lambda_handler(
            self._event("/public/finance", key_ctx=self._key_ctx()), None
        )
        self.assertEqual(out["statusCode"], 200)
        body = json.loads(out["body"])
        for key in (
            "hillmarton",
            "morrison",
            "incomeRecords",
            "expenseRecords",
            "investmentRecords",
            "savingsRecords",
            "pensionRecords",
            "accountRecords",
            "liabilityRecords",
            "allocationRecords",
        ):
            self.assertIn(key, body)

    def test_public_records_returns_items(self) -> None:
        out = lambda_handler(
            self._event("/public/records", key_ctx=self._key_ctx()), None
        )
        self.assertEqual(out["statusCode"], 200)
        body = json.loads(out["body"])
        self.assertEqual(body["items"], [])
        self.assertIsNone(body["nextCursor"])

    def test_unlisted_public_path_not_found(self) -> None:
        out = lambda_handler(
            self._event("/public/finance/hillmarton", key_ctx=self._key_ctx()),
            None,
        )
        self.assertEqual(out["statusCode"], 404)

    def test_non_get_method_not_found(self) -> None:
        out = lambda_handler(
            self._event("/public/finance", method="PUT", key_ctx=self._key_ctx()),
            None,
        )
        self.assertEqual(out["statusCode"], 404)

    def test_bare_public_prefix_not_found(self) -> None:
        out = lambda_handler(
            self._event("/public", key_ctx=self._key_ctx()), None
        )
        self.assertEqual(out["statusCode"], 404)

    def test_key_context_cannot_reach_admin_routes(self) -> None:
        # An API-key principal hitting a non-/public route has no JWT claims,
        # so the admin gate must reject it.
        out = lambda_handler(
            self._event("/finance", key_ctx=self._key_ctx()), None
        )
        self.assertEqual(out["statusCode"], 401)

    def test_admin_get_finance_still_works(self) -> None:
        event = self._event("/finance")
        event["requestContext"]["authorizer"] = {
            "jwt": {
                "claims": {"sub": "admin-sub", "cognito:groups": "[admin]"}
            }
        }
        out = lambda_handler(event, None)
        self.assertEqual(out["statusCode"], 200)
        self.assertIn("hillmarton", json.loads(out["body"]))


if __name__ == "__main__":
    unittest.main()
