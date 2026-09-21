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
import board_duties
import board_hk
import board_opendata
import board_places
import board_staff
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
        self.assertEqual(len(rows), 1)
        self.assertTrue(all(board_opendata.is_kindergarten(r) for r in rows))
        self.assertEqual(rows[0]["nameEn"], "Little Stars KG")
        self.assertEqual(rows[0]["sourceId"], "12345678")
        self.assertAlmostEqual(float(rows[0]["lat"]), 22.38)
        self.assertEqual(rows[0]["phone"], "2648 0000")
        self.assertEqual(rows[0]["officialUrl"], "https://kg.example")

    def test_parse_edb_csv_keep_all(self) -> None:
        rows = board_opendata.parse_edb_csv(EDB_CSV, keep_all=True)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["nameEn"] for r in rows}, {"Little Stars KG", "Tai Po Secondary"})

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

    def test_expire_stale_places_scans_each_status(self) -> None:
        with patch.object(board_store, "list_candidates", return_value=[]) as listed:
            board_catalog_candidates.expire_stale_places(self.table)
        self.assertEqual(listed.call_args.kwargs.get("per_status_limit"), 10_000)

    def test_remember_listing_skips_existing_key(self) -> None:
        org = {"name": "Quarry Bay Park Playground", "area_name": "Eastern"}
        board_catalog_candidates.remember_listing(self.table, org)
        with patch.object(board_store, "put_listing_mirror") as put:
            board_catalog_candidates.remember_listing(self.table, org)
        put.assert_not_called()

    def test_seed_listing_mirror_runs_once_per_table(self) -> None:
        first = board_catalog_candidates.upsert_candidate(
            self.table,
            {"source": "lcsd", "sourceId": "seed-1", "nameEn": "Seed Park", "district": "Eastern"},
        )
        board_catalog_candidates.set_status(self.table, first["candidateId"], "imported")
        n1 = board_catalog_candidates.seed_listing_mirror(self.table)
        n2 = board_catalog_candidates.seed_listing_mirror(self.table)
        self.assertGreater(n1, 0)
        self.assertEqual(n2, 0)


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

        def fake_import(payload, token, **_kwargs):
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

    def test_import_marks_long_org_name(self) -> None:
        os.environ["BOARD_CATALOG_IMPORT_ENABLED"] = "true"
        os.environ["BOARD_CATALOG_MANAGER_ID"] = "mgr-1"
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_IMPORT_ENABLED", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_MANAGER_ID", None))
        long_name = "A" * 120
        keep = board_catalog_candidates.upsert_candidate(
            self.table,
            {"source": "lcsd", "sourceId": "long", "nameEn": long_name, "district": "Eastern"},
        )

        def fake_import(payload, token, **_kwargs):
            return {
                "ok": True,
                "summary": {"failed": 0, "created": 1, "updated": 0},
                "results": [{"type": "organizations", "key": long_name[:80], "status": "created"}],
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

    def test_import_marks_all_when_failed_is_zero(self) -> None:
        os.environ["BOARD_CATALOG_IMPORT_ENABLED"] = "true"
        os.environ["BOARD_CATALOG_MANAGER_ID"] = "mgr-1"
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_IMPORT_ENABLED", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_MANAGER_ID", None))
        keep = board_catalog_candidates.upsert_candidate(
            self.table,
            {"source": "lcsd", "sourceId": "id-key", "nameEn": "Id Key Park", "district": "Eastern"},
        )

        def fake_import(payload, token, **_kwargs):
            return {
                "ok": True,
                "summary": {"failed": 0, "created": 1, "updated": 0},
                "results": [{"type": "organizations", "key": "org-uuid-1", "status": "created"}],
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

    def test_import_continues_after_batch_timeout(self) -> None:
        os.environ["BOARD_CATALOG_IMPORT_ENABLED"] = "true"
        os.environ["BOARD_CATALOG_MANAGER_ID"] = "mgr-1"
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_IMPORT_ENABLED", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_MANAGER_ID", None))
        first = board_catalog_candidates.upsert_candidate(
            self.table,
            {"source": "lcsd", "sourceId": "one", "nameEn": "One Park", "district": "Eastern"},
        )
        second = board_catalog_candidates.upsert_candidate(
            self.table,
            {"source": "lcsd", "sourceId": "two", "nameEn": "Two Park", "district": "Eastern"},
        )
        calls: list[str] = []

        def fake_import(payload, token, *, timeout=None):
            self.assertEqual(timeout, board_catalog_import._BULK_IMPORT_HTTP_TIMEOUT)
            name = str(((payload.get("organizations") or [{}])[0] or {}).get("name") or "")
            calls.append(name)
            if len(calls) == 1:
                raise board_catalog_import.CatalogImportError(
                    "siutindei admin POST https://siu.example/v1/admin/imports failed: The read operation timed out"
                )
            return {
                "ok": True,
                "summary": {"failed": 0, "created": 1, "updated": 0},
                "results": [{"type": "organizations", "key": name, "status": "created"}],
            }

        with (
            patch.object(board_catalog_bulk, "BOARD_CATALOG_MAX_ORGS_PER_BULK_IMPORT", 1),
            patch.object(board_catalog_bulk, "load_source_rows", return_value=[]),
            patch.object(board_catalog_import, "configured", return_value=True),
            patch.object(board_catalog_import, "_id_token", return_value="tok"),
            patch.object(board_catalog_import, "_run_remote_import", side_effect=fake_import),
        ):
            out = board_catalog_bulk.import_source(self.table, "lcsd")
        self.assertEqual(len(calls), 2)
        self.assertEqual(out["imported"], 1)
        self.assertFalse(out["ok"])
        self.assertIn("timed out", out["batches"][0]["error"])
        statuses = {
            board_store.get_candidate(self.table, first["candidateId"])["status"],
            board_store.get_candidate(self.table, second["candidateId"])["status"],
        }
        self.assertEqual(statuses, {"approved", "imported"})

    def test_handle_job_import_keeps_batch_timeout_on_job(self) -> None:
        os.environ["BOARD_CATALOG_IMPORT_ENABLED"] = "true"
        os.environ["BOARD_CATALOG_MANAGER_ID"] = "mgr-1"
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_IMPORT_ENABLED", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_MANAGER_ID", None))
        board_catalog_candidates.upsert_candidate(
            self.table,
            {"source": "lcsd", "sourceId": "keep", "nameEn": "Keep Park", "district": "Eastern"},
        )

        def fake_import(payload, token, *, timeout=None):
            raise board_catalog_import.CatalogImportError(
                "siutindei admin POST https://siu.example/v1/admin/imports failed: The read operation timed out"
            )

        with (
            patch.object(board_store, "records_table", return_value=self.table),
            patch.object(board_catalog_bulk, "load_source_rows", return_value=[]),
            patch.object(board_catalog_import, "configured", return_value=True),
            patch.object(board_catalog_import, "_id_token", return_value="tok"),
            patch.object(board_catalog_import, "_run_remote_import", side_effect=fake_import),
        ):
            out = board_catalog_bulk.handle_job({"action": "import", "source": "lcsd"})
        self.assertFalse(out["ok"])
        job = board_catalog_bulk._job(self.table, "lcsd")
        self.assertEqual(job["phase"], "done")
        self.assertFalse(job.get("ok"))
        self.assertIn("timed out", job.get("error") or "")

    def test_handle_job_unexpected_error_marks_error(self) -> None:
        with (
            patch.object(board_store, "records_table", return_value=self.table),
            patch.object(board_catalog_bulk, "load_source_rows", return_value=[]),
            patch.object(board_catalog_bulk, "preview_source", side_effect=RuntimeError("cognito timeout")),
        ):
            out = board_catalog_bulk.handle_job({"action": "preview", "source": "lcsd"})
        self.assertFalse(out["ok"])
        self.assertIn("cognito timeout", out["error"])
        job = board_catalog_bulk._job(self.table, "lcsd")
        self.assertIsNotNone(job)
        self.assertEqual(job["phase"], "error")
        self.assertIn("cognito timeout", job["error"])

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
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))

    def test_extract_listing_names(self) -> None:
        html = "<h2>Happy Playhouse</h2><a>Tai Po Art Class</a>\n- Sha Tin Sports Hall"
        names = board_catalog_discovery.extract_listing_names(html)
        self.assertIn("Happy Playhouse", names)
        self.assertIn("Tai Po Art Class", names)

    def test_extract_listing_names_drops_nav_and_decodes_entities(self) -> None:
        html = (
            "<nav><a>Browse</a><a>Privacy Policy</a></nav >"
            "<header><a>Contact Us</a></header>"
            "<script>document.write('<a>Fake Listing</a>')</script >"
            "<h2>Kids&#x27; Activities in Tung Chung</h2>"
            "<a>Kids Boxing Classes</a>"
            "<a>Toddler&#x27;s Ballet</a>"
            "<a>Browse All Activities</a>"
            "<footer><a>Terms of Use</a></footer>"
        )
        names = board_catalog_discovery.extract_listing_names(html)
        self.assertEqual(names, ["Kids Boxing Classes", "Toddler's Ballet"])

    def test_extract_listing_names_drops_nav_chrome(self) -> None:
        html = (
            "<a>Next</a><a>Page 2</a><a>« Previous</a><a>See all</a>"
            "<a>Kids Boxing Classes</a>"
        )
        self.assertEqual(board_catalog_discovery.extract_listing_names(html), ["Kids Boxing Classes"])

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
        self.assertEqual(rows[0]["district"], "unknown")

    def test_ingest_listings_page_uses_url_district(self) -> None:
        n = board_catalog_discovery.ingest_listings_page(
            self.table,
            {"watchId": "w1", "district": "Sha Tin"},
            "<h2>Kids Boxing Classes</h2>",
            "https://classbee.hk/activities/area/tung_chung",
        )
        self.assertEqual(n, 1)
        self.assertEqual(board_store.list_candidates(self.table, "new")[0]["district"], "Islands")

    def test_ingest_listings_page_uses_watch_district(self) -> None:
        n = board_catalog_discovery.ingest_listings_page(
            self.table,
            {"watchId": "w1", "district": "tai-po"},
            "<h2>Happy Playhouse</h2> Tseung Kwan O campus",
            "https://directory.example/organisations",
        )
        self.assertEqual(n, 1)
        self.assertEqual(board_store.list_candidates(self.table, "new")[0]["district"], "Tai Po")

    def test_ingest_listings_page_ignores_citywide_page_text(self) -> None:
        n = board_catalog_discovery.ingest_listings_page(
            self.table,
            {"watchId": "w1"},
            "<h2>Happy Playhouse</h2> Featured in Tseung Kwan O",
            "https://directory.example/organisations",
        )
        self.assertEqual(n, 1)
        self.assertEqual(board_store.list_candidates(self.table, "new")[0]["district"], "unknown")

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

    def test_source_needs_refresh_when_cache_empty(self) -> None:
        self.assertTrue(board_catalog_discovery.source_needs_refresh(self.table, "edb"))
        board_store.put_cache(
            self.table,
            "opendata:edb",
            {"fetchedAt": "2026-09-16T00:00:00Z", "rowCount": 1, "s3Key": "board/x/opendata/edb.json.gz"},
        )
        self.assertFalse(board_catalog_discovery.source_needs_refresh(self.table, "edb"))
        board_store.put_cache(
            self.table,
            "opendata:edb",
            {"fetchedAt": "2026-09-16T00:00:00Z", "rowCount": 0},
        )
        self.assertTrue(board_catalog_discovery.source_needs_refresh(self.table, "edb"))

    def test_source_needs_refresh_ignores_legacy_pointer_without_row_count(self) -> None:
        board_store.put_cache(
            self.table,
            "opendata:edb",
            {"fetchedAt": "2026-09-01T00:00:00Z", "s3Key": "board/x/opendata/edb.json.gz"},
        )
        self.assertFalse(board_catalog_discovery.source_needs_refresh(self.table, "edb"))

    def test_run_discovery_refreshes_empty_cache_off_monday(self) -> None:
        settings = _enable_staff(self.table)
        wednesday = datetime(2026, 9, 16, 4, 0, tzinfo=board_hk.HKT)
        with (
            patch.object(board_catalog_discovery, "discover_places", return_value={"upserted": 0}),
            patch.object(board_catalog_discovery, "source_needs_refresh", return_value=True),
            patch.object(board_catalog_discovery, "refresh_open_data", return_value={"edb": {"fetched": 1}}) as refresh,
        ):
            out = board_catalog_discovery.run_discovery(self.table, settings, now=wednesday)
        refresh.assert_called_once()
        self.assertEqual(out["openData"]["edb"]["fetched"], 1)

    def test_list_filtered_and_bulk_reject(self) -> None:
        keep = board_catalog_candidates.upsert_candidate(
            self.table, {"source": "places", "nameEn": "Eastern Park", "district": "Eastern"}
        )
        junk = board_catalog_candidates.upsert_candidate(
            self.table, {"source": "competitor", "nameEn": "Browse Activities", "district": "Sha Tin"}
        )
        page = board_catalog_candidates.list_filtered(self.table, "new", source="competitor", q="browse")
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["candidates"][0]["candidateId"], junk["candidateId"])
        out = board_catalog_candidates.bulk_set_status(
            self.table, decision="reject", source="competitor", status="new"
        )
        self.assertEqual(out["updated"], 1)
        self.assertEqual(board_store.get_candidate(self.table, junk["candidateId"])["status"], "rejected")
        self.assertEqual(board_store.get_candidate(self.table, keep["candidateId"])["status"], "new")

    def test_expire_stale_competitor_closes_unmatched(self) -> None:
        old = board_catalog_candidates.upsert_candidate(
            self.table, {"source": "competitor", "nameEn": "Old Listing", "district": "Tai Po"}
        )
        old["createdAt"] = "2026-09-01T00:00:00Z"
        board_store.put_candidate(self.table, old)
        fresh = board_catalog_candidates.upsert_candidate(
            self.table, {"source": "competitor", "nameEn": "New Listing", "district": "Tai Po"}
        )
        matched = board_catalog_candidates.upsert_candidate(
            self.table, {"source": "competitor", "nameEn": "Matched Listing", "district": "Tai Po"}
        )
        matched["createdAt"] = "2026-09-01T00:00:00Z"
        matched["placeId"] = "ChIJold"
        board_store.put_candidate(self.table, matched)
        n = board_catalog_candidates.expire_stale_competitor(
            self.table, now=datetime(2026, 9, 16, tzinfo=timezone.utc)
        )
        self.assertEqual(n, 1)
        self.assertEqual(board_store.get_candidate(self.table, old["candidateId"])["status"], "closed")
        self.assertEqual(board_store.get_candidate(self.table, fresh["candidateId"])["status"], "new")
        self.assertEqual(board_store.get_candidate(self.table, matched["candidateId"])["status"], "new")
        closed = board_catalog_candidates.bulk_set_status(
            self.table,
            decision="close",
            source="competitor",
            status="new",
            before="2026-09-09T00:00:00Z",
            missing_place_id=True,
        )
        self.assertEqual(closed["updated"], 0)

    def test_enrich_competitor_with_places(self) -> None:
        row = board_catalog_candidates.upsert_candidate(
            self.table, {"source": "competitor", "nameEn": "Happy Playhouse", "district": "Sha Tin"}
        )
        places = [
            {
                "placeId": "ChIJhappy",
                "address": "1 Sha Tin Centre, Sha Tin",
                "website": "https://happy.example",
                "phone": "+852 1234 5678",
                "location": {"latitude": 22.38, "longitude": 114.19},
            }
        ]
        with patch.object(board_places, "text_search", return_value=places):
            n = board_catalog_candidates.enrich_with_places(self.table, {})
        self.assertEqual(n, 1)
        saved = board_store.get_candidate(self.table, row["candidateId"])
        self.assertEqual(saved.get("placeId"), "ChIJhappy")
        self.assertIn("Sha Tin", saved.get("addressEn") or "")


class OpenDataCacheTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        board_staff._MEMORY_BLOBS.clear()  # noqa: SLF001
        self.addCleanup(board_staff._MEMORY_BLOBS.clear)

    def test_store_pointer_round_trip(self) -> None:
        rows = [{"nameEn": "Little Stars KG", "district": "Sha Tin"}]
        stored = board_opendata._store(self.table, "opendata:edb", rows)  # noqa: SLF001
        self.assertEqual(stored["rowCount"], 1)
        self.assertTrue(stored["s3Key"].endswith("opendata-edb.json.gz"))
        hit = board_store.get_cache(self.table, "opendata:edb")
        payload = (hit or {}).get("payload") or {}
        self.assertNotIn("rows", payload)
        self.assertEqual(payload["rowCount"], 1)
        self.assertEqual(payload["s3Key"], stored["s3Key"])
        cached = board_opendata._cached(self.table, "opendata:edb")  # noqa: SLF001
        self.assertIsNotNone(cached)
        self.assertEqual(cached["rows"][0]["nameEn"], "Little Stars KG")

    def test_legacy_inline_rows_still_read(self) -> None:
        board_store.put_cache(
            self.table,
            "opendata:edb",
            {"rows": [{"nameEn": "Old KG"}], "fetchedAt": "2026-01-01T00:00:00Z"},
            ttl_seconds=3600,
        )
        cached = board_opendata._cached(self.table, "opendata:edb")  # noqa: SLF001
        self.assertEqual(cached["rows"][0]["nameEn"], "Old KG")

    def test_edb_store_failure_still_returns_rows(self) -> None:
        with (
            patch.object(board_opendata, "_download", return_value=EDB_CSV),
            patch.object(board_store, "put_cache", side_effect=RuntimeError("ValidationException: Item size")),
        ):
            out = board_opendata.edb_schools(self.table, force=True)
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["rows"][0]["nameEn"], "Little Stars KG")
        self.assertTrue(out["fetchedAt"])

    def test_edb_store_failure_logs_cache_failed(self) -> None:
        with (
            patch.object(board_opendata, "_download", return_value=EDB_CSV),
            patch.object(board_store, "put_cache", side_effect=RuntimeError("ValidationException: Item size")),
            patch.object(board_opendata, "_log_event") as logged,
        ):
            board_opendata.edb_schools(self.table, force=True)
        tags = [kwargs.get("tag") for _args, kwargs in logged.call_args_list]
        self.assertIn("board_opendata_cache_failed", tags)
        self.assertNotIn("board_opendata_fetch_failed", tags)


class ChunkedIngestTests(BoardTestCase):
    def test_queue_ingest_without_import_enabled(self) -> None:
        os.environ.pop("BOARD_CATALOG_IMPORT_ENABLED", None)
        with patch("board_async.try_invoke_event", return_value=True) as invoke:
            out = board_catalog_bulk.queue_action(self.table, "ingest", "edb", requested_by="discovery")
        self.assertTrue(out["queued"])
        self.assertEqual(out["action"], "ingest")
        invoke.assert_called_once()
        self.assertEqual(invoke.call_args[0][0]["action"], "ingest")

    def test_edb_ingest_chunks_and_reenqueues(self) -> None:
        rows = [
            {
                "nameEn": f"KG {i:04d}",
                "district": "Sha Tin",
                "sourceId": f"edb-{i}",
                "facilityKind": "edb_kindergarten",
            }
            for i in range(1200)
        ]
        queued: list[dict] = []

        def capture(payload):
            queued.append(payload)
            return True

        with (
            patch.object(board_store, "records_table", return_value=self.table),
            patch.object(board_catalog_bulk, "load_source_rows", return_value=rows),
            patch("board_async.try_invoke_event", side_effect=capture),
        ):
            first = board_catalog_bulk.handle_job({"action": "ingest", "source": "edb", "offset": 0})
            self.assertTrue(first["continued"])
            self.assertEqual(first["processed"], 500)
            self.assertEqual(first["upserted"], 500)
            self.assertEqual(first["remaining"], 700)
            self.assertEqual(queued[-1]["offset"], 500)
            second = board_catalog_bulk.handle_job(queued[-1])
            self.assertEqual(second["remaining"], 200)
            self.assertEqual(second["processed"], 1000)
            self.assertEqual(second["upserted"], 1000)
            third = board_catalog_bulk.handle_job(queued[-1])
            self.assertFalse(third.get("continued"))
            self.assertEqual(third["remaining"], 0)
            self.assertEqual(third["processed"], 1200)
            self.assertEqual(third["upserted"], 1200)
        self.assertEqual(len(board_store.list_candidates(self.table, "approved", per_status_limit=10_000)), 1200)
        job = board_catalog_bulk._job(self.table, "edb")
        self.assertIsNotNone(job)
        self.assertEqual(job["phase"], "done")
        self.assertEqual(job["upserted"], 1200)
        self.assertEqual(job["processed"], 1200)

    def test_needs_chunked_ingest_is_row_count_not_source(self) -> None:
        self.assertFalse(board_catalog_bulk.needs_chunked_ingest(board_catalog_bulk.INGEST_BATCH))
        self.assertTrue(board_catalog_bulk.needs_chunked_ingest(board_catalog_bulk.INGEST_BATCH + 1))

    def test_large_preview_chunks_for_any_source(self) -> None:
        rows = [
            {
                "nameEn": f"Park {i:04d}",
                "district": "Eastern",
                "sourceId": f"lcsd-{i}",
                "facilityKind": "lcsd_playground",
            }
            for i in range(600)
        ]
        queued: list[dict] = []

        def capture(payload):
            queued.append(payload)
            return True

        with (
            patch.object(board_store, "records_table", return_value=self.table),
            patch.object(board_catalog_bulk, "load_source_rows", return_value=rows),
            patch("board_async.try_invoke_event", side_effect=capture),
        ):
            out = board_catalog_bulk.handle_job({"action": "preview", "source": "lcsd"})
        self.assertTrue(out["continued"])
        self.assertEqual(out["processed"], 500)
        self.assertEqual(queued[-1]["action"], "preview")
        self.assertEqual(queued[-1]["source"], "lcsd")
        self.assertEqual(queued[-1]["offset"], 500)
        self.assertFalse(queued[-1].get("ingestDone"))

    def test_small_preview_finishes_in_one_job(self) -> None:
        os.environ["BOARD_CATALOG_IMPORT_ENABLED"] = "true"
        os.environ["BOARD_CATALOG_MANAGER_ID"] = "mgr-1"
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_IMPORT_ENABLED", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_MANAGER_ID", None))
        rows = [
            {
                "nameEn": "Little Stars KG",
                "district": "Sha Tin",
                "sourceId": "edb-1",
                "facilityKind": "edb_kindergarten",
            }
        ]
        with (
            patch.object(board_store, "records_table", return_value=self.table),
            patch.object(board_catalog_bulk, "load_source_rows", return_value=rows),
            patch("board_async.try_invoke_event", return_value=True) as invoke,
        ):
            out = board_catalog_bulk.handle_job({"action": "preview", "source": "edb"})
        self.assertFalse(out.get("continued"))
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("approved"), 1)
        self.assertEqual((out.get("ingest") or {}).get("upserted"), 1)
        invoke.assert_not_called()

    def test_official_ingest_skips_listing_mirror(self) -> None:
        board_catalog_candidates.remember_listing(
            self.table, {"name": "Quarry Bay Park Playground", "area_name": "Eastern"}
        )
        rows = [
            {
                "nameEn": "Quarry Bay Park Playground",
                "district": "Eastern",
                "sourceId": "lcsd-new",
                "facilityKind": "lcsd_playground",
            }
        ]
        with patch.object(board_catalog_bulk, "load_source_rows", return_value=rows):
            out = board_catalog_bulk.ingest_source(self.table, "lcsd")
        self.assertEqual(out["upserted"], 0)
        self.assertEqual(out["skippedDuplicates"], 1)
        self.assertEqual(board_store.list_candidates(self.table), [])

    def test_continue_failure_marks_error(self) -> None:
        rows = [
            {
                "nameEn": f"Park {i:04d}",
                "district": "Eastern",
                "sourceId": f"lcsd-{i}",
                "facilityKind": "lcsd_playground",
            }
            for i in range(600)
        ]
        with (
            patch.object(board_store, "records_table", return_value=self.table),
            patch.object(board_catalog_bulk, "load_source_rows", return_value=rows),
            patch("board_async.try_invoke_event", return_value=False),
        ):
            out = board_catalog_bulk.handle_job({"action": "ingest", "source": "lcsd"})
        self.assertFalse(out["ok"])
        self.assertIn("enqueue", out["error"])
        job = board_catalog_bulk._job(self.table, "lcsd")
        self.assertIsNotNone(job)
        self.assertEqual(job["phase"], "error")
        self.assertIn("enqueue", job["error"])
        self.assertEqual(job["offset"], 500)

    def test_import_job_skips_reingest(self) -> None:
        with (
            patch.object(board_store, "records_table", return_value=self.table),
            patch.object(board_catalog_bulk, "import_source", return_value={"ok": True, "imported": 0}) as imported,
        ):
            board_catalog_bulk.handle_job({"action": "import", "source": "lcsd", "ingestDone": True})
        imported.assert_called_once()
        self.assertTrue(imported.call_args.kwargs.get("skip_ingest"))

    def test_queue_action_skips_active_job(self) -> None:
        os.environ["BOARD_CATALOG_IMPORT_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_IMPORT_ENABLED", None))
        board_catalog_bulk._put_job(
            self.table,
            "edb",
            {"phase": "running", "action": "ingest", "at": board_store.now_iso()},
        )
        with patch("board_async.try_invoke_event", return_value=True) as invoke:
            out = board_catalog_bulk.queue_action(self.table, "preview", "edb")
        self.assertTrue(out["alreadyRunning"])
        self.assertEqual(out["action"], "ingest")
        invoke.assert_not_called()
        self.assertEqual(board_catalog_bulk._job(self.table, "edb")["action"], "ingest")

    def test_queue_action_replaces_stale_job(self) -> None:
        os.environ["BOARD_CATALOG_IMPORT_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_IMPORT_ENABLED", None))
        board_catalog_bulk._put_job(
            self.table,
            "edb",
            {"phase": "running", "action": "ingest", "at": "2020-01-01T00:00:00Z"},
        )
        with patch("board_async.try_invoke_event", return_value=True) as invoke:
            out = board_catalog_bulk.queue_action(self.table, "preview", "edb")
        self.assertFalse(out.get("alreadyRunning"))
        self.assertTrue(out["invoked"])
        invoke.assert_called_once()
        self.assertEqual(board_catalog_bulk._job(self.table, "edb")["action"], "preview")


class DiscoveryOpenDataTests(BoardTestCase):
    def _open_data_rows(self, source: str, count: int) -> list[dict]:
        kind = {
            "lcsd": "lcsd_playground",
            "edb": "edb_kindergarten",
            "swd": "swd_child_care",
        }[source]
        return [
            {
                "nameEn": f"{source} {i:04d}",
                "district": "Eastern",
                "sourceId": f"{source}-{i}",
                "facilityKind": kind,
            }
            for i in range(count)
        ]

    def test_refresh_queues_any_source_over_batch(self) -> None:
        counts = {"lcsd": board_catalog_bulk.INGEST_BATCH + 1, "edb": 1, "swd": 1}

        def load(_table, source, *, force: bool = False):
            del force
            return self._open_data_rows(source, counts[source])

        with (
            patch.object(board_catalog_bulk, "load_source_rows", side_effect=load),
            patch.object(board_opendata, "_cached", return_value={"fetchedAt": "2026-09-21T00:00:00Z"}),
            patch.object(
                board_catalog_bulk,
                "queue_action",
                return_value={"ok": True, "queued": True, "invoked": True, "action": "ingest"},
            ) as queued,
        ):
            notes = board_catalog_discovery.refresh_open_data(self.table)
        self.assertTrue(notes["lcsd"]["queued"])
        self.assertEqual(notes["lcsd"]["fetched"], board_catalog_bulk.INGEST_BATCH + 1)
        self.assertNotIn("queued", notes["edb"])
        self.assertEqual(notes["edb"]["upserted"], 1)
        queued.assert_called_once()
        self.assertEqual(queued.call_args.args[1], "ingest")
        self.assertEqual(queued.call_args.args[2], "lcsd")

    def test_refresh_ingests_small_sources_inline(self) -> None:
        def load(_table, source, *, force: bool = False):
            del force
            return self._open_data_rows(source, 1)

        with (
            patch.object(board_catalog_bulk, "load_source_rows", side_effect=load),
            patch.object(board_opendata, "_cached", return_value={"fetchedAt": "2026-09-21T00:00:00Z"}),
            patch.object(board_catalog_bulk, "queue_action") as queued,
        ):
            notes = board_catalog_discovery.refresh_open_data(self.table)
        queued.assert_not_called()
        for source in board_catalog_bulk.OPEN_DATA_SOURCES:
            self.assertEqual(notes[source]["upserted"], 1)
            self.assertNotIn("queued", notes[source])

    def test_refresh_notes_gap_when_fetch_has_no_rows(self) -> None:
        def load(_table, source, *, force: bool = False):
            del force
            return [] if source == "edb" else self._open_data_rows(source, 1)

        with (
            patch.object(board_catalog_bulk, "load_source_rows", side_effect=load),
            patch.object(board_opendata, "_cached", return_value={"fetchedAt": "2026-09-21T00:00:00Z"}),
        ):
            board_catalog_discovery.refresh_open_data(self.table)
        gaps = board_duties.list_config_gaps(self.table)
        self.assertTrue(any(g.get("gapId") == "opendata-edb" for g in gaps))

    def test_refresh_open_data_notes_gap_when_edb_empty(self) -> None:
        def load(_table, source, *, force: bool = False):
            del force
            return [] if source == "edb" else self._open_data_rows(source, 1)

        def cached(_table, name):
            if name == "opendata:edb":
                return {"fetchedAt": ""}
            return {"fetchedAt": "2026-09-21T00:00:00Z"}

        with (
            patch.object(board_catalog_bulk, "load_source_rows", side_effect=load),
            patch.object(board_opendata, "_cached", side_effect=cached),
        ):
            board_catalog_discovery.refresh_open_data(self.table)
        gaps = board_duties.list_config_gaps(self.table)
        self.assertTrue(any(g.get("gapId") == "opendata-edb" for g in gaps))

    def test_refresh_open_data_clears_gap_when_edb_ok(self) -> None:
        board_duties.note_config_gap(self.table, gap_id="opendata-edb", reason="EDB kindergarten fetch returned no rows")

        def load(_table, source, *, force: bool = False):
            del force
            return self._open_data_rows(source, 1)

        with (
            patch.object(board_catalog_bulk, "load_source_rows", side_effect=load),
            patch.object(board_opendata, "_cached", return_value={"fetchedAt": "2026-09-21T00:00:00Z"}),
        ):
            board_catalog_discovery.refresh_open_data(self.table)
        gaps = board_duties.list_config_gaps(self.table)
        self.assertFalse(any(g.get("gapId") == "opendata-edb" for g in gaps))


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
