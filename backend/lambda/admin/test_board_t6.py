"""T6: App Store Connect + Google Play reads, review replies, release-notes drafts."""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404
import unittest
from typing import Any
from unittest.mock import patch
from urllib import request as urlrequest

import board_cache
import board_context
import board_store
import board_stores
from board_tools import REGISTRY, ToolContext, execute_call
from test_board_tools import ToolsTestCase


def _openssl_pem(kind: str) -> str:
    if kind == "ec":
        raw = subprocess.run(  # nosec B603 B607
            ["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout"],
            capture_output=True,
            check=True,
        )
        pkcs8 = subprocess.run(  # nosec B603 B607
            ["openssl", "pkcs8", "-topk8", "-nocrypt"],
            input=raw.stdout,
            capture_output=True,
            check=True,
        )
        return pkcs8.stdout.decode()
    rsa = subprocess.run(  # nosec B603 B607
        ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048"],
        capture_output=True,
        check=True,
    )
    return rsa.stdout.decode()


class FakeStoresHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(self, req: urlrequest.Request, timeout=None):  # noqa: ARG002
        method = req.get_method()
        url = req.full_url
        body: Any = None
        if req.data:
            raw = req.data.decode("utf-8")
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = raw
        self.calls.append((method, url, body))
        if "oauth2.googleapis.com/token" in url:
            payload: Any = {"access_token": "play-oauth-test", "expires_in": 3600}  # nosec B105
        elif "/v1/apps/app-1/customerReviews" in url:
            payload = {
                "data": [
                    {
                        "id": "rev-apple-1",
                        "type": "customerReviews",
                        "attributes": {
                            "rating": 5,
                            "title": "Great",
                            "body": "Email me at parent@example.com",
                            "reviewerNickname": "Wendy",
                            "createdDate": "2026-09-01T00:00:00Z",
                            "territory": "HKG",
                        },
                        "relationships": {"response": {"data": None}},
                    }
                ]
            }
        elif "/v1/apps/app-1/appStoreVersions" in url:
            payload = {
                "data": [
                    {
                        "attributes": {
                            "versionString": "1.4.0",
                            "appStoreState": "READY_FOR_SALE",
                        }
                    }
                ]
            }
        elif "/v1/apps/app-1/perfPowerMetrics" in url:
            payload = {
                "productData": [
                    {
                        "platform": "iOS",
                        "metricCategories": [
                            {
                                "identifier": "HANG",
                                "metrics": [
                                    {
                                        "identifier": "hangRate",
                                        "unit": {"identifier": "hoursPerHour"},
                                        "datasets": [
                                            {
                                                "filterCriteria": {"percentile": "percentile.fifty", "device": "all_iphones"},
                                                "points": [{"version": "1.3.0", "value": 0.05}, {"version": "1.4.0", "value": 0.02}],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        elif "/v1/apps/app-1" in url and method == "GET":
            payload = {"data": {"attributes": {"name": "siutindei", "bundleId": "com.siutindei.app"}}}
        elif "/v1/salesReports" in url:
            payload = {"data": []}
        elif "/v1/customerReviewResponses" in url and method == "POST":
            payload = {"data": {"id": "resp-1"}}
        elif "/androidpublisher/v3/applications/com.siutindei.app/reviews/" in url and method == "POST":
            payload = {"result": {"replyText": "Thanks"}}
        elif "/androidpublisher/v3/applications/com.siutindei.app/reviews" in url:
            payload = {
                "reviews": [
                    {
                        "reviewId": "rev-play-1",
                        "authorName": "Alex",
                        "comments": [
                            {
                                "userComment": {
                                    "text": "Call 9123 4567 please",
                                    "starRating": 4,
                                    "lastModified": {"seconds": "1756900000"},
                                }
                            }
                        ],
                    }
                ]
            }
        elif url.endswith("/crashRateMetricSet") and method == "GET":
            payload = {
                "freshnessInfo": {
                    "freshnesses": [
                        {"aggregationPeriod": "DAILY", "latestEndTime": {"year": 2026, "month": 9, "day": 3}}
                    ]
                }
            }
        elif "crashRateMetricSet:query" in url:
            payload = {
                "rows": [
                    {
                        "aggregationPeriod": "DAILY",
                        "startTime": {"year": 2026, "month": 9, "day": 2},
                        "metrics": [
                            {"metric": "crashRate", "decimalValue": {"value": "0.01"}},
                            {"metric": "distinctUsers", "decimalValue": {"value": "120"}},
                        ],
                    },
                    {
                        "aggregationPeriod": "DAILY",
                        "startTime": {"year": 2026, "month": 9, "day": 1},
                        "metrics": [
                            {"metric": "crashRate", "decimalValue": {"value": "0.03"}},
                            {"metric": "distinctUsers", "decimalValue": {"value": "110"}},
                        ],
                    },
                ]
            }
        else:
            payload = {"data": []}

        class _Resp:
            def read(self) -> bytes:
                return json.dumps(payload).encode()

            def __enter__(self) -> "_Resp":
                return self

            def __exit__(self, *args: Any) -> None:
                return None

        return _Resp()


class StoresTestCase(ToolsTestCase):
    def setUp(self) -> None:
        super().setUp()
        board_stores.reset_caches_for_tests()
        os.environ["APP_STORE_CONNECT_TOKEN"] = "asc-test-token"  # nosec B105
        os.environ["APP_STORE_CONNECT_APP_ID"] = "app-1"
        os.environ["GOOGLE_PLAY_ACCESS_TOKEN"] = "play-test-token"  # nosec B105
        os.environ["GOOGLE_PLAY_PACKAGE_NAME"] = "com.siutindei.app"
        os.environ["APP_STORE_CONNECT_KEY"] = json.dumps(
            {"keyId": "KEY1", "issuerId": "ISS1", "privateKey": "unused", "appId": "app-1"}
        )
        os.environ["GOOGLE_PLAY_SERVICE_ACCOUNT"] = json.dumps(
            {
                "client_email": "play@example.iam.gserviceaccount.com",
                "private_key": "unused",
                "packageName": "com.siutindei.app",
            }
        )

        def _clear_store_env() -> None:
            for key in (
                "APP_STORE_CONNECT_TOKEN",
                "APP_STORE_CONNECT_KEY",
                "APP_STORE_CONNECT_APP_ID",
                "GOOGLE_PLAY_ACCESS_TOKEN",
                "GOOGLE_PLAY_SERVICE_ACCOUNT",
                "GOOGLE_PLAY_PACKAGE_NAME",
            ):
                os.environ.pop(key, None)
            board_stores.reset_caches_for_tests()

        self.addCleanup(_clear_store_env)
        self.http = FakeStoresHttp()
        p = patch.object(board_stores, "_urlopen", self.http)
        p.start()
        self.addCleanup(p.stop)

    def _ctx(self, persona: str = "cmo", *, actor: str = "persona", global_mode: str = "propose") -> ToolContext:
        settings = board_store.load_settings(self.table)
        settings["tools"]["globalMode"] = global_mode
        return ToolContext(
            table=self.table,
            settings=settings,
            persona_id=persona,
            display_name=persona.upper(),
            actor=actor,
            owner_sub="owner-1" if actor == "owner" else "",
        )


class TestStoresReads(StoresTestCase):
    def test_metrics_and_reviews_mask_pii(self) -> None:
        ctx = self._ctx()
        metrics = board_stores.op_metrics(ctx, {})
        self.assertEqual(metrics["apple"]["name"], "siutindei")
        self.assertEqual(metrics["apple"]["averageRating"], 5)
        self.assertEqual(metrics["play"]["packageName"], "com.siutindei.app")
        # No ASC_VENDOR_NUMBER in this fixture: downloads are unavailable, never a fake zero.
        self.assertFalse(metrics["apple"]["downloads"]["available"])
        self.assertIn("ASC_VENDOR_NUMBER", metrics["apple"]["downloads"]["reason"])
        self.assertIsNone(metrics["apple"]["installs"])
        self.assertIsNone(metrics["play"]["installs"])
        self.assertEqual(metrics["play"]["installsNote"], "not available from these APIs")
        self.assertFalse(any("errorCountMetricSet" in url for _m, url, _b in self.http.calls))
        self.assertFalse(metrics["cached"])
        again = board_stores.op_metrics(ctx, {})
        self.assertTrue(again["cached"])
        reviews = board_stores.op_list_reviews(ctx, {"store": "both", "limit": 10})
        bodies = [r["body"] for r in reviews["reviews"]]
        self.assertTrue(any("contact#hidden" in b for b in bodies))
        self.assertTrue(any("phone#hidden" in b for b in bodies))
        self.assertFalse(any("parent@example.com" in b or "9123 4567" in b for b in bodies))

    def test_crashes_and_ratings_hit_both_stores(self) -> None:
        ctx = self._ctx()
        crashes = board_stores.op_crashes(ctx, {})
        self.assertEqual(crashes["apple"]["kind"], "hangs")
        self.assertEqual(crashes["apple"]["metrics"][0]["identifier"], "hangRate")
        self.assertEqual(crashes["apple"]["metrics"][0]["value"], 0.02)
        self.assertEqual(crashes["apple"]["metrics"][0]["version"], "1.4.0")
        self.assertIn("not crash counts", crashes["apple"]["note"])
        self.assertTrue(crashes["play"]["available"])
        self.assertEqual(crashes["play"]["latestCrashRate"], 0.01)
        self.assertEqual(crashes["play"]["latestDate"], "2026-09-02")
        self.assertEqual(crashes["play"]["windowEnd"], "2026-09-03")
        self.assertEqual([d["date"] for d in crashes["play"]["days"]], ["2026-09-01", "2026-09-02"])
        query = next(b for m, url, b in self.http.calls if "crashRateMetricSet:query" in url)
        self.assertEqual(query["metrics"], ["crashRate", "distinctUsers"])
        self.assertEqual(query["timelineSpec"]["endTime"]["day"], 3)
        ratings = board_stores.op_ratings(ctx, {})
        self.assertEqual(ratings["apple"]["averageRating"], 5)
        self.assertEqual(ratings["play"]["reviewCount"], 1)

    def test_cache_refresh_and_context_digest(self) -> None:
        with (
            patch("board_cache.board_aws.refresh_caches", return_value={"aws:monthly_cost": "ok"}),
            patch("board_cache.board_security.refresh_caches", return_value={"security:cognito": "ok"}),
        ):
            notes = board_cache.refresh_all(self.table)
        self.assertEqual(notes["stores"]["stores:metrics"], "ok")
        pack = board_context.build_context_pack(self.table, board_store.load_settings(self.table), roster=[])
        self.assertIn("App stores", pack["text"])
        self.assertIn("App Store 5", pack["text"])


class TestStoresWrites(StoresTestCase):
    def test_cmo_review_reply_is_proposal_until_owner_approves(self) -> None:
        ctx = self._ctx("cmo")
        out = execute_call(
            ctx,
            REGISTRY["stores_reply_review"],
            {"store": "apple", "reviewId": "rev-apple-1", "message": "Thanks!", "reason": "Happy parent."},
        )
        self.assertEqual(out.status, "pending_approval")
        self.assertFalse(any("/customerReviewResponses" in url for _m, url, _b in self.http.calls))

    def test_owner_reply_hits_apple_and_play(self) -> None:
        owner = self._ctx("cmo", actor="owner")
        apple = execute_call(
            owner,
            REGISTRY["stores_reply_review"],
            {"store": "apple", "reviewId": "rev-apple-1", "message": "Thanks!", "reason": "Approved."},
        )
        self.assertEqual(apple.status, "ok")
        play = execute_call(
            owner,
            REGISTRY["stores_reply_review"],
            {"store": "play", "reviewId": "rev-play-1", "message": "Thanks!", "reason": "Approved."},
        )
        self.assertEqual(play.status, "ok")
        self.assertTrue(any(m == "POST" and "/v1/customerReviewResponses" in url for m, url, _ in self.http.calls))
        self.assertTrue(any(m == "POST" and ":reply" in url for m, url, _ in self.http.calls))

    def test_cmo_act_sends_review_reply(self) -> None:
        ctx = self._ctx("cmo", global_mode="act")
        out = execute_call(
            ctx,
            REGISTRY["stores_reply_review"],
            {"store": "apple", "reviewId": "rev-apple-1", "message": "Thanks!", "reason": "CMO act."},
        )
        self.assertEqual(out.status, "ok")
        self.assertTrue(any(m == "POST" and "/v1/customerReviewResponses" in url for m, url, _ in self.http.calls))

    def test_release_notes_always_propose_even_at_act(self) -> None:
        ctx = self._ctx("cmo", global_mode="act")
        out = execute_call(
            ctx,
            REGISTRY["stores_draft_release_notes"],
            {"store": "both", "notes": "Bug fixes in Tuen Mun bookings.", "reason": "1.4.1."},
        )
        self.assertEqual(out.status, "pending_approval")
        owner = self._ctx("cmo", actor="owner")
        ran = execute_call(
            owner,
            REGISTRY["stores_draft_release_notes"],
            {"store": "both", "version": "1.4.1", "notes": "Bug fixes.", "reason": "Approved."},
        )
        self.assertEqual(ran.status, "ok")
        self.assertFalse(ran.result.get("published"))
        actions = board_store.list_actions(self.table)
        self.assertTrue(any("Release notes" in str(a.get("title") or "") for a in actions))

    def test_cpo_cannot_act_on_reviews(self) -> None:
        ctx = self._ctx("cpo", global_mode="act")
        out = execute_call(
            ctx,
            REGISTRY["stores_reply_review"],
            {"store": "play", "reviewId": "rev-play-1", "message": "Thanks!", "reason": "CPO."},
        )
        self.assertEqual(out.status, "pending_approval")


class TestStoresJwt(unittest.TestCase):
    def test_es256_and_rs256_round_trip_headers(self) -> None:
        try:
            ec = _openssl_pem("ec")
            rsa = _openssl_pem("rsa")
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            self.skipTest(f"openssl unavailable: {exc}")
        es = board_stores.sign_jwt(
            {"alg": "ES256", "kid": "K", "typ": "JWT"},
            {"iss": "issuer", "aud": "appstoreconnect-v1"},
            ec,
        )
        rs = board_stores.sign_jwt(
            {"alg": "RS256", "typ": "JWT"},
            {"iss": "sa@example.com", "aud": board_stores.PLAY_TOKEN_URL},
            rsa,
        )
        self.assertEqual(len(es.split(".")), 3)
        self.assertEqual(len(rs.split(".")), 3)
        self.assertTrue(es.startswith("eyJ"))
        self.assertTrue(rs.startswith("eyJ"))


class TestStoresUnconfigured(ToolsTestCase):
    def test_reads_raise_when_secrets_missing(self) -> None:
        board_stores.reset_caches_for_tests()
        for key in (
            "APP_STORE_CONNECT_TOKEN",
            "APP_STORE_CONNECT_KEY",
            "APP_STORE_CONNECT_KEY_SECRET_ARN",
            "APP_STORE_CONNECT_APP_ID",
            "GOOGLE_PLAY_ACCESS_TOKEN",
            "GOOGLE_PLAY_SERVICE_ACCOUNT",
            "GOOGLE_PLAY_SERVICE_ACCOUNT_SECRET_ARN",
            "GOOGLE_PLAY_PACKAGE_NAME",
        ):
            os.environ.pop(key, None)
        self.addCleanup(board_stores.reset_caches_for_tests)
        self.assertFalse(board_stores.configured())
        notes = board_stores.refresh_caches(self.table)
        self.assertEqual(notes["stores:metrics"], "skipped")
        ctx = ToolContext(table=self.table, settings=board_store.load_settings(self.table), persona_id="cmo")
        with self.assertRaises(board_stores.StoresError):
            board_stores.op_metrics(ctx, {})


if __name__ == "__main__":
    unittest.main()
