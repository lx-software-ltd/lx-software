"""Unit tests for openrouter_statement_parser (no network or AWS calls)."""

from __future__ import annotations

import io
import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _install_stubs() -> None:
    if "boto3" not in sys.modules:
        sys.modules["boto3"] = MagicMock()
    if "botocore" not in sys.modules:
        botocore = types.ModuleType("botocore")
        exceptions = types.ModuleType("botocore.exceptions")

        class ClientError(Exception):  # noqa: D401
            pass

        exceptions.ClientError = ClientError
        botocore.exceptions = exceptions
        sys.modules["botocore"] = botocore
        sys.modules["botocore.exceptions"] = exceptions


_install_stubs()

import openrouter_statement_parser as parser  # noqa: E402
import openrouter_client  # noqa: E402


def _fake_completion_body(content_obj: dict[str, object]) -> bytes:
    return json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(content_obj),
                    }
                }
            ]
        }
    ).encode("utf-8")


class TestNormalizeResult(unittest.TestCase):
    def test_minimal_line(self) -> None:
        parsed = {
            "lines": [
                {
                    "dateUtc": "2026-04-01",
                    "type": "expenditure",
                    "description": "Coffee",
                    "grossAmount": 3.5,
                    "currency": "gbp",
                }
            ]
        }
        out = parser._normalize_result(parsed, default_currency="HKD")
        self.assertEqual(len(out["lines"]), 1)
        line = out["lines"][0]
        self.assertEqual(line["currency"], "GBP")
        self.assertEqual(line["grossAmount"], 3.5)
        self.assertEqual(line["netAmount"], 3.5)
        self.assertEqual(line["vat"], 0.0)
        self.assertTrue(line["dateUtc"].startswith("2026-04-01T"))
        self.assertTrue(line["dateUtc"].endswith("Z"))

    def test_line_type_aliases(self) -> None:
        parsed = {
            "lines": [
                {
                    "dateUtc": "2026-04-01T12:00:00Z",
                    "type": "credit",
                    "description": "Salary",
                    "grossAmount": 100,
                },
                {
                    "dateUtc": "2026-04-02T12:00:00Z",
                    "type": "DEBIT",
                    "description": "Rent",
                    "grossAmount": 50,
                },
            ]
        }
        out = parser._normalize_result(parsed, default_currency="GBP")
        self.assertEqual(out["lines"][0]["type"], "income")
        self.assertEqual(out["lines"][1]["type"], "expenditure")

    def test_mortgage_type_from_model(self) -> None:
        parsed = {
            "lines": [
                {
                    "dateUtc": "2026-04-03T12:00:00Z",
                    "type": "mortgage",
                    "description": "Home loan",
                    "grossAmount": 1200,
                }
            ]
        }
        out = parser._normalize_result(parsed, default_currency="GBP")
        self.assertEqual(len(out["lines"]), 1)
        self.assertEqual(out["lines"][0]["type"], "mortgage")

    def test_mtg_in_description_forces_mortgage(self) -> None:
        for desc in ("MTG", "DD MTG PAYMENT", "Direct debit mtg"):
            with self.subTest(desc=desc):
                parsed = {
                    "lines": [
                        {
                            "dateUtc": "2026-04-01",
                            "type": "expenditure",
                            "description": desc,
                            "grossAmount": 800,
                            "currency": "GBP",
                        }
                    ]
                }
                out = parser._normalize_result(parsed, default_currency="GBP")
                self.assertEqual(out["lines"][0]["type"], "mortgage")

    def test_drops_invalid_lines(self) -> None:
        parsed = {
            "lines": [
                {"dateUtc": "bogus", "type": "income", "description": "x", "grossAmount": 1},
                {"dateUtc": "2026-04-01", "type": "weird", "description": "x", "grossAmount": 1},
                {"dateUtc": "2026-04-01", "type": "income", "description": "", "grossAmount": 1},
                {"dateUtc": "2026-04-01", "type": "income", "description": "ok", "grossAmount": None},
            ]
        }
        out = parser._normalize_result(parsed, default_currency="HKD")
        self.assertEqual(out["lines"], [])

    def test_unsupported_currency_falls_back_to_default(self) -> None:
        parsed = {
            "lines": [
                {
                    "dateUtc": "2026-04-01",
                    "type": "income",
                    "description": "Misc",
                    "grossAmount": 10,
                    "currency": "JPY",
                }
            ]
        }
        out = parser._normalize_result(parsed, default_currency="HKD")
        self.assertEqual(out["lines"][0]["currency"], "HKD")

    def test_money_string_with_symbol(self) -> None:
        parsed = {
            "lines": [
                {
                    "dateUtc": "2026-04-01",
                    "type": "expenditure",
                    "description": "Lunch",
                    "grossAmount": "£12.50",
                    "currency": "GBP",
                }
            ]
        }
        out = parser._normalize_result(parsed, default_currency="GBP")
        self.assertEqual(out["lines"][0]["grossAmount"], 12.5)

    def test_net_plus_vat_resolves_gross(self) -> None:
        parsed = {
            "lines": [
                {
                    "dateUtc": "2026-04-01",
                    "type": "expenditure",
                    "description": "Service",
                    "netAmount": 100,
                    "vat": 20,
                    "currency": "GBP",
                }
            ]
        }
        out = parser._normalize_result(parsed, default_currency="GBP")
        line = out["lines"][0]
        self.assertEqual(line["grossAmount"], 120.0)
        self.assertEqual(line["netAmount"], 100.0)
        self.assertEqual(line["vat"], 20.0)

    def test_drops_payment_to_landlord_lines(self) -> None:
        parsed = {
            "lines": [
                {
                    "dateUtc": "2026-04-01",
                    "type": "expenditure",
                    "description": "Payment to Landlord",
                    "grossAmount": 500,
                    "currency": "GBP",
                },
                {
                    "dateUtc": "2026-04-02",
                    "type": "expenditure",
                    "description": "PAYMENT TO LANDLORD",
                    "grossAmount": 100,
                    "currency": "GBP",
                },
                {
                    "dateUtc": "2026-04-03",
                    "type": "expenditure",
                    "description": "Utilities",
                    "grossAmount": 40,
                    "currency": "GBP",
                },
            ]
        }
        out = parser._normalize_result(parsed, default_currency="GBP")
        self.assertEqual(len(out["lines"]), 1)
        self.assertEqual(out["lines"][0]["description"], "Utilities")


class TestParseStatementFromAsset(unittest.TestCase):
    def setUp(self) -> None:
        parser.reset_api_key_cache_for_tests()

    def test_pdf_includes_file_parser_plugin(self) -> None:
        openrouter_client.reset_api_key_cache_for_tests()
        s3 = MagicMock()
        s3.get_object.return_value = {"Body": io.BytesIO(b"%PDF-1.4 fake")}
        secrets = MagicMock()
        secrets.get_secret_value.return_value = {
            "SecretString": json.dumps({"statement-parser": "sk-test"})
        }

        captured: dict[str, object] = {}

        class _FakeResp:
            def __init__(self, body: bytes) -> None:
                self._body = body

            def read(self) -> bytes:
                return self._body

            def __enter__(self):  # noqa: D401
                return self

            def __exit__(self, *_a):
                return False

        def _fake_urlopen(req, timeout=None):  # noqa: ARG001
            captured["url"] = req.full_url
            captured["body"] = req.data
            captured["headers"] = dict(req.headers)
            return _FakeResp(
                _fake_completion_body(
                    {
                        "lines": [
                            {
                                "dateUtc": "2026-04-15",
                                "type": "income",
                                "description": "Tenant payment",
                                "grossAmount": 1000,
                                "currency": "GBP",
                            }
                        ]
                    }
                )
            )

        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_API_KEY_SECRET_ARN": "arn:aws:secretsmanager:eu-west-1:1:secret:fake",
                "OPENROUTER_API_KEY": "",
            },
            clear=False,
        ), patch("openrouter_client.urlrequest.urlopen", _fake_urlopen):
            result = parser.parse_statement_from_asset(
                s3_client=s3,
                secrets_client=secrets,
                bucket="b",
                s3_key="uploads/x/1/statement.pdf",
                file_name="statement.pdf",
                content_type="application/pdf",
                default_currency="GBP",
                owner="hillmarton",
            )

        self.assertEqual(len(result["lines"]), 1)
        self.assertEqual(result["lines"][0]["currency"], "GBP")
        body = json.loads(captured["body"].decode("utf-8"))
        self.assertIn("plugins", body, "PDF requests must include the file-parser plugin")
        self.assertEqual(body["plugins"][0]["id"], "file-parser")
        self.assertEqual(body["messages"][1]["content"][1]["type"], "file")
        self.assertEqual(body["usage"], {"include": True})
        self.assertEqual(body["user"], "statement-parser:hillmarton")
        self.assertEqual(
            captured["headers"]["Authorization"], "Bearer sk-test"
        )
        headers = captured["headers"]
        self.assertEqual(
            next(v for k, v in headers.items() if k.lower() == "x-openrouter-title"),
            "LX Admin - Statement parser",
        )

    def test_image_uses_image_url(self) -> None:
        s3 = MagicMock()
        s3.get_object.return_value = {"Body": io.BytesIO(b"\x89PNG\r\n")}
        secrets = MagicMock()
        captured: dict[str, object] = {}

        class _FakeResp:
            def __init__(self, body: bytes) -> None:
                self._body = body

            def read(self) -> bytes:
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        def _fake_urlopen(req, timeout=None):  # noqa: ARG001
            captured["body"] = req.data
            return _FakeResp(_fake_completion_body({"lines": []}))

        with patch.dict(
            "os.environ", {"OPENROUTER_API_KEY": "sk-env"}, clear=False
        ), patch("openrouter_client.urlrequest.urlopen", _fake_urlopen):
            result = parser.parse_statement_from_asset(
                s3_client=s3,
                secrets_client=secrets,
                bucket="b",
                s3_key="uploads/x/1/photo.png",
                file_name="photo.png",
                content_type="image/png",
                default_currency="HKD",
            )

        self.assertEqual(result["lines"], [])
        body = json.loads(captured["body"].decode("utf-8"))
        self.assertNotIn("plugins", body)
        self.assertEqual(body["messages"][1]["content"][1]["type"], "image_url")


if __name__ == "__main__":
    unittest.main()
