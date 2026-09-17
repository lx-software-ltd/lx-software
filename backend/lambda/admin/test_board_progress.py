"""Listing / partnership progress snapshot (owner dashboard)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

from test_board import BoardTestCase

import board_content
import board_data_api
import board_hk
import board_progress
import board_store


def _enable_staff(table: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True})
    return board_store.save_settings(table, settings)


class ProgressSnapshotTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.settings = _enable_staff(self.table)
        self.catalog = [
            {
                "district": "Sha Tin",
                "category": "play",
                "activities": 12,
                "providers": 4,
                "stores": 4,
                "completeness": 0.8,
                "has_photo": 0.5,
                "has_price": 0.8,
                "has_schedule": 0.8,
                "has_geo": 1.0,
            },
            {
                "district": "Tai Po",
                "category": "sport",
                "activities": 0,
                "providers": 2,
                "stores": 0,
                "completeness": 0.1,
                "has_photo": 0.0,
                "has_price": 0.0,
                "has_schedule": 0.0,
                "has_geo": 0.4,
            },
        ]
        self.funnel = [
            {"day": board_hk.today_hkt(), "district": "Sha Tin", "searches": 40, "listing_views": 20, "cta_taps": 5, "leads_relayed": 3, "bookings_confirmed": 1},
        ]
        self.pipeline = [
            {
                "organization_id": "org-1",
                "organization_name": "Sha Tin Playhouse",
                "signed_up_on": "2026-08-01",
                "onboarding_step": "photos",
                "days_since_last_edit": 18,
                "subscription_status": "incomplete",
            },
            {
                "organization_id": "org-2",
                "organization_name": "Live Gym",
                "signed_up_on": "2026-09-01",
                "onboarding_step": "live",
                "days_since_last_edit": 1,
                "subscription_status": "active",
            },
        ]
        board_data_api.set_executor_for_tests(self._execute)
        self.addCleanup(lambda: board_data_api.set_executor_for_tests(None))

    def _execute(self, sql: str, _params: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        low = sql.lower()
        if "v_catalog_health" in low:
            return list(self.catalog)
        if "v_funnel_daily" in low:
            return list(self.funnel)
        if "v_provider_pipeline" in low:
            return list(self.pipeline)
        return []

    def test_snapshot_flags_listing_and_signing_gaps(self) -> None:
        now = datetime.now(timezone.utc)
        board_store.put_prospect(
            self.table,
            {
                "prospectId": "p-contact",
                "name": "Tai Po Hall",
                "type": "community",
                "district": "Tai Po",
                "stage": "contacted",
                "nextTouchAt": (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "createdAt": (now - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "updatedAt": (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        board_store.put_prospect(
            self.table,
            {
                "prospectId": "p-qual",
                "name": "Need Email Ltd",
                "type": "provider",
                "district": "Sha Tin",
                "stage": "qualified",
                "contact": None,
                "qualifiedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "createdAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "updatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        board_content.upsert_item(
            self.table,
            {"channel": "facebook", "copyEn": "Old draft", "template": "spotlight", "fields": {"title": "Old"}},
            status="drafted",
        )
        draft = board_store.list_content(self.table, "drafted", limit=5)[0]
        draft["slotAt"] = (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        board_store.put_content(self.table, draft)

        snap = board_progress.snapshot(self.table, self.settings)
        self.assertEqual(snap["listings"]["activities"], 12)
        self.assertAlmostEqual(snap["listings"]["hasPhotoAvg"], 0.25)
        self.assertAlmostEqual(snap["listings"]["hasPriceAvg"], 0.4)
        self.assertAlmostEqual(snap["listings"]["hasScheduleAvg"], 0.4)
        self.assertAlmostEqual(snap["listings"]["hasGeoAvg"], 0.7)
        self.assertTrue(any(g["label"] == "Tai Po" for g in snap["listings"]["gaps"]))
        tai_po = next(g for g in snap["listings"]["gaps"] if g["label"] == "Tai Po")
        self.assertIn("missing photos, price, hours, geo", tai_po["detail"])
        self.assertEqual(snap["listings"]["funnel7d"]["listingViews"], 20)
        self.assertEqual(snap["signings"]["count"], 2)
        self.assertEqual(snap["signings"]["stalled"][0]["name"], "Sha Tin Playhouse")
        self.assertGreaterEqual(snap["partnerships"]["needsContact"], 1)
        self.assertTrue(any(s["name"] == "Tai Po Hall" for s in snap["partnerships"]["stalled"]))
        ids = {b["id"] for b in snap["bottlenecks"]}
        self.assertIn("listings-gap", ids)
        self.assertIn("signings-stalled", ids)
        self.assertIn("partnerships-target", ids)
        self.assertIn("content-empty", ids)

    def test_route_returns_snapshot(self) -> None:
        status, body = self.call("/siu-tin-dei/board/progress")
        self.assertEqual(status, 200)
        self.assertIn("listings", body)
        self.assertIn("signings", body)
        self.assertIn("partnerships", body)
        self.assertIn("content", body)
        self.assertIn("bottlenecks", body)
        self.assertEqual(body["listings"]["activities"], 12)

    def test_unknown_district_is_labelled_unlinked(self) -> None:
        self.catalog = [
            {"district": "unknown", "category": "Class", "activities": 5, "providers": 5, "stores": 0, "completeness": 0.0},
            {"district": "Wan Chai", "category": "Workshop", "activities": 1, "providers": 1, "stores": 1, "completeness": 0.75},
        ]
        snap = board_progress.snapshot(self.table, self.settings)
        labels = [row["label"] for row in snap["listings"]["byDistrict"]]
        self.assertIn("No venue linked", labels)
        self.assertNotIn("unknown", labels)
        ids = {b["id"] for b in snap["bottlenecks"]}
        self.assertIn("listings-unlinked", ids)

    def test_unlinked_and_district_gap_both_listed(self) -> None:
        self.catalog = [
            {"district": "unknown", "category": "Class", "activities": 5, "providers": 5, "stores": 0, "completeness": 0.9},
            {"district": "Tai Po", "category": "sport", "activities": 0, "providers": 2, "stores": 0, "completeness": 0.1},
            {"district": "Wan Chai", "category": "Workshop", "activities": 1, "providers": 1, "stores": 1, "completeness": 0.75},
        ]
        snap = board_progress.snapshot(self.table, self.settings)
        ids = [b["id"] for b in snap["bottlenecks"]]
        self.assertIn("listings-unlinked", ids)
        self.assertIn("listings-gap", ids)
        gap = next(b for b in snap["bottlenecks"] if b["id"] == "listings-gap")
        self.assertIn("Tai Po", gap["summary"])
        self.assertNotIn("No venue linked", gap["summary"])

    def test_unavailable_product_views_become_bottlenecks(self) -> None:
        board_data_api.set_executor_for_tests(None)
        snap = board_progress.snapshot(self.table, self.settings)
        self.assertTrue(snap["listings"]["error"])
        self.assertTrue(any(b["id"] == "listings-unavailable" for b in snap["bottlenecks"]))
