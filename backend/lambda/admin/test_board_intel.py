"""Unit tests for Executive Board market intelligence (WP5)."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from contract_constants import BOARD_KEY
from test_board import BoardTestCase, FakeTable

import board_crawl
import board_intel
import board_opendata
import board_staff
import board_store
import board_watch


FIXTURES = Path(__file__).resolve().parent / "test_fixtures"


def _enable_staff(table: Any, **staff: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True, **staff})
    return board_store.save_settings(table, settings)


class SsrfTests(BoardTestCase):
    def test_link_local_and_redirect_refused(self) -> None:
        with self.assertRaises(Exception):
            board_crawl.fetch("http://169.254.169.254/")
        self.assertTrue(board_crawl.host_is_blocked("127.0.0.1"))
        self.assertTrue(board_crawl.host_is_blocked("169.254.169.254"))

    def test_fetch_page_requires_watchlist(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        settings = _enable_staff(self.table)
        ctx = type("C", (), {"table": self.table, "settings": settings})()
        refused = board_intel.op_fetch_page(ctx, {"url": "https://evil.example/"})
        self.assertIn("watchlist", refused.get("error") or "")
        board_watch.add_watch(self.table, {"name": "Ok", "kind": "competitor", "urls": ["https://ok.example/home"]})
        fetched = board_crawl.FetchResult(status=200, final_url="https://ok.example/home", content_type="text/html", text="<p>hi</p>", hash="h")
        with patch.object(board_crawl, "fetch", return_value=fetched), patch.object(board_crawl, "robots_allows", return_value=True):
            allowed = board_intel.op_fetch_page(ctx, {"url": "https://ok.example/home"})
        self.assertEqual(allowed.get("status"), 200)


class CrawlHelperTests(unittest.TestCase):
    def test_normalise_strips_counters_dates_and_times(self) -> None:
        raw = "Price 88 updated 2026-09-09 at 14:30:01 visitors 1234567 stay"
        out = board_crawl.normalise(raw)
        self.assertNotIn("2026-09-09", out)
        self.assertNotIn("14:30", out)
        self.assertNotIn("1234567", out)
        self.assertIn("Price 88", out)
        self.assertIn("stay", out)

    def test_robots_denial(self) -> None:
        table = FakeTable()
        robots = "User-agent: *\nDisallow: /secret\n"
        board_store.put_cache(table, "crawl:robots:example.com", {"body": robots}, ttl_seconds=86400)
        self.assertFalse(board_crawl.robots_allows(table, "https://example.com/secret/page"))
        self.assertTrue(board_crawl.robots_allows(table, "https://example.com/public"))

    def test_put_digest_key_uses_board_key(self) -> None:
        key = board_crawl.put_digest("watch-1", "https://example.com/page", "2026-09-11", "hello")
        self.assertEqual(
            key,
            f"board/{BOARD_KEY}/intel/watch-1/{board_crawl.url_digest('https://example.com/page')}/2026-09-11.txt",
        )

    def test_pace_host_sleeps_when_last_fetch_is_recent(self) -> None:
        table = FakeTable()
        board_store.put_cache(
            table,
            "crawl:host:example.com",
            {"lastFetchAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
            ttl_seconds=86400,
        )
        with patch("board_crawl.time.sleep") as sleep:
            board_crawl.pace_host(table, "example.com")
        sleep.assert_called()


class ChangeDetectionTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.settings = _enable_staff(self.table)
        self.watch = board_watch.add_watch(
            self.table,
            {"name": "Kiztopia", "kind": "competitor", "urls": ["https://kiztopia.example/pricing"]},
        )

    def test_second_crawl_writes_change_when_hash_differs(self) -> None:
        first = board_crawl.FetchResult(
            status=200,
            final_url="https://kiztopia.example/pricing",
            content_type="text/html",
            text="<html><body>Price $100 for Saturday swimming classes in Sha Tin this weekend and more details for parents.</body></html>",
            hash="aaa",
        )
        second = board_crawl.FetchResult(
            status=200,
            final_url="https://kiztopia.example/pricing",
            content_type="text/html",
            text="<html><body>Price $120 for Saturday swimming classes in Sha Tin this weekend and more details for parents.</body></html>",
            hash="bbb",
        )
        with (
            patch("board_crawl.robots_allows", return_value=True),
            patch("board_crawl.pace_host"),
            patch("board_crawl.host_backed_off", return_value=False),
            patch("board_intel._desk_summary", return_value="Price went up."),
            patch("board_crawl.fetch", side_effect=[first, second]),
        ):
            board_intel.daily_crawl(self.table, self.settings)
            board_intel.daily_crawl(self.table, self.settings)
        changes = board_store.list_changes(self.table)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["kind"], "pricing")
        self.assertEqual(changes[0]["summary"], "Price went up.")
        public = board_intel.list_changes(self.table, 7)
        self.assertIn("Price $100", public[0]["beforeDigest"])
        self.assertIn("Price $120", public[0]["afterDigest"])

    def test_empty_body_stops_after_two_fetches(self) -> None:
        empty = board_crawl.FetchResult(
            status=200,
            final_url="https://kiztopia.example/pricing",
            content_type="text/html",
            text="<html><body></body></html>",
            hash="empty",
        )
        with (
            patch("board_crawl.robots_allows", return_value=True),
            patch("board_crawl.pace_host"),
            patch("board_crawl.host_backed_off", return_value=False),
            patch("board_crawl.fetch", return_value=empty),
        ):
            board_intel.daily_crawl(self.table, self.settings)
            board_intel.daily_crawl(self.table, self.settings)
            board_intel.daily_crawl(self.table, self.settings)
        pages = board_store.list_watch_pages(self.table, self.watch["watchId"])
        self.assertTrue(pages[0].get("emptyBody"))
        self.assertGreaterEqual(int(pages[0].get("emptyFetches") or 0), 2)


class DiscoverTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = board_store.default_settings()

    def test_candidate_promoted_after_two_weeks(self) -> None:
        payload = {"results": [{"url": "https://newkids.example/classes", "title": "New Kids"}]}

        def _search(_ctx: Any, _args: dict[str, Any]) -> dict[str, Any]:
            return payload

        with (
            patch("board_research.op_search", side_effect=_search),
            patch("board_watch._utc_now") as now,
        ):
            now.return_value = datetime(2026, 9, 7, tzinfo=timezone.utc)
            first = board_watch.discover(self.table, self.settings)
            self.assertEqual(first["added"], 1)
            now.return_value = datetime(2026, 9, 14, tzinfo=timezone.utc)
            second = board_watch.discover(self.table, self.settings)
        self.assertEqual(second["promoted"], 1)
        watches = board_watch.list_watchlist(self.table)
        self.assertEqual(watches[0]["kind"], "competitor")
        self.assertEqual(len(watches[0]["seenWeeks"]), 2)


class BriefTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "market-analyst", {"isActive": True})

    def test_brief_json_creates_later_action_and_dedupes(self) -> None:
        task = board_staff.create_task(
            self.table,
            self.settings,
            assignee="market-analyst",
            origin="duty",
            brief="Write the weekly market brief.",
            deliverable_type="markdown",
            event_ref={"kind": "duty", "id": "market-brief:2026-09-10"},
            created_by="test",
            status="review",
        )
        body = (
            "This week competitors raised prices in Sha Tin.\n\n"
            "```json\n"
            '{"gaps":[{"category":"STEM","district":"Sha Tin","competitorCount":3}],'
            '"ideas":[{"title":"STEM filter on search","why":"three competitors show it","effort":"S"}],'
            '"prospects":[{"name":"Kiztopia Sha Tin","type":"venue","url":"https://kiztopia.example"}]}\n'
            "```\n"
        )
        board_staff._blob_put(f"board/{BOARD_KEY}/staff/{task['taskId']}/deliverable.md", body.encode("utf-8"))  # noqa: SLF001
        task["deliverableKey"] = f"board/{BOARD_KEY}/staff/{task['taskId']}/deliverable.md"
        task["summary"] = "STEM gap in Sha Tin"
        board_store.put_task(self.table, task)
        first = board_intel.on_brief_delivered(self.table, task)
        second = board_intel.on_brief_delivered(self.table, task)
        self.assertEqual(first["ideas"], 1)
        self.assertEqual(second["ideas"], 0)
        actions = [a for a in board_store.list_actions(self.table) if a.get("status") == "open"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["priority"], "later")
        self.assertEqual(actions[0]["persona"], "cpo")
        gaps = board_store.get_cache(self.table, "intel:gaps")
        self.assertEqual(len((gaps or {}).get("payload", {}).get("gaps") or []), 1)
        stored = [p for p in board_store.list_prospects(self.table) if "Kiztopia" in str(p.get("name") or "")]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].get("source"), "intel")
        self.assertEqual(stored[0].get("website"), "https://kiztopia.example")

    def test_accept_task_runs_on_brief_delivered(self) -> None:
        task = board_staff.create_task(
            self.table,
            self.settings,
            assignee="market-analyst",
            origin="duty",
            brief="Write the weekly market brief.",
            deliverable_type="markdown",
            event_ref={"kind": "duty", "id": "market-brief:2026-09-10"},
            created_by="test",
            status="review",
        )
        body = 'Done.\n\n```json\n{"gaps":[],"ideas":[{"title":"Weekend camp pack","why":"season","effort":"M"}],"prospects":[]}\n```\n'
        board_staff._blob_put(f"board/{BOARD_KEY}/staff/{task['taskId']}/deliverable.md", body.encode("utf-8"))  # noqa: SLF001
        task["deliverableKey"] = f"board/{BOARD_KEY}/staff/{task['taskId']}/deliverable.md"
        board_store.put_task(self.table, task)
        board_staff.apply_review(self.table, self.settings, task, verdict="accept", notes="ok", by="manager")
        titles = [a.get("title") for a in board_store.list_actions(self.table)]
        self.assertIn("Weekend camp pack", titles)


class OpendataTests(unittest.TestCase):
    def test_fehd_csv_fixture_maps_districts(self) -> None:
        body = (FIXTURES / "fehd_sample.csv").read_text(encoding="utf-8")
        rows = board_opendata.parse_fehd_csv(body)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["district"], "Sha Tin")
        self.assertEqual(rows[1]["district"], "Islands")
        self.assertEqual(rows[0]["nameEn"], "Happy Kids Kitchen")

    def test_fehd_xml_maps_licence_rows(self) -> None:
        body = """<?xml version="1.0" encoding="UTF-8"?>
<LICENCELIST>
  <LP>
    <EN_NAME>Happy Kids Kitchen</EN_NAME>
    <TC_NAME>快樂小廚房</TC_NAME>
    <ADR>1 Sha Tin Centre Street</ADR>
    <DIST>Sha Tin</DIST>
  </LP>
</LICENCELIST>
"""
        rows = board_opendata.parse_fehd_xml(body)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["district"], "Sha Tin")
        self.assertEqual(rows[0]["nameEn"], "Happy Kids Kitchen")


class RouteTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        _enable_staff(self.table)

    def test_watchlist_crud_and_changes(self) -> None:
        status, body = self.call(
            "/siu-tin-dei/board/watchlist",
            "POST",
            {"name": "Kiztopia", "kind": "competitor", "urls": ["https://kiztopia.example/pricing"]},
        )
        self.assertEqual(status, 201)
        watch_id = body["watch"]["watchId"]
        status, body = self.call("/siu-tin-dei/board/watchlist")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["watches"]), 1)
        status, body = self.call(
            f"/siu-tin-dei/board/watchlist/{watch_id}",
            "PUT",
            {"kind": "directory"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["watch"]["kind"], "directory")
        status, body = self.call("/siu-tin-dei/board/changes", query="days=7")
        self.assertEqual(status, 200)
        self.assertEqual(body["changes"], [])
        status, _ = self.call(f"/siu-tin-dei/board/watchlist/{watch_id}", "DELETE")
        self.assertEqual(status, 200)

    def test_watchlist_409_when_env_off(self) -> None:
        os.environ["BOARD_STAFF_ENABLED"] = "false"
        status, body = self.call("/siu-tin-dei/board/watchlist")
        self.assertEqual(status, 409)
        self.assertIn("disabled", body["message"].lower())
