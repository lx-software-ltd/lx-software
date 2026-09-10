"""Unit tests for Executive Board lessons (WP4)."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from test_board import BoardTestCase

import board_budget
import board_lessons
import board_personas
import board_staff
import board_store


def _enable_staff(table: Any, **staff: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True, **staff})
    return board_store.save_settings(table, settings)


class LessonTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.settings = _enable_staff(self.table)

    def test_veto_draft_and_confirm_renders_into_prompt(self) -> None:
        hold = {
            "holdId": "h1",
            "op": "meta_propose_post",
            "classKey": "publish:facebook",
            "seatId": "content-marketer",
            "personaId": "cmo",
            "summary": "Propose Page post",
            "vetoReason": "Missing the district",
            "preview": {"kind": "post", "text": "Come this weekend"},
        }

        def fake_complete(**kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(text='{"instruction":"Always name the district and the date."}', usage={})

        with patch.object(board_budget, "board_completion", side_effect=fake_complete):
            lesson = board_lessons.create_from_veto(self.table, hold)
        self.assertEqual(lesson["instruction"], "Always name the district and the date.")
        self.assertFalse(lesson["confirmed"])
        board_lessons.confirm(self.table, lesson["lessonId"])
        texts = board_staff._confirmed_lessons(self.table, "content-marketer")
        self.assertIn("Always name the district and the date.", texts)
        seat = {"id": "content-marketer", "title": "Content Marketer", "displayName": "Content", "reportsTo": "cmo", "brief": "Write posts."}
        prompt = board_personas.render_seat_prompt(seat, {"displayName": "Maya", "title": "CMO"}, {}, texts)
        self.assertIn("STANDING INSTRUCTIONS FROM THE FOUNDER", prompt)
        self.assertIn("Always name the district and the date.", prompt)

    def test_correction_and_return(self) -> None:
        board_store.add_tool_call(
            self.table,
            {
                "callId": "call-wrong",
                "op": "mail_reply",
                "toolId": "mail",
                "status": "ok",
                "summary": "Replied too casually",
                "personaId": "support",
                "seatId": "support",
            },
        )

        def fake_complete(**kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(text='{"instruction":"Stay inside the reply policy."}', usage={})

        with patch.object(board_budget, "board_completion", side_effect=fake_complete):
            from_call = board_lessons.create_from_correction(self.table, "call-wrong", "Tone was wrong")
            from_task = board_lessons.create_from_return(
                self.table,
                {"taskId": "t1", "assignee": "support", "brief": "Reply to parent", "lastReview": {"notes": "Need the catalog fact"}},
            )
        self.assertEqual(from_call["kind"], "correction")
        self.assertEqual(from_task["kind"], "return")
        board_lessons.dismiss(self.table, from_call["lessonId"])
        dismissed = board_store.get_lesson(self.table, from_call["lessonId"])
        self.assertTrue(dismissed.get("dismissed"))


if __name__ == "__main__":
    unittest.main()
