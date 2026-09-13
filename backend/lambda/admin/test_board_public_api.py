"""Scopes, redaction, and 60s notify coalesce for the public API key."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import board_public_api
import board_store
from test_board import BoardTestCase, FakeTable


class PathClassTests(unittest.TestCase):
    def test_finance_and_ops_and_full(self) -> None:
        self.assertEqual(board_public_api.path_class("/public/finance"), "finance")
        self.assertEqual(board_public_api.path_class("/public/siu-tin-dei/board"), "siutindei-board-ops")
        self.assertEqual(
            board_public_api.path_class("/public/siu-tin-dei/board/breakers"),
            "siutindei-board-ops",
        )
        self.assertEqual(
            board_public_api.path_class("/public/siu-tin-dei/board/mail"),
            "siutindei-board-full",
        )

    def test_full_scope_covers_ops(self) -> None:
        self.assertTrue(
            board_public_api.path_allowed(
                "/public/siu-tin-dei/board/staff", ["siutindei-board-full"]
            )
        )
        self.assertFalse(
            board_public_api.path_allowed("/public/siu-tin-dei/board/mail", ["siutindei-board-ops"])
        )
        self.assertFalse(board_public_api.path_allowed("/public/siu-tin-dei/board", ["finance"]))


class RedactAndNotifyTests(BoardTestCase):
    def test_overview_strips_allow_list_without_pii(self) -> None:
        settings = board_store.load_settings(self.table)
        settings["tools"]["allowList"] = ["owner@example.com"]
        settings["review"]["digestTo"] = "owner@example.com"
        board_store.save_settings(self.table, settings)
        response = {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "settings": {
                        "tools": {"allowList": ["owner@example.com"]},
                        "review": {"digestTo": "owner@example.com"},
                    }
                }
            ),
        }
        redacted = board_public_api.redact_board_response(
            "/public/siu-tin-dei/board", response, ["siutindei-board-ops"]
        )
        body = json.loads(redacted["body"])
        self.assertEqual(body["settings"]["tools"]["allowList"], [])
        self.assertEqual(body["settings"]["review"]["digestTo"], "")

    def test_creative_url_stripped_without_assets(self) -> None:
        response = {"statusCode": 200, "body": json.dumps({"url": "https://signed", "key": "k"})}
        redacted = board_public_api.redact_board_response(
            "/public/siu-tin-dei/board/content/abc/creative/0",
            response,
            ["siutindei-board-full"],
        )
        self.assertEqual(json.loads(redacted["body"]), {"key": "k"})

    def test_notify_coalesces_within_60s(self) -> None:
        settings = board_store.load_settings(self.table)
        settings["review"]["digestTo"] = "owner@example.com"
        board_store.save_settings(self.table, settings)
        sent: list[dict] = []

        def fake_send(table, plan, *, sent_by, index=True):
            sent.append(plan)
            return {"ok": True}

        event = {
            "requestContext": {
                "http": {"sourceIp": "203.0.113.9", "userAgent": "test"},
                "requestId": "req-n1",
            },
            "headers": {},
        }
        key_ctx = {"keyId": "k-n", "label": "n", "scopes": "finance"}
        with (
            patch("board_mail.sending_enabled", lambda: True),
            patch("board_mail.send_plan", fake_send),
        ):
            board_public_api.notify_key_use(event, key_ctx=key_ctx, path="/public/finance", method="GET")
            board_public_api.notify_key_use(event, key_ctx=key_ctx, path="/public/finance", method="GET")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["to"], ["owner@example.com"])
        self.assertEqual(sent[0]["fromMailbox"], "hello")

    def test_claim_slot_uses_fake_table_condition(self) -> None:
        table = FakeTable()
        now = datetime(2026, 9, 13, 4, 0, tzinfo=timezone.utc)
        self.assertTrue(
            board_public_api.try_claim_notify_slot(
                table, key_id="k1", path_cls="allowed:finance", source_ip="1.1.1.1", now=now
            )
        )
        self.assertFalse(
            board_public_api.try_claim_notify_slot(
                table, key_id="k1", path_cls="allowed:finance", source_ip="1.1.1.1", now=now
            )
        )
