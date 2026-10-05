"""LinkedIn OAuth, posts, comments, images, and metrics without the network."""

from __future__ import annotations

import json
import unittest

from test_support import FakeTable, install_aws_stubs

install_aws_stubs()

import linkedin_api  # noqa: E402
import linkedin_store  # noqa: E402
from linkedin_api import LinkedInApiError  # noqa: E402


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
        self.assertIn("w_organization_social", url)
        self.assertIn("rw_organization_admin", url)
        self.assertIn("state=abc", url)

    def test_commentary_appends_a_missing_hashtag_and_escapes_parentheses(self) -> None:
        text = linkedin_api.commentary("A lesson (short).", ["Architecture"])
        self.assertIn("\\(short\\)", text)
        self.assertIn("#Architecture", text)

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
        self.assertIn(b"First comment", seen["POST https://api.linkedin.com/rest/socialActions/urn%3Ali%3Ashare%3A9/comments"])

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
