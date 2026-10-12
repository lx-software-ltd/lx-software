"""Config-gap cache, called directly rather than through the duty wrappers."""

from __future__ import annotations

import board_config_gaps
import board_store
from test_board import BoardTestCase


class ConfigGapCacheTests(BoardTestCase):
    def test_same_week_refreshes_the_reason_once(self) -> None:
        first = board_config_gaps.note_config_gap(self.table, gap_id="dmarc:example.com", reason="first")
        self.assertEqual(first["reason"], "first")
        again = board_config_gaps.note_config_gap(self.table, gap_id="dmarc:example.com", reason="second")
        self.assertIsNone(again)
        same = board_config_gaps.note_config_gap(self.table, gap_id="dmarc:example.com", reason="second")
        self.assertIsNone(same)
        rows = [
            row for row in board_config_gaps.list_config_gaps(self.table) if row.get("gapId") == "dmarc:example.com"
        ]
        self.assertEqual([row["reason"] for row in rows], ["second"])
        updates = [
            row for row in board_store.list_updates(self.table) if "dmarc:example.com" in str(row.get("text") or "")
        ]
        self.assertEqual(len(updates), 1)
        self.assertIn("first", updates[0]["text"])

    def test_older_week_collapses_and_clear_removes_the_row(self) -> None:
        board_config_gaps.note_config_gap(self.table, gap_id="dmarc:example.com", reason="this week")
        board_config_gaps.note_config_gap(self.table, gap_id="opendata-edb", reason="empty fetch")
        items = board_config_gaps.list_config_gaps(self.table)
        items.append({"gapId": "dmarc:example.com", "week": "2020-W01", "reason": "old", "at": "2020-01-01T00:00:00Z"})
        board_store.put_cache(self.table, "config:gaps", {"items": items}, ttl_seconds=40 * 86400)
        board_config_gaps.note_config_gap(self.table, gap_id="dmarc:example.com", reason="still this week")
        rows = [
            row for row in board_config_gaps.list_config_gaps(self.table) if row.get("gapId") == "dmarc:example.com"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "still this week")
        self.assertNotEqual(rows[0]["week"], "2020-W01")
        self.assertEqual(board_config_gaps.clear_config_gap(self.table, "dmarc:example.com"), 1)
        self.assertFalse(
            any(row.get("gapId") == "dmarc:example.com" for row in board_config_gaps.list_config_gaps(self.table))
        )
        self.assertTrue(
            any(row.get("gapId") == "opendata-edb" for row in board_config_gaps.list_config_gaps(self.table))
        )
        self.assertEqual(board_config_gaps.clear_config_gap(self.table, "dmarc:example.com"), 0)
