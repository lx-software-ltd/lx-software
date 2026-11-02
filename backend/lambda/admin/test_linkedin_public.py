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
                "metrics": {"impressions": 26200, "reactions": 180, "comments": 20},
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
        self.assertEqual(item["metrics"]["impressions"], 26200)
        self.assertEqual(item["publishedAt"], "2026-10-30T00:30:00.000Z")
        self.assertEqual(item["url"], "https://www.linkedin.com/feed/update/urn:li:share:1")
        self.assertEqual(item["image"], {"status": "ready", "caption": "A line."})
        encoded = json.dumps(item)
        self.assertNotIn("should-not-leak", encoded)
        self.assertNotIn("organizationId", encoded)
        self.assertNotIn("secret.png", encoded)
        self.assertNotIn("a desk at night", encoded)
        self.assertNotIn("Unpublished draft.", encoded)
