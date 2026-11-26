"""Wire-level checks for one response from each audience."""

from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _install_stubs() -> None:
    if "boto3" in sys.modules and not isinstance(sys.modules["boto3"], MagicMock):
        return
    mock_boto = MagicMock()
    sys.modules["boto3"] = mock_boto

    class _Exceptions(types.ModuleType):
        ClientError: type[Exception]

    class _Botocore(types.ModuleType):
        exceptions: _Exceptions

    class ClientError(Exception):
        pass

    exceptions = _Exceptions("botocore.exceptions")
    exceptions.ClientError = ClientError
    botocore = _Botocore("botocore")
    botocore.exceptions = exceptions
    sys.modules["botocore"] = botocore
    sys.modules["botocore.exceptions"] = exceptions


_install_stubs()

from http_call import http_call  # noqa: E402
from http_common import _json_response, apply_wire, legacy_http_path  # noqa: E402


def _http(method: str, path: str) -> dict:
    return {
        "requestContext": {
            "http": {"method": method, "path": path},
            "requestId": "req-wire",
        },
        "headers": {},
        "rawQueryString": "",
        "isBase64Encoded": False,
    }


def _admin(path: str) -> dict:
    event = _http("GET", path)
    event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": "admin-sub", "cognito:groups": "[admin]"}}}
    return event


def _partner(path: str) -> dict:
    event = _http("GET", path)
    event["requestContext"]["authorizer"] = {"lambda": {"keyId": "k123", "label": "test", "scope": "read"}}
    return event


class WireHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        import runtime

        table = MagicMock()
        table.get_item.return_value = {}
        table.scan.return_value = {"Items": []}
        patcher_ddb = patch.object(runtime, "_ddb")
        mock_ddb = patcher_ddb.start()
        self.addCleanup(patcher_ddb.stop)
        mock_ddb.Table.return_value = table
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

    def test_admin_response_and_error_use_wire_names(self) -> None:
        denied = http_call(_http("GET", "/v1/admin/me"), raw=True)
        error = json.loads(denied["body"])
        self.assertEqual(denied["statusCode"], 401)
        self.assertIn("request_id", error)
        self.assertNotIn("requestId", error)
        self.assertEqual(denied["headers"]["x-request-id"], "req-wire")

        out = http_call(_admin("/v1/admin/finance"), raw=True)
        body = json.loads(out["body"])
        self.assertEqual(out["statusCode"], 200)
        self.assertIn("income_records", body)
        self.assertNotIn("incomeRecords", body)

    def test_partner_response_uses_wire_names(self) -> None:
        out = http_call(_partner("/v1/partner/finance"), raw=True)
        body = json.loads(out["body"])
        self.assertEqual(out["statusCode"], 200)
        self.assertIn("income_records", body)
        self.assertNotIn("incomeRecords", body)

    def test_public_response_uses_wire_names(self) -> None:
        out = http_call(_http("GET", "/v1/public/newsletter/subscribe"), raw=True)
        body = json.loads(out["body"])
        self.assertGreaterEqual(out["statusCode"], 400)
        self.assertIn("request_id", body)
        self.assertNotIn("requestId", body)

    def test_webhook_body_is_left_unchanged(self) -> None:
        def respond(_event: dict) -> dict:
            return _json_response(200, {"hubMode": "subscribe"})

        out = apply_wire(_http("POST", "/webhooks/meta"), respond)
        self.assertEqual(json.loads(out["body"])["hubMode"], "subscribe")

    def test_list_cursor_query_and_path_parameter(self) -> None:
        seen: dict = {}

        def respond(event: dict) -> dict:
            seen["query"] = event.get("queryStringParameters")
            seen["params"] = event.get("pathParameters")
            seen["raw"] = event.get("rawQueryString")
            return _json_response(200, {"nextCursor": "n1", "items": []})

        event = _admin("/v1/admin/siutindei/board/catalog/candidates")
        event["queryStringParameters"] = {"missing_place_id": "1"}
        event["rawQueryString"] = "missing_place_id=1"
        event["pathParameters"] = {"job_id": "abc"}
        out = apply_wire(event, respond)
        self.assertEqual(seen["query"], {"missingPlaceId": "1"})
        self.assertEqual(seen["params"], {"jobId": "abc"})
        self.assertEqual(seen["raw"], "missingPlaceId=1")
        body = json.loads(out["body"])
        self.assertEqual(body["next_cursor"], "n1")
        self.assertNotIn("nextCursor", body)

    def test_the_partner_board_path_returns_snake_case(self) -> None:
        def respond(_event: dict) -> dict:
            return _json_response(200, {"nextCursor": "n1", "items": []})

        out = apply_wire(_partner("/v1/partner/siutindei/board/actions"), respond)
        body = json.loads(out["body"])
        self.assertEqual(body["next_cursor"], "n1")
        self.assertNotIn("nextCursor", body)
        self.assertEqual(
            legacy_http_path("/public/siu-tin-dei/board/actions"),
            "/public/siu-tin-dei/board/actions",
        )

    def test_the_wire_contract_is_read_once(self) -> None:
        import http_common
        import wire_format

        http_common._WIRE_CONTRACT = None
        calls = {"n": 0}
        real = wire_format.load_contract

        def wrapped(path: object = None) -> dict:
            calls["n"] += 1
            return real(path)

        def respond(_event: dict) -> dict:
            return _json_response(200, {"status": "ok"})

        with patch.object(wire_format, "load_contract", wrapped):
            apply_wire(_http("GET", "/health"), respond)
            apply_wire(_http("GET", "/health"), respond)
        self.assertEqual(calls["n"], 1)
