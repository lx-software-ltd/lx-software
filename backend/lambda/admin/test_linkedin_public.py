"""Published LinkedIn posts exposed to a public API key."""

from __future__ import annotations

import json
import unittest

from test_support import FakeTable, install_aws_stubs

install_aws_stubs()

import board_public_api  # noqa: E402
import linkedin_public  # noqa: E402
import linkedin_store  # noqa: E402


class LinkedInPublicPostsTests(unittest.TestCase):
    def test_path_matches_the_scope_constant(self) -> None:
        self.assertEqual(linkedin_public.PATH, board_public_api.LINKEDIN_POSTS_PATH)

    def test_only_published_posts_and_no_secrets(self) -> None:
        table = FakeTable()
        linkedin_store.put_post(
            table,
            {
                "postId": "post_pub",
                "status": "published",
                "pillar": "personal",
                "seedId": "",
                "body": "A post about Hong Kong.",
                "firstComment": "",
                "hashtags": ["HongKong"],
                "channel": "profile",
                "slotAt": "2026-10-30T00:30:00.000Z",
                "createdAt": "2026-10-29T12:00:00.000Z",
                "platform": {
                    "url": "https://www.linkedin.com/feed/update/urn:li:share:1",
                    "publishedAt": "2026-10-30T00:30:00.000Z",
                    "organizationId": "999",
                },
                "metrics": {
                    "impressions": 26200,
                    "reactions": 180,
                    "comments": 20,
                    "pulledAt": "2026-10-30T01:00:00.000Z",
                    "error": "member analytics denied",
                    "unavailable": False,
                },
                "image": {
                    "status": "ready",
                    "contentType": "image/png",
                    "caption": "A line.",
                    "scene": "a desk at night",
                    "key": "linkedin/posts/secret.png",
                },
                "accessToken": "should-not-leak",
            },
        )
        linkedin_store.put_post(
            table,
            {
                "postId": "post_draft",
                "status": "drafted",
                "body": "Unpublished draft.",
                "createdAt": "2026-10-29T12:00:00.000Z",
            },
        )
        payload = linkedin_public.published_posts(table)
        self.assertEqual([row["postId"] for row in payload["items"]], ["post_pub"])
        item = payload["items"][0]
        self.assertEqual(item["body"], "A post about Hong Kong.")
        self.assertEqual(
            item["metrics"],
            {"impressions": 26200, "reactions": 180, "comments": 20},
        )
        self.assertEqual(item["publishedAt"], "2026-10-30T00:30:00.000Z")
        self.assertEqual(item["url"], "https://www.linkedin.com/feed/update/urn:li:share:1")
        self.assertEqual(item["image"], {"status": "ready", "caption": "A line."})
        encoded = json.dumps(item)
        self.assertNotIn("should-not-leak", encoded)
        self.assertNotIn("organizationId", encoded)
        self.assertNotIn("secret.png", encoded)
        self.assertNotIn("a desk at night", encoded)
        self.assertNotIn("Unpublished draft.", encoded)
        self.assertNotIn("member analytics denied", encoded)
        self.assertNotIn("pulledAt", encoded)

    def test_follows_every_index_page(self) -> None:
        pages = [
            {
                "Items": [_stored("post_a", "2026-10-01T00:30:00.000Z")],
                "LastEvaluatedKey": {"gsi1pk": "LINKEDIN#posts#published", "gsi1sk": "1#post_a"},
            },
            {"Items": [_stored("post_b", "2026-10-08T00:30:00.000Z")]},
        ]

        class Pages:
            def __init__(self) -> None:
                self.calls: list[dict | None] = []

            def query(self, **kwargs):
                self.calls.append(kwargs.get("ExclusiveStartKey"))
                return pages[len(self.calls) - 1]

        table = Pages()
        payload = linkedin_public.published_posts(table)
        self.assertEqual([row["postId"] for row in payload["items"]], ["post_a", "post_b"])
        self.assertIsNone(table.calls[0])
        self.assertEqual(table.calls[1]["gsi1sk"], "1#post_a")
        self.assertNotIn("truncated", payload)

    def test_status_drafted_returns_drafts_and_keeps_secrets_off(self) -> None:
        table = FakeTable()
        linkedin_store.put_post(
            table,
            {
                "postId": "post_pub",
                "status": "published",
                "body": "Already out.",
                "slotAt": "2026-10-30T00:30:00.000Z",
                "createdAt": "2026-10-29T12:00:00.000Z",
            },
        )
        linkedin_store.put_post(
            table,
            {
                "postId": "post_draft",
                "status": "drafted",
                "pillar": "platforms",
                "seedId": "cloudfront-extensionless",
                "body": "Unpublished draft about a refresh.",
                "firstComment": "The three lines of the fix.",
                "hashtags": ["cloud"],
                "slotAt": "",
                "createdAt": "2026-11-01T12:00:00.000Z",
                "accessToken": "should-not-leak",
                "generation": {"model": "secret-model", "voiceHash": "abc"},
                "image": {
                    "status": "ready",
                    "caption": "A spoken line.",
                    "scene": "a desk the prompt must not leave",
                    "key": "linkedin/posts/secret.png",
                },
            },
        )
        code, payload = linkedin_public.posts_response(table, {"status": "drafted"})
        self.assertEqual(code, 200)
        self.assertEqual(payload["status"], ["drafted"])
        self.assertEqual([row["postId"] for row in payload["items"]], ["post_draft"])
        item = payload["items"][0]
        self.assertEqual(item["status"], "drafted")
        self.assertEqual(item["body"], "Unpublished draft about a refresh.")
        self.assertEqual(item["firstComment"], "The three lines of the fix.")
        self.assertEqual(item["image"], {"status": "ready", "caption": "A spoken line."})
        encoded = json.dumps(payload)
        self.assertNotIn("Already out.", encoded)
        self.assertNotIn("should-not-leak", encoded)
        self.assertNotIn("secret-model", encoded)
        self.assertNotIn("secret.png", encoded)
        self.assertNotIn("a desk the prompt must not leave", encoded)
        self.assertNotIn("voiceHash", encoded)

    def test_status_all_and_a_list_and_a_bad_value(self) -> None:
        table = FakeTable()
        for post_id, status in (
            ("post_draft", "drafted"),
            ("post_ok", "approved"),
            ("post_pub", "published"),
        ):
            linkedin_store.put_post(
                table,
                {
                    "postId": post_id,
                    "status": status,
                    "body": post_id,
                    "slotAt": "2026-10-01T00:30:00.000Z",
                    "createdAt": "2026-10-01T00:30:00.000Z",
                },
            )
        code, payload = linkedin_public.posts_response(table, {"status": "all"})
        self.assertEqual(code, 200)
        self.assertEqual(
            sorted(row["postId"] for row in payload["items"]),
            ["post_draft", "post_ok", "post_pub"],
        )
        code, payload = linkedin_public.posts_response(table, {"status": " Drafted, approved "})
        self.assertEqual(code, 200)
        self.assertEqual(payload["status"], ["drafted", "approved"])
        self.assertEqual(
            sorted(row["postId"] for row in payload["items"]),
            ["post_draft", "post_ok"],
        )
        code, payload = linkedin_public.posts_response(table, {"status": "ideas"})
        self.assertEqual(code, 400)
        self.assertIn("status", payload["message"])
        code, payload = linkedin_public.posts_response(table, None)
        self.assertEqual(code, 200)
        self.assertEqual([row["postId"] for row in payload["items"]], ["post_pub"])
        self.assertNotIn("status", payload)
        self.assertEqual(payload["items"][0]["status"], "published")


class LinkedInPublicWriteTests(unittest.TestCase):
    def test_create_update_and_archive_round_trip(self) -> None:
        table = FakeTable()
        code, payload = linkedin_public.handle(
            table,
            "POST",
            linkedin_public.PATH,
            {
                "body": '{"body":"A hook about a 20 KB limit.","firstComment":"The policy line.","hashtags":["CDK"],"pillar":"platforms"}'
            },
        )
        self.assertEqual(code, 201)
        item = payload["item"]
        self.assertEqual(item["status"], "drafted")
        self.assertEqual(item["pillar"], "platforms")
        self.assertEqual(item["hashtags"], ["CDK"])
        self.assertEqual(item["firstComment"], "The policy line.")
        self.assertIsNone(item["image"])
        encoded = json.dumps(payload)
        self.assertNotIn("guardrails", encoded)
        self.assertNotIn("generation", encoded)
        post_id = item["postId"]

        code, payload = linkedin_public.handle(table, "GET", f"{linkedin_public.PATH}/{post_id}", {})
        self.assertEqual(code, 200)
        self.assertEqual(payload["item"]["body"], "A hook about a 20 KB limit.")

        code, payload = linkedin_public.handle(
            table,
            "PUT",
            f"{linkedin_public.PATH}/{post_id}",
            {"body": '{"body":"A different hook about the same limit.","firstComment":"Still the policy line."}'},
        )
        self.assertEqual(code, 200)
        self.assertEqual(payload["item"]["body"], "A different hook about the same limit.")
        self.assertEqual(payload["item"]["hashtags"], ["CDK"])
        self.assertEqual(payload["item"]["pillar"], "platforms")

        code, payload = linkedin_public.handle(table, "DELETE", f"{linkedin_public.PATH}/{post_id}", {})
        self.assertEqual(code, 200)
        self.assertEqual(payload["item"]["status"], "archived")
        again, again_body = linkedin_public.handle(table, "DELETE", f"{linkedin_public.PATH}/{post_id}", {})
        self.assertEqual(again, 200)
        self.assertEqual(again_body["item"]["status"], "archived")

    def test_create_rejects_a_missing_body_and_a_duplicate(self) -> None:
        table = FakeTable()
        code, payload = linkedin_public.handle(table, "POST", linkedin_public.PATH, {"body": "{}"})
        self.assertEqual(code, 400)
        self.assertIn("body", payload["message"])
        code, _payload = linkedin_public.handle(
            table,
            "POST",
            linkedin_public.PATH,
            {"body": '{"body":"Same hook. Same lesson."}'},
        )
        self.assertEqual(code, 201)
        code, payload = linkedin_public.handle(
            table,
            "POST",
            linkedin_public.PATH,
            {"body": '{"body":"Same hook. Same lesson."}'},
        )
        self.assertEqual(code, 400)
        self.assertIn("similar", payload["message"])

    def test_published_posts_cannot_be_edited_or_archived(self) -> None:
        table = FakeTable()
        linkedin_store.put_post(
            table,
            {
                "postId": "post_pub",
                "status": "published",
                "body": "Already out.",
                "pillar": "architecture",
                "createdAt": "2026-10-01T00:30:00.000Z",
            },
        )
        path = f"{linkedin_public.PATH}/post_pub"
        code, payload = linkedin_public.handle(table, "PUT", path, {"body": '{"body":"A rewrite."}'})
        self.assertEqual(code, 400)
        code, payload = linkedin_public.handle(table, "DELETE", path, {})
        self.assertEqual(code, 400)
        self.assertIn("published", payload["message"])
        stored = linkedin_store.get_post(table, "post_pub")
        assert stored is not None
        self.assertEqual(stored["status"], "published")
        self.assertEqual(stored["body"], "Already out.")

    def test_wrong_method_and_missing_post(self) -> None:
        table = FakeTable()
        code, payload = linkedin_public.handle(table, "PUT", linkedin_public.PATH, {"body": "{}"})
        self.assertEqual(code, 405)
        code, payload = linkedin_public.handle(table, "DELETE", linkedin_public.PATH, {})
        self.assertEqual(code, 405)
        code, payload = linkedin_public.handle(table, "GET", f"{linkedin_public.PATH}/missing", {})
        self.assertEqual(code, 404)
        code, payload = linkedin_public.handle(table, "POST", f"{linkedin_public.PATH}/li_abc/approve", {"body": "{}"})
        self.assertEqual(code, 404)


def _stored(post_id: str, slot: str) -> dict:
    return {
        "pk": f"LINKEDIN#post#{post_id}",
        "sk": "META",
        "gsi1pk": "LINKEDIN#posts#published",
        "gsi1sk": f"{slot}#{post_id}",
        "postId": post_id,
        "status": "published",
        "body": post_id,
        "slotAt": slot,
        "createdAt": slot,
    }
