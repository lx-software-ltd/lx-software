"""A pre-launch home page tells the board that GA4 zero is expected."""

from __future__ import annotations

from unittest.mock import patch

import board_context
import board_crawl
import board_web
import board_web_live
from test_board import BoardTestCase

_MAINTENANCE = "<html><head><meta name='robots' content='noindex'></head><body>Coming soon</body></html>"


class SiteLiveTests(BoardTestCase):
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
