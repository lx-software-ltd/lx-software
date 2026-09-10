"""Unit tests for Executive Board staff tasks (WP1)."""

from __future__ import annotations

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
from contract_constants import BOARD_STAFF_MAX_STEPS_PER_TASK, BOARD_STAFF_TASK_BUDGET_DESK_USD


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
        roster = board_staff.seats_by_id(self.table, settings)
        self.assertFalse(roster["prospector"]["isActive"])
        self.assertEqual(board_staff.seat_level(settings, roster, "prospector", "mail"), "off")

    def test_create_task_validates_and_defaults_budget(self) -> None:
        settings = _enable_staff(self.table)
        with self.assertRaises(board_staff.StaffError):
            board_staff.create_task(self.table, settings, assignee="nope", origin="owner", brief="x", deliverable_type="markdown", created_by="t")
        with self.assertRaises(board_staff.StaffError):
            board_staff.create_task(self.table, settings, assignee="prospector", origin="owner", brief="x", deliverable_type="markdown", created_by="t")
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
        self.assertIn("Do the work", frame)
        seat = {"id": "support", "title": "Parent Support", "displayName": "Sam", "reportsTo": "coo", "brief": "Help parents."}
        prompt = board_personas.render_seat_prompt(seat, {"displayName": "Pat", "title": "COO"}, {}, ["Be brief."])
        self.assertIn("reporting to Pat", prompt)
        self.assertIn("STANDING INSTRUCTIONS", prompt)


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
        board_staff.run_step({"internal": "board_staff_step", "boardKey": "siuTinDei", "taskId": task["taskId"], "step": 2})
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
        board_staff.run_review({"internal": "board_staff_review", "boardKey": "siuTinDei", "taskId": task["taskId"]})
        done = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(done["status"], "delivered")
        reviews = board_store.list_task_reviews(self.table, task["taskId"])
        self.assertEqual(reviews[0]["verdict"], "accept")

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

    def test_review_return_then_second_return_delivers(self) -> None:
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
            self.assertEqual(third["status"], "delivered")
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
        board_staff.run_step({"internal": "board_staff_step", "boardKey": "siuTinDei", "taskId": task["taskId"], "step": BOARD_STAFF_MAX_STEPS_PER_TASK})
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["status"], "failed")
        self.assertEqual(latest["failureReason"], "step limit")

    def test_stuck_sweep(self) -> None:
        settings = _enable_staff(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(self.table, settings, assignee="cfo", origin="owner", brief="Stuck", deliverable_type="markdown", created_by="a")
        board_store.claim_task_step(self.table, task["taskId"], 0)
        stale = board_store.get_task(self.table, task["taskId"])
        stale["updatedAt"] = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        board_store.put_task(self.table, stale)
        board_staff.handle_tick({"internal": "board_staff_tick", "boardKey": "siuTinDei"})
        self.assertEqual(board_store.get_task(self.table, task["taskId"])["status"], "failed")
        self.assertEqual(board_store.get_task(self.table, task["taskId"])["failureReason"], "stuck")

    def test_ceo_task_reviewed_by_cfo(self) -> None:
        task = {"assigneeKind": "persona", "assignee": "ceo", "managerId": "ceo"}
        self.assertEqual(board_staff._reviewer_id(task), "cfo")


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
        settings["staff"]["enabled"] = False
        off = {op.name for op, _ in board_tools.available_ops(settings, "cfo", context="chat")}
        self.assertNotIn("staff_assign", off)
