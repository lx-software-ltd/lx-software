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

    def test_parking_keeps_completed_step_progress(self) -> None:
        from types import SimpleNamespace

        task = _running_task(self.table, self.settings)
        self.assertEqual(int(task.get("step") or 0), 0)
        result = SimpleNamespace(
            usage={"promptTokens": 10, "completionTokens": 5, "cost": 0.01},
            text="Proposing the action now",
            calls=[{"callId": "c1", "status": "pending_approval", "approvalId": "ap-1"}],
        )
        with patch.object(board_async, "invoke_async", side_effect=lambda payload, *, fallback=None: None) as inv:
            board_staff._complete_step(self.table, task["taskId"], task, result, 1)
            inv.assert_not_called()
        parked = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(parked["status"], "waiting_approval")
        self.assertEqual(parked["blockedOn"], ["ap-1"])
        self.assertEqual(int(parked["step"]), 1)
        self.assertEqual(int(parked["stepsUsed"]), 1)
        self.assertTrue(parked.get("scratchpadKey"))
        self.assertEqual(int((parked.get("usage") or {}).get("calls") or 0), 1)
        self.assertEqual(int((parked.get("usage") or {}).get("promptTokens") or 0), 10)
        steps = board_store.list_task_steps(self.table, task["taskId"])
        self.assertEqual(len(steps), 1)
        with patch.object(board_async, "invoke_async") as inv:
            board_staff.resume_after_approval(
                self.table,
                self.settings,
                {"approvalId": "ap-1", "status": "rejected", "context": {"taskId": task["taskId"]}},
            )
            self.assertEqual(inv.call_args.args[0]["step"], 2)

    def test_parking_yields_to_cancel_that_landed_mid_step(self) -> None:
        task = _running_task(self.table, self.settings)
        stored = board_store.get_task(self.table, task["taskId"])
        stored["status"] = "cancelled"
        board_store.put_task(self.table, stored)
        board_staff._park_waiting_approval(self.table, task, ["ap-x"])
        self.assertEqual(board_store.get_task(self.table, task["taskId"])["status"], "cancelled")


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
        self.assertGreaterEqual(
            board_staff._token_overlap("Call 10 activity providers Book calls", "Call 10 activity providers Book calls now"),
            0.6,
        )
        self.assertFalse(
            board_staff._same_as_previous_step(self.table, "missing", [{"op": "code_review_pr", "status": "ok"}])
        )

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

    def test_invalid_arguments_do_not_trip_and_auto_reset(self) -> None:
        now = board_store.now_iso()
        for i in range(12):
            board_store.add_tool_call(
                self.table,
                {
                    "callId": f"arg-{i}",
                    "op": "github_list_commits",
                    "toolId": "github",
                    "status": "error",
                    "resultPreview": "Invalid arguments: unknown argument 'branch'",
                    "createdAt": now,
                },
            )
        tripped = board_breakers.evaluate(self.table, board_store.load_settings(self.table))
        self.assertNotIn("tool:github", tripped)
        board_breakers.trip(self.table, "tool:github", "10 errors in the last hour")
        board_breakers.evaluate(self.table, board_store.load_settings(self.table))
        self.assertTrue(board_breakers.is_tripped(self.table, "tool:github"))
        old = datetime.now(timezone.utc) - timedelta(minutes=31)
        row = board_store.get_breaker(self.table, "tool:github")
        row["trippedAt"] = old.strftime("%Y-%m-%dT%H:%M:%SZ")
        board_store.put_breaker(self.table, "tool:github", row)
        board_breakers.evaluate(self.table, board_store.load_settings(self.table))
        self.assertFalse(board_breakers.is_tripped(self.table, "tool:github"))
        updates = board_store.list_updates(self.table)
        self.assertTrue(any("reset (auto)" in str(u.get("text") or "") for u in updates))

    def test_generic_not_found_still_counts_toward_breaker(self) -> None:
        now = board_store.now_iso()
        for i in range(10):
            board_store.add_tool_call(
                self.table,
                {
                    "callId": f"nf-{i}",
                    "op": "board_update_action",
                    "toolId": "board",
                    "status": "error",
                    "resultPreview": "Action act-dash not found",
                    "createdAt": now,
                },
            )
        tripped = board_breakers.evaluate(self.table, board_store.load_settings(self.table))
        self.assertIn("tool:board", tripped)

    def test_github_404_does_not_trip_tool_breaker(self) -> None:
        now = board_store.now_iso()
        for i in range(12):
            board_store.add_tool_call(
                self.table,
                {
                    "callId": f"404-{i}",
                    "op": "github_get_file",
                    "toolId": "github",
                    "status": "error",
                    "resultPreview": "apps/missing.ts not found in lx-software-ltd/siutindei",
                    "createdAt": now,
                },
            )
        tripped = board_breakers.evaluate(self.table, board_store.load_settings(self.table))
        self.assertNotIn("tool:github", tripped)

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
        partner = EmailMessage()
        partner["From"] = "complaints@partner.example"
        partner["Subject"] = "A parent complaint about a listing"
        self.assertFalse(board_mail._is_bulk_mail(partner))

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

    def test_headline_mail_counts_archived(self) -> None:
        board_store.put_mail_thread(
            self.table, {"threadId": "m-arch", "subject": "DMARC", "disposition": "archived"}
        )
        board_store.put_mail_thread(
            self.table, {"threadId": "m-out", "subject": "Hi", "disposition": "", "lastDirection": "out"}
        )
        board_store.put_mail_thread(self.table, {"threadId": "m-open", "subject": "Q", "disposition": ""})
        pack = board_review.headline_pack(self.table, self.settings, board_hk.today_hkt())
        self.assertEqual(pack["mail"]["archived"], 1)
        self.assertEqual(pack["mail"]["replied"], 1)
        self.assertEqual(pack["mail"]["open"], 1)
        digest = "\n".join(board_review._headline_lines({"headline": pack}))  # noqa: SLF001
        self.assertIn("Mail: 1 replied / 1 archived / 1 open", digest)

    def test_template_data_is_placeholder(self) -> None:
        self.assertTrue(board_staff._deliverable_has_placeholders("Campaign A reached 123 sessions"))
        self.assertFalse(board_staff._deliverable_has_placeholders("Sha Tin Playhouse had 18 bookings"))

    def test_duty_no_evidence_accept_holds_and_does_not_close_action(self) -> None:
        board_store.save_staff_override(self.table, "architect", {"isActive": True})
        action = {
            "actionId": "act-dash",
            "title": "Implement dashboard",
            "status": "open",
            "createdAt": board_store.now_iso(),
        }
        board_store.put_action(self.table, action)
        task = board_staff.create_task(
            self.table,
            self.settings,
            assignee="architect",
            origin="duty",
            brief="Groom the GitHub backlog and label issues board-ready",
            deliverable_type="markdown",
            action_id="act-dash",
            created_by="test",
        )
        task["status"] = "review"
        task["flags"] = ["no_evidence"]
        task["actionId"] = "act-dash"
        board_store.put_task(self.table, task)
        out = board_staff.apply_review(
            self.table, self.settings, task, verdict="accept", notes="looks fine", by="manager"
        )
        self.assertEqual(out["status"], "needs_owner")
        self.assertEqual(board_store.get_action(self.table, "act-dash")["status"], "open")

    def test_review_headline_accept_delivers_without_evidence(self) -> None:
        board_store.save_staff_override(self.table, "business-analyst", {"isActive": True})
        date = board_hk.today_hkt()
        task = board_staff.create_task(
            self.table,
            self.settings,
            assignee="business-analyst",
            origin="duty",
            brief="Write the three-sentence headline for today's review from this JSON",
            deliverable_type="markdown",
            event_ref={"kind": "duty", "id": f"review-headline:{date}"},
            created_by="test",
        )
        task["status"] = "review"
        task["flags"] = ["no_evidence"]
        board_store.put_task(self.table, task)
        out = board_staff.apply_review(
            self.table, self.settings, task, verdict="accept", notes="concise", by="manager"
        )
        self.assertEqual(out["status"], "delivered")

    def test_narrative_uses_accepted_needs_owner_headline(self) -> None:
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        board_store.save_staff_override(self.table, "business-analyst", {"isActive": True})
        date = board_hk.today_hkt()
        task = board_staff.create_task(
            self.table,
            self.settings,
            assignee="business-analyst",
            origin="duty",
            brief="Write the three-sentence headline",
            deliverable_type="markdown",
            event_ref={"kind": "duty", "id": f"review-headline:{date}"},
            created_by="test",
        )
        key = board_staff._deliverable_key(task["taskId"], "markdown")  # noqa: SLF001
        board_staff._blob_put(key, b"Three sentences about the day.")  # noqa: SLF001
        task.update(
            {
                "status": "needs_owner",
                "flags": ["no_evidence"],
                "lastReview": {"verdict": "accept", "notes": "ok", "by": "manager"},
                "deliverableKey": key,
                "summary": "headline",
            }
        )
        board_store.put_task(self.table, task)
        text = board_review._narrative(self.table, date)  # noqa: SLF001
        self.assertIn("Three sentences", text)

    def test_duty_tool_error_accept_is_not_held(self) -> None:
        board_store.save_staff_override(self.table, "data-analyst", {"isActive": True})
        task = board_staff.create_task(
            self.table,
            self.settings,
            assignee="data-analyst",
            origin="duty",
            brief="Write this week's attribution pack using web_sessions by utm_campaign.",
            deliverable_type="markdown",
            created_by="test",
        )
        board_store.add_tool_call(
            self.table,
            {
                "callId": "web-1",
                "op": "web_sessions",
                "toolId": "web",
                "status": "error",
                "resultPreview": "GA4 is not configured",
                "taskId": task["taskId"],
                "createdAt": board_store.now_iso(),
            },
        )
        task["status"] = "review"
        task["flags"] = ["no_evidence"]
        board_store.put_task(self.table, task)
        out = board_staff.apply_review(
            self.table, self.settings, task, verdict="accept", notes="unavailable with tool error", by="manager"
        )
        self.assertEqual(out["status"], "delivered")

    def test_weekly_readout_skips_when_meta_and_ga4_unconfigured(self) -> None:
        board_store.save_staff_override(self.table, "growth-specialist", {"isActive": True})
        with (
            patch.object(board_content, "_readout_unconfigured_reason", return_value="Meta page/IG and GA4 not configured"),
            patch.object(board_async, "invoke_async", side_effect=lambda payload, *, fallback=None: None),
        ):
            out = board_content.weekly_readout(self.table, self.settings)
        self.assertIsNone(out)
        tasks = board_store.list_tasks(self.table, "queued") + board_store.list_tasks(self.table, "running")
        self.assertFalse(any(str((t.get("eventRef") or {}).get("id") or "").startswith("config:") for t in tasks))
        gaps = board_duties.list_config_gaps(self.table)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["gapId"], "content-readout")
        updates = board_store.list_updates(self.table)
        self.assertTrue(any("CONFIG content-readout" in str(u.get("text") or "") for u in updates))

    def test_weekly_readout_skips_when_growth_specialist_inactive(self) -> None:
        board_store.save_staff_override(self.table, "growth-specialist", {"isActive": False})
        with patch.object(
            board_content, "_readout_unconfigured_reason", return_value="should not run"
        ):
            out = board_content.weekly_readout(self.table, self.settings)
        self.assertIsNone(out)
        self.assertEqual(board_duties.list_config_gaps(self.table), [])
        tasks = board_store.list_tasks(self.table, "queued") + board_store.list_tasks(self.table, "running")
        self.assertFalse(any(str((t.get("eventRef") or {}).get("kind") or "") == "duty" for t in tasks))

    def test_pending_approval_blocks_action_close(self) -> None:
        board_store.save_staff_override(self.table, "architect", {"isActive": True})
        board_store.put_action(
            self.table,
            {"actionId": "act-open", "title": "Dashboard", "status": "open", "createdAt": board_store.now_iso()},
        )
        task = board_staff.create_task(
            self.table,
            self.settings,
            assignee="architect",
            origin="owner",
            brief="Implement the dashboard",
            deliverable_type="markdown",
            action_id="act-open",
            created_by="test",
        )
        task["status"] = "review"
        task["flags"] = []
        task["actionId"] = "act-open"
        task["blockedOn"] = ["appr-1"]
        board_store.put_task(self.table, task)
        out = board_staff._accept_task(self.table, task, board_store.now_iso())  # noqa: SLF001
        self.assertEqual(out["status"], "delivered")
        self.assertEqual(board_store.get_action(self.table, "act-open")["status"], "open")


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

    def test_parse_mid_text_function_call(self) -> None:
        calls = board_tools.parse_prose_tool_calls(
            'scratch notes\n!function_call:{"name":"task_note","arguments":{"text":"x"}}\nthen more prose'
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "task_note")

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
        original = board_store.get_meeting(self.table, "m-fail")
        self.assertEqual(original["retriedByMeetingId"], "m-retry")
        # A second tick inside the two-hour window must not spawn another standup.
        with patch.object(board_meeting, "start_meeting") as start_again:
            self.assertIsNone(board_meeting.maybe_retry_failed_schedule(self.table, settings))
            start_again.assert_not_called()

    def test_failed_schedule_retry_refused_is_not_retried_again(self) -> None:
        settings = board_store.load_settings(self.table)
        settings["schedule"] = {"morningEnabled": True, "eveningEnabled": False}
        board_store.put_meeting(
            self.table,
            {
                "meetingId": "m-fail2",
                "status": "failed",
                "trigger": "schedule:morning",
                "createdAt": board_store.now_iso(),
                "updatedAt": board_store.now_iso(),
            },
        )
        with patch.object(board_meeting, "start_meeting", side_effect=board_meeting.MeetingError("busy")):
            self.assertIsNone(board_meeting.maybe_retry_failed_schedule(self.table, settings))
        self.assertTrue(str(board_store.get_meeting(self.table, "m-fail2")["retriedByMeetingId"]).startswith("skipped:"))
        with patch.object(board_meeting, "start_meeting") as start_again:
            self.assertIsNone(board_meeting.maybe_retry_failed_schedule(self.table, settings))
            start_again.assert_not_called()


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


class CodeImplementHandoffTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        patcher = patch.object(board_async, "invoke_async", side_effect=lambda payload, *, fallback=None: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.settings = _enable_staff(self.table)
        self.settings["tools"]["globalMode"] = "propose"
        board_store.save_settings(self.table, self.settings)
        board_store.save_staff_override(self.table, "engineer-1", {"isActive": True})

    def _implement(self) -> dict[str, Any]:
        task = board_staff.create_task(
            self.table,
            self.settings,
            assignee="engineer-1",
            origin="event",
            brief="Implement board-ready issue #484. Call code_run_task with issueNumber=484.",
            deliverable_type="pr",
            event_ref={"kind": "code-implement", "id": "issue:484", "issueNumber": 484},
            created_by="test",
        )
        latest = board_store.get_task(self.table, task["taskId"]) or task
        latest["status"] = "running"
        board_store.put_task(self.table, latest)
        return board_store.get_task(self.table, task["taskId"]) or latest

    def _ctx(self, task: dict[str, Any]) -> board_tools.ToolContext:
        return board_tools.ToolContext(
            table=self.table,
            settings=self.settings,
            persona_id="cto",
            display_name="CTO",
            kind="task",
            actor="persona",
            task_id=task["taskId"],
            seat_id="engineer-1",
        )

    def test_task_finish_parks_when_code_run_is_pending(self) -> None:
        task = self._implement()
        board_tools.create_approval(
            self._ctx(task),
            board_tools.REGISTRY["code_run_task"],
            {"issueNumber": 484, "brief": "Fix extract-zip", "kind": "fix", "reason": "sec"},
            summary="Dispatched the coding runner",
        )
        out = board_staff.op_task_finish(
            self._ctx(task),
            {
                "summary": "Proposed the runner.",
                "deliverableType": "markdown",
                "deliverable": "Awaiting founder approval to dispatch.",
                "evidence": [],
                "confidence": "low",
            },
        )
        self.assertEqual(out["status"], "waiting_approval")
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["status"], "waiting_approval")

    def test_reject_code_run_ends_implement_task(self) -> None:
        task = self._implement()
        approval = board_tools.create_approval(
            self._ctx(task),
            board_tools.REGISTRY["code_run_task"],
            {"issueNumber": 484, "brief": "Fix extract-zip", "kind": "fix", "reason": "sec"},
            summary="Dispatched the coding runner",
        )
        board_staff._park_waiting_approval(self.table, task, [approval["approvalId"]])
        approval["status"] = "rejected"
        approval["context"] = {"taskId": task["taskId"]}
        board_store.put_approval(self.table, approval)
        board_staff.resume_after_approval(self.table, self.settings, approval)
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["status"], "needs_owner")
        self.assertIn("rejected", latest.get("failureReason") or "")

    def test_approve_code_run_delivers_implement_task(self) -> None:
        task = self._implement()
        approval = board_tools.create_approval(
            self._ctx(task),
            board_tools.REGISTRY["code_run_task"],
            {"issueNumber": 484, "brief": "Fix extract-zip", "kind": "fix", "reason": "sec"},
            summary="Dispatched the coding runner",
        )
        board_staff._park_waiting_approval(self.table, task, [approval["approvalId"]])
        approval["status"] = "executed"
        approval["context"] = {"taskId": task["taskId"]}
        board_store.put_approval(self.table, approval)
        board_staff.resume_after_approval(self.table, self.settings, approval)
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["status"], "delivered")
        self.assertIn("code_runner_dispatched", latest.get("flags") or [])
        self.assertTrue(latest.get("expiresAt"))

    def _finish(self, task: dict[str, Any]) -> dict[str, Any]:
        return board_staff.op_task_finish(
            self._ctx(task),
            {
                "summary": "Runner handed off.",
                "deliverableType": "markdown",
                "deliverable": "code_run_task dispatched.",
                "evidence": [],
                "confidence": "low",
            },
        )

    def test_task_finish_refuses_code_implement_without_runner(self) -> None:
        task = self._implement()
        with self.assertRaises(board_staff.StaffError) as raised:
            self._finish(task)
        self.assertIn("code_run_task", str(raised.exception))
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["status"], "running")

    def test_task_finish_delivers_when_runner_already_dispatched(self) -> None:
        task = self._implement()
        approval = board_tools.create_approval(
            self._ctx(task),
            board_tools.REGISTRY["code_run_task"],
            {"issueNumber": 484, "brief": "Fix extract-zip", "kind": "fix", "reason": "sec"},
            summary="Dispatched the coding runner",
        )
        approval["status"] = "executed"
        approval["decidedAt"] = board_store.now_iso()
        approval["context"] = {"taskId": task["taskId"]}
        board_store.put_approval(self.table, approval)
        out = self._finish(task)
        self.assertEqual(out["status"], "delivered")
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["status"], "delivered")
        self.assertTrue(latest.get("expiresAt"))
        self.assertIn("code_runner_dispatched", latest.get("flags") or [])

    def test_task_finish_delivers_when_run_cache_dispatched(self) -> None:
        task = self._implement()
        board_code._put_run(  # noqa: SLF001
            self.table,
            task["taskId"],
            {
                "taskId": task["taskId"],
                "dispatchedAt": board_store.now_iso(),
                "runStatus": "in_progress",
            },
        )
        out = self._finish(task)
        self.assertEqual(out["status"], "delivered")
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["status"], "delivered")
        self.assertTrue(latest.get("expiresAt"))

    def test_task_finish_delivers_when_tool_call_ok(self) -> None:
        task = self._implement()
        board_store.add_tool_call(
            self.table,
            {
                "callId": "run-ok",
                "op": "code_run_task",
                "toolId": "code",
                "status": "ok",
                "taskId": task["taskId"],
                "createdAt": board_store.now_iso(),
            },
        )
        out = self._finish(task)
        self.assertEqual(out["status"], "delivered")

    def test_task_finish_after_retry_ignores_prior_failed_run(self) -> None:
        task = self._implement()
        old = "2026-09-14T09:21:59.000Z"
        approval = board_tools.create_approval(
            self._ctx(task),
            board_tools.REGISTRY["code_run_task"],
            {"issueNumber": 484, "brief": "Fix extract-zip", "kind": "fix", "reason": "sec"},
            summary="Dispatched the coding runner",
        )
        approval["status"] = "executed"
        approval["decidedAt"] = old
        approval["updatedAt"] = old
        approval["context"] = {"taskId": task["taskId"]}
        board_store.put_approval(self.table, approval)
        board_code._put_run(  # noqa: SLF001
            self.table,
            task["taskId"],
            {
                "taskId": task["taskId"],
                "dispatchedAt": old,
                "failedAt": "2026-09-14T09:25:00.000Z",
                "conclusion": "failure",
                "runStatus": "completed",
            },
        )
        board_store.add_tool_call(
            self.table,
            {
                "callId": "run-old",
                "op": "code_run_task",
                "toolId": "code",
                "status": "ok",
                "taskId": task["taskId"],
                "createdAt": old,
            },
        )
        task["status"] = "needs_owner"
        board_store.put_task(self.table, task)
        retried = board_staff.retry_task(self.table, self.settings, task["taskId"], "owner")
        retried["status"] = "running"
        board_store.put_task(self.table, retried)
        # Prior failed dispatch must not count as a live runner, so finish
        # still requires a new code_run_task (it must not auto-deliver).
        with self.assertRaises(board_staff.StaffError) as raised:
            self._finish(retried)
        self.assertIn("code_run_task", str(raised.exception))
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["status"], "running")
        self.assertFalse(latest.get("expiresAt"))
        self.assertNotIn("code_runner_dispatched", latest.get("flags") or [])


class ApprovalAndCallIdTests(BoardTestCase):
    def test_code_run_task_dedupes_pending_by_issue(self) -> None:
        settings = board_store.default_settings()
        settings["tools"]["globalMode"] = "propose"
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=settings,
            persona_id="cto",
            display_name="CTO",
            kind="task",
            actor="persona",
            task_id="impl-1",
        )
        first = board_tools.create_approval(
            ctx,
            board_tools.REGISTRY["code_run_task"],
            {"issueNumber": 484, "brief": "Fix extract-zip", "kind": "fix", "reason": "first"},
            summary="Dispatched the coding runner",
        )
        second = board_tools.create_approval(
            ctx,
            board_tools.REGISTRY["code_run_task"],
            {"issueNumber": 484, "brief": "Different wording", "kind": "fix", "reason": "again"},
            summary="Retry extract-zip with a tighter brief",
        )
        self.assertEqual(first["approvalId"], second["approvalId"])
        pending = [a for a in board_store.list_approvals(self.table) if a.get("status") == "pending"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["arguments"]["brief"], "Different wording")
        self.assertEqual(pending[0]["summary"], "Retry extract-zip with a tighter brief")

    def test_execute_call_returns_internal_call_id(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        settings = _enable_staff(self.table)
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=settings,
            persona_id="ceo",
            display_name="CEO",
            kind="task",
            actor="persona",
            task_id="t-1",
            llm_tool_call_id="call_xBcJqwPl7xTCkUM4TCnz6XgI",
        )
        outcome = board_tools.execute_call(ctx, board_tools.REGISTRY["staff_list_tasks"], {"limit": 5})
        self.assertTrue(outcome.call_id)
        self.assertEqual(outcome.result.get("callId"), outcome.call_id)
        stored = board_store.list_tool_calls_for_task(self.table, "t-1")
        self.assertEqual(stored[0]["toolCallId"], "call_xBcJqwPl7xTCkUM4TCnz6XgI")


if __name__ == "__main__":
    unittest.main()
