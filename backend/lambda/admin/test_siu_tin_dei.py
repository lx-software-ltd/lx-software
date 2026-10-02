"""Unit tests for the Siu Tin Dei statement book (no AWS calls)."""

from __future__ import annotations

import json
import sys
import types
import unittest
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

from dispatch import lambda_handler  # noqa: E402
from finance_store import (  # noqa: E402
    _finance_owner_ddb_key,
    _statement_book_ddb_key,
)
from parse_jobs import (  # noqa: E402
    _path_siu_tin_dei_parse_job,
    _path_statement_book_parse_job,
)
from parse_statement import _resolve_parse_line_type_filter  # noqa: E402


class TestStatementBookKeys(unittest.TestCase):
    def test_book_key_is_not_a_house_key(self) -> None:
        self.assertEqual(
            _statement_book_ddb_key("siuTinDei"),
            {"pk": "FINANCE#book#siuTinDei", "sk": "STATE"},
        )
        self.assertEqual(
            _finance_owner_ddb_key("siuTinDei"),
            {"pk": "FINANCE#book#siuTinDei", "sk": "STATE"},
        )
        self.assertEqual(
            _finance_owner_ddb_key("hillmarton"),
            {"pk": "FINANCE#house#hillmarton", "sk": "STATE"},
        )
        self.assertEqual(
            _statement_book_ddb_key("lxSoftware"),
            {"pk": "FINANCE#book#lxSoftware", "sk": "STATE"},
        )
        self.assertEqual(
            _finance_owner_ddb_key("lxSoftware"),
            {"pk": "FINANCE#book#lxSoftware", "sk": "STATE"},
        )


class TestParseLineTypeFilter(unittest.TestCase):
    def test_mortgage_only_wins(self) -> None:
        self.assertEqual(
            _resolve_parse_line_type_filter(
                mortgage_only=True, line_type_only="income"
            ),
            "mortgage",
        )

    def test_line_type_only(self) -> None:
        self.assertEqual(
            _resolve_parse_line_type_filter(
                mortgage_only=False, line_type_only="expenditure"
            ),
            "expenditure",
        )
        self.assertEqual(
            _resolve_parse_line_type_filter(
                mortgage_only=False, line_type_only="INCOME"
            ),
            "income",
        )

    def test_unknown_type_is_ignored(self) -> None:
        self.assertIsNone(
            _resolve_parse_line_type_filter(
                mortgage_only=False, line_type_only="other"
            )
        )


class TestSiuTinDeiParseJobPath(unittest.TestCase):
    def test_from_path_parameters(self) -> None:
        ev = {"pathParameters": {"jobId": "abc123"}}
        self.assertEqual(
            _path_siu_tin_dei_parse_job(ev, "/siu-tin-dei/parse-statement/jobs/abc123"),
            "abc123",
        )

    def test_from_path_split(self) -> None:
        self.assertEqual(
            _path_siu_tin_dei_parse_job({}, "/siu-tin-dei/parse-statement/jobs/j1"),
            "j1",
        )

    def test_invalid(self) -> None:
        self.assertIsNone(_path_siu_tin_dei_parse_job({}, "/siu-tin-dei"))
        self.assertIsNone(
            _path_siu_tin_dei_parse_job({}, "/finance/hillmarton/parse-statement/jobs/j1")
        )


class TestStatementBookParseJobPath(unittest.TestCase):
    def test_lx_software_from_path_split(self) -> None:
        self.assertEqual(
            _path_statement_book_parse_job(
                {}, "/lx-software/parse-statement/jobs/j1", "lx-software"
            ),
            "j1",
        )

    def test_lx_software_rejects_other_slug(self) -> None:
        self.assertIsNone(
            _path_statement_book_parse_job(
                {}, "/siu-tin-dei/parse-statement/jobs/j1", "lx-software"
            )
        )


class TestSiuTinDeiRoutes(unittest.TestCase):
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
            },
        )
        patcher_env.start()
        self.addCleanup(patcher_env.stop)

    @staticmethod
    def _event(path: str, method: str = "GET", body: dict | None = None) -> dict:
        event: dict = {
            "requestContext": {
                "http": {"method": method, "path": path},
                "requestId": "req-std-1",
                "authorizer": {
                    "jwt": {
                        "claims": {
                            "sub": "admin-sub",
                            "cognito:groups": "[admin]",
                        }
                    }
                },
            },
            "rawQueryString": "",
        }
        if body is not None:
            event["body"] = json.dumps(body)
        return event

    def test_get_returns_empty_book(self) -> None:
        out = lambda_handler(self._event("/siu-tin-dei"), None)
        self.assertEqual(out["statusCode"], 200)
        data = json.loads(out["body"])["data"]
        self.assertEqual(data["defaultCurrency"], "HKD")
        self.assertEqual(data["lines"], [])

    def test_put_rejects_mortgage_line(self) -> None:
        body = {
            "defaultCurrency": "HKD",
            "float": {"amount": 0, "currency": "HKD"},
            "lines": [
                {
                    "id": "a",
                    "dateUtc": "2026-05-08T12:00:00.000Z",
                    "type": "mortgage",
                    "description": "x",
                    "netAmount": 1,
                    "vat": 0,
                    "grossAmount": 1,
                    "currency": "HKD",
                }
            ],
        }
        out = lambda_handler(self._event("/siu-tin-dei", method="PUT", body=body), None)
        self.assertEqual(out["statusCode"], 400)
        self.assertIn("income or expenditure", json.loads(out["body"])["message"])

    def test_put_accepts_expense_and_forces_hkd_default(self) -> None:
        body = {
            "defaultCurrency": "USD",
            "float": {"amount": 0, "currency": "USD"},
            "lines": [
                {
                    "id": "a",
                    "dateUtc": "2026-05-08T12:00:00.000Z",
                    "type": "expenditure",
                    "description": "Rice",
                    "netAmount": 10,
                    "vat": 0,
                    "grossAmount": 10,
                    "currency": "HKD",
                }
            ],
        }
        out = lambda_handler(self._event("/siu-tin-dei", method="PUT", body=body), None)
        self.assertEqual(out["statusCode"], 200)
        data = json.loads(out["body"])["data"]
        self.assertEqual(data["defaultCurrency"], "HKD")
        self.assertEqual(data["lines"][0]["type"], "expenditure")
        book_puts = [
            c.kwargs["Item"]
            for c in self.table.put_item.call_args_list
            if c.kwargs.get("Item", {}).get("pk") == "FINANCE#book#siuTinDei"
        ]
        self.assertEqual(len(book_puts), 1)

    def test_parse_requires_tab_scoped_type(self) -> None:
        out = lambda_handler(
            self._event(
                "/siu-tin-dei/parse-statement",
                method="POST",
                body={"key": "uploads/admin-sub/x/inv.pdf"},
            ),
            None,
        )
        self.assertEqual(out["statusCode"], 400)
        self.assertIn("lineTypeOnly", json.loads(out["body"])["message"])


class TestLxSoftwareRoutes(unittest.TestCase):
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
            },
        )
        patcher_env.start()
        self.addCleanup(patcher_env.stop)

    @staticmethod
    def _event(path: str, method: str = "GET", body: dict | None = None) -> dict:
        event: dict = {
            "requestContext": {
                "http": {"method": method, "path": path},
                "requestId": "req-lxs-1",
                "authorizer": {
                    "jwt": {
                        "claims": {
                            "sub": "admin-sub",
                            "cognito:groups": "[admin]",
                        }
                    }
                },
            },
            "rawQueryString": "",
        }
        if body is not None:
            event["body"] = json.dumps(body)
        return event

    def test_get_returns_empty_book(self) -> None:
        out = lambda_handler(self._event("/lx-software"), None)
        self.assertEqual(out["statusCode"], 200)
        data = json.loads(out["body"])["data"]
        self.assertEqual(data["defaultCurrency"], "HKD")
        self.assertEqual(data["lines"], [])

    def test_put_rejects_mortgage_line(self) -> None:
        body = {
            "defaultCurrency": "HKD",
            "float": {"amount": 0, "currency": "HKD"},
            "lines": [
                {
                    "id": "a",
                    "dateUtc": "2026-05-08T12:00:00.000Z",
                    "type": "mortgage",
                    "description": "x",
                    "netAmount": 1,
                    "vat": 0,
                    "grossAmount": 1,
                    "currency": "HKD",
                }
            ],
        }
        out = lambda_handler(self._event("/lx-software", method="PUT", body=body), None)
        self.assertEqual(out["statusCode"], 400)
        self.assertIn("income or expenditure", json.loads(out["body"])["message"])

    def test_put_accepts_expense_and_forces_hkd_default(self) -> None:
        body = {
            "defaultCurrency": "USD",
            "float": {"amount": 0, "currency": "USD"},
            "lines": [
                {
                    "id": "a",
                    "dateUtc": "2026-05-08T12:00:00.000Z",
                    "type": "expenditure",
                    "description": "Hosting",
                    "netAmount": 10,
                    "vat": 0,
                    "grossAmount": 10,
                    "currency": "HKD",
                }
            ],
        }
        out = lambda_handler(self._event("/lx-software", method="PUT", body=body), None)
        self.assertEqual(out["statusCode"], 200)
        data = json.loads(out["body"])["data"]
        self.assertEqual(data["defaultCurrency"], "HKD")
        self.assertEqual(data["lines"][0]["type"], "expenditure")
        book_puts = [
            c.kwargs["Item"]
            for c in self.table.put_item.call_args_list
            if c.kwargs.get("Item", {}).get("pk") == "FINANCE#book#lxSoftware"
        ]
        self.assertEqual(len(book_puts), 1)

    def test_parse_requires_tab_scoped_type(self) -> None:
        out = lambda_handler(
            self._event(
                "/lx-software/parse-statement",
                method="POST",
                body={"key": "uploads/admin-sub/x/inv.pdf"},
            ),
            None,
        )
        self.assertEqual(out["statusCode"], 400)
        self.assertIn("lineTypeOnly", json.loads(out["body"])["message"])


if __name__ == "__main__":
    unittest.main()
