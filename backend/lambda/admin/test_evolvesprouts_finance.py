"""Evolve Sprouts statement-book mirror (no AWS calls)."""

from __future__ import annotations

import json
import sys
import types
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch


def _install_stubs() -> None:
    sys.modules["boto3"] = MagicMock()

    class ClientError(Exception):
        def __init__(self, message: str = "", response: dict | None = None) -> None:
            super().__init__(message)
            self.response = response or {"Error": {"Code": "", "Message": message}}

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
from finance_store import MirroredBookError, upsert_mirrored_lines  # noqa: E402


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
                "id": "late",
                "direction": "inbound",
                "amount": 4,
                "currency": "HKD",
                "succeeded_at": "2026-10-01T17:30:00Z",
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
            {
                "id": "nodate",
                "direction": "inbound",
                "amount": 6,
                "currency": "HKD",
                "succeeded_at": "",
            },
        ]
    if "payment_allocations" in sql:
        return [
            {"payment_id": "p1", "invoice_paid_at": "2026-04-15"},
            {"payment_id": "late", "invoice_paid_at": "2026-10-01"},
        ]
    if "FROM expenses" in sql:
        return [
            {
                "id": "e1",
                "status": "submitted",
                "total": 8,
                "subtotal": 7,
                "tax": 1,
                "currency": "HKD",
                "invoice_date": "2026-04-01",
                "vendor_name": "Example Vendor",
                "invoice_number": "INV-9",
            },
            {
                "id": "e2",
                "status": "paid",
                "total": 5,
                "tax": 0.5,
                "currency": "EUR",
                "invoice_date": "2026-03-01",
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
            {
                "id": "e4",
                "status": "submitted",
                "total": 3,
                "currency": "",
                "invoice_date": "2026-04-04",
            },
            {
                "id": "e5",
                "status": "paid",
                "total": None,
                "currency": "HKD",
                "paid_at": "2026-04-05",
            },
            {
                "id": "e6",
                "status": "paid",
                "total": 9,
                "currency": "HKD",
                "paid_at": "2026-04-06",
            },
        ]
    if "customer_invoices" in sql:
        return [
            {"currency": "HKD", "outstanding": 12.5, "n": 2},
            {"currency": "JPY", "outstanding": 9, "n": 1},
            {"currency": "", "outstanding": 2, "n": 1},
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
        self.assertEqual(result["skippedIncomplete"], 5)
        self.assertEqual(result["linesRemoved"], 1)
        by_id = {line["id"]: line for line in self._book_lines()}
        self.assertEqual(
            set(by_id),
            {"manual-1", "es-pay-p1", "es-pay-late", "es-ref-r1", "es-exp-e1", "es-exp-e2"},
        )
        self.assertEqual(by_id["es-pay-p1"]["type"], "income")
        self.assertEqual(by_id["es-pay-p1"]["description"], "p1")
        self.assertEqual(by_id["es-pay-p1"]["dateUtc"], "2026-04-15T00:00:00.000Z")
        self.assertEqual(by_id["es-pay-late"]["dateUtc"], "2026-10-01T00:00:00.000Z")
        self.assertEqual(by_id["es-ref-r1"]["type"], "expenditure")
        self.assertEqual(by_id["es-ref-r1"]["currency"], "USD")
        self.assertEqual(by_id["es-ref-r1"]["dateUtc"], "2026-05-02T00:00:00.000Z")
        self.assertEqual(by_id["es-exp-e1"]["description"], "Example Vendor INV-9")
        self.assertEqual(by_id["es-exp-e1"]["netAmount"], 7)
        self.assertEqual(by_id["es-exp-e1"]["vat"], 1)
        self.assertEqual(by_id["es-exp-e1"]["grossAmount"], 8)
        self.assertEqual(by_id["es-exp-e1"]["dateUtc"], "2026-04-01T00:00:00.000Z")
        self.assertEqual(by_id["es-exp-e2"]["description"], "e2")
        self.assertEqual(by_id["es-exp-e2"]["netAmount"], 4.5)
        self.assertEqual(by_id["es-exp-e2"]["vat"], 0.5)
        self.assertEqual(by_id["es-exp-e2"]["dateUtc"], "2026-03-01T00:00:00.000Z")
        self.assertEqual(by_id["es-pay-p1"]["source"], "evolvesprouts")
        self.assertNotIn("source", by_id["manual-1"])
        self.assertEqual(by_id["manual-1"]["description"], "Kept")

        again = es.sync(self.table)
        self.assertEqual(again["linesWritten"], 0)
        self.assertEqual(again["linesRemoved"], 0)
        self.assertEqual(
            {line["id"] for line in self._book_lines()},
            {"manual-1", "es-pay-p1", "es-pay-late", "es-ref-r1", "es-exp-e1", "es-exp-e2"},
        )
        summary = es.load_summary(self.table)
        self.assertEqual(summary["submittedExpenses"], 1)
        self.assertEqual(summary["paidExpenses"], 1)
        self.assertIsNone(summary["syncError"])
        self.assertTrue(summary["configured"])

    def test_expense_vendor_name_comes_from_organizations(self) -> None:
        self.assertIn("LEFT JOIN organizations o ON o.id = e.vendor_id", es.EXPENSES_SQL)
        self.assertIn("o.name AS vendor_name", es.EXPENSES_SQL)
        self.assertNotIn("e.vendor_name", es.EXPENSES_SQL)

    def test_gain_date_uses_invoice_paid_at(self) -> None:
        self.assertIn("payment_allocations", es.INVOICE_PAID_SQL)
        self.assertIn("invoice_paid_at", es.INVOICE_PAID_SQL)

    def test_expense_date_uses_issued_invoice_date(self) -> None:
        self.assertIn("e.invoice_date", es.EXPENSES_SQL)
        self.assertNotIn("e.paid_at", es.EXPENSES_SQL)

    def test_gain_date_falls_back_to_succeeded_at(self) -> None:
        def rows(sql: str, _parameters: list | None) -> list[dict]:
            if "payment_allocations" in sql:
                raise board_data_api.DataApiError("permission denied for payment_allocations")
            return _rows(sql, _parameters)

        board_data_api.set_executor_for_tests(rows)
        result = es.sync(self.table)
        self.assertTrue(result["ok"])
        by_id = {line["id"]: line for line in self._book_lines()}
        self.assertEqual(by_id["es-pay-p1"]["dateUtc"], "2026-05-01T00:00:00.000Z")
        self.assertEqual(by_id["es-pay-late"]["dateUtc"], "2026-10-02T00:00:00.000Z")
        self.assertEqual(by_id["es-exp-e2"]["dateUtc"], "2026-03-01T00:00:00.000Z")

    def test_currency_only_correction_is_written(self) -> None:
        es.sync(self.table)
        item = self.table.items[("FINANCE#book#evolveSprouts", "STATE")]
        for line in item["lines"]:
            if line["id"] == "es-pay-p1":
                line["currency"] = "USD"
                line["netAmount"] = Decimal("99")
        result = es.sync(self.table)
        self.assertGreaterEqual(result["linesWritten"], 1)
        by_id = {line["id"]: line for line in self._book_lines()}
        self.assertEqual(by_id["es-pay-p1"]["currency"], "HKD")
        self.assertEqual(by_id["es-pay-p1"]["netAmount"], 10)

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

    def test_queue_sync_stamps_pending_and_invokes(self) -> None:
        with patch("board_async.try_invoke_event", return_value=True) as invoke:
            result = es.queue_sync(self.table)
        self.assertTrue(result["queued"])
        self.assertTrue(result["invoked"])
        self.assertTrue(result["pendingSince"])
        invoke.assert_called_once_with({"internal": "evolvesprouts_finance_mirror"})
        stored = es.load_summary(self.table)
        self.assertEqual(stored["pendingSince"], result["pendingSince"])

    def test_queue_sync_clears_pending_when_invoke_fails(self) -> None:
        with patch("board_async.try_invoke_event", return_value=False):
            result = es.queue_sync(self.table)
        self.assertFalse(result["queued"])
        self.assertIsNone(result["pendingSince"])
        self.assertIn("Could not start", result["syncError"])
        stored = es.load_summary(self.table)
        self.assertIsNone(stored["pendingSince"])
        self.assertIn("Could not start", stored["syncError"])


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

    def test_http_sync_queues_when_configured(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "EVOLVESPROUTS_CLUSTER_ARN": "arn:cluster",
                    "EVOLVESPROUTS_DB_SECRET_ARN": "arn:secret",
                },
            ),
            patch("board_async.try_invoke_event", return_value=True) as invoke,
        ):
            out = lambda_handler(self._event("/evolve-sprouts/sync", method="POST"), None)
        self.assertEqual(out["statusCode"], 200)
        body = json.loads(out["body"])
        self.assertTrue(body["queued"])
        invoke.assert_called_once()

    def test_mirror_trigger_records_a_database_error(self) -> None:
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
            with self.assertRaises(es.EvolveSproutsFinanceError):
                lambda_handler({"internal": "evolvesprouts_finance_mirror"}, None)
        saved = self.table.put_item.call_args.kwargs["Item"]
        self.assertIn("refused", str(saved.get("syncError")))

    def test_nightly_trigger_skips_when_unconfigured(self) -> None:
        out = lambda_handler({"internal": "evolvesprouts_finance_mirror"}, None)
        self.assertEqual(out["skipped"], "not_configured")


class TestDataApiPages(unittest.TestCase):
    def tearDown(self) -> None:
        board_data_api.set_executor_for_tests(None)

    def test_follows_next_token(self) -> None:
        board_data_api.set_executor_for_tests(None)
        responses = [
            {
                "columnMetadata": [{"name": "id"}],
                "records": [[{"stringValue": "a"}]],
                "nextToken": "n1",
            },
            {
                "columnMetadata": [{"name": "id"}],
                "records": [[{"stringValue": "b"}]],
            },
        ]
        client = MagicMock()
        client.execute_statement.side_effect = responses
        with (
            patch.dict(
                "os.environ",
                {
                    "EVOLVESPROUTS_CLUSTER_ARN": "arn:cluster",
                    "EVOLVESPROUTS_DB_SECRET_ARN": "arn:secret",
                },
            ),
            patch.object(board_data_api.boto3, "client", return_value=client),
        ):
            rows = board_data_api.execute("SELECT 1", target=board_data_api.evolvesprouts_target())
        self.assertEqual([row["id"] for row in rows], ["a", "b"])
        self.assertEqual(client.execute_statement.call_count, 2)
        self.assertEqual(client.execute_statement.call_args_list[1].kwargs.get("nextToken"), "n1")


class TestMirroredLineLimits(unittest.TestCase):
    def _table(self) -> MagicMock:
        table = MagicMock()
        table.get_item.return_value = {
            "Item": {
                "pk": "FINANCE#book#evolveSprouts",
                "sk": "STATE",
                "defaultCurrency": "HKD",
                "float": {"amount": Decimal("0"), "currency": "HKD"},
                "lines": [],
            }
        }
        return table

    @staticmethod
    def _line() -> dict:
        return {
            "id": "es-pay-1",
            "dateUtc": "2026-01-01T00:00:00.000Z",
            "type": "income",
            "description": "x",
            "netAmount": 1,
            "vat": 0,
            "grossAmount": 1,
            "currency": "HKD",
            "source": "evolvesprouts",
        }

    def test_item_too_large_is_a_mirrored_book_error(self) -> None:
        # Subclass the ClientError finance_store already imported. The suite
        # stubs botocore later, so a fresh import is a different class and
        # the except clause never sees it.
        import finance_store

        class SizeError(finance_store.ClientError):
            def __init__(self) -> None:
                Exception.__init__(self, "too big")
                self.response = {
                    "Error": {
                        "Code": "ValidationException",
                        "Message": "Item size has exceeded the maximum allowed size of 400 KB",
                    }
                }

        table = self._table()
        table.put_item.side_effect = SizeError()
        with self.assertRaises(MirroredBookError) as ctx:
            upsert_mirrored_lines(
                table,
                "evolveSprouts",
                [self._line()],
                id_prefixes=("es-pay-",),
                source="evolvesprouts",
            )
        self.assertIn("too large", str(ctx.exception))

    def test_other_client_errors_propagate(self) -> None:
        import finance_store

        class Denied(finance_store.ClientError):
            def __init__(self) -> None:
                Exception.__init__(self, "no")
                self.response = {"Error": {"Code": "AccessDeniedException", "Message": "no"}}

        table = self._table()
        table.put_item.side_effect = Denied()
        with self.assertRaises(finance_store.ClientError):
            upsert_mirrored_lines(
                table,
                "evolveSprouts",
                [self._line()],
                id_prefixes=("es-pay-",),
                source="evolvesprouts",
            )


if __name__ == "__main__":
    unittest.main()
