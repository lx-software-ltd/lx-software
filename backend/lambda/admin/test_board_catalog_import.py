"""Unit tests for catalog sheet → importer JSON (Option A)."""

from __future__ import annotations

import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from test_board import BoardTestCase

import board_catalog
import board_catalog_import
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
        self.assertEqual(org["category_name"], "Playground")
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
        self.assertEqual(out["organizations"][0]["category_name"], "Playground")
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
                return {"status": 200, "imported": 1}
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
        task["status"] = "delivered"
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
        self.assertEqual((saved.get("importResult") or {}).get("sent"), 1)

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
        self.assertIn("delivered", str(ctx.exception))

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
        delivered = board_staff._accept_task(self.table, task, "2026-09-16T12:00:00Z")
        self.assertEqual(delivered["status"], "delivered")
        preview = delivered.get("importPreview") or {}
        self.assertTrue(preview.get("ok"))
        self.assertEqual((preview.get("dryRun") or {}).get("accepted"), 1)
        self.assertFalse(delivered.get("importedAt"))
        self.assertEqual(self.calls, [])


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


if __name__ == "__main__":
    unittest.main()
