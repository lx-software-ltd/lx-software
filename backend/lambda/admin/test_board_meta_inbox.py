"""Message inbox: webhook stays fast, the owner sees text, staff and keys see aliases."""

from __future__ import annotations

import json
import os
import time
import unittest
from typing import Any
from unittest.mock import patch

import board_meta
import board_meta_inbox
import board_meta_ingest
import board_meta_triage
import board_meta_whatsapp
import board_policy
import board_public_api
import board_routes
import board_staff
import board_store
import board_tools
import board_triage
from test_board import BoardTestCase
from test_board_t5 import MetaTestCase

NUMBER = "85291234567"


def _page_messages(count: int) -> dict[str, Any]:
    return {
        "object": "page",
        "entry": [
            {
                "id": "page-1",
                "messaging": [
                    {
                        "sender": {"id": f"psid-{i}"},
                        "recipient": {"id": "page-1"},
                        "timestamp": 1_700_000_000_000 + i,
                        "message": {"mid": f"m-{i}", "text": f"hello {i}"},
                    }
                    for i in range(count)
                ],
            }
        ],
    }


class IngestTests(MetaTestCase):
    def test_fifty_messages_return_before_any_follow_up(self) -> None:
        calls: list[dict[str, Any]] = []

        def capture(payload: dict[str, Any], *, fallback: Any) -> None:
            calls.append(payload)

        started = time.monotonic()
        with patch("board_async.invoke_async", side_effect=capture):
            out = board_meta.ingest_webhook(self.table, _page_messages(50))
        elapsed = time.monotonic() - started
        self.assertEqual(set(out), {"stored", "duplicates"})
        self.assertEqual(out, {"stored": 50, "duplicates": 0})
        self.assertLess(elapsed, 2.0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["internal"], "board_meta_after_ingest")
        self.assertEqual(len(calls[0]["items"]), 50)

    def test_history_decline_is_recorded_and_stores_nothing(self) -> None:
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "waba-1",
                    "changes": [{"field": "history", "value": {"errors": [{"code": 2593109}]}}],
                }
            ],
        }
        out = board_meta_ingest.ingest_webhook(self.table, payload)
        self.assertEqual(out, {"stored": 0, "duplicates": 0})
        cached = board_store.get_cache(self.table, "meta:wa-history") or {}
        self.assertTrue((cached.get("payload") or {}).get("declined"))

    def test_owner_sees_the_number_and_staff_see_an_alias(self) -> None:
        with patch.object(board_meta_ingest, "follow_up", lambda items: None):
            board_meta.ingest_webhook(
                self.table,
                {
                    "object": "whatsapp_business_account",
                    "entry": [
                        {
                            "id": "waba-1",
                            "changes": [
                                {
                                    "field": "messages",
                                    "value": {
                                        "messages": [
                                            {
                                                "from": NUMBER,
                                                "id": "wamid.1",
                                                "timestamp": "1700000000",
                                                "type": "text",
                                                "text": {"body": "Saturday at the pitch, call 9123 4567"},
                                            }
                                        ]
                                    },
                                }
                            ],
                        }
                    ],
                },
            )
        owner = board_meta_inbox.list_for_owner(self.table)
        self.assertIn("9123", owner["threads"][0]["lastText"])
        ctx = board_tools.ToolContext(table=self.table, settings=board_store.load_settings(self.table), persona_id="coo", actor="persona")
        staff = board_meta_inbox.op_list_threads(ctx, {})
        self.assertNotIn("9123", staff["threads"][0]["lastText"])
        detail = board_meta_inbox.op_get_thread(ctx, {"threadId": owner["threads"][0]["threadId"]})
        self.assertNotIn("9123", detail["messages"][0]["text"])
        self.assertEqual(detail["messages"][0]["direction"], "in")


class RouteTests(BoardTestCase):
    def test_owner_routes_list_and_mark_read(self) -> None:
        with patch.object(board_meta_ingest, "follow_up", lambda items: None):
            board_meta.ingest_webhook(
                self.table,
                {
                    "object": "page",
                    "entry": [
                        {
                            "id": "page-1",
                            "messaging": [
                                {
                                    "sender": {"id": "psid-9"},
                                    "recipient": {"id": "page-1"},
                                    "timestamp": 1_700_000_000_000,
                                    "message": {"mid": "m-9", "text": "see you Saturday"},
                                }
                            ],
                        }
                    ],
                },
            )
        status, body = self._board("GET", "/siu-tin-dei/board/messages")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 1)
        self.assertIn("Saturday", body["threads"][0]["lastText"])
        thread_id = body["threads"][0]["threadId"]
        status, body = self._board("GET", f"/siu-tin-dei/board/messages/{thread_id}")
        self.assertEqual(body["messages"][0]["text"], "see you Saturday")
        status, body = self._board("POST", f"/siu-tin-dei/board/messages/{thread_id}/read", {})
        self.assertFalse(body["thread"]["unread"])

    def test_key_without_pii_is_masked_and_media_is_refused(self) -> None:
        raw = {"threads": [{"displayName": "Ada", "phone": "85291234567", "lastText": "call 9123 4567", "lastTextMasked": "call 9123 4567"}]}
        response = {"statusCode": 200, "body": json.dumps(raw)}
        masked = board_public_api.redact_board_response(
            "/public/siu-tin-dei/board/messages", response, ["siutindei-board-full"]
        )
        shown = json.loads(masked["body"])["threads"][0]
        self.assertNotIn("91234567", shown["phone"])
        self.assertNotIn("91234567", shown["lastText"])
        refused = board_public_api.redact_board_response(
            "/public/siu-tin-dei/board/messages/thread-1/media/0",
            {"statusCode": 200, "body": json.dumps({"url": "https://example.com/photo"})},
            ["siutindei-board-full"],
        )
        self.assertEqual(refused["statusCode"], 403)
        self.assertTrue(board_public_api.write_blocked("POST", "/public/siu-tin-dei/board/messages/whatsapp/connect"))
        self.assertTrue(board_public_api.write_blocked("POST", "/public/siu-tin-dei/board/messages/whatsapp/sync"))
        self.assertTrue(board_public_api.write_blocked("POST", "/public/siu-tin-dei/board/messages/connect/page"))

    def _board(self, method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
        out = board_routes.handle_board_route(self.event(path, method, body), method, path, "owner")
        assert out is not None
        return out["statusCode"], json.loads(out["body"])


class WhatsAppLinkTests(unittest.TestCase):
    def test_the_tap_to_send_link_carries_the_number_and_the_text(self) -> None:
        link = board_meta_whatsapp.phone_link("+852 9123 4567", "Saturday 9am")
        self.assertEqual(link, "https://wa.me/85291234567?text=Saturday%209am")
        self.assertEqual(board_meta_whatsapp.phone_link("", "x"), "")


class OrganisationThreadTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        # In-memory blobs, and the seat does not start on the task: no call leaves the test.
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        runner = patch.object(board_staff, "run_step", lambda payload: None)
        runner.start()
        self.addCleanup(runner.stop)
        settings = board_store.load_settings(self.table)
        settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True})
        self.settings = board_store.save_settings(self.table, settings)
        board_store.save_staff_override(self.table, "content-marketer", {"isActive": True})

    def test_a_known_organisation_gets_a_catalog_task_and_no_automatic_reply(self) -> None:
        board_store.put_prospect(
            self.table,
            {"prospectId": "org-1", "name": "Harbour Club", "type": "provider", "stage": "contacted", "phone": f"+{NUMBER}"},
        )
        with patch.object(board_store, "records_table", return_value=self.table):
            board_meta.ingest_webhook(
                self.table,
                {
                    "object": "whatsapp_business_account",
                    "entry": [
                        {
                            "id": "waba-1",
                            "changes": [
                                {
                                    "field": "messages",
                                    "value": {
                                        "messages": [
                                            {
                                                "from": NUMBER,
                                                "id": "wamid.org",
                                                "timestamp": "1700000001",
                                                "type": "text",
                                                "text": {"body": "Saturday 9am at the court"},
                                            }
                                        ]
                                    },
                                }
                            ],
                        }
                    ],
                },
            )
        tasks = [task for status in board_triage.OPEN_TASK_STATUSES for task in board_store.list_tasks(self.table, status)]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["assignee"], "content-marketer")
        self.assertIn("Harbour Club", tasks[0]["brief"])
        self.assertEqual(board_store.list_approvals(self.table), [])
        thread = board_store.list_meta_threads(self.table)[0]
        self.assertEqual(thread["prospectId"], "org-1")
        ctx = board_tools.ToolContext(table=self.table, settings=self.settings, persona_id="coo", actor="persona")
        reason = board_policy.check_reply(
            self.settings,
            ctx,
            board_tools.REGISTRY["meta_reply_whatsapp"],
            {"threadId": thread["threadId"], "message": "Thanks", "reason": "reply"},
            thread,
        )
        self.assertIn("owner", reason or "")
        again = board_meta_triage.on_message(self.table, self.settings, thread, {"direction": "in", "text": "again", "channel": "whatsapp"})
        self.assertEqual(again["taskId"], tasks[0]["taskId"])


if __name__ == "__main__":
    unittest.main()
