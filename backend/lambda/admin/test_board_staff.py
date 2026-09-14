"""Unit tests for Executive Board staff tasks (WP1)."""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

from test_board import BoardTestCase
from test_board_tools import ScriptedOpenRouter, ToolsTestCase

import board_async
import board_personas
import board_staff
import board_store
import board_tools
from contract_constants import (
    BOARD_KEY,
    BOARD_STAFF_MAX_IDLE_STEPS_PER_TASK,
    BOARD_STAFF_MAX_STEPS_PER_TASK,
    BOARD_STAFF_TASK_BUDGET_DESK_USD,
)


def _enable_staff(table: Any, **staff: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True, **staff})
    return board_store.save_settings(table, settings)


class StaffEngineTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.async_payloads: list[dict[str, Any]] = []

        def capture(payload: dict[str, Any], *, fallback: Any = None) -> None:  # noqa: ARG001
            self.async_payloads.append(payload)

        patcher = patch.object(board_async, "invoke_async", side_effect=capture)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_seat_level_capped_by_manager_and_global(self) -> None:
        settings = _enable_staff(self.table)
        settings["tools"]["globalMode"] = "propose"
        settings["tools"]["matrix"]["mail"]["coo"] = "act"
        board_store.save_settings(self.table, settings)
        board_store.save_staff_override(self.table, "support", {"isActive": True})
        roster = board_staff.seats_by_id(self.table, settings)
        self.assertEqual(board_staff.seat_level(settings, roster, "support", "mail"), "propose")

    def test_benched_manager_turns_seat_off(self) -> None:
        settings = _enable_staff(self.table)
        settings["tools"]["matrix"]["mail"]["coo"] = "off"
        board_store.save_settings(self.table, settings)
        board_store.save_staff_override(self.table, "support", {"isActive": True})
        roster = board_staff.seats_by_id(self.table, settings)
        self.assertEqual(board_staff.seat_level(settings, roster, "support", "mail"), "off")

    def test_inactive_seat_is_off(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "architect", {"isActive": False})
        roster = board_staff.seats_by_id(self.table, settings)
        self.assertFalse(roster["architect"]["isActive"])
        self.assertEqual(board_staff.seat_level(settings, roster, "architect", "mail"), "off")

    def test_security_analyst_task_exposes_github_security_and_research(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "security-analyst", {"isActive": True})
        board_store.save_staff_override(self.table, "support", {"isActive": True})
        roster = board_staff.seats_by_id(self.table, settings)
        analyst = {
            op.name
            for op, _ in board_tools.available_ops(
                settings, "ciso", context="task", seat_id="security-analyst", seats_by_id=roster
            )
        }
        self.assertIn("github_list_security_alerts", analyst)
        self.assertIn("github_get_security_alert", analyst)
        self.assertIn("github_get_file", analyst)
        self.assertIn("security_github_alerts", analyst)
        self.assertIn("research_search", analyst)
        self.assertIn("task_finish", analyst)
        self.assertNotIn("code_run_task", analyst)
        support = {
            op.name
            for op, _ in board_tools.available_ops(
                settings, "coo", context="task", seat_id="support", seats_by_id=roster
            )
        }
        self.assertTrue(any(name.startswith("mail_") for name in support))
        self.assertNotIn("github_list_security_alerts", support)
        chat = {
            op.name
            for op, _ in board_tools.available_ops(
                settings, "ciso", context="chat", seat_id="security-analyst", seats_by_id=roster
            )
        }
        self.assertIn("github_list_security_alerts", chat)
        self.assertNotIn("task_finish", chat)

    def test_create_task_validates_and_defaults_budget(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "architect", {"isActive": False})
        with self.assertRaises(board_staff.StaffError):
            board_staff.create_task(self.table, settings, assignee="nope", origin="owner", brief="x", deliverable_type="markdown", created_by="t")
        with self.assertRaises(board_staff.StaffError):
            board_staff.create_task(self.table, settings, assignee="architect", origin="owner", brief="x", deliverable_type="markdown", created_by="t")
        with self.assertRaises(board_staff.StaffError):
            board_staff.create_task(self.table, settings, assignee="cfo", origin="owner", brief="", deliverable_type="markdown", created_by="t")
        task = board_staff.create_task(
            self.table,
            settings,
            assignee="cfo",
            origin="owner",
            brief="List our three biggest monthly costs from AWS and finance",
            deliverable_type="markdown",
            created_by="admin",
        )
        self.assertEqual(task["status"], "running")
        self.assertEqual(task["budgetUsd"], BOARD_STAFF_TASK_BUDGET_DESK_USD)
        self.assertEqual(task["assigneeKind"], "persona")
        self.assertEqual(len(self.async_payloads), 1)
        self.assertEqual(self.async_payloads[0]["internal"], "board_staff_step")
        self.assertEqual(self.async_payloads[0]["boardKey"], BOARD_KEY)

    def test_drain_queue_respects_max_running(self) -> None:
        settings = _enable_staff(self.table, maxRunningTasks=1)
        first = board_staff.create_task(self.table, settings, assignee="cfo", origin="owner", brief="One", deliverable_type="markdown", created_by="a")
        second = board_staff.create_task(self.table, settings, assignee="cfo", origin="owner", brief="Two", deliverable_type="markdown", created_by="a")
        self.assertEqual(board_store.get_task(self.table, first["taskId"])["status"], "running")
        self.assertEqual(board_store.get_task(self.table, second["taskId"])["status"], "queued")
        self.assertEqual(len(self.async_payloads), 1)

    def test_prompts_include_task_frame(self) -> None:
        frame = board_personas.render_task_frame(
            {"brief": "Do the work", "deliverableType": "markdown", "budgetUsd": 1, "usage": {"cost": 0.2}, "step": 1},
            "earlier note",
        )
        self.assertIn("Either call task_note", frame)
        self.assertIn("tool calls", frame)
        self.assertIn("Do the work", frame)
        self.assertIn("do not invent tool names", frame)
        self.assertIn("[Insert", frame)
        seat = {"id": "support", "title": "Parent Support", "displayName": "Sam", "reportsTo": "coo", "brief": "Help parents."}
        prompt = board_personas.render_seat_prompt(seat, {"displayName": "Pat", "title": "COO"}, {}, ["Be brief."])
        self.assertIn("reporting to Pat", prompt)
        self.assertIn("STANDING INSTRUCTIONS", prompt)
        self.assertIn("never invent tool names", prompt)
        self.assertIn(board_personas.BOOKS_OF_RECORD, prompt)

    def test_accountant_prompt_points_at_product_database_not_xero(self) -> None:
        seat = board_staff.seat_default("accountant") or {}
        cfo = board_personas.persona_default("cfo") or {}
        prompt = board_personas.render_seat_prompt(seat, cfo, {}, [])
        self.assertIn("finance_aging_report", prompt)
        self.assertIn("finance_cash_snapshot", prompt)
        self.assertIn("Siu Tin Dei product database", prompt)
        self.assertIn("no QuickBooks", prompt)
        duties = {str(d["id"]): d for d in (seat.get("duties") or [])}
        self.assertIn("finance_aging_report", duties["weekly-aging"]["brief"])
        self.assertIn("finance_cash_snapshot", duties["month-end-memo"]["brief"])
        self.assertIn("finance_aging_report", duties["month-end-memo"]["brief"])
        self.assertIn("meta_ad_spend", duties["month-end-memo"]["brief"])
        self.assertEqual((seat.get("tools") or {}).get("meta"), "read")
        review = board_staff._review_user_prompt(  # noqa: SLF001
            {
                "assignee": "accountant",
                "brief": duties["weekly-aging"]["brief"],
                "deliverableType": "markdown",
                "confidence": "low",
            },
            "Need QuickBooks.",
            [],
        )
        self.assertIn("finance_aging_report", review)
        self.assertIn("Do not return asking for accounting software", review)
        self.assertIn("finance_cash_snapshot", review)
        self.assertIn("[Insert", review)
        self.assertIn("book of record", board_tools.REGISTRY["finance_aging_report"].description)
        self.assertIn("no QuickBooks/Xero", board_tools.REGISTRY["finance_list_invoices"].description)
        self.assertIn("LX Software statement book", duties["month-end-memo"]["brief"])
        self.assertIn("Siu Tin Dei", duties["month-end-memo"]["brief"])

    def test_community_manager_can_verify_ga4_visitor_sources(self) -> None:
        seat = board_staff.seat_default("community-manager") or {}
        cmo = board_personas.persona_default("cmo") or {}
        prompt = board_personas.render_seat_prompt(seat, cmo, {}, [])
        self.assertIn("web_sessions", prompt)
        self.assertIn("web_conversions", prompt)
        self.assertIn("Never ask for GA4 console", prompt)
        self.assertEqual((seat.get("tools") or {}).get("web"), "read")
        brief = (
            "Verify analytics and tracking setup for visitor source measurement. "
            "Done looks like: GA4 fully integrated with channel attribution and "
            "event tracking to measure organic traffic. Success metric: Analytics "
            "data shows visitor sources post-launch."
        )
        needed = board_staff._brief_required_evidence_tools(brief)  # noqa: SLF001
        self.assertEqual(needed, ["web_sessions", "web_conversions"])
        self.assertEqual(
            board_staff._brief_required_evidence_tools("Reply to the WhatsApp thread."),  # noqa: SLF001
            [],
        )
        review = board_staff._review_user_prompt(  # noqa: SLF001
            {
                "assignee": "community-manager",
                "brief": brief,
                "deliverableType": "markdown",
                "confidence": "low",
            },
            "Unable to verify GA4; no access to analytics tools.",
            [],
        )
        self.assertIn("web_sessions", review)
        self.assertIn("Do not return asking for GA4", review)
        self.assertIn("book of record for visitor sources", board_tools.REGISTRY["web_sessions"].description)
        settings = _enable_staff(self.table)
        roster = board_staff.seats_by_id(self.table, settings)
        self.assertEqual(board_staff.seat_level(settings, roster, "community-manager", "web"), "read")
        ops = {
            op.name
            for op, _ in board_tools.available_ops(
                settings, "cmo", context="task", seat_id="community-manager", seats_by_id=roster
            )
        }
        self.assertTrue(set(needed) <= ops, ops)
        self.assertIn("web_gtm_status", ops)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(
                self.table,
                settings,
                assignee="community-manager",
                origin="owner",
                brief=brief,
                deliverable_type="markdown",
                created_by="a",
            )
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=settings,
            persona_id="cmo",
            kind="task",
            task_id=task["taskId"],
            seat_id="community-manager",
        )
        with self.assertRaises(board_staff.StaffError) as raised:
            board_staff.op_task_finish(
                ctx,
                {
                    "summary": "Could not verify.",
                    "deliverableType": "markdown",
                    "deliverable": "Unable to verify GA4 integration due to lack of access.",
                    "evidence": [],
                    "openQuestions": ["Need GA4 console access"],
                    "confidence": "low",
                },
            )
        self.assertIn("web_sessions", str(raised.exception))
        self.assertEqual(board_store.get_task(self.table, task["taskId"])["status"], "running")

    def test_weekly_kpi_pack_is_siu_tin_dei_only(self) -> None:
        seat = board_staff.seat_default("business-analyst") or {}
        duties = {str(d["id"]): d for d in (seat.get("duties") or [])}
        brief = duties["weekly-kpi-pack"]["brief"]
        self.assertIn("Siu Tin Dei", brief)
        self.assertIn("aws_monthly_cost", brief)
        self.assertIn("meta_ad_spend", brief)
        self.assertIn("do not include LX Software", brief)
        self.assertIn("accounts-sheet cash", brief)
        self.assertIn("LX Software", board_tools.REGISTRY["finance_cash_snapshot"].description)
        self.assertIn("Siu Tin Dei", board_tools.REGISTRY["finance_cash_snapshot"].description)
        review = board_staff._review_user_prompt(  # noqa: SLF001
            {
                "assignee": "business-analyst",
                "brief": brief,
                "deliverableType": "markdown",
                "confidence": "medium",
            },
            "LX Software: HKD -2235.00",
            [],
        )
        self.assertIn("LX Software statement book", review)
        self.assertIn("Siu Tin Dei", review)
        # Naming spend tools in the brief makes task_finish demand evidence from
        # them, so the seat must be able to call both in task context.
        needed = board_staff._brief_required_evidence_tools(brief)  # noqa: SLF001
        self.assertEqual(needed, ["aws_monthly_cost", "meta_ad_spend"])
        settings = _enable_staff(self.table)
        roster = board_staff.seats_by_id(self.table, settings)
        ops = {
            op.name
            for op, _ in board_tools.available_ops(
                settings, "ceo", context="task", seat_id="business-analyst", seats_by_id=roster
            )
        }
        self.assertTrue(set(needed) <= ops, ops)

    def test_blob_keys_use_board_key(self) -> None:
        self.assertEqual(
            board_staff._scratchpad_key("t1"),  # noqa: SLF001
            f"board/{BOARD_KEY}/staff/t1/scratchpad.md",
        )
        self.assertEqual(
            board_staff._deliverable_key("t1", "markdown"),  # noqa: SLF001
            f"board/{BOARD_KEY}/staff/t1/deliverable.md",
        )


class StaffStepTests(ToolsTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))

    def _queued_task(self, **kwargs: Any) -> dict[str, Any]:
        settings = _enable_staff(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            return board_staff.create_task(
                self.table,
                settings,
                assignee="cfo",
                origin="owner",
                brief="List our three biggest monthly costs from AWS and finance",
                deliverable_type="markdown",
                created_by="admin",
                **kwargs,
            )

    def test_run_step_idempotent_duplicate_payload(self) -> None:
        task = self._queued_task()
        board_store.claim_task_step(self.table, task["taskId"], 0)
        board_staff.run_step({"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": task["taskId"], "step": 2})
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["step"], 0)

    def test_task_finish_evidence_rule_and_review_accept(self) -> None:
        task = self._queued_task()
        board_store.claim_task_step(self.table, task["taskId"], 0)
        board_store.add_tool_call(
            self.table,
            {"callId": "aws-1", "op": "aws_monthly_cost", "context": {"taskId": task["taskId"]}, "taskId": task["taskId"]},
        )
        board_store.add_tool_call(
            self.table,
            {"callId": "fin-1", "op": "finance_aging_report", "context": {"taskId": task["taskId"]}, "taskId": task["taskId"]},
        )
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=board_store.load_settings(self.table),
            persona_id="cfo",
            display_name="CFO",
            kind="task",
            task_id=task["taskId"],
            actor="persona",
        )
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff.op_task_finish(
                ctx,
                {
                    "summary": "Top costs listed.",
                    "deliverableType": "markdown",
                    "deliverable": "# Costs\n\n- Lambda\n- OpenRouter",
                    "evidence": ["aws-1", "fin-1", "missing"],
                    "openQuestions": [],
                    "confidence": "high",
                },
            )
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["status"], "review")
        self.assertEqual(latest["evidence"], ["aws-1", "fin-1"])
        self.use_script([], '{"verdict":"accept","notes":"Good."}')
        board_staff.run_review({"internal": "board_staff_review", "boardKey": BOARD_KEY, "taskId": task["taskId"]})
        done = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(done["status"], "delivered")
        reviews = board_store.list_task_reviews(self.table, task["taskId"])
        self.assertEqual(reviews[0]["verdict"], "accept")

    def test_review_unparsable_verdict_returns(self) -> None:
        task = self._queued_task()
        board_store.claim_task_step(self.table, task["taskId"], 0)
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=board_store.load_settings(self.table),
            persona_id="cfo",
            display_name="CFO",
            kind="task",
            task_id=task["taskId"],
            actor="persona",
        )
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff.op_task_finish(
                ctx,
                {
                    "summary": "Draft",
                    "deliverableType": "markdown",
                    "deliverable": "# Draft",
                    "evidence": [],
                    "openQuestions": [],
                    "confidence": "low",
                },
            )
        self.use_script([], "not json at all")
        board_staff.run_review({"internal": "board_staff_review", "boardKey": BOARD_KEY, "taskId": task["taskId"]})
        done = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(done["lastReview"]["verdict"], "return")

    def test_review_empty_completion_returns(self) -> None:
        task = self._queued_task()
        board_store.claim_task_step(self.table, task["taskId"], 0)
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=board_store.load_settings(self.table),
            persona_id="cfo",
            display_name="CFO",
            kind="task",
            task_id=task["taskId"],
            actor="persona",
        )
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff.op_task_finish(
                ctx,
                {
                    "summary": "Draft",
                    "deliverableType": "markdown",
                    "deliverable": "# Draft",
                    "evidence": [],
                    "openQuestions": [],
                    "confidence": "low",
                },
            )
        self.use_script([], "")
        board_staff.run_review({"internal": "board_staff_review", "boardKey": BOARD_KEY, "taskId": task["taskId"]})
        done = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(done["lastReview"]["verdict"], "return")

    def test_task_finish_high_confidence_without_evidence_is_flagged(self) -> None:
        task = self._queued_task()
        board_store.claim_task_step(self.table, task["taskId"], 0)
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=board_store.load_settings(self.table),
            persona_id="cfo",
            kind="task",
            task_id=task["taskId"],
        )
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff.op_task_finish(
                ctx,
                {
                    "summary": "Guessing.",
                    "deliverableType": "markdown",
                    "deliverable": "none",
                    "evidence": [],
                    "openQuestions": [],
                    "confidence": "high",
                },
            )
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["confidence"], "medium")
        self.assertIn("no_evidence", latest["flags"])

    def test_task_finish_rejects_placeholder_memo(self) -> None:
        task = self._queued_task()
        board_store.claim_task_step(self.table, task["taskId"], 0)
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=board_store.load_settings(self.table),
            persona_id="cfo",
            kind="task",
            task_id=task["taskId"],
        )
        with self.assertRaises(board_staff.StaffError) as raised:
            board_staff.op_task_finish(
                ctx,
                {
                    "summary": "Month-end close",
                    "deliverableType": "markdown",
                    "deliverable": (
                        "# Month-End Close Memo\n"
                        "- Current Balance: [Insert verified cash balance]\n"
                        "- 0-30 Days: [Insert amount]"
                    ),
                    "evidence": [],
                    "openQuestions": [],
                    "confidence": "low",
                },
            )
        self.assertIn("placeholder", str(raised.exception).lower())
        self.assertEqual(board_store.get_task(self.table, task["taskId"])["status"], "running")

    def test_task_finish_requires_evidence_when_brief_names_tools(self) -> None:
        settings = _enable_staff(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(
                self.table,
                settings,
                assignee="cfo",
                origin="duty",
                brief=(
                    "Call finance_cash_snapshot, finance_aging_report, aws_monthly_cost "
                    "and meta_ad_spend. Write the month-end close memo."
                ),
                deliverable_type="markdown",
                created_by="board_duties",
            )
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=settings,
            persona_id="cfo",
            kind="task",
            task_id=task["taskId"],
        )
        with self.assertRaises(board_staff.StaffError) as raised:
            board_staff.op_task_finish(
                ctx,
                {
                    "summary": "Close",
                    "deliverableType": "markdown",
                    "deliverable": "Cash HKD 1.00. Aging current 0.",
                    "evidence": [],
                    "openQuestions": [],
                    "confidence": "low",
                },
            )
        self.assertIn("finance_cash_snapshot", str(raised.exception))
        self.assertEqual(board_store.get_task(self.table, task["taskId"])["status"], "running")

    def test_accountant_can_read_cash_and_meta(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "accountant", {"isActive": True})
        roster = board_staff.seats_by_id(self.table, settings)
        self.assertEqual(board_staff.seat_level(settings, roster, "accountant", "meta"), "read")
        ops = {
            op.name
            for op, _ in board_tools.available_ops(
                settings, "cfo", context="task", seat_id="accountant", seats_by_id=roster
            )
        }
        self.assertIn("finance_cash_snapshot", ops)
        self.assertIn("meta_ad_spend", ops)
        self.assertIn("aws_monthly_cost", ops)
        self.assertIn("finance_aging_report", ops)

    def test_review_return_then_max_revisions_needs_owner(self) -> None:
        task = self._queued_task()
        board_store.claim_task_step(self.table, task["taskId"], 0)
        task = board_store.get_task(self.table, task["taskId"])
        task["status"] = "review"
        task["deliverableKey"] = "x"
        board_store.put_task(self.table, task)
        settings = board_store.load_settings(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            first = board_staff.apply_review(self.table, settings, task, verdict="return", notes="More evidence", by="manager")
            self.assertEqual(first["status"], "running")
            self.assertEqual(first["revisions"], 1)
            first["status"] = "review"
            board_store.put_task(self.table, first)
            second = board_staff.apply_review(self.table, settings, first, verdict="return", notes="Still thin", by="manager")
            self.assertEqual(second["revisions"], 2)
            second["status"] = "review"
            board_store.put_task(self.table, second)
            third = board_staff.apply_review(self.table, settings, second, verdict="return", notes="Stop", by="manager")
            self.assertEqual(third["status"], "needs_owner")
            self.assertEqual(third["lastReview"]["verdict"], "return")

    def test_review_accept_closes_action(self) -> None:
        action_id = board_store.new_id()
        board_store.put_action(
            self.table,
            {
                "actionId": action_id,
                "title": "Cost review",
                "status": "open",
                "note": "",
                "createdAt": board_store.now_iso(),
                "updatedAt": board_store.now_iso(),
            },
        )
        task = self._queued_task()
        board_store.claim_task_step(self.table, task["taskId"], 0)
        task = board_store.get_task(self.table, task["taskId"])
        task.update({"status": "review", "actionId": action_id, "deliverableType": "markdown", "summary": "Done"})
        board_store.put_task(self.table, task)
        settings = board_store.load_settings(self.table)
        board_staff.apply_review(self.table, settings, task, verdict="accept", notes="ok", by="manager")
        action = board_store.get_action(self.table, action_id)
        self.assertEqual(action["status"], "done")
        self.assertIn(f"staff:{task['taskId']}", action["closedBy"])

    def test_step_limit_finishes_incomplete(self) -> None:
        task = self._queued_task()
        board_store.claim_task_step(self.table, task["taskId"], 0)
        task = board_store.get_task(self.table, task["taskId"])
        task["step"] = BOARD_STAFF_MAX_STEPS_PER_TASK - 1
        task["status"] = "running"
        board_store.put_task(self.table, task)
        scripted = ScriptedOpenRouter([], "Still working.")
        self.router.openrouter = scripted
        board_staff.run_step({"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": task["taskId"], "step": BOARD_STAFF_MAX_STEPS_PER_TASK})
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["status"], "failed")
        self.assertEqual(latest["failureReason"], "step limit")

    def test_security_analyst_step_offers_github_and_research_tools(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "security-analyst", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(
                self.table,
                settings,
                assignee="security-analyst",
                origin="event",
                brief="New security alert gh:dependabot:153: js-yaml: maxTotalMergeKeys does not limit CPU use",
                deliverable_type="markdown",
                created_by="board_duties",
            )
        scripted = self.use_script([], "Checking the advisory.")
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff.run_step(
                {"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": task["taskId"], "step": 1}
            )
        self.assertTrue(scripted.requests)
        offered = {tool["function"]["name"] for tool in scripted.requests[0].get("tools") or []}
        self.assertIn("github_get_security_alert", offered)
        self.assertIn("github_list_security_alerts", offered)
        self.assertIn("github_get_file", offered)
        self.assertIn("security_github_alerts", offered)
        self.assertIn("research_search", offered)
        self.assertIn("task_finish", offered)
        preamble = " ".join(
            str(msg.get("content") or "")
            for msg in scripted.requests[0].get("messages") or []
            if msg.get("role") == "system"
        )
        self.assertIn("read_github", preamble)
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["step"], 1)
        self.assertNotEqual(latest.get("failureReason"), "step limit")

    def test_stuck_sweep(self) -> None:
        settings = _enable_staff(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(self.table, settings, assignee="cfo", origin="owner", brief="Stuck", deliverable_type="markdown", created_by="a")
        board_store.claim_task_step(self.table, task["taskId"], 0)
        stale = board_store.get_task(self.table, task["taskId"])
        stale_at = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        stale["updatedAt"] = stale_at
        stale.pop("stepClaimedAt", None)
        board_store.put_task(self.table, stale)
        payloads: list[dict[str, Any]] = []
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: payloads.append(payload)):
            board_staff.handle_tick({"internal": "board_staff_tick", "boardKey": BOARD_KEY})
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["status"], "running")
        self.assertTrue(latest.get("stuckRetried"))
        self.assertTrue(any(p.get("internal") == "board_staff_step" for p in payloads))
        latest["updatedAt"] = stale_at
        latest.pop("stepClaimedAt", None)
        board_store.put_task(self.table, latest)
        board_staff.handle_tick({"internal": "board_staff_tick", "boardKey": BOARD_KEY})
        failed = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failureReason"], "stuck")

    def test_drain_requeues_when_invoke_raises(self) -> None:
        settings = _enable_staff(self.table)
        calls: list[dict[str, Any]] = []

        def boom(payload: dict[str, Any], fallback: Any = None) -> None:
            calls.append(payload)
            raise RuntimeError("Lambda.Invoke failed")

        with patch.object(board_async, "invoke_async", boom):
            task = board_staff.create_task(
                self.table, settings, assignee="cfo", origin="owner", brief="Start me", deliverable_type="markdown", created_by="a"
            )
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["status"], "queued")
        self.assertIsNone(latest.get("startedAt"))
        self.assertTrue(any(p.get("internal") == "board_staff_step" for p in calls))

    def test_ceo_task_reviewed_by_cfo(self) -> None:
        task = {"assigneeKind": "persona", "assignee": "ceo", "managerId": "ceo"}
        self.assertEqual(board_staff._reviewer_id(task), "cfo")

    def test_task_finish_records_step_so_return_can_resume(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        self.use_script(
            [
                [
                    (
                        "task_finish",
                        {
                            "summary": "Draft",
                            "deliverableType": "markdown",
                            "deliverable": "# Draft",
                            "evidence": [],
                            "openQuestions": [],
                            "confidence": "low",
                        },
                    )
                ]
            ],
            "",
        )
        payloads: list[dict[str, Any]] = []
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: payloads.append(payload)):
            board_staff.run_step(
                {"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": tid, "step": 1}
            )
        latest = board_store.get_task(self.table, tid)
        self.assertEqual(latest["status"], "review")
        self.assertEqual(latest["step"], 1)
        settings = board_store.load_settings(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: payloads.append(payload)):
            board_staff.apply_review(self.table, settings, latest, verdict="return", notes="more", by="manager")
        latest = board_store.get_task(self.table, tid)
        self.assertEqual(latest["status"], "running")
        self.assertEqual(latest["stepClaimed"], 1)
        self.assertEqual(payloads[-1]["step"], 2)
        self.assertTrue(board_store.claim_task_step(self.table, tid, 1))

    def test_return_repairs_stale_step_claim(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        self.assertTrue(board_store.claim_task_step(self.table, tid, 0))
        latest = board_store.get_task(self.table, tid)
        latest.update({"status": "review", "step": 0, "stepClaimed": 1, "deliverableKey": "x"})
        board_store.put_task(self.table, latest)
        settings = board_store.load_settings(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff.apply_review(self.table, settings, latest, verdict="return", notes="more", by="manager")
        self.assertTrue(board_store.claim_task_step(self.table, tid, 0))

    def test_idle_steps_nudge_then_fail(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        self.use_script([], "Just a thought.")
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            for seq in range(1, BOARD_STAFF_MAX_IDLE_STEPS_PER_TASK + 1):
                board_staff.run_step(
                    {"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": tid, "step": seq}
                )
        latest = board_store.get_task(self.table, tid)
        self.assertEqual(latest["status"], "failed")
        self.assertEqual(latest["failureReason"], "idle step limit")
        self.assertEqual(latest["idleSteps"], BOARD_STAFF_MAX_IDLE_STEPS_PER_TASK)
        scratch = board_staff._blob_get(board_staff._scratchpad_key(tid)).decode()  # noqa: SLF001
        self.assertIn("NUDGE", scratch)

    def test_prose_cannot_call_task_finish_is_salvaged(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        report = (
            "Since I cannot call `task_note` or `task_finish`, I will document the findings here.\n\n"
            "### Security Alert Triage\n"
            "**GitHub Repository**: No open HIGH/CRITICAL security alerts found.\n"
            "**Security Hub**: No active HIGH/CRITICAL findings found.\n"
            "Proposed Remediations: None needed at this time.\n"
            "**Summary**: No open HIGH/CRITICAL security alerts found in GitHub or Security Hub.\n"
            "**Confidence**: High\n"
        )
        self.use_script([], report)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff.run_step({"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": tid, "step": 1})
        latest = board_store.get_task(self.table, tid)
        self.assertEqual(latest["status"], "review", latest.get("failureReason"))
        self.assertIn("salvaged", latest.get("flags") or [])
        body = board_staff._blob_get(str(latest.get("deliverableKey") or "")).decode()  # noqa: SLF001
        self.assertIn("Security Alert Triage", body)

    def test_last_idle_step_requires_task_finish_tool_choice(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        latest = board_store.get_task(self.table, tid)
        latest["idleSteps"] = BOARD_STAFF_MAX_IDLE_STEPS_PER_TASK - 1
        board_store.put_task(self.table, latest)
        scripted = self.use_script(
            [
                [
                    (
                        "task_finish",
                        {
                            "summary": "No high-severity alerts.",
                            "deliverableType": "markdown",
                            "deliverable": "# Triage\n\nNo HIGH/CRITICAL GitHub or Security Hub alerts.",
                            "evidence": [],
                            "openQuestions": [],
                            "confidence": "low",
                        },
                    )
                ]
            ]
        )
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff.run_step({"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": tid, "step": 1})
        self.assertEqual(
            scripted.requests[0]["tool_choice"],
            {"type": "function", "function": {"name": "task_finish"}},
        )
        names = [str(t.get("function", {}).get("name")) for t in scripted.requests[0]["tools"]]
        self.assertEqual(names[:2], ["task_note", "task_finish"])
        self.assertEqual(board_store.get_task(self.table, tid)["status"], "review")

    def test_step_exception_retries_once_then_fails(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        payloads: list[dict[str, Any]] = []

        def boom(*_a: Any, **_k: Any) -> None:
            raise RuntimeError("IncompleteRead(220 bytes read)")

        with (
            patch.object(board_tools, "run_tool_loop", boom),
            patch.object(board_async, "invoke_async", lambda payload, fallback=None: payloads.append(payload)),
        ):
            board_staff.run_step({"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": tid, "step": 1})
        latest = board_store.get_task(self.table, tid)
        self.assertEqual(latest["status"], "running")
        self.assertTrue(payloads[-1].get("retried"))
        with (
            patch.object(board_tools, "run_tool_loop", boom),
            patch.object(board_async, "invoke_async", lambda payload, fallback=None: payloads.append(payload)),
        ):
            board_staff.run_step(payloads[-1])
        latest = board_store.get_task(self.table, tid)
        self.assertEqual(latest["status"], "failed")
        self.assertIn("IncompleteRead", latest["failureReason"])

    def test_tool_loop_stops_after_task_finish(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        scripted = self.use_script(
            [
                [
                    (
                        "task_finish",
                        {
                            "summary": "Draft",
                            "deliverableType": "markdown",
                            "deliverable": "# Draft",
                            "evidence": [],
                            "openQuestions": [],
                            "confidence": "low",
                        },
                    )
                ]
            ],
            "should not be requested",
        )
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff.run_step(
                {"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": tid, "step": 1}
            )
        self.assertEqual(len(scripted.requests), 1)
        self.assertNotEqual(scripted.requests[0].get("tool_choice"), "none")
        latest = board_store.get_task(self.table, tid)
        self.assertEqual(latest["status"], "review")
        self.assertEqual(latest["step"], 1)

    def test_permanent_openrouter_4xx_does_not_retry(self) -> None:
        from openrouter_client import OpenRouterError

        task = self._queued_task()
        tid = task["taskId"]
        payloads: list[dict[str, Any]] = []

        def boom(*_a: Any, **_k: Any) -> None:
            raise OpenRouterError("OpenRouter request failed with status 400", status=400)

        with (
            patch.object(board_tools, "run_tool_loop", boom),
            patch.object(board_async, "invoke_async", lambda payload, fallback=None: payloads.append(payload)),
        ):
            board_staff.run_step({"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": tid, "step": 1})
        latest = board_store.get_task(self.table, tid)
        self.assertEqual(latest["status"], "failed")
        self.assertTrue(latest["failureReason"].startswith("step error:"))
        self.assertFalse(any(p.get("retried") for p in payloads))

    def test_openrouter_402_trips_budget_breaker(self) -> None:
        from openrouter_client import OpenRouterError

        task = self._queued_task()
        tid = task["taskId"]

        def boom(*_a: Any, **_k: Any) -> None:
            raise OpenRouterError("OpenRouter request failed with status 402", status=402)

        with (
            patch.object(board_tools, "run_tool_loop", boom),
            patch.object(board_async, "invoke_async", lambda payload, fallback=None: None),
        ):
            board_staff.run_step({"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": tid, "step": 1})
        latest = board_store.get_task(self.table, tid)
        self.assertEqual(latest["status"], "failed")
        breaker = board_store.get_breaker(self.table, "budget")
        self.assertTrue(breaker and breaker.get("tripped"))

    def test_daily_budget_requeues_instead_of_failing(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        settings = board_store.load_settings(self.table)
        settings["staff"]["dailyBudgetUsd"] = 0.01
        board_store.save_settings(self.table, settings)
        board_store.add_staff_usage_day(self.table, "cfo", {"cost": 0.02, "calls": 1})
        self.assertEqual(board_store.get_task(self.table, tid)["status"], "running")
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff.run_step({"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": tid, "step": 1})
        latest = board_store.get_task(self.table, tid)
        self.assertEqual(latest["status"], "queued")
        self.assertIn("daily budget", latest.get("parkedReason") or "")
        self.assertEqual(board_staff.drain_queue(self.table, board_store.load_settings(self.table)), 0)

    def test_stale_step_claim_reinvokes_once_then_fails(self) -> None:
        settings = _enable_staff(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(
                self.table, settings, assignee="cfo", origin="owner", brief="Hung", deliverable_type="markdown", created_by="a"
            )
        board_store.claim_task_step(self.table, task["taskId"], 0)
        stale = board_store.get_task(self.table, task["taskId"])
        stale_at = (datetime.now(timezone.utc) - timedelta(minutes=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
        stale["stepClaimedAt"] = stale_at
        stale["updatedAt"] = board_store.now_iso()
        board_store.put_task(self.table, stale)
        payloads: list[dict[str, Any]] = []
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: payloads.append(payload)):
            board_staff.handle_tick({"internal": "board_staff_tick", "boardKey": BOARD_KEY})
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["status"], "running")
        self.assertTrue(latest.get("stuckRetried"))
        self.assertTrue(any(p.get("internal") == "board_staff_step" for p in payloads))
        latest["stepClaimedAt"] = stale_at
        latest["updatedAt"] = stale_at
        board_store.put_task(self.table, latest)
        board_staff.handle_tick({"internal": "board_staff_tick", "boardKey": BOARD_KEY})
        failed = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failureReason"], "stuck")


class StaffRouteTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ.pop("ASSETS_BUCKET_NAME", None)

    def test_post_disabled_is_409(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "false"
        status, body = self.call(
            "/siu-tin-dei/board/tasks",
            "POST",
            {"assignee": "cfo", "brief": "List costs", "deliverableType": "markdown"},
        )
        self.assertEqual(status, 409)
        self.assertEqual(body["message"], "Staff is disabled")

    def test_unknown_seat_is_404_and_bad_body_is_400(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        status, body = self.call("/siu-tin-dei/board/staff/not-a-seat", "PUT", {"isActive": True})
        self.assertEqual(status, 404)
        _enable_staff(self.table)
        status, body = self.call("/siu-tin-dei/board/tasks", "POST", {"assignee": "cfo", "brief": "", "deliverableType": "markdown"})
        self.assertEqual(status, 400)
        status, body = self.call("/siu-tin-dei/board/tasks/missing")
        self.assertEqual(status, 404)

    def test_post_staff_tick_enqueues_and_never_runs_inline(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        _enable_staff(self.table)
        queued: list[dict[str, Any]] = []

        def fake_invoke(payload: dict[str, Any]) -> bool:
            queued.append(payload)
            return True

        with patch.object(board_async, "try_invoke_event", side_effect=fake_invoke), patch.object(
            board_staff, "handle_tick"
        ) as tick:
            status, body = self.call("/siu-tin-dei/board/staff/tick", "POST", {})
        self.assertEqual(status, 200)
        self.assertTrue(body.get("queued"))
        self.assertTrue(body.get("invoked"))
        tick.assert_not_called()
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["internal"], "board_staff_tick")
        self.assertEqual(queued[0]["boardKey"], board_store.BOARD_KEY)
        with patch.object(board_async, "try_invoke_event", return_value=False), patch.object(
            board_staff, "handle_tick"
        ) as inline:
            status, body = self.call("/siu-tin-dei/board/staff/tick", "POST", {})
        self.assertEqual(status, 200)
        self.assertTrue(body.get("queued"))
        self.assertFalse(body.get("invoked"))
        inline.assert_not_called()
        status, _ = self.call("/siu-tin-dei/board/staff/tick", "GET")
        self.assertEqual(status, 405)

    def test_post_staff_tick_disabled_is_409(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "false"
        status, body = self.call("/siu-tin-dei/board/staff/tick", "POST", {})
        self.assertEqual(status, 409)
        self.assertEqual(body["message"], "Staff is disabled")

    def test_get_staff_and_create_task(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            _enable_staff(self.table)
            status, body = self.call("/siu-tin-dei/board/staff")
            self.assertEqual(status, 200)
            self.assertTrue(body["enabled"])
            self.assertEqual(len(body["seats"]), 15)
            status, created = self.call(
                "/siu-tin-dei/board/tasks",
                "POST",
                {"assignee": "cfo", "brief": "List our three biggest monthly costs from AWS and finance", "deliverableType": "markdown"},
            )
            self.assertEqual(status, 201)
            self.assertEqual(created["task"]["assignee"], "cfo")
            status, listed = self.call("/siu-tin-dei/board/tasks")
            self.assertEqual(status, 200)
            self.assertGreaterEqual(len(listed["tasks"]), 1)

    def test_retry_failed_task_requeues(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            _enable_staff(self.table)
            status, created = self.call(
                "/siu-tin-dei/board/tasks",
                "POST",
                {"assignee": "cfo", "brief": "List our three biggest monthly costs from AWS and finance", "deliverableType": "markdown"},
            )
            self.assertEqual(status, 201)
            task_id = created["task"]["taskId"]
            row = board_store.get_task(self.table, task_id)
            row.update({"status": "failed", "failureReason": "stuck", "stepClaimed": 1})
            board_store.put_task(self.table, row)
            status, body = self.call(f"/siu-tin-dei/board/tasks/{task_id}/retry", "POST", {})
            self.assertEqual(status, 200)
            self.assertIn(body["task"]["status"], ("queued", "running"))
            self.assertEqual(body["task"].get("failureReason") or "", "")
            status, again = self.call(f"/siu-tin-dei/board/tasks/{task_id}/retry", "POST", {})
            self.assertEqual(status, 409)

    def test_cancel_failed_task_dismisses_it(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            _enable_staff(self.table)
            status, created = self.call(
                "/siu-tin-dei/board/tasks",
                "POST",
                {"assignee": "cfo", "brief": "List our three biggest monthly costs from AWS and finance", "deliverableType": "markdown"},
            )
            self.assertEqual(status, 201)
            task_id = created["task"]["taskId"]
            row = board_store.get_task(self.table, task_id)
            row.update({"status": "failed", "failureReason": "step limit"})
            board_store.put_task(self.table, row)
            status, body = self.call(f"/siu-tin-dei/board/tasks/{task_id}/cancel", "POST", {})
            self.assertEqual(status, 200)
            self.assertEqual(body["task"]["status"], "cancelled")
            self.assertIn("step limit", body["task"].get("failureReason") or "")
            self.assertEqual(board_store.get_task(self.table, task_id)["cancelledFrom"], "failed")
            row = board_store.get_task(self.table, task_id)
            row["status"] = "delivered"
            row.pop("failureReason", None)
            board_store.put_task(self.table, row)
            status, body = self.call(f"/siu-tin-dei/board/tasks/{task_id}/cancel", "POST", {})
            self.assertEqual(status, 409)

    def test_persona_cancel_appends_reason_and_refuses_delivered(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            settings = _enable_staff(self.table)
            status, created = self.call(
                "/siu-tin-dei/board/tasks",
                "POST",
                {"assignee": "cfo", "brief": "List our three biggest monthly costs from AWS and finance", "deliverableType": "markdown"},
            )
            self.assertEqual(status, 201)
            task_id = created["task"]["taskId"]
            row = board_store.get_task(self.table, task_id)
            row.update({"status": "failed", "failureReason": "step limit", "managerId": "cfo"})
            board_store.put_task(self.table, row)
            ctx = board_tools.ToolContext(
                table=self.table,
                settings=settings,
                persona_id="cfo",
                display_name="CFO",
                kind="chat",
                actor="persona",
                owner_sub="cfo",
            )
            out = board_staff.op_staff_cancel_task(ctx, {"taskId": task_id, "reason": "superseded"})
            self.assertEqual(out["status"], "cancelled")
            reason = out.get("failureReason") or ""
            self.assertIn("step limit", reason)
            self.assertIn("superseded", reason)
            stored = board_store.get_task(self.table, task_id)
            self.assertEqual(stored["cancelledFrom"], "failed")
            self.assertIn("step limit", stored.get("failureReason") or "")
            stored["status"] = "delivered"
            stored.pop("failureReason", None)
            board_store.put_task(self.table, stored)
            with self.assertRaises(board_staff.StaffError) as raised:
                board_staff.op_staff_cancel_task(ctx, {"taskId": task_id})
            self.assertEqual(raised.exception.code, "conflict")

    def test_retry_resets_usage_after_task_budget(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            _enable_staff(self.table)
            status, created = self.call(
                "/siu-tin-dei/board/tasks",
                "POST",
                {"assignee": "cfo", "brief": "List our three biggest monthly costs from AWS and finance", "deliverableType": "markdown"},
            )
            self.assertEqual(status, 201)
            task_id = created["task"]["taskId"]
            row = board_store.get_task(self.table, task_id)
            row.update({
                "status": "failed",
                "failureReason": "Task budget exhausted",
                "usage": {"promptTokens": 10, "completionTokens": 5, "cost": 1.0, "calls": 2},
                "budgetUsd": 1.0,
            })
            board_store.put_task(self.table, row)
            status, body = self.call(f"/siu-tin-dei/board/tasks/{task_id}/retry", "POST", {})
            self.assertEqual(status, 200)
            self.assertEqual((body["task"].get("usage") or {}).get("cost") or 0, 0)
            self.assertEqual((body["task"].get("previousUsage") or {}).get("cost"), 1.0)
            self.assertEqual(body["task"].get("attempt"), 2)

    def test_retry_refuses_inactive_seat_and_closed_action(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            _enable_staff(self.table)
            board_store.save_staff_override(self.table, "support", {"isActive": True})
            status, created = self.call(
                "/siu-tin-dei/board/tasks",
                "POST",
                {"assignee": "support", "brief": "Reply to the parent who asked about lunch", "deliverableType": "markdown"},
            )
            self.assertEqual(status, 201)
            task_id = created["task"]["taskId"]
            row = board_store.get_task(self.table, task_id)
            row.update({"status": "failed", "failureReason": "stuck"})
            board_store.put_task(self.table, row)
            board_store.save_staff_override(self.table, "support", {"isActive": False})
            status, body = self.call(f"/siu-tin-dei/board/tasks/{task_id}/retry", "POST", {})
            self.assertEqual(status, 409)
            self.assertIn("not active", body["message"])
            board_store.save_staff_override(self.table, "support", {"isActive": True})
            action_id = board_store.new_id()
            board_store.put_action(
                self.table,
                {
                    "actionId": action_id,
                    "title": "Closed",
                    "status": "done",
                    "createdAt": board_store.now_iso(),
                    "updatedAt": board_store.now_iso(),
                },
            )
            row = board_store.get_task(self.table, task_id)
            row["actionId"] = action_id
            board_store.put_task(self.table, row)
            status, body = self.call(f"/siu-tin-dei/board/tasks/{task_id}/retry", "POST", {})
            self.assertEqual(status, 409)
            self.assertIn("closed", body["message"])

    def test_list_keeps_failed_when_many_delivered(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        settings = _enable_staff(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            failed_ids = []
            for i in range(3):
                task = board_staff.create_task(
                    self.table,
                    settings,
                    assignee="cfo",
                    origin="owner",
                    brief=f"Failed item number {i} needs a long enough brief",
                    deliverable_type="markdown",
                    created_by="t",
                )
                row = board_store.get_task(self.table, task["taskId"])
                row.update({"status": "failed", "failureReason": "stuck", "finishedAt": board_store.now_iso()})
                board_store.put_task(self.table, row)
                failed_ids.append(task["taskId"])
            for i in range(40):
                task = board_staff.create_task(
                    self.table,
                    settings,
                    assignee="cfo",
                    origin="owner",
                    brief=f"Delivered item number {i} needs a long enough brief",
                    deliverable_type="markdown",
                    created_by="t",
                )
                row = board_store.get_task(self.table, task["taskId"])
                row.update({"status": "delivered", "finishedAt": board_store.now_iso()})
                board_store.put_task(self.table, row)
        listed = board_staff.list_tasks_for_api(self.table, limit=20)
        listed_ids = {t["taskId"] for t in listed}
        for tid in failed_ids:
            self.assertIn(tid, listed_ids)


class StaffKillSwitchTests(BoardTestCase):
    def test_env_enabled_false_when_unset(self) -> None:
        os.environ.pop("BOARD_STAFF_ENABLED", None)
        self.assertFalse(board_staff.env_enabled())


class StaffAccountingTests(StaffStepTests):
    def test_run_step_noops_when_env_disabled(self) -> None:
        task = self._queued_task()
        board_store.claim_task_step(self.table, task["taskId"], 0)
        os.environ["BOARD_STAFF_ENABLED"] = "false"
        board_staff.run_step(
            {"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": task["taskId"], "step": 1}
        )
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["step"], 0)

    def test_task_usage_accumulates_and_budget_stops_third_step(self) -> None:
        task = self._queued_task(budget_usd=0.015)

        class FakeResult:
            text = "working"
            calls: list[Any] = []
            usage = {"cost": 0.01, "promptTokens": 10, "completionTokens": 5, "totalTokens": 15}

        with patch.object(board_async, "invoke_async", side_effect=lambda payload, *, fallback=None: None):
            with patch.object(board_tools, "run_tool_loop", return_value=FakeResult()):
                board_staff.run_step(
                    {"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": task["taskId"], "step": 1}
                )
                board_staff.run_step(
                    {"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": task["taskId"], "step": 2}
                )
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertAlmostEqual(float((latest.get("usage") or {}).get("cost") or 0), 0.02)
        with patch.object(board_tools, "run_tool_loop", return_value=FakeResult()):
            board_staff.run_step(
                {"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": task["taskId"], "step": 3}
            )
        failed = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failureReason"], "Task budget exhausted")

    def test_claim_task_step_mutual_exclusion(self) -> None:
        task = self._queued_task()
        self.assertTrue(board_store.claim_task_step(self.table, task["taskId"], 0))
        self.assertFalse(board_store.claim_task_step(self.table, task["taskId"], 0))

    def test_staff_usage_day_adds_atomically(self) -> None:
        board_store.add_staff_usage_day(self.table, "cfo", {"cost": 0.01, "calls": 1})
        board_store.add_staff_usage_day(self.table, "cfo", {"cost": 0.02, "calls": 1})
        day = board_store.load_staff_usage_day(self.table)
        self.assertAlmostEqual(day["cost"], 0.03)
        self.assertEqual(day["calls"], 2)

    def test_fake_table_rejects_python_float_like_dynamodb(self) -> None:
        with self.assertRaises(TypeError) as ctx:
            self.table.update_item(
                Key={"pk": "BOARD#siuTinDei#staffusage#test", "sk": "STATE"},
                UpdateExpression="ADD cost :c",
                ExpressionAttributeValues={":c": 0.01},
            )
        self.assertIn("Decimal", str(ctx.exception))

    def test_settings_conflict_then_retry(self) -> None:
        first = board_store.load_settings(self.table)
        board_store.save_settings(self.table, first)
        with self.assertRaises(board_store.SettingsConflict):
            board_store.save_settings(self.table, first)

        def apply(settings: dict[str, Any]) -> dict[str, Any]:
            staff = dict(settings.get("staff") or {})
            staff["enabled"] = True
            settings["staff"] = board_store.normalize_staff_config(staff)
            return settings

        saved = board_store.save_settings_retry(self.table, apply)
        self.assertTrue(saved["staff"]["enabled"])


class StaffToolAvailabilityTests(unittest.TestCase):
    def test_task_ops_only_in_task_context(self) -> None:
        settings = board_store.default_settings()
        settings["tools"]["enabled"] = True
        settings["staff"]["enabled"] = True
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        chat = {op.name for op, _ in board_tools.available_ops(settings, "cfo", context="chat")}
        task = {op.name for op, _ in board_tools.available_ops(settings, "cfo", context="task")}
        self.assertNotIn("task_finish", chat)
        self.assertIn("task_finish", task)
        self.assertIn("staff_assign", chat)
        self.assertIn("staff_assign", task)
        self.assertIn("finance_aging_report", task)
        self.assertIn("finance_cash_snapshot", task)
        self.assertIn("aws_monthly_cost", task)
        self.assertIn("meta_ad_spend", task)
        self.assertEqual([op.name for op, _ in board_tools.available_ops(settings, "cfo", context="task")[:2]], ["task_note", "task_finish"])
        preamble = board_tools.tools_preamble(board_tools.available_ops(settings, "cfo", context="task"))
        self.assertIn("TASK CONTROL", preamble)
        self.assertNotIn("Write operations on task", preamble)
        settings["staff"]["enabled"] = False
        off = {op.name for op, _ in board_tools.available_ops(settings, "cfo", context="chat")}
        self.assertNotIn("staff_assign", off)

    def test_task_ops_offered_when_tools_kill_switch_is_off(self) -> None:
        settings = board_store.default_settings()
        settings["tools"]["enabled"] = False
        chat = board_tools.available_ops(settings, "cfo", context="chat")
        self.assertEqual(chat, [])
        names = [op.name for op, _ in board_tools.available_ops(settings, "cfo", context="task")]
        self.assertEqual(names, ["task_note", "task_finish"])

    def test_security_analyst_task_context_includes_github_and_finish(self) -> None:
        settings = board_store.default_settings()
        settings["tools"]["enabled"] = True
        settings["staff"]["enabled"] = True
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        seat = board_staff.seat_default("security-analyst") or {}
        roster = {
            "security-analyst": {
                **seat,
                "isActive": True,
                "tools": dict(seat.get("tools") or {}),
            }
        }
        names = {
            op.name
            for op, _ in board_tools.available_ops(
                settings,
                "ciso",
                context="task",
                seat_id="security-analyst",
                seats_by_id=roster,
            )
        }
        self.assertIn("task_finish", names)
        self.assertIn("task_note", names)
        self.assertIn("github_list_security_alerts", names)
        self.assertIn("security_aws_findings", names)


class StaffExecuteCallTests(StaffStepTests):
    def test_execute_call_task_finish_allowed_for_seat_without_task_tool(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "business-analyst", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(
                self.table,
                settings,
                assignee="business-analyst",
                origin="duty",
                brief="Write the three-sentence headline",
                deliverable_type="markdown",
                created_by="board_review",
            )
        roster = board_staff.seats_by_id(self.table, settings)
        self.assertEqual(board_staff.seat_level(settings, roster, "business-analyst", "task"), "off")
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=board_store.load_settings(self.table),
            persona_id="ceo",
            display_name="Business analyst",
            kind="task",
            task_id=task["taskId"],
            seat_id="business-analyst",
            actor="persona",
        )
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            out = board_tools.execute_call(
                ctx,
                board_tools.REGISTRY["task_finish"],
                {
                    "summary": "Quiet day with no tasks delivered.",
                    "deliverableType": "markdown",
                    "deliverable": "Quiet day. No tasks delivered, running, or blocked.",
                    "evidence": [],
                    "openQuestions": [],
                    "confidence": "low",
                    "reason": "Duty headline.",
                },
            )
        self.assertEqual(out.status, "ok", out.result)
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["status"], "review")

    def test_execute_call_task_finish_refused_outside_task_context(self) -> None:
        settings = _enable_staff(self.table)
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=settings,
            persona_id="ceo",
            kind="chat",
            actor="persona",
        )
        out = board_tools.execute_call(
            ctx,
            board_tools.REGISTRY["task_finish"],
            {
                "summary": "Nope",
                "deliverableType": "markdown",
                "deliverable": "no",
                "confidence": "low",
            },
        )
        self.assertEqual(out.status, "error")
        self.assertIn("not available", str(out.result.get("error") or "").lower())


class StaffActionHandoffTests(BoardTestCase):
    """Founder actions handed to staff: from the minutes (via Approvals) and from the owner."""

    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.async_payloads: list[dict[str, Any]] = []

        # Meetings run their phases inline (as in test_board); staff steps stay captured.
        def capture_or_run(payload: dict[str, Any], *, fallback: Any = None) -> None:
            if str(payload.get("internal") or "").startswith("board_meeting") and fallback is not None:
                fallback(payload)
                return
            self.async_payloads.append(payload)

        patcher = patch.object(board_async, "invoke_async", side_effect=capture_or_run)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _open_action(self, **extra: Any) -> dict[str, Any]:
        action = {
            "actionId": board_store.new_id(),
            "title": "Call 10 activity providers",
            "detail": "Book calls with providers in Sha Tin.",
            "persona": "coo",
            "assignee": "",
            "priority": "now",
            "effort": "M",
            "metric": "10 calls booked",
            "dependsOn": [],
            "status": "open",
            "note": "",
            "meetingId": "m-1",
            "reaffirmedByMeetingIds": [],
            "dueAt": None,
            "createdAt": board_store.now_iso(),
            "updatedAt": board_store.now_iso(),
            **extra,
        }
        board_store.put_action(self.table, action)
        return action

    def test_owner_hands_action_to_seat_and_accept_closes_it(self) -> None:
        _enable_staff(self.table)
        board_store.save_staff_override(self.table, "prospector", {"isActive": True})
        action = self._open_action()
        status, body = self.call(
            "/siu-tin-dei/board/tasks",
            "POST",
            {"assignee": "prospector", "brief": "Call 10 providers", "deliverableType": "markdown", "actionId": action["actionId"]},
        )
        self.assertEqual(status, 201, body)
        task = body["task"]
        self.assertEqual(task["actionId"], action["actionId"])
        self.assertEqual(task["meetingId"], "m-1")
        linked = board_store.get_action(self.table, action["actionId"])
        self.assertEqual(linked["assignee"], "prospector")
        self.assertEqual(linked["staffTaskId"], task["taskId"])
        self.assertEqual(linked["status"], "open")
        # A second hand-off while the first task is open is refused.
        status, body = self.call(
            "/siu-tin-dei/board/tasks",
            "POST",
            {"assignee": "prospector", "brief": "Again", "deliverableType": "markdown", "actionId": action["actionId"]},
        )
        self.assertEqual(status, 409, body)
        # Deliver and accept: the founder action closes with the task reference.
        stored = board_store.get_task(self.table, task["taskId"])
        stored["status"] = "review"
        board_store.put_task(self.table, stored)
        status, body = self.call(f"/siu-tin-dei/board/tasks/{task['taskId']}/review", "POST", {"verdict": "accept", "notes": "Good"})
        self.assertEqual(status, 200, body)
        closed = board_store.get_action(self.table, action["actionId"])
        self.assertEqual(closed["status"], "done")
        self.assertEqual(closed["closedBy"], f"staff:{task['taskId']}")
        self.assertIn(task["taskId"], closed["note"])

    def test_owner_hand_off_validates_action(self) -> None:
        _enable_staff(self.table)
        status, body = self.call(
            "/siu-tin-dei/board/tasks",
            "POST",
            {"assignee": "cfo", "brief": "x", "deliverableType": "markdown", "actionId": "does-not-exist"},
        )
        self.assertEqual(status, 400, body)
        done = self._open_action(status="done")
        status, body = self.call(
            "/siu-tin-dei/board/tasks",
            "POST",
            {"assignee": "cfo", "brief": "x", "deliverableType": "markdown", "actionId": done["actionId"]},
        )
        self.assertEqual(status, 409, body)

    def test_minutes_assignee_becomes_approval_then_task(self) -> None:
        _enable_staff(self.table)
        board_store.save_staff_override(self.table, "prospector", {"isActive": True})
        status, body = self.call("/siu-tin-dei/board/meetings", "POST", {"mode": "standup"})
        self.assertEqual(status, 202, body)
        _, meeting = self.call(f"/siu-tin-dei/board/meetings/{body['meetingId']}")
        self.assertEqual(meeting["meeting"]["status"], "succeeded")
        minutes_request = next(r for r in self.openrouter.requests if "Write the minutes" in r["messages"][-1]["content"])
        prompt = minutes_request["messages"][-1]["content"]
        self.assertIn("Active staff seats", prompt)
        self.assertIn("- prospector —", prompt)
        _, actions = self.call("/siu-tin-dei/board/actions", query="status=open")
        by_title = {a["title"]: a for a in actions["actions"]}
        self.assertEqual(by_title["Pick the beta launch date"]["assignee"], "")
        self.assertEqual(by_title["Call 10 activity providers"]["assignee"], "prospector")
        action = by_title["Call 10 activity providers"]
        # The chair's staff tool defaults to propose: the hand-off waits for the owner.
        self.assertEqual(board_store.list_tasks(self.table, None), [])
        status, approvals = self.call("/siu-tin-dei/board/approvals", query="status=pending")
        self.assertEqual(status, 200)
        self.assertEqual(len(approvals["approvals"]), 1)
        approval = approvals["approvals"][0]
        self.assertEqual(approval["op"], "staff_assign")
        self.assertEqual(approval["personaId"], "ceo")
        self.assertEqual(approval["arguments"]["assignee"], "prospector")
        self.assertEqual(approval["arguments"]["actionId"], action["actionId"])
        self.assertIn("Done looks like: Book calls.", approval["arguments"]["brief"])
        self.assertIn("Success metric: 10 calls", approval["arguments"]["brief"])
        status, body = self.call(f"/siu-tin-dei/board/approvals/{approval['approvalId']}/approve", "POST", {})
        self.assertEqual(status, 200, body)
        tasks = board_store.list_tasks(self.table, None)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["assignee"], "prospector")
        self.assertEqual(tasks[0]["actionId"], action["actionId"])
        linked = board_store.get_action(self.table, action["actionId"])
        self.assertEqual(linked["staffTaskId"], tasks[0]["taskId"])

    def test_minutes_assignee_starts_task_when_chair_may_act(self) -> None:
        settings = _enable_staff(self.table)
        settings["tools"]["globalMode"] = "act"
        settings["tools"]["matrix"]["staff"]["ceo"] = "act"
        board_store.save_settings(self.table, settings)
        board_store.save_staff_override(self.table, "prospector", {"isActive": True})
        status, body = self.call("/siu-tin-dei/board/meetings", "POST", {"mode": "standup"})
        self.assertEqual(status, 202, body)
        tasks = board_store.list_tasks(self.table, None)
        self.assertEqual([t["assignee"] for t in tasks], ["prospector"])
        self.assertEqual(tasks[0]["origin"], "minutes")
        status, approvals = self.call("/siu-tin-dei/board/approvals", query="status=pending")
        self.assertEqual(approvals["approvals"], [])


class CashSnapshotTests(BoardTestCase):
    def test_cash_snapshot_aggregates_without_account_names(self) -> None:
        import board_finance
        from ddb_convert import _to_ddb_nested
        from finance_store import _finance_owner_ddb_key, _finance_sheet_ddb_key, _normalize_finance_payload

        self.table.put_item(
            Item={
                **_finance_sheet_ddb_key("accounts"),
                **_to_ddb_nested(
                    {
                        "records": [
                            {
                                "id": "ac-hsbc",
                                "description": "HSBC HK current 123-456",
                                "accountType": "Bank Account",
                                "billingCycleDay": 1,
                                "recordedValue": 1000.0,
                                "currency": "HKD",
                                "lastUpdated": "2026-09-12",
                            },
                            {
                                "id": "ac-monzo",
                                "description": "Monzo",
                                "accountType": "Bank Account",
                                "billingCycleDay": 1,
                                "recordedValue": 50.0,
                                "currency": "GBP",
                                "lastUpdated": "2026-09-11",
                            },
                            {
                                "id": "ac-amex",
                                "description": "Amex Platinum",
                                "accountType": "Credit Card",
                                "billingCycleDay": 14,
                                "recordedValue": 200.0,
                                "currency": "HKD",
                                "lastUpdated": "2026-09-01",
                            },
                        ]
                    }
                ),
            }
        )
        payload = _normalize_finance_payload(
            {
                "defaultCurrency": "HKD",
                "float": {"amount": 0, "currency": "HKD"},
                "lines": [
                    {
                        "id": "inc-1",
                        "dateUtc": "2026-09-01T00:00:00.000Z",
                        "type": "income",
                        "description": "Listing fee",
                        "netAmount": 388,
                        "vat": 0,
                        "grossAmount": 388,
                        "currency": "HKD",
                    }
                ],
            }
        )
        self.table.put_item(Item={**_finance_owner_ddb_key("siuTinDei"), **_to_ddb_nested(payload)})
        lx_payload = _normalize_finance_payload(
            {
                "defaultCurrency": "HKD",
                "float": {"amount": 0, "currency": "HKD"},
                "lines": [
                    {
                        "id": "lx-exp-1",
                        "dateUtc": "2026-09-01T00:00:00.000Z",
                        "type": "expenditure",
                        "description": "AWS admin console",
                        "netAmount": 2235,
                        "vat": 0,
                        "grossAmount": 2235,
                        "currency": "HKD",
                    }
                ],
            }
        )
        self.table.put_item(Item={**_finance_owner_ddb_key("lxSoftware"), **_to_ddb_nested(lx_payload)})
        snap = board_finance.cash_snapshot(self.table, now=datetime(2026, 9, 13, tzinfo=timezone.utc))
        self.assertEqual(snap["asOf"], "2026-09-13")
        self.assertEqual(snap["cash"]["accountCount"], 3)
        self.assertEqual(snap["cash"]["liquidByCurrency"], [{"currency": "GBP", "amount": 50.0}, {"currency": "HKD", "amount": 1000.0}])
        self.assertEqual(snap["cash"]["creditCardByCurrency"], [{"currency": "HKD", "amount": 200.0}])
        self.assertIn("all houses", snap["cash"]["note"])
        blob = json.dumps(snap)
        self.assertNotIn("HSBC", blob)
        self.assertNotIn("123-456", blob)
        self.assertNotIn("Amex", blob)
        self.assertEqual(snap["statementBooks"]["scope"], "siuTinDei")
        self.assertEqual(list(snap["statementBooks"]["books"]), ["siuTinDei"])
        self.assertNotIn("lxSoftware", snap["statementBooks"]["books"])
        self.assertIn("LX Software", snap["statementBooks"]["note"])
        fy = (snap["statementBooks"]["books"]["siuTinDei"].get("fiscalYear") or [])
        self.assertTrue(any(row["currency"] == "HKD" and row["income"] == 388.0 for row in fy))
        ctx = board_tools.ToolContext(table=self.table, settings=board_store.default_settings(), persona_id="cfo")
        out = board_tools.REGISTRY["finance_cash_snapshot"].run(ctx, {})
        self.assertEqual(out["cash"]["accountCount"], 3)
        self.assertNotIn("lxSoftware", out["statementBooks"]["books"])
        rendered = board_finance.render_finance_summary(snap["statementBooks"])
        self.assertIn("Siu Tin Dei", rendered)
        self.assertNotIn("LX Software", rendered)
        self.assertNotIn("2235", rendered)


if __name__ == "__main__":
    unittest.main()
