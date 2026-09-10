"""Newsletter subscribe, confirm, send and bounce (WP8)."""

from __future__ import annotations

import json
import os
import unittest
from typing import Any
from unittest.mock import patch

import board_holds
import board_newsletter
import board_outreach
import board_store
import board_tools
from test_board import BoardTestCase, lambda_handler


class FakeSes:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.templates: dict[str, dict[str, Any]] = {}
        self.bulk: list[dict[str, Any]] = []

    def send_email(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"MessageId": "ses-confirm-1"}

    def get_email_template(self, TemplateName: str) -> dict[str, Any]:
        if TemplateName not in self.templates:
            raise RuntimeError("not found")
        return self.templates[TemplateName]

    def create_email_template(self, **kwargs: Any) -> dict[str, Any]:
        self.templates[kwargs["TemplateName"]] = kwargs
        return {}

    def send_bulk_email(self, **kwargs: Any) -> dict[str, Any]:
        self.bulk.append(kwargs)
        return {"BulkEmailEntryResults": []}


def _enable_staff(table: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True})
    settings["tools"]["globalMode"] = "act"
    return board_store.save_settings(table, settings)


class NewsletterTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        os.environ["BOARD_MAIL_SENDING_ENABLED"] = "true"
        os.environ["BOARD_LINK_SIGNING_SECRET"] = "link-secret-for-tests"
        os.environ["PUBLIC_API_BASE_URL"] = "https://api.example"
        os.environ["BOARD_MAIL_DOMAIN"] = "siutindei.com"
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_MAIL_SENDING_ENABLED", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_LINK_SIGNING_SECRET", None))
        self.addCleanup(lambda: os.environ.pop("PUBLIC_API_BASE_URL", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_MAIL_DOMAIN", None))
        board_outreach.reset_caches_for_tests()
        self.settings = _enable_staff(self.table)
        self.ses = FakeSes()
        ses_patch = patch.object(board_outreach, "_ses_client", lambda: self.ses)
        ses_patch.start()
        self.addCleanup(ses_patch.stop)

    def test_token_round_trip_and_tamper(self) -> None:
        digest = board_outreach.suppress_digest("parent@example.com")
        token = board_newsletter.make_token("c", "parents", digest)
        self.assertEqual(board_newsletter.parse_token(token), ("c", "parents", digest))
        self.assertIsNone(board_newsletter.parse_token(token[:-2] + "xx"))

    def test_double_opt_in_required_before_send(self) -> None:
        event = {
            "requestContext": {
                "http": {"method": "POST", "path": "/public/newsletter/subscribe", "sourceIp": "1.1.1.1"},
                "requestId": "n1",
            },
            "body": json.dumps({"list": "parents", "email": "parent@example.com", "lang": "en"}),
            "rawQueryString": "",
        }
        out = lambda_handler(event, None)
        self.assertEqual(out["statusCode"], 200)
        self.assertEqual(len(self.ses.calls), 1)
        self.assertEqual(self.ses.calls[0]["FromEmailAddress"], "news@siutindei.com")
        digest = board_outreach.suppress_digest("parent@example.com")
        issue = board_newsletter.draft_issue(self.table, self.settings, list_name="parents", markdown="# Hello")
        refused = board_newsletter.send_issue(
            self.table, self.settings, issue_id=issue["issueId"], list_name="parents"
        )
        self.assertEqual(refused["error"], "no confirmed subscribers")
        confirm = board_newsletter.make_token("c", "parents", digest)
        confirmed = lambda_handler(
            {
                "requestContext": {
                    "http": {"method": "GET", "path": f"/public/newsletter/confirm/{confirm}", "sourceIp": "1.1.1.1"},
                    "requestId": "n2",
                },
                "rawQueryString": "",
            },
            None,
        )
        self.assertEqual(confirmed["statusCode"], 200)
        sent = board_newsletter.send_issue(
            self.table, self.settings, issue_id=issue["issueId"], list_name="parents"
        )
        self.assertTrue(sent.get("ok"))
        self.assertEqual(sent["sent"], 1)
        self.assertEqual(len(self.ses.bulk), 1)
        self.assertEqual(len(self.ses.bulk[0]["BulkEmailEntries"]), 1)

    def test_unsubscribe_honoured_and_shared_bounce(self) -> None:
        digest = board_outreach.suppress_digest("parent@example.com")
        board_store.put_newsletter_sub(
            self.table,
            digest,
            "parents",
            {
                "digest": digest,
                "email": "parent@example.com",
                "list": "parents",
                "lang": "en",
                "confirmedAt": board_store.now_iso(),
                "createdAt": board_store.now_iso(),
            },
        )
        token = board_newsletter.make_token("u", "parents", digest)
        out = lambda_handler(
            {
                "requestContext": {
                    "http": {"method": "GET", "path": f"/public/newsletter/unsubscribe/{token}", "sourceIp": "2.2.2.2"},
                    "requestId": "n3",
                },
                "rawQueryString": "",
            },
            None,
        )
        self.assertEqual(out["statusCode"], 200)
        row = board_store.get_newsletter_sub(self.table, digest, "parents")
        self.assertTrue((row or {}).get("unsubscribedAt"))
        self.assertFalse(board_outreach.is_suppressed(self.table, "parent@example.com"))
        issue = board_newsletter.draft_issue(self.table, self.settings, list_name="parents", markdown="# Bye")
        refused = board_newsletter.send_issue(
            self.table, self.settings, issue_id=issue["issueId"], list_name="parents"
        )
        self.assertEqual(refused["error"], "no confirmed subscribers")
        other = board_outreach.suppress_digest("other@example.com")
        board_store.put_newsletter_sub(
            self.table,
            other,
            "parents",
            {
                "digest": other,
                "email": "other@example.com",
                "list": "parents",
                "lang": "en",
                "confirmedAt": board_store.now_iso(),
                "createdAt": board_store.now_iso(),
            },
        )
        issue2 = board_newsletter.draft_issue(self.table, self.settings, list_name="parents", markdown="# Two")
        board_newsletter.handle_ses_events(
            [
                {
                    "eventSource": "aws:sqs",
                    "body": json.dumps(
                        {
                            "Type": "Notification",
                            "Message": json.dumps(
                                {
                                    "eventType": "Bounce",
                                    "bounce": {"bounceType": "Permanent"},
                                    "mail": {
                                        "tags": {"issueId": [issue2["issueId"]]},
                                        "destination": ["other@example.com"],
                                    },
                                }
                            ),
                        }
                    ),
                }
            ]
        )
        self.assertTrue(board_outreach.is_suppressed(self.table, "other@example.com"))
        latest = board_newsletter.get_issue(self.table, issue2["issueId"])
        self.assertGreaterEqual(int((latest or {}).get("metrics", {}).get("bounces") or 0), 1)

    def test_batch_send_and_hold_class(self) -> None:
        for i in range(51):
            email = f"p{i}@example.com"
            digest = board_outreach.suppress_digest(email)
            board_store.put_newsletter_sub(
                self.table,
                digest,
                "providers",
                {
                    "digest": digest,
                    "email": email,
                    "list": "providers",
                    "lang": "en",
                    "confirmedAt": board_store.now_iso(),
                    "createdAt": board_store.now_iso(),
                },
            )
        issue = board_newsletter.draft_issue(self.table, self.settings, list_name="providers", markdown="# Batch")
        sent = board_newsletter.send_issue(
            self.table, self.settings, issue_id=issue["issueId"], list_name="providers"
        )
        self.assertEqual(sent["sent"], 51)
        self.assertEqual(len(self.ses.bulk), 2)
        self.assertEqual(len(self.ses.bulk[0]["BulkEmailEntries"]), 50)
        self.assertEqual(len(self.ses.bulk[1]["BulkEmailEntries"]), 1)
        ctx = board_tools.ToolContext(table=self.table, settings=self.settings, persona_id="cmo", kind="task")
        action, key = board_holds.classify(
            board_tools.REGISTRY["newsletter_send"],
            ctx,
            {"issueId": issue["issueId"], "list": "providers"},
            self.settings,
        )
        self.assertEqual(action, "publish")
        self.assertEqual(key, "publish:newsletter")

    def test_second_send_is_noop_and_tags_issue(self) -> None:
        digest = board_outreach.suppress_digest("once@example.com")
        board_store.put_newsletter_sub(
            self.table,
            digest,
            "parents",
            {
                "digest": digest,
                "email": "once@example.com",
                "list": "parents",
                "lang": "en",
                "confirmedAt": board_store.now_iso(),
                "createdAt": board_store.now_iso(),
            },
        )
        issue = board_newsletter.draft_issue(self.table, self.settings, list_name="parents", markdown="# Once")
        first = board_newsletter.send_issue(self.table, self.settings, issue_id=issue["issueId"], list_name="parents")
        second = board_newsletter.send_issue(self.table, self.settings, issue_id=issue["issueId"], list_name="parents")
        self.assertTrue(first.get("ok"))
        self.assertTrue(second.get("noop"))
        self.assertEqual(second.get("sent"), 0)
        self.assertEqual(self.ses.bulk[0]["DefaultEmailTags"], [{"Name": "issueId", "Value": issue["issueId"]}])

    def test_failed_bulk_entry_not_counted(self) -> None:
        digest = board_outreach.suppress_digest("fail@example.com")
        board_store.put_newsletter_sub(
            self.table,
            digest,
            "parents",
            {
                "digest": digest,
                "email": "fail@example.com",
                "list": "parents",
                "lang": "en",
                "confirmedAt": board_store.now_iso(),
                "createdAt": board_store.now_iso(),
            },
        )

        def fail_one(**kwargs: Any) -> dict[str, Any]:
            self.ses.bulk.append(kwargs)
            return {"BulkEmailEntryResults": [{"Status": "FAILED"}]}

        self.ses.send_bulk_email = fail_one  # type: ignore[method-assign]
        issue = board_newsletter.draft_issue(self.table, self.settings, list_name="parents", markdown="# Fail")
        sent = board_newsletter.send_issue(self.table, self.settings, issue_id=issue["issueId"], list_name="parents")
        self.assertEqual(sent["sent"], 0)

    def test_cross_list_keeps_first_confirmed(self) -> None:
        digest = board_outreach.suppress_digest("both@example.com")
        board_store.put_newsletter_sub(
            self.table,
            digest,
            "parents",
            {
                "digest": digest,
                "email": "both@example.com",
                "list": "parents",
                "lang": "en",
                "confirmedAt": board_store.now_iso(),
                "createdAt": board_store.now_iso(),
            },
        )
        lambda_handler(
            {
                "requestContext": {
                    "http": {"method": "POST", "path": "/public/newsletter/subscribe", "sourceIp": "9.9.9.9"},
                    "requestId": "nl-x",
                },
                "body": json.dumps({"list": "providers", "email": "both@example.com"}),
                "rawQueryString": "",
            },
            None,
        )
        parents = board_store.get_newsletter_sub(self.table, digest, "parents")
        providers = board_store.get_newsletter_sub(self.table, digest, "providers")
        self.assertTrue((parents or {}).get("confirmedAt"))
        self.assertFalse(bool((providers or {}).get("confirmedAt")))
        self.assertEqual(len(self.ses.calls), 0)

    def test_fourth_confirm_not_sent(self) -> None:
        for i in range(4):
            lambda_handler(
                {
                    "requestContext": {
                        "http": {"method": "POST", "path": "/public/newsletter/subscribe", "sourceIp": f"3.3.3.{i}"},
                        "requestId": f"nl-c{i}",
                    },
                    "body": json.dumps({"list": "parents", "email": f"c{i}@example.com"}),
                    "rawQueryString": "",
                },
                None,
            )
        # same digest four times
        self.ses.calls.clear()
        email = "repeat@example.com"
        for i in range(4):
            # force a fresh pending row so cooldown is what blocks the fourth
            digest = board_outreach.suppress_digest(email)
            existing = board_store.get_newsletter_sub(self.table, digest, "parents") or {}
            existing.pop("confirmSentAt", None)
            existing.pop("confirmedAt", None)
            if existing:
                board_store.put_newsletter_sub(self.table, digest, "parents", existing)
            lambda_handler(
                {
                    "requestContext": {
                        "http": {"method": "POST", "path": "/public/newsletter/subscribe", "sourceIp": f"4.4.4.{i}"},
                        "requestId": f"nl-r{i}",
                    },
                    "body": json.dumps({"list": "parents", "email": email}),
                    "rawQueryString": "",
                },
                None,
            )
        self.assertLessEqual(len(self.ses.calls), 3)

    def test_newsletter_complaint_leaves_outreach_day_unchanged(self) -> None:
        import board_hk
        import dispatch

        today = board_hk.today_hkt()
        board_store.save_outreach_day(self.table, {"sent": 10, "bounces": 0, "complaints": 0}, today)
        event = {
            "Records": [
                {
                    "messageId": "good-1",
                    "eventSource": "aws:sqs",
                    "body": json.dumps(
                        {
                            "eventType": "Complaint",
                            "mail": {
                                "tags": {
                                    "ses:configuration-set": ["lxsoftware-admin-siutindei-newsletter"],
                                    "issueId": ["iss-1"],
                                },
                                "destination": ["x@example.com"],
                            },
                        }
                    ),
                },
                {
                    "messageId": "bad-1",
                    "eventSource": "aws:sqs",
                    "body": "{not-json",
                },
            ]
        }
        def raise_on_bad(records: list[dict[str, Any]]) -> dict[str, Any]:
            if records and records[0].get("messageId") == "bad-1":
                raise RuntimeError("boom")
            return {"handled": 0}

        with (
            patch("board_newsletter.handle_ses_events", return_value={"handled": 1}),
            patch("board_outreach.handle_ses_events", side_effect=raise_on_bad),
        ):
            out = dispatch.lambda_handler(event, None)
        day = board_store.load_outreach_day(self.table, today)
        self.assertEqual(int(day.get("complaints") or 0), 0)
        self.assertEqual(out.get("batchItemFailures"), [{"itemIdentifier": "bad-1"}])

    def test_resubscribe_after_unsubscribe(self) -> None:
        digest = board_outreach.suppress_digest("again@example.com")
        board_store.put_newsletter_sub(
            self.table,
            digest,
            "parents",
            {
                "digest": digest,
                "email": "again@example.com",
                "list": "parents",
                "lang": "en",
                "confirmedAt": board_store.now_iso(),
                "unsubscribedAt": board_store.now_iso(),
                "createdAt": board_store.now_iso(),
            },
        )
        out = lambda_handler(
            {
                "requestContext": {
                    "http": {"method": "POST", "path": "/public/newsletter/subscribe", "sourceIp": "5.5.5.5"},
                    "requestId": "nl-again",
                },
                "body": json.dumps({"list": "parents", "email": "again@example.com"}),
                "rawQueryString": "",
            },
            None,
        )
        self.assertEqual(out["statusCode"], 200)
        self.assertEqual(len(self.ses.calls), 1)


if __name__ == "__main__":
    unittest.main()
