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
    "Name_cn": "鰂魚涌公園遊樂場",
    "Address_en": "Taikoo Shing, Eastern",
    "Address_cn": "鰂魚涌",
    "District_en": "Eastern",
    "Opening_hours_en": "Daily 7:00 am &ndash; 11:00 pm<br />Closed Monday",
    "Latitude": 22.291,
    "Longitude": 114.216,
    "GIHS": "abcGIHS",
    "OBJECTID": "lcsd-1"
  }
]
"""

LCSD_PLAYROOM_JSON = """
[
  {
    "Name_en": "Shek Tong Tsui Sports Centre",
    "Name_cn": "石塘咀體育館",
    "District_en": "Central and Western",
    "GIHS": "play-1"
  }
]
"""

CSDI_PARK = """
{"features":[{"attributes":{"OBJECTID":9,"NameEN":"Jordan Valley Park","NameTC":"佐敦谷公園","AddressEN":"No.71, New Clear Water Bay Road","DistrictEN":"KWUN TONG","LATITUDE":22.33,"LONGITUDE":114.22},"geometry":{"x":114.22,"y":22.33}}]}
"""

EDB_CSV = """SCHOOL NO.,ENGLISH NAME,中文名稱,ENGLISH ADDRESS,DISTRICT,SCHOOL LEVEL,LATITUDE,LONGITUDE,TELEPHONE,WEBSITE
12345678,Little Stars KG,小星星幼稚園,12 Main St,Sha Tin,Kindergarten,22.38,114.19,2648 0000,https://kg.example
00000001,Tai Po Secondary,大埔中學,1 School Rd,Tai Po,Secondary,22.45,114.16,2664 0000,https://sec.example
"""

SWD_CSV = """Centre Name (English),Centre Name (Chinese),Address,District,Telephone
Happy Child Care,快樂幼兒中心,88 Park Rd,Wan Chai,2345 6789
"""

SWD_TSV = "Name of Centre\t中心名稱\tAddress\tDistrict\tTel. No.\nHappy Child Care\t快樂幼兒中心\t88 Park Rd, Wan Chai\tWan Chai\t2345 6789\n"


class OpenDataParserTests(unittest.TestCase):
    def test_parse_lcsd_json(self) -> None:
        rows = board_opendata.parse_lcsd_json(LCSD_JSON, facility_kind="lcsd_playground", category="Outdoor activity")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["nameEn"], "Quarry Bay Park Playground")
        self.assertEqual(rows[0]["nameZh"], "鰂魚涌公園遊樂場")
        self.assertEqual(rows[0]["district"], "Eastern")
        self.assertEqual(rows[0]["facilityKind"], "lcsd_playground")
        self.assertEqual(rows[0]["sourceId"], "lcsd-1")
        self.assertIn("Daily 7:00 am", rows[0]["openingHours"])
        self.assertNotIn("<br", rows[0]["openingHours"])
        self.assertNotIn("&ndash;", rows[0]["openingHours"])

    def test_playroom_name_is_qualified(self) -> None:
        rows = board_opendata.parse_lcsd_json(
            LCSD_PLAYROOM_JSON, facility_kind="lcsd_playroom", category="Indoor fun"
        )
        self.assertEqual(rows[0]["nameEn"], "Shek Tong Tsui Sports Centre Children's Play Room")
        self.assertEqual(rows[0]["sourceId"], "play-1")

    def test_parse_csdi_park_features(self) -> None:
        rows = board_opendata.parse_csdi_features(CSDI_PARK, facility_kind="lcsd_park", category="Outdoor activity")
        self.assertEqual(rows[0]["nameEn"], "Jordan Valley Park")
        self.assertEqual(rows[0]["nameZh"], "佐敦谷公園")
        self.assertEqual(rows[0]["district"], "Kwun Tong")
        self.assertEqual(rows[0]["sourceId"], "9")
        self.assertAlmostEqual(float(rows[0]["lat"]), 22.33)

    def test_edb_kindergartens_filter(self) -> None:
        rows = board_opendata.parse_edb_csv(EDB_CSV)
        kgs = [r for r in rows if board_opendata.is_kindergarten(r)]
        self.assertEqual(len(kgs), 1)
        self.assertEqual(kgs[0]["nameEn"], "Little Stars KG")
        self.assertEqual(kgs[0]["sourceId"], "12345678")
        self.assertAlmostEqual(float(kgs[0]["lat"]), 22.38)
        self.assertEqual(kgs[0]["phone"], "2648 0000")
        self.assertEqual(kgs[0]["officialUrl"], "https://kg.example")

    def test_parse_swd_csv(self) -> None:
        rows = board_opendata.parse_swd_csv(SWD_CSV)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["nameEn"], "Happy Child Care")
        self.assertEqual(rows[0]["source"], "swd")
        self.assertTrue(rows[0]["sourceId"])

    def test_parse_swd_utf16_tsv(self) -> None:
        rows = board_opendata.parse_swd_csv(SWD_TSV)
        self.assertEqual(rows[0]["nameEn"], "Happy Child Care")
        self.assertEqual(rows[0]["phone"], "2345 6789")


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

    def test_commercial_places_stays_new(self) -> None:
        doc = board_catalog_candidates.upsert_candidate(
            self.table,
            {
                "source": "places",
                "placeId": "ChIJamuse",
                "nameEn": "Indoor Play Palace",
                "district": "Sha Tin",
                "types": ["amusement_center"],
                "facilityKind": "places_amusement",
                "rating": 4.8,
                "userRatingCount": 200,
            },
        )
        self.assertEqual(doc["status"], "new")

    def test_upsert_keeps_described_copy(self) -> None:
        first = board_catalog_candidates.upsert_candidate(
            self.table,
            {
                "source": "lcsd",
                "sourceId": "lcsd-1",
                "nameEn": "Quarry Bay Park Playground",
                "district": "Eastern",
                "descriptionEn": "Harbourfront playground with slides.",
                "descriptionSource": "official",
            },
        )
        again = board_catalog_candidates.upsert_candidate(
            self.table,
            {
                "source": "lcsd",
                "sourceId": "lcsd-1",
                "nameEn": "Quarry Bay Park Playground",
                "district": "Eastern",
                "descriptionEn": "Quarry Bay Park Playground is a public outdoor venue in Eastern for children and families.",
                "descriptionSource": "template",
            },
        )
        self.assertEqual(again["candidateId"], first["candidateId"])
        self.assertEqual(again["descriptionEn"], "Harbourfront playground with slides.")
        self.assertEqual(again["descriptionSource"], "official")

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
        self.assertEqual(board_catalog_candidates.expire_stale_places(self.table), 0)


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

    def test_import_marks_only_created_rows(self) -> None:
        os.environ["BOARD_CATALOG_IMPORT_ENABLED"] = "true"
        os.environ["BOARD_CATALOG_MANAGER_ID"] = "mgr-1"
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_IMPORT_ENABLED", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_MANAGER_ID", None))
        keep = board_catalog_candidates.upsert_candidate(
            self.table,
            {"source": "lcsd", "sourceId": "keep", "nameEn": "Keep Park", "district": "Eastern"},
        )
        drop = board_catalog_candidates.upsert_candidate(
            self.table,
            {"source": "lcsd", "sourceId": "drop", "nameEn": "Drop Park", "district": "Eastern"},
        )

        def fake_import(payload, token):
            return {
                "ok": False,
                "summary": {"failed": 1, "created": 1, "updated": 0},
                "results": [
                    {"type": "organizations", "key": "Keep Park", "status": "created"},
                    {"type": "organizations", "key": "Drop Park", "status": "failed"},
                ],
            }

        with (
            patch.object(board_catalog_bulk, "load_source_rows", return_value=[]),
            patch.object(board_catalog_import, "configured", return_value=True),
            patch.object(board_catalog_import, "_id_token", return_value="tok"),
            patch.object(board_catalog_import, "_run_remote_import", side_effect=fake_import),
        ):
            out = board_catalog_bulk.import_source(self.table, "lcsd")
        self.assertEqual(out["imported"], 1)
        self.assertEqual(board_store.get_candidate(self.table, keep["candidateId"])["status"], "imported")
        self.assertEqual(board_store.get_candidate(self.table, drop["candidateId"])["status"], "approved")

    def test_queue_preview_returns_queued(self) -> None:
        os.environ["BOARD_CATALOG_IMPORT_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_IMPORT_ENABLED", None))
        with patch("board_async.try_invoke_event", return_value=True) as invoke:
            out = board_catalog_bulk.queue_action(self.table, "preview", "lcsd")
        self.assertTrue(out["queued"])
        self.assertTrue(out["invoked"])
        invoke.assert_called_once()
        self.assertEqual(invoke.call_args[0][0]["internal"], "board_catalog_bulk")

    def test_bulk_preview_route_queues(self) -> None:
        os.environ["BOARD_CATALOG_IMPORT_ENABLED"] = "true"
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_IMPORT_ENABLED", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        with patch("board_async.try_invoke_event", return_value=True):
            status, body = self.call("/siu-tin-dei/board/catalog/bulk/lcsd/preview", "POST", {"remote": True})
        self.assertEqual(status, 200)
        self.assertTrue(body.get("queued"))

    def test_discovery_run_409_when_staff_off(self) -> None:
        status, body = self.call("/siu-tin-dei/board/catalog/discovery/run", "POST", {})
        self.assertEqual(status, 409)
        self.assertIn("disabled", body["message"].lower())

    def test_discovery_run_queues_when_staff_on(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        _enable_staff(self.table)
        with patch("board_async.try_invoke_event", return_value=True) as invoke:
            status, body = self.call("/siu-tin-dei/board/catalog/discovery/run", "POST", {})
        self.assertEqual(status, 200)
        self.assertTrue(body.get("queued"))
        self.assertEqual(invoke.call_args[0][0]["internal"], "board_catalog_discovery")


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
