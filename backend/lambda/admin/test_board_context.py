"""Founder notes stay in the context pack when system lines fill the log."""

from __future__ import annotations

from unittest.mock import patch

import board_context
import board_store
from test_board import BoardTestCase


class ContextUpdateTests(BoardTestCase):
    def test_system_lines_leave_the_founder_note_in_the_pack(self) -> None:
        board_store.add_update(self.table, text="Pause Facebook and Instagram.", owner_sub="founder")
        for index in range(80):
            board_store.add_update(
                self.table,
                text=f"BREAKER tool:mail — trip {index}",
                owner_sub=None,
                kind="system",
            )
        with patch("board_crawl.fetch", side_effect=OSError("offline")):
            pack = board_context.build_context_pack(self.table, board_store.load_settings(self.table), roster=[])
        texts = [row["text"] for row in pack["updates"]]
        self.assertIn("Pause Facebook and Instagram.", texts)
        self.assertEqual(len(pack["systemUpdates"]), 5)
        rendered = board_context.render_context_pack(pack)
        self.assertIn("Pause Facebook and Instagram.", rendered)
        self.assertIn("--- System log (newest first) ---", rendered)
