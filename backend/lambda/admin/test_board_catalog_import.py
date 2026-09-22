"""Unit tests for catalog sheet → importer JSON."""

from __future__ import annotations

import io
import json
import os
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from test_board import BoardTestCase

import board_catalog
import board_catalog_import
import board_holds
import board_staff
import board_store


SHEET = {
    "district": "Eastern",
    "organisations": [
        {
            "name_en": "Quarry Bay Park Playground",
            "name_zh": "鰂魚涌公園遊樂場",
            "type": "playground",
            "address_en": "Taikoo Shing, Eastern",
            "lat": 22.291,
            "lng": 114.216,
            "official_url": "https://www.lcsd.gov.hk/en/parks/qbp.html",
            "phone": "unverified",
            "opening_hours": "unverified",
            "description_en": "Harbourfront playground with slides.",
            "source_url": "https://www.lcsd.gov.hk/en/parks/qbp.html",
            "verified_fields": [
                "name_en",
                "type",
                "address_en",
                "lat",
                "lng",
                "official_url",
                "description_en",
                "source_url",
            ],
            "unverified_fields": ["phone", "opening_hours"],
        },
        {
            "name_en": "Invented Playhouse",
            "type": "indoor_play",
            "phone": "+852 9999 0000",
            "verified_fields": [],
            "unverified_fields": ["name_en", "type", "phone"],
        },
    ],
}


def _enable_staff(table):
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config(
        {**(settings.get("staff") or {}), "enabled": True}
    )
    return board_store.save_settings(table, settings)


def _stamp_fresh_remote(task: dict, **dry_extra) -> dict:
    now = board_store.now_iso()
    task["lastValidatedAt"] = now
    preview = dict(task.get("importPreview") or {})
    dry = dict(preview.get("dryRun") or {"ok": True, "accepted": 1, "skipped": 0})
    dry["mode"] = "remote"
    dry.pop("remoteError", None)
    dry.update(dry_extra)
    preview["ok"] = True
    preview["dryRun"] = dry
    preview["taskId"] = task.get("taskId")
    task["importPreview"] = preview
    return task


class TransformTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["BOARD_CATALOG_MANAGER_ID"] = "mgr-1"
        os.environ.pop("BOARD_CATALOG_IMPORT_ENABLED", None)
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_MANAGER_ID", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_IMPORT_ENABLED", None))
        board_catalog_import.set_auth_for_tests(None)
        board_catalog_import.set_http_for_tests(None)
        board_catalog_import.set_secret_for_tests(None)

    def test_verified_fields_only(self) -> None:
        out = board_catalog_import.transform_sheet(SHEET)
        self.assertEqual(out["accepted"], 1)
        self.assertEqual(out["skipped"], 1)
        org = out["organizations"][0]
        self.assertEqual(org["name"], "Quarry Bay Park Playground")
        self.assertEqual(org["area_name"], "Eastern")
        self.assertEqual(org["category_name"], "Outdoor activity")
        self.assertEqual(org["manager_id"], "mgr-1")
        self.assertEqual(org["website"], "https://www.lcsd.gov.hk/en/parks/qbp.html")
        self.assertEqual(org["lat"], 22.291)
        self.assertNotIn("phone", org)
        self.assertIn("unverified=phone", org["vetting_note"])

    def test_parse_fenced_json(self) -> None:
        text = "Notes\n```json\n" + __import__("json").dumps(SHEET) + "\n```\n"
        sheet = board_catalog_import.parse_sheet(text)
        self.assertEqual(sheet["district"], "Eastern")

    def test_local_dry_run_ok(self) -> None:
        transformed = board_catalog_import.transform_sheet(SHEET)
        dry = board_catalog_import.local_dry_run(transformed)
        self.assertTrue(dry["ok"])
        self.assertEqual(dry["mode"], "local")
        self.assertEqual(dry["accepted"], 1)

    def test_sports_maps_to_sport(self) -> None:
        sheet = {
            "district": "Southern",
            "organisations": [
                {
                    "name_en": "Aberdeen Sports Club",
                    "type": "sports",
                    "verified_fields": ["name_en", "type"],
                }
            ],
        }
        out = board_catalog_import.transform_sheet(sheet)
        self.assertEqual(out["accepted"], 1)
        self.assertEqual(out["organizations"][0]["category_name"], "Sport")

    def test_sport_alias_maps_to_sport(self) -> None:
        sheet = {
            "district": "Islands",
            "organisations": [
                {
                    "name_en": "Galaxy Sports Asia",
                    "type": "sport",
                    "verified_fields": ["name_en"],
                }
            ],
        }
        out = board_catalog_import.transform_sheet(sheet)
        self.assertEqual(out["accepted"], 1)
        self.assertEqual(out["organizations"][0]["category_name"], "Sport")

    def test_indoor_play_maps_to_indoor_fun(self) -> None:
        sheet = {
            "district": "Wan Chai",
            "organisations": [
                {
                    "name_en": "One Small Step",
                    "type": "indoor_play",
                    "verified_fields": ["name_en", "type"],
                }
            ],
        }
        out = board_catalog_import.transform_sheet(sheet)
        self.assertEqual(out["accepted"], 1)
        self.assertEqual(out["organizations"][0]["category_name"], "Indoor fun")

    def test_restaurant_type_is_skipped_without_a_product_category(self) -> None:
        sheet = {
            "district": "Wan Chai",
            "organisations": [
                {
                    "name_en": "Kids Menu Cafe",
                    "type": "restaurant",
                    "verified_fields": ["name_en", "type"],
                }
            ],
        }
        out = board_catalog_import.transform_sheet(sheet)
        self.assertEqual(out["accepted"], 0)
        self.assertEqual(out["skipped"], 1)
        self.assertIn("unknown type restaurant", str(out["orgReports"][0].get("reason") or ""))

    def test_type_accepted_without_verified_fields(self) -> None:
        sheet = {
            "district": "Eastern",
            "organisations": [
                {
                    "name_en": "Quarry Bay Park Playground",
                    "type": "playground",
                    "address_en": "Taikoo Shing",
                    "verified_fields": ["name_en", "address_en"],
                }
            ],
        }
        out = board_catalog_import.transform_sheet(sheet)
        self.assertEqual(out["accepted"], 1)
        self.assertEqual(out["organizations"][0]["category_name"], "Outdoor activity")
        self.assertEqual(out["organizations"][0]["address"], "Taikoo Shing")

    def test_alias_first_wins(self) -> None:
        sheet = {
            "district": "Eastern",
            "organisations": [
                {
                    "name_en": "Park",
                    "type": "playground",
                    "address_en": "from address_en",
                    "address": "from address",
                    "official_url": "https://official.example",
                    "website": "https://website.example",
                    "verified_fields": ["name_en", "address_en", "address", "official_url", "website"],
                }
            ],
        }
        org = board_catalog_import.transform_sheet(sheet)["organizations"][0]
        self.assertEqual(org["address"], "from address_en")
        self.assertEqual(org["website"], "https://official.example")

    def test_verified_hours_and_free_become_importer_rows(self) -> None:
        sheet = {
            "district": "Eastern",
            "organisations": [
                {
                    "name_en": "Quarry Bay Park Playground",
                    "type": "playground",
                    "address_en": "Quarry Bay Park, Lei King Road",
                    "free_or_paid": "free",
                    "opening_hours": "Daily 07:00-23:00",
                    "price_note": "unverified",
                    "verified_fields": [
                        "name_en",
                        "address_en",
                        "free_or_paid",
                        "opening_hours",
                    ],
                    "unverified_fields": ["price_note"],
                }
            ],
        }
        org = board_catalog_import.transform_sheet(sheet)["organizations"][0]
        self.assertNotIn("opening_hours=", org["vetting_note"])
        self.assertNotIn("free_or_paid=", org["vetting_note"])
        activity = org["activities"][0]
        self.assertEqual(activity["pricing"], [{"location_name": "Quarry Bay Park, Lei King Road", "pricing_type": "free"}])
        entries = activity["schedules"][0]["weekly_entries"]
        self.assertEqual(len(entries), 7)
        self.assertEqual(entries[0]["start_time"], "07:00")
        self.assertEqual(entries[0]["end_time"], "23:00")
        self.assertEqual(activity["schedules"][0]["timezone"], "Asia/Hong_Kong")

    def test_parseable_hkd_price_note_becomes_per_class(self) -> None:
        row = board_catalog_import.parse_pricing("paid", "HK$80 per class")
        self.assertEqual(row, {"pricing_type": "per_class", "amount": 80.0, "currency": "HKD"})

    def test_price_note_prefers_per_class_over_trial(self) -> None:
        row = board_catalog_import.parse_pricing("paid", "trial $50, HK$120 per class")
        self.assertEqual(row, {"pricing_type": "per_class", "amount": 120.0, "currency": "HKD"})

    def test_opening_hours_expands_weekday_range(self) -> None:
        entries = board_catalog_import.parse_opening_hours("Mon-Fri 9am-6pm")
        self.assertEqual([row["day_of_week"] for row in entries], [1, 2, 3, 4, 5])
        self.assertEqual(entries[0]["start_time"], "09:00")
        self.assertEqual(entries[0]["end_time"], "18:00")

    def test_opening_hours_drops_closed_days(self) -> None:
        entries = board_catalog_import.parse_opening_hours("7am-11pm, closed Tuesdays")
        self.assertEqual([row["day_of_week"] for row in entries], [0, 1, 3, 4, 5, 6])

    def test_opening_hours_parses_daily_chinese(self) -> None:
        entries = board_catalog_import.parse_opening_hours("每日上午7時至晚上11時")
        self.assertEqual(len(entries), 7)
        self.assertEqual(entries[0]["start_time"], "07:00")
        self.assertEqual(entries[0]["end_time"], "23:00")

    def test_opening_hours_skips_age_ranges_and_24h(self) -> None:
        self.assertIsNone(board_catalog_import.parse_opening_hours("Ages 3-12"))
        self.assertIsNone(board_catalog_import.parse_opening_hours("24 hours daily"))
        self.assertIsNone(board_catalog_import.parse_opening_hours("9:00-18:00"))

    def test_unparseable_hours_stay_in_vetting_note(self) -> None:
        self.assertIsNone(board_catalog_import.parse_opening_hours("open most days"))
        sheet = {
            "district": "Wan Chai",
            "organisations": [
                {
                    "name_en": "Wan Chai Park",
                    "type": "playground",
                    "opening_hours": "open most days",
                    "verified_fields": ["name_en", "opening_hours"],
                }
            ],
        }
        org = board_catalog_import.transform_sheet(sheet)["organizations"][0]
        self.assertIn("activities", org)
        self.assertNotIn("schedules", org["activities"][0])
        self.assertIn("opening_hours=open most days", org["vetting_note"])

    def test_sheet_quality_requires_two_first_class_facts(self) -> None:
        thin = {
            "district": "Eastern",
            "organisations": [
                {
                    "name_en": "Thin Park",
                    "type": "playground",
                    "verified_fields": ["name_en"],
                }
            ],
        }
        issues = board_catalog_import.sheet_quality_issues(thin)
        self.assertTrue(issues)
        rich = {
            "district": "Eastern",
            "organisations": [
                {
                    "name_en": "Rich Park",
                    "address_en": "Lei King Road",
                    "opening_hours": "Daily 07:00-23:00",
                    "verified_fields": ["name_en", "address_en", "opening_hours"],
                }
            ],
        }
        self.assertEqual(board_catalog_import.sheet_quality_issues(rich), [])

    def test_keep_quality_orgs_drops_thin_rows(self) -> None:
        sheet = {
            "district": "Eastern",
            "organisations": [
                {
                    "name_en": "Thin Park",
                    "type": "playground",
                    "verified_fields": ["name_en"],
                },
                {
                    "name_en": "Rich Park",
                    "address_en": "Lei King Road",
                    "opening_hours": "Daily 07:00-23:00",
                    "verified_fields": ["name_en", "address_en", "opening_hours"],
                },
            ],
        }
        kept, dropped = board_catalog_import.keep_quality_orgs(sheet)
        self.assertEqual([o["name_en"] for o in kept["organisations"]], ["Rich Park"])
        self.assertEqual(dropped, ["Thin Park"])

    def test_enrich_trusts_brief_names(self) -> None:
        names = board_catalog_import.names_from_brief(
            "Founder directive — CATALOG DESCRIBE Islands: write 40-word EN + 繁中 descriptions, "
            "age_range and price_note for Galaxy Sports Asia, Kids Club at Tung Chung, and "
            "Tung Chung North Park in Islands (hint)."
        )
        self.assertIn("galaxy sports asia", names)
        self.assertIn("kids club at tung chung", names)
        self.assertIn("tung chung north park", names)
        import board_catalog

        real = board_catalog_import.names_from_brief(
            board_catalog.compose_enrich_brief(
                {"name": "Islands", "hint": "LCSD Tung Chung North Park first"},
                ["Galaxy Sports Asia", "Kids Club at Tung Chung", "Sports and Recreation Centre"],
            )
        )
        self.assertEqual(real, {"galaxy sports asia", "kids club at tung chung", "sports and recreation centre"})
        split = board_catalog_import.names_from_brief(
            "Write descriptions for Sports and Recreation Centre, Happy Park in Eastern. Read only official pages."
        )
        self.assertEqual(split, {"sports and recreation centre", "happy park"})
        task = {
            "eventRef": {"kind": "catalog-enrich", "orgNames": ["Repulse Bay Beach"]},
            "brief": "for Stanley Plaza in Southern",
        }
        known = board_catalog_import._known_names_for_task(None, task)  # noqa: SLF001
        self.assertIsNotNone(known)
        self.assertIn("repulse bay beach", known)
        self.assertIn("stanley plaza", known)
        org, report = board_catalog_import.transform_org(
            {
                "name_en": "Stanley Plaza",
                "type": "indoor_play",
                "district": "Southern",
                "verified_fields": ["address_en"],
                "address_en": "Stanley",
            },
            district="Southern",
            manager_id="mgr-1",
            index=0,
            known_names=known,
        )
        self.assertIsNotNone(org)
        self.assertNotIn("name is not in verified_fields", str(report))

    def test_is_catalog_sheet_includes_enrich(self) -> None:
        self.assertTrue(board_catalog_import.is_catalog_sheet({"eventRef": {"kind": "catalog-micro-batch"}}))
        self.assertTrue(board_catalog_import.is_catalog_sheet({"eventRef": {"kind": "catalog-enrich"}}))
        self.assertFalse(board_catalog_import.is_catalog_sheet({"eventRef": {"kind": "duty"}}))

    def test_unknown_type_skipped(self) -> None:
        sheet = {
            "district": "Eastern",
            "organisations": [
                {
                    "name_en": "Mystery",
                    "type": "spaceship",
                    "verified_fields": ["name_en", "type"],
                }
            ],
        }
        out = board_catalog_import.transform_sheet(sheet)
        self.assertEqual(out["accepted"], 0)
        self.assertIn("unknown type", out["orgReports"][0]["reason"])

    def test_import_refuses_when_kill_switch_off(self) -> None:
        with self.assertRaises(board_catalog_import.CatalogImportError) as ctx:
            board_catalog_import.run_import(None, {"taskId": "t1", "eventRef": {"kind": "catalog-micro-batch"}})
        self.assertIn("switched off", str(ctx.exception))

    def test_config_gap_while_off(self) -> None:
        gap = board_catalog_import.config_gap()
        self.assertIsNotNone(gap)
        self.assertEqual(gap["id"], "catalog-import")
        self.assertIn("kill switch", gap["reason"])


class ImportClientTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        os.environ["BOARD_CATALOG_IMPORT_ENABLED"] = "true"
        os.environ["SIUTINDEI_ADMIN_API_BASE_URL"] = "https://admin.example.test"
        os.environ["SIUTINDEI_USER_POOL_ID"] = "ap-southeast-1_pool"
        os.environ["BOARD_IMPORTER_CLIENT_ID"] = "client-1"
        os.environ["BOARD_CATALOG_MANAGER_ID"] = "mgr-1"
        os.environ["BOARD_IMPORTER_CREDENTIALS_SECRET_ARN"] = "arn:test"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        for key in (
            "BOARD_CATALOG_IMPORT_ENABLED",
            "SIUTINDEI_ADMIN_API_BASE_URL",
            "SIUTINDEI_USER_POOL_ID",
            "BOARD_IMPORTER_CLIENT_ID",
            "BOARD_CATALOG_MANAGER_ID",
            "BOARD_IMPORTER_CREDENTIALS_SECRET_ARN",
        ):
            self.addCleanup(lambda k=key: os.environ.pop(k, None))
        board_catalog_import.set_secret_for_tests(lambda: {"username": "importer", "password": "secret"})
        board_catalog_import.set_auth_for_tests(lambda user, pw: f"idtok-{user}")
        self.calls: list[tuple[str, str, dict | None]] = []

        def http(method, url, headers, body):
            parsed = json.loads(body) if body else None
            self.calls.append((method, url, parsed))
            if url.endswith("/admin/imports/presign"):
                return {
                    "upload_url": "https://s3.example.test/put?X-Amz-Signature=secret",
                    "object_key": "imports/board.json",
                }
            if url.startswith("https://s3.example.test/put"):
                return {"status": 200}
            if url.endswith("/admin/imports"):
                dry = bool((parsed or {}).get("dry_run"))
                return {
                    "status": 200,
                    "dry_run": dry,
                    "summary": {
                        "organizations": {"created": 1, "updated": 0, "failed": 0, "skipped": 0},
                        "locations": {"created": 0, "updated": 0, "failed": 0, "skipped": 0},
                        "activities": {"created": 0, "updated": 0, "failed": 0, "skipped": 0},
                        "pricing": {"created": 0, "updated": 0, "failed": 0, "skipped": 0},
                        "schedules": {"created": 0, "updated": 0, "failed": 0, "skipped": 0},
                        "warnings": 0,
                        "errors": 0,
                    },
                    "results": [
                        {
                            "type": "organizations",
                            "key": "Quarry Bay Park Playground",
                            "status": "created",
                            "warnings": [],
                            "errors": [],
                        }
                    ],
                    "file_warnings": [],
                }
            raise AssertionError(url)

        board_catalog_import.set_http_for_tests(http)
        self.addCleanup(lambda: board_catalog_import.set_auth_for_tests(None))
        self.addCleanup(lambda: board_catalog_import.set_http_for_tests(None))
        self.addCleanup(lambda: board_catalog_import.set_secret_for_tests(None))

    def test_owner_import_presign_put_post(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch("board_async.invoke_async", lambda payload, fallback=None: None):
            task = board_catalog.create_next(self.table, settings)
        key = board_staff._deliverable_key(task["taskId"], "json")
        board_staff._blob_put(key, json.dumps(SHEET).encode())
        task["deliverableKey"] = key
        task["status"] = "awaiting_import"
        task["importPhase"] = "validated"
        _stamp_fresh_remote(task)
        board_store.put_task(self.table, task)
        out = board_catalog_import.run_import(self.table, task)
        self.assertTrue(out["ok"])
        self.assertEqual(
            [c[0] for c in self.calls],
            ["POST", "PUT", "POST"],
        )
        self.assertEqual(self.calls[-1][2], {"object_key": "imports/board.json"})
        self.assertEqual(out["import"]["sent"], 1)
        self.assertEqual(out["import"]["accepted"], 1)
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertTrue(saved.get("importedAt"))
        self.assertEqual(saved.get("status"), "delivered")
        self.assertEqual((saved.get("importResult") or {}).get("sent"), 1)
        self.assertEqual((saved.get("importResult") or {}).get("created"), 1)

        with self.assertRaises(board_catalog_import.CatalogImportError) as ctx:
            board_catalog_import.run_import(self.table, saved)
        self.assertIn("already imported", str(ctx.exception))

        self.calls.clear()
        again = board_catalog_import.run_import(self.table, saved, force=True)
        self.assertTrue(again["ok"])
        self.assertEqual([c[0] for c in self.calls], ["POST", "PUT", "POST"])

    def test_remote_dry_run_uses_presign(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch("board_async.invoke_async", lambda payload, fallback=None: None):
            task = board_catalog.create_next(self.table, settings)
        key = board_staff._deliverable_key(task["taskId"], "json")
        board_staff._blob_put(key, json.dumps(SHEET).encode())
        task["deliverableKey"] = key
        board_store.put_task(self.table, task)
        out = board_catalog_import.preview_task(self.table, task, remote=True)
        self.assertEqual([c[0] for c in self.calls], ["POST", "PUT", "POST"])
        self.assertEqual(
            self.calls[-1][2],
            {"object_key": "imports/board.json", "dry_run": True},
        )
        self.assertEqual((out.get("dryRun") or {}).get("mode"), "remote")
        self.assertTrue((out.get("dryRun") or {}).get("ok"))
        self.assertEqual(((out.get("dryRun") or {}).get("summary") or {}).get("created"), 1)

    def _catalog_task_with_sheet(self) -> dict:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch("board_async.invoke_async", lambda payload, fallback=None: None):
            task = board_catalog.create_next(self.table, settings)
        key = board_staff._deliverable_key(task["taskId"], "json")
        board_staff._blob_put(key, json.dumps(SHEET).encode())
        task["deliverableKey"] = key
        board_store.put_task(self.table, task)
        return task

    def test_owner_preview_defaults_to_remote(self) -> None:
        task = self._catalog_task_with_sheet()
        out = board_catalog_import.owner_preview(self.table, {"taskId": task["taskId"]})
        self.assertEqual([c[0] for c in self.calls], ["POST", "PUT", "POST"])
        self.assertEqual((out.get("dryRun") or {}).get("mode"), "remote")
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(((saved.get("importPreview") or {}).get("dryRun") or {}).get("mode"), "remote")
        self.assertTrue(saved.get("lastValidatedAt"))

    def test_owner_preview_stays_local_when_remote_false(self) -> None:
        task = self._catalog_task_with_sheet()
        out = board_catalog_import.owner_preview(self.table, {"taskId": task["taskId"], "remote": False})
        self.assertEqual(self.calls, [])
        self.assertEqual((out.get("dryRun") or {}).get("mode"), "local")

    def test_wants_remote_defaults_true(self) -> None:
        self.assertTrue(board_catalog_import._wants_remote({}))
        self.assertTrue(board_catalog_import._wants_remote({"remote": True}))
        self.assertFalse(board_catalog_import._wants_remote({"remote": False}))
        self.assertFalse(board_catalog_import._wants_remote({"remote": "false"}))
        self.assertTrue(board_catalog_import._wants_remote({"remote": "true"}))

    def test_owner_preview_parks_collision(self) -> None:
        task = self._catalog_task_with_sheet()
        task["status"] = "awaiting_import"
        task["importPhase"] = "validated"
        board_store.put_task(self.table, task)

        def collision_http(method, url, headers, body):
            parsed = json.loads(body) if body else None
            self.calls.append((method, url, parsed))
            if url.endswith("/admin/imports/presign"):
                return {"upload_url": "https://s3.example.test/put", "object_key": "imports/board.json"}
            if url.startswith("https://s3.example.test/put"):
                return {"status": 200}
            return {
                "status": 200,
                "dry_run": True,
                "summary": {"organizations": {"created": 0, "updated": 1, "failed": 0, "skipped": 0}},
                "results": [{"type": "organizations", "key": "Kidz Club", "status": "updated", "errors": []}],
                "file_warnings": [],
            }

        board_catalog_import.set_http_for_tests(collision_http)
        out = board_catalog_import.owner_preview(self.table, {"taskId": task["taskId"]})
        self.assertTrue((out.get("dryRun") or {}).get("wouldUpdate"))
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "needs_owner")
        self.assertEqual(saved.get("importPhase"), "collision")
        self.assertEqual(saved.get("importError"), "")

    def test_owner_preview_clears_import_error(self) -> None:
        task = self._catalog_task_with_sheet()
        task["status"] = "awaiting_import"
        task["importPhase"] = "pending"
        task["importError"] = "Cognito AdminInitiateAuth did not return an IdToken"
        board_store.put_task(self.table, task)
        board_catalog_import.owner_preview(self.table, {"taskId": task["taskId"]})
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("importPhase"), "validated")
        self.assertEqual(saved.get("importError"), "")
        self.assertTrue(saved.get("lastValidatedAt"))

    def test_owner_preview_local_keeps_collision(self) -> None:
        task = self._catalog_task_with_sheet()
        task["status"] = "needs_owner"
        task["importPhase"] = "collision"
        task["importError"] = "old remote error"
        board_store.put_task(self.table, task)
        board_catalog_import.owner_preview(self.table, {"taskId": task["taskId"], "remote": False})
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "needs_owner")
        self.assertEqual(saved.get("importPhase"), "collision")
        self.assertEqual(saved.get("importError"), "old remote error")

    def test_run_import_refuses_stored_collision(self) -> None:
        task = self._catalog_task_with_sheet()
        task["status"] = "awaiting_import"
        task["importPhase"] = "validated"
        _stamp_fresh_remote(task, wouldUpdate=["Kidz Club"], summary={"updated": 1})
        board_store.put_task(self.table, task)
        self.calls.clear()
        out = board_catalog_import.run_import(self.table, task)
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("collision"))
        self.assertEqual(self.calls, [])
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "needs_owner")
        self.assertEqual(saved.get("importPhase"), "collision")

    def test_owner_import_stale_refreshes_without_live_write(self) -> None:
        task = self._catalog_task_with_sheet()
        task["status"] = "awaiting_import"
        task["importPhase"] = "pending"
        task["lastValidatedAt"] = "2020-01-01T00:00:00Z"
        board_store.put_task(self.table, task)
        self.calls.clear()
        out = board_catalog_import.owner_import(self.table, {"taskId": task["taskId"]})
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("previewed"))
        self.assertTrue(all((c[2] or {}).get("dry_run") for c in self.calls if c[1].endswith("/admin/imports")))
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("importPhase"), "validated")
        self.assertFalse(saved.get("importedAt"))

    def test_import_refuses_non_catalog_and_undelivered(self) -> None:
        with self.assertRaises(board_catalog_import.CatalogImportError) as ctx:
            board_catalog_import.run_import(
                None,
                {"taskId": "t1", "status": "delivered", "eventRef": {"kind": "mail"}},
            )
        self.assertIn("not a catalog", str(ctx.exception))
        with self.assertRaises(board_catalog_import.CatalogImportError) as ctx:
            board_catalog_import.run_import(
                None,
                {"taskId": "t1", "status": "review", "eventRef": {"kind": "catalog-micro-batch"}},
            )
        self.assertIn("waiting to import", str(ctx.exception))

    def test_http_error_strips_query(self) -> None:
        board_catalog_import.set_http_for_tests(None)
        signed = "https://s3.example.test/put?X-Amz-Signature=secret"
        err = urllib.error.HTTPError(signed, 403, "Forbidden", hdrs={}, fp=io.BytesIO(b"no"))
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(board_catalog_import.CatalogImportError) as ctx:
                board_catalog_import._http("PUT", signed)
        message = str(ctx.exception)
        self.assertNotIn("X-Amz-Signature", message)
        self.assertNotIn("secret", message)
        self.assertIn("https://s3.example.test/put", message)
        self.assertEqual(
            board_catalog_import._safe_url(signed),
            "https://s3.example.test/put",
        )

    def test_accept_hook_previews_without_import(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch("board_async.invoke_async", lambda payload, fallback=None: None):
            task = board_catalog.create_next(self.table, settings)
        key = board_staff._deliverable_key(task["taskId"], "json")
        board_staff._blob_put(key, __import__("json").dumps(SHEET).encode())
        task["deliverableKey"] = key
        task["status"] = "review"
        task["lastReview"] = {"verdict": "accept", "notes": "", "at": "2026-09-16T00:00:00Z"}
        board_store.put_task(self.table, task)
        accepted = board_staff._accept_task(self.table, task, "2026-09-16T12:00:00Z")
        self.assertEqual(accepted["status"], "awaiting_import")
        self.assertEqual(accepted.get("importPhase"), "validated")
        preview = accepted.get("importPreview") or {}
        self.assertTrue(preview.get("ok"))
        self.assertEqual((preview.get("dryRun") or {}).get("accepted"), 1)
        self.assertFalse(accepted.get("importedAt"))
        self.assertEqual([c[0] for c in self.calls], ["POST", "PUT", "POST"])

    def test_accept_collision_parks_needs_owner(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch("board_async.invoke_async", lambda payload, fallback=None: None):
            task = board_catalog.create_next(self.table, settings)
        key = board_staff._deliverable_key(task["taskId"], "json")
        board_staff._blob_put(key, json.dumps(SHEET).encode())
        task["deliverableKey"] = key
        task["status"] = "review"
        task["lastReview"] = {"verdict": "accept", "notes": "", "at": "2026-09-16T00:00:00Z"}
        board_store.put_task(self.table, task)

        def collision_http(method, url, headers, body):
            parsed = json.loads(body) if body else None
            self.calls.append((method, url, parsed))
            if url.endswith("/admin/imports/presign"):
                return {"upload_url": "https://s3.example.test/put", "object_key": "imports/board.json"}
            if url.startswith("https://s3.example.test/put"):
                return {"status": 200}
            return {
                "status": 200,
                "dry_run": True,
                "summary": {
                    "organizations": {"created": 0, "updated": 1, "failed": 0, "skipped": 0},
                    "warnings": 0,
                    "errors": 0,
                },
                "results": [{"type": "organizations", "key": "Quarry Bay Park Playground", "status": "updated", "errors": []}],
                "file_warnings": [],
            }

        board_catalog_import.set_http_for_tests(collision_http)
        parked = board_staff._accept_task(self.table, task, "2026-09-16T12:00:00Z")
        self.assertEqual(parked["status"], "needs_owner")
        self.assertEqual(parked.get("importPhase"), "collision")
        self.assertIn("update existing", " ".join(parked.get("openQuestions") or []))

    def test_enrich_accept_updates_and_handoffs(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        board_store.save_staff_override(self.table, "provider-success", {"isActive": True})
        sheet = {
            "district": "Eastern",
            "organisations": [
                {
                    "name_en": "Quarry Bay Park Playground",
                    "type": "playground",
                    "address_en": "Taikoo Shing, Eastern",
                    "official_url": "https://www.lcsd.gov.hk/en/parks/qbp.html",
                    "verified_fields": ["name_en", "address_en", "official_url"],
                },
                {
                    "name_en": "Kidz Club",
                    "type": "class",
                    "address_en": "1 King's Road",
                    "official_url": "https://kidzclub.example/eastern",
                    "opening_hours": "Mon-Fri 9am-6pm",
                    "free_or_paid": "paid",
                    "price_note": "HK$120 per class",
                    "verified_fields": [
                        "name_en",
                        "address_en",
                        "official_url",
                        "opening_hours",
                        "free_or_paid",
                        "price_note",
                    ],
                },
            ],
        }

        def collision_http(method, url, headers, body):
            parsed = json.loads(body) if body else None
            self.calls.append((method, url, parsed))
            if url.endswith("/admin/imports/presign"):
                return {"upload_url": "https://s3.example.test/put", "object_key": "imports/board.json"}
            if url.startswith("https://s3.example.test/put"):
                return {"status": 200}
            return {
                "status": 200,
                "dry_run": True,
                "summary": {
                    "organizations": {"created": 0, "updated": 2, "failed": 0, "skipped": 0},
                    "warnings": 0,
                    "errors": 0,
                },
                "results": [
                    {"type": "organizations", "key": "Quarry Bay Park Playground", "status": "updated", "errors": []},
                    {"type": "organizations", "key": "Kidz Club", "status": "updated", "errors": []},
                ],
                "file_warnings": [],
            }

        board_catalog_import.set_http_for_tests(collision_http)
        import board_geocode

        board_geocode.set_lookup_for_tests(lambda _addr: {})
        self.addCleanup(lambda: board_geocode.set_lookup_for_tests(None))
        with patch("board_async.invoke_async", lambda payload, fallback=None: None):
            first = board_catalog.create_next(self.table, settings)
            first["status"] = "delivered"
            first["importPreview"] = {
                "payload": {
                    "organizations": [
                        {"name": "Quarry Bay Park Playground"},
                        {"name": "Kidz Club"},
                    ]
                }
            }
            board_store.put_task(self.table, first)
            task = board_catalog.create_enrich(self.table, settings)
            key = board_staff._deliverable_key(task["taskId"], "json")
            board_staff._blob_put(key, json.dumps(sheet).encode())
            task["deliverableKey"] = key
            task["status"] = "review"
            task["lastReview"] = {"verdict": "accept", "notes": "", "at": "2026-09-16T00:00:00Z"}
            board_store.put_task(self.table, task)
            accepted = board_staff._accept_task(self.table, task, "2026-09-16T12:00:00Z")
        self.assertEqual(
            accepted["status"],
            "awaiting_import",
            msg=f"phase={accepted.get('importPhase')} flags={accepted.get('flags')} questions={accepted.get('openQuestions')} error={accepted.get('importError')}",
        )
        self.assertEqual(accepted.get("importPhase"), "validated")
        handoffs = [
            row
            for status in ("queued", "running")
            for row in board_store.list_tasks(self.table, status, limit=50)
            if (row.get("eventRef") or {}).get("kind") == "catalog-handoff"
        ]
        self.assertEqual(len(handoffs), 1)
        self.assertEqual(handoffs[0]["assignee"], "provider-success")
        self.assertEqual(handoffs[0]["eventRef"]["name"], "Kidz Club")

    def test_run_import_allows_enrich_updates(self) -> None:
        task = self._catalog_task_with_sheet()
        task["eventRef"] = {**(task.get("eventRef") or {}), "kind": "catalog-enrich"}
        task["status"] = "awaiting_import"
        task["importPhase"] = "validated"
        _stamp_fresh_remote(task, wouldUpdate=["Quarry Bay Park Playground"], summary={"updated": 1, "failed": 0})
        board_store.put_task(self.table, task)
        self.calls.clear()
        out = board_catalog_import.run_import(self.table, task)
        self.assertTrue(out["ok"])
        self.assertFalse(out.get("collision"))
        self.assertTrue(any(url.endswith("/admin/imports") for _method, url, _body in self.calls))

    def test_run_import_live_updated_does_not_park_enrich(self) -> None:
        """Post-import ``summary.updated`` must honour enrich updates (same as pre-import)."""
        task = self._catalog_task_with_sheet()
        task["eventRef"] = {**(task.get("eventRef") or {}), "kind": "catalog-enrich"}
        task["status"] = "awaiting_import"
        task["importPhase"] = "validated"
        _stamp_fresh_remote(task, summary={"updated": 0, "failed": 0, "created": 1})
        board_store.put_task(self.table, task)

        def live_updated(payload, token, *, timeout=None):
            return {
                "ok": True,
                "summary": {"failed": 0, "created": 0, "updated": 1},
                "results": [
                    {
                        "type": "organizations",
                        "key": "Quarry Bay Park Playground",
                        "status": "updated",
                    }
                ],
                "wouldUpdate": ["Quarry Bay Park Playground"],
                "sent": 1,
                "accepted": 1,
                "objectKey": "imports/board.json",
            }

        with patch.object(board_catalog_import, "_run_remote_import", side_effect=live_updated):
            out = board_catalog_import.run_import(self.table, task)
        self.assertTrue(out["ok"])
        self.assertFalse(out.get("collision"))
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("importPhase"), "imported")
        self.assertEqual(saved.get("status"), "delivered")
        self.assertTrue(saved.get("importedAt"))

    def test_skip_marks_delivered_without_import(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch("board_async.invoke_async", lambda payload, fallback=None: None):
            task = board_catalog.create_next(self.table, settings)
        task["status"] = "awaiting_import"
        task["importPhase"] = "validated"
        board_store.put_task(self.table, task)
        out = board_catalog_import.skip_import(self.table, task)
        self.assertTrue(out["skipped"])
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "delivered")
        self.assertTrue(saved.get("importSkipped"))
        self.assertFalse(saved.get("importedAt"))
        self.assertEqual(self.calls, [])

    def test_awaiting_cap_blocks_next_district(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch("board_async.invoke_async", lambda payload, fallback=None: None):
            first = board_catalog.create_next(self.table, settings)
        first["status"] = "awaiting_import"
        board_store.put_task(self.table, first)
        with patch.object(board_catalog_import, "BOARD_CATALOG_MAX_AWAITING_IMPORT", 1):
            with self.assertRaises(board_staff.StaffError) as ctx:
                board_catalog.create_next(self.table, settings)
        self.assertIn("awaiting_import cap", str(ctx.exception))

    def test_backfill_promotes_delivered_unimported(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch("board_async.invoke_async", lambda payload, fallback=None: None):
            task = board_catalog.create_next(self.table, settings)
        key = board_staff._deliverable_key(task["taskId"], "json")
        board_staff._blob_put(key, json.dumps(SHEET).encode())
        task["deliverableKey"] = key
        task["status"] = "delivered"
        task["finishedAt"] = "2026-09-16T00:00:00Z"
        task["expiresAt"] = 1
        board_store.put_task(self.table, task)
        out = board_catalog_import.handle_tick(self.table, settings)
        self.assertEqual(out["backfilled"], 1)
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "awaiting_import")
        self.assertIsNone(saved.get("finishedAt"))
        self.assertNotIn("expiresAt", saved)

    def test_org_counts_read_nested_summary(self) -> None:
        counts = board_catalog_import._org_counts(
            {
                "summary": {
                    "organizations": {"created": 2, "updated": 1, "failed": 3, "skipped": 0},
                    "warnings": 0,
                    "errors": 4,
                }
            }
        )
        self.assertEqual(counts, {"created": 2, "updated": 1, "failed": 3, "skipped": 0})
        self.assertEqual(board_catalog_import._importer_accepted({"summary": {"organizations": {"created": 2, "updated": 1}}}), 3)
        self.assertEqual(
            board_catalog_import._importer_accepted(
                {
                    "summary": {
                        "organizations": {"created": 0, "updated": 0, "failed": 0, "skipped": 3},
                        "locations": {"created": 0, "updated": 0, "failed": 0, "skipped": 3},
                        "activities": {"created": 2, "updated": 0, "failed": 0, "skipped": 1},
                    }
                }
            ),
            2,
        )

    def _sheet_task(self, settings, status="review"):
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch("board_async.invoke_async", lambda payload, fallback=None: None):
            task = board_catalog.create_next(self.table, settings)
        key = board_staff._deliverable_key(task["taskId"], "json")
        board_staff._blob_put(key, json.dumps(SHEET).encode())
        task["deliverableKey"] = key
        task["status"] = status
        if status == "review":
            task["lastReview"] = {"verdict": "accept", "notes": "", "at": "2026-09-16T00:00:00Z"}
        board_store.put_task(self.table, task)
        return task

    def test_auto_import_hold_executes(self) -> None:
        settings = _enable_staff(self.table)
        settings["catalog"] = {"autoImport": True}
        settings = board_store.save_settings(self.table, settings)
        task = board_staff._accept_task(self.table, self._sheet_task(settings), "2026-09-16T12:00:00Z")
        self.assertEqual(task.get("importPhase"), "validated")
        out = board_catalog_import.handle_tick(self.table, settings)
        self.assertEqual(out["scheduled"], 1)
        holds = board_store.list_holds(self.table, "scheduled", limit=20)
        self.assertEqual(len(holds), 1)
        self.assertTrue(holds[0].get("internal"))
        ran = board_holds.execute_due(self.table, settings, "2099-01-01T00:00:00Z")
        self.assertEqual(ran, 1)
        latest = board_store.get_hold(self.table, holds[0]["holdId"])
        self.assertEqual(latest.get("status"), "executed")
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "delivered")
        self.assertTrue(saved.get("importedAt"))

    def test_sweep_never_imports_immediately(self) -> None:
        settings = _enable_staff(self.table)
        settings["catalog"] = {"autoImport": True}
        settings = board_store.save_settings(self.table, settings)
        task = board_staff._accept_task(self.table, self._sheet_task(settings), "2026-09-16T12:00:00Z")
        with patch.object(board_holds, "hold_hours", return_value=0):
            out = board_catalog_import.handle_tick(self.table, settings)
        self.assertEqual(out["scheduled"], 1)
        self.assertEqual(out["imported"], 0)
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "awaiting_import")
        self.assertFalse(saved.get("importedAt"))

    def test_local_pending_does_not_churn_every_tick(self) -> None:
        for key in ("SIUTINDEI_ADMIN_API_BASE_URL", "SIUTINDEI_USER_POOL_ID", "BOARD_IMPORTER_CLIENT_ID"):
            os.environ.pop(key, None)
        settings = _enable_staff(self.table)
        now = board_store.now_iso()
        accepted = board_staff._accept_task(self.table, self._sheet_task(settings), now)
        self.assertEqual(accepted.get("importPhase"), "pending")
        self.assertEqual(accepted.get("lastValidatedAt"), now)
        first = accepted.get("acceptedAt")
        out = board_catalog_import.handle_tick(self.table, settings)
        self.assertEqual(out["revalidated"], 0)
        saved = board_store.get_task(self.table, accepted["taskId"])
        self.assertEqual(saved.get("acceptedAt"), first)

    def test_remote_auth_failure_stays_pending(self) -> None:
        settings = _enable_staff(self.table)
        board_catalog_import.set_auth_for_tests(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cognito down")))
        accepted = board_staff._accept_task(self.table, self._sheet_task(settings), "2026-09-16T12:00:00Z")
        self.assertEqual(accepted.get("status"), "awaiting_import")
        self.assertEqual(accepted.get("importPhase"), "pending")
        self.assertIn("cognito", str(accepted.get("importError") or "").lower())

    def test_partial_retry_sends_only_failed_orgs(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="awaiting_import")
        task["importPhase"] = "partial"
        _stamp_fresh_remote(task)
        task["importResult"] = {
            "results": [
                {"type": "organizations", "key": "Quarry Bay Park Playground", "status": "failed"},
            ]
        }
        board_store.put_task(self.table, task)
        bodies: list[dict] = []

        def http(method, url, headers, body):
            parsed = json.loads(body) if body else None
            if url.endswith("/admin/imports/presign"):
                return {"upload_url": "https://s3.example.test/put", "object_key": "imports/board.json"}
            if url.startswith("https://s3.example.test/put"):
                bodies.append(parsed or {})
                return {"status": 200}
            return {
                "status": 200,
                "summary": {"organizations": {"created": 1, "updated": 0, "failed": 0, "skipped": 0}},
                "results": [{"type": "organizations", "key": "Quarry Bay Park Playground", "status": "created"}],
            }

        board_catalog_import.set_http_for_tests(http)
        out = board_catalog_import.run_import(self.table, task)
        self.assertTrue(out["ok"])
        self.assertEqual(len((bodies[-1] or {}).get("organizations") or []), 1)
        self.assertEqual(bodies[-1]["organizations"][0]["name"], "Quarry Bay Park Playground")

    def test_activity_failure_is_partial_even_when_orgs_succeed(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="awaiting_import")
        task["importPhase"] = "validated"
        _stamp_fresh_remote(task)
        board_store.put_task(self.table, task)

        def http(method, url, headers, body):
            if url.endswith("/admin/imports/presign"):
                return {"upload_url": "https://s3.example.test/put", "object_key": "imports/board.json"}
            if url.startswith("https://s3.example.test/put"):
                return {"status": 200}
            return {
                "status": 200,
                "summary": {
                    "organizations": {"created": 1, "updated": 0, "failed": 0, "skipped": 0},
                    "activities": {"created": 0, "updated": 0, "failed": 1, "skipped": 0},
                },
                "results": [
                    {"type": "organizations", "key": "Wan Chai Park", "status": "created"},
                    {
                        "type": "activities",
                        "key": "Wan Chai Park / Wan Chai Park",
                        "status": "failed",
                        "errors": [{"field": "category_name", "message": "unknown category_name"}],
                    },
                ],
            }

        board_catalog_import.set_http_for_tests(http)
        out = board_catalog_import.run_import(self.table, task)
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("partial"))
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "needs_owner")
        self.assertEqual(saved.get("importPhase"), "partial")
        self.assertIn("unknown category_name", str(saved.get("importError") or "") + str(saved.get("openQuestions") or ""))
        self.assertTrue(board_catalog_import.can_reimport(saved))

    def test_owner_reimport_force_sends_imported_sheet(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="delivered")
        task["importedAt"] = "2026-09-16T12:00:00Z"
        task["importPhase"] = "imported"
        task["importResult"] = {"failedActivities": 1, "results": [{"type": "activities", "status": "failed"}]}
        board_store.put_task(self.table, task)
        self.assertTrue(board_catalog_import.can_reimport(task))

        def http(method, url, headers, body):
            if url.endswith("/admin/imports/presign"):
                return {"upload_url": "https://s3.example.test/put", "object_key": "imports/board.json"}
            if url.startswith("https://s3.example.test/put"):
                return {"status": 200}
            return {
                "status": 200,
                "summary": {"organizations": {"created": 0, "updated": 1, "failed": 0, "skipped": 0}},
                "results": [{"type": "organizations", "key": "Quarry Bay Park Playground", "status": "updated"}],
            }

        board_catalog_import.set_http_for_tests(http)
        out = board_catalog_import.owner_reimport(self.table, {"taskId": task["taskId"]})
        self.assertTrue(out["ok"])
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertTrue(saved.get("reimportedAt"))

    def test_reimport_transport_failure_keeps_imported_phase(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="delivered")
        task["importedAt"] = "2026-09-16T12:00:00Z"
        task["importPhase"] = "imported"
        task["importResult"] = {"failedActivities": 1}
        board_store.put_task(self.table, task)
        with patch.object(
            board_catalog_import,
            "_run_remote_import",
            side_effect=board_catalog_import.CatalogImportError("siutindei import request failed"),
        ):
            with self.assertRaises(board_catalog_import.CatalogImportError):
                board_catalog_import.reimport_failed_rows(self.table, task)
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("importPhase"), "imported")
        self.assertEqual(saved.get("importedAt"), "2026-09-16T12:00:00Z")
        self.assertIn("failed", saved.get("importError") or "")

    def test_partial_import_returns_ok_false(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="awaiting_import")
        task["importPhase"] = "validated"
        _stamp_fresh_remote(task)
        board_store.put_task(self.table, task)

        def http(method, url, headers, body):
            if url.endswith("/admin/imports/presign"):
                return {"upload_url": "https://s3.example.test/put", "object_key": "imports/board.json"}
            if url.startswith("https://s3.example.test/put"):
                return {"status": 200}
            return {
                "status": 200,
                "summary": {"organizations": {"created": 0, "updated": 0, "failed": 1, "skipped": 0}},
                "results": [
                    {
                        "type": "organizations",
                        "key": "Quarry Bay Park Playground",
                        "status": "failed",
                        "errors": [{"message": "bad row"}],
                    }
                ],
            }

        board_catalog_import.set_http_for_tests(http)
        out = board_catalog_import.run_import(self.table, task)
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("partial"))
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "needs_owner")
        self.assertEqual(saved.get("importPhase"), "partial")

    def test_requeue_clears_importer_questions(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="needs_owner")
        task["importPhase"] = "collision"
        task["openQuestions"] = ["siutindei would update existing organisations: Kidz Club"]
        board_store.put_task(self.table, task)
        out = board_catalog_import.requeue_for_import(self.table, task)
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "awaiting_import")
        self.assertEqual(saved.get("openQuestions"), [])
        self.assertEqual(out.get("taskId"), task["taskId"])

    def test_accept_preserves_accepted_at(self) -> None:
        settings = _enable_staff(self.table)
        first = board_staff._accept_task(self.table, self._sheet_task(settings), "2026-09-16T12:00:00Z")
        self.assertEqual(first.get("acceptedAt"), "2026-09-16T12:00:00Z")
        again = board_catalog_import.accept_catalog_task(self.table, first, "2026-09-17T12:00:00Z")
        self.assertEqual(again.get("acceptedAt"), "2026-09-16T12:00:00Z")

    def test_cap_counts_parked_import_sheets(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch("board_async.invoke_async", lambda payload, fallback=None: None):
            first = board_catalog.create_next(self.table, settings)
        first["status"] = "needs_owner"
        first["importPhase"] = "collision"
        board_store.put_task(self.table, first)
        with patch.object(board_catalog_import, "BOARD_CATALOG_MAX_AWAITING_IMPORT", 1):
            with self.assertRaises(board_staff.StaffError) as ctx:
                board_catalog.create_next(self.table, settings)
        self.assertIn("awaiting_import cap", str(ctx.exception))

    def test_import_drops_scheduled_hold(self) -> None:
        settings = _enable_staff(self.table)
        settings["catalog"] = {"autoImport": True}
        settings = board_store.save_settings(self.table, settings)
        task = board_staff._accept_task(self.table, self._sheet_task(settings), "2026-09-16T12:00:00Z")
        board_catalog_import.handle_tick(self.table, settings)
        self.assertEqual(len(board_store.list_holds(self.table, "scheduled", limit=20)), 1)
        board_catalog_import.run_import(self.table, board_store.get_task(self.table, task["taskId"]))
        self.assertEqual(board_store.list_holds(self.table, "scheduled", limit=20), [])
        vetoed = board_store.list_holds(self.table, "vetoed", limit=20)
        self.assertEqual(len(vetoed), 1)
        self.assertEqual(vetoed[0].get("vetoReason"), "imported")

    def test_stored_zero_catalog_hold_becomes_default(self) -> None:
        out = board_store.normalize_boundaries({"holds": {"catalog_import": 0}})
        self.assertEqual(out["holds"]["catalog_import"], 2)
        self.assertNotIn("catalog_import", out["holdOverrides"])
        explicit = board_store.normalize_boundaries(
            {"holds": {"catalog_import": 0}, "holdOverrides": {"catalog_import": 0}}
        )
        self.assertEqual(explicit["holds"]["catalog_import"], 0)
        self.assertEqual(explicit["holdOverrides"]["catalog_import"], 0)

    def _stale_iso(self) -> str:
        return (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_tick_revalidates_parked_invalid_remote_sheet(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="needs_owner")
        task["importPhase"] = "invalid"
        _stamp_fresh_remote(
            task,
            ok=False,
            errors=["name_translations.zh-HK must be a valid ISO 639-1 language code"],
        )
        task["lastValidatedAt"] = self._stale_iso()
        board_store.put_task(self.table, task)
        out = board_catalog_import.handle_tick(self.table, settings)
        self.assertEqual(out["revalidated"], 1)
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "awaiting_import")
        self.assertEqual(saved.get("importPhase"), "validated")
        self.assertEqual(saved.get("revalidateAttempts"), 0)

    def test_tick_skips_fresh_parked_invalid_sheet(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="needs_owner")
        task["importPhase"] = "invalid"
        _stamp_fresh_remote(task, ok=False)
        board_store.put_task(self.table, task)
        out = board_catalog_import.handle_tick(self.table, settings)
        self.assertEqual(out["revalidated"], 0)
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "needs_owner")
        self.assertEqual(saved.get("importPhase"), "invalid")

    def test_tick_skips_local_invalid_sheet(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="needs_owner")
        task["importPhase"] = "invalid"
        task["lastValidatedAt"] = self._stale_iso()
        task["importPreview"] = {
            "ok": False,
            "dryRun": {"ok": False, "mode": "local", "errors": ["name is not in verified_fields"]},
        }
        board_store.put_task(self.table, task)
        out = board_catalog_import.handle_tick(self.table, settings)
        self.assertEqual(out["revalidated"], 0)
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "needs_owner")

    def test_tick_stops_after_three_parked_revalidates(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="needs_owner")
        task["importPhase"] = "rejected"
        task["revalidateAttempts"] = 3
        _stamp_fresh_remote(task, ok=False)
        task["lastValidatedAt"] = self._stale_iso()
        board_store.put_task(self.table, task)
        out = board_catalog_import.handle_tick(self.table, settings)
        self.assertEqual(out["revalidated"], 0)
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "needs_owner")
        self.assertEqual(saved.get("revalidateAttempts"), 3)

    def test_requeue_resets_revalidate_attempts(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="needs_owner")
        task["importPhase"] = "invalid"
        task["revalidateAttempts"] = 2
        board_store.put_task(self.table, task)
        out = board_catalog_import.requeue_for_import(self.table, task)
        self.assertTrue(out["ok"])
        saved = out["task"]
        self.assertEqual(saved.get("status"), "awaiting_import")
        self.assertEqual(saved.get("importPhase"), "pending")
        self.assertEqual(saved.get("revalidateAttempts"), 0)

    def test_owner_preview_resets_revalidate_attempts(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="needs_owner")
        task["importPhase"] = "invalid"
        task["revalidateAttempts"] = 2
        board_store.put_task(self.table, task)
        preview = board_catalog_import.owner_preview(self.table, {"taskId": task["taskId"]})
        self.assertTrue(preview.get("ok"))
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "awaiting_import")
        self.assertEqual(saved.get("importPhase"), "validated")
        self.assertEqual(saved.get("revalidateAttempts"), 0)

    def test_owner_preview_local_resets_revalidate_attempts(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="needs_owner")
        task["importPhase"] = "invalid"
        task["revalidateAttempts"] = 2
        _stamp_fresh_remote(task, ok=False)
        board_store.put_task(self.table, task)
        preview = board_catalog_import.owner_preview(
            self.table, {"taskId": task["taskId"], "remote": False}
        )
        self.assertTrue(preview.get("ok"))
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("revalidateAttempts"), 0)

    def _rejecting_remote_http(self) -> None:
        def http(method, url, headers, body):
            parsed = json.loads(body) if body else None
            if url.endswith("/admin/imports/presign"):
                return {
                    "upload_url": "https://s3.example.test/put?X-Amz-Signature=secret",
                    "object_key": "imports/board.json",
                }
            if url.startswith("https://s3.example.test/put"):
                return {"status": 200}
            if url.endswith("/admin/imports"):
                return {
                    "status": 200,
                    "dry_run": bool((parsed or {}).get("dry_run")),
                    "summary": {
                        "organizations": {"created": 0, "updated": 0, "failed": 1, "skipped": 0},
                        "locations": {"created": 0, "updated": 0, "failed": 0, "skipped": 0},
                        "activities": {"created": 0, "updated": 0, "failed": 0, "skipped": 0},
                        "pricing": {"created": 0, "updated": 0, "failed": 0, "skipped": 0},
                        "schedules": {"created": 0, "updated": 0, "failed": 0, "skipped": 0},
                        "warnings": 0,
                        "errors": 1,
                    },
                    "results": [
                        {
                            "type": "organizations",
                            "key": "Quarry Bay Park Playground",
                            "status": "failed",
                            "warnings": [],
                            "errors": [
                                {
                                    "message": "name_translations.zh-HK must be a valid ISO 639-1 language code"
                                }
                            ],
                        }
                    ],
                    "file_warnings": [],
                }
            raise AssertionError(url)

        board_catalog_import.set_http_for_tests(http)

    def test_tick_reparks_invalid_remote_sheet_and_counts_attempt(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="needs_owner")
        task["importPhase"] = "invalid"
        _stamp_fresh_remote(
            task,
            ok=False,
            errors=["name_translations.zh-HK must be a valid ISO 639-1 language code"],
        )
        task["lastValidatedAt"] = self._stale_iso()
        board_store.put_task(self.table, task)
        self._rejecting_remote_http()
        out = board_catalog_import.handle_tick(self.table, settings)
        self.assertEqual(out["revalidated"], 1)
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "needs_owner")
        self.assertEqual(saved.get("importPhase"), "rejected")
        self.assertEqual(saved.get("revalidateAttempts"), 1)
        questions = saved.get("openQuestions") or []
        zh = [q for q in questions if "zh-HK" in str(q)]
        self.assertEqual(len(zh), 1)
        saved["lastValidatedAt"] = self._stale_iso()
        board_store.put_task(self.table, saved)
        again = board_catalog_import.handle_tick(self.table, settings)
        self.assertEqual(again["revalidated"], 1)
        latest = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(latest.get("revalidateAttempts"), 2)
        self.assertEqual(len([q for q in (latest.get("openQuestions") or []) if "zh-HK" in str(q)]), 1)

    def test_tick_remote_error_keeps_parked_without_spending_attempt(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="needs_owner")
        task["importPhase"] = "invalid"
        _stamp_fresh_remote(task, ok=False)
        task["lastValidatedAt"] = self._stale_iso()
        board_store.put_task(self.table, task)
        board_catalog_import.set_auth_for_tests(
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cognito down"))
        )
        out = board_catalog_import.handle_tick(self.table, settings)
        self.assertEqual(out["revalidated"], 1)
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "needs_owner")
        self.assertEqual(saved.get("importPhase"), "invalid")
        self.assertEqual(int(saved.get("revalidateAttempts") or 0), 0)
        self.assertIn("cognito", str(saved.get("importError") or "").lower())
        dry = (saved.get("importPreview") or {}).get("dryRun") or {}
        self.assertTrue(dry.get("remoteError"))
        self.assertEqual(dry.get("mode"), "remote")

    def test_tick_records_give_up_after_third_parked_revalidate(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="needs_owner")
        task["importPhase"] = "rejected"
        task["revalidateAttempts"] = 2
        _stamp_fresh_remote(task, ok=False)
        task["lastValidatedAt"] = self._stale_iso()
        board_store.put_task(self.table, task)
        self._rejecting_remote_http()
        out = board_catalog_import.handle_tick(self.table, settings)
        self.assertEqual(out["revalidated"], 1)
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "needs_owner")
        self.assertEqual(saved.get("revalidateAttempts"), 3)
        self.assertIn(board_catalog_import._revalidate_gave_up_line(), saved.get("openQuestions") or [])
        saved["lastValidatedAt"] = self._stale_iso()
        board_store.put_task(self.table, saved)
        again = board_catalog_import.handle_tick(self.table, settings)
        self.assertEqual(again["revalidated"], 0)
        headline = board_catalog_import.catalog_headline(self.table)
        self.assertEqual(headline["revalidateExhausted"], 1)
        parked = headline["parkedSheets"]
        self.assertEqual(parked[0]["revalidateAttempts"], 3)
        self.assertEqual(parked[0]["taskId"], task["taskId"])

    def test_http_attaches_amzn_request_id(self) -> None:
        headers = {"x-amzn-RequestId": "req-abc"}
        err = urllib.error.HTTPError(
            "https://siu.example/v1/admin/imports",
            500,
            "boom",
            headers,
            io.BytesIO(b'{"error":"x"}'),
        )
        board_catalog_import.set_http_for_tests(None)

        def boom(*_a, **_k):
            raise err

        with patch("urllib.request.urlopen", boom):
            with self.assertRaises(board_catalog_import.CatalogImportError) as ctx:
                board_catalog_import._http("POST", "https://siu.example/v1/admin/imports")
        self.assertEqual(ctx.exception.request_id, "req-abc")
        self.assertIn("requestId=req-abc", str(ctx.exception))

    def test_http_wraps_read_timeout(self) -> None:
        board_catalog_import.set_http_for_tests(None)

        def boom(*_a, **_k):
            raise TimeoutError("The read operation timed out")

        with patch("urllib.request.urlopen", boom):
            with self.assertRaises(board_catalog_import.CatalogImportError) as ctx:
                board_catalog_import._http(
                    "POST",
                    "https://siu.example/v1/admin/imports",
                    timeout=board_catalog_import._IMPORT_HTTP_TIMEOUT,
                )
        self.assertIn("timed out", str(ctx.exception))
        self.assertIn("siutindei admin POST", str(ctx.exception))

    def test_three_remote_errors_open_cto_task(self) -> None:
        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "cto", {"isActive": True})
        task = self._sheet_task(settings, status="awaiting_import")
        task["importPhase"] = "pending"
        preview = dict(task.get("importPreview") or {})
        preview["dryRun"] = {"mode": "remote", "remoteError": "siutindei 500 DetachedInstanceError"}
        task["importPreview"] = preview
        board_store.put_task(self.table, task)
        with patch("board_async.invoke_async", lambda payload, fallback=None: None):
            for _ in range(3):
                latest = board_store.get_task(self.table, task["taskId"]) or task
                board_catalog_import._note_pending_remote_error(self.table, settings, latest)
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("remoteErrorCount"), 3)
        row = board_catalog_import.engineering_import_error(self.table)
        self.assertEqual(row["kind"], "siutindei-import")
        headline = board_catalog_import.catalog_headline(self.table)
        self.assertGreaterEqual(int(headline.get("remoteErrorSheets") or 0), 1)
        opened = [
            t
            for status in ("queued", "running")
            for t in board_store.list_tasks(self.table, status, limit=50)
            if (t.get("eventRef") or {}).get("id") == "siutindei-import-error"
        ]
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["assignee"], "cto")

    def test_remote_error_clears_on_recovery(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="awaiting_import")
        task["importError"] = (
            "siutindei admin POST https://siu.example/v1/admin/imports failed: 500 boom requestId=req-1"
        )
        task["remoteErrorCount"] = 2
        task["remoteErrorFirstAt"] = "2026-09-01T00:00:00Z"
        preview = dict(task.get("importPreview") or {})
        preview["dryRun"] = {"mode": "remote", "ok": True}
        task["importPreview"] = preview
        board_store.put_task(self.table, task)
        latest = board_store.get_task(self.table, task["taskId"]) or task
        board_catalog_import._note_pending_remote_error(self.table, settings, latest)
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("remoteErrorCount"), 0)
        self.assertFalse(saved.get("remoteErrorFirstAt"))
        self.assertFalse(saved.get("importError"))

    def test_remote_error_recovery_keeps_collision_import_error(self) -> None:
        settings = _enable_staff(self.table)
        task = self._sheet_task(settings, status="needs_owner")
        task["importError"] = "name collision: Foo Park"
        task["remoteErrorCount"] = 2
        task["remoteErrorFirstAt"] = "2026-09-01T00:00:00Z"
        preview = dict(task.get("importPreview") or {})
        preview["dryRun"] = {"mode": "remote", "ok": True}
        task["importPreview"] = preview
        board_store.put_task(self.table, task)
        latest = board_store.get_task(self.table, task["taskId"]) or task
        board_catalog_import._note_pending_remote_error(self.table, settings, latest)
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("importError"), "name collision: Foo Park")
        self.assertEqual(saved.get("remoteErrorCount"), 0)
        self.assertFalse(saved.get("remoteErrorFirstAt"))


class RouteTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        os.environ.pop("BOARD_CATALOG_IMPORT_ENABLED", None)
        os.environ["BOARD_CATALOG_MANAGER_ID"] = "mgr-1"
        self.addCleanup(lambda: os.environ.pop("BOARD_CATALOG_MANAGER_ID", None))

    def test_preview_route(self) -> None:
        import board_routes

        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch("board_async.invoke_async", lambda payload, fallback=None: None):
            task = board_catalog.create_next(self.table, settings)
        key = board_staff._deliverable_key(task["taskId"], "json")
        board_staff._blob_put(key, __import__("json").dumps(SHEET).encode())
        task["deliverableKey"] = key
        board_store.put_task(self.table, task)
        event = self.event("/siu-tin-dei/board/catalog/preview", "POST", {"taskId": task["taskId"]})
        resp = board_routes.handle_board_route(event, "POST", "/siu-tin-dei/board/catalog/preview", "owner")
        self.assertEqual(resp["statusCode"], 200)
        body = __import__("json").loads(resp["body"])
        self.assertTrue(body["preview"]["ok"])
        self.assertFalse(body["preview"]["importEnabled"])
        # Importer env is unset here, so the default remote request stays local.
        self.assertEqual((body["preview"].get("dryRun") or {}).get("mode"), "local")

    def test_import_route_conflict_when_off(self) -> None:
        import board_routes

        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch("board_async.invoke_async", lambda payload, fallback=None: None):
            task = board_catalog.create_next(self.table, settings)
        event = self.event("/siu-tin-dei/board/catalog/import", "POST", {"taskId": task["taskId"]})
        resp = board_routes.handle_board_route(event, "POST", "/siu-tin-dei/board/catalog/import", "owner")
        self.assertEqual(resp["statusCode"], 409)
        self.assertIn("switched off", resp["body"])

    def test_skip_route(self) -> None:
        import board_routes

        settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        with patch("board_async.invoke_async", lambda payload, fallback=None: None):
            task = board_catalog.create_next(self.table, settings)
        task["status"] = "awaiting_import"
        task["importPhase"] = "pending"
        board_store.put_task(self.table, task)
        event = self.event("/siu-tin-dei/board/catalog/skip", "POST", {"taskId": task["taskId"]})
        resp = board_routes.handle_board_route(event, "POST", "/siu-tin-dei/board/catalog/skip", "owner")
        self.assertEqual(resp["statusCode"], 200)
        saved = board_store.get_task(self.table, task["taskId"])
        self.assertEqual(saved.get("status"), "delivered")
        self.assertTrue(saved.get("importSkipped"))


if __name__ == "__main__":
    unittest.main()
