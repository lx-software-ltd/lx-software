"""JSON preview on a finished-task sample row."""

from __future__ import annotations

import json
import os
from typing import Any

import board_hk
import board_review
import board_review_sample
import board_store
from test_board import BoardTestCase


def _enable_staff(table: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True})
    return board_store.save_settings(table, settings)


class FinishPreviewTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.settings = _enable_staff(self.table)

    def _yesterday(self) -> str:
        from datetime import timedelta

        return board_hk.to_iso(
            (board_hk.now_hkt() - timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        )

    def test_task_finish_preview_is_the_json_not_the_key(self) -> None:
        created = self._yesterday()
        body = {"district": "Eastern", "organisations": [{"name_en": "Quarry Bay Park Playground"}]}
        board_store.add_tool_call(
            self.table,
            {
                "callId": "call-json",
                "op": "task_finish",
                "toolId": "task",
                "status": "ok",
                "summary": "Finished the task",
                "createdAt": created,
                "arguments": {"deliverableType": "json", "deliverable": json.dumps(body)},
                "resultPreview": '{"ok": true, "deliverableKey": "board/executive/staff/t/deliverable.json"}',
                "personaId": "content-marketer",
                "displayName": "Mei",
            },
        )
        board_store.add_tool_call(
            self.table,
            {
                "callId": "call-md",
                "op": "task_finish",
                "toolId": "task",
                "status": "ok",
                "summary": "Finished the task",
                "createdAt": created,
                "arguments": {"deliverableType": "markdown", "deliverable": "# Stanley calendar"},
                "personaId": "content-marketer",
            },
        )
        huge = {"note": "n" * 4000}
        board_store.add_tool_call(
            self.table,
            {
                "callId": "call-huge",
                "op": "task_finish",
                "toolId": "task",
                "status": "ok",
                "summary": "Finished the task",
                "createdAt": created,
                "arguments": {"deliverableType": "json", "deliverable": json.dumps(huge)},
                "personaId": "content-marketer",
            },
        )
        self.settings["review"] = board_store.normalize_review_config({"sampleSize": 5})
        rows = {row["callId"]: row for row in board_review._sample(self.table, self.settings, board_hk.today_hkt())}
        preview = rows["call-json"]["deliverablePreview"]
        self.assertIn('"district": "Eastern"', preview)
        self.assertIn("Quarry Bay Park Playground", preview)
        self.assertNotIn("deliverableKey", preview)
        self.assertEqual(rows["call-md"]["deliverablePreview"], "")
        self.assertIn("[truncated,", rows["call-huge"]["deliverablePreview"])
        self.assertLess(len(rows["call-huge"]["deliverablePreview"]), 2000)
        line = board_review_sample.digest_line(rows["call-json"])
        self.assertIn("Finished the task", line)
        self.assertNotIn("Quarry Bay Park Playground", line)

    def test_today_read_overlays_the_preview_without_writing_the_snapshot(self) -> None:
        created = self._yesterday()
        board_store.add_tool_call(
            self.table,
            {
                "callId": "call-json",
                "op": "task_finish",
                "toolId": "task",
                "status": "ok",
                "summary": "Finished the task",
                "createdAt": created,
                "arguments": {"deliverableType": "json", "deliverable": '{"district":"Eastern"}'},
                "personaId": "content-marketer",
                "displayName": "Mei",
            },
        )
        today = board_hk.today_hkt()
        board_store.put_review_snapshot(self.table, today, {"date": today, "sample": [], "digestHtml": "stored"})
        status, body = self.call("/siu-tin-dei/board/review")
        self.assertEqual(status, 200)
        rows = {row["callId"]: row for row in body["review"]["sample"]}
        self.assertIn('"district": "Eastern"', rows["call-json"]["deliverablePreview"])
        stored = board_store.get_review_snapshot(self.table, today)
        self.assertEqual(stored["sample"], [])
        self.assertEqual(stored["digestHtml"], "stored")
