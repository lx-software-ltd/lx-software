"""Board audit fixes A–D: pause, validate, idle, bulk mail, lessons, watchlist."""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any
from unittest.mock import patch

from test_board import BoardTestCase

import board_async
import board_breakers
import board_code
import board_content
import board_duties
import board_github
import board_hk
import board_lessons
import board_mail
import board_meeting
import board_personas
import board_places
import board_review
import board_staff
import board_store
import board_tools
import board_watch


def _enable_staff(table: Any, **staff: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config(
        {**(settings.get("staff") or {}), "enabled": True, **staff}
    )
    return board_store.save_settings(table, settings)


def _running_task(table: Any, settings: dict[str, Any], brief: str = "Do the work") -> dict[str, Any]:
    task = board_staff.create_task(
        table,
        settings,
        assignee="support",
        origin="owner",
        brief=brief,
        deliverable_type="markdown",
        created_by="test",
    )
    latest = board_store.get_task(table, task["taskId"]) or task
    latest["status"] = "running"
    board_store.put_task(table, latest)
    return board_store.get_task(table, task["taskId"]) or latest


class PauseAndDedupeTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        patcher = patch.object(board_async, "invoke_async", side_effect=lambda payload, *, fallback=None: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "support", {"isActive": True})

    def test_park_and_resume_waiting_approval(self) -> None:
        task = _running_task(self.table, self.settings)
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=self.settings,
            persona_id="cmo",
            display_name="Maya",
            kind="task",
            task_id=task["taskId"],
        )
        first = board_tools.create_approval(
            ctx,
            board_tools.REGISTRY["board_add_action"],
            {"title": "Ship it", "reason": "first"},
            summary="Ship it",
        )
        second = board_tools.create_approval(
            ctx,
            board_tools.REGISTRY["board_add_action"],
            {"title": "Ship it", "reason": "again"},
            summary="Ship it again",
        )
        self.assertEqual(first["approvalId"], second["approvalId"])
        board_staff._park_waiting_approval(self.table, task, [first["approvalId"]])
        parked = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(parked["status"], "waiting_approval")
        first["status"] = "rejected"
        first["context"] = {"taskId": task["taskId"]}
        board_store.put_approval(self.table, first)
        board_staff.resume_after_approval(self.table, self.settings, first)
        resumed = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(resumed["status"], "running")


class ValidateProposalTests(BoardTestCase):
    def test_content_publish_missing_and_stale_slot(self) -> None:
        self.assertIn("does not exist", board_content.validate_publish(self.table, {"contentId": "nope"}))
        old = (datetime.now(timezone.utc) - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
        board_store.put_content(
            self.table,
            {
                "contentId": "c1",
                "status": "draft",
                "channel": "facebook",
                "title": "Hello",
                "createdAt": board_store.now_iso(),
            },
        )
        self.assertIn("past", board_content.validate_publish(self.table, {"contentId": "c1", "slotAt": old}))

    def test_code_run_task_closed_issue_fail_open_on_error(self) -> None:
        with patch.object(board_github, "op_get_issue", return_value={"number": 9, "state": "closed"}):
            self.assertIn("not open", board_code.validate_run_task({"issueNumber": 9}))
        with patch.object(board_github, "op_get_issue", side_effect=RuntimeError("github down")):
            self.assertIsNone(board_code.validate_run_task({"issueNumber": 9}))

    def test_github_create_issue_similar_open(self) -> None:
        with patch.object(
            board_github,
            "op_search_issues",
            return_value={"items": [{"title": "Add Sha Tin listing", "state": "open", "number": 44}]},
        ):
            err = board_github.validate_create_issue({"title": "Add Sha Tin listing"})
        self.assertIn("similar open issue", err or "")


class IdleAndDateTests(BoardTestCase):
    def test_error_calls_are_not_productive(self) -> None:
        self.assertEqual(
            board_staff._productive_calls([{"op": "github_search_issues", "status": "error"}]),
            [],
        )
        self.assertTrue(board_staff._productive_calls([{"op": "github_search_issues", "status": "ok"}]))

    def test_similar_plans(self) -> None:
        self.assertTrue(board_staff._plans_similar("Search GitHub for the issue", "Search github for the issue."))
        self.assertFalse(board_staff._plans_similar("Search GitHub", "Publish the weekend guide"))

    def test_preamble_and_task_frame_include_hkt_date(self) -> None:
        text = board_personas.common_preamble({})
        self.assertIn(f"Today is {board_hk.today_hkt()} (HKT)", text)
        frame = board_personas.render_task_frame(
            {"brief": "x", "deliverableType": "markdown", "budgetUsd": 1, "usage": {}, "step": 0},
            "",
        )
        self.assertIn(f"Today is {board_hk.today_hkt()} (HKT)", frame)


class BreakerAndUnconfiguredTests(BoardTestCase):
    def test_not_configured_errors_do_not_trip_tool_breaker(self) -> None:
        now = board_store.now_iso()
        for i in range(12):
            board_store.add_tool_call(
                self.table,
                {
                    "callId": f"err-{i}",
                    "op": "meta_page_insights",
                    "toolId": "meta",
                    "status": "error",
                    "resultPreview": "META_PAGE_ID is not set",
                    "createdAt": now,
                },
            )
        tripped = board_breakers.evaluate(self.table, board_store.load_settings(self.table))
        self.assertNotIn("tool:meta", tripped)

    def test_unconfigured_writes_are_hidden(self) -> None:
        os.environ.pop("GOOGLE_ANALYTICS_ACCESS_TOKEN", None)
        os.environ.pop("GA4_PROPERTY_IDS", None)
        settings = board_store.default_settings()
        settings["tools"]["globalMode"] = "act"
        cmo = {op.name for op, _ in board_tools.available_ops(settings, "cmo", context="chat")}
        ceo = {op.name for op, _ in board_tools.available_ops(settings, "ceo", context="chat")}
        self.assertNotIn("meta_propose_post", cmo)
        self.assertNotIn("stores_reply_review", cmo)
        self.assertIn("github_search_issues", ceo)


class BulkMailAndChatMaskTests(BoardTestCase):
    def test_dmarc_and_ses_subjects_are_bulk(self) -> None:
        msg = EmailMessage()
        msg["From"] = "dmarc@siutindei.com"
        msg["Subject"] = "Report domain: siutindei.com"
        self.assertTrue(board_mail._is_bulk_mail(msg))
        ses = EmailMessage()
        ses["From"] = "noreply@amazonses.com"
        ses["Subject"] = "Finish setting up Amazon SES"
        self.assertTrue(board_mail._is_bulk_mail(ses))
        auto = EmailMessage()
        auto["From"] = "parent@example.com"
        auto["Subject"] = "Thanks"
        auto["X-Auto-Response-Suppress"] = "All"
        self.assertTrue(board_mail._is_bulk_mail(auto))
        human = EmailMessage()
        human["From"] = "parent@example.com"
        human["Subject"] = "Class on Saturday"
        self.assertFalse(board_mail._is_bulk_mail(human))

    def test_thread_search_matches_alias_and_raw_email(self) -> None:
        board_store.put_mail_thread(
            self.table,
            {
                "threadId": "th1",
                "subject": "Booking",
                "snippet": "Can we come?",
                "lastFrom": "wendy@gmail.com",
                "lastFromName": "Wendy",
                "mailbox": "hello@siutindei.com",
                "participants": ["wendy@gmail.com"],
                "unread": True,
                "lastMessageAt": board_store.now_iso(),
            },
        )
        listing = board_mail.thread_list(self.table, query="wendy@gmail.com")
        self.assertEqual(listing["total"], 1)
        listing = board_mail.thread_list(self.table, query="contact#1")
        self.assertEqual(listing["total"], 1)


class LessonAndReviewTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        patcher = patch.object(board_async, "invoke_async", side_effect=lambda payload, *, fallback=None: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.settings = _enable_staff(self.table)

    def test_lesson_upsert_and_skip_salvaged(self) -> None:
        task = {
            "taskId": "t-lesson",
            "assignee": "support",
            "brief": "Reply to parent",
            "lastReview": {"notes": "Need the catalog fact"},
        }

        def fake_complete(**kwargs: Any) -> Any:
            return type("C", (), {"text": '{"instruction":"Cite the catalog."}', "usage": {}})()

        with patch("board_lessons.board_budget.board_completion", side_effect=fake_complete):
            first = board_lessons.create_from_return(self.table, task)
            again = board_lessons.create_from_return(
                self.table, {**task, "lastReview": {"notes": "Still missing"}}
            )
            skipped = board_lessons.create_from_return(
                self.table, {**task, "taskId": "t2", "flags": ["salvaged"]}
            )
        self.assertEqual(first["lessonId"], again["lessonId"])
        self.assertEqual(skipped, {})

    def test_unverified_accept_goes_to_needs_owner(self) -> None:
        board_store.save_staff_override(self.table, "support", {"isActive": True})
        task = board_staff.create_task(
            self.table,
            self.settings,
            assignee="support",
            origin="owner",
            brief="Publish the weekend guide and label the GitHub issue",
            deliverable_type="markdown",
            created_by="test",
        )
        task["status"] = "review"
        task["flags"] = ["no_evidence"]
        board_store.put_task(self.table, task)
        out = board_staff.apply_review(
            self.table, self.settings, task, verdict="accept", notes="looks fine", by="manager"
        )
        self.assertEqual(out["status"], "needs_owner")

    def test_headline_counts_today_delivered_only(self) -> None:
        board_store.save_staff_override(self.table, "support", {"isActive": True})
        old = board_staff.create_task(
            self.table,
            self.settings,
            assignee="support",
            origin="owner",
            brief="Old delivery",
            deliverable_type="markdown",
            created_by="test",
        )
        old["status"] = "delivered"
        old["finishedAt"] = "2026-01-01T04:00:00Z"
        old["updatedAt"] = old["finishedAt"]
        board_store.put_task(self.table, old)
        fresh = board_staff.create_task(
            self.table,
            self.settings,
            assignee="support",
            origin="owner",
            brief="Today delivery",
            deliverable_type="markdown",
            created_by="test",
        )
        now = board_store.now_iso()
        fresh["status"] = "delivered"
        fresh["finishedAt"] = now
        fresh["updatedAt"] = now
        board_store.put_task(self.table, fresh)
        pack = board_review.headline_pack(self.table, self.settings, board_hk.today_hkt())
        self.assertEqual(pack["tasks"]["delivered"], 1)

    def test_template_data_is_placeholder(self) -> None:
        self.assertTrue(board_staff._deliverable_has_placeholders("Campaign A reached 123 sessions"))
        self.assertFalse(board_staff._deliverable_has_placeholders("Sha Tin Playhouse had 18 bookings"))


class WatchPlacesTargetTests(BoardTestCase):
    def test_watch_rejects_foreign_and_listicle_hosts(self) -> None:
        self.assertTrue(board_watch._ignored("klook.com"))
        self.assertTrue(board_watch._rejected_tld("kids.tw"))
        self.assertFalse(board_watch._has_hk_signal({"title": "Best camps"}, "kids.sg"))
        self.assertTrue(board_watch._has_hk_signal({"title": "Kids camp Hong Kong"}, "playhouse.com"))
        self.assertEqual(board_watch._candidate_name({"title": "10 Best Kids Activities in Hong Kong"}, "play.hk"), "play.hk")

    def test_places_drops_non_hk_and_sends_rectangle(self) -> None:
        os.environ["GOOGLE_PLACES_KEY"] = "test-places-key"
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("GOOGLE_PLACES_KEY", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        board_places.reset_key_cache_for_tests()
        settings = _enable_staff(self.table)
        payload = {
            "places": [
                {
                    "id": "hk-1",
                    "displayName": {"text": "Playhouse"},
                    "formattedAddress": "Sha Tin, Hong Kong",
                },
                {
                    "id": "tw-1",
                    "displayName": {"text": "Taipei Kids"},
                    "formattedAddress": "Da'an District, Taipei, Taiwan",
                },
            ]
        }
        with patch.object(board_places, "_http", return_value=payload) as http:
            places = board_places.text_search(self.table, "kids play", settings=settings)
        self.assertEqual([p["placeId"] for p in places], ["hk-1"])
        body = json.loads(http.call_args.kwargs["body"].decode("utf-8"))
        self.assertIn("locationRestriction", body)
        self.assertEqual(body["locationRestriction"]["rectangle"]["low"]["latitude"], 22.15)

    def test_default_qualified_per_week_is_fifteen(self) -> None:
        bounds = board_store.default_boundaries()
        self.assertEqual(bounds["outreach"]["targets"]["qualifiedPerWeek"], 15)


class ProseToolCallAndStuckTests(BoardTestCase):
    def test_parse_deepseek_function_call(self) -> None:
        calls = board_tools.parse_prose_tool_calls(
            'I will finish now\n!function_call:{"name":"task_finish","arguments":{"summary":"done"}}'
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "task_finish")
        self.assertEqual(calls[0].arguments["summary"], "done")

    def test_stuck_writes_failure_detail(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        with patch.object(board_async, "invoke_async", side_effect=lambda payload, *, fallback=None: None):
            settings = _enable_staff(self.table)
            board_store.save_staff_override(self.table, "support", {"isActive": True})
            task = _running_task(self.table, settings)
        failed = board_staff._finish_incomplete(self.table, task, "stuck")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failureReason"], "stuck")
        self.assertEqual(failed["failureDetail"]["reason"], "stuck")

    def test_failed_schedule_retries_once(self) -> None:
        settings = board_store.load_settings(self.table)
        settings["schedule"] = {"morningEnabled": True, "eveningEnabled": False}
        board_store.put_meeting(
            self.table,
            {
                "meetingId": "m-fail",
                "status": "failed",
                "trigger": "schedule:morning",
                "createdAt": board_store.now_iso(),
                "updatedAt": board_store.now_iso(),
            },
        )
        with patch.object(board_meeting, "start_meeting", return_value={"meetingId": "m-retry"}) as start:
            out = board_meeting.maybe_retry_failed_schedule(self.table, settings)
        self.assertEqual(out["meetingId"], "m-retry")
        self.assertEqual(start.call_args.kwargs["trigger"], "schedule:morning:retry")


class DutiesBatchTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        patcher = patch.object(board_async, "invoke_async", side_effect=lambda payload, *, fallback=None: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.settings = _enable_staff(self.table, dutiesEnabled=False)
        board_store.save_staff_override(self.table, "security-analyst", {"isActive": True})

    def test_multiple_github_alerts_become_one_task(self) -> None:
        board_store.put_cache(
            self.table,
            "security:github",
            {
                "dependabot": [{"number": 9, "summary": "lodash"}, {"number": 10, "summary": "minimist"}],
                "codeScanning": [],
                "secretScanning": [],
            },
        )
        out = board_duties.triage_ops_signals(self.table, self.settings)
        self.assertEqual(out["alerts"], 1)
        tasks = board_store.list_tasks(self.table, "queued") + board_store.list_tasks(self.table, "running")
        batch = [t for t in tasks if str((t.get("eventRef") or {}).get("id") or "").startswith("alert:gh:batch:")]
        self.assertEqual(len(batch), 1)
        self.assertIn("lodash", batch[0]["brief"])
        self.assertIn("minimist", batch[0]["brief"])


if __name__ == "__main__":
    unittest.main()
