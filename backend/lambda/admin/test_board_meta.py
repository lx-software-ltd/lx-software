"""Retired Meta insight names are dropped before the Graph call."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import board_meta
import board_meta_metrics


class MetricAllowListTests(unittest.TestCase):
    def test_retired_page_metrics_fall_back_when_nothing_current_remains(self) -> None:
        metric, ignored = board_meta_metrics.choose("page_impressions,page_engaged_users", kind="page")
        self.assertEqual(metric, board_meta_metrics.PAGE_DEFAULT)
        self.assertEqual(ignored, ["page_impressions", "page_engaged_users"])

    def test_a_current_name_is_kept_and_the_retired_name_is_reported(self) -> None:
        metric, ignored = board_meta_metrics.choose("page_media_view,page_impressions", kind="page")
        self.assertEqual(metric, "page_media_view")
        self.assertEqual(ignored, ["page_impressions"])

    def test_page_insights_drops_retired_names(self) -> None:
        with (
            patch("board_meta.page_id", return_value="page-1"),
            patch("board_meta.graph_pages", return_value=[]) as graph,
        ):
            out = board_meta.op_page_insights(None, {"metric": "impressions,page_media_view"})
        self.assertEqual(out["ignoredMetrics"], ["impressions"])
        self.assertEqual(graph.call_args.args[2]["metric"], "page_media_view")

    def test_ig_insights_drops_retired_names(self) -> None:
        with (
            patch("board_meta.ig_user_id", return_value="ig-1"),
            patch("board_meta.graph_pages", return_value=[]) as graph,
        ):
            out = board_meta.op_ig_insights(None, {"metric": "impressions,reach"})
        self.assertEqual(out["ignoredMetrics"], ["impressions"])
        self.assertEqual(graph.call_args.args[2]["metric"], "reach")
