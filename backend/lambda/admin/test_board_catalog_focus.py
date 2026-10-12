"""Neighbourhood-first go-live: focus areas across catalog duties, discovery, candidates and bulk import."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

import board_async
import board_catalog
import board_catalog_bulk
import board_catalog_candidates
import board_catalog_discovery
import board_catalog_focus
import board_catalog_import
import board_places
import board_public_api
import board_routes
import board_store
from contract_constants import BOARD_CATALOG_DISTRICTS
from test_board import BoardTestCase

STANLEY_ADDRESS = "Shop 201, Stanley Plaza, 23 Carmel Road, Stanley, Hong Kong"
ABERDEEN_ADDRESS = "2 Aberdeen Praya Road, Aberdeen, Hong Kong"


def _enable(table, **catalog):
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config(
        {**(settings.get("staff") or {}), "enabled": True, "dutiesEnabled": True, "maxRunningTasks": 20}
    )
    settings["catalog"] = board_store.normalize_catalog_config({**(settings.get("catalog") or {}), **catalog})
    return board_store.save_settings(table, settings)


class FocusModuleTests(unittest.TestCase):
    def test_default_is_stanley_then_hong_kong_island(self) -> None:
        self.assertEqual(board_catalog_focus.focus_area_ids({}), ["stanley"])
        # Membership stays Stanley's district; the go-live order is rotation only.
        self.assertEqual(board_catalog_focus.focus_district_names({}), ["Southern"])
        self.assertEqual(
            board_catalog_focus.priority_district_names({}),
            ["Southern", "Central and Western", "Wan Chai", "Eastern"],
        )
        self.assertEqual(board_catalog_focus.focus_label({}), "Stanley (Southern)")
        self.assertEqual(board_catalog_focus.focus_area_ids(None), ["stanley"])
        # An explicit empty district list keeps the contract order after the areas.
        self.assertEqual(board_catalog_focus.priority_district_names({"catalog": {"focusDistricts": []}}), ["Southern"])
        # No focus at all: nothing is in focus, but the rotation still follows the plan.
        no_focus = {"catalog": {"focusAreas": []}}
        self.assertFalse(board_catalog_focus.has_focus(no_focus))
        self.assertEqual(board_catalog_focus.priority_district_names(no_focus)[0], "Southern")

    def test_default_district_order_follows_the_go_live_plan(self) -> None:
        contract_ids = [row["id"] for row in BOARD_CATALOG_DISTRICTS]
        self.assertEqual(len(contract_ids), 18)
        ordered = [row["id"] for row in board_catalog_focus.order_districts(None, {})]
        self.assertEqual(ordered[:4], ["southern", "central-and-western", "wan-chai", "eastern"])
        self.assertEqual(sorted(ordered), sorted(contract_ids))
        areas = board_catalog_focus.areas()
        self.assertEqual(areas[0]["id"], "stanley")
        self.assertTrue(all(a.get("district") for a in areas))
        contract_names = {row["name"] for row in BOARD_CATALOG_DISTRICTS}
        self.assertTrue(all(a["district"] in contract_names for a in areas))
        self.assertTrue(all(d in contract_names for d in board_catalog_focus.DEFAULT_FOCUS_DISTRICTS))
        self.assertTrue(board_catalog_focus.focus_queries())
        self.assertEqual(board_catalog_focus.category_for_kind("places_sport"), "Sport")
        self.assertEqual(board_catalog_focus.category_for_kind("places_playground"), "")

    def test_owner_settings_override_and_empty_means_no_focus(self) -> None:
        settings = {"catalog": {"focusAreas": ["repulse-bay", "stanley"]}}
        self.assertEqual(board_catalog_focus.focus_area_ids(settings), ["repulse-bay", "stanley"])
        self.assertEqual(board_catalog_focus.focus_area_ids({"catalog": {"focusAreas": []}}), [])
        self.assertFalse(board_catalog_focus.has_focus({"catalog": {"focusAreas": []}}))
        self.assertEqual(
            board_catalog_focus.focus_district_names({"catalog": {"focusAreas": [], "focusDistricts": ["Wan Chai"]}}),
            ["Wan Chai"],
        )
        self.assertEqual(board_catalog_focus.focus_area_ids({"catalog": {"focusAreas": ["nowhere"]}}), [])

    def test_order_districts_moves_focus_districts_first(self) -> None:
        rows = [{"id": "a", "name": "Eastern"}, {"id": "b", "name": "Wan Chai"}, {"id": "c", "name": "Southern"}]
        ordered = board_catalog_focus.order_districts(rows, {})
        self.assertEqual([r["id"] for r in ordered], ["c", "b", "a"])
        unchanged = board_catalog_focus.order_districts(rows, {"catalog": {"focusAreas": [], "focusDistricts": []}})
        self.assertEqual([r["id"] for r in unchanged], ["a", "b", "c"])
        explicit = board_catalog_focus.order_districts(rows, {"catalog": {"focusAreas": [], "focusDistricts": ["Wan Chai"]}})
        self.assertEqual([r["id"] for r in explicit], ["b", "a", "c"])
        self.assertEqual(
            board_catalog_focus.order_district_names(["Eastern", "Southern"], {}),
            ["Southern", "Eastern"],
        )

    def test_area_from_address_name_alias_chinese_and_point(self) -> None:
        self.assertEqual(board_catalog_focus.area_for({"addressEn": STANLEY_ADDRESS}), "stanley")
        self.assertEqual(board_catalog_focus.area_for({"addressEn": "Chung Hom Kok Road, Hong Kong"}), "stanley")
        self.assertEqual(board_catalog_focus.area_for({"addressZh": "赤柱佳美道23號"}), "stanley")
        self.assertEqual(board_catalog_focus.area_for({"lat": 22.2195, "lng": 114.2140}), "stanley")
        self.assertEqual(board_catalog_focus.area_for({"addressEn": ABERDEEN_ADDRESS}), "aberdeen")
        self.assertEqual(board_catalog_focus.area_for({"addressEn": "Nathan Road, Mong Kok"}), "")

    def test_area_rejects_false_friends_and_district_mismatch(self) -> None:
        self.assertEqual(
            board_catalog_focus.area_for({"addressEn": "3/F, 10 Stanley Street, Central", "district": "Central and Western"}),
            "central",
        )
        self.assertEqual(board_catalog_focus.area_for({"addressEn": "Stanley Street, Hong Kong"}), "")
        # A Stanley-named address stored under another district is not a Stanley row.
        self.assertEqual(board_catalog_focus.area_for({"addressEn": STANLEY_ADDRESS, "district": "Eastern"}), "")
        # A stored area id wins when it is a known area.
        self.assertEqual(board_catalog_focus.area_for({"area": "shek-o", "addressEn": STANLEY_ADDRESS}), "shek-o")

    def test_is_focus_row_by_area_then_by_district(self) -> None:
        self.assertTrue(board_catalog_focus.is_focus_row({"addressEn": STANLEY_ADDRESS, "district": "Southern"}, {}))
        self.assertFalse(board_catalog_focus.is_focus_row({"addressEn": ABERDEEN_ADDRESS, "district": "Southern"}, {}))
        district_only = {"catalog": {"focusAreas": [], "focusDistricts": ["Southern"]}}
        self.assertTrue(board_catalog_focus.is_focus_row({"addressEn": ABERDEEN_ADDRESS, "district": "Southern"}, district_only))
        self.assertFalse(board_catalog_focus.is_focus_row({"district": "Eastern"}, district_only))

    def test_normalize_focus_settings_strict_and_lenient(self) -> None:
        out: dict = {}
        board_catalog_focus.normalize_focus_settings({"focusAreas": ["Stanley", "stanley", "bogus"]}, out)
        self.assertEqual(out["focusAreas"], ["stanley"])
        with self.assertRaises(ValueError):
            board_catalog_focus.normalize_focus_settings({"focusAreas": ["bogus"]}, {}, strict=True)
        with self.assertRaises(ValueError):
            board_catalog_focus.normalize_focus_settings({"focusAreas": "stanley"}, {}, strict=True)
        out = {}
        board_catalog_focus.normalize_focus_settings({"focusDistricts": ["southern", "Nowhere"]}, out)
        self.assertEqual(out["focusDistricts"], ["Southern"])
        with self.assertRaises(ValueError):
            board_catalog_focus.normalize_focus_settings({"focusDistricts": ["Nowhere"]}, {}, strict=True)
        # null drops the key (back to the contract default); [] is an explicit no-focus.
        out = {}
        board_catalog_focus.normalize_focus_settings({"focusAreas": None}, out)
        self.assertNotIn("focusAreas", out)
        out = {}
        board_catalog_focus.normalize_focus_settings({"focusAreas": []}, out)
        self.assertEqual(out["focusAreas"], [])

    def test_store_normalize_keeps_focus_and_validate_settings_rejects_unknown(self) -> None:
        cfg = board_store.normalize_catalog_config({"focusAreas": ["stanley"], "focusDistricts": ["Wan Chai"]})
        self.assertEqual(cfg["focusAreas"], ["stanley"])
        self.assertEqual(cfg["focusDistricts"], ["Wan Chai"])
        current = board_store.default_settings() if hasattr(board_store, "default_settings") else {}
        with self.assertRaises(ValueError):
            board_routes.validate_settings({"catalog": {"focusAreas": ["bogus"]}}, current)


class FocusDutyTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))

    def test_first_sheet_is_the_stanley_neighbourhood_then_southern_then_hk_island(self) -> None:
        settings = _enable(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            first = board_catalog.create_next(self.table, settings)
            second = board_catalog.create_next(self.table, settings)
            third = board_catalog.create_next(self.table, settings)
        self.assertEqual(first["eventRef"]["districtId"], "southern")
        self.assertEqual(first["eventRef"]["areaId"], "stanley")
        self.assertEqual(first["eventRef"]["id"], "catalog:southern:stanley")
        self.assertIn("CATALOG MICRO-BATCH Stanley (Southern)", first["brief"])
        self.assertIn("FOCUS", first["brief"])
        self.assertIn("Chung Hom Kok", first["brief"])
        self.assertEqual(second["eventRef"]["districtId"], "southern")
        self.assertNotIn("areaId", second["eventRef"])
        self.assertNotIn("FOCUS", second["brief"])
        self.assertEqual(third["eventRef"]["districtId"], "central-and-western")

    def test_focus_sheet_is_claimed_once(self) -> None:
        settings = _enable(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_catalog.create_next(self.table, settings)
        self.assertIn("southern:stanley", board_catalog.claimed_district_ids(self.table))
        nxt = board_catalog.next_district(self.table, settings, enforce_completeness_gate=False)
        self.assertEqual(nxt["id"], "southern")
        self.assertNotIn("areaId", nxt)

    def test_coverage_reports_focus_and_next_label(self) -> None:
        _enable(self.table)
        coverage = board_catalog_import.catalog_coverage(self.table)
        self.assertEqual(coverage["nextDistrict"], "Stanley (Southern)")
        self.assertEqual(coverage["focus"], "Stanley (Southern)")

    def test_owner_can_move_focus_to_the_next_neighbourhood(self) -> None:
        settings = _enable(self.table, focusAreas=["repulse-bay"])
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            first = board_catalog.create_next(self.table, settings)
        self.assertEqual(first["eventRef"]["areaId"], "repulse-bay")
        self.assertIn("Repulse Bay (Southern)", first["brief"])


class FocusCandidateTests(BoardTestCase):
    def _places_row(self, name: str, address: str, **extra) -> dict:
        return {
            "source": "places",
            "placeId": "ChIJ" + name.replace(" ", ""),
            "nameEn": name,
            "addressEn": address,
            "district": "Southern",
            "officialUrl": "https://" + name.replace(" ", "").lower() + ".example",
            "types": ["point_of_interest", "establishment"],
            "facilityKind": "places_class",
            **extra,
        }

    def test_upsert_stamps_area_and_relaxes_auto_approve_inside_the_focus(self) -> None:
        stanley = board_catalog_candidates.upsert_candidate(self.table, self._places_row("Stanley Art Kids", STANLEY_ADDRESS))
        self.assertEqual(stanley["area"], "stanley")
        self.assertEqual(stanley["status"], "approved")
        self.assertEqual(stanley["category"], "Class")
        aberdeen = board_catalog_candidates.upsert_candidate(self.table, self._places_row("Aberdeen Art Kids", ABERDEEN_ADDRESS))
        self.assertEqual(aberdeen["area"], "aberdeen")
        self.assertEqual(aberdeen["status"], "new")
        social = board_catalog_candidates.upsert_candidate(
            self.table,
            self._places_row("Stanley FB Club", STANLEY_ADDRESS, officialUrl="https://www.facebook.com/stanleyfb"),
        )
        self.assertEqual(social["status"], "new")
        no_focus = {"catalog": {"focusAreas": []}}
        plain = board_catalog_candidates.upsert_candidate(
            self.table, self._places_row("Stanley Music Kids", STANLEY_ADDRESS), settings=no_focus
        )
        self.assertEqual(plain["status"], "new")

    def test_filter_by_area(self) -> None:
        board_catalog_candidates.upsert_candidate(self.table, self._places_row("Stanley Art Kids", STANLEY_ADDRESS))
        board_catalog_candidates.upsert_candidate(self.table, self._places_row("Aberdeen Art Kids", ABERDEEN_ADDRESS))
        page = board_catalog_candidates.list_filtered(self.table, None, area="stanley")
        self.assertEqual([r["nameEn"] for r in page["candidates"]], ["Stanley Art Kids"])
        self.assertEqual(page["total"], 1)

    def test_add_manual_validates_dedupes_and_honours_status(self) -> None:
        with self.assertRaises(ValueError):
            board_catalog_candidates.add_manual(self.table, {"addressEn": STANLEY_ADDRESS})
        with self.assertRaises(ValueError):
            board_catalog_candidates.add_manual(self.table, {"nameEn": "Nowhere Club"})
        with self.assertRaises(ValueError):
            board_catalog_candidates.add_manual(self.table, {"nameEn": "X", "district": "Southern", "category": "Restaurant"})
        with self.assertRaises(ValueError):
            board_catalog_candidates.add_manual(self.table, {"nameEn": "X", "district": "Southern", "officialUrl": "stanleykids.example"})
        doc = board_catalog_candidates.add_manual(
            self.table,
            {
                "nameEn": "Stanley Sailing Juniors",
                "addressEn": STANLEY_ADDRESS,
                "officialUrl": "https://stanleysailing.example",
                "category": "sports",
                "sourceUrl": "https://competitor.example/stanley",
                "note": "found on a competitor listing",
            },
            added_by="api-key",
        )
        self.assertEqual(doc["source"], "manual")
        self.assertEqual(doc["district"], "Southern")
        self.assertEqual(doc["area"], "stanley")
        self.assertEqual(doc["category"], "Sport")
        self.assertEqual(doc["status"], "approved")
        self.assertTrue(doc["sourceId"].startswith("manual:"))
        self.assertEqual(doc["sourceUrl"], "https://competitor.example/stanley")
        again = board_catalog_candidates.add_manual(
            self.table,
            {"nameEn": "Stanley Sailing Juniors", "district": "Southern", "phone": "2813 0000"},
        )
        self.assertEqual(again["candidateId"], doc["candidateId"])
        self.assertEqual(again["phone"], "2813 0000")
        self.assertEqual(len(board_store.list_candidates(self.table)), 1)
        # No website: stays on the owner queue unless the caller says approved.
        queued = board_catalog_candidates.add_manual(
            self.table, {"nameEn": "Stanley Beach Playgroup", "area": "stanley"}
        )
        self.assertEqual(queued["status"], "new")
        self.assertEqual(queued["district"], "Southern")
        forced = board_catalog_candidates.add_manual(
            self.table, {"nameEn": "Stanley Library Storytime", "area": "stanley", "status": "approved"}
        )
        self.assertEqual(forced["status"], "approved")
        # Website plus address would auto-approve; an explicit "new" keeps it on the queue.
        held = board_catalog_candidates.add_manual(
            self.table,
            {
                "nameEn": "Stanley Hoops Juniors",
                "addressEn": STANLEY_ADDRESS,
                "officialUrl": "https://hoops.example/stanley",
                "status": "new",
            },
        )
        self.assertEqual(held["status"], "new")
        self.assertEqual(held["area"], "stanley")

    def test_add_manual_skips_names_already_live(self) -> None:
        board_catalog_candidates.remember_listing(self.table, {"name": "Stanley Art Kids", "area_name": "Southern"})
        out = board_catalog_candidates.add_manual(self.table, {"nameEn": "Stanley Art Kids", "district": "Southern"})
        self.assertTrue(out["skipped"])
        self.assertEqual(board_store.list_candidates(self.table), [])

    def test_manual_route_is_key_allowed_and_returns_201(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        body = {"nameEn": "Stanley Sailing Juniors", "addressEn": STANLEY_ADDRESS, "officialUrl": "https://stanleysailing.example"}
        event = self.event("/siu-tin-dei/board/catalog/candidates", "POST", body)
        resp = board_routes.handle_board_route(event, "POST", "/siu-tin-dei/board/catalog/candidates", "owner")
        self.assertEqual(resp["statusCode"], 201)
        payload = json.loads(resp["body"])
        self.assertEqual(payload["candidate"]["area"], "stanley")
        bad = self.event("/siu-tin-dei/board/catalog/candidates", "POST", {"district": "Southern"})
        resp = board_routes.handle_board_route(bad, "POST", "/siu-tin-dei/board/catalog/candidates", "owner")
        self.assertEqual(resp["statusCode"], 400)
        self.assertFalse(board_public_api.write_blocked("POST", "/public/siu-tin-dei/board/catalog/candidates"))
        self.assertTrue(board_public_api.write_blocked("POST", "/public/siu-tin-dei/board/catalog/candidates/bulk"))


class FocusDiscoveryTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = _enable(self.table)

    def test_discover_area_queries_the_circle_without_included_type_and_caches(self) -> None:
        payload = {
            "places": [
                {
                    "id": "ChIJstanleyart",
                    "displayName": {"text": "Stanley Art Kids"},
                    "formattedAddress": STANLEY_ADDRESS,
                    "location": {"latitude": 22.219, "longitude": 114.213},
                    "websiteUri": "https://stanleyartkids.example",
                    "types": ["point_of_interest"],
                }
            ]
        }
        area = board_catalog_focus.area_by_id("stanley")
        queries = [("kids art class", "places_class"), ("kids swimming lessons", "places_sport")]
        with patch.object(board_places, "_http", return_value=payload) as http, patch.object(
            board_places, "_api_key", return_value="k"
        ):
            first = board_places.discover_area(self.table, area, queries, settings=self.settings)
            second = board_places.discover_area(self.table, area, queries, settings=self.settings)
        self.assertEqual(http.call_count, 2)
        body = json.loads(http.call_args.kwargs["body"].decode("utf-8"))
        self.assertNotIn("includedType", body)
        self.assertEqual(body["locationBias"]["circle"]["radius"], 2500.0)
        self.assertIn("Stanley Hong Kong", body["textQuery"])
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["area"], "stanley")
        self.assertEqual(first[0]["district"], "Southern")
        self.assertEqual(first[0]["lat"], 22.219)
        self.assertEqual(first[0]["facilityKind"], "places_class")
        self.assertEqual([p["placeId"] for p in second], [p["placeId"] for p in first])
        self.assertEqual(float(second[0]["lat"]), 22.219)

    def test_focus_sweep_keeps_only_places_inside_the_area(self) -> None:
        places = [
            {
                "placeId": "ChIJinside",
                "name": "Stanley Art Kids",
                "address": STANLEY_ADDRESS,
                "lat": 22.219,
                "lng": 114.213,
                "website": "https://stanleyartkids.example",
                "types": ["point_of_interest"],
                "facilityKind": "places_class",
                "district": "Southern",
                "area": "stanley",
            },
            {
                "placeId": "ChIJoutside",
                "name": "Causeway Dance Studio",
                "address": "5 Yee Wo Street, Causeway Bay, Hong Kong",
                "lat": 22.2801,
                "lng": 114.1855,
                "website": "https://causewaydance.example",
                "types": ["point_of_interest"],
                "facilityKind": "places_class",
                "district": "Southern",
                "area": "stanley",
            },
        ]
        with patch.object(board_places, "discover_area", return_value=places) as sweep, patch.object(
            board_places, "discover", return_value=[]
        ):
            out = board_catalog_discovery.discover_places(self.table, self.settings)
        sweep.assert_called_once()
        self.assertEqual(out["focusAreas"], ["stanley"])
        self.assertEqual(out["focusUpserted"], 1)
        rows = board_store.list_candidates(self.table)
        self.assertEqual([r["nameEn"] for r in rows], ["Stanley Art Kids"])
        self.assertEqual(rows[0]["area"], "stanley")
        self.assertEqual(rows[0]["status"], "approved")
        self.assertEqual(rows[0]["lat"], 22.219)

    def test_explicit_districts_skip_the_focus_sweep(self) -> None:
        with patch.object(board_places, "discover_area") as sweep, patch.object(board_places, "discover", return_value=[]):
            out = board_catalog_discovery.discover_places(self.table, self.settings, districts=["Eastern"])
        sweep.assert_not_called()
        self.assertEqual(out["focusAreas"], [])

    def test_no_focus_means_no_sweep(self) -> None:
        settings = _enable(self.table, focusAreas=[])
        with patch.object(board_places, "discover_area") as sweep, patch.object(board_places, "discover", return_value=[]):
            board_catalog_discovery.discover_places(self.table, settings)
        sweep.assert_not_called()


class FocusBulkTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_CATALOG_IMPORT_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_IMPORT_ENABLED", None))

    def _approved(self, name: str, address: str, district: str, source: str = "places") -> dict:
        return board_catalog_candidates.upsert_candidate(
            self.table,
            {
                "source": source,
                "sourceId": "id-" + name.replace(" ", ""),
                "placeId": "ChIJ" + name.replace(" ", ""),
                "nameEn": name,
                "addressEn": address,
                "district": district,
                "officialUrl": "https://" + name.replace(" ", "").lower() + ".example",
                "openingHours": "Mon-Sun 09:00-18:00",
                "types": ["point_of_interest"],
                "facilityKind": "places_class",
            },
        )

    def test_approved_rows_are_ordered_focus_area_then_focus_district(self) -> None:
        settings = _enable(self.table)
        self._approved("Eastern Kids", "Quarry Bay, Hong Kong", "Eastern")
        self._approved("Aberdeen Kids", ABERDEEN_ADDRESS, "Southern")
        self._approved("Stanley Kids", STANLEY_ADDRESS, "Southern")
        rows = board_catalog_bulk._approved_for_source(self.table, "places", settings)  # noqa: SLF001
        self.assertEqual([r["nameEn"] for r in rows], ["Stanley Kids", "Aberdeen Kids", "Eastern Kids"])
        no_focus = _enable(self.table, focusAreas=[])
        plain = board_catalog_bulk._approved_for_source(self.table, "places", no_focus)  # noqa: SLF001
        self.assertEqual(len(plain), 3)

    def test_focus_counts_and_sources_status(self) -> None:
        settings = _enable(self.table)
        self._approved("Stanley Kids", STANLEY_ADDRESS, "Southern")
        self._approved("Aberdeen Kids", ABERDEEN_ADDRESS, "Southern")
        board_catalog_candidates.add_manual(
            self.table, {"nameEn": "Stanley Sailing Juniors", "area": "stanley", "status": "approved"}, settings=settings
        )
        focus = board_catalog_bulk.focus_counts(self.table, settings)
        self.assertEqual(focus["label"], "Stanley (Southern)")
        self.assertEqual(focus["approved"], 2)
        self.assertEqual(focus["bySource"]["places"]["approved"], 1)
        self.assertEqual(focus["bySource"]["manual"]["approved"], 1)
        status = board_catalog_bulk.sources_status(self.table)
        self.assertEqual(status["focus"]["approved"], 2)
        self.assertIn("manual", [s["id"] for s in status["sources"]])
        payload = board_catalog_bulk.load_source_payload(self.table, "manual")
        self.assertEqual(payload["rowCount"], 1)

    def test_focus_rows_bypass_the_launch_target_and_the_50_row_gate(self) -> None:
        settings = _enable(self.table, autoImport=True)
        self._approved("Stanley Kids", STANLEY_ADDRESS, "Southern")
        self._approved("Stanley Swim", "Stanley Main Beach, Stanley, Hong Kong", "Southern")
        self._approved("Eastern Kids", "Quarry Bay, Hong Kong", "Eastern")
        with (
            patch.object(board_catalog_import, "configured", return_value=True),
            patch.object(board_catalog_import, "import_enabled", return_value=True),
            patch.object(board_catalog_bulk, "auto_import_row_limit", return_value=0),
            patch.object(board_async, "try_invoke_event", return_value=True),
        ):
            out = board_catalog_bulk.maybe_queue_auto_imports(self.table, settings)
        self.assertEqual(out.get("queued"), ["places"])
        self.assertTrue(out.get("focus"))
        self.assertEqual(out.get("limit"), 2)
        holds = board_store.list_holds(self.table, "scheduled", limit=20)
        self.assertEqual(len(holds), 1)
        self.assertEqual((holds[0].get("arguments") or {}).get("limit"), 2)

    def test_without_focus_rows_the_launch_target_still_blocks(self) -> None:
        settings = _enable(self.table, autoImport=True)
        self._approved("Eastern Kids", "Quarry Bay, Hong Kong", "Eastern")
        with (
            patch.object(board_catalog_import, "configured", return_value=True),
            patch.object(board_catalog_import, "import_enabled", return_value=True),
            patch.object(board_catalog_bulk, "auto_import_row_limit", return_value=0),
        ):
            out = board_catalog_bulk.maybe_queue_auto_imports(self.table, settings)
        self.assertEqual(out.get("queued"), [])
        self.assertEqual(out.get("reason"), "launch target reached")


if __name__ == "__main__":
    unittest.main()
