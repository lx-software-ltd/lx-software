"""Places API cap and cache (WP6)."""

from __future__ import annotations

import json
import os
import unittest
from typing import Any
from unittest.mock import patch

import board_places
import board_store
from test_board import BoardTestCase


def _enable_staff(table: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True})
    return board_store.save_settings(table, settings)


class PlacesTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["GOOGLE_PLACES_KEY"] = "test-places-key"
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("GOOGLE_PLACES_KEY", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        board_places.reset_key_cache_for_tests()
        self.settings = _enable_staff(self.table)

    def test_cache_avoids_second_charge(self) -> None:
        payload = {
            "places": [
                {
                    "id": "ChIJtest",
                    "displayName": {"text": "Playhouse"},
                    "formattedAddress": "Sha Tin",
                    "websiteUri": "https://play.example",
                    "nationalPhoneNumber": "2345 6789",
                    "rating": 4.5,
                    "userRatingCount": 20,
                    "types": ["amusement_park"],
                }
            ]
        }
        with patch.object(board_places, "_http", return_value=payload) as http:
            first = board_places.text_search(self.table, "kids play sha tin", settings=self.settings)
            second = board_places.text_search(self.table, "kids play sha tin", settings=self.settings)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(first[0]["placeId"], "ChIJtest")
        self.assertEqual(second[0]["name"], "Playhouse")
        month = board_store.get_cache(self.table, board_places._month_key())
        self.assertAlmostEqual(float(month["payload"]["usd"]), board_places.TEXT_SEARCH_USD)

    def test_monthly_cap_refuses(self) -> None:
        board_store.put_cache(
            self.table,
            board_places._month_key(),
            {"usd": 20.0, "searches": 500, "details": 0},
            ttl_seconds=86400,
        )
        with self.assertRaises(board_places.PlacesError) as ctx:
            board_places.text_search(self.table, "anything", settings=self.settings)
        self.assertEqual(ctx.exception.payload["error"], "places monthly cap exceeded")

    def test_field_mask_constant(self) -> None:
        self.assertIn("websiteUri", board_places.FIELD_MASK)
        self.assertTrue(board_places.SEARCH_FIELD_MASK.startswith("places."))


class PlacesRouteHiddenWhenStaffOff(BoardTestCase):
    def test_prospects_409_when_env_off(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "false"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        status, body = self.call("/siu-tin-dei/board/prospects")
        self.assertEqual(status, 409)
        self.assertIn("disabled", body["message"].lower())


if __name__ == "__main__":
    unittest.main()
