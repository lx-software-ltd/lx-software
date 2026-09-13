"""Unit tests for the public API key authorizer (boto3 stubbed before import)."""

import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _install_stubs() -> None:
    mock_boto = MagicMock()
    sys.modules["boto3"] = mock_boto

    class ClientError(Exception):
        def __init__(self, response=None, operation_name=""):
            super().__init__(operation_name)
            self.response = response or {}

    botocore = types.ModuleType("botocore")
    exceptions = types.ModuleType("botocore.exceptions")
    exceptions.ClientError = ClientError
    botocore.exceptions = exceptions
    sys.modules["botocore"] = botocore
    sys.modules["botocore.exceptions"] = exceptions


_install_stubs()

import handler  # noqa: E402
from api_key_hash import hash_api_key  # noqa: E402
from handler import _is_expired, lambda_handler  # noqa: E402

_KEY = "lxpk_test-key-value"
_DIGEST = hash_api_key(_KEY)


def _event(key: str | None = _KEY, source_ip: str = "203.0.113.10") -> dict:
    headers = {} if key is None else {"x-api-key": key}
    return {
        "headers": headers,
        "requestContext": {
            "requestId": "req-1",
            "http": {"sourceIp": source_ip, "method": "GET", "path": "/public/finance"},
        },
    }


def _valid_item(**overrides) -> dict:
    item = {
        "pk": f"APIKEY#{_DIGEST}",
        "sk": "META",
        "keyId": "k123",
        "label": "test key",
        "scope": "read",
        "revoked": False,
    }
    item.update(overrides)
    return item


class TestAuthorizer(unittest.TestCase):
    def setUp(self) -> None:
        self.table = MagicMock()
        patcher_ddb = patch.object(handler, "_ddb")
        self.mock_ddb = patcher_ddb.start()
        self.addCleanup(patcher_ddb.stop)
        self.mock_ddb.Table.return_value = self.table
        patcher_env = patch.dict(
            "os.environ", {"RECORDS_TABLE_NAME": "records-test"}
        )
        patcher_env.start()
        self.addCleanup(patcher_env.stop)

    def test_missing_header_denied(self) -> None:
        self.table.get_item.return_value = {"Item": _valid_item()}
        self.assertFalse(lambda_handler(_event(key=None), None)["isAuthorized"])
        self.table.get_item.assert_not_called()

    def test_blank_or_oversized_key_denied(self) -> None:
        self.assertFalse(lambda_handler(_event(key="   "), None)["isAuthorized"])
        self.assertFalse(
            lambda_handler(_event(key="x" * 300), None)["isAuthorized"]
        )
        self.table.get_item.assert_not_called()

    def test_unknown_key_denied(self) -> None:
        self.table.get_item.return_value = {}
        self.assertFalse(lambda_handler(_event(), None)["isAuthorized"])

    def test_valid_key_allowed_with_context(self) -> None:
        self.table.get_item.return_value = {"Item": _valid_item()}
        out = lambda_handler(_event(), None)
        self.assertTrue(out["isAuthorized"])
        self.assertEqual(out["context"]["keyId"], "k123")
        self.assertEqual(out["context"]["scope"], "read")
        self.assertEqual(out["context"]["scopes"], "finance")
        self.table.get_item.assert_called_once_with(
            Key={"pk": f"APIKEY#{_DIGEST}", "sk": "META"}
        )
        self.table.update_item.assert_called()

    def test_explicit_scopes_allowed(self) -> None:
        self.table.get_item.return_value = {
            "Item": _valid_item(scopes=["finance", "siutindei-board-ops"])
        }
        out = lambda_handler(_event(), None)
        self.assertTrue(out["isAuthorized"])
        self.assertEqual(out["context"]["scopes"], "finance,siutindei-board-ops")

    def test_cidr_blocks_other_ip(self) -> None:
        self.table.get_item.return_value = {
            "Item": _valid_item(allowedCidrs=["10.0.0.0/8"])
        }
        self.assertFalse(lambda_handler(_event(source_ip="203.0.113.10"), None)["isAuthorized"])
        self.assertTrue(lambda_handler(_event(source_ip="10.1.2.3"), None)["isAuthorized"])

    def test_cidr_without_source_ip_denied(self) -> None:
        self.table.get_item.return_value = {
            "Item": _valid_item(allowedCidrs=["10.0.0.0/8"])
        }
        ev = _event()
        ev["requestContext"]["http"] = {}
        self.assertFalse(lambda_handler(ev, None)["isAuthorized"])

    def test_revoked_key_denied(self) -> None:
        self.table.get_item.return_value = {"Item": _valid_item(revoked=True)}
        self.assertFalse(lambda_handler(_event(), None)["isAuthorized"])

    def test_expired_key_denied(self) -> None:
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self.table.get_item.return_value = {"Item": _valid_item(expiresAt=past)}
        self.assertFalse(lambda_handler(_event(), None)["isAuthorized"])

    def test_future_expiry_allowed(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        self.table.get_item.return_value = {"Item": _valid_item(expiresAt=future)}
        self.assertTrue(lambda_handler(_event(), None)["isAuthorized"])

    def test_non_read_scope_denied(self) -> None:
        self.table.get_item.return_value = {"Item": _valid_item(scope="write")}
        self.assertFalse(lambda_handler(_event(), None)["isAuthorized"])

    def test_ddb_error_denied(self) -> None:
        from botocore.exceptions import ClientError

        self.table.get_item.side_effect = ClientError(
            {"Error": {"Code": "InternalServerError"}}, "GetItem"
        )
        self.assertFalse(lambda_handler(_event(), None)["isAuthorized"])


class TestHashApiKey(unittest.TestCase):
    def test_deterministic(self) -> None:
        self.assertEqual(hash_api_key(_KEY), _DIGEST)

    def test_distinct_keys_distinct_digests(self) -> None:
        self.assertNotEqual(hash_api_key("lxpk_other-key"), _DIGEST)

    def test_hex_output(self) -> None:
        self.assertEqual(len(_DIGEST), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in _DIGEST))


class TestIsExpired(unittest.TestCase):
    def test_absent_never_expires(self) -> None:
        now = datetime.now(timezone.utc)
        self.assertFalse(_is_expired(None, now))
        self.assertFalse(_is_expired("", now))

    def test_date_only_string(self) -> None:
        now = datetime(2026, 6, 15, tzinfo=timezone.utc)
        self.assertTrue(_is_expired("2026-06-01", now))
        self.assertFalse(_is_expired("2026-07-01", now))

    def test_zulu_suffix(self) -> None:
        now = datetime(2026, 6, 15, tzinfo=timezone.utc)
        self.assertTrue(_is_expired("2026-06-01T00:00:00Z", now))

    def test_garbage_fails_closed(self) -> None:
        now = datetime.now(timezone.utc)
        self.assertTrue(_is_expired("not-a-date", now))


if __name__ == "__main__":
    unittest.main()
