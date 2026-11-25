"""Qualify brief: named scoring tool, district gaps, and a task-sized count."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import board_prospects
import board_store
import board_targets
import board_tools
import board_tools_outreach
from test_board import BoardTestCase


def _enable_staff(table: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True})
    return board_store.save_settings(table, settings)


class QualifyBriefTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "prospector", {"isActive": True})

    def test_brief_names_scoring_caps_the_ask_and_drops_other_districts(self) -> None:
        bounds = dict(self.settings["boundaries"])
        outreach = dict(bounds["outreach"])
        outreach["districtsFirst"] = ["Southern"]
        bounds["outreach"] = outreach
        self.settings["boundaries"] = board_store.normalize_boundaries(bounds)
        self.settings = board_store.save_settings(self.table, self.settings)
        board_store.put_cache(
            self.table,
            "intel:gaps",
            {
                "gaps": [
                    {"category": "play", "district": "Sai Kung", "competitorCount": 2},
                    {"category": "play", "district": "Southern", "competitorCount": 1},
                ]
            },
        )
        with patch.object(board_targets, "prorated_target", return_value=21):
            result = board_targets.check(self.table, self.settings)
        self.assertTrue(result["taskIds"])
        task = board_store.get_task(self.table, result["taskIds"][0])
        assert task is not None
        brief = str(task.get("brief") or "")
        self.assertIn("outreach_score_prospect", brief)
        self.assertIn("Find and qualify 8", brief)
        self.assertNotIn("qualify 21", brief)
        self.assertNotIn("Sai Kung", brief)
        self.assertIn("Southern", brief)

    def test_list_filters_district_and_upsert_rejects_a_mismatched_name(self) -> None:
        board_prospects.upsert(self.table, name="South Hall", type="venue", district="Southern")
        board_prospects.upsert(self.table, name="Yuen Hall", type="venue", district="Yuen Long")
        ctx = board_tools.ToolContext(table=self.table, settings=self.settings, persona_id="coo", kind="task")
        listed = board_tools_outreach._outreach_list_prospects(ctx, {"district": "southern"})  # noqa: SLF001
        districts = {row.get("district") for row in listed["prospects"]}
        self.assertEqual(districts, {"Southern"})
        refused = board_tools_outreach._outreach_upsert_prospect(  # noqa: SLF001
            ctx, {"name": "Club (Wan Chai)", "type": "venue", "district": "Southern"}
        )
        self.assertIn("error", refused)
        accepted = board_tools_outreach._outreach_upsert_prospect(  # noqa: SLF001
            ctx,
            {
                "name": "Club (Wan Chai)",
                "type": "venue",
                "district": "Southern",
                "address": "1 Harbour Road, Wan Chai",
            },
        )
        self.assertNotIn("error", accepted)
        self.assertEqual(accepted["prospect"]["district"], "Wan Chai")
