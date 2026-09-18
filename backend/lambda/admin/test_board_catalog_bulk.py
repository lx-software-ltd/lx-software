"""Bulk catalog sources, candidate queue and discovery."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from test_board import BoardTestCase

import board_catalog_bulk
import board_catalog_candidates
import board_catalog_discovery
import board_catalog_import
import board_opendata
import board_places
import board_store


def _enable_staff(table):
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True})
    return board_store.save_settings(table, settings)


LCSD_JSON = """
[
  {
    "Name_en": "Quarry Bay Park Playground",
    "Name_tc": "鰂魚涌公園遊樂場",
    "Address_en": "Taikoo Shing, Eastern",
    "District_en": "Eastern",
    "Latitude": 22.291,
    "Longitude": 114.216,
    "OBJECTID": "lcsd-1"
  }
]
"""

EDB_CSV = """ENGLISH NAME,中文名稱,ENGLISH ADDRESS,DISTRICT,SCHOOL LEVEL
Little Stars KG,小星星幼稚園,12 Main St,Sha Tin,Kindergarten
Tai Po Secondary,大埔中學,1 School Rd,Tai Po,Secondary
"""

SWD_CSV = """Centre Name (English),Centre Name (Chinese),Address,District,Telephone
Happy Child Care,快樂幼兒中心,88 Park Rd,Wan Chai,2345 6789
"""


class OpenDataParserTests(unittest.TestCase):
    def test_parse_lcsd_json(self) -> None:
        rows = board_opendata.parse_lcsd_json(LCSD_JSON, facility_kind="lcsd_playground", category="Outdoor activity")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["nameEn"], "Quarry Bay Park Playground")
        self.assertEqual(rows[0]["district"], "Eastern")
        self.assertEqual(rows[0]["facilityKind"], "lcsd_playground")
        self.assertEqual(rows[0]["sourceId"], "lcsd-1")

    def test_edb_kindergartens_filter(self) -> None:
        rows = board_opendata.parse_edb_csv(EDB_CSV)
        kgs = [r for r in rows if board_opendata.is_kindergarten(r)]
        self.assertEqual(len(kgs), 1)
        self.assertEqual(kgs[0]["nameEn"], "Little Stars KG")

    def test_parse_swd_csv(self) -> None:
        rows = board_opendata.parse_swd_csv(SWD_CSV)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["nameEn"], "Happy Child Care")
        self.assertEqual(rows[0]["source"], "swd")
        self.assertTrue(rows[0]["sourceId"])


class CandidateQueueTests(BoardTestCase):
    def test_official_source_auto_approves(self) -> None:
        doc = board_catalog_candidates.upsert_candidate(
            self.table,
            {
                "source": "lcsd",
                "sourceId": "lcsd-1",
                "nameEn": "Quarry Bay Park Playground",
                "district": "Eastern",
                "facilityKind": "lcsd_playground",
            },
        )
        self.assertEqual(doc["status"], "approved")
        self.assertEqual(doc["category"], "Outdoor activity")

    def test_competitor_stays_new(self) -> None:
        doc = board_catalog_candidates.upsert_candidate(
            self.table,
            {"source": "competitor", "nameEn": "Example Playhouse", "district": "Sha Tin"},
        )
        self.assertEqual(doc["status"], "new")

    def test_duplicate_imported_is_skipped(self) -> None:
        first = board_catalog_candidates.upsert_candidate(
            self.table,
            {"source": "lcsd", "sourceId": "lcsd-1", "nameEn": "Quarry Bay Park Playground", "district": "Eastern"},
        )
        board_catalog_candidates.set_status(self.table, first["candidateId"], "imported")
        board_catalog_candidates.remember_listing(
            self.table, {"name": "Quarry Bay Park Playground", "area_name": "Eastern", "lat": 22.291, "lng": 114.216}
        )
        self.assertTrue(
            board_catalog_candidates.is_duplicate(
                self.table,
                {"source": "lcsd", "sourceId": "lcsd-1", "nameEn": "Quarry Bay Park Playground", "district": "Eastern"},
            )
        )

    def test_expire_stale_places(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
        board_catalog_candidates.upsert_candidate(
            self.table,
            {
                "source": "places",
                "placeId": "ChIJ1",
                "nameEn": "Old Park",
                "district": "Eastern",
                "phone": "2345 0000",
                "openingHours": "Daily 09:00-18:00",
                "placesFetchedAt": old,
                "types": ["park"],
            },
        )
        n = board_catalog_candidates.expire_stale_places(self.table)
        self.assertEqual(n, 1)
        rows = board_store.list_candidates(self.table, "approved")
        self.assertEqual(rows[0].get("openingHours"), "")
        self.assertTrue(rows[0].get("placesExpired"))


class BulkTransformTests(BoardTestCase):
    def test_candidate_to_org_always_has_activity(self) -> None:
        org = board_catalog_bulk.candidate_to_org(
            {
                "source": "lcsd",
                "sourceId": "lcsd-1",
                "nameEn": "Quarry Bay Park Playground",
                "nameZh": "鰂魚涌公園遊樂場",
                "district": "Eastern",
                "category": "Outdoor activity",
            },
            manager_id="mgr-1",
        )
        self.assertEqual(org["category_name"], "Outdoor activity")
        self.assertEqual(len(org["activities"]), 1)
        self.assertIn("public outdoor venue", org["description"])
        self.assertTrue(org["description_zh"])

    def test_preview_uses_approved_candidates(self) -> None:
        os.environ["BOARD_CATALOG_IMPORT_ENABLED"] = "true"
        os.environ["BOARD_CATALOG_MANAGER_ID"] = "mgr-1"
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_IMPORT_ENABLED", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_MANAGER_ID", None))
        with patch.object(
            board_catalog_bulk,
            "load_source_rows",
            return_value=[
                {
                    "source": "lcsd",
                    "sourceId": "lcsd-1",
                    "nameEn": "Quarry Bay Park Playground",
                    "district": "Eastern",
                    "facilityKind": "lcsd_playground",
                }
            ],
        ):
            out = board_catalog_bulk.preview_source(self.table, "lcsd", remote=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["approved"], 1)
        self.assertEqual(out["wouldSend"], 1)
        self.assertEqual(out["dryRuns"][0]["accepted"], 1)

    def test_unknown_source_rejected(self) -> None:
        with self.assertRaises(board_catalog_bulk.BulkImportError):
            board_catalog_bulk.preview_source(self.table, "fehd")


class DiscoveryTests(BoardTestCase):
    def test_extract_listing_names(self) -> None:
        html = "<h2>Happy Playhouse</h2><a>Tai Po Art Class</a>\n- Sha Tin Sports Hall"
        names = board_catalog_discovery.extract_listing_names(html)
        self.assertIn("Happy Playhouse", names)
        self.assertIn("Tai Po Art Class", names)

    def test_ingest_listings_page_creates_new_candidates(self) -> None:
        n = board_catalog_discovery.ingest_listings_page(
            self.table,
            {"watchId": "w1"},
            "<h2>Example Playhouse</h2>",
            "https://competitor.example/listings",
        )
        self.assertEqual(n, 1)
        rows = board_store.list_candidates(self.table, "new")
        self.assertEqual(rows[0]["source"], "competitor")
        self.assertEqual(rows[0]["nameEn"], "Example Playhouse")

    def test_discover_places_upserts(self) -> None:
        settings = _enable_staff(self.table)
        places = [
            {
                "placeId": "ChIJpark",
                "name": "Eastern Playground",
                "address": "Quarry Bay, Eastern, Hong Kong",
                "types": ["park"],
                "rating": 4.4,
                "userRatingCount": 40,
                "facilityKind": "places_park",
            }
        ]
        with patch.object(board_places, "discover", return_value=places):
            out = board_catalog_discovery.discover_places(self.table, settings, districts=["Eastern"])
        self.assertEqual(out["upserted"], 1)
        rows = board_store.list_candidates(self.table)
        self.assertEqual(rows[0]["source"], "places")
        self.assertEqual(rows[0]["status"], "approved")

    def test_run_discovery_skips_when_staff_off(self) -> None:
        settings = board_store.load_settings(self.table)
        out = board_catalog_discovery.run_discovery(self.table, settings)
        self.assertEqual(out.get("skipped"), "disabled")


class CatalogImportActivityTests(unittest.TestCase):
    def test_transform_org_always_emits_activity(self) -> None:
        org, meta = board_catalog_import.transform_org(
            {
                "name_en": "Wan Chai Park",
                "type": "playground",
                "address_en": "Wan Chai",
                "verified_fields": ["name_en", "address_en"],
                "unverified_fields": ["opening_hours"],
            },
            district="Wan Chai",
            manager_id="mgr-1",
            index=0,
        )
        self.assertFalse(meta.get("skipped"))
        self.assertEqual(len(org["activities"]), 1)
        self.assertNotIn("schedules", org["activities"][0])


if __name__ == "__main__":
    unittest.main()
