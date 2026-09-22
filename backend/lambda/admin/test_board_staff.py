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
import board_budget
import board_code
import board_personas
import board_staff
import board_store
import board_tools
from contract_constants import (
    BOARD_KEY,
    BOARD_STAFF_MAX_IDLE_STEPS_PER_TASK,
    BOARD_STAFF_MAX_REVISIONS,
    BOARD_STAFF_MAX_STEPS_PER_TASK,
    BOARD_STAFF_STEP_MODELS,
    BOARD_STAFF_TASK_BUDGET_DESK_USD,
)


def _enable_staff(table: Any, **staff: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True, **staff})
    return board_store.save_settings(table, settings)


class StaffEngineTests(BoardTestCase):
    def test_supersede_stale_failed_duties_keeps_the_newest(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        settings = board_store.load_settings(self.table)
        settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True})
        board_store.save_settings(self.table, settings)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        older = board_staff.create_task(
            self.table,
            settings,
            assignee="content-marketer",
            origin="duty",
            brief="describe southern",
            deliverable_type="json",
            event_ref={"kind": "catalog-enrich", "id": "catalog-enrich:southern"},
            created_by="test",
        )
        older["status"] = "failed"
        older["failureReason"] = "OpenRouter 402"
        older["createdAt"] = "2026-09-20T00:33:00Z"
        board_store.put_task(self.table, older)
        newer = board_staff.create_task(
            self.table,
            settings,
            assignee="content-marketer",
            origin="duty",
            brief="describe southern again",
            deliverable_type="json",
            event_ref={"kind": "catalog-enrich", "id": "catalog-enrich:southern"},
            created_by="test",
        )
        newer["status"] = "needs_owner"
        newer["createdAt"] = "2026-09-21T00:33:00Z"
        board_store.put_task(self.table, newer)
        lone = board_staff.create_task(
            self.table,
            settings,
            assignee="content-marketer",
            origin="duty",
            brief="content plan",
            deliverable_type="json",
            event_ref={"kind": "duty", "id": "content-plan:2026-09-20"},
            created_by="test",
        )
        lone["status"] = "failed"
        lone["failureReason"] = "choices are missing"
        lone["createdAt"] = "2026-09-20T10:00:00Z"
        board_store.put_task(self.table, lone)
        self.assertEqual(board_staff.supersede_stale_failed_duties(self.table), 1)
        closed = board_store.get_task(self.table, older["taskId"])
        self.assertEqual(closed["status"], "cancelled")
        self.assertEqual(closed["closedBy"], "board_staff:superseded")
        self.assertEqual(closed["failureReason"], "")
        self.assertEqual(board_store.get_task(self.table, newer["taskId"])["status"], "needs_owner")
        self.assertEqual(board_store.get_task(self.table, lone["taskId"])["status"], "failed")
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
        self.assertIn("task_request_help", prompt)
        self.assertIn(board_personas.BOOKS_OF_RECORD, prompt)
        self.assertIn(board_personas.ANALYTICS_OF_RECORD, prompt)
        with_help = board_personas.render_task_frame(
            {"brief": "Do the work", "deliverableType": "markdown", "budgetUsd": 1, "usage": {"cost": 0}, "step": 0},
            "",
            help_available="Help available: data-analyst (web).",
        )
        self.assertIn("Help available: data-analyst (web).", with_help)
        code_frame = board_personas.render_task_frame(
            {
                "brief": "Fix CI",
                "deliverableType": "pr",
                "budgetUsd": 3,
                "usage": {"cost": 0},
                "step": 0,
                "eventRef": {"kind": "code-implement", "prNumber": 501},
            },
            "",
        )
        self.assertIn("Call code_run_task once", code_frame)

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
        self.assertEqual(set(needed), {"web_sessions", "web_conversions"})
        self.assertEqual(
            board_staff._brief_required_evidence_tools("Reply to the WhatsApp thread."),  # noqa: SLF001
            [],
        )
        self.assertEqual(
            board_staff._brief_required_evidence_tools(brief, offered={"task_finish", "meta_list_dms"}),  # noqa: SLF001
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
        board_store.add_tool_call(
            self.table,
            {
                "callId": "meta-1",
                "op": "meta_list_dms",
                "context": {"taskId": task["taskId"]},
                "taskId": task["taskId"],
            },
        )
        with self.assertRaises(board_staff.StaffError) as wrong_tool:
            board_staff.op_task_finish(
                ctx,
                {
                    "summary": "Cited the wrong tool.",
                    "deliverableType": "markdown",
                    "deliverable": "Unable to verify GA4 integration due to lack of access.",
                    "evidence": ["meta-1"],
                    "openQuestions": [],
                    "confidence": "low",
                },
            )
        self.assertIn("web_sessions", str(wrong_tool.exception))
        self.assertEqual(board_staff.preferred_assignee_for_brief(self.table, settings, brief), "data-analyst")
        self.assertIn("data-analyst", board_staff.ga4_assignee_hint(self.table, settings))
        import board_meeting

        roster_text, seat_ids = board_meeting._assignee_roster_text(  # noqa: SLF001
            self.table, settings, ["cmo", "cio"]
        )
        self.assertIn("data-analyst", seat_ids)
        self.assertIn("assign data-analyst", roster_text)
        self.assertIn("Do not assign community-manager", roster_text)

    def test_content_marketer_has_web_read_and_refuses_web_help(self) -> None:
        seat = board_staff.seat_default("content-marketer") or {}
        self.assertEqual((seat.get("tools") or {}).get("web"), "read")
        self.assertEqual((seat.get("tools") or {}).get("research"), "read")
        self.assertIn("do not request help for web", (seat.get("brief") or "").lower())
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        roster = board_staff.seats_by_id(self.table, settings)
        self.assertEqual(board_staff.seat_level(settings, roster, "content-marketer", "web"), "read")
        ops = {
            op.name
            for op, _ in board_tools.available_ops(
                settings, "cmo", context="task", seat_id="content-marketer", seats_by_id=roster
            )
        }
        self.assertIn("research_fetch_page", ops)
        self.assertIn("web_sessions", ops)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(
                self.table,
                settings,
                assignee="content-marketer",
                origin="duty",
                brief="Catalog sheet",
                deliverable_type="json",
                created_by="admin",
            )
        reason = board_staff.validate_task_request_help(
            board_tools.ToolContext(
                table=self.table,
                settings=settings,
                persona_id="cmo",
                kind="task",
                task_id=task["taskId"],
                seat_id="content-marketer",
            ),
            {"need": "Fetch official LCSD pages", "toolIds": ["web"]},
        )
        self.assertIn("already have those tools", reason)

    def test_ga4_brief_does_not_deadlock_seats_without_web(self) -> None:
        settings = _enable_staff(self.table)
        brief = "Verify GA4 visitor sources and event tracking."
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(
                self.table,
                settings,
                assignee="support",
                origin="owner",
                brief=brief,
                deliverable_type="markdown",
                created_by="a",
            )
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=settings,
            persona_id="coo",
            kind="task",
            task_id=task["taskId"],
            seat_id="support",
        )
        offered = board_staff._offered_task_ops(ctx)  # noqa: SLF001
        self.assertNotIn("web_sessions", offered)
        self.assertEqual(board_staff._brief_required_evidence_tools(brief, offered=offered), [])  # noqa: SLF001
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            out = board_staff.op_task_finish(
                ctx,
                {
                    "summary": "No web tools on this seat.",
                    "deliverableType": "markdown",
                    "deliverable": "This seat cannot read GA4; hand the brief to data-analyst.",
                    "evidence": [],
                    "openQuestions": ["Reassign to data-analyst"],
                    "confidence": "low",
                },
            )
        self.assertEqual(out["status"], "review")

    def test_retry_needs_owner_requeues(self) -> None:
        settings = _enable_staff(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(
                self.table,
                settings,
                assignee="community-manager",
                origin="owner",
                brief="Verify GA4 visitor sources.",
                deliverable_type="markdown",
                created_by="a",
            )
        task["status"] = "needs_owner"
        task["revisions"] = 2
        board_store.put_task(self.table, task)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            retried = board_staff.retry_task(self.table, settings, task["taskId"], "owner-1")
        self.assertIn(retried["status"], ("queued", "running"))
        self.assertEqual(retried["revisions"], 0)
        self.assertEqual(retried.get("retriedBy"), "owner-1")
        self.assertNotEqual(retried["status"], "needs_owner")

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

    def test_task_finish_accepts_openrouter_tool_call_id_alias(self) -> None:
        task = self._queued_task()
        board_store.claim_task_step(self.table, task["taskId"], 0)
        board_store.add_tool_call(
            self.table,
            {
                "callId": "aws-hex",
                "toolCallId": "call_xBcJqwPl7xTCkUM4TCnz6XgI",
                "op": "aws_monthly_cost",
                "context": {"taskId": task["taskId"]},
                "taskId": task["taskId"],
            },
        )
        board_store.add_tool_call(
            self.table,
            {
                "callId": "fin-hex",
                "toolCallId": "call_c5cyCLCJraBvdZ3cR9qcuNep",
                "op": "finance_aging_report",
                "context": {"taskId": task["taskId"]},
                "taskId": task["taskId"],
            },
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
                    "summary": "Cited model tool_call_ids.",
                    "deliverableType": "markdown",
                    "deliverable": "# Costs\n\n- Lambda",
                    "evidence": ["call_xBcJqwPl7xTCkUM4TCnz6XgI", "call_c5cyCLCJraBvdZ3cR9qcuNep"],
                    "openQuestions": [],
                    "confidence": "high",
                },
            )
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["status"], "review")
        self.assertEqual(latest["evidence"], ["aws-hex", "fin-hex"])

    def test_canonical_evidence_keeps_step_only_call_ids(self) -> None:
        task = self._queued_task()
        board_store.put_task_step(
            self.table,
            task["taskId"],
            {"seq": 0, "attempt": 1, "callIds": ["step-only-hex"]},
        )
        kept = board_staff._canonical_evidence_ids(  # noqa: SLF001
            self.table, task, ["step-only-hex", "unknown"]
        )
        self.assertEqual(kept, ["step-only-hex"])

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

    def test_catalog_quality_return_flags_thin_sheet(self) -> None:
        thin = json.dumps(
            {
                "district": "Eastern",
                "organisations": [
                    {"name_en": "Thin Park", "type": "playground", "verified_fields": ["name_en"]}
                ],
            }
        )
        rich = json.dumps(
            {
                "district": "Eastern",
                "organisations": [
                    {
                        "name_en": "Rich Park",
                        "address_en": "Lei King Road",
                        "opening_hours": "Daily 07:00-23:00",
                        "verified_fields": ["name_en", "address_en", "opening_hours"],
                    }
                ],
            }
        )
        catalog = {"eventRef": {"kind": "catalog-micro-batch"}}
        enrich = {"eventRef": {"kind": "catalog-enrich"}}
        other = {"eventRef": {"kind": "duty"}}
        self.assertIn("only 0 of address", board_staff._catalog_quality_return(catalog, thin))
        self.assertEqual(board_staff._catalog_quality_return(catalog, rich), "")
        self.assertIn("only 0 of address", board_staff._catalog_quality_return(enrich, thin))
        self.assertEqual(board_staff._catalog_quality_return(other, thin), "")
        prompt = board_staff._review_user_prompt(catalog, thin, [])
        self.assertIn("fewer than two of", prompt)
        self.assertIn("opening_hours", prompt)

    def test_catalog_review_overrides_accept_when_sheet_is_thin(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(
                self.table,
                settings,
                assignee="content-marketer",
                origin="duty",
                brief="Catalog sheet",
                deliverable_type="json",
                event_ref={"kind": "catalog-micro-batch", "id": "catalog:eastern", "districtId": "eastern"},
                created_by="admin",
            )
        board_store.claim_task_step(self.table, task["taskId"], 0)
        thin = {
            "district": "Eastern",
            "organisations": [
                {"name_en": "Thin Park", "type": "playground", "verified_fields": ["name_en"]}
            ],
        }
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=settings,
            persona_id="content-marketer",
            display_name="Content Marketer",
            kind="task",
            task_id=task["taskId"],
            actor="persona",
        )
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff.op_task_finish(
                ctx,
                {
                    "summary": "Three orgs.",
                    "deliverableType": "json",
                    "deliverable": json.dumps(thin),
                    "evidence": [],
                    "openQuestions": [],
                    "confidence": "high",
                },
            )
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest["status"], "review")
        with patch.object(board_budget, "board_completion") as completion:
            board_staff.run_review({"internal": "board_staff_review", "boardKey": BOARD_KEY, "taskId": task["taskId"]})
        review_calls = [call for call in completion.call_args_list if call.kwargs.get("tag") == "board_staff_review"]
        self.assertEqual(review_calls, [])
        done = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(done["lastReview"]["verdict"], "return")
        self.assertIn("Return —", done["lastReview"]["notes"])
        self.assertIn("Thin Park", done["lastReview"]["notes"])

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

    def test_task_finish_strips_function_call_and_rejects_bad_json(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(
                self.table,
                settings,
                assignee="content-marketer",
                origin="owner",
                brief="Return a JSON object with organisations.",
                deliverable_type="markdown",
                created_by="a",
            )
        board_store.claim_task_step(self.table, task["taskId"], 0)
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=board_store.load_settings(self.table),
            persona_id="cmo",
            kind="task",
            task_id=task["taskId"],
        )
        with self.assertRaises(board_staff.StaffError) as raised:
            board_staff.op_task_finish(
                ctx,
                {
                    "summary": "batch",
                    "deliverable": "not json at all",
                    "deliverableType": "markdown",
                    "evidence": [],
                    "confidence": "low",
                },
            )
        self.assertIn("JSON does not parse", str(raised.exception))
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff.op_task_finish(
                ctx,
                {
                    "summary": "batch",
                    "deliverable": '!function_call:{"name":"task_finish"}\n{"district":"Sha Tin","organisations":[]}',
                    "deliverableType": "markdown",
                    "evidence": [],
                    "confidence": "low",
                },
            )
        raw = board_staff.read_deliverable(board_store.get_task(self.table, task["taskId"]))
        self.assertNotIn("!function_call:", raw)
        self.assertIn("Sha Tin", raw)

    def test_task_finish_archives_mail_from_memo(self) -> None:
        settings = _enable_staff(self.table)
        board_store.put_mail_thread(self.table, {"threadId": "th-fin", "subject": "FYI", "disposition": ""})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(
                self.table,
                settings,
                assignee="support",
                origin="event",
                brief="Triage inbound mail",
                deliverable_type="markdown",
                created_by="board_triage",
                event_ref={"kind": "mail", "id": "th-fin"},
            )
        board_store.claim_task_step(self.table, task["taskId"], 0)
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=board_store.load_settings(self.table),
            persona_id="coo",
            kind="task",
            task_id=task["taskId"],
        )
        board_staff.op_task_finish(
            ctx,
            {
                "summary": "archived",
                "deliverable": "ARCHIVED — no action: automated SES notice",
                "deliverableType": "markdown",
                "evidence": [],
                "confidence": "low",
            },
        )
        self.assertEqual(board_store.get_mail_thread(self.table, "th-fin")["disposition"], "archived")

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

    def test_two_steps_left_appends_finish_nudge(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        latest = board_store.get_task(self.table, tid)
        latest["status"] = "running"
        latest["step"] = BOARD_STAFF_MAX_STEPS_PER_TASK - 3
        board_store.put_task(self.table, latest)
        result = type(
            "R",
            (),
            {
                "text": "still researching",
                "usage": {},
                "calls": [{"op": "research_search", "status": "ok", "callId": "c1"}],
            },
        )()
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff._complete_step(self.table, tid, latest, result, BOARD_STAFF_MAX_STEPS_PER_TASK - 2)
        scratch = board_staff._blob_get(board_staff._scratchpad_key(tid)).decode()  # noqa: SLF001
        self.assertIn("Two steps left", scratch)

    def test_repeated_code_review_calls_count_as_idle(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "architect", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(
                self.table,
                settings,
                assignee="architect",
                origin="event",
                brief="Review PR #7",
                deliverable_type="markdown",
                event_ref={"kind": "code-review", "id": "pr:7", "prNumber": 7},
                created_by="board_code",
            )
        tid = task["taskId"]
        latest = board_store.get_task(self.table, tid)
        latest["status"] = "running"
        latest["step"] = 1
        board_store.put_task(self.table, latest)
        args = {"prNumber": 7, "reason": "Review the pull request."}
        board_store.add_tool_call(
            self.table,
            {
                "callId": "rev-1",
                "op": "code_review_pr",
                "toolId": "code",
                "status": "ok",
                "taskId": tid,
                "arguments": args,
            },
        )
        board_store.put_task_step(
            self.table,
            tid,
            {"seq": 1, "plan": "review", "callIds": ["rev-1"], "at": board_store.now_iso()},
        )
        board_store.add_tool_call(
            self.table,
            {
                "callId": "rev-2",
                "op": "code_review_pr",
                "toolId": "code",
                "status": "ok",
                "taskId": tid,
                "arguments": args,
            },
        )
        result = type(
            "R",
            (),
            {
                "text": "reviewed again",
                "usage": {},
                "calls": [{"op": "code_review_pr", "status": "ok", "callId": "rev-2", "arguments": args}],
            },
        )()
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff._complete_step(self.table, tid, latest, result, 2)
        out = board_store.get_task(self.table, tid)
        self.assertEqual(out["idleSteps"], 1)
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

    def test_openrouter_403_retries_once_on_other_model(self) -> None:
        from openrouter_client import OpenRouterError

        task = self._queued_task()
        tid = task["taskId"]
        payloads: list[dict[str, Any]] = []

        def boom(*_a: Any, **_k: Any) -> None:
            raise OpenRouterError("The request is prohibited due to a violation of provider Terms Of Service.", status=403)

        with (
            patch.object(board_tools, "run_tool_loop", boom),
            patch.object(board_async, "invoke_async", lambda payload, fallback=None: payloads.append(payload)),
        ):
            board_staff.run_step({"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": tid, "step": 1})
        latest = board_store.get_task(self.table, tid)
        self.assertEqual(latest["status"], "running")
        self.assertTrue(payloads)
        self.assertTrue(payloads[0].get("retried"))
        self.assertIn(payloads[0].get("modelOverride"), BOARD_STAFF_STEP_MODELS)

    def test_openrouter_403_keeps_pinned_seat_model(self) -> None:
        from openrouter_client import OpenRouterError

        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(
                self.table,
                settings,
                assignee="content-marketer",
                origin="owner",
                brief="Plan next week's content calendar",
                deliverable_type="json",
                created_by="admin",
            )
        tid = task["taskId"]
        payloads: list[dict[str, Any]] = []

        def boom(*_a: Any, **_k: Any) -> None:
            raise OpenRouterError("The request is prohibited due to a violation of provider Terms Of Service.", status=403)

        with (
            patch.object(board_tools, "run_tool_loop", boom),
            patch.object(board_async, "invoke_async", lambda payload, fallback=None: payloads.append(payload)),
        ):
            board_staff.run_step({"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": tid, "step": 1})
        self.assertTrue(payloads)
        self.assertEqual(payloads[0].get("modelOverride"), "qwen/qwen-2.5-72b-instruct")

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
        self.assertEqual(latest["status"], "queued")
        self.assertIn("OpenRouter credits", latest.get("parkedReason") or "")
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

    def test_openrouter_credits_pause_requeues(self) -> None:
        import board_breakers

        task = self._queued_task()
        tid = task["taskId"]
        board_breakers.trip(self.table, "budget", "OpenRouter 402: insufficient credits")
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff.run_step({"internal": "board_staff_step", "boardKey": BOARD_KEY, "taskId": tid, "step": 1})
        latest = board_store.get_task(self.table, tid)
        self.assertEqual(latest["status"], "queued")
        self.assertIn("openrouter credits paused", latest.get("parkedReason") or "")

    def test_openrouter_credits_pause_skips_drain(self) -> None:
        import board_breakers

        settings = _enable_staff(self.table)
        board_breakers.trip(self.table, "budget", "OpenRouter 402: insufficient credits")
        task = board_staff.create_task(
            self.table,
            settings,
            assignee="cfo",
            origin="owner",
            brief="List our three biggest monthly costs from AWS and finance",
            deliverable_type="markdown",
            created_by="admin",
        )
        self.assertEqual(task["status"], "queued")
        self.assertEqual(board_staff.drain_queue(self.table, settings), 0)
        self.assertEqual(board_store.get_task(self.table, task["taskId"])["status"], "queued")

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

    def test_owner_accept_bypasses_unverified_hold(self) -> None:
        task = self._queued_task()
        board_store.claim_task_step(self.table, task["taskId"], 0)
        task = board_store.get_task(self.table, task["taskId"])
        task.update(
            {
                "status": "review",
                "origin": "event",
                "brief": "Implement the booking form",
                "flags": ["no_evidence", "salvaged"],
                "deliverableType": "markdown",
                "summary": "Done",
            }
        )
        board_store.put_task(self.table, task)
        settings = board_store.load_settings(self.table)
        held = board_staff.apply_review(self.table, settings, dict(task), verdict="accept", notes="ok", by="manager")
        self.assertEqual(held["status"], "needs_owner")
        accepted = board_staff.apply_review(
            self.table, settings, board_store.get_task(self.table, task["taskId"]), verdict="accept", notes="merged", by="owner:founder"
        )
        self.assertEqual(accepted["status"], "delivered")
        self.assertEqual(accepted.get("acceptedBy"), "owner:founder")

    def test_blocked_finish_parks_without_review(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        board_store.claim_task_step(self.table, tid, 0)
        latest = board_store.get_task(self.table, tid)
        latest["status"] = "running"
        board_store.put_task(self.table, latest)
        ctx = board_tools.ToolContext(
            self.table, board_store.load_settings(self.table), "cto", kind="task", task_id=tid, seat_id="engineer-1"
        )
        board_store.add_tool_call(
            self.table,
            {
                "callId": "refused-1",
                "op": "code_run_task",
                "toolId": "code",
                "status": "refused",
                "taskId": tid,
                "resultPreview": '{"error": "already in flight"}',
            },
        )
        out = board_staff.op_task_finish(
            ctx,
            {
                "summary": "Runner breaker is tripped",
                "deliverableType": "markdown",
                "deliverable": "Cannot dispatch; tool:code breaker is tripped.",
                "confidence": "low",
                "status": "blocked",
                "blockedReason": "runner already in flight",
            },
        )
        self.assertTrue(out.get("blocked"))
        parked = board_store.get_task(self.table, tid)
        self.assertEqual(parked["status"], "needs_owner")
        self.assertEqual(parked["parkedReason"], "blocked:tool:code")
        self.assertEqual(parked.get("reviews") or 0, 0)

    def test_blocked_finish_without_refused_call_is_rejected(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        board_store.claim_task_step(self.table, tid, 0)
        latest = board_store.get_task(self.table, tid)
        latest["status"] = "running"
        board_store.put_task(self.table, latest)
        ctx = board_tools.ToolContext(
            self.table, board_store.load_settings(self.table), "cto", kind="task", task_id=tid, seat_id="engineer-1"
        )
        with self.assertRaises(board_staff.StaffError) as raised:
            board_staff.op_task_finish(
                ctx,
                {
                    "summary": "This is hard",
                    "deliverableType": "markdown",
                    "deliverable": "Giving up.",
                    "confidence": "low",
                    "status": "blocked",
                    "blockedReason": "too hard",
                },
            )
        self.assertIn("refused tool call", str(raised.exception))

    def test_repeated_identical_reads_fail_with_no_progress(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        latest = board_store.get_task(self.table, tid)
        latest["status"] = "running"
        latest["step"] = 1
        latest["idleSteps"] = BOARD_STAFF_MAX_IDLE_STEPS_PER_TASK - 1
        board_store.put_task(self.table, latest)
        args = {"taskId": "run-1"}
        board_store.add_tool_call(
            self.table,
            {
                "callId": "get-1",
                "op": "code_get_run",
                "toolId": "code",
                "status": "ok",
                "taskId": tid,
                "arguments": args,
            },
        )
        board_store.put_task_step(
            self.table, tid, {"seq": 1, "plan": "poll", "callIds": ["get-1"], "at": board_store.now_iso()}
        )
        board_store.add_tool_call(
            self.table,
            {
                "callId": "get-2",
                "op": "code_get_run",
                "toolId": "code",
                "status": "ok",
                "taskId": tid,
                "arguments": args,
            },
        )
        result = type(
            "R",
            (),
            {
                "text": "still pending",
                "usage": {},
                "calls": [{"op": "code_get_run", "status": "ok", "callId": "get-2", "arguments": args}],
            },
        )()
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff._complete_step(self.table, tid, latest, result, 2)
        out = board_store.get_task(self.table, tid)
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["failureReason"], "no progress")

    def test_repeated_research_reads_do_not_fail_with_no_progress(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        latest = board_store.get_task(self.table, tid)
        latest["status"] = "running"
        latest["step"] = 1
        latest["idleSteps"] = BOARD_STAFF_MAX_IDLE_STEPS_PER_TASK - 1
        board_store.put_task(self.table, latest)
        args = {"query": "hong kong weekend activities"}
        board_store.add_tool_call(
            self.table,
            {
                "callId": "search-1",
                "op": "research_search",
                "toolId": "research",
                "status": "ok",
                "taskId": tid,
                "arguments": args,
            },
        )
        board_store.put_task_step(
            self.table, tid, {"seq": 1, "plan": "search", "callIds": ["search-1"], "at": board_store.now_iso()}
        )
        board_store.add_tool_call(
            self.table,
            {
                "callId": "search-2",
                "op": "research_search",
                "toolId": "research",
                "status": "ok",
                "taskId": tid,
                "arguments": args,
            },
        )
        result = type(
            "R",
            (),
            {
                "text": "same results",
                "usage": {},
                "calls": [{"op": "research_search", "status": "ok", "callId": "search-2", "arguments": args}],
            },
        )()
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff._complete_step(self.table, tid, latest, result, 2)
        out = board_store.get_task(self.table, tid)
        self.assertNotEqual(out.get("failureReason"), "no progress")

    def test_task_note_is_not_evidence(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        board_store.claim_task_step(self.table, tid, 0)
        board_store.add_tool_call(
            self.table,
            {
                "callId": "note-1",
                "op": "task_note",
                "toolId": "task",
                "status": "ok",
                "taskId": tid,
                "arguments": {"text": "drafting"},
            },
        )
        ctx = board_tools.ToolContext(
            self.table, board_store.load_settings(self.table), "cfo", kind="task", task_id=tid
        )
        with self.assertRaises(board_staff.StaffError) as raised:
            board_staff.op_task_finish(
                ctx,
                {
                    "summary": "Drafted from a note",
                    "deliverableType": "markdown",
                    "deliverable": "Template agreement.",
                    "evidence": ["note-1"],
                    "openQuestions": [],
                    "confidence": "high",
                },
            )
        self.assertIn("task_note call ids are not evidence", str(raised.exception))

    def test_intra_step_poll_repeats_fail_with_no_progress(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        latest = board_store.get_task(self.table, tid)
        latest["status"] = "running"
        latest["step"] = 1
        latest["idleSteps"] = BOARD_STAFF_MAX_IDLE_STEPS_PER_TASK - 1
        latest["eventRef"] = {"kind": "code-implement", "id": "issue:1"}
        board_store.put_task(self.table, latest)
        args = {"taskId": tid}
        calls: list[dict[str, Any]] = []
        for i in range(3):
            cid = f"poll-{i}"
            board_store.add_tool_call(
                self.table,
                {
                    "callId": cid,
                    "op": "code_get_run",
                    "toolId": "code",
                    "status": "ok",
                    "taskId": tid,
                    "arguments": args,
                },
            )
            calls.append({"op": "code_get_run", "status": "ok", "callId": cid, "arguments": args})
        result = type("R", (), {"text": "still pending", "usage": {}, "calls": calls})()
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff._complete_step(self.table, tid, latest, result, 2)
        out = board_store.get_task(self.table, tid)
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["failureReason"], "no progress")

    def test_salvage_after_return_parks_needs_owner(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        latest = board_store.get_task(self.table, tid)
        latest["status"] = "running"
        latest["step"] = BOARD_STAFF_MAX_STEPS_PER_TASK - 1
        latest["lastReview"] = {"verdict": "return", "notes": "no progress", "by": "manager"}
        board_store.put_task(self.table, latest)
        note = "The CI run for PR #501 is still failing. " * 12
        result = type("R", (), {"text": note, "usage": {}, "calls": []})()
        invoked: list[dict[str, Any]] = []

        def capture(payload: dict[str, Any], fallback: Any = None) -> None:  # noqa: ARG001
            invoked.append(payload)

        with patch.object(board_async, "invoke_async", side_effect=capture):
            board_staff._complete_step(self.table, tid, latest, result, BOARD_STAFF_MAX_STEPS_PER_TASK)
        out = board_store.get_task(self.table, tid)
        self.assertEqual(out["status"], "needs_owner")
        self.assertIn("salvaged", out.get("flags") or [])
        self.assertIn("already returned", out.get("parkedReason") or "")
        self.assertFalse(any(p.get("internal") == "board_staff_review" for p in invoked))

    def test_salvage_after_retry_ignores_stale_return(self) -> None:
        task = self._queued_task()
        tid = task["taskId"]
        latest = board_store.get_task(self.table, tid)
        latest["status"] = "running"
        latest["step"] = BOARD_STAFF_MAX_STEPS_PER_TASK - 1
        latest["retriedAt"] = "2026-09-16T00:00:00Z"
        latest["lastReview"] = {
            "verdict": "return",
            "notes": "no progress",
            "by": "manager",
            "at": "2026-09-15T00:00:00Z",
        }
        board_store.put_task(self.table, latest)
        note = "The CI run for PR #501 is still failing. " * 12
        result = type("R", (), {"text": note, "usage": {}, "calls": []})()
        invoked: list[dict[str, Any]] = []

        def capture(payload: dict[str, Any], fallback: Any = None) -> None:  # noqa: ARG001
            invoked.append(payload)

        with patch.object(board_async, "invoke_async", side_effect=capture):
            board_staff._complete_step(self.table, tid, latest, result, BOARD_STAFF_MAX_STEPS_PER_TASK)
        out = board_store.get_task(self.table, tid)
        self.assertEqual(out["status"], "review")
        self.assertTrue(any(p.get("internal") == "board_staff_review" for p in invoked))

    def test_model_for_seat_uses_override(self) -> None:
        settings = _enable_staff(self.table, modelBySeat={"engineer-1": "qwen/qwen-2.5-72b-instruct"})
        self.assertEqual(
            board_staff._model_for_seat(settings, "engineer-1", "deepDive"),  # noqa: SLF001
            "qwen/qwen-2.5-72b-instruct",
        )
        self.assertNotEqual(board_staff._model_for_seat(settings, "support", "standup"), "qwen/qwen-2.5-72b-instruct")  # noqa: SLF001
        raw = {
            **settings,
            "staff": {**(settings.get("staff") or {}), "modelBySeat": {"engineer-1": "openai/gpt-nope"}},
        }
        self.assertNotEqual(board_staff._model_for_seat(raw, "engineer-1", "deepDive"), "openai/gpt-nope")  # noqa: SLF001
        cleaned = board_store.normalize_staff_config({"modelBySeat": {"engineer-1": "openai/gpt-nope", "support": "deepseek/deepseek-chat"}})
        self.assertNotIn("engineer-1", cleaned["modelBySeat"])
        self.assertEqual(cleaned["modelBySeat"]["support"], "deepseek/deepseek-chat")
        # The content-marketer default is a one-time migration, not a read-time force,
        # so the owner can clear it later.
        self.assertNotIn("content-marketer", cleaned["modelBySeat"])
        self.assertEqual(board_store.default_staff_config()["modelBySeat"]["content-marketer"], "qwen/qwen-2.5-72b-instruct")

    def test_ensure_autonomy_defaults_persists_model_and_hold(self) -> None:
        board_store._put_state(  # noqa: SLF001
            self.table,
            "settings",
            {"staff": {"enabled": True}, "boundaries": {"holds": {"catalog_import": 24}}, "version": 1},
        )
        out = board_store.ensure_autonomy_defaults(self.table)
        self.assertEqual(out["staff"]["modelBySeat"]["content-marketer"], "qwen/qwen-2.5-72b-instruct")
        self.assertEqual(out["boundaries"]["holds"]["catalog_import"], 2)
        self.assertNotIn("catalog_import", out["boundaries"]["holdOverrides"])
        stored = board_store._get_state(self.table, "settings")  # noqa: SLF001
        self.assertEqual(stored["staff"]["modelBySeat"]["content-marketer"], "qwen/qwen-2.5-72b-instruct")
        self.assertEqual(stored["boundaries"]["holds"]["catalog_import"], 2)
        self.assertNotIn("catalog_import", stored["boundaries"].get("holdOverrides") or {})
        again = board_store.ensure_autonomy_defaults(self.table)
        self.assertEqual(again["version"], out["version"])
        # Owner edits after the migration are respected on later ticks.
        edited = board_store.load_settings(self.table)
        edited["boundaries"]["holds"]["catalog_import"] = 24
        edited["staff"]["modelBySeat"].pop("content-marketer", None)
        board_store.save_settings(self.table, edited)
        later = board_store.ensure_autonomy_defaults(self.table)
        self.assertEqual(later["boundaries"]["holds"]["catalog_import"], 24)
        self.assertNotIn("content-marketer", later["staff"]["modelBySeat"])

    def test_ensure_autonomy_defaults_respects_ramp_override(self) -> None:
        board_store._put_state(  # noqa: SLF001
            self.table,
            "settings",
            {"boundaries": {"holds": {"catalog_import": 0}, "holdOverrides": {"catalog_import": 0}}, "version": 1},
        )
        out = board_store.ensure_autonomy_defaults(self.table)
        self.assertEqual(out["boundaries"]["holds"]["catalog_import"], 0)
        self.assertEqual(out["boundaries"]["holdOverrides"]["catalog_import"], 0)

    def test_review_flag_line_names_salvaged(self) -> None:
        line = board_staff._review_flag_line({"flags": ["salvaged", "no_evidence"]})  # noqa: SLF001
        self.assertIn("FLAGS: salvaged, no_evidence", line)
        self.assertIn("official_url", line)

    def test_scratchpad_frame_trims_old_chunks(self) -> None:
        pad = "\n\n".join([f"note {i} " + ("x" * 20) for i in range(8)])
        frame = board_personas.render_task_frame({"brief": "Do work", "budgetUsd": 3, "usage": {}, "step": 1}, pad)
        self.assertIn("earlier scratchpad notes omitted", frame)
        self.assertIn("note 7", frame)
        self.assertNotIn("note 0", frame)


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

    def test_create_task_with_pr_number_sets_revision_ref(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None), patch.object(
            board_code,
            "owner_revision_ref",
            return_value={
                "kind": "code-implement",
                "id": "pr:498:owner",
                "prNumber": 498,
                "issueNumber": 489,
                "sourceTaskId": "run-1",
            },
        ):
            _enable_staff(self.table)
            status, created = self.call(
                "/siu-tin-dei/board/tasks",
                "POST",
                {
                    "assignee": "cfo",
                    "brief": "Fix CI on PR 498",
                    "deliverableType": "pr",
                    "prNumber": 498,
                },
            )
        self.assertEqual(status, 201)
        self.assertEqual(created["task"]["eventRef"]["prNumber"], 498)
        self.assertEqual(created["task"]["eventRef"]["issueNumber"], 489)
        self.assertIn("code_run_task ONCE", created["task"]["brief"])

    def test_create_engineer_task_derives_revision_ref_from_brief(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None), patch.object(
            board_code,
            "owner_revision_ref",
            return_value={
                "kind": "code-implement",
                "id": "pr:501:owner",
                "prNumber": 501,
                "issueNumber": 489,
                "sourceTaskId": "run-1",
            },
        ) as revision:
            _enable_staff(self.table)
            board_store.save_staff_override(self.table, "engineer-1", {"isActive": True})
            status, created = self.call(
                "/siu-tin-dei/board/tasks",
                "POST",
                {
                    "assignee": "engineer-1",
                    "brief": "Fix the two failing resolver tests on PR #501 (unknown area_name).",
                    "deliverableType": "pr",
                },
            )
        self.assertEqual(status, 201, created)
        revision.assert_called_once()
        self.assertEqual(revision.call_args.args[1], 501)
        self.assertEqual(created["task"]["eventRef"]["prNumber"], 501)
        self.assertEqual(created["task"]["eventRef"]["issueNumber"], 489)

    def test_create_engineer_task_brief_issue_fills_owner_revision(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None), patch.object(
            board_code,
            "owner_revision_ref",
            return_value={
                "kind": "code-implement",
                "id": "pr:501:owner",
                "prNumber": 501,
                "issueNumber": 489,
                "sourceTaskId": "run-1",
            },
        ) as revision:
            _enable_staff(self.table)
            board_store.save_staff_override(self.table, "engineer-2", {"isActive": True})
            status, created = self.call(
                "/siu-tin-dei/board/tasks",
                "POST",
                {
                    "assignee": "engineer-2",
                    "brief": "Fix CI on PR #501, issue #489.",
                    "deliverableType": "pr",
                },
            )
        self.assertEqual(status, 201, created)
        self.assertEqual(revision.call_args.args[2], 489)
        self.assertEqual(created["task"]["eventRef"]["issueNumber"], 489)

    def test_create_engineer_markdown_ignores_pr_mention_in_brief(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None), patch.object(
            board_code,
            "owner_revision_ref",
        ) as revision:
            _enable_staff(self.table)
            board_store.save_staff_override(self.table, "engineer-1", {"isActive": True})
            status, created = self.call(
                "/siu-tin-dei/board/tasks",
                "POST",
                {
                    "assignee": "engineer-1",
                    "brief": "Summarise comments on PR #501",
                    "deliverableType": "markdown",
                },
            )
        self.assertEqual(status, 201, created)
        revision.assert_not_called()
        self.assertFalse(created["task"].get("eventRef"))

    def test_create_engineer_brief_revision_without_issue_still_creates(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None), patch.object(
            board_code,
            "owner_revision_ref",
            side_effect=board_code.CodeRefused("PR #501 has no linked GitHub issue; pass issueNumber"),
        ) as revision:
            _enable_staff(self.table)
            board_store.save_staff_override(self.table, "engineer-1", {"isActive": True})
            status, created = self.call(
                "/siu-tin-dei/board/tasks",
                "POST",
                {
                    "assignee": "engineer-1",
                    "brief": "Fix CI on PR #501",
                    "deliverableType": "pr",
                },
            )
        self.assertEqual(status, 201, created)
        revision.assert_called_once()
        self.assertFalse(created["task"].get("eventRef"))
        self.assertNotIn("code_run_task", created["task"]["brief"])

    def test_create_non_engineer_task_ignores_pr_mention_in_brief(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None), patch.object(
            board_code,
            "owner_revision_ref",
        ) as revision:
            _enable_staff(self.table)
            status, created = self.call(
                "/siu-tin-dei/board/tasks",
                "POST",
                {
                    "assignee": "cfo",
                    "brief": "Summarise spend related to PR #501",
                    "deliverableType": "markdown",
                },
            )
        self.assertEqual(status, 201, created)
        revision.assert_not_called()
        self.assertFalse(created["task"].get("eventRef"))

    def test_create_task_pr_without_linked_issue_returns_400(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None), patch.object(
            board_code,
            "owner_revision_ref",
            side_effect=board_code.CodeRefused("PR #999 has no linked GitHub issue; pass issueNumber"),
        ):
            _enable_staff(self.table)
            status, body = self.call(
                "/siu-tin-dei/board/tasks",
                "POST",
                {
                    "assignee": "cfo",
                    "brief": "Fix CI on an orphan PR",
                    "deliverableType": "pr",
                    "prNumber": 999,
                },
            )
        self.assertEqual(status, 400)
        self.assertIn("issue", str(body.get("message") or "").lower())

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
            row.update(
                {
                    "status": "failed",
                    "failureReason": "stuck",
                    "stepClaimed": 1,
                    "lastReview": {"verdict": "return", "notes": "try again", "at": "2026-01-01T00:00:00Z"},
                }
            )
            board_store.put_task(self.table, row)
            status, body = self.call(f"/siu-tin-dei/board/tasks/{task_id}/retry", "POST", {})
            self.assertEqual(status, 200)
            self.assertIn(body["task"]["status"], ("queued", "running"))
            self.assertEqual(body["task"].get("failureReason") or "", "")
            self.assertFalse(body["task"].get("lastReview"))
            status, again = self.call(f"/siu-tin-dei/board/tasks/{task_id}/retry", "POST", {})
            self.assertEqual(status, 409)

    def test_retry_labels_stale_scratchpad(self) -> None:
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
            board_staff._append_scratchpad(row, "run already scheduled")  # noqa: SLF001
            row.update({"status": "needs_owner", "failureReason": "breaker tripped"})
            board_store.put_task(self.table, row)
            status, body = self.call(f"/siu-tin-dei/board/tasks/{task_id}/retry", "POST", {})
            self.assertEqual(status, 200)
            scratch = board_staff._blob_get(body["task"]["scratchpadKey"]).decode()  # noqa: SLF001
            self.assertIn("RETRY — the notes below are from a failed attempt", scratch)
            self.assertIn("run already scheduled", scratch)
            self.assertLess(scratch.find("RETRY —"), scratch.find("run already scheduled"))

    def test_prepend_scratchpad_drops_existing_when_banner_fills_cap(self) -> None:
        task = {"taskId": "t-pre", "scratchpadKey": "pad/t-pre"}
        board_staff._blob_put("pad/t-pre", b"old notes that must not survive")  # noqa: SLF001
        with patch.object(board_staff, "BOARD_STAFF_SCRATCHPAD_MAX_CHARS", 12):
            out = board_staff._prepend_scratchpad(task, "BANNER-HERE")  # noqa: SLF001
        self.assertEqual(out, "BANNER-HERE")
        self.assertNotIn("old notes", out)
        with patch.object(board_staff, "BOARD_STAFF_SCRATCHPAD_MAX_CHARS", 8):
            trimmed = board_staff._prepend_scratchpad(task, "BANNER-HERE")  # noqa: SLF001
        self.assertEqual(trimmed, "BANNER-H")
        self.assertLessEqual(len(trimmed), 8)

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
        self.assertIn("task_request_help", task)
        self.assertNotIn("task_request_help", chat)
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
        self.assertEqual(names, ["task_note", "task_finish", "task_request_help"])

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

    def test_minutes_assign_reuses_overlapping_open_task(self) -> None:
        settings = _enable_staff(self.table)
        settings["tools"]["globalMode"] = "propose"
        board_store.save_settings(self.table, settings)
        board_store.save_staff_override(self.table, "prospector", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            existing = board_staff.create_task(
                self.table,
                settings,
                assignee="prospector",
                origin="owner",
                brief="Call 10 activity providers\nDone looks like: Book calls.",
                deliverable_type="markdown",
                created_by="a",
            )
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=board_store.load_settings(self.table),
            persona_id="ceo",
            display_name="CEO",
            kind="meeting",
            meeting_id="m1",
            actor="persona",
        )
        outcome = board_tools.execute_call(
            ctx,
            board_tools.REGISTRY["staff_assign"],
            {
                "assignee": "prospector",
                "brief": "Call 10 activity providers\nDone looks like: Book calls.",
                "deliverableType": "markdown",
                "reason": "Assigned in the board minutes.",
            },
        )
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(outcome.result.get("taskId"), existing["taskId"])
        self.assertEqual([a for a in board_store.list_approvals(self.table) if a.get("status") == "pending"], [])


class StaffHelpTests(ToolsTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        patcher = patch.object(board_async, "invoke_async", side_effect=lambda payload, fallback=None: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_help_in_flight_and_json_brief_regexes(self) -> None:
        help_re = board_staff._HELP_IN_FLIGHT_RE  # noqa: SLF001
        self.assertTrue(help_re.search("help is in flight"))
        self.assertTrue(help_re.search("help request is still in flight"))
        self.assertTrue(help_re.search("Help request in flight."))
        self.assertFalse(help_re.search("opened a help request yesterday"))
        json_re = board_staff._JSON_BRIEF_RE  # noqa: SLF001
        self.assertFalse(json_re.search("Read the config in JSON and summarise in markdown."))
        self.assertFalse(json_re.search("Summarise contracts/board-staff.json for the founder."))
        self.assertTrue(json_re.search("Return a valid JSON object"))
        self.assertTrue(json_re.search("deliver the answer as JSON"))

    def _support_task(self, brief: str = "Verify analytics and tracking setup for visitor source measurement") -> tuple[dict[str, Any], dict[str, Any]]:
        settings = _enable_staff(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(
                self.table,
                settings,
                assignee="support",
                origin="owner",
                brief=brief,
                deliverable_type="markdown",
                created_by="admin",
            )
        return board_store.get_task(self.table, task["taskId"]) or task, settings

    def _help_ctx(self, task: dict[str, Any], settings: dict[str, Any], *, actor: str = "persona") -> board_tools.ToolContext:
        return board_tools.ToolContext(
            table=self.table,
            settings=settings,
            persona_id="coo",
            display_name="Support",
            kind="task",
            task_id=str(task["taskId"]),
            seat_id="support",
            actor=actor,
            owner_sub="owner-1" if actor == "owner" else "",
        )

    def test_finish_blocks_help_in_flight_memo(self) -> None:
        task, settings = self._support_task()
        board_store.claim_task_step(self.table, task["taskId"], 0)
        latest = board_store.get_task(self.table, task["taskId"])
        latest["status"] = "running"
        latest["helpTaskIds"] = ["child-help"]
        board_store.put_task(self.table, latest)
        board_store.put_task(
            self.table,
            {
                "taskId": "child-help",
                "status": "running",
                "parentTaskId": task["taskId"],
                "assignee": "data-analyst",
                "origin": "task",
            },
        )
        ctx = self._help_ctx(latest, settings)
        with self.assertRaises(board_staff.StaffError) as raised:
            board_staff.op_task_finish(
                ctx,
                {
                    "summary": "waiting",
                    "deliverable": "help request is still in flight",
                    "deliverableType": "markdown",
                    "evidence": [],
                    "confidence": "low",
                },
            )
        self.assertIn("wait for the help task", str(raised.exception))
        self.assertEqual(board_store.get_task(self.table, task["taskId"])["status"], "running")

    def test_finish_allows_short_pr_memo_after_refused_help(self) -> None:
        task, settings = self._support_task("Open a draft PR for the booking form.")
        board_store.claim_task_step(self.table, task["taskId"], 0)
        board_store.add_tool_call(
            self.table,
            {
                "callId": "help-refused",
                "op": "task_request_help",
                "status": "error",
                "taskId": task["taskId"],
            },
        )
        ctx = self._help_ctx(board_store.get_task(self.table, task["taskId"]), settings)
        with self.assertRaises(board_staff.StaffError) as waiting:
            board_staff.op_task_finish(
                ctx,
                {
                    "summary": "waiting",
                    "deliverable": "help is in flight",
                    "deliverableType": "markdown",
                    "evidence": [],
                    "confidence": "low",
                },
            )
        self.assertIn("wait for the help task", str(waiting.exception))
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            out = board_staff.op_task_finish(
                ctx,
                {
                    "summary": "opened",
                    "deliverable": "PR #7 opened, CI green.",
                    "deliverableType": "pr",
                    "evidence": [],
                    "confidence": "medium",
                },
            )
        self.assertEqual(out["status"], "review")

    def test_json_filename_in_brief_does_not_require_json_deliverable(self) -> None:
        settings = _enable_staff(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_staff.create_task(
                self.table,
                settings,
                assignee="support",
                origin="owner",
                brief="Read the config in JSON and summarise in markdown.",
                deliverable_type="markdown",
                created_by="a",
            )
        board_store.claim_task_step(self.table, task["taskId"], 0)
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=settings,
            persona_id="coo",
            kind="task",
            task_id=task["taskId"],
        )
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            out = board_staff.op_task_finish(
                ctx,
                {
                    "summary": "notes",
                    "deliverable": "The staff contract lists seats and step limits.",
                    "deliverableType": "markdown",
                    "evidence": [],
                    "confidence": "low",
                },
            )
        self.assertEqual(out["status"], "review")

    def test_page_fetch_help_remaps_web_to_research(self) -> None:
        settings = _enable_staff(self.table)
        parent = {"assignee": "community-manager", "managerId": "cmo"}
        assignee, kind = board_staff.pick_helper(self.table, settings, parent, ["research"])
        self.assertEqual(kind, "seat")
        self.assertNotEqual(assignee, "community-manager")
        remapped = board_staff._remap_help_tool_ids(["web"], "Fetch official LCSD pages")  # noqa: SLF001
        self.assertEqual(remapped, ["research"])
        self.assertEqual(board_staff._remap_help_tool_ids(["web"], "GA4 sessions this week"), ["web"])  # noqa: SLF001

    def test_pick_helper_prefers_read_only_web_seat(self) -> None:
        settings = _enable_staff(self.table)
        parent = {"assignee": "support", "managerId": "coo"}
        assignee, kind = board_staff.pick_helper(self.table, settings, parent, ["web"])
        self.assertEqual(kind, "seat")
        self.assertEqual(assignee, "data-analyst")
        assignee, kind = board_staff.pick_helper(
            self.table, settings, parent, ["web"], suggested="business-analyst"
        )
        self.assertEqual(assignee, "business-analyst")

    def test_request_help_proposes_then_child_feeds_parent(self) -> None:
        task, settings = self._support_task()
        ctx = self._help_ctx(task, settings)
        outcome = board_tools.execute_call(
            ctx,
            board_tools.REGISTRY["task_request_help"],
            {
                "need": "GA4 sessions and referrers for visitor sources",
                "toolIds": ["web"],
                "reason": "Support was not offered web reads",
            },
        )
        self.assertEqual(outcome.status, "pending_approval", outcome.result)
        self.assertTrue(outcome.approval_id)
        board_staff._park_waiting_approval(self.table, task, [outcome.approval_id])  # noqa: SLF001
        parked = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(parked["status"], "waiting_approval")
        decided = board_tools.decide_approval(
            self.table, settings, outcome.approval_id, approve=True, owner_sub="owner-1"
        )
        self.assertEqual(decided["status"], "executed", decided)
        self.assertIn("data-analyst", str(decided.get("summary") or ""))
        parent = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(parent["status"], "waiting_subtask")
        child_id = parent["helpTaskIds"][0]
        child = board_store.get_task(self.table, child_id)
        self.assertEqual(child["origin"], "task")
        self.assertEqual(child["parentTaskId"], task["taskId"])
        self.assertEqual(child["assignee"], "data-analyst")
        self.assertFalse(child.get("actionId"))
        board_store.add_tool_call(
            self.table,
            {
                "callId": "web-1",
                "op": "web_sessions",
                "summary": "12 sessions, google / organic",
                "context": {"taskId": child_id},
                "taskId": child_id,
                "status": "ok",
            },
        )
        child["deliverableKey"] = board_staff._deliverable_key(child_id, "markdown")  # noqa: SLF001
        board_staff._blob_put(child["deliverableKey"], b"GA4 connected. 12 sessions from google/organic.")  # noqa: SLF001
        child["summary"] = "GA4 sessions look live"
        child["evidence"] = ["web-1"]
        board_store.put_task(self.table, child)
        board_staff._accept_task(self.table, child, board_store.now_iso())  # noqa: SLF001
        parent = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(parent["status"], "running")
        scratch = board_staff._blob_get(parent["scratchpadKey"]).decode()  # noqa: SLF001
        self.assertIn("HELP FROM data-analyst", scratch)
        self.assertIn("12 sessions", scratch)
        self.assertIn("EVIDENCE: web-1 (web_sessions)", scratch)
        child_ctx = board_tools.ToolContext(
            table=self.table,
            settings=settings,
            persona_id="coo",
            display_name="Support",
            kind="task",
            task_id=str(parent["taskId"]),
            seat_id="support",
            actor="persona",
        )
        fetched = board_staff.op_staff_get_deliverable(child_ctx, {"taskId": child_id})
        self.assertEqual(fetched["evidence"], ["web-1"])
        self.assertEqual(fetched["evidenceCalls"][0]["op"], "web_sessions")
        parent_ctx = self._help_ctx(parent, settings)
        with self.assertRaises(board_staff.StaffError) as missing:
            board_staff.op_task_finish(
                parent_ctx,
                {
                    "summary": "Tried to finish without citing help.",
                    "deliverableType": "markdown",
                    "deliverable": "GA4 is connected.",
                    "evidence": [],
                    "openQuestions": [],
                    "confidence": "medium",
                },
            )
        self.assertIn("EVIDENCE", str(missing.exception))
        cited = [
            line.split()[1]
            for line in scratch.splitlines()
            if line.startswith("EVIDENCE:")
        ]
        self.assertEqual(cited, ["web-1"])
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_staff.op_task_finish(
                parent_ctx,
                {
                    "summary": "Visitor sources verified via data-analyst.",
                    "deliverableType": "markdown",
                    "deliverable": "GA4 is connected. Sources: google/organic.",
                    "evidence": cited,
                    "openQuestions": [],
                    "confidence": "high",
                },
            )
        finished = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(finished["status"], "review")
        self.assertEqual(finished["evidence"], ["web-1"])

    def test_request_help_act_creates_child_without_approval(self) -> None:
        task, settings = self._support_task()
        settings["tools"]["globalMode"] = "act"
        settings["tools"]["matrix"]["staff"]["coo"] = "act"
        board_store.save_settings(self.table, settings)
        settings = board_store.load_settings(self.table)
        ctx = self._help_ctx(task, settings)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            outcome = board_tools.execute_call(
                ctx,
                board_tools.REGISTRY["task_request_help"],
                {"need": "Sessions by source", "toolIds": ["web"], "reason": "Need GA4"},
            )
        self.assertEqual(outcome.status, "ok", outcome.result)
        parent = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(parent["status"], "waiting_subtask")
        self.assertEqual(board_store.list_approvals(self.table), [])

    def test_reject_help_resumes_parent(self) -> None:
        task, settings = self._support_task()
        ctx = self._help_ctx(task, settings)
        outcome = board_tools.execute_call(
            ctx,
            board_tools.REGISTRY["task_request_help"],
            {"need": "Sessions", "toolIds": ["web"], "reason": "Need GA4"},
        )
        board_staff._park_waiting_approval(self.table, task, [outcome.approval_id])  # noqa: SLF001
        board_tools.decide_approval(
            self.table, settings, outcome.approval_id, approve=False, owner_sub="owner-1"
        )
        parent = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(parent["status"], "running")
        scratch = board_staff._blob_get(parent["scratchpadKey"]).decode()  # noqa: SLF001
        self.assertIn("founder declined", scratch)
        self.assertEqual(int(parent.get("helpRequests") or 0), 1)
        again = board_staff.validate_task_request_help(
            self._help_ctx(parent, settings),
            {"need": "Sessions", "toolIds": ["web"]},
        )
        self.assertIn("already used", again)

    def test_help_refuses_tools_the_seat_already_has(self) -> None:
        task, settings = self._support_task(brief="Reply to the parent")
        reason = board_staff.validate_task_request_help(
            self._help_ctx(task, settings),
            {"need": "Send the reply", "toolIds": ["mail"]},
        )
        self.assertIn("already have those tools", reason)

    def test_help_refuses_when_nobody_covers_the_tools(self) -> None:
        task, settings = self._support_task()
        reason = board_staff.validate_task_request_help(
            self._help_ctx(task, settings),
            {"need": "Dispatch the coding runner", "toolIds": ["code"]},
        )
        self.assertIn("No active seat has those tools", reason)

    def test_help_child_cannot_request_further_help(self) -> None:
        task, settings = self._support_task()
        settings["tools"]["globalMode"] = "act"
        settings["tools"]["matrix"]["staff"]["coo"] = "act"
        board_store.save_settings(self.table, settings)
        settings = board_store.load_settings(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_tools.execute_call(
                self._help_ctx(task, settings),
                board_tools.REGISTRY["task_request_help"],
                {"need": "Sessions", "toolIds": ["web"], "reason": "Need GA4"},
            )
        parent = board_store.get_task(self.table, task["taskId"])
        child = board_store.get_task(self.table, parent["helpTaskIds"][0])
        child_ctx = board_tools.ToolContext(
            table=self.table,
            settings=settings,
            persona_id="cio",
            display_name="Data",
            kind="task",
            task_id=str(child["taskId"]),
            seat_id="data-analyst",
            actor="persona",
        )
        reason = board_staff.validate_task_request_help(
            child_ctx, {"need": "More", "toolIds": ["finance"]}
        )
        self.assertIn("cannot request further help", reason)

    def test_cancel_parent_cancels_open_child(self) -> None:
        task, settings = self._support_task()
        settings["tools"]["globalMode"] = "act"
        settings["tools"]["matrix"]["staff"]["coo"] = "act"
        board_store.save_settings(self.table, settings)
        settings = board_store.load_settings(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_tools.execute_call(
                self._help_ctx(task, settings),
                board_tools.REGISTRY["task_request_help"],
                {"need": "Sessions", "toolIds": ["web"], "reason": "Need GA4"},
            )
        parent = board_store.get_task(self.table, task["taskId"])
        child_id = parent["helpTaskIds"][0]
        cancelled = board_staff.cancel_task(self.table, task["taskId"], "owner-1")
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(board_store.get_task(self.table, child_id)["status"], "cancelled")
        self.assertEqual(board_store.get_task(self.table, task["taskId"])["status"], "cancelled")

    def test_waiting_subtask_expires(self) -> None:
        task, settings = self._support_task()
        settings["tools"]["globalMode"] = "act"
        settings["tools"]["matrix"]["staff"]["coo"] = "act"
        board_store.save_settings(self.table, settings)
        settings = board_store.load_settings(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_tools.execute_call(
                self._help_ctx(task, settings),
                board_tools.REGISTRY["task_request_help"],
                {"need": "Sessions", "toolIds": ["web"], "reason": "Need GA4"},
            )
        parent = board_store.get_task(self.table, task["taskId"])
        child_id = parent["helpTaskIds"][0]
        parent["parkedAt"] = "2000-01-01T00:00:00Z"
        parent["updatedAt"] = board_store.now_iso()
        board_store.put_task(self.table, parent)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            expired = board_staff.expire_waiting_help(self.table, settings)
        self.assertGreaterEqual(expired, 1)
        self.assertEqual(board_store.get_task(self.table, child_id)["status"], "cancelled")
        resumed = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(resumed["status"], "running")
        scratch = board_staff._blob_get(resumed["scratchpadKey"]).decode()  # noqa: SLF001
        self.assertIn("no answer", scratch)

    def test_help_available_line_lists_missing_tools(self) -> None:
        task, settings = self._support_task()
        line = board_staff.help_available_line(self.table, settings, task)
        self.assertIn("data-analyst", line)
        self.assertIn("web", line)
        self.assertIn("task_request_help", line)
        self.assertNotIn("board,", line)
        self.assertNotIn("staff)", line)
        self.assertNotIn("(board)", line)

    def test_child_failure_resumes_parent(self) -> None:
        task, settings = self._support_task()
        settings["tools"]["globalMode"] = "act"
        settings["tools"]["matrix"]["staff"]["coo"] = "act"
        board_store.save_settings(self.table, settings)
        settings = board_store.load_settings(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_tools.execute_call(
                self._help_ctx(task, settings),
                board_tools.REGISTRY["task_request_help"],
                {"need": "Sessions", "toolIds": ["web"], "reason": "Need GA4"},
            )
        parent = board_store.get_task(self.table, task["taskId"])
        child = board_store.get_task(self.table, parent["helpTaskIds"][0])
        board_staff._finish_incomplete(self.table, child, "step error")  # noqa: SLF001
        resumed = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(resumed["status"], "running")
        scratch = board_staff._blob_get(resumed["scratchpadKey"]).decode()  # noqa: SLF001
        self.assertIn("help unavailable", scratch)

    def _act_help(self, brief: str = "Verify analytics and tracking setup for visitor source measurement") -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        task, settings = self._support_task(brief=brief)
        settings["tools"]["globalMode"] = "act"
        settings["tools"]["matrix"]["staff"]["coo"] = "act"
        board_store.save_settings(self.table, settings)
        settings = board_store.load_settings(self.table)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_tools.execute_call(
                self._help_ctx(task, settings),
                board_tools.REGISTRY["task_request_help"],
                {"need": "Sessions", "toolIds": ["web"], "reason": "Need GA4"},
            )
        parent = board_store.get_task(self.table, task["taskId"])
        child = board_store.get_task(self.table, parent["helpTaskIds"][0])
        return parent, child, settings

    def test_finish_refused_while_waiting_on_help(self) -> None:
        parent, child, settings = self._act_help()
        with self.assertRaises(board_staff.StaffError) as cm:
            board_staff.op_task_finish(
                self._help_ctx(parent, settings),
                {
                    "summary": "Skipping the helper",
                    "deliverableType": "markdown",
                    "deliverable": "Unable to verify.",
                    "evidence": [],
                    "openQuestions": [],
                    "confidence": "low",
                },
            )
        self.assertIn("waiting_subtask", str(cm.exception))
        self.assertNotIn(board_store.get_task(self.table, child["taskId"])["status"], {"cancelled", "delivered", "failed"})
        self.assertEqual(board_store.get_task(self.table, parent["taskId"])["status"], "waiting_subtask")

    def test_child_needs_owner_keeps_parent_parked(self) -> None:
        parent, child, settings = self._act_help()
        child["revisions"] = BOARD_STAFF_MAX_REVISIONS
        child["status"] = "review"
        board_store.put_task(self.table, child)
        board_staff.apply_review(
            self.table,
            settings,
            child,
            verdict="return",
            notes="Still no GA4 proof.",
            by="cio",
        )
        child = board_store.get_task(self.table, child["taskId"])
        self.assertEqual(child["status"], "needs_owner")
        parked = board_store.get_task(self.table, parent["taskId"])
        self.assertEqual(parked["status"], "waiting_subtask")
        self.assertIn("founder review", parked.get("parkedReason") or "")
        scratch = board_staff._blob_get(parked["scratchpadKey"]).decode()  # noqa: SLF001
        self.assertIn("waiting for founder review", scratch)
        parked["parkedAt"] = "2000-01-01T00:00:00Z"
        parked["updatedAt"] = "2000-01-01T00:00:00Z"
        board_store.put_task(self.table, parked)
        expired = board_staff.expire_waiting_help(self.table, settings)
        self.assertEqual(expired, 0)
        self.assertEqual(board_store.get_task(self.table, child["taskId"])["status"], "needs_owner")
        self.assertEqual(board_store.get_task(self.table, parent["taskId"])["status"], "waiting_subtask")

    def test_failed_help_approval_resumes_parent(self) -> None:
        task, settings = self._support_task()
        ctx = self._help_ctx(task, settings)
        outcome = board_tools.execute_call(
            ctx,
            board_tools.REGISTRY["task_request_help"],
            {"need": "Sessions", "toolIds": ["web"], "reason": "Need GA4"},
        )
        board_staff._park_waiting_approval(self.table, task, [outcome.approval_id])  # noqa: SLF001
        for seat_id in ("data-analyst", "community-manager", "business-analyst"):
            board_store.save_staff_override(self.table, seat_id, {"isActive": False})
        settings = board_store.load_settings(self.table)
        decided = board_tools.decide_approval(
            self.table, settings, outcome.approval_id, approve=True, owner_sub="owner-1"
        )
        self.assertEqual(decided["status"], "failed", decided)
        parent = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(parent["status"], "running")
        self.assertEqual(int(parent.get("helpRequests") or 0), 1)
        scratch = board_staff._blob_get(parent["scratchpadKey"]).decode()  # noqa: SLF001
        self.assertIn("help request failed", scratch)
        again = board_staff.validate_task_request_help(
            self._help_ctx(parent, settings),
            {"need": "Sessions", "toolIds": ["web"]},
        )
        self.assertIn("already used", again)

    def test_expired_help_approval_is_rejected(self) -> None:
        task, settings = self._support_task()
        ctx = self._help_ctx(task, settings)
        outcome = board_tools.execute_call(
            ctx,
            board_tools.REGISTRY["task_request_help"],
            {"need": "Sessions", "toolIds": ["web"], "reason": "Need GA4"},
        )
        board_staff._park_waiting_approval(self.table, task, [outcome.approval_id])  # noqa: SLF001
        parked = board_store.get_task(self.table, task["taskId"])
        parked["parkedAt"] = "2000-01-01T00:00:00Z"
        board_store.put_task(self.table, parked)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            expired = board_staff.expire_waiting_help(self.table, settings)
        self.assertGreaterEqual(expired, 1)
        approval = board_store.get_approval(self.table, outcome.approval_id)
        self.assertEqual(approval["status"], "rejected")
        self.assertEqual(approval.get("decidedBySub"), "system:expiry")
        resumed = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(resumed["status"], "running")
        self.assertEqual(int(resumed.get("helpRequests") or 0), 1)
        with self.assertRaises(ValueError):
            board_tools.decide_approval(
                self.table, settings, outcome.approval_id, approve=True, owner_sub="owner-1"
            )

    def test_updated_at_does_not_extend_help_wait(self) -> None:
        parent, child, settings = self._act_help()
        parent["parkedAt"] = board_store.now_iso()
        parent["updatedAt"] = "2000-01-01T00:00:00Z"
        board_store.put_task(self.table, parent)
        expired = board_staff.expire_waiting_help(self.table, settings)
        self.assertEqual(expired, 0)
        self.assertEqual(board_store.get_task(self.table, parent["taskId"])["status"], "waiting_subtask")
        self.assertNotIn(board_store.get_task(self.table, child["taskId"])["status"], {"cancelled", "delivered", "failed"})

    def test_help_refuses_internal_tool_ids(self) -> None:
        task, settings = self._support_task()
        reason = board_staff.validate_task_request_help(
            self._help_ctx(task, settings),
            {"need": "Read board records", "toolIds": ["board", "staff"]},
        )
        self.assertIn("toolIds must be one or more board tools", reason)

    def test_pick_helper_falls_back_to_manager_persona(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "business-analyst", {"isActive": False})
        parent = {"assignee": "support", "managerId": "coo"}
        assignee, kind = board_staff.pick_helper(self.table, settings, parent, ["finance"])
        self.assertEqual(kind, "persona")
        self.assertEqual(assignee, "coo")

    def test_waiting_subtask_blocks_second_hand_off(self) -> None:
        _enable_staff(self.table)
        action = {
            "actionId": board_store.new_id(),
            "title": "Verify visitor sources",
            "status": "open",
            "assignee": "support",
            "createdAt": board_store.now_iso(),
            "updatedAt": board_store.now_iso(),
        }
        board_store.put_action(self.table, action)
        parent, _child, _settings = self._act_help()
        parent["actionId"] = action["actionId"]
        board_store.put_task(self.table, parent)
        action["staffTaskId"] = parent["taskId"]
        board_store.put_action(self.table, action)
        status, body = self.call(
            "/siu-tin-dei/board/tasks",
            "POST",
            {
                "assignee": "support",
                "brief": "Again",
                "deliverableType": "markdown",
                "actionId": action["actionId"],
            },
        )
        self.assertEqual(status, 409, body)


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
