"""LinkedIn OAuth, posts, comments, images, and metrics without the network."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from test_support import FakeTable, install_aws_stubs

install_aws_stubs()

import linkedin_api  # noqa: E402
import linkedin_store  # noqa: E402
from linkedin_api import LinkedInApiError  # noqa: E402


def patch_load():
    return patch.object(linkedin_api, "load_credentials", side_effect=AssertionError("credentials were read again"))


def _ok(status: int, payload: dict | None = None, headers: dict | None = None):
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    return status, headers or {}, body


class LinkedInApiTests(unittest.TestCase):
    def tearDown(self) -> None:
        linkedin_api.set_transport_for_tests(None)

    def test_authorize_url_includes_the_posting_scopes(self) -> None:
        url = linkedin_api.authorize_url(client_id="client", redirect="https://admin.example/callback", state="abc")
        self.assertIn("client_id=client", url)
        self.assertIn("w_member_social", url)
        self.assertNotIn("w_organization_social", url)
        self.assertNotIn("r_member_postAnalytics", url)
        self.assertIn("state=abc", url)
        pages = linkedin_api.authorize_url(
            client_id="client",
            redirect="https://admin.example/callback",
            state="abc",
            include_organizations=True,
        )
        self.assertIn("w_organization_social", pages)
        self.assertIn("rw_organization_admin", pages)
        self.assertNotIn("r_member_postAnalytics", pages)
        analytics = linkedin_api.authorize_url(
            client_id="client",
            redirect="https://admin.example/callback",
            state="abc",
            include_member_analytics=True,
        )
        self.assertIn("r_member_postAnalytics", analytics)
        self.assertNotIn("w_organization_social", analytics)
        both = linkedin_api.authorize_url(
            client_id="client",
            redirect="https://admin.example/callback",
            state="abc",
            include_organizations=True,
            include_member_analytics=True,
        )
        self.assertIn("r_member_postAnalytics", both)
        self.assertIn("w_organization_social", both)

    def test_commentary_appends_a_missing_hashtag_and_escapes_parentheses(self) -> None:
        text = linkedin_api.commentary("A lesson (short).", ["Architecture"])
        self.assertIn("\\(short\\)", text)
        self.assertIn("#Architecture", text)

    def test_commentary_leaves_urls_and_hashtags_alone(self) -> None:
        text = linkedin_api.commentary("See https://example.com/my_page_(2) and #hong_kong.", [])
        self.assertIn("https://example.com/my_page_(2)", text)
        self.assertIn("#hong_kong", text)
        self.assertNotIn("\\_", text)

    def test_commentary_rejects_text_over_the_linkedin_limit(self) -> None:
        with self.assertRaises(LinkedInApiError):
            linkedin_api.commentary("(" * 2000, [])

    def test_oauth_state_expires_and_remembers_page_scope(self) -> None:
        table = FakeTable()
        linkedin_store.save_oauth_state(table, "abc", "sub", include_organizations=True)
        item = table.items[("LINKEDIN#oauth#abc", "META")]
        self.assertGreater(item["expiresAt"], 0)
        owner, pages, analytics = linkedin_store.consume_oauth_state(table, "abc")
        self.assertEqual((owner, pages, analytics), ("sub", True, False))

    def test_missing_credentials_are_cached(self) -> None:
        linkedin_api.reset_credentials_cache_for_tests()
        self.assertEqual(linkedin_api.credentials_status(), "missing")
        with patch_load():
            self.assertEqual(linkedin_api.credentials_status(), "missing")

    def test_page_author_requires_an_organization(self) -> None:
        with self.assertRaises(LinkedInApiError):
            linkedin_api.author_urn({"channel": "page", "memberId": "m"})
        self.assertEqual(
            linkedin_api.author_urn({"channel": "page", "organizationId": "99", "memberId": "m"}),
            "urn:li:organization:99",
        )

    def test_exchange_and_organizations(self) -> None:
        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del headers, body
            if method == "POST" and url.endswith("/accessToken"):
                return _ok(200, {"access_token": "token", "refresh_token": "refresh", "expires_in": 3600})
            if url.endswith("/userinfo"):
                return _ok(200, {"sub": "member1", "name": "Example Member"})
            if "organizationAcls" in url:
                return _ok(200, {"elements": [{"organization": "urn:li:organization:99", "role": "ADMINISTRATOR"}]})
            if url.endswith("/organizations/99"):
                return _ok(200, {"localizedName": "Example Page"})
            return _ok(404, {"message": "missing"})

        linkedin_api.set_transport_for_tests(transport)
        token = linkedin_api.exchange_code(
            client_id="client",
            client_secret="secret",
            code="code",
            redirect="https://admin.example/callback",
        )
        self.assertEqual(token["access_token"], "token")
        self.assertEqual(linkedin_api.userinfo("token")["memberId"], "member1")
        self.assertEqual(linkedin_api.list_organizations("token"), [{"id": "99", "name": "Example Page"}])

    def test_create_post_comment_and_counts(self) -> None:
        seen: dict[str, bytes | None] = {}

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del headers
            seen[f"{method} {url}"] = body
            if url.endswith("/posts"):
                return _ok(201, {}, {"x-restli-id": "urn:li:share:9"})
            if url.endswith("/comments"):
                return _ok(201, {})
            if url.endswith("/socialActions/urn%3Ali%3Ashare%3A9"):
                return _ok(200, {"likesSummary": {"totalLikes": 3}, "commentsSummary": {"totalFirstLevelComments": 1}})
            return _ok(404, {"message": "missing"})

        linkedin_api.set_transport_for_tests(transport)
        urn = linkedin_api.create_post("token", "urn:li:person:member1", "Hello")
        linkedin_api.create_comment("token", urn, "urn:li:person:member1", "First comment")
        counts = linkedin_api.social_counts("token", urn)
        self.assertEqual(urn, "urn:li:share:9")
        self.assertEqual(counts, {"reactions": 3, "comments": 1})
        self.assertIn(
            b"First comment", seen["POST https://api.linkedin.com/rest/socialActions/urn%3Ali%3Ashare%3A9/comments"]
        )

    def test_page_impressions_read_the_share_statistics(self) -> None:
        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers, body
            self.assertIn("organizationalEntity", url)
            self.assertIn("shares=List(", url)
            return _ok(200, {"elements": [{"totalShareStatistics": {"impressionCount": 12}}]})

        linkedin_api.set_transport_for_tests(transport)
        self.assertEqual(linkedin_api.page_impressions("token", "99", "urn:li:share:9"), 12)

    def test_page_impressions_use_the_ugc_post_parameter(self) -> None:
        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers, body
            self.assertIn("ugcPosts=List(", url)
            return _ok(200, {"elements": [{"totalShareStatistics": {"impressionCount": 2}}]})

        linkedin_api.set_transport_for_tests(transport)
        self.assertEqual(linkedin_api.page_impressions("token", "99", "urn:li:ugcPost:9"), 2)

    def test_member_impressions_read_the_lifetime_total(self) -> None:
        seen: list[str] = []

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers, body
            seen.append(url)
            return _ok(200, {"elements": [{"count": 12, "metricType": "IMPRESSION"}]})

        linkedin_api.set_transport_for_tests(transport)
        self.assertEqual(linkedin_api.member_impressions("token", "urn:li:share:9"), 12)
        self.assertIn("entity=(share:urn%3Ali%3Ashare%3A9)", seen[0])
        self.assertIn("queryType=IMPRESSION", seen[0])
        self.assertIn("aggregation=TOTAL", seen[0])

    def test_member_impressions_use_the_ugc_entity(self) -> None:
        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers, body
            self.assertIn("entity=(ugc:urn%3Ali%3AugcPost%3A9)", url)
            return _ok(200, {"elements": [{"count": 2, "metricType": "IMPRESSION"}]})

        linkedin_api.set_transport_for_tests(transport)
        self.assertEqual(linkedin_api.member_impressions("token", "urn:li:ugcPost:9"), 2)

    def test_member_impressions_leave_the_count_empty_when_denied(self) -> None:
        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, url, headers, body
            return _ok(403, {"message": "forbidden"})

        linkedin_api.set_transport_for_tests(transport)
        self.assertIsNone(linkedin_api.member_impressions("token", "urn:li:share:9"))

    def test_an_activity_urn_resolves_to_the_share_id(self) -> None:
        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers, body
            self.assertIn("/posts/urn%3Ali%3Aactivity%3A55", url)
            return _ok(200, {"id": "urn:li:share:55"})

        linkedin_api.set_transport_for_tests(transport)
        self.assertEqual(linkedin_api.resolve_share_urn("token", "urn:li:activity:55"), "urn:li:share:55")

    def test_a_failed_activity_lookup_returns_no_urn(self) -> None:
        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, url, headers, body
            return _ok(404, {"message": "not found"})

        linkedin_api.set_transport_for_tests(transport)
        self.assertEqual(linkedin_api.resolve_share_urn("token", "urn:li:activity:55"), "")

    def test_connection_target_selects_a_page(self) -> None:
        table = FakeTable()
        linkedin_store.save_connection(
            table,
            {
                "accessToken": "token",
                "memberId": "member1",
                "channel": "profile",
                "organizations": [{"id": "99", "name": "Example Page"}],
            },
        )
        public = linkedin_store.set_connection_target(table, "page", "99")
        self.assertEqual(public["channel"], "page")
        self.assertEqual(public["organizationName"], "Example Page")
        self.assertNotIn("accessToken", public)
