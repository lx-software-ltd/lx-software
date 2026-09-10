"""Unit tests for Executive Board daily review (WP4)."""

from __future__ import annotations

import os
import unittest
from datetime import timedelta
from typing import Any
from unittest.mock import patch

from test_board import BoardTestCase

import board_hk
import board_mail
import board_review
import board_staff
import board_store


def _enable_staff(table: Any, **staff: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True, **staff})
    return board_store.save_settings(table, settings)


class ReviewCompileTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.settings = _enable_staff(self.table)

    def test_compile_has_every_section(self) -> None:
        date = board_hk.today_hkt()
        review = board_review.compile(self.table, self.settings, date)
        for key in (
            "headline",
            "holdsDue",
            "escalations",
            "sample",
            "breakers",
            "suggestions",
            "assisted",
            "market",
            "promotion",
            "narrative",
        ):
            self.assertIn(key, review)
        headline = review["headline"]
        self.assertIn("tasks", headline)
        self.assertIn("messagesByChannel", headline)
        self.assertIn("holds", headline)
        self.assertIn("spend", headline)

    def test_sample_is_deterministic_under_seeded_rng(self) -> None:
        yesterday = board_hk.now_hkt() - timedelta(days=1)
        created = board_hk.to_iso(yesterday.replace(hour=12, minute=0, second=0, microsecond=0))
        for i, summary in enumerate(("alpha-reply", "zeta-reply", "mid-reply")):
            board_store.add_tool_call(
                self.table,
                {
                    "callId": f"call-{i}",
                    "op": "mail_reply",
                    "toolId": "mail",
                    "status": "ok",
                    "summary": summary,
                    "createdAt": created,
                    "arguments": {"threadId": f"t{i}", "body": "ok", "reason": "reply"},
                    "personaId": "coo",
                },
            )
        self.settings["review"] = board_store.normalize_review_config({"sampleSize": 2})
        date = board_hk.today_hkt()
        first = board_review.compile(self.table, self.settings, date)["sample"]
        board_store.put_review_snapshot(self.table, date, {})
        second = board_review.compile(self.table, self.settings, date)["sample"]
        self.assertEqual([row["callId"] for row in first], [row["callId"] for row in second])
        self.assertEqual(len(first), 2)

    def test_digest_html_contains_every_section_link(self) -> None:
        date = "2026-09-09"
        review = {
            "date": date,
            "narrative": "Quiet morning.",
            "headline": {"tasks": {"delivered": 1, "running": 0, "blocked": 0}, "spend": {"staffUsd": 1, "budgetUsd": 20}},
        }
        html = board_review.render_digest_html(review)
        for fragment in board_review.SECTION_IDS:
            self.assertIn(f"section=review#{fragment}", html)
            self.assertIn("/siu-tin-dei?tab=board", html)

    def test_send_digest_skips_empty_digest_to(self) -> None:
        review = board_review.compile(self.table, self.settings, board_hk.today_hkt())
        result = board_review.send_digest(self.table, self.settings, review)
        self.assertEqual(result.get("skipped"), "empty digestTo")

    def test_send_digest_skips_when_sending_disabled(self) -> None:
        self.settings["review"] = board_store.normalize_review_config({"digestTo": "founder@example.com"})
        review = {"date": board_hk.today_hkt(), "headline": {}, "narrative": ""}
        os.environ.pop("BOARD_MAIL_SENDING_ENABLED", None)
        result = board_review.send_digest(self.table, self.settings, review)
        self.assertEqual(result.get("skipped"), "sending disabled")

    def test_send_digest_uses_send_plan_when_enabled(self) -> None:
        self.settings["review"] = board_store.normalize_review_config({"digestTo": "founder@example.com"})
        review = board_review.compile(self.table, self.settings, "2026-09-09")
        captured: dict[str, Any] = {}

        def fake_send(table: Any, plan: dict[str, Any], *, sent_by: str) -> dict[str, Any]:
            captured["plan"] = plan
            captured["sent_by"] = sent_by
            return {"ok": True}

        with patch.object(board_mail, "sending_enabled", return_value=True), patch.object(
            board_mail, "send_plan", side_effect=fake_send
        ):
            result = board_review.send_digest(self.table, self.settings, review)
        self.assertTrue(result.get("ok"))
        self.assertEqual(captured["plan"]["fromMailbox"], "board")
        self.assertEqual(captured["plan"]["to"], ["founder@example.com"])
        self.assertIn("headline", captured["plan"]["html"])
        for fragment in board_review.SECTION_IDS:
            self.assertIn(f"#{fragment}", captured["plan"]["html"])

    def test_headline_duty_at_07_00(self) -> None:
        board_store.save_staff_override(self.table, "business-analyst", {"isActive": True})
        fake_now = board_hk.parse_iso("2026-09-09T23:05:00Z")  # 07:05 HKT
        with patch.object(board_hk, "now_hkt", return_value=board_hk.as_hkt(fake_now)):
            task = board_review.maybe_create_headline_duty(self.table, self.settings)
        self.assertIsNotNone(task)
        self.assertEqual(task["assignee"], "business-analyst")
        self.assertEqual(task["origin"], "duty")
        self.assertIn("three-sentence headline", task["brief"])


if __name__ == "__main__":
    unittest.main()
