"""Unit tests for the OpenRouter usage ledger and bill split."""

from __future__ import annotations

import unittest

from test_board import FakeTable  # noqa: E402

import openrouter_usage  # noqa: E402
from openrouter_client import SERVICE_EXECUTIVE_BOARD, SERVICE_STATEMENT_PARSER  # noqa: E402


class TestOpenRouterUsage(unittest.TestCase):
    def test_cost_centers(self) -> None:
        self.assertEqual(
            openrouter_usage.cost_center_for(
                service=SERVICE_EXECUTIVE_BOARD, owner="siuTinDei"
            ),
            "siuTinDei",
        )
        self.assertEqual(
            openrouter_usage.cost_center_for(
                service=SERVICE_STATEMENT_PARSER, owner="siuTinDei"
            ),
            "siuTinDei",
        )
        self.assertEqual(
            openrouter_usage.cost_center_for(
                service=SERVICE_STATEMENT_PARSER, owner="lxSoftware"
            ),
            "lxSoftware",
        )
        self.assertEqual(
            openrouter_usage.cost_center_for(
                service=SERVICE_STATEMENT_PARSER, owner="hillmarton"
            ),
            "hillmarton",
        )

    def test_month_rollup_splits_the_bill(self) -> None:
        table = FakeTable()
        openrouter_usage.add_usage_day(
            table,
            service=SERVICE_EXECUTIVE_BOARD,
            owner="siuTinDei",
            usage={"promptTokens": 10, "completionTokens": 5, "totalTokens": 15, "cost": 1.2},
            date_iso="2026-09-02",
        )
        openrouter_usage.add_usage_day(
            table,
            service=SERVICE_STATEMENT_PARSER,
            owner="siuTinDei",
            usage={"promptTokens": 20, "completionTokens": 2, "totalTokens": 22, "cost": 0.3},
            date_iso="2026-09-03",
        )
        openrouter_usage.add_usage_day(
            table,
            service=SERVICE_STATEMENT_PARSER,
            owner="hillmarton",
            usage={"promptTokens": 8, "completionTokens": 1, "totalTokens": 9, "cost": 0.4},
            date_iso="2026-09-03",
        )
        openrouter_usage.add_usage_day(
            table,
            service=SERVICE_STATEMENT_PARSER,
            owner="lxSoftware",
            usage={"promptTokens": 4, "completionTokens": 1, "totalTokens": 5, "cost": 0.1},
            date_iso="2026-09-04",
        )
        out = openrouter_usage.list_usage(table, from_day="2026-09-01", to_day="2026-09-08")
        self.assertAlmostEqual(out["total"]["cost"], 2.0)
        self.assertEqual(out["total"]["calls"], 4)
        by_id = {c["id"]: c for c in out["costCenters"]}
        self.assertAlmostEqual(by_id["siuTinDei"]["cost"], 1.5)
        self.assertEqual(len(by_id["siuTinDei"]["services"]), 2)
        self.assertAlmostEqual(by_id["lxSoftware"]["cost"], 0.1)
        self.assertAlmostEqual(by_id["hillmarton"]["cost"], 0.4)

    def test_rejects_inverted_range(self) -> None:
        table = FakeTable()
        with self.assertRaises(ValueError):
            openrouter_usage.list_usage(table, from_day="2026-09-10", to_day="2026-09-01")


if __name__ == "__main__":
    unittest.main()
