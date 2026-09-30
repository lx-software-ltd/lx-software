"""Evolve Sprouts statement-book mirror (no AWS calls)."""

from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _install_stubs() -> None:
    sys.modules["boto3"] = MagicMock()

    class ClientError(Exception):
        pass

    botocore = types.ModuleType("botocore")
    exceptions = types.ModuleType("botocore.exceptions")
    exceptions.ClientError = ClientError
    botocore.exceptions = exceptions
    sys.modules["botocore"] = botocore
    sys.modules["botocore.exceptions"] = exceptions


_install_stubs()

import board_data_api  # noqa: E402
from dispatch import lambda_handler  # noqa: E402
import evolvesprouts_finance as es  # noqa: E402


class _MemTable:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict] = {}

    def get_item(self, Key: dict) -> dict:
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def put_item(self, Item: dict) -> None:
        self.items[(Item["pk"], Item["sk"])] = Item


def _rows(sql: str, _parameters: list | None) -> list[dict]:
    if "customer_payments" in sql:
        return [
            {
                "id": "p1",
                "direction": "inbound",
                "amount": 10,
                "currency": "HKD",
                "succeeded_at": "2026-05-01T12:00:00Z",
            },
            {
                "id": "r1",
                "direction": "refund",
                "amount": 2,
                "currency": "USD",
                "succeeded_at": "2026-05-02",
            },
            {
                "id": "bad",
                "direction": "inbound",
                "amount": 3,
                "currency": "JPY",
                "succeeded_at": "2026-05-03",
            },
            {
                "id": "zero",
                "direction": "inbound",
                "amount": 0,
                "currency": "HKD",
                "succeeded_at": "2026-05-03",
            },
        ]
    if "FROM expenses" in sql:
        return [
            {
                "id": "e1",
                "status": "submitted",
                "total": 8,
                "currency": "HKD",
                "invoice_date": "2026-04-01",
                "vendor_name": "Example Vendor",
                "invoice_number": "INV-9",
            },
            {
                "id": "e2",
                "status": "paid",
                "total": 5,
                "currency": "EUR",
                "paid_at": "2026-04-02",
                "vendor_name": "",
                "invoice_number": "",
            },
            {
                "id": "e3",
                "status": "submitted",
                "total": 4,
                "currency": "XXX",
                "invoice_date": "2026-04-03",
            },
        ]
    if "customer_invoices" in sql:
        return [
            {"currency": "HKD", "outstanding": 12.5, "n": 2},
            {"currency": "JPY", "outstanding": 9, "n": 1},
        ]
    return []


class TestEvolveSproutsMirror(unittest.TestCase):
    def setUp(self) -> None:
        self.table = _MemTable()
        self.env = patch.dict(
            "os.environ",
            {
                "EVOLVESPROUTS_CLUSTER_ARN": "arn:cluster",
                "EVOLVESPROUTS_DB_SECRET_ARN": "arn:secret",
                "EVOLVESPROUTS_DB_NAME": "evolvesprouts",
                "RECORDS_TABLE_NAME": "records-test",
            },
        )
        self.env.start()
        board_data_api.set_executor_for_tests(_rows)
        from decimal import Decimal

        self.table.items[("FINANCE#book#evolveSprouts", "STATE")] = {
            "pk": "FINANCE#book#evolveSprouts",
            "sk": "STATE",
            "defaultCurrency": "HKD",
            "float": {"amount": Decimal("0"), "currency": "HKD"},
            "lines": [
                {
                    "id": "manual-1",
                    "dateUtc": "2026-01-01T00:00:00.000Z",
                    "type": "income",
                    "description": "Kept",
                    "netAmount": Decimal("1"),
                    "vat": Decimal("0"),
                    "grossAmount": Decimal("1"),
                    "currency": "HKD",
                },
                {
                    "id": "es-pay-gone",
                    "dateUtc": "2026-01-01T00:00:00.000Z",
                    "type": "income",
                    "description": "Stale",
                    "netAmount": Decimal("9"),
                    "vat": Decimal("0"),
                    "grossAmount": Decimal("9"),
                    "currency": "HKD",
                    "source": "evolvesprouts",
                },
            ],
        }

    def tearDown(self) -> None:
        board_data_api.set_executor_for_tests(None)
        self.env.stop()

    def _book_lines(self) -> list[dict]:
        item = self.table.items[("FINANCE#book#evolveSprouts", "STATE")]
        return list(item["lines"])

    def test_sync_maps_cash_and_keeps_manual_lines(self) -> None:
        result = es.sync(self.table)
        self.assertTrue(result["ok"])
        self.assertEqual(result["submittedExpenses"], 1)
        self.assertEqual(result["paidExpenses"], 1)
        self.assertEqual(result["openInvoices"], 2)
        self.assertEqual(result["outstandingByCurrency"]["HKD"], 12.5)
        self.assertEqual(result["skippedUnsupportedCurrency"], 3)
        self.assertEqual(result["linesRemoved"], 1)
        by_id = {line["id"]: line for line in self._book_lines()}
        self.assertEqual(set(by_id), {"manual-1", "es-pay-p1", "es-ref-r1", "es-exp-e1", "es-exp-e2"})
        self.assertEqual(by_id["es-pay-p1"]["type"], "income")
        self.assertEqual(by_id["es-pay-p1"]["description"], "[evolve-sprouts] Payment p1")
        self.assertEqual(by_id["es-ref-r1"]["type"], "expenditure")
        self.assertEqual(by_id["es-ref-r1"]["currency"], "USD")
        self.assertEqual(by_id["es-exp-e1"]["description"], "[evolve-sprouts] Expense Example Vendor INV-9")
        self.assertEqual(by_id["es-exp-e2"]["description"], "[evolve-sprouts] Expense e2")
        self.assertEqual(by_id["es-pay-p1"]["source"], "evolvesprouts")
        self.assertNotIn("source", by_id["manual-1"])
        self.assertEqual(by_id["manual-1"]["description"], "Kept")

        again = es.sync(self.table)
        self.assertEqual(again["linesWritten"], 0)
        self.assertEqual(again["linesRemoved"], 0)
        self.assertEqual(
            {line["id"] for line in self._book_lines()},
            {"manual-1", "es-pay-p1", "es-ref-r1", "es-exp-e1", "es-exp-e2"},
        )
        summary = es.load_summary(self.table)
        self.assertEqual(summary["submittedExpenses"], 1)
        self.assertEqual(summary["paidExpenses"], 1)
        self.assertTrue(summary["configured"])

    def test_not_configured_skips_the_database(self) -> None:
        called = {"n": 0}

        def explode(sql: str, parameters: list | None) -> list[dict]:
            called["n"] += 1
            return []

        board_data_api.set_executor_for_tests(explode)
        with patch.dict(
            "os.environ",
            {"EVOLVESPROUTS_CLUSTER_ARN": "", "EVOLVESPROUTS_DB_SECRET_ARN": ""},
        ):
            result = es.sync(self.table)
        self.assertEqual(result["skipped"], "not_configured")
        self.assertFalse(result["configured"])
        self.assertEqual(called["n"], 0)
        self.assertEqual(self._book_lines()[0]["id"], "manual-1")


class TestEvolveSproutsRoutes(unittest.TestCase):
    def setUp(self) -> None:
        import runtime

        self.table = MagicMock()
        self.table.get_item.return_value = {}
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
                "EVOLVESPROUTS_CLUSTER_ARN": "",
                "EVOLVESPROUTS_DB_SECRET_ARN": "",
            },
        )
        patcher_env.start()
        self.addCleanup(patcher_env.stop)
        self.addCleanup(lambda: board_data_api.set_executor_for_tests(None))

    @staticmethod
    def _event(path: str, method: str = "GET", body: dict | None = None) -> dict:
        event: dict = {
            "requestContext": {
                "http": {"method": method, "path": path},
                "requestId": "req-es-1",
                "authorizer": {
                    "jwt": {"claims": {"sub": "admin-sub", "cognito:groups": "[admin]"}}
                },
            },
            "rawQueryString": "",
        }
        if body is not None:
            event["body"] = json.dumps(body)
        return event

    def test_summary_and_sync_when_unconfigured(self) -> None:
        summary = lambda_handler(self._event("/evolve-sprouts/summary"), None)
        self.assertEqual(summary["statusCode"], 200)
        body = json.loads(summary["body"])
        self.assertFalse(body["configured"])
        self.assertEqual(body["openInvoices"], 0)
        self.assertEqual(body["submittedExpenses"], 0)

        synced = lambda_handler(self._event("/evolve-sprouts/sync", method="POST"), None)
        self.assertEqual(synced["statusCode"], 200)
        self.assertEqual(json.loads(synced["body"])["skipped"], "not_configured")

    def test_put_and_import_are_rejected(self) -> None:
        denied = lambda_handler(
            self._event(
                "/evolve-sprouts",
                method="PUT",
                body={"defaultCurrency": "HKD", "float": {"amount": 0, "currency": "HKD"}, "lines": []},
            ),
            None,
        )
        self.assertEqual(denied["statusCode"], 403)
        self.assertIn("Evolve Sprouts", json.loads(denied["body"])["message"])
        self.table.put_item.assert_not_called()

        imported = lambda_handler(
            self._event(
                "/evolve-sprouts/parse-statement",
                method="POST",
                body={"key": "uploads/admin-sub/x/inv.pdf", "lineTypeOnly": "expenditure"},
            ),
            None,
        )
        self.assertEqual(imported["statusCode"], 403)

    def test_get_book_still_returns_lines(self) -> None:
        out = lambda_handler(self._event("/evolve-sprouts"), None)
        self.assertEqual(out["statusCode"], 200)
        self.assertEqual(json.loads(out["body"])["data"]["lines"], [])

    def test_sync_reports_a_database_error(self) -> None:
        def explode(sql: str, parameters: list | None) -> list[dict]:
            raise board_data_api.DataApiError("database refused the statement")

        board_data_api.set_executor_for_tests(explode)
        with patch.dict(
            "os.environ",
            {
                "EVOLVESPROUTS_CLUSTER_ARN": "arn:cluster",
                "EVOLVESPROUTS_DB_SECRET_ARN": "arn:secret",
            },
        ):
            out = lambda_handler(self._event("/evolve-sprouts/sync", method="POST"), None)
        self.assertEqual(out["statusCode"], 502)
        self.assertIn("refused", json.loads(out["body"])["message"])

    def test_nightly_trigger_skips_when_unconfigured(self) -> None:
        out = lambda_handler({"internal": "evolvesprouts_finance_mirror"}, None)
        self.assertEqual(out["skipped"], "not_configured")


if __name__ == "__main__":
    unittest.main()
