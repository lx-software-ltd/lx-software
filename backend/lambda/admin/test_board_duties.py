"""Unit tests for Executive Board seat duties and ops triage (WP9)."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from test_board import BoardTestCase

import board_async
import board_duties
import board_hk
import board_meeting
import board_receivables
import board_review
import board_staff
import board_store
from contract_constants import BOARD_STAFF_SEATS


BA_KPI = "0 8 * * MON"
ACCOUNTANT_MONTH = "0 9 1 * *"
# Monday 2026-09-07 08:10 HKT == 00:10 UTC. July dates stay UTC+8 (no DST).
MONDAY_HKT = board_hk.HKT
JULY_MONDAY_UTC = datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc)  # 08:00 HKT
SEPT_MONDAY_0810_HKT = datetime(2026, 9, 7, 8, 10, tzinfo=MONDAY_HKT)
SEPT_FIRST_0900_HKT = datetime(2026, 9, 1, 9, 0, tzinfo=MONDAY_HKT)
SEPT_FIRST_0100_UTC = datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc)  # 09:00 HKT


def _enable_staff(table: Any, **staff: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config(
        {**(settings.get("staff") or {}), "enabled": True, "dutiesEnabled": True, **staff}
    )
    return board_store.save_settings(table, settings)


def _seed_duties_current(table: Any, now: datetime) -> None:
    for seat in BOARD_STAFF_SEATS:
        seat_id = str(seat.get("id") or "")
        for duty in seat.get("duties") or []:
            cron = str(duty.get("cron") or "")
            duty_id = str(duty.get("id") or "")
            if not cron or not duty_id:
                continue
            scheduled = board_duties.last_scheduled(cron, now)
            board_store.put_cache(
                table,
                f"duty:{seat_id}:{duty_id}",
                {
                    "ranAt": board_hk.to_iso(now),
                    "scheduledAt": board_hk.to_iso(scheduled or now),
                    "taskId": "seeded",
                },
            )


class CronArithmeticTests(unittest.TestCase):
    def test_monday_utc_midnight_is_hkt_0800(self) -> None:
        parsed = board_duties.parse_cron(BA_KPI)
        self.assertTrue(board_duties.matches(parsed, JULY_MONDAY_UTC))
        local = board_hk.as_hkt(JULY_MONDAY_UTC)
        self.assertEqual((local.weekday(), local.hour, local.minute), (0, 8, 0))

    def test_july_stays_plus_eight_no_dst(self) -> None:
        winter = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)  # Monday
        summer = JULY_MONDAY_UTC
        self.assertEqual(board_hk.as_hkt(winter).utcoffset(), board_hk.as_hkt(summer).utcoffset())
        self.assertEqual(board_hk.as_hkt(summer).hour, 8)

    def test_month_end_is_first_of_month_hkt_not_utc(self) -> None:
        parsed = board_duties.parse_cron(ACCOUNTANT_MONTH)
        self.assertTrue(board_duties.matches(parsed, SEPT_FIRST_0900_HKT))
        self.assertTrue(board_duties.matches(parsed, SEPT_FIRST_0100_UTC))
        # 00:00 UTC on the 1st is still 08:00 HKT — not yet 09:00.
        too_early_utc = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(board_duties.matches(parsed, too_early_utc))
        last = board_duties.last_scheduled(ACCOUNTANT_MONTH, too_early_utc)
        self.assertIsNotNone(last)
        self.assertEqual(board_hk.as_hkt(last).day, 1)
        self.assertEqual(board_hk.as_hkt(last).month, 8)

    def test_unix_dow_sunday_is_zero_or_seven(self) -> None:
        sunday = datetime(2026, 9, 6, 9, 0, tzinfo=MONDAY_HKT)
        self.assertTrue(board_duties.matches(board_duties.parse_cron("0 9 * * 0"), sunday))
        self.assertTrue(board_duties.matches(board_duties.parse_cron("0 9 * * 7"), sunday))
        self.assertTrue(board_duties.matches(board_duties.parse_cron("0 9 * * SUN"), sunday))

    def test_is_due_when_last_run_is_before_most_recent_scheduled(self) -> None:
        now = SEPT_MONDAY_0810_HKT
        scheduled = board_duties.last_scheduled(BA_KPI, now)
        self.assertEqual(board_hk.as_hkt(scheduled).isoformat(), "2026-09-07T08:00:00+08:00")
        self.assertTrue(board_duties.is_due(BA_KPI, "", now))
        prev = board_hk.to_iso(datetime(2026, 8, 31, 8, 0, tzinfo=MONDAY_HKT))
        self.assertTrue(board_duties.is_due(BA_KPI, prev, now))
        self.assertFalse(board_duties.is_due(BA_KPI, board_hk.to_iso(scheduled), now))


class DutyRunTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        patcher = patch.object(board_async, "invoke_async", side_effect=lambda payload, *, fallback=None: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.settings = _enable_staff(self.table)

    def test_duties_disabled_creates_nothing(self) -> None:
        settings = _enable_staff(self.table, dutiesEnabled=False)
        created = board_duties.run_due(self.table, settings, now=SEPT_MONDAY_0810_HKT)
        self.assertEqual(created, [])

    def test_staff_off_creates_nothing(self) -> None:
        settings = _enable_staff(self.table)
        settings["staff"]["enabled"] = False
        board_store.save_settings(self.table, settings)
        created = board_duties.run_due(self.table, settings, now=SEPT_MONDAY_0810_HKT)
        self.assertEqual(created, [])

    def test_kpi_duty_is_idempotent_on_the_same_monday(self) -> None:
        now = SEPT_MONDAY_0810_HKT
        _seed_duties_current(self.table, now)
        board_store.put_cache(self.table, "duty:business-analyst:weekly-kpi-pack", {})
        first = board_duties.run_due(self.table, self.settings, now=now)
        again = board_duties.run_due(self.table, self.settings, now=now)
        kpi = [t for t in first if (t.get("eventRef") or {}).get("id") == "business-analyst:weekly-kpi-pack:2026-09-07"]
        self.assertEqual(len(kpi), 1)
        self.assertEqual(kpi[0]["assignee"], "business-analyst")
        self.assertEqual(kpi[0]["origin"], "duty")
        self.assertEqual(again, [])

    def test_missed_tick_catches_up_once(self) -> None:
        now = SEPT_MONDAY_0810_HKT
        _seed_duties_current(self.table, now)
        prev = board_hk.to_iso(datetime(2026, 8, 31, 8, 0, tzinfo=MONDAY_HKT))
        board_store.put_cache(
            self.table,
            "duty:business-analyst:weekly-kpi-pack",
            {"scheduledAt": prev, "ranAt": prev, "taskId": "old"},
        )
        created = board_duties.run_due(self.table, self.settings, now=now)
        ids = [(t.get("eventRef") or {}).get("id") for t in created]
        self.assertIn("business-analyst:weekly-kpi-pack:2026-09-07", ids)
        again = board_duties.run_due(self.table, self.settings, now=now)
        self.assertEqual(again, [])

    def test_month_end_memo_fires_on_first_at_0900_hkt(self) -> None:
        now = SEPT_FIRST_0900_HKT
        _seed_duties_current(self.table, now)
        board_store.put_cache(self.table, "duty:accountant:month-end-memo", {})
        created = board_duties.run_due(self.table, self.settings, now=now)
        ids = [(t.get("eventRef") or {}).get("id") for t in created]
        self.assertIn("accountant:month-end-memo:2026-09-01", ids)

    def test_inactive_seat_is_skipped(self) -> None:
        now = SEPT_MONDAY_0810_HKT
        board_store.save_staff_override(self.table, "business-analyst", {"isActive": False})
        _seed_duties_current(self.table, now)
        board_store.put_cache(self.table, "duty:business-analyst:weekly-kpi-pack", {})
        created = board_duties.run_due(self.table, self.settings, now=now)
        ids = [(t.get("eventRef") or {}).get("id") for t in created]
        self.assertNotIn("business-analyst:weekly-kpi-pack:2026-09-07", ids)


class OpsTriageTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        patcher = patch.object(board_async, "invoke_async", side_effect=lambda payload, *, fallback=None: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.settings = _enable_staff(self.table, dutiesEnabled=False)

    def test_new_alarm_goes_to_cto_when_architect_inactive(self) -> None:
        board_store.save_staff_override(self.table, "architect", {"isActive": False})
        board_store.put_cache(
            self.table,
            "aws:alarms",
            {"alarms": [{"name": "lxsoftware-admin-errors", "reason": "threshold"}]},
        )
        out = board_duties.triage_ops_signals(self.table, self.settings)
        self.assertEqual(out["alarms"], 1)
        tasks = [t for t in board_store.list_tasks(self.table, "queued") + board_store.list_tasks(self.table, "running")]
        alarm_tasks = [t for t in tasks if (t.get("eventRef") or {}).get("id") == "alarm:lxsoftware-admin-errors"]
        self.assertEqual(len(alarm_tasks), 1)
        self.assertEqual(alarm_tasks[0]["assignee"], "cto")
        again = board_duties.triage_ops_signals(self.table, self.settings)
        self.assertEqual(again["alarms"], 0)

    def test_active_architect_gets_alarms(self) -> None:
        board_store.save_staff_override(self.table, "architect", {"isActive": True})
        board_store.put_cache(self.table, "aws:alarms", {"alarms": [{"name": "api-5xx", "reason": "5xx"}]})
        board_duties.triage_ops_signals(self.table, self.settings)
        tasks = board_store.list_tasks(self.table, "queued") + board_store.list_tasks(self.table, "running")
        hit = [t for t in tasks if (t.get("eventRef") or {}).get("id") == "alarm:api-5xx"]
        self.assertEqual(hit[0]["assignee"], "architect")

    def test_new_security_alert_goes_to_security_analyst(self) -> None:
        board_store.put_cache(
            self.table,
            "security:findings",
            {"securityHub": {"findings": [{"id": "arn:finding-1", "title": "S3 public"}]}, "accessAnalyzer": {"findings": []}},
        )
        board_store.put_cache(
            self.table,
            "security:github",
            {"dependabot": [{"number": 9, "summary": "lodash"}], "codeScanning": [], "secretScanning": []},
        )
        out = board_duties.triage_ops_signals(self.table, self.settings)
        self.assertEqual(out["alerts"], 2)
        tasks = board_store.list_tasks(self.table, "queued") + board_store.list_tasks(self.table, "running")
        assignees = {t["assignee"] for t in tasks if (t.get("eventRef") or {}).get("kind") == "ops"}
        self.assertEqual(assignees, {"security-analyst"})
        again = board_duties.triage_ops_signals(self.table, self.settings)
        self.assertEqual(again["alerts"], 0)

    def test_staff_off_skips_ops_triage(self) -> None:
        self.settings["staff"]["enabled"] = False
        board_store.save_settings(self.table, self.settings)
        board_store.put_cache(self.table, "aws:alarms", {"alarms": [{"name": "x"}]})
        self.assertEqual(board_duties.triage_ops_signals(self.table, self.settings), {"alarms": 0, "alerts": 0})


class DunningHandOffTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        patcher = patch.object(board_async, "invoke_async", side_effect=lambda payload, *, fallback=None: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.settings = _enable_staff(self.table, dutiesEnabled=False)

    def test_staff_accountant_gets_a_task_not_an_approval(self) -> None:
        aging = {"buckets": {"d7": [{"id": "inv-d7", "number": "STD-2026-0007", "daysOverdue": 7}]}}
        with (
            patch.object(board_receivables, "configured", return_value=True),
            patch.object(board_receivables, "op_aging_report", return_value=aging),
            patch.object(board_store, "records_table", return_value=self.table),
        ):
            first = board_receivables.handle_dunning_trigger({})
            again = board_receivables.handle_dunning_trigger({})
        self.assertEqual(first["created"], 1)
        self.assertEqual(again["created"], 0)
        approvals = [a for a in board_store.list_approvals(self.table) if a.get("op") == "finance_send_reminder"]
        self.assertEqual(approvals, [])
        tasks = board_store.list_tasks(self.table, "queued") + board_store.list_tasks(self.table, "running")
        dunning = [t for t in tasks if (t.get("eventRef") or {}).get("kind") == "dunning"]
        self.assertEqual(len(dunning), 1)
        self.assertEqual(dunning[0]["assignee"], "accountant")
        self.assertEqual(dunning[0]["eventRef"]["id"], "inv-d7:d7")

    def test_staff_off_still_queues_an_approval(self) -> None:
        self.settings["staff"]["enabled"] = False
        board_store.save_settings(self.table, self.settings)
        aging = {"buckets": {"d7": [{"id": "inv-d7", "number": "STD-2026-0007", "daysOverdue": 7}]}}
        with (
            patch.object(board_receivables, "configured", return_value=True),
            patch.object(board_receivables, "op_aging_report", return_value=aging),
            patch.object(board_store, "records_table", return_value=self.table),
        ):
            out = board_receivables.handle_dunning_trigger({})
        self.assertEqual(out["created"], 1)
        pending = [a for a in board_store.list_approvals(self.table) if a.get("op") == "finance_send_reminder"]
        self.assertEqual(len(pending), 1)


class BoundarySuggestionTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.settings = _enable_staff(self.table, dutiesEnabled=False)

    def test_unknown_class_is_dropped_and_known_class_keeps_ramp(self) -> None:
        out = board_duties.validate_boundary_suggestions(
            self.table,
            [
                {"classKey": "publish:facebook", "change": "promote to 0 hours", "evidence": "30 clean posts"},
                {"classKey": "not-a-class:x", "change": "nope", "evidence": "x"},
                {"classKey": "", "change": "empty"},
            ],
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["classKey"], "publish:facebook")
        self.assertEqual(out[0]["source"], "standup")
        self.assertIn("eligibleForPromotion", out[0]["ramp"])

    def test_standup_suggestions_prepend_review_ramp_rows(self) -> None:
        board_store.put_cache(
            self.table,
            "standup:boundary-suggestions",
            {
                "items": [
                    {
                        "classKey": "publish:facebook",
                        "change": "promote to 0 hours",
                        "evidence": "clean week",
                        "source": "standup",
                    }
                ]
            },
        )
        review = board_review.compile(self.table, self.settings, "2026-09-07")
        self.assertEqual(review["suggestions"][0]["source"], "standup")
        self.assertEqual(review["suggestions"][0]["classKey"], "publish:facebook")

    def test_normalize_minutes_keeps_boundary_suggestions(self) -> None:
        minutes = board_meeting.normalize_minutes(
            {
                "headline": "H",
                "boundarySuggestions": [{"classKey": "cold_outreach:provider", "change": "hold 12h", "evidence": "ok"}],
            },
            agenda=[],
            persona_ids={"ceo"},
            default_persona="ceo",
        )
        self.assertEqual(minutes["boundarySuggestions"][0]["classKey"], "cold_outreach:provider")


if __name__ == "__main__":
    unittest.main()
