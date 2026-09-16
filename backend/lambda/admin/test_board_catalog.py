"""Unit tests for catalog micro-batch duty."""

from __future__ import annotations

import os
import unittest
from datetime import datetime
from unittest.mock import patch

from test_board import BoardTestCase

import board_async
import board_catalog
import board_duties
import board_hk
import board_staff
import board_store
from contract_constants import BOARD_CATALOG_DISTRICTS, BOARD_CATALOG_OUTPUT_CONTRACT


def _enable(table, **staff):
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config(
        {**(settings.get("staff") or {}), "enabled": True, "dutiesEnabled": True, **staff}
    )
    return board_store.save_settings(table, settings)


class CatalogDutyTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))

    def test_compose_brief_includes_contract_and_district(self) -> None:
        district = BOARD_CATALOG_DISTRICTS[0]
        brief = board_catalog.compose_brief(district)
        self.assertIn(district["name"], brief)
        self.assertIn("research_fetch_page", brief)
        self.assertTrue(BOARD_CATALOG_OUTPUT_CONTRACT[:40] in brief)

    def test_create_next_skips_claimed_districts(self) -> None:
        settings = _enable(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            first = board_catalog.create_next(self.table, settings)
            second = board_catalog.create_next(self.table, settings)
        self.assertEqual(first["eventRef"]["districtId"], BOARD_CATALOG_DISTRICTS[0]["id"])
        self.assertEqual(second["eventRef"]["districtId"], BOARD_CATALOG_DISTRICTS[1]["id"])
        self.assertEqual(first["deliverableType"], "json")

    def test_duty_creates_one_catalog_task(self) -> None:
        settings = _enable(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        when = datetime(2026, 9, 16, 8, 0, tzinfo=board_hk.HKT)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            created = board_duties.run_due(self.table, settings, now=when)
        catalog = [t for t in created if (t.get("eventRef") or {}).get("kind") == "catalog-micro-batch"]
        self.assertEqual(len(catalog), 1)
        self.assertIn("CATALOG MICRO-BATCH", catalog[0]["brief"])

    def test_duty_second_slot_creates_next_district(self) -> None:
        settings = _enable(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        morning = datetime(2026, 9, 16, 8, 0, tzinfo=board_hk.HKT)
        midday = datetime(2026, 9, 16, 12, 0, tzinfo=board_hk.HKT)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            first = board_duties.run_due(self.table, settings, now=morning)
            second = board_duties.run_due(self.table, settings, now=midday)
            again = board_duties.run_due(self.table, settings, now=midday)
        catalog = [t for t in first + second if (t.get("eventRef") or {}).get("kind") == "catalog-micro-batch"]
        self.assertEqual(len(catalog), 2)
        self.assertEqual(catalog[0]["eventRef"]["districtId"], BOARD_CATALOG_DISTRICTS[0]["id"])
        self.assertEqual(catalog[1]["eventRef"]["districtId"], BOARD_CATALOG_DISTRICTS[1]["id"])
        self.assertEqual(
            [t for t in again if (t.get("eventRef") or {}).get("kind") == "catalog-micro-batch"],
            [],
        )


if __name__ == "__main__":
    unittest.main()
