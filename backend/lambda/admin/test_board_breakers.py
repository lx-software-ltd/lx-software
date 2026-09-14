"""Unit tests for Executive Board breakers (WP4)."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

from test_board import BoardTestCase
from test_board_tools import ToolsTestCase

import board_async
import board_breakers
import board_hk
import board_holds
import board_staff
import board_store
import board_tools


def _enable_staff(table: Any, **staff: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True, **staff})
    settings["tools"]["globalMode"] = "act"
    return board_store.save_settings(table, settings)


class BreakerRuleTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.settings = _enable_staff(self.table, dailyBudgetUsd=20)

    def test_budget_100_disables_staff(self) -> None:
        board_store.add_staff_usage_day(self.table, "support", {"cost": 20.0, "calls": 1})
        tripped = board_breakers.evaluate(self.table, board_store.load_settings(self.table))
        self.assertIn("budget", tripped)
        settings = board_store.load_settings(self.table)
        self.assertFalse(settings["staff"]["enabled"])
        self.assertTrue(board_breakers.is_tripped(self.table, "budget"))

    def test_budget_80_before_noon_pauses_senior(self) -> None:
        board_store.add_staff_usage_day(self.table, "support", {"cost": 16.0, "calls": 1})
        noon_before = board_hk.parse_iso("2026-09-09T02:00:00Z")  # 10:00 HKT
        with patch.object(board_hk, "now_hkt", return_value=board_hk.as_hkt(noon_before)):
            tripped = board_breakers.evaluate(self.table, board_store.load_settings(self.table))
        self.assertIn("budget", tripped)
        settings = board_store.load_settings(self.table)
        self.assertTrue(settings["staff"]["seniorPaused"])
        self.assertTrue(settings["staff"]["enabled"])

    def test_tool_errors_trip(self) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(10):
            board_store.add_tool_call(
                self.table,
                {
                    "callId": f"err-{i}",
                    "op": "mail_reply",
                    "toolId": "mail",
                    "status": "error",
                    "summary": "failed",
                    "createdAt": now,
                    "personaId": "coo",
                },
            )
        tripped = board_breakers.evaluate(self.table, self.settings)
        self.assertIn("tool:mail", tripped)
        self.assertTrue(board_breakers.is_tripped(self.table, "tool:mail"))

    def test_auto_reset_waits_for_age_and_low_count(self) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(4):
            board_store.add_tool_call(
                self.table,
                {
                    "callId": f"low-{i}",
                    "op": "mail_reply",
                    "toolId": "mail",
                    "status": "error",
                    "summary": "failed",
                    "createdAt": now,
                },
            )
        board_breakers.trip(self.table, "tool:mail", "10 errors in the last hour")
        board_breakers.evaluate(self.table, self.settings)
        self.assertTrue(board_breakers.is_tripped(self.table, "tool:mail"))
        row = board_store.get_breaker(self.table, "tool:mail")
        row["trippedAt"] = (datetime.now(timezone.utc) - timedelta(minutes=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
        board_store.put_breaker(self.table, "tool:mail", row)
        board_breakers.evaluate(self.table, self.settings)
        self.assertFalse(board_breakers.is_tripped(self.table, "tool:mail"))
        self.assertTrue(any("reset (auto)" in str(u.get("text") or "") for u in board_store.list_updates(self.table)))

    def test_auto_reset_skips_when_countable_errors_still_high(self) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(8):
            board_store.add_tool_call(
                self.table,
                {
                    "callId": f"mid-{i}",
                    "op": "mail_reply",
                    "toolId": "mail",
                    "status": "error",
                    "summary": "failed",
                    "createdAt": now,
                },
            )
        board_breakers.trip(self.table, "tool:mail", "10 errors in the last hour")
        row = board_store.get_breaker(self.table, "tool:mail")
        row["trippedAt"] = (datetime.now(timezone.utc) - timedelta(minutes=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
        board_store.put_breaker(self.table, "tool:mail", row)
        board_breakers.evaluate(self.table, self.settings)
        self.assertTrue(board_breakers.is_tripped(self.table, "tool:mail"))

    def test_channel_after_reply_then_escalation(self) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        board_store.add_tool_call(
            self.table,
            {
                "callId": "reply-1",
                "op": "mail_reply",
                "toolId": "mail",
                "status": "ok",
                "summary": "replied",
                "createdAt": now,
                "arguments": {"threadId": "th-1"},
                "personaId": "coo",
            },
        )
        board_breakers.note_escalation_after_reply(self.table, channel="mail", thread_id="th-1")
        self.assertTrue(board_breakers.is_tripped(self.table, "channel:mail"))

    def test_class_demote_trips_class_breaker(self) -> None:
        board_store.put_hold(
            self.table,
            {
                "holdId": "h-ramp",
                "status": "executed",
                "classKey": "publish:facebook",
                "actionClass": "publish",
                "executeAt": board_store.now_iso(),
            },
        )
        board_store.save_ramp(
            self.table,
            "publish:facebook",
            {
                "classKey": "publish:facebook",
                "actions": 20,
                "vetoes": 20,
                "days": {},
                "recent": ["veto"] * 20,
            },
        )
        tripped = board_breakers.evaluate(self.table, self.settings)
        self.assertIn("class:publish:facebook", tripped)

    def test_task_errors_never_trip_and_clear_existing(self) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(12):
            board_store.add_tool_call(
                self.table,
                {
                    "callId": f"task-err-{i}",
                    "op": "task_finish",
                    "toolId": "task",
                    "status": "error",
                    "resultPreview": '{"error": "breaker tripped", "breaker": "tool:task"}',
                    "createdAt": now,
                },
            )
        tripped = board_breakers.evaluate(self.table, self.settings)
        self.assertNotIn("tool:task", tripped)
        board_breakers.trip(self.table, "tool:task", "11 errors in the last hour")
        board_breakers.evaluate(self.table, self.settings)
        self.assertFalse(board_breakers.is_tripped(self.table, "tool:task"))

    def test_evidence_validation_errors_do_not_trip_mail_or_web(self) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(12):
            board_store.add_tool_call(
                self.table,
                {
                    "callId": f"ev-{i}",
                    "op": "task_finish",
                    "toolId": "web",
                    "status": "error",
                    "resultPreview": "This brief requires evidence from web_sessions, web_conversions.",
                    "createdAt": now,
                },
            )
        tripped = board_breakers.evaluate(self.table, self.settings)
        self.assertNotIn("tool:web", tripped)

    def test_reset(self) -> None:
        board_breakers.trip(self.table, "tool:mail", "test")
        board_breakers.reset(self.table, "tool:mail", "owner")
        self.assertFalse(board_breakers.is_tripped(self.table, "tool:mail"))
        updates = board_store.list_updates(self.table)
        self.assertTrue(any("BREAKER tool:mail" in str(u.get("text") or "") for u in updates))


class BreakerExecuteCallTests(ToolsTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.settings = _enable_staff(self.table)

    def test_execute_call_refuses_when_tool_tripped(self) -> None:
        board_breakers.trip(self.table, "tool:staff", "test")
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=board_store.load_settings(self.table),
            persona_id="ceo",
            display_name="CEO",
            kind="chat",
            actor="persona",
        )
        outcome = board_tools.execute_call(
            ctx,
            board_tools.REGISTRY["staff_assign"],
            {"assignee": "cfo", "brief": "Write a one-line status", "deliverableType": "markdown"},
        )
        self.assertEqual(outcome.status, "error")
        self.assertEqual(outcome.result.get("breaker"), "tool:staff")

    def test_execute_call_works_after_reset(self) -> None:
        board_breakers.trip(self.table, "tool:staff", "test")
        board_breakers.reset(self.table, "tool:staff", "owner")
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=board_store.load_settings(self.table),
            persona_id="ceo",
            display_name="CEO",
            kind="chat",
            actor="persona",
        )
        outcome = board_tools.execute_call(
            ctx,
            board_tools.REGISTRY["staff_list_tasks"],
            {"limit": 5},
        )
        self.assertNotEqual(outcome.result.get("breaker"), "tool:staff")

    def test_task_finish_still_runs_when_task_breaker_tripped(self) -> None:
        board_breakers.trip(self.table, "tool:task", "test")
        settings = board_store.load_settings(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(
                self.table,
                settings,
                assignee="support",
                origin="owner",
                brief="Write a one-line status. No tools required.",
                deliverable_type="markdown",
                created_by="test",
            )
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=settings,
            persona_id="ceo",
            display_name="CEO",
            kind="task",
            actor="persona",
            task_id=task["taskId"],
            seat_id="support",
        )
        outcome = board_tools.execute_call(
            ctx,
            board_tools.REGISTRY["task_finish"],
            {
                "summary": "Done",
                "deliverableType": "markdown",
                "deliverable": "Status is green.",
                "evidence": [],
                "confidence": "low",
            },
        )
        self.assertNotEqual(outcome.result.get("breaker"), "tool:task")
        self.assertNotEqual(outcome.status, "error")


if __name__ == "__main__":
    unittest.main()
