"""Content calendar, holds and publish (WP7)."""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import patch

import board_content
import board_hk
import board_holds
import board_staff
import board_store
import board_tools
from test_board import BoardTestCase


def _enable_staff(table: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True})
    settings["tools"]["globalMode"] = "act"
    return board_store.save_settings(table, settings)


class FakeGraph:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def __call__(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((method, path, kwargs))
        if method == "POST" and path.endswith("/media"):
            return {"id": "ig-create-1"}
        if method == "POST" and path.endswith("/media_publish"):
            return {"id": "ig-pub-1"}
        if method == "POST" and "/photos" in path:
            return {"id": "fb-post-1"}
        if method == "GET":
            return {"insights": {"post_impressions": 120, "impressions": 90}}
        return {"id": "ok"}


class ContentTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        os.environ["META_PAGE_ID"] = "page-1"
        os.environ["META_IG_USER_ID"] = "ig-1"
        os.environ["META_BOARD_TOKEN"] = "token"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.addCleanup(lambda: os.environ.pop("META_PAGE_ID", None))
        self.addCleanup(lambda: os.environ.pop("META_IG_USER_ID", None))
        self.addCleanup(lambda: os.environ.pop("META_BOARD_TOKEN", None))
        self.settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})
        self.graph = FakeGraph()
        graph_patch = patch("board_meta.graph", self.graph)
        graph_patch.start()
        self.addCleanup(graph_patch.stop)
        page_patch = patch("board_meta.page_id", lambda: "page-1")
        page_patch.start()
        self.addCleanup(page_patch.stop)
        ig_patch = patch("board_meta.ig_user_id", lambda: "ig-1")
        ig_patch.start()
        self.addCleanup(ig_patch.stop)

    def test_plan_json_creates_rows_and_hold(self) -> None:
        slot = "2026-09-14T02:00:00+00:00"
        task = board_staff.create_task(
            self.table,
            self.settings,
            assignee="content-marketer",
            origin="duty",
            brief="Plan the week",
            deliverable_type="json",
            event_ref={"kind": "duty", "id": "content-plan:2026-09-10"},
            created_by="test",
            status="review",
        )
        items = []
        for i, channel in enumerate(["facebook"] * 7 + ["instagram"] * 7 + ["instagram_story"] * 7):
            items.append(
                {
                    "slotAt": slot,
                    "channel": channel,
                    "pillar": "activity spotlight",
                    "copyEn": f"Play {i}",
                    "copyZh": f"玩 {i}",
                    "hashtags": ["siutindei"],
                    "template": "spotlight",
                    "fields": {"title": f"Play {i}"},
                    "linkPath": "/activities",
                }
            )
        board_staff._blob_put(  # noqa: SLF001
            f"board/siuTinDei/staff/{task['taskId']}/deliverable.json",
            __import__("json").dumps({"items": items}).encode("utf-8"),
        )
        task["deliverableKey"] = f"board/siuTinDei/staff/{task['taskId']}/deliverable.json"
        board_store.put_task(self.table, task)
        out = board_content.on_plan_delivered(self.table, self.settings, task)
        self.assertEqual(out["items"], 21)
        rows = board_store.list_content(self.table, "scheduled")
        self.assertGreaterEqual(len(rows), 21)
        holds = board_store.list_holds(self.table, "scheduled")
        fb = [h for h in holds if str(h.get("classKey") or "").startswith("publish:facebook")]
        self.assertTrue(fb)
        self.assertEqual(board_hk.parse_iso(fb[0]["executeAt"]), board_hk.parse_iso(slot))

    def test_publish_fakes_and_ig_cap(self) -> None:
        doc = board_content.upsert_item(
            self.table,
            {
                "channel": "facebook",
                "slotAt": board_store.now_iso(),
                "copyEn": "Hello",
                "copyZh": "你好",
                "template": "news",
                "fields": {"title": "Hello"},
            },
        )
        doc = board_content.render_item(self.table, doc)
        sent = board_content.publish(self.table, self.settings, doc["contentId"])
        self.assertTrue(sent.get("ok"))
        self.assertEqual(sent["platformPostId"], "fb-post-1")
        ig = board_content.upsert_item(
            self.table,
            {
                "channel": "instagram",
                "slotAt": board_store.now_iso(),
                "copyEn": "IG",
                "copyZh": "IG中",
                "template": "guide",
                "fields": {"title": "IG"},
            },
        )
        ig = board_content.render_item(self.table, ig)
        sent_ig = board_content.publish(self.table, self.settings, ig["contentId"])
        self.assertTrue(sent_ig.get("ok"))
        self.assertEqual(sent_ig["platformPostId"], "ig-pub-1")
        story = board_content.upsert_item(
            self.table,
            {"channel": "instagram_story", "copyEn": "Story", "template": "quote", "fields": {"title": "Story"}},
        )
        story = board_content.render_item(self.table, story)
        self.assertTrue(str(story["creativeKeys"][0]).endswith("/0.png"))
        self.assertEqual(len(story["creativeKeys"]), 1)
        sent_story = board_content.publish(self.table, self.settings, story["contentId"])
        self.assertTrue(sent_story.get("ok"))
        self.assertEqual(sent_story["platformPostId"], "ig-pub-1")
        self.assertTrue(any(c[1].endswith("/media") and (c[2].get("body") or {}).get("media_type") == "STORIES" for c in self.graph.calls))
        capped = board_content.upsert_item(
            self.table,
            {
                "channel": "instagram",
                "slotAt": board_store.now_iso(),
                "copyEn": "IG2",
                "copyZh": "IG2中",
                "template": "guide",
                "fields": {"title": "IG2"},
            },
        )
        capped = board_content.render_item(self.table, capped)
        board_store.put_cache(self.table, f"igpublish:{board_hk.today_hkt()}", {"count": 25}, ttl_seconds=86400)
        refused = board_content.publish(self.table, self.settings, capped["contentId"])
        self.assertEqual(refused["error"], "ig daily cap reached")

    def test_assisted_and_readout_boost(self) -> None:
        doc = board_content.upsert_item(
            self.table,
            {
                "channel": "assisted_xiaohongshu",
                "slotAt": "2000-01-01T00:00:00+00:00",
                "copyZh": "小红书",
                "copyEn": "xhs",
                "template": "spotlight",
                "fields": {"title": "XHS"},
            },
            status="scheduled",
        )
        due = board_content.assisted_due(self.table, self.settings)
        self.assertEqual(due[0]["contentId"], doc["contentId"])
        posted = board_content.mark_posted(self.table, doc["contentId"])
        self.assertEqual(posted["platformPostId"], "manual")
        live = board_content.upsert_item(
            self.table,
            {"channel": "facebook", "copyEn": "Boost me", "template": "news", "fields": {"title": "Boost"}},
            status="published",
        )
        live["platformPostId"] = "fb-best"
        board_store.put_content(self.table, live)
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=self.settings,
            persona_id="cmo",
            kind="task",
            actor="persona",
            seat_id="growth-specialist",
        )
        with patch.object(board_tools, "execute_call", return_value=board_tools.ToolOutcome(status="held", result={"status": "held"}, summary="boost")) as boost:
            perf = board_content.write_performance(self.table, self.settings)
        self.assertGreaterEqual(perf["updated"], 1)
        self.assertTrue(boost.called)

    def test_hold_classification(self) -> None:
        row = board_content.upsert_item(self.table, {"channel": "instagram", "copyEn": "x", "template": "news", "fields": {}})
        ctx = board_tools.ToolContext(table=self.table, settings=self.settings, persona_id="cmo", kind="task")
        action, key = board_holds.classify(
            board_tools.REGISTRY["content_publish"],
            ctx,
            {"contentId": row["contentId"]},
            self.settings,
        )
        self.assertEqual(action, "publish")
        self.assertEqual(key, "publish:instagram")

    def test_veto_hold_marks_content_vetoed(self) -> None:
        doc = board_content.upsert_item(
            self.table,
            {
                "channel": "facebook",
                "slotAt": "2026-09-20T02:00:00+00:00",
                "copyEn": "Veto me",
                "template": "news",
                "fields": {"title": "Veto"},
            },
        )
        doc = board_content.render_item(self.table, doc)
        scheduled = board_content.schedule_publish(self.table, self.settings, doc)
        hold_id = str(scheduled.get("holdId") or "")
        self.assertTrue(hold_id)
        with patch("board_budget.board_completion", side_effect=RuntimeError("no model")):
            board_holds.veto(self.table, hold_id, "owner", "not this one")
        latest = board_store.get_content(self.table, doc["contentId"])
        self.assertEqual(latest["status"], "vetoed")
        lessons = board_store.list_lessons(self.table)
        self.assertTrue(lessons)


if __name__ == "__main__":
    unittest.main()
