"""A pre-launch home page tells the board that GA4 zero is expected."""

from __future__ import annotations

from unittest.mock import patch

import board_context
import board_crawl
import board_store
import board_web
import board_web_live
from test_board import BoardTestCase

_MAINTENANCE = "<html><head><meta name='robots' content='noindex'></head><body>Coming soon</body></html>"


class SiteLiveTests(BoardTestCase):
    allow_site_probe = True

    def test_maintenance_html_is_not_live(self) -> None:
        fetched = board_crawl.FetchResult(
            status=200,
            final_url="https://siutindei.com/",
            content_type="text/html",
            text=_MAINTENANCE,
            hash="abc",
        )
        with patch("board_crawl.fetch", return_value=fetched):
            status = board_web_live.site_status(self.table)
        self.assertIs(status["siteLive"], False)
        digest = board_web.digest_for_context(self.table)
        self.assertIs(digest["siteLive"], False)
        rendered = board_context.render_context_pack({"web": digest})
        self.assertIn(board_web_live.MAINTENANCE_LINE, rendered)
        noted = board_web_live.annotate(self.table, {"sessions": 0})
        self.assertIn("pre-launch maintenance", noted["note"])

    def test_a_failed_probe_is_not_repeated(self) -> None:
        with patch("board_crawl.fetch", side_effect=OSError("offline")) as fetch:
            self.assertEqual(board_web_live.site_status(self.table), {})
            self.assertEqual(board_web_live.site_status(self.table), {})
        self.assertEqual(fetch.call_count, 1)

    def test_maintenance_is_cached_for_an_hour_and_live_for_a_day(self) -> None:
        maintenance = board_crawl.FetchResult(
            status=200, final_url="https://siutindei.com/", content_type="text/html", text=_MAINTENANCE, hash="m"
        )
        with (
            patch("board_crawl.fetch", return_value=maintenance),
            patch.object(board_store, "put_cache", wraps=board_store.put_cache) as cached,
        ):
            board_web_live.site_status(self.table)
        self.assertEqual(cached.call_args.kwargs["ttl_seconds"], board_web_live.MAINTENANCE_TTL)

    def test_a_live_home_page_is_cached_for_a_day(self) -> None:
        live = board_crawl.FetchResult(
            status=200,
            final_url="https://siutindei.com/",
            content_type="text/html",
            text="<html><script>GTM-ABC123</script></html>",
            hash="l",
        )
        with (
            patch("board_crawl.fetch", return_value=live),
            patch.object(board_store, "put_cache", wraps=board_store.put_cache) as cached,
        ):
            status = board_web_live.site_status(self.table)
        self.assertIs(status["siteLive"], True)
        self.assertEqual(cached.call_args.kwargs["ttl_seconds"], board_web_live.LIVE_TTL)
