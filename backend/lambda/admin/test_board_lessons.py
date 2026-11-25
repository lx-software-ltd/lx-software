"""Unit tests for Executive Board lessons (WP4)."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import board_budget
import board_lessons
import board_personas
import board_staff
import board_store
from test_board import BoardTestCase


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
        seat = {
            "id": "content-marketer",
            "title": "Content Marketer",
            "displayName": "Content",
            "reportsTo": "cmo",
            "brief": "Write posts.",
        }
        prompt = board_personas.render_seat_prompt(seat, {"displayName": "Maya", "title": "CMO"}, {}, texts)
        self.assertIn("STANDING INSTRUCTIONS FROM THE FOUNDER", prompt)
        self.assertIn("Always name the district and the date.", prompt)

    def test_confirmed_lessons_outlast_a_run_of_newer_unconfirmed_rows(self) -> None:
        clock = iter(f"2026-11-09T08:{minute:02d}:00.000Z" for minute in range(60))

        def write(instruction: str, ref: str) -> dict[str, Any]:
            return board_lessons._write(
                self.table,
                kind="veto",
                subject="content-marketer",
                class_key="publish:instagram",
                what=f"content {ref}",
                instruction=instruction,
                source_ref=ref,
            )

        with patch.object(board_store, "now_iso", side_effect=lambda: next(clock)):
            kept = write("One real Stanley listing per post.", "kept")
            for index in range(20):
                write(f"Unconfirmed draft {index}.", f"noise-{index}")
        board_lessons.confirm(self.table, kept["lessonId"])
        self.assertEqual(
            board_staff._confirmed_lessons(self.table, "content-marketer"),
            ["One real Stanley listing per post."],
        )

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
                {
                    "taskId": "t1",
                    "assignee": "support",
                    "brief": "Reply to parent",
                    "lastReview": {"notes": "Need the catalog fact"},
                },
            )
        self.assertEqual(from_call["kind"], "correction")
        self.assertEqual(from_task["kind"], "return")
        board_lessons.dismiss(self.table, from_call["lessonId"])
        dismissed = board_store.get_lesson(self.table, from_call["lessonId"])
        assert dismissed is not None
        self.assertTrue(dismissed.get("dismissed"))

    def test_a_second_veto_in_the_hour_updates_the_draft(self) -> None:
        class Fake:
            text = '{"instruction":"Do not repeat this class."}'

        first = {
            "holdId": "h1",
            "op": "content_publish",
            "classKey": "publish:facebook",
            "seatId": "content-marketer",
            "summary": "Post one",
            "vetoReason": "paused",
        }
        second = {**first, "holdId": "h2", "summary": "Post two"}
        with (
            patch.object(board_budget, "board_completion", return_value=Fake()),
            patch.object(board_budget, "model_for", return_value="desk"),
        ):
            created = board_lessons.create_from_veto(self.table, first, class_once=True)
            updated = board_lessons.create_from_veto(self.table, second, class_once=True)
        self.assertEqual(created["lessonId"], updated["lessonId"])
        self.assertIn("Post two", updated["what"])
        rows = [row for row in board_lessons.list_lessons(self.table, "content-marketer") if row.get("kind") == "veto"]
        self.assertEqual(len(rows), 1)

    def test_two_ordinary_vetoes_stay_two_lessons(self) -> None:
        class Fake:
            text = '{"instruction":"Do not repeat this."}'

        first = {
            "holdId": "h1",
            "op": "mail_send",
            "classKey": "cold_outreach:provider",
            "seatId": "provider-success",
            "summary": "First letter",
        }
        second = {**first, "holdId": "h2", "summary": "Second letter"}
        with (
            patch.object(board_budget, "board_completion", return_value=Fake()),
            patch.object(board_budget, "model_for", return_value="desk"),
        ):
            board_lessons.create_from_veto(self.table, first)
            board_lessons.create_from_veto(self.table, second)
        rows = [row for row in board_lessons.list_lessons(self.table, "provider-success") if row.get("kind") == "veto"]
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
