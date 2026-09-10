"""Prospect dedupe, scoring, qualification and contact filter (WP6)."""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import patch

import board_prospects
import board_store
from test_board import BoardTestCase


def _enable_staff(table: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True})
    return board_store.save_settings(table, settings)


class DedupeTests(unittest.TestCase):
    def test_domain_normalises_www_and_slash(self) -> None:
        self.assertEqual(board_prospects.dedupe_key("https://www.Play.example/", "", ""), "play.example")
        self.assertEqual(board_prospects.dedupe_key("http://play.example/path", "", ""), "play.example")

    def test_phone_formats(self) -> None:
        self.assertEqual(board_prospects.dedupe_key("", "2345 6789", ""), "+85223456789")
        self.assertEqual(board_prospects.dedupe_key("", "+852-2345-6789", ""), "+85223456789")

    def test_place_id_fallback(self) -> None:
        self.assertEqual(board_prospects.dedupe_key("", "", "ChIJabc"), "ChIJabc")


class QualifyTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.settings = _enable_staff(self.table)

    def test_qualify_by_type_and_score(self) -> None:
        venue, _ = board_prospects.upsert(self.table, name="Hall", type="venue", district="Sha Tin")
        venue["score"] = 70
        self.assertEqual(board_prospects.qualify(self.table, self.settings, venue)["stage"], "qualified")
        resto, _ = board_prospects.upsert(self.table, name="Cafe", type="restaurant", district="Sha Tin")
        resto["score"] = 80
        self.assertEqual(board_prospects.qualify(self.table, self.settings, resto)["stage"], "parked")
        low, _ = board_prospects.upsert(self.table, name="Tiny", type="venue", district="Tai Po")
        low["score"] = 40
        self.assertEqual(board_prospects.qualify(self.table, self.settings, low)["stage"], "discovered")

    def test_unmapped_district_is_unknown(self) -> None:
        row, _ = board_prospects.upsert(self.table, name="X", type="venue", district="Narnia")
        self.assertEqual(row["district"], "unknown")

    def test_business_address_filter(self) -> None:
        allow = {"boundaries": {"outreach": {"personalAddressesAllowed": False}}}
        self.assertTrue(board_prospects._is_business_address("info@hall.example", allow_personal=False))
        self.assertFalse(board_prospects._is_business_address("wendy.chan@gmail.com", allow_personal=False))
        self.assertTrue(board_prospects._is_business_address("wendy.chan@gmail.com", allow_personal=True))
        row, _ = board_prospects.upsert(
            self.table, name="Hall", type="venue", website="https://hall.example", email="wendy.chan@gmail.com"
        )
        found = board_prospects.find_contact(self.table, allow, row)
        self.assertIsNone(found)
        self.assertIsNone(board_store.get_prospect(self.table, row["prospectId"]).get("contact") or None)

    def test_score_uses_fake_desk(self) -> None:
        row, _ = board_prospects.upsert(self.table, name="Hall", type="venue", website="https://hall.example")

        class Fake:
            text = '{"score": 66, "note": "Has a Saturday schedule."}'

        import board_crawl

        fetched = board_crawl.FetchResult(
            status=200,
            final_url="https://hall.example",
            content_type="text/html",
            text="<html><body>" + ("play " * 40) + "</body></html>",
            hash="abc",
        )
        with (
            patch("board_crawl.fetch", return_value=fetched),
            patch("board_budget.board_completion", return_value=Fake()),
            patch("board_budget.model_for", return_value="desk"),
        ):
            score, note = board_prospects.score(self.table, self.settings, row)
        self.assertEqual(score, 66)
        self.assertIn("Saturday", note)

    def test_upsert_dedupes_and_intel_helper(self) -> None:
        first, created = board_prospects.upsert(self.table, name="A", type="venue", website="https://www.hall.example/")
        self.assertTrue(created)
        second, created2 = board_prospects.upsert(self.table, name="A2", type="venue", website="https://hall.example")
        self.assertFalse(created2)
        self.assertEqual(first["prospectId"], second["prospectId"])
        row, _ = board_prospects.upsert_prospect(self.table, {"name": "Intel Hall", "type": "provider", "website": "https://intel.example"})
        self.assertEqual(row["source"], "intel")

    def test_import_merge_and_routes(self) -> None:
        csv_text = "name,type,district,website,email\nHall,venue,Sha Tin,https://hall.example,info@hall.example\n"
        out = board_prospects.import_csv(self.table, csv_text)
        self.assertEqual(out["created"], 1)
        a, _ = board_prospects.upsert(self.table, name="Twin", type="venue", district="Sha Tin", website="https://a.example")
        b, _ = board_prospects.upsert(self.table, name="Twin", type="venue", district="Sha Tin", website="https://b.example")
        dest = board_prospects.merge(self.table, a["prospectId"], b["prospectId"])
        self.assertEqual(dest["prospectId"], b["prospectId"])
        self.assertEqual(board_store.get_prospect(self.table, a["prospectId"])["stage"], "suppressed")
        status, body = self.call("/siu-tin-dei/board/prospects")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(body["prospects"]), 2)
        status, body = self.call(f"/siu-tin-dei/board/prospects/{b['prospectId']}", "PUT", {"stage": "parked", "note": "owner"})
        self.assertEqual(status, 200)
        self.assertEqual(body["prospect"]["stage"], "parked")
        status, _ = self.call(f"/siu-tin-dei/board/prospects/{a['prospectId']}/merge", "POST", {"into": b["prospectId"]})
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
