"""Unit tests for the Enable Banking sync module (no boto3 on host)."""

import base64
import json
import sys
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _install_stubs() -> None:
    if "boto3" not in sys.modules:
        sys.modules["boto3"] = MagicMock()
    if "botocore.exceptions" not in sys.modules:
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

import bank_sync  # noqa: E402
import runtime  # noqa: E402
from bank_sync import (  # noqa: E402
    BANK_SYNC_STATE_KEY,
    _build_eb_jwt,
    _consent_valid_until,
    _pick_balance,
    _summarize_session_accounts,
    bank_sync_enabled,
    run_bank_sync,
)
from ddb_convert import _from_ddb_nested, _to_ddb_nested  # noqa: E402
from dispatch import lambda_handler  # noqa: E402
from finance_store import _finance_sheet_ddb_key  # noqa: E402


class FakeTable:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict] = {}

    @staticmethod
    def _key(key: dict) -> tuple[str, str]:
        return (key["pk"], key["sk"])

    def get_item(self, Key: dict) -> dict:
        item = self.items.get(self._key(Key))
        return {"Item": item} if item else {}

    def put_item(self, Item: dict, **kwargs) -> None:
        self.items[(Item["pk"], Item["sk"])] = Item

    def delete_item(self, Key: dict) -> None:
        self.items.pop(self._key(Key), None)

    def scan(self, **kwargs) -> dict:
        return {"Items": list(self.items.values())}


ENABLED_ENV = {
    "RECORDS_TABLE_NAME": "records-test",
    "AUDIT_LOG_TABLE_NAME": "audit-test",
    "ASSETS_BUCKET_NAME": "assets-test",
    "ENABLE_BANKING_APP_ID": "app-123",
    "ENABLE_BANKING_KMS_KEY_ID": "kms-key-1",
    "ADMIN_WEB_ORIGIN": "https://admin.example.com",
}

DISABLED_ENV = {
    "RECORDS_TABLE_NAME": "records-test",
    "AUDIT_LOG_TABLE_NAME": "audit-test",
    "ASSETS_BUCKET_NAME": "assets-test",
    "ENABLE_BANKING_APP_ID": "",
    "ENABLE_BANKING_KMS_KEY_ID": "",
}


def _b64url_decode(segment: str) -> bytes:
    pad = "=" * ((4 - len(segment) % 4) % 4)
    return base64.urlsafe_b64decode(segment + pad)


def _admin_event(path: str, method: str = "GET", body: dict | None = None) -> dict:
    event: dict = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "requestId": "req-banking-1",
            "authorizer": {
                "jwt": {
                    "claims": {"sub": "admin-sub", "cognito:groups": "[admin]"}
                }
            },
        },
        "rawQueryString": "",
    }
    if body is not None:
        event["body"] = json.dumps(body)
    return event


class BankSyncTestCase(unittest.TestCase):
    """Shared table/env plumbing for bank sync tests."""

    env: dict = ENABLED_ENV

    def setUp(self) -> None:
        self.table = FakeTable()
        patcher_ddb = patch.object(runtime, "_ddb")
        mock_ddb = patcher_ddb.start()
        self.addCleanup(patcher_ddb.stop)
        mock_ddb.Table.return_value = self.table
        patcher_env = patch.dict("os.environ", self.env, clear=False)
        patcher_env.start()
        self.addCleanup(patcher_env.stop)
        bank_sync._jwt_cache.update({"token": None, "expires": 0.0, "app_id": None})  # nosec B105

    def _seed_state(self, state: dict) -> None:
        self.table.put_item(Item={**BANK_SYNC_STATE_KEY, **_to_ddb_nested(state)})

    def _seed_accounts_sheet(self, records: list[dict]) -> None:
        self.table.put_item(
            Item={
                **_finance_sheet_ddb_key("accounts"),
                **_to_ddb_nested({"records": records}),
            }
        )

    def _stored_state(self) -> dict:
        item = self.table.items.get(FakeTable._key(BANK_SYNC_STATE_KEY))
        return _from_ddb_nested(item) if item else {}

    def _stored_accounts(self) -> list[dict]:
        key = FakeTable._key(_finance_sheet_ddb_key("accounts"))
        item = self.table.items.get(key)
        return _from_ddb_nested(item)["records"] if item else []


SESSION_HSBC = {
    "sessionId": "sess-hsbc",
    "bankName": "HSBC Personal",
    "bankCountry": "GB",
    "validUntil": "2026-11-01T00:00:00Z",
    "createdAt": "2026-08-01T00:00:00Z",
    "accounts": [
        {
            "uid": "uid-current",
            "identifier": "GB33BUKB20201555555555",
            "name": "Current Account",
            "currency": "GBP",
        }
    ],
}

ACCOUNT_RECORD = {
    "id": "acc-hsbc-uk",
    "description": "HSBC UK current",
    "accountType": "Bank Account",
    "billingCycleDay": 1,
    "recordedValue": 100.0,
    "currency": "GBP",
    "lastUpdated": "2026-01-01",
}


class TestJwtSigning(BankSyncTestCase):
    def test_builds_rs256_jwt_via_kms(self) -> None:
        kms = MagicMock()
        kms.sign.return_value = {"Signature": b"fake-signature"}
        with patch.object(runtime, "_kms", kms):
            token = _build_eb_jwt(now_epoch=1_700_000_000)
        header_b64, payload_b64, signature_b64 = token.split(".")
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
        self.assertEqual(
            header, {"typ": "JWT", "alg": "RS256", "kid": "app-123"}
        )
        self.assertEqual(payload["iss"], "enablebanking.com")
        self.assertEqual(payload["aud"], "api.enablebanking.com")
        self.assertEqual(payload["iat"], 1_700_000_000)
        self.assertEqual(payload["exp"], 1_700_000_000 + 3600)
        self.assertEqual(_b64url_decode(signature_b64), b"fake-signature")
        kms.sign.assert_called_once()
        kwargs = kms.sign.call_args.kwargs
        self.assertEqual(kwargs["KeyId"], "kms-key-1")
        self.assertEqual(kwargs["SigningAlgorithm"], "RSASSA_PKCS1_V1_5_SHA_256")
        self.assertEqual(
            kwargs["Message"].decode("ascii"), f"{header_b64}.{payload_b64}"
        )

    def test_jwt_cache_reuses_token(self) -> None:
        kms = MagicMock()
        kms.sign.return_value = {"Signature": b"sig"}
        with patch.object(runtime, "_kms", kms):
            first = bank_sync._eb_jwt()
            second = bank_sync._eb_jwt()
        self.assertEqual(first, second)
        kms.sign.assert_called_once()

    def test_enabled_flag(self) -> None:
        self.assertTrue(bank_sync_enabled())
        with patch.dict("os.environ", {"ENABLE_BANKING_APP_ID": ""}):
            self.assertFalse(bank_sync_enabled())


class TestPickBalance(unittest.TestCase):
    def test_prefers_booked_balance(self) -> None:
        balances = [
            {
                "balance_type": "ITAV",
                "balance_amount": {"amount": "90.00", "currency": "GBP"},
            },
            {
                "balance_type": "CLBD",
                "balance_amount": {"amount": "100.50", "currency": "GBP"},
            },
        ]
        picked = _pick_balance(balances)
        assert picked is not None
        self.assertEqual(picked["balanceType"], "CLBD")
        self.assertEqual(picked["amount"], 100.50)

    def test_falls_back_to_first_usable(self) -> None:
        balances = [
            {"balance_type": "ZZZZ", "balance_amount": {"amount": "1", "currency": "EUR"}},
        ]
        picked = _pick_balance(balances)
        assert picked is not None
        self.assertEqual(picked["amount"], 1.0)
        self.assertEqual(picked["currency"], "EUR")

    def test_skips_invalid_amounts(self) -> None:
        balances = [
            {"balance_type": "CLBD", "balance_amount": {"amount": "not-a-number"}},
            {"balance_type": "ITAV", "balance_amount": {"amount": "5.5", "currency": "gbp"}},
        ]
        picked = _pick_balance(balances)
        assert picked is not None
        self.assertEqual(picked["amount"], 5.5)
        self.assertEqual(picked["currency"], "GBP")

    def test_returns_none_when_unusable(self) -> None:
        self.assertIsNone(_pick_balance(None))
        self.assertIsNone(_pick_balance([]))
        self.assertIsNone(_pick_balance([{"balance_amount": {"amount": "nan"}}]))


class TestConsentValidUntil(unittest.TestCase):
    def test_caps_to_bank_maximum(self) -> None:
        until = datetime.strptime(
            _consent_valid_until(90 * 24 * 3600), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        expected = datetime.now(timezone.utc) + timedelta(days=90)
        self.assertLess(abs((until - expected).total_seconds()), 60)

    def test_defaults_to_180_days(self) -> None:
        for bogus in (None, True, -5, "soon"):
            until = datetime.strptime(
                _consent_valid_until(bogus), "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
            expected = datetime.now(timezone.utc) + timedelta(days=180)
            self.assertLess(abs((until - expected).total_seconds()), 60)


class TestSummarizeSessionAccounts(unittest.TestCase):
    def test_extracts_iban_and_metadata(self) -> None:
        accounts = _summarize_session_accounts(
            [
                {
                    "uid": "u1",
                    "account_id": {"iban": "FI0455231152453547"},
                    "name": "Main",
                    "currency": "EUR",
                    "product": "Current",
                }
            ]
        )
        self.assertEqual(
            accounts,
            [
                {
                    "uid": "u1",
                    "identifier": "FI0455231152453547",
                    "name": "Main",
                    "product": "Current",
                    "currency": "EUR",
                }
            ],
        )

    def test_falls_back_to_other_ids_and_skips_invalid(self) -> None:
        accounts = _summarize_session_accounts(
            [
                {"uid": "u2", "all_account_ids": [{"identification": "123456"}]},
                {"name": "missing uid"},
                "not-a-dict",
            ]
        )
        self.assertEqual(accounts, [{"uid": "u2", "identifier": "123456"}])


class TestRunBankSync(BankSyncTestCase):
    def _seed_linked(self) -> None:
        self._seed_state(
            {
                "sessions": [SESSION_HSBC],
                "mappings": [
                    {"accountUid": "uid-current", "accountRecordId": "acc-hsbc-uk"}
                ],
            }
        )
        self._seed_accounts_sheet([ACCOUNT_RECORD])

    def test_updates_record_value_and_last_updated(self) -> None:
        self._seed_linked()
        balances = {
            "balances": [
                {
                    "balance_type": "CLBD",
                    "balance_amount": {"amount": "2450.75", "currency": "GBP"},
                }
            ]
        }
        with patch.object(bank_sync, "_eb_request", return_value=balances) as eb:
            report = run_bank_sync(self.table)
        eb.assert_called_once_with("GET", "/accounts/uid-current/balances")
        self.assertEqual(report["results"][0]["status"], "ok")
        self.assertEqual(report["results"][0]["balance"], 2450.75)
        records = self._stored_accounts()
        self.assertEqual(records[0]["recordedValue"], 2450.75)
        today = datetime.now(timezone.utc).date().isoformat()
        self.assertEqual(records[0]["lastUpdated"], today)
        self.assertEqual(self._stored_state()["lastSync"]["results"], report["results"])

    def test_unchanged_balance_keeps_last_updated(self) -> None:
        self._seed_linked()
        balances = {
            "balances": [
                {
                    "balance_type": "CLBD",
                    "balance_amount": {"amount": "100.0", "currency": "GBP"},
                }
            ]
        }
        with patch.object(bank_sync, "_eb_request", return_value=balances):
            report = run_bank_sync(self.table)
        self.assertEqual(report["results"][0]["status"], "ok")
        records = self._stored_accounts()
        self.assertEqual(records[0]["recordedValue"], 100.0)
        self.assertEqual(records[0]["lastUpdated"], "2026-01-01")

    def test_currency_mismatch_is_error_and_skips_update(self) -> None:
        self._seed_linked()
        balances = {
            "balances": [
                {
                    "balance_type": "CLBD",
                    "balance_amount": {"amount": "99.0", "currency": "EUR"},
                }
            ]
        }
        with patch.object(bank_sync, "_eb_request", return_value=balances):
            report = run_bank_sync(self.table)
        self.assertEqual(report["results"][0]["status"], "error")
        self.assertIn("does not match", report["results"][0]["message"])
        self.assertEqual(self._stored_accounts()[0]["recordedValue"], 100.0)

    def test_upstream_error_is_reported_per_account(self) -> None:
        self._seed_linked()
        with patch.object(
            bank_sync,
            "_eb_request",
            side_effect=bank_sync.BankSyncUpstreamError("Enable Banking HTTP 401"),
        ):
            report = run_bank_sync(self.table)
        self.assertEqual(report["results"][0]["status"], "error")
        self.assertIn("HTTP 401", report["results"][0]["message"])

    def test_missing_record_or_account(self) -> None:
        self._seed_state(
            {
                "sessions": [SESSION_HSBC],
                "mappings": [
                    {"accountUid": "uid-current", "accountRecordId": "gone"},
                    {"accountUid": "uid-unknown", "accountRecordId": "acc-hsbc-uk"},
                ],
            }
        )
        self._seed_accounts_sheet([ACCOUNT_RECORD])
        with patch.object(bank_sync, "_eb_request") as eb:
            report = run_bank_sync(self.table)
        eb.assert_not_called()
        statuses = [r["status"] for r in report["results"]]
        self.assertEqual(statuses, ["error", "error"])


class TestBankingRoutesDisabled(BankSyncTestCase):
    env = DISABLED_ENV

    def test_get_banking_reports_disabled(self) -> None:
        out = lambda_handler(_admin_event("/v1/admin/banking"), None)
        self.assertEqual(out["statusCode"], 200)
        body = json.loads(out["body"])
        self.assertFalse(body["enabled"])
        self.assertEqual(body["sessions"], [])
        self.assertEqual(body["mappings"], [])

    def test_auth_start_rejected_when_disabled(self) -> None:
        out = lambda_handler(
            _admin_event(
                "/v1/admin/banking/auth",
                method="POST",
                body={
                    "bankName": "HSBC Personal",
                    "country": "GB",
                    "redirectUrl": "http://localhost:5173/banking/callback",
                },
            ),
            None,
        )
        self.assertEqual(out["statusCode"], 400)
        self.assertIn("not configured", json.loads(out["body"])["message"])

    def test_internal_worker_noops_when_disabled(self) -> None:
        with patch.object(bank_sync, "run_bank_sync") as run:
            out = lambda_handler({"internal": "bank_sync"}, None)
        run.assert_not_called()
        self.assertEqual(out, {})


class TestBankingAuthRoutes(BankSyncTestCase):
    def test_auth_start_rejects_unlisted_redirect(self) -> None:
        out = lambda_handler(
            _admin_event(
                "/v1/admin/banking/auth",
                method="POST",
                body={
                    "bankName": "HSBC Personal",
                    "country": "GB",
                    "redirectUrl": "https://evil.example.com/banking/callback",
                },
            ),
            None,
        )
        self.assertEqual(out["statusCode"], 400)
        self.assertIn("redirectUrl", json.loads(out["body"])["message"])

    def test_auth_start_happy_path_stores_state(self) -> None:
        def fake_eb(method, path, **kwargs):
            if path == "/aspsps":
                return {
                    "aspsps": [
                        {
                            "name": "HSBC Personal",
                            "country": "GB",
                            "maximum_consent_validity": 7776000,
                        }
                    ]
                }
            self.assertEqual(path, "/auth")
            body = kwargs["body"]
            self.assertEqual(body["aspsp"], {"name": "HSBC Personal", "country": "GB"})
            self.assertEqual(
                body["redirect_url"],
                "https://admin.example.com/banking/callback",
            )
            self.assertEqual(body["psu_type"], "personal")
            return {"url": "https://auth.enablebanking.com/x", "authorization_id": "a1"}

        with patch.object(bank_sync, "_eb_request", side_effect=fake_eb):
            out = lambda_handler(
                _admin_event(
                    "/v1/admin/banking/auth",
                    method="POST",
                    body={
                        "bankName": "HSBC Personal",
                        "country": "GB",
                        "redirectUrl": "https://admin.example.com/banking/callback",
                    },
                ),
                None,
            )
        self.assertEqual(out["statusCode"], 200)
        body = json.loads(out["body"])
        self.assertEqual(body["url"], "https://auth.enablebanking.com/x")
        pending = self.table.items.get((f"BANKSYNC#auth#{body['state']}", "META"))
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertEqual(pending["bankName"], "HSBC Personal")

    def test_auth_start_unknown_bank(self) -> None:
        with patch.object(
            bank_sync, "_eb_request", return_value={"aspsps": []}
        ):
            out = lambda_handler(
                _admin_event(
                    "/v1/admin/banking/auth",
                    method="POST",
                    body={
                        "bankName": "No Such Bank",
                        "country": "GB",
                        "redirectUrl": "https://admin.example.com/banking/callback",
                    },
                ),
                None,
            )
        self.assertEqual(out["statusCode"], 400)
        self.assertIn("Unknown bank", json.loads(out["body"])["message"])

    def test_sessions_rejects_unknown_state(self) -> None:
        out = lambda_handler(
            _admin_event(
                "/v1/admin/banking/sessions",
                method="POST",
                body={"code": "auth-code", "state": "nope"},
            ),
            None,
        )
        self.assertEqual(out["statusCode"], 400)
        self.assertIn("authorization state", json.loads(out["body"])["message"])

    def test_sessions_happy_path_stores_session(self) -> None:
        self.table.put_item(
            Item={
                "pk": "BANKSYNC#auth#state-1",
                "sk": "META",
                "bankName": "HSBC Personal",
                "bankCountry": "GB",
                "redirectUrl": "https://admin.example.com/banking/callback",
                "expiresAt": int(time.time()) + 600,
            }
        )
        session_response = {
            "session_id": "sess-1",
            "accounts": [
                {
                    "uid": "uid-1",
                    "account_id": {"iban": "GB33BUKB20201555555555"},
                    "name": "Current",
                    "currency": "GBP",
                }
            ],
            "aspsp": {"name": "HSBC Personal", "country": "GB"},
            "access": {"valid_until": "2026-11-10T00:00:00Z"},
        }
        with patch.object(
            bank_sync, "_eb_request", return_value=session_response
        ) as eb:
            out = lambda_handler(
                _admin_event(
                    "/v1/admin/banking/sessions",
                    method="POST",
                    body={"code": "auth-code", "state": "state-1"},
                ),
                None,
            )
        eb.assert_called_once_with("POST", "/sessions", body={"code": "auth-code"})
        self.assertEqual(out["statusCode"], 200)
        session = json.loads(out["body"])["session"]
        self.assertEqual(session["sessionId"], "sess-1")
        self.assertEqual(session["validUntil"], "2026-11-10T00:00:00Z")
        self.assertEqual(session["accounts"][0]["identifier"], "GB33BUKB20201555555555")
        # State token is single-use.
        self.assertNotIn(("BANKSYNC#auth#state-1", "META"), self.table.items)
        stored = self._stored_state()
        self.assertEqual(len(stored["sessions"]), 1)

    def test_expired_state_rejected(self) -> None:
        self.table.put_item(
            Item={
                "pk": "BANKSYNC#auth#state-old",
                "sk": "META",
                "expiresAt": int(time.time()) - 10,
            }
        )
        out = lambda_handler(
            _admin_event(
                "/v1/admin/banking/sessions",
                method="POST",
                body={"code": "auth-code", "state": "state-old"},
            ),
            None,
        )
        self.assertEqual(out["statusCode"], 400)
        self.assertIn("expired", json.loads(out["body"])["message"])


class TestBankingMappingsAndDelete(BankSyncTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._seed_state({"sessions": [SESSION_HSBC], "mappings": []})
        self._seed_accounts_sheet([ACCOUNT_RECORD])

    def test_put_mappings_happy_path(self) -> None:
        out = lambda_handler(
            _admin_event(
                "/v1/admin/banking/mappings",
                method="PUT",
                body={
                    "mappings": [
                        {"accountUid": "uid-current", "accountRecordId": "acc-hsbc-uk"}
                    ]
                },
            ),
            None,
        )
        self.assertEqual(out["statusCode"], 200)
        self.assertEqual(len(self._stored_state()["mappings"]), 1)

    def test_put_mappings_rejects_unknown_uid(self) -> None:
        out = lambda_handler(
            _admin_event(
                "/v1/admin/banking/mappings",
                method="PUT",
                body={
                    "mappings": [
                        {"accountUid": "nope", "accountRecordId": "acc-hsbc-uk"}
                    ]
                },
            ),
            None,
        )
        self.assertEqual(out["statusCode"], 400)
        self.assertIn("linked bank account", json.loads(out["body"])["message"])

    def test_put_mappings_rejects_unknown_record(self) -> None:
        out = lambda_handler(
            _admin_event(
                "/v1/admin/banking/mappings",
                method="PUT",
                body={
                    "mappings": [
                        {"accountUid": "uid-current", "accountRecordId": "nope"}
                    ]
                },
            ),
            None,
        )
        self.assertEqual(out["statusCode"], 400)
        self.assertIn("accounts-sheet record", json.loads(out["body"])["message"])

    def test_put_mappings_rejects_duplicates(self) -> None:
        out = lambda_handler(
            _admin_event(
                "/v1/admin/banking/mappings",
                method="PUT",
                body={
                    "mappings": [
                        {"accountUid": "uid-current", "accountRecordId": "acc-hsbc-uk"},
                        {"accountUid": "uid-current", "accountRecordId": "acc-hsbc-uk"},
                    ]
                },
            ),
            None,
        )
        self.assertEqual(out["statusCode"], 400)
        self.assertIn("duplicated", json.loads(out["body"])["message"])

    def test_delete_session_removes_session_and_mappings(self) -> None:
        self._seed_state(
            {
                "sessions": [SESSION_HSBC],
                "mappings": [
                    {"accountUid": "uid-current", "accountRecordId": "acc-hsbc-uk"}
                ],
            }
        )
        with patch.object(bank_sync, "_eb_request") as eb:
            out = lambda_handler(
                _admin_event("/v1/admin/banking/sessions/sess-hsbc", method="DELETE"),
                None,
            )
        eb.assert_called_once_with("DELETE", "/sessions/sess-hsbc")
        self.assertEqual(out["statusCode"], 200)
        stored = self._stored_state()
        self.assertEqual(stored["sessions"], [])
        self.assertEqual(stored["mappings"], [])

    def test_delete_unknown_session_404(self) -> None:
        out = lambda_handler(
            _admin_event("/v1/admin/banking/sessions/other", method="DELETE"), None
        )
        self.assertEqual(out["statusCode"], 404)

    def test_get_banking_returns_state(self) -> None:
        out = lambda_handler(_admin_event("/v1/admin/banking"), None)
        self.assertEqual(out["statusCode"], 200)
        body = json.loads(out["body"])
        self.assertTrue(body["enabled"])
        self.assertEqual(body["sessions"][0]["sessionId"], "sess-hsbc")
        self.assertEqual(body["callbackPath"], "/banking/callback")


class TestBankingSyncRoute(BankSyncTestCase):
    def test_sync_route_runs_and_persists_report(self) -> None:
        self._seed_state(
            {
                "sessions": [SESSION_HSBC],
                "mappings": [
                    {"accountUid": "uid-current", "accountRecordId": "acc-hsbc-uk"}
                ],
            }
        )
        self._seed_accounts_sheet([ACCOUNT_RECORD])
        balances = {
            "balances": [
                {
                    "balance_type": "XPCD",
                    "balance_amount": {"amount": "321.00", "currency": "GBP"},
                }
            ]
        }
        with patch.object(bank_sync, "_eb_request", return_value=balances):
            out = lambda_handler(
                _admin_event("/v1/admin/banking/sync", method="POST"), None
            )
        self.assertEqual(out["statusCode"], 200)
        body = json.loads(out["body"])
        self.assertEqual(body["results"][0]["status"], "ok")
        self.assertEqual(body["results"][0]["balanceType"], "XPCD")
        self.assertEqual(self._stored_accounts()[0]["recordedValue"], 321.0)

    def test_internal_worker_runs_sync(self) -> None:
        self._seed_state({"sessions": [], "mappings": []})
        out = lambda_handler({"internal": "bank_sync"}, None)
        self.assertEqual(out, {})
        self.assertIn("lastSync", self._stored_state())


if __name__ == "__main__":
    unittest.main()
