"""HK ALS geocode for catalog imports."""

from __future__ import annotations

import os
import unittest

import board_catalog_import
import board_geocode
import board_store
from test_board import FakeTable


ALS_EASTERN = {
    "SuggestedAddress": [
        {
            "Address": {
                "PremisesAddress": {
                    "EngPremisesAddress": {"EngDistrict": {"DcDistrict": "EASTERN DISTRICT"}},
                    "GeospatialInformation": {"Latitude": "22.28369", "Longitude": "114.21179"},
                }
            }
        }
    ]
}


class GeocodeTests(unittest.TestCase):
    def tearDown(self) -> None:
        board_geocode.set_lookup_for_tests(None)

    def test_picks_matching_district(self) -> None:
        board_geocode.set_lookup_for_tests(lambda _addr: ALS_EASTERN)
        hit = board_geocode.lookup_address("Quarry Bay Park", district="Eastern")
        self.assertEqual(hit["lat"], 22.28369)
        self.assertEqual(hit["lng"], 114.21179)
        self.assertEqual(hit["source"], "als")

    def test_rejects_other_district(self) -> None:
        board_geocode.set_lookup_for_tests(lambda _addr: ALS_EASTERN)
        self.assertIsNone(board_geocode.lookup_address("Quarry Bay Park", district="Wan Chai"))

    def test_fail_open_on_lookup_error(self) -> None:
        def boom(_addr: str):
            raise TimeoutError("als down")

        board_geocode.set_lookup_for_tests(boom)
        self.assertIsNone(board_geocode.lookup_address("Anywhere", district="Eastern"))

    def test_fills_org_and_caches(self) -> None:
        table = FakeTable()
        board_geocode.set_lookup_for_tests(lambda _addr: ALS_EASTERN)
        org = {"name": "Park", "address": "Quarry Bay Park", "area_name": "Eastern", "vetting_note": "ok"}
        filled = board_geocode.fill_org_coords(org, district="Eastern", table=table)
        self.assertEqual(filled["lat"], 22.28369)
        self.assertIn("geocode_source=als", filled["vetting_note"])
        cached = board_store.get_cache(table, board_geocode.cache_name("Quarry Bay Park"))
        self.assertIsNotNone(cached)

    def test_transform_geocodes_verified_address_without_coords(self) -> None:
        os.environ["BOARD_CATALOG_MANAGER_ID"] = "mgr-1"
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_MANAGER_ID", None))
        table = FakeTable()
        board_geocode.set_lookup_for_tests(lambda _addr: ALS_EASTERN)
        sheet = {
            "district": "Eastern",
            "organisations": [
                {
                    "name_en": "Quarry Bay Park Playground",
                    "type": "playground",
                    "address_en": "Quarry Bay Park",
                    "verified_fields": ["name_en", "address_en"],
                }
            ],
        }
        org = board_catalog_import.transform_sheet(sheet, table=table)["organizations"][0]
        self.assertEqual(org["lat"], 22.28369)
        self.assertEqual(org["lng"], 114.21179)


if __name__ == "__main__":
    unittest.main()
