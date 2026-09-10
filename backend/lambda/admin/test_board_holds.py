"""Unit tests for Executive Board hold windows (WP2)."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from test_board import BoardTestCase
from test_board_tools import ToolsTestCase

import board_holds
import board_store
import board_tools
from contract_constants import (
    BOARD_STAFF_RAMP_DEMOTE_WINDOW_ACTIONS,
    BOARD_STAFF_RAMP_MIN_ACTIONS,
)


def _enable_staff(table: Any, **staff: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True, **staff})
    settings["tools"]["globalMode"] = "act"
    return board_store.save_settings(table, settings)


def _ctx(table: Any, settings: dict[str, Any], persona: str = "cmo") -> board_tools.ToolContext:
    return board_tools.ToolContext(
        table=table,
        settings=settings,
        persona_id=persona,
        display_name=persona.upper(),
        kind="chat",
        actor="persona",
    )


def _op(name: str) -> board_tools.ToolOp:
    return board_tools.REGISTRY[name]


class ClassifyTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = board_store.default_settings()
        self.ctx = board_tools.ToolContext(
            table=self.table,
            settings=self.settings,
            persona_id="cmo",
            display_name="CMO",
        )

    def _cls(self, name: str, args: dict[str, Any] | None = None) -> tuple[str, str]:
        return board_holds.classify(_op(name), self.ctx, args or {}, self.settings)

    def test_classification_table(self) -> None:
        self.assertEqual(self._cls("staff_assign"), ("internal", "internal"))
        self.assertEqual(self._cls("task_note"), ("internal", "internal"))
        self.assertEqual(self._cls("board_add_action"), ("internal", "internal"))
        self.assertEqual(self._cls("github_create_issue"), ("internal", "internal"))
        self.assertEqual(self._cls("github_comment_issue"), ("internal", "internal"))
        self.assertEqual(self._cls("github_set_labels"), ("internal", "internal"))
        self.assertEqual(self._cls("product_flag_listing"), ("internal", "internal"))
        self.assertEqual(self._cls("security_open_remediation"), ("internal", "internal"))
        self.assertEqual(self._cls("aws_propose_budget_alert"), ("internal", "internal"))
        self.assertEqual(self._cls("finance_draft_invoice"), ("internal", "internal"))
        self.assertEqual(self._cls("finance_propose_price_change"), ("internal", "internal"))
        self.assertEqual(self._cls("finance_record_manual_payment"), ("internal", "internal"))
        self.assertEqual(self._cls("finance_match_payment"), ("internal", "internal"))
        self.assertEqual(self._cls("mail_reply"), ("inbound_reply", "inbound_reply:mail"))
        self.assertEqual(self._cls("meta_reply_comment"), ("inbound_reply", "inbound_reply:meta"))
        self.assertEqual(self._cls("meta_reply_dm"), ("inbound_reply", "inbound_reply:meta"))
        self.assertEqual(self._cls("meta_reply_whatsapp"), ("inbound_reply", "inbound_reply:whatsapp"))
        self.assertEqual(self._cls("stores_reply_review"), ("inbound_reply", "inbound_reply:stores"))
        self.assertEqual(self._cls("mail_send", {"to": "stranger@example.com"}), ("cold_outreach", "cold_outreach:unknown"))
        self.assertEqual(self._cls("mail_forward", {"to": "stranger@example.com"}), ("cold_outreach", "cold_outreach:unknown"))
        self.assertEqual(self._cls("finance_send_invoice", {"to": "stranger@example.com"}), ("cold_outreach", "cold_outreach:unknown"))
        self.assertEqual(self._cls("finance_send_reminder", {"to": "stranger@example.com"}), ("cold_outreach", "cold_outreach:unknown"))
        self.assertEqual(self._cls("meta_relay_lead", {"to": "stranger@example.com"}), ("cold_outreach", "cold_outreach:unknown"))
        self.assertEqual(self._cls("meta_propose_post"), ("publish", "publish:facebook"))
        self.assertEqual(self._cls("meta_propose_story"), ("publish", "publish:instagram"))
        self.assertEqual(self._cls("stores_draft_release_notes"), ("publish", "publish:stores"))
        self.assertEqual(self._cls("meta_create_ad_set"), ("spend", "spend:meta"))
        self.assertEqual(self._cls("meta_boost_post"), ("spend", "spend:meta"))


class HoldHoursTests(BoardTestCase):
    def test_override_and_breaker_default(self) -> None:
        settings = _enable_staff(self.table)
        settings["boundaries"]["holdOverrides"]["publish:facebook"] = 0
        board_store.save_settings(self.table, settings)
        self.assertEqual(board_holds.hold_hours(self.table, settings, "publish", "publish:facebook"), 0)
        board_store.put_breaker(self.table, "publish", {"tripped": True, "reason": "test"})
        self.assertEqual(board_holds.hold_hours(self.table, settings, "publish", "publish:facebook"), 24)


class ExecuteCallHoldTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))

    def test_act_publish_is_held_not_approval(self) -> None:
        settings = _enable_staff(self.table)
        op = _op("meta_propose_post")
        outcome = board_tools.execute_call(
            _ctx(self.table, settings, "cmo"),
            op,
            {"message": "Saturday swim in Sha Tin", "reason": "weekly spotlight"},
        )
        self.assertEqual(outcome.status, "held")
        self.assertTrue(outcome.result.get("holdId"))
        self.assertIn("unless vetoed", outcome.summary)
        holds = board_store.list_holds(self.table, "scheduled")
        self.assertEqual(len(holds), 1)
        self.assertEqual(holds[0]["op"], "meta_propose_post")
        self.assertEqual(holds[0]["actionClass"], "publish")
        approvals = [a for a in board_store.list_approvals(self.table) if a.get("status") == "pending"]
        self.assertEqual(approvals, [])

    def test_staff_off_keeps_always_propose_as_approval(self) -> None:
        settings = board_store.load_settings(self.table)
        settings["tools"]["globalMode"] = "act"
        board_store.save_settings(self.table, settings)
        outcome = board_tools.execute_call(
            _ctx(self.table, settings, "cmo"),
            _op("meta_propose_post"),
            {"message": "x", "reason": "test"},
        )
        self.assertEqual(outcome.status, "pending_approval")

    def test_hold_zero_still_executes_or_approves(self) -> None:
        settings = _enable_staff(self.table)
        settings["boundaries"]["holds"]["internal"] = 0
        board_store.save_settings(self.table, settings)
        outcome = board_tools.execute_call(
            _ctx(self.table, settings, "ceo"),
            _op("board_add_action"),
            {
                "title": "Pick a launch date",
                "detail": "Calendar it.",
                "priority": "now",
                "reason": "needed",
            },
        )
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(board_store.list_holds(self.table, "scheduled"), [])

    def test_quiet_hours_shift_to_next_morning(self) -> None:
        settings = _enable_staff(self.table)
        settings["boundaries"]["holds"]["publish"] = 24
        board_store.save_settings(self.table, settings)
        frozen = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)  # 23:00 HKT
        with patch("board_holds.datetime") as dt:
            dt.now.return_value = frozen
            dt.side_effect = lambda *a, **k: datetime(*a, **k)
            doc = board_holds.create_hold(
                _ctx(self.table, settings, "cmo"),
                _op("meta_propose_post"),
                {"message": "x", "reason": "t"},
                action_class="publish",
                class_key="publish:facebook",
                hours=24,
                summary="Propose Page post",
            )
        # 15:00 UTC + 24h = 23:00 HKT next day → quiet → 08:00 HKT after that = 00:00 UTC Sep 12
        self.assertTrue(doc["executeAt"].startswith("2026-09-12T00:00:00"))


class ExecuteDueAndVetoTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))

    def _scheduled_action(self) -> dict[str, Any]:
        settings = _enable_staff(self.table)
        settings["boundaries"]["holds"]["internal"] = 24
        settings = board_store.save_settings(self.table, settings)
        outcome = board_tools.execute_call(
            _ctx(self.table, settings, "ceo"),
            _op("board_add_action"),
            {
                "title": "Call ten providers",
                "detail": "Book the calls.",
                "priority": "now",
                "reason": "pipeline",
            },
        )
        self.assertEqual(outcome.status, "held")
        hold = board_store.get_hold(self.table, outcome.result["holdId"])
        assert hold is not None
        hold["executeAt"] = "2020-01-01T00:00:00Z"
        board_store.put_hold(self.table, hold)
        return hold

    def test_execute_due_runs_through_execute_call(self) -> None:
        hold = self._scheduled_action()
        settings = board_store.load_settings(self.table)
        ran = board_holds.execute_due(self.table, settings, "2026-09-10T00:00:00Z")
        self.assertEqual(ran, 1)
        stored = board_store.get_hold(self.table, hold["holdId"])
        self.assertEqual(stored["status"], "executed")
        actions = board_store.list_actions(self.table)
        self.assertTrue(any("Call ten providers" in str(a.get("title") or "") for a in actions))

    def test_veto_prevents_execution(self) -> None:
        hold = self._scheduled_action()
        board_holds.veto(self.table, hold["holdId"], "owner", "not this week")
        settings = board_store.load_settings(self.table)
        ran = board_holds.execute_due(self.table, settings, "2026-09-10T00:00:00Z")
        self.assertEqual(ran, 0)
        stored = board_store.get_hold(self.table, hold["holdId"])
        self.assertEqual(stored["status"], "vetoed")
        self.assertEqual(board_store.list_actions(self.table), [])

    def test_veto_class_today(self) -> None:
        hold = self._scheduled_action()
        vetoed = board_holds.veto_class_today(self.table, hold["classKey"], "owner")
        self.assertEqual(len(vetoed), 1)
        self.assertEqual(vetoed[0]["status"], "vetoed")

    def test_mail_reply_thread_changed_fails(self) -> None:
        settings = _enable_staff(self.table)
        settings["boundaries"]["holds"]["inbound_reply"] = 24
        settings = board_store.save_settings(self.table, settings)
        board_store.put_mail_thread(
            self.table,
            {
                "threadId": "th-1",
                "subject": "swim",
                "lastInboundAt": "2026-09-10T10:00:00Z",
                "updatedAt": "2026-09-10T10:00:00Z",
            },
        )
        hold = board_holds.create_hold(
            _ctx(self.table, settings, "coo"),
            _op("mail_reply"),
            {"threadId": "th-1", "body": "Thanks", "reason": "reply"},
            action_class="inbound_reply",
            class_key="inbound_reply:mail",
            hours=24,
            summary="Reply",
        )
        hold["executeAt"] = "2020-01-01T00:00:00Z"
        board_store.put_hold(self.table, hold)
        thread = board_store.get_mail_thread(self.table, "th-1") or {}
        thread["lastInboundAt"] = "2026-09-10T12:00:00Z"
        board_store.put_mail_thread(self.table, thread)
        ran = board_holds.execute_due(self.table, settings, "2026-09-10T13:00:00Z")
        self.assertEqual(ran, 1)
        stored = board_store.get_hold(self.table, hold["holdId"])
        self.assertEqual(stored["status"], "failed")
        self.assertIn("thread changed", str(stored.get("result") or ""))


class RampTests(BoardTestCase):
    def test_promotion_and_demotion_thresholds(self) -> None:
        settings = _enable_staff(self.table)
        key = "publish:facebook"
        for _ in range(BOARD_STAFF_RAMP_MIN_ACTIONS):
            board_holds.record_ramp(self.table, settings, key, vetoed=False)
        state = board_holds.ramp_state(self.table, key)
        self.assertTrue(state["eligibleForPromotion"])
        self.assertFalse(state["shouldDemote"])
        settings["boundaries"]["holdOverrides"][key] = 0
        board_store.save_settings(self.table, settings)
        for _ in range(BOARD_STAFF_RAMP_DEMOTE_WINDOW_ACTIONS):
            board_holds.record_ramp(self.table, settings, key, vetoed=True)
        settings = board_store.load_settings(self.table)
        self.assertNotIn(key, settings["boundaries"].get("holdOverrides") or {})


class HoldRouteTests(ToolsTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        _enable_staff(self.table)

    def test_holds_and_veto_routes(self) -> None:
        settings = board_store.load_settings(self.table)
        outcome = board_tools.execute_call(
            _ctx(self.table, settings, "cmo"),
            _op("meta_propose_post"),
            {"message": "Hi", "reason": "test"},
        )
        hold_id = outcome.result["holdId"]
        status, body = self.call("/siu-tin-dei/board/holds")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["holds"]), 1)
        status, body = self.call(f"/siu-tin-dei/board/holds/{hold_id}/veto", "POST", {"reason": "no"})
        self.assertEqual(status, 200)
        self.assertEqual(body["hold"]["status"], "vetoed")
        status, body = self.call("/siu-tin-dei/board/holds/missing/veto", "POST", {"reason": "x"})
        self.assertEqual(status, 404)

    def test_veto_class_and_boundaries_and_ramp(self) -> None:
        settings = board_store.load_settings(self.table)
        board_tools.execute_call(
            _ctx(self.table, settings, "cmo"),
            _op("meta_propose_post"),
            {"message": "Hi", "reason": "test"},
        )
        status, body = self.call("/siu-tin-dei/board/holds/veto-class", "POST", {"classKey": "publish:facebook"})
        self.assertEqual(status, 200)
        self.assertEqual(len(body["holds"]), 1)
        status, body = self.call("/siu-tin-dei/board/holds/veto-class", "POST", {})
        self.assertEqual(status, 400)
        status, body = self.call(
            "/siu-tin-dei/board/boundaries",
            "PUT",
            {"holds": {"publish": 12}, "reply": {"quietHoursHkt": [23, 7]}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["boundaries"]["holds"]["publish"], 12)
        status, body = self.call("/siu-tin-dei/board/ramp")
        self.assertEqual(status, 200)
        self.assertTrue(any(r["classKey"] == "publish:facebook" for r in body["ramp"]))

    def test_disabled_env_returns_409(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "false"
        status, body = self.call("/siu-tin-dei/board/holds")
        self.assertEqual(status, 409)
        self.assertEqual(body["message"], "Staff is disabled")


class PreambleTests(unittest.TestCase):
    def test_held_is_explained_to_the_model(self) -> None:
        settings = board_store.default_settings()
        settings["tools"]["globalMode"] = "act"
        ops = board_tools.available_ops(settings, "cmo", context="chat")
        text = board_tools.tools_preamble(ops)
        self.assertIn("held", text)
        self.assertIn("I have scheduled", text)


if __name__ == "__main__":
    unittest.main()
