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

    def test_phrase_boundaries_ignore_longer_words(self) -> None:
        settings = linkedin_store.default_settings()
        allowed = linkedin_store.guardrails(
            "I hire mentors, and the word interimistic is not a status.",
            "",
            [],
            settings,
        )
        self.assertFalse(any(row["code"] == "forbidden_word" for row in allowed))
        blocked = linkedin_store.guardrails("Please hire me. I am interim.", "", [], settings)
        details = " ".join(row["detail"] for row in blocked)
        self.assertIn("hire me", details)
        self.assertIn("interim", details)
        product = linkedin_store.guardrails("A siutindeiish note.", "", [], settings)
        self.assertFalse(any(row["code"] == "product_mention" for row in product))

    def test_phone_and_hashtag_checks_skip_plain_numbers(self) -> None:
        settings = linkedin_store.default_settings()
        plain = linkedin_store.guardrails("We served 10000000 requests. See issue #42.", "", [], settings)
        self.assertFalse(any(row["code"] in ("phone", "hashtags") for row in plain))
        plus = linkedin_store.guardrails("Call +85212345678.", "", [], settings)
        spaced = linkedin_store.guardrails("Call 852 1234 5678.", "", [], settings)
        self.assertTrue(any(row["code"] == "phone" for row in plus))
        self.assertTrue(any(row["code"] == "phone" for row in spaced))
        tight = {**settings, "hashtagCap": 0}
        tagged = linkedin_store.guardrails("See #Architecture.", "", [], tight)
        self.assertTrue(any(row["code"] == "hashtags" for row in tagged))

    def test_slot_with_an_offset_is_stored_as_utc(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nKeep the slot."})
        linkedin_store.approve_post(
            self.table,
            doc["postId"],
            "admin-sub",
            now=datetime(2026, 10, 5, 10, 0, tzinfo=HKT),
        )
        edited = linkedin_store.update_post(
            self.table,
            doc["postId"],
            {"slotAt": "2026-10-06T08:30:00+08:00"},
        )
        self.assertEqual(edited["status"], "approved")
        self.assertEqual(edited["slotAt"], "2026-10-06T00:30:00.000Z")

    def test_settings_save_keeps_spend_and_plan_date(self) -> None:
        linkedin_store.add_spend(self.table, 1.25)
        linkedin_store.save_plan_date(self.table, "2026-10-04")
        saved = linkedin_store.save_settings(self.table, {**linkedin_store.default_settings(), "voiceNotes": ""})
        self.assertAlmostEqual(linkedin_store.month_spend(self.table), 1.25)
        self.assertEqual(linkedin_store.load_plan_date(self.table), "2026-10-04")
        self.assertIn("first person", saved["voiceNotes"])

    def test_regenerate_reuses_a_used_idea(self) -> None:
        idea = linkedin_store.create_idea(self.table, "A used lesson about reviews.", "leadership")
        linkedin_store.mark_idea_used(self.table, idea["ideaId"], "li_old")
        chosen = linkedin_draft.choose_topics(
            self.table,
            linkedin_store.default_settings(),
            count=1,
            idea_ids=[idea["ideaId"]],
        )
        self.assertEqual(chosen[0]["idea"]["text"], "A used lesson about reviews.")
        fresh = linkedin_draft.choose_topics(self.table, linkedin_store.default_settings(), count=1)
        self.assertIsNone(fresh[0]["idea"])

    def test_openrouter_error_becomes_a_failed_generation(self) -> None:
        from openrouter_client import OpenRouterError

        def complete(_messages):
            raise OpenRouterError("linkedin key missing")

        with self.assertRaises(LinkedInError) as caught:
            linkedin_draft.generate_drafts(self.table, count=1, complete=complete)
        self.assertIn("linkedin key missing", str(caught.exception))

    def test_model_hashtags_drop_invalid_tags(self) -> None:
        parsed = linkedin_draft.parse_draft(
            '{"body":"A short hook.\\n\\nOne lesson.","firstComment":"","hashtags":["good-tag","Architecture"],"pillar":"architecture"}'
        )
        self.assertEqual(parsed["hashtags"], ["Architecture"])

    def test_live_generation_books_usage(self) -> None:
        from openrouter_client import ChatCompletion
        from openrouter_usage import usage_day_pk, utc_today

        completion = ChatCompletion(
            text='{"body":"A short hook.\\n\\nOne lesson.","firstComment":"","hashtags":["Architecture"],"pillar":"architecture"}',
            model="test-model",
            usage={"promptTokens": 11, "completionTokens": 22, "totalTokens": 33, "cost": 0.03},
        )
        with patch.dict("os.environ", {"OPENROUTER_MODEL": "test-model"}):
            with patch("openrouter_client.chat_completion", return_value=completion):
                result = linkedin_draft.generate_drafts(self.table, count=1)
        self.assertEqual(len(result["posts"]), 1)
        item = self.table.items[(usage_day_pk(utc_today()), "linkedin#draft")]
        self.assertEqual(item["calls"], 1)
        self.assertEqual(item["promptTokens"], 11)
        self.assertEqual(item["costCenter"], "lxSoftware")
        self.assertAlmostEqual(linkedin_store.month_spend(self.table), 0.03)


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
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nDue now."})
        doc["status"] = "approved"
        doc["slotAt"] = "2020-01-01T00:30:00.000Z"
        linkedin_store.put_post(self.table, doc)
        linkedin_store.save_settings(
            self.table,
            {**linkedin_store.default_settings(), "notifyEmail": "owner@example.com"},
        )
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true"}):
            with patch.object(linkedin, "send_notice", return_value=True) as send:
                result = linkedin.handle_publish_due({})
        self.assertEqual(result["reminded"], 1)
        self.assertEqual(result["publish"], "publish_not_implemented")
        self.assertNotIn("skipped", result)
        send.assert_called_once()
        stored = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(stored["status"], "approved")

    def test_generate_without_a_job_does_not_draft(self) -> None:
        result = linkedin.handle_generate({})
        self.assertEqual(result, {"skipped": "missing_job"})
        self.assertEqual(linkedin_store.list_posts(self.table), [])

    def test_worker_error_marks_the_job_failed(self) -> None:
        from openrouter_client import OpenRouterError

        job = linkedin_store.new_job(self.table, "generate", {"count": 1})
        with patch.object(linkedin_draft, "generate_drafts", side_effect=OpenRouterError("linkedin key missing")):
            result = linkedin.handle_generate({"jobId": job["jobId"]})
        self.assertFalse(result["ok"])
        stored = linkedin_store.get_job(self.table, job["jobId"])
        self.assertEqual(stored["status"], "failed")
        self.assertIn("linkedin key missing", stored["error"])

        unknown = linkedin_store.new_job(self.table, "generate", {"count": 1})
        with patch.object(linkedin_draft, "generate_drafts", side_effect=RuntimeError("boom")):
            failed = linkedin.handle_generate({"jobId": unknown["jobId"]})
        self.assertEqual(failed["error"], "Generation failed.")
        self.assertEqual(linkedin_store.get_job(self.table, unknown["jobId"])["status"], "failed")

    def test_bad_replacement_hashtag_fails_the_job(self) -> None:
        post = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nKeep this id."})
        job = linkedin_store.new_job(self.table, "generate", {"postId": post["postId"]})
        generated = {
            "body": "A short hook.\n\nA new lesson.",
            "firstComment": "",
            "hashtags": ["not-a-tag"],
            "pillar": "architecture",
        }
        with patch.object(
            linkedin_draft,
            "generate_drafts",
            return_value={"posts": [generated], "errors": [], "spendUsd": 0},
        ):
            result = linkedin.handle_generate({"jobId": job["jobId"]})
        self.assertFalse(result["ok"])
        stored = linkedin_store.get_job(self.table, job["jobId"])
        self.assertEqual(stored["status"], "failed")
        self.assertIn("invalid", stored["error"])

    def test_idea_create_and_delete_are_audited(self) -> None:
        created = lambda_handler(
            _event("/lx-software/linkedin/ideas", "POST", {"text": "A lesson about reviews.", "pillar": "leadership"}),
            None,
        )
        self.assertEqual(created["statusCode"], 201)
        idea_id = _body(created)["item"]["ideaId"]
        deleted = lambda_handler(_event(f"/lx-software/linkedin/ideas/{idea_id}", "DELETE"), None)
        self.assertEqual(deleted["statusCode"], 200)
        actions = [str(item["sk"]) for item in self.table.items.values() if str(item.get("pk")) == "USER#admin-sub"]
        self.assertTrue(any(action.endswith("#LINKEDIN_IDEA_CREATE") for action in actions))
        self.assertTrue(any(action.endswith("#LINKEDIN_IDEA_DELETE") for action in actions))

    def test_generate_queues_a_job(self) -> None:
        with patch("board_async.try_invoke_event", return_value=True) as invoke:
            response = lambda_handler(_event("/lx-software/linkedin/generate", "POST", {"count": 1}), None)
        self.assertEqual(response["statusCode"], 202)
        invoke.assert_called_once()
        self.assertEqual(invoke.call_args.args[0]["internal"], "linkedin_generate")
