"""Unit tests for Executive Board daily review (WP4)."""

from __future__ import annotations

import os
import unittest
from datetime import timedelta
from typing import Any
from unittest.mock import patch

from test_board import BoardTestCase

import board_code
import board_github
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
        with patch.object(board_github, "_request", side_effect=AssertionError("compile must not call GitHub")):
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
        self.assertIn("digestHtml", review)
        self.assertIn("Headline numbers", review["digestHtml"])
        self.assertNotIn("section=review#", review["digestHtml"])

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

    def test_digest_html_inlines_section_summaries_not_spa_links(self) -> None:
        date = "2026-09-09"
        review = {
            "date": date,
            "narrative": "Quiet morning.",
            "headline": {
                "tasks": {"delivered": 1, "running": 0, "blocked": 0},
                "holds": {"executed": 1, "vetoed": 0},
                "spend": {"staffUsd": 1, "budgetUsd": 20},
                "messagesByChannel": {"mail": 2},
            },
            "holdsDue": [
                {
                    "summary": "Propose Page post",
                    "classKey": "publish:facebook",
                    "executeAt": "2026-09-09T10:00:00+08:00",
                    "preview": {"text": "Saturday swimming"},
                }
            ],
            "escalations": [
                {
                    "taskId": "t1",
                    "assignee": "support",
                    "brief": "Parent asked about a refund.",
                    "suggestedReply": {"summary": "Offer a credit"},
                }
            ],
            "assisted": [{"channel": "assisted_xiaohongshu", "slotAt": "2026-09-09T12:00:00", "copyZh": "沙田週末"}],
            "sample": [{"callId": "c1", "summary": "Replied to a parent", "op": "mail_reply"}],
            "market": {
                "changes": [{"summary": "Saturday class price rose."}],
                "latestBrief": {"summary": "Weekly market brief"},
            },
            "breakers": [{"name": "tool:task", "tripped": True, "reason": "too many failures"}],
            "suggestions": [{"classKey": "publish:facebook", "actions": 32, "rate": 0}],
            "promotion": {"behindBy": 0, "commits": [{"sha": "abcdef12", "message": "fix booking copy"}]},
        }
        html = board_review.render_digest_html(review)
        text = board_review.render_digest_text(review)
        self.assertNotIn("section=review#", html)
        self.assertNotIn("http", html)
        for title in board_review.SECTION_LABELS.values():
            self.assertIn(title, html)
            self.assertIn(title, text)
        self.assertIn("Quiet morning.", html)
        self.assertIn("Delivered 1", html)
        self.assertIn("Propose Page post", html)
        self.assertIn("Parent asked about a refund", html)
        self.assertIn("Offer a credit", html)
        self.assertIn("Replied to a parent", html)
        self.assertIn("tool:task", html)
        self.assertIn("fix booking copy", html)
        self.assertIn("Saturday class price rose.", text)

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

        staging = {"behindBy": 0, "aheadBy": 1, "commits": [{"sha": "abcdef12", "message": "fix booking copy"}]}
        with patch.object(board_mail, "sending_enabled", return_value=True), patch.object(
            board_mail, "send_plan", side_effect=fake_send
        ), patch.object(board_code, "staging_preview", return_value=staging) as preview:
            result = board_review.send_digest(self.table, self.settings, review)
        self.assertTrue(result.get("ok"))
        self.assertEqual(preview.call_count, 1)
        self.assertEqual(captured["plan"]["fromMailbox"], "board")
        self.assertEqual(captured["plan"]["to"], ["founder@example.com"])
        self.assertIn("Headline numbers", captured["plan"]["html"])
        self.assertIn("fix booking copy", captured["plan"]["html"])
        self.assertNotIn("section=review#", captured["plan"]["html"])
        self.assertIn("Headline numbers", captured["plan"]["text"])
        self.assertIn("fix booking copy", captured["plan"]["text"])

    def test_send_digest_reports_staging_error_inline(self) -> None:
        self.settings["review"] = board_store.normalize_review_config({"digestTo": "founder@example.com"})
        review = board_review.compile(self.table, self.settings, "2026-09-09")
        captured: dict[str, Any] = {}

        def fake_send(table: Any, plan: dict[str, Any], *, sent_by: str) -> dict[str, Any]:
            captured["plan"] = plan
            return {"ok": True}

        with patch.object(board_mail, "sending_enabled", return_value=True), patch.object(
            board_mail, "send_plan", side_effect=fake_send
        ), patch.object(board_code, "staging_preview", side_effect=RuntimeError("boom")):
            board_review.send_digest(self.table, self.settings, review)
        self.assertIn("staging check failed", captured["plan"]["text"])

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
