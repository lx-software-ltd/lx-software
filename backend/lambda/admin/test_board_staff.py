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
        self.assertIn("Do the work", frame)
        seat = {"id": "support", "title": "Parent Support", "displayName": "Sam", "reportsTo": "coo", "brief": "Help parents."}
        prompt = board_personas.render_seat_prompt(seat, {"displayName": "Pat", "title": "COO"}, {}, ["Be brief."])
        self.assertIn("reporting to Pat", prompt)
        self.assertIn("STANDING INSTRUCTIONS", prompt)
        self.assertIn(board_personas.BOOKS_OF_RECORD, prompt)

    def test_accountant_prompt_points_at_product_database_not_xero(self) -> None:
        seat = board_staff.seat_default("accountant") or {}
        cfo = board_personas.persona_default("cfo") or {}
        prompt = board_personas.render_seat_prompt(seat, cfo, {}, [])
        self.assertIn("finance_aging_report", prompt)
        self.assertIn("Siu Tin Dei product database", prompt)
        self.assertIn("no QuickBooks", prompt)
        duties = {str(d["id"]): d for d in (seat.get("duties") or [])}
        self.assertIn("finance_aging_report", duties["weekly-aging"]["brief"])
        self.assertIn("finance_aging_report", duties["month-end-memo"]["brief"])
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
        self.assertIn("book of record", board_tools.REGISTRY["finance_aging_report"].description)
        self.assertIn("no QuickBooks/Xero", board_tools.REGISTRY["finance_list_invoices"].description)

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

    def test_stuck_sweep(self) -> None:
        settings = _enable_staff(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(self.table, settings, assignee="cfo", origin="owner", brief="Stuck", deliverable_type="markdown", created_by="a")
        board_store.claim_task_step(self.table, task["taskId"], 0)
        stale = board_store.get_task(self.table, task["taskId"])
        stale["updatedAt"] = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        board_store.put_task(self.table, stale)
        board_staff.handle_tick({"internal": "board_staff_tick", "boardKey": BOARD_KEY})
        self.assertEqual(board_store.get_task(self.table, task["taskId"])["status"], "failed")
        self.assertEqual(board_store.get_task(self.table, task["taskId"])["failureReason"], "stuck")

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
        settings["staff"]["enabled"] = False
        off = {op.name for op, _ in board_tools.available_ops(settings, "cfo", context="chat")}
        self.assertNotIn("staff_assign", off)


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
