"""Unit tests for Executive Board triage and reply policy (WP3)."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from test_board import BoardTestCase
from test_board_mail import build_mail

import board_async
import board_budget
import board_holds
import board_mail
import board_policy
import board_staff
import board_store
import board_templates
import board_tools
import board_triage


def _enable_staff(table: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True})
    settings["tools"]["globalMode"] = "act"
    return board_store.save_settings(table, settings)


class FakeCompletion:
    def __init__(self, text: str) -> None:
        self.text = text
        self.model = "test"
        self.usage = {"cost": 0.0, "promptTokens": 1, "completionTokens": 1}
        self.tool_calls = []


class TriageTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        _enable_staff(self.table)
        patcher = patch.object(board_async, "invoke_async", side_effect=lambda payload, fallback=None: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_keyword_escalation_both_scripts(self) -> None:
        en = board_triage.classify_text(self.table, board_store.load_settings(self.table), "my son was injured yesterday", channel="mail")
        self.assertTrue(en["escalate"])
        zh = board_triage.classify_text(self.table, board_store.load_settings(self.table), "小朋友受傷了", channel="mail")
        self.assertTrue(zh["escalate"])

    def test_prospect_domain_routes_to_provider_success(self) -> None:
        board_store.put_prospect(self.table, {"prospectId": "p1", "type": "provider", "stage": "qualified"})
        board_store.put_prospect_key(self.table, "studio.example", "p1")
        settings = board_store.load_settings(self.table)
        with patch.object(board_budget, "board_completion", return_value=FakeCompletion('{"audience":"provider","intent":"question","escalate":false,"reason":""}')):
            classified = board_triage.classify_text(self.table, settings, "can we list our classes?", channel="mail", sender="info@studio.example")
        self.assertEqual(classified["audience"], "provider")

    def test_model_classification_cached(self) -> None:
        settings = board_store.load_settings(self.table)
        fake = FakeCompletion('{"audience":"parent","intent":"booking","escalate":false,"reason":""}')
        with patch("board_budget.board_completion", return_value=fake) as mocked:
            first = board_triage.classify_text(self.table, settings, "any Saturday swim in Sha Tin?", channel="mail")
            second = board_triage.classify_text(self.table, settings, "any Saturday swim in Sha Tin?", channel="mail")
        self.assertEqual(first["audience"], "parent")
        self.assertEqual(second["intent"], "booking")
        self.assertEqual(mocked.call_count, 1)

    def test_one_task_per_thread_appends_new_message(self) -> None:
        with patch("board_budget.board_completion", return_value=FakeCompletion('{"audience":"parent","intent":"question","escalate":false,"reason":""}')):
            first = board_mail.ingest_bytes(self.table, build_mail(text="Is there swimming in Sha Tin?", message_id="<one@test>"))
            second = board_mail.ingest_bytes(
                self.table,
                build_mail(text="Also Saturday morning?", message_id="<two@test>", in_reply_to="<one@test>", references="<one@test>"),
            )
        self.assertEqual(first["threadId"], second["threadId"])
        tasks = [t for status in ("queued", "running") for t in board_store.list_tasks(self.table, status)]
        self.assertEqual(len({t["taskId"] for t in tasks}), 1)
        task = tasks[0]
        pad = board_staff._blob_get(task.get("scratchpadKey") or f"board/siuTinDei/staff/{task['taskId']}/scratchpad.md").decode()
        self.assertIn("NEW MESSAGE", pad)

    def test_injury_is_needs_owner_and_sends_ack(self) -> None:
        seen: list[tuple[str, dict[str, Any]]] = []

        def capture(ctx: Any, op: Any, args: dict[str, Any]) -> board_tools.ToolOutcome:
            seen.append((op.name, args))
            return board_tools.ToolOutcome(status="ok", result={"ok": True}, summary="ack")

        with patch.object(board_tools, "execute_call", side_effect=capture):
            board_mail.ingest_bytes(self.table, build_mail(text="my son was injured at class", message_id="<inj@test>"))
        tasks = board_store.list_tasks(self.table, "needs_owner")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["assignee"], "support")
        self.assertTrue(any(name == "mail_reply" and args.get("templateId") == "ack_escalation" for name, args in seen))

    def test_bulk_headers_skip_triage(self) -> None:
        board_mail.ingest_bytes(
            self.table,
            build_mail(text="newsletter", headers={"Auto-Submitted": "auto-generated", "List-Unsubscribe": "<mailto:u@x>"}, message_id="<bulk@test>"),
        )
        self.assertEqual(board_store.list_tasks(self.table, "queued"), [])
        self.assertEqual(board_store.list_tasks(self.table, "needs_owner"), [])

    def test_review_detection_dedupe(self) -> None:
        settings = board_store.load_settings(self.table)
        reviews = [{"reviewId": "r1", "store": "apple", "rating": 2, "text": "app crashed"}]
        first = board_triage.on_store_reviews(self.table, settings, reviews)
        second = board_triage.on_store_reviews(self.table, settings, reviews)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["taskId"], second[0]["taskId"])


class PolicyTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        _enable_staff(self.table)
        patcher = patch.object(board_async, "invoke_async", side_effect=lambda payload, fallback=None: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_forbidden_promise_becomes_approval(self) -> None:
        settings = board_store.load_settings(self.table)
        ctx = board_tools.ToolContext(table=self.table, settings=settings, persona_id="coo", display_name="COO")
        reason = board_policy.check_reply(
            settings,
            ctx,
            board_tools.REGISTRY["mail_reply"],
            {"threadId": "t", "body": "We guarantee a refund of $50", "reason": "x"},
            {},
        )
        self.assertIn("refund", reason or "")

    def test_missing_sensitive_template(self) -> None:
        settings = board_store.load_settings(self.table)
        ctx = board_tools.ToolContext(table=self.table, settings=settings, persona_id="coo", display_name="COO")
        reason = board_policy.check_reply(
            settings,
            ctx,
            board_tools.REGISTRY["mail_reply"],
            {"threadId": "t", "body": "About your card", "reason": "x"},
            {"intent": "payment_dispute"},
        )
        self.assertIn("template", reason or "")

    def test_per_thread_cap(self) -> None:
        settings = board_store.load_settings(self.table)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        thread = {"threadId": "t", "repliesToday": 3, "repliesDate": today}
        ctx = board_tools.ToolContext(table=self.table, settings=settings, persona_id="coo", display_name="COO")
        reason = board_policy.check_reply(
            settings,
            ctx,
            board_tools.REGISTRY["mail_reply"],
            {"threadId": "t", "body": "hello again", "reason": "x"},
            thread,
        )
        self.assertIn("daily reply limit", reason or "")

    def test_quiet_hours_hold_not_approval(self) -> None:
        settings = board_store.load_settings(self.table)
        settings["boundaries"]["holds"]["inbound_reply"] = 0
        board_store.save_settings(self.table, settings)
        settings["tools"]["allowList"] = ["wendy.chan@gmail.com"]
        board_store.save_settings(self.table, settings)
        board_store.put_mail_thread(
            self.table,
            {
                "threadId": "th-q",
                "subject": "hi",
                "mailbox": "hello@siutindei.com",
                "lastFrom": "wendy.chan@gmail.com",
                "participants": ["wendy.chan@gmail.com"],
            },
        )
        frozen = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)  # 23:00 HKT
        ctx = board_tools.ToolContext(table=self.table, settings=settings, persona_id="coo", display_name="COO", actor="persona")
        with patch("board_policy.datetime") as pdt, patch("board_holds.datetime") as hdt:
            pdt.now.return_value = frozen
            pdt.side_effect = lambda *a, **k: datetime(*a, **k)
            hdt.now.return_value = frozen
            hdt.side_effect = lambda *a, **k: datetime(*a, **k)
            outcome = board_tools.execute_call(
                ctx,
                board_tools.REGISTRY["mail_reply"],
                {"threadId": "th-q", "body": "Thanks for writing.", "reason": "reply"},
            )
        self.assertEqual(outcome.status, "held")
        holds = board_store.list_holds(self.table, "scheduled")
        self.assertEqual(len(holds), 1)
        self.assertTrue(holds[0]["executeAt"].startswith("2026-09-11T00:00:00"))

    def test_template_render(self) -> None:
        self.assertIn("siutindei", board_templates.render("ack_escalation", "en").lower())
        self.assertIn("小天地", board_templates.render("ack_escalation", "zh-HK"))
        self.assertEqual(board_templates.pick_lang("受傷"), "zh-HK")


if __name__ == "__main__":
    unittest.main()
