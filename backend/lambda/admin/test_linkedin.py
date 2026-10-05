"""LinkedIn draft queue: slots, guardrails, and the assisted workflow."""

from __future__ import annotations

import json
import unittest
from datetime import datetime
from unittest.mock import patch

from test_support import FakeTable, install_aws_stubs

install_aws_stubs()

import linkedin  # noqa: E402
import linkedin_draft  # noqa: E402
import linkedin_store  # noqa: E402
import runtime  # noqa: E402
from dispatch import lambda_handler  # noqa: E402
from linkedin_store import HKT, LinkedInError  # noqa: E402

ENABLED = {
    "RECORDS_TABLE_NAME": "records-test",
    "AUDIT_LOG_TABLE_NAME": "audit-test",
    "LINKEDIN_ENABLED": "true",
    "LINKEDIN_PUBLISH_ENABLED": "false",
    "ADMIN_WEB_ORIGIN": "https://admin.example.com",
    "INBOUND_MAIL_DOMAIN": "inbound.example.com",
}


def _event(path: str, method: str = "GET", body: dict | None = None) -> dict:
    event: dict = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "requestId": "req-linkedin",
            "authorizer": {"jwt": {"claims": {"sub": "admin-sub", "cognito:groups": "[admin]"}}},
        },
        "rawQueryString": "",
    }
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _body(response: dict) -> dict:
    return json.loads(response["body"])


class LinkedInStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = FakeTable()

    def test_default_slot_is_eight_thirty_hkt_on_tuesday_and_thursday(self) -> None:
        now = datetime(2026, 10, 5, 10, 0, tzinfo=HKT)
        slots = linkedin_store.next_slots(linkedin_store.default_settings(), now=now, count=2)
        self.assertEqual(slots[0], "2026-10-06T00:30:00.000Z")
        self.assertEqual(slots[1], "2026-10-08T00:30:00.000Z")

    def test_a_passed_tuesday_slot_moves_to_thursday(self) -> None:
        now = datetime(2026, 10, 6, 9, 0, tzinfo=HKT)
        slots = linkedin_store.next_slots(linkedin_store.default_settings(), now=now, count=1)
        self.assertEqual(slots[0], "2026-10-08T00:30:00.000Z")

    def test_guardrails_block_company_product_and_a_long_hook(self) -> None:
        settings = linkedin_store.default_settings()
        findings = linkedin_store.guardrails(
            "I built this at LX Software and it ships today.",
            "",
            [],
            settings,
        )
        self.assertTrue(any(row["code"] == "forbidden_word" for row in findings))
        product = linkedin_store.guardrails("We mirrored siutindei invoices.", "", [], settings)
        self.assertTrue(any(row["code"] == "product_mention" for row in product))
        long_hook = "x" * 211
        hook = linkedin_store.guardrails(long_hook, "", [], settings)
        self.assertTrue(any(row["code"] == "hook" for row in hook))
        self.assertIn("lx software", linkedin_store.BUILTIN_FORBIDDEN)

    def test_owner_forbidden_word_is_settings_not_a_builtin(self) -> None:
        settings = linkedin_store.default_settings()
        settings["forbiddenWords"] = ["acme corp"]
        findings = linkedin_store.guardrails("A note about Acme Corp.", "", [], settings)
        self.assertTrue(any("acme corp" in row["detail"] for row in findings))

    def test_approve_assigns_a_slot_and_an_edit_clears_it(self) -> None:
        settings = linkedin_store.default_settings()
        doc = linkedin_store.create_post(
            self.table,
            {"body": "A short hook.\n\nOne lesson.", "pillar": "architecture"},
            settings=settings,
        )
        approved = linkedin_store.approve_post(
            self.table,
            doc["postId"],
            "admin-sub",
            now=datetime(2026, 10, 5, 10, 0, tzinfo=HKT),
        )
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["slotAt"], "2026-10-06T00:30:00.000Z")
        edited = linkedin_store.update_post(
            self.table,
            doc["postId"],
            {"body": "A different hook.\n\nStill one lesson."},
        )
        self.assertEqual(edited["status"], "drafted")
        self.assertEqual(edited["slotAt"], "")

    def test_approve_refuses_a_failing_post(self) -> None:
        doc = linkedin_store.create_post(
            self.table,
            {"body": "Available immediately for a chat about systems."},
        )
        with self.assertRaises(LinkedInError):
            linkedin_store.approve_post(self.table, doc["postId"], "admin-sub")

    def test_mark_posted_requires_a_linkedin_url(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nDone."})
        with self.assertRaises(LinkedInError):
            linkedin_store.mark_posted(self.table, doc["postId"], "https://example.com/post")
        posted = linkedin_store.mark_posted(
            self.table,
            doc["postId"],
            "https://www.linkedin.com/feed/update/urn:li:share:1",
        )
        self.assertEqual(posted["status"], "published")

    def test_duplicate_body_is_rejected(self) -> None:
        linkedin_store.create_post(self.table, {"body": "Same hook.\n\nSame lesson."})
        with self.assertRaises(LinkedInError):
            linkedin_store.create_post(self.table, {"body": "Same   hook.\n\nSame lesson."})

    def test_weekly_budget_stops_generation(self) -> None:
        settings = linkedin_store.default_settings()
        settings["maxUsdPerMonth"] = 0
        linkedin_store.save_settings(self.table, settings)

        def complete(_messages):
            return {"body": "A short hook.\n\nLesson.", "firstComment": "", "hashtags": [], "pillar": "architecture"}, 0.2

        with self.assertRaises(LinkedInError):
            linkedin_draft.generate_drafts(self.table, count=1, complete=complete)

    def test_generation_stores_a_draft_and_spends(self) -> None:
        calls = {"n": 0}

        def complete(_messages):
            calls["n"] += 1
            return {
                "body": "The hook fits.\n\nThen the lesson, without a pitch.",
                "firstComment": "",
                "hashtags": ["Architecture"],
                "pillar": "architecture",
            }, 0.02

        result = linkedin_draft.generate_drafts(self.table, count=1, pillar="leadership", complete=complete)
        self.assertEqual(len(result["posts"]), 1)
        self.assertEqual(result["posts"][0]["pillar"], "leadership")
        self.assertEqual(calls["n"], 1)
        self.assertAlmostEqual(linkedin_store.month_spend(self.table), 0.02)

    def test_failing_draft_gets_one_rewrite(self) -> None:
        calls = {"n": 0}

        def complete(_messages):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"body": "LX Software taught me this.", "firstComment": "", "hashtags": [], "pillar": "delivery"}, 0.01
            return {"body": "A rewrite hook.\n\nThe lesson stands alone.", "firstComment": "", "hashtags": [], "pillar": "delivery"}, 0.01

        result = linkedin_draft.generate_drafts(self.table, count=1, complete=complete)
        self.assertEqual(calls["n"], 2)
        self.assertIn("rewrite hook", result["posts"][0]["body"])
        self.assertNotIn("LX Software", result["posts"][0]["body"])


class LinkedInHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = FakeTable()
        patcher = patch.object(runtime, "_ddb")
        mock_ddb = patcher.start()
        self.addCleanup(patcher.stop)
        mock_ddb.Table.return_value = self.table
        self.env = patch.dict("os.environ", ENABLED, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_writes_are_refused_when_the_switch_is_off(self) -> None:
        with patch.dict("os.environ", {"LINKEDIN_ENABLED": "false"}):
            overview = lambda_handler(_event("/lx-software/linkedin"), None)
            self.assertEqual(overview["statusCode"], 200)
            self.assertFalse(_body(overview)["enabled"])
            created = lambda_handler(
                _event("/lx-software/linkedin/posts", "POST", {"body": "A short hook."}),
                None,
            )
            self.assertEqual(created["statusCode"], 403)

    def test_create_approve_and_mark_posted(self) -> None:
        created = lambda_handler(
            _event(
                "/lx-software/linkedin/posts",
                "POST",
                {"body": "A short hook.\n\nOne lesson.", "pillar": "platforms"},
            ),
            None,
        )
        self.assertEqual(created["statusCode"], 201)
        post_id = _body(created)["item"]["postId"]
        approved = lambda_handler(
            _event(f"/lx-software/linkedin/posts/{post_id}/approve", "POST", {}),
            None,
        )
        self.assertEqual(approved["statusCode"], 200)
        self.assertEqual(_body(approved)["item"]["status"], "approved")
        posted = lambda_handler(
            _event(
                f"/lx-software/linkedin/posts/{post_id}/mark-posted",
                "POST",
                {"url": "https://www.linkedin.com/feed/update/urn:li:share:9"},
            ),
            None,
        )
        self.assertEqual(_body(posted)["item"]["status"], "published")

    def test_due_reminder_sends_once(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nDue now."})
        doc["status"] = "approved"
        doc["slotAt"] = "2020-01-01T00:30:00.000Z"
        linkedin_store.put_post(self.table, doc)
        linkedin_store.save_settings(self.table, {**linkedin_store.default_settings(), "notifyEmail": "owner@example.com"})
        with patch.object(linkedin, "send_notice", return_value=True) as send:
            first = linkedin.handle_publish_due({})
            second = linkedin.handle_publish_due({})
        self.assertEqual(first["reminded"], 1)
        self.assertEqual(second["reminded"], 0)
        send.assert_called_once()
        self.assertIn("linkedin-post=", send.call_args.args[2])

    def test_publish_switch_does_not_post(self) -> None:
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true"}):
            result = linkedin.handle_publish_due({})
        self.assertEqual(result["skipped"], "publish_not_implemented")

    def test_generate_queues_a_job(self) -> None:
        with patch("board_async.try_invoke_event", return_value=True) as invoke:
            response = lambda_handler(_event("/lx-software/linkedin/generate", "POST", {"count": 1}), None)
        self.assertEqual(response["statusCode"], 202)
        invoke.assert_called_once()
        self.assertEqual(invoke.call_args.args[0]["internal"], "linkedin_generate")
