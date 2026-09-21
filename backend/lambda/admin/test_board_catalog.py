"""Unit tests for catalog micro-batch duty."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from test_board import BoardTestCase

import board_async
import board_catalog
import board_catalog_import
import board_duties
import board_hk
import board_research
import board_staff
import board_store
from contract_constants import (
    BOARD_CATALOG_DISTRICTS,
    BOARD_CATALOG_FETCH_CAP,
    BOARD_CATALOG_OUTPUT_CONTRACT,
)


def _enable(table, **staff):
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config(
        {**(settings.get("staff") or {}), "enabled": True, "dutiesEnabled": True, **staff}
    )
    return board_store.save_settings(table, settings)


def _seed_imported_orgs(table, district, names):
    task = {
        "taskId": f"seed-{district['id']}",
        "status": "delivered",
        "assignee": "content-marketer",
        "eventRef": {
            "kind": "catalog-micro-batch",
            "districtId": district["id"],
            "district": district["name"],
        },
        "importPreview": {"payload": {"organizations": [{"name": name} for name in names]}},
        "createdAt": "2026-09-01T00:00:00Z",
        "updatedAt": "2026-09-01T00:00:00Z",
    }
    board_store.put_task(table, task)
    return task


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

    def test_create_next_paused_when_micro_batch_off(self) -> None:
        settings = _enable(self.table)
        settings["catalog"] = board_store.normalize_catalog_config({"microBatchEnabled": False})
        settings = board_store.save_settings(self.table, settings)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with self.assertRaises(board_staff.StaffError) as ctx:
            board_catalog.create_next(self.table, settings)
        self.assertIn("micro-batch paused", str(ctx.exception))

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

    def test_compose_brief_prefers_lcsd_hint(self) -> None:
        district = BOARD_CATALOG_DISTRICTS[0]
        brief = board_catalog.compose_brief(district)
        self.assertIn("LCSD", district["hint"])
        self.assertIn(district["hint"], brief)
        self.assertIn("address_en", brief)
        self.assertIn("opening_hours", brief)
        self.assertIn("free_or_paid", brief)

    def test_create_enrich_targets_imported_low_district(self) -> None:
        settings = _enable(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        district = BOARD_CATALOG_DISTRICTS[0]
        _seed_imported_orgs(self.table, district, ["Quarry Bay Park Playground"])
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            enrich = board_catalog.create_enrich(self.table, settings)
        self.assertEqual(enrich["eventRef"]["kind"], "catalog-enrich")
        self.assertEqual(enrich["eventRef"]["districtId"], district["id"])
        self.assertIn("CATALOG DESCRIBE", enrich["brief"])
        self.assertIn("Quarry Bay Park Playground", enrich["brief"])
        self.assertIn("copy each name_en into verified_fields", enrich["brief"])
        self.assertTrue(BOARD_CATALOG_OUTPUT_CONTRACT[:40] in enrich["brief"])

    def test_enrich_cooldown_uses_created_at_not_updated_at(self) -> None:
        district = BOARD_CATALOG_DISTRICTS[0]
        old = (datetime.now(timezone.utc) - timedelta(hours=49)).strftime("%Y-%m-%dT%H:%M:%SZ")
        recent = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        board_store.put_task(
            self.table,
            {
                "taskId": "enrich-stale",
                "status": "needs_owner",
                "assignee": "content-marketer",
                "eventRef": {
                    "kind": "catalog-enrich",
                    "districtId": district["id"],
                    "district": district["name"],
                },
                "createdAt": old,
                "updatedAt": recent,
            },
        )
        self.assertNotIn(district["id"], board_catalog.enrich_recently_blocked_ids(self.table))
        board_store.put_task(
            self.table,
            {
                "taskId": "enrich-fresh",
                "status": "needs_owner",
                "assignee": "content-marketer",
                "eventRef": {
                    "kind": "catalog-enrich",
                    "districtId": district["id"],
                    "district": district["name"],
                },
                "createdAt": recent,
                "updatedAt": recent,
            },
        )
        self.assertIn(district["id"], board_catalog.enrich_recently_blocked_ids(self.table))

    def test_create_enrich_skips_district_without_imported_names(self) -> None:
        settings = _enable(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            board_catalog.create_next(self.table, settings)
            with self.assertRaises(board_staff.StaffError) as ctx:
                board_catalog.create_enrich(self.table, settings)
        self.assertIn("no district needs enrich", str(ctx.exception))

    def test_enrich_duty_fires_on_half_hour_slot(self) -> None:
        settings = _enable(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        morning = datetime(2026, 9, 16, 8, 0, tzinfo=board_hk.HKT)
        enrich_slot = datetime(2026, 9, 16, 8, 30, tzinfo=board_hk.HKT)
        yesterday = datetime(2026, 9, 15, 16, 30, tzinfo=board_hk.HKT)
        board_store.put_cache(
            self.table,
            "duty:content-marketer:catalog-enrich",
            {"ranAt": board_hk.to_iso(yesterday), "scheduledAt": board_hk.to_iso(yesterday)},
        )
        parsed = board_duties.parse_cron("30 8,12,16 * * *")
        self.assertFalse(board_duties.matches(parsed, morning))
        self.assertTrue(board_duties.matches(parsed, enrich_slot))
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            first = board_duties.run_due(self.table, settings, now=morning)
            for task in first:
                if (task.get("eventRef") or {}).get("kind") == "catalog-micro-batch":
                    task["status"] = "delivered"
                    task["importPreview"] = {
                        "payload": {"organizations": [{"name": "Quarry Bay Park Playground"}]}
                    }
                    board_store.put_task(self.table, task)
            second = board_duties.run_due(self.table, settings, now=enrich_slot)
        self.assertTrue(any((t.get("eventRef") or {}).get("kind") == "catalog-micro-batch" for t in first))
        self.assertFalse(any((t.get("eventRef") or {}).get("kind") == "catalog-enrich" for t in first))
        enrich = [t for t in second if (t.get("eventRef") or {}).get("kind") == "catalog-enrich"]
        self.assertEqual(len(enrich), 1)
        self.assertEqual(enrich[0]["eventRef"]["districtId"], BOARD_CATALOG_DISTRICTS[0]["id"])

    def test_catalog_duties_skip_when_budget_breaker_tripped(self) -> None:
        import board_breakers

        settings = _enable(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        board_breakers.trip(self.table, "budget", "OpenRouter 402: no credits")
        when = datetime(2026, 9, 16, 8, 0, tzinfo=board_hk.HKT)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            created = board_duties.run_due(self.table, settings, now=when)
        self.assertEqual(
            [t for t in created if (t.get("eventRef") or {}).get("kind") in ("catalog-micro-batch", "catalog-enrich")],
            [],
        )

    def test_completeness_gate_pauses_new_districts(self) -> None:
        settings = _enable(self.table, maxRunningTasks=20)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            created = [board_catalog.create_next(self.table, settings) for _ in range(4)]
        board_store.put_cache(
            self.table,
            "product:catalog_health",
            {
                "rows": [
                    {
                        "district": (task.get("eventRef") or {}).get("district"),
                        "category": "Outdoor activity",
                        "activities": 3,
                        "completeness": 0.2,
                    }
                    for task in created
                ]
            },
        )
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            with self.assertRaises(board_staff.StaffError) as ctx:
                board_catalog.create_next(self.table, settings)
        self.assertIn("below 50% completeness", str(ctx.exception))
        self.assertEqual(board_catalog.low_completeness_imported_count(self.table), 4)

    def test_completeness_gate_ignores_missing_scores(self) -> None:
        settings = _enable(self.table, maxRunningTasks=20)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            for _ in range(4):
                board_catalog.create_next(self.table, settings)
            fifth = board_catalog.create_next(self.table, settings)
        self.assertEqual(board_catalog.low_completeness_imported_count(self.table), 0)
        self.assertEqual(fifth["eventRef"]["districtId"], BOARD_CATALOG_DISTRICTS[4]["id"])

    def test_completeness_gate_allows_next_when_imported_are_healthy(self) -> None:
        settings = _enable(self.table, maxRunningTasks=20)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            created = [board_catalog.create_next(self.table, settings) for _ in range(4)]
        rows = [
            {
                "district": (task.get("eventRef") or {}).get("district"),
                "category": "Outdoor activity",
                "activities": 3,
                "providers": 3,
                "stores": 3,
                "completeness": 0.8,
            }
            for task in created
        ]
        board_store.put_cache(self.table, "product:catalog_health", {"rows": rows})
        self.assertEqual(board_catalog.low_completeness_imported_count(self.table), 0)
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            fifth = board_catalog.create_next(self.table, settings)
        self.assertEqual(fifth["eventRef"]["districtId"], BOARD_CATALOG_DISTRICTS[4]["id"])

    def test_high_completeness_district_is_not_enriched(self) -> None:
        settings = _enable(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            first = board_catalog.create_next(self.table, settings)
        board_store.put_cache(
            self.table,
            "product:catalog_health",
            {
                "rows": [
                    {
                        "district": first["eventRef"]["district"],
                        "category": "Outdoor activity",
                        "activities": 3,
                        "completeness": 0.75,
                    }
                ]
            },
        )
        with self.assertRaises(board_staff.StaffError) as ctx:
            board_catalog.create_enrich(self.table, settings)
        self.assertIn("no district needs enrich", str(ctx.exception))

    def test_handoff_skips_lcsd_and_opens_provider_success(self) -> None:
        settings = _enable(self.table)
        board_store.save_staff_override(self.table, "provider-success", {"isActive": True})
        task = {
            "eventRef": {"kind": "catalog-enrich", "district": "Eastern", "districtId": "eastern"},
        }
        sheet = {
            "district": "Eastern",
            "organisations": [
                {
                    "name_en": "Quarry Bay Park Playground",
                    "type": "playground",
                    "official_url": "https://www.lcsd.gov.hk/en/parks/qbp.html",
                },
                {
                    "name_en": "Kidz Club",
                    "type": "class",
                    "official_url": "https://kidzclub.example/wan-chai",
                },
            ],
        }
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            created = board_catalog.handoff_commercial_providers(self.table, settings, task, sheet)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["assignee"], "provider-success")
        self.assertEqual(created[0]["eventRef"]["kind"], "catalog-handoff")
        self.assertEqual(created[0]["eventRef"]["name"], "Kidz Club")
        self.assertFalse(board_catalog.is_commercial_org(sheet["organisations"][0]))
        self.assertTrue(board_catalog.is_commercial_org(sheet["organisations"][1]))
        self.assertFalse(
            board_catalog.is_commercial_org(
                {
                    "name_en": "St John's Church Family Centre",
                    "type": "class",
                    "official_url": "https://stjohns.example/family",
                }
            )
        )
        self.assertFalse(
            board_catalog.is_commercial_org(
                {
                    "name_en": "Eastern Youth Association",
                    "type": "class",
                    "official_url": "https://eya.org.hk/classes",
                }
            )
        )

    def test_micro_batch_accept_does_not_handoff(self) -> None:
        settings = _enable(self.table)
        task = {"eventRef": {"kind": "catalog-micro-batch", "district": "Eastern"}}
        sheet = {
            "organisations": [
                {"name_en": "Kidz Club", "type": "class", "official_url": "https://kidzclub.example"}
            ]
        }
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            created = board_catalog.handoff_commercial_providers(self.table, settings, task, sheet)
        self.assertEqual(created, [])

    def test_catalog_coverage_counts_imported_and_next(self) -> None:
        settings = _enable(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            first = board_catalog.create_next(self.table, settings)
        board_store.put_cache(
            self.table,
            "product:catalog_health",
            {
                "rows": [
                    {
                        "district": first["eventRef"]["district"],
                        "category": "Outdoor activity",
                        "activities": 3,
                        "completeness": 0.25,
                    }
                ]
            },
        )
        coverage = board_catalog_import.catalog_coverage(self.table)
        self.assertEqual(coverage["importedDistricts"], 1)
        self.assertEqual(coverage["completeDistricts"], 0)
        self.assertEqual(coverage["nextDistrict"], BOARD_CATALOG_DISTRICTS[1]["name"])
        headline = board_catalog_import.catalog_headline(self.table)
        self.assertEqual(headline["importedDistricts"], 1)
        self.assertEqual(headline["nextDistrict"], BOARD_CATALOG_DISTRICTS[1]["name"])

    def test_catalog_fetch_cap_is_nine(self) -> None:
        settings = _enable(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            catalog = board_catalog.create_next(self.table, settings)
            other = board_staff.create_task(
                self.table,
                settings,
                assignee="content-marketer",
                origin="owner",
                brief="Write a post",
                deliverable_type="markdown",
                created_by="admin",
            )
        self.assertEqual(BOARD_CATALOG_FETCH_CAP, 9)
        self.assertEqual(board_research.fetch_cap_for_task(self.table, catalog["taskId"]), 9)
        self.assertEqual(board_research.fetch_cap_for_task(self.table, other["taskId"]), 6)
        self.assertEqual(board_research.fetch_cap_for_task(self.table, ""), 6)
        ctx = type("Ctx", (), {})()
        original = board_store.get_task
        with patch.object(board_store, "get_task", side_effect=original) as getter:
            self.assertEqual(board_research.fetch_cap_for_task(self.table, catalog["taskId"], ctx=ctx), 9)
            self.assertEqual(board_research.fetch_cap_for_task(self.table, catalog["taskId"], ctx=ctx), 9)
        self.assertEqual(getter.call_count, 1)

    def test_fetch_cap_resets_after_retry(self) -> None:
        settings = _enable(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch.object(board_async, "invoke_async", lambda payload, fallback=None: None):
            task = board_catalog.create_next(self.table, settings)
        tid = task["taskId"]
        ctx = type("Ctx", (), {"table": self.table, "task_id": tid})()
        for i in range(9):
            board_store.add_tool_call(
                self.table,
                {
                    "op": "research_fetch_page",
                    "status": "ok",
                    "taskId": tid,
                    "attempt": 1,
                    "createdAt": f"2026-09-18T00:00:{i:02d}Z",
                },
            )
        self.assertIn("fetch cap", board_research.op_fetch_page(ctx, {"url": "https://www.lcsd.gov.hk/x"})["error"])
        task["attempt"] = 2
        task["retriedAt"] = "2026-09-21T00:00:00Z"
        board_store.put_task(self.table, task)
        board_store.add_tool_call(
            self.table,
            {
                "op": "research_fetch_page",
                "status": "ok",
                "taskId": tid,
                "attempt": 2,
                "createdAt": "2026-09-21T00:01:00Z",
            },
        )
        # One call on attempt 2 — still under the catalog cap of 9.
        out = board_research.op_fetch_page(ctx, {"url": "https://example.invalid"})
        self.assertNotIn("fetch cap", str(out.get("error") or ""))

    def test_context_pack_includes_catalog_counts_and_built(self) -> None:
        import board_catalog_candidates
        import board_context

        board_catalog_candidates.upsert_candidate(
            self.table,
            {
                "source": "lcsd",
                "sourceId": "lcsd-1",
                "nameEn": "Quarry Bay Park Playground",
                "district": "Eastern",
            },
        )
        pack = board_context.build_context_pack(
            self.table, board_store.load_settings(self.table), roster=[]
        )
        self.assertIn("lcsd", pack["catalog"]["candidates"])
        self.assertTrue(any("importer" in line.lower() for line in pack["catalog"]["built"]))
        self.assertIn("Catalog (already built", pack["text"])
        self.assertIn("research_fetch_page", pack["text"])


if __name__ == "__main__":
    unittest.main()
