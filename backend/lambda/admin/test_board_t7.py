"""T7: act rollout — phone allow-list, owner ads caps, boost_post, spend tracking."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import board_meta
import board_store
from board_tools import REGISTRY, ToolContext, execute_call
from test_board_t5 import MetaTestCase


class TestT7AllowListAndCaps(MetaTestCase):
    def test_phone_allow_list_put_persists_and_whatsapp_acts(self) -> None:
        status, body = self.call(
            "/v1/admin/siutindei/board/tools",
            "PUT",
            {"globalMode": "act", "allowList": ["+852 9123 4567"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["config"]["allowList"], ["+85291234567"])
        self.assertIn("spendCaps", body["config"])
        self.assertIn("adsSpend", body)
        now = datetime.now(timezone.utc)
        thread_id = board_meta.whatsapp_thread_id("+85291234567")
        board_store.put_meta_thread(
            self.table,
            {
                "threadId": thread_id,
                "channel": "whatsapp",
                "senderId": "85291234567",
                "lastInboundAt": now.isoformat().replace("+00:00", "Z"),
                "unread": True,
            },
        )
        settings = board_store.load_settings(self.table)
        ctx = ToolContext(table=self.table, settings=settings, persona_id="coo", actor="persona")
        ok = execute_call(
            ctx,
            REGISTRY["meta_reply_whatsapp"],
            {"to": "+85291234567", "threadId": thread_id, "message": "Hi", "reason": "In window."},
        )
        self.assertEqual(ok.status, "ok")
        # Digit-only match: stored +852… vs a to= without plus.
        also = execute_call(
            ctx,
            REGISTRY["meta_reply_whatsapp"],
            {"to": "85291234567", "threadId": thread_id, "message": "Hi again", "reason": "Same number."},
        )
        self.assertEqual(also.status, "ok")

    def test_spend_caps_put_clamps_and_overrides_guard(self) -> None:
        status, body = self.call(
            "/v1/admin/siutindei/board/tools",
            "PUT",
            {"spendCaps": {"metaAdsDailyUsd": -3, "metaAdsMonthlyUsd": 9999}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["config"]["spendCaps"]["metaAdsDailyUsd"], 0.0)
        self.assertEqual(body["config"]["spendCaps"]["metaAdsMonthlyUsd"], 2000.0)
        status, body = self.call(
            "/v1/admin/siutindei/board/tools",
            "PUT",
            {"globalMode": "act", "spendCaps": {"metaAdsDailyUsd": 20, "metaAdsMonthlyUsd": 400}},
        )
        self.assertEqual(status, 200)
        settings = board_store.load_settings(self.table)
        ctx = ToolContext(table=self.table, settings=settings, persona_id="cmo", actor="persona")
        out = execute_call(
            ctx,
            REGISTRY["meta_create_ad_set"],
            {"name": "HK boost", "dailyBudgetUsd": 10, "reason": "Fits the raised monthly cap."},
        )
        self.assertEqual(out.status, "ok")
        self.assertEqual(out.result["status"], "PAUSED")
        spend = board_store.load_ads_spend(self.table)
        self.assertEqual(spend["dailyUsd"], 10.0)
        self.assertEqual(spend["monthlyUsd"], 300.0)
        status, body = self.call("/v1/admin/siutindei/board/tools")
        self.assertEqual(status, 200)
        self.assertEqual(body["adsSpend"]["recordedDailyUsd"], 10.0)
        self.assertEqual(body["adsSpend"]["recordedMonthlyUsd"], 300.0)

    def test_ad_set_under_daily_cap_acts_when_monthly_fits(self) -> None:
        ctx = self._ctx("cmo", global_mode="act")
        out = execute_call(
            ctx,
            REGISTRY["meta_create_ad_set"],
            {"name": "Small", "dailyBudgetUsd": 1, "reason": "USD 30 month is under 50."},
        )
        self.assertEqual(out.status, "ok")

    def test_daily_cap_ten_is_allowed_eleven_is_not(self) -> None:
        ctx = self._ctx("cmo", global_mode="act")
        ok = execute_call(
            ctx,
            REGISTRY["meta_create_ad_set"],
            {"name": "At cap", "dailyBudgetUsd": 10, "reason": "Equals the daily cap."},
        )
        # 10 * 30 = 300 > monthly 50, so this still proposes on the monthly rule.
        self.assertEqual(ok.status, "pending_approval")
        self.assertIn("cap", ok.result["message"])
        settings = board_store.load_settings(self.table)
        settings["tools"]["globalMode"] = "act"
        settings["tools"]["spendCaps"] = {"metaAdsDailyUsd": 10, "metaAdsMonthlyUsd": 400}
        board_store.save_settings(self.table, settings)
        ctx = ToolContext(table=self.table, settings=settings, persona_id="cmo", actor="persona")
        at_daily = execute_call(
            ctx,
            REGISTRY["meta_create_ad_set"],
            {"name": "At daily", "dailyBudgetUsd": 10, "reason": "Daily 10 is allowed."},
        )
        self.assertEqual(at_daily.status, "ok")
        over_daily = execute_call(
            ctx,
            REGISTRY["meta_create_ad_set"],
            {"name": "Over daily", "dailyBudgetUsd": 11, "reason": "Over the daily cap."},
        )
        self.assertEqual(over_daily.status, "pending_approval")
        self.assertIn("daily cap", over_daily.result["message"])

    def test_recorded_spend_forces_propose(self) -> None:
        settings = board_store.load_settings(self.table)
        settings["tools"]["globalMode"] = "act"
        settings["tools"]["spendCaps"] = {"metaAdsDailyUsd": 10, "metaAdsMonthlyUsd": 400}
        board_store.save_settings(self.table, settings)
        board_store.record_ads_spend(self.table, daily_usd=9, monthly_usd=9)
        ctx = ToolContext(table=self.table, settings=settings, persona_id="cmo", actor="persona")
        out = execute_call(
            ctx,
            REGISTRY["meta_create_ad_set"],
            {"name": "Overflow", "dailyBudgetUsd": 2, "reason": "9 + 2 exceeds daily 10."},
        )
        self.assertEqual(out.status, "pending_approval")
        self.assertIn("daily cap", out.result["message"])

    def test_graph_month_spend_forces_propose(self) -> None:
        ctx = self._ctx("cmo", global_mode="act")
        with patch.object(board_meta, "graph_month_spend", return_value=40.0):
            out = execute_call(
                ctx,
                REGISTRY["meta_create_ad_set"],
                {"name": "Overflow", "dailyBudgetUsd": 1, "reason": "40 + 30 exceeds monthly 50."},
            )
        self.assertEqual(out.status, "pending_approval")
        self.assertIn("month", out.result["message"])

    def test_boost_post_acts_under_cap_and_proposes_over(self) -> None:
        ctx = self._ctx("cmo", global_mode="act")
        ok = execute_call(
            ctx,
            REGISTRY["meta_boost_post"],
            {"postId": "111", "dailyBudgetUsd": 2, "days": 3, "reason": "USD 6 month fits."},
        )
        self.assertEqual(ok.status, "ok")
        self.assertEqual(ok.result["status"], "ACTIVE")
        self.assertEqual(ok.result["objectStoryId"], "page-1_111")
        self.assertTrue(any("/campaigns" in url for _m, url, _b in self.graph.calls))
        self.assertTrue(any("/ads" in url and "/adsets" not in url for _m, url, _b in self.graph.calls))
        spend = board_store.load_ads_spend(self.table)
        self.assertEqual(spend["dailyUsd"], 2.0)
        self.assertEqual(spend["monthlyUsd"], 6.0)
        over = execute_call(
            ctx,
            REGISTRY["meta_boost_post"],
            {"postId": "222", "dailyBudgetUsd": 10, "days": 30, "reason": "USD 300 exceeds 50."},
        )
        self.assertEqual(over.status, "pending_approval")
        self.assertIn("cap", over.result["message"])

    def test_boost_post_is_registered(self) -> None:
        self.assertIn("meta_boost_post", REGISTRY)
        self.assertEqual(REGISTRY["meta_boost_post"].tool_id, "meta")
        self.assertTrue(REGISTRY["meta_boost_post"].is_write)


class TestT7AdSetOverCapStillProposes(MetaTestCase):
    def test_ad_set_over_cap_is_forced_to_propose(self) -> None:
        ctx = self._ctx("cmo", global_mode="act")
        out = execute_call(
            ctx,
            REGISTRY["meta_create_ad_set"],
            {"name": "Boost", "dailyBudgetUsd": 10, "reason": "Too spendy."},
        )
        self.assertEqual(out.status, "pending_approval")
        self.assertIn("cap", out.result["message"])
