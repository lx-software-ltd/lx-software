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

    def test_write_allowed_matrix(self) -> None:
        write_ctx = {"keyId": "k-w", "write": "1"}
        read_ctx = {"keyId": "k-r", "write": "0"}
        ops = ["siutindei-board-ops"]
        full = ["siutindei-board-full"]
        full_pii = ["siutindei-board-full", "siutindei-pii"]
        with patch.dict("os.environ", {"PUBLIC_API_WRITES_ENABLED": "true"}):
            self.assertIsNone(
                board_public_api.write_deny_reason(
                    "POST", "/public/siu-tin-dei/board/tasks", write_ctx, ops
                )
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "POST", "/public/siu-tin-dei/board/tasks", read_ctx, ops
                ),
                "key_read_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "PUT", "/public/siu-tin-dei/board/charter", write_ctx, ops
                ),
                "scope",
            )
            self.assertTrue(
                board_public_api.write_allowed(
                    "PUT", "/public/siu-tin-dei/board/charter", write_ctx, full
                )
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "POST",
                    "/public/siu-tin-dei/board/approvals/a1/approve",
                    write_ctx,
                    full,
                ),
                "owner_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "POST", "/public/siu-tin-dei/board/code/promote", write_ctx, full
                ),
                "owner_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "POST", "/public/siu-tin-dei/board/code/sync-staging", write_ctx, full
                ),
                "owner_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "POST", "/public/siu-tin-dei/board/catalog/preview", write_ctx, full
                ),
                "owner_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "POST", "/public/siu-tin-dei/board/catalog/import", write_ctx, full
                ),
                "owner_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "POST",
                    "/public/siu-tin-dei/board/ramp/mail_reply/promote",
                    write_ctx,
                    ops,
                ),
                "owner_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "POST",
                    "/public/siu-tin-dei/board/ramp/mail_reply/pause",
                    write_ctx,
                    ops,
                ),
                "owner_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "PUT", "/public/siu-tin-dei/board/tools", write_ctx, ops
                ),
                "owner_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "PUT",
                    "/public/siu-tin-dei/board/settings",
                    write_ctx,
                    full,
                ),
                "owner_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "PUT",
                    "/public/siu-tin-dei/board/boundaries",
                    write_ctx,
                    full,
                ),
                "owner_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "POST", "/public/siu-tin-dei/board/staff/tick", write_ctx, ops
                ),
                "owner_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "DELETE", "/public/siu-tin-dei/board/chat/ceo", write_ctx, full
                ),
                "owner_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "POST",
                    "/public/siu-tin-dei/board/meetings/m1/cancel",
                    write_ctx,
                    full,
                ),
                "owner_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "POST",
                    "/public/siu-tin-dei/board/tasks/t1/cancel",
                    write_ctx,
                    ops,
                ),
                "owner_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "POST", "/public/siu-tin-dei/board/mail/selftest", write_ctx, full
                ),
                "owner_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "PUT", "/public/finance", write_ctx, ["finance"]
                ),
                "finance_read_only",
            )
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "PUT",
                    "/public/siu-tin-dei/board/prospects/p1",
                    write_ctx,
                    full,
                ),
                "scope",
            )
            self.assertTrue(
                board_public_api.write_allowed(
                    "PUT",
                    "/public/siu-tin-dei/board/prospects/p1",
                    write_ctx,
                    full_pii,
                )
            )
            self.assertFalse(
                board_public_api.key_context_allows_write({"allowWrite": True})
            )
            self.assertTrue(board_public_api.key_context_allows_write({"write": "1"}))
        with patch.dict("os.environ", {"PUBLIC_API_WRITES_ENABLED": "false"}):
            self.assertEqual(
                board_public_api.write_deny_reason(
                    "POST", "/public/siu-tin-dei/board/tasks", write_ctx, ops
                ),
                "writes_disabled",
            )

    def test_contact_heavy_heads_need_pii_on_top_of_full(self) -> None:
        for path in (
            "/public/siu-tin-dei/board/prospects",
            "/public/siu-tin-dei/board/outreach/stats",
            "/public/siu-tin-dei/board/outreach/identity",
            "/public/siu-tin-dei/board/receivables",
        ):
            self.assertFalse(board_public_api.path_allowed(path, ["siutindei-board-full"]))
            self.assertFalse(board_public_api.path_allowed(path, ["siutindei-pii"]))
            self.assertTrue(
                board_public_api.path_allowed(path, ["siutindei-board-full", "siutindei-pii"])
            )
        self.assertTrue(
            board_public_api.path_allowed("/public/siu-tin-dei/board/mail", ["siutindei-board-full"])
        )


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

    def test_settings_put_response_strips_allow_list_without_pii(self) -> None:
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
            "/public/siu-tin-dei/board/settings", response, ["siutindei-board-full"]
        )
        body = json.loads(redacted["body"])
        self.assertEqual(body["settings"]["tools"]["allowList"], [])
        self.assertEqual(body["settings"]["review"]["digestTo"], "")

    def test_tools_config_allow_list_stripped_without_pii(self) -> None:
        response = {
            "statusCode": 200,
            "body": json.dumps({"config": {"allowList": ["owner@example.com", "+85291234567"]}}),
        }
        redacted = board_public_api.redact_board_response(
            "/public/siu-tin-dei/board/tools", response, ["siutindei-board-ops"]
        )
        self.assertEqual(json.loads(redacted["body"])["config"]["allowList"], [])
        kept = board_public_api.redact_board_response(
            "/public/siu-tin-dei/board/tools",
            response,
            ["siutindei-board-ops", "siutindei-pii"],
        )
        self.assertEqual(
            json.loads(kept["body"])["config"]["allowList"],
            ["owner@example.com", "+85291234567"],
        )

    def test_write_notify_does_not_coalesce(self) -> None:
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
                "requestId": "req-w1",
            },
            "headers": {},
        }
        key_ctx = {
            "keyId": "k-w",
            "label": "w",
            "scopes": "siutindei-board-ops",
            "write": "1",
        }
        with (
            patch("board_mail.sending_enabled", lambda: True),
            patch("board_mail.send_plan", fake_send),
        ):
            board_public_api.notify_key_use(
                event,
                key_ctx=key_ctx,
                path="/public/siu-tin-dei/board/tasks",
                method="POST",
                kind="write",
            )
            board_public_api.notify_key_use(
                event,
                key_ctx=key_ctx,
                path="/public/siu-tin-dei/board/tasks",
                method="POST",
                kind="write",
            )
        self.assertEqual(len(sent), 2)

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

    def test_denied_notify_keeps_empty_method(self) -> None:
        settings = board_store.load_settings(self.table)
        settings["review"]["digestTo"] = "owner@example.com"
        board_store.save_settings(self.table, settings)
        sent: list[dict] = []

        def fake_send(table, plan, *, sent_by, index=True):
            sent.append(plan)
            return {"ok": True}

        with (
            patch("board_mail.sending_enabled", lambda: True),
            patch("board_mail.send_plan", fake_send),
        ):
            board_public_api.handle_internal_notify(
                {
                    "keyId": "k-deny",
                    "label": "d",
                    "scopes": ["finance"],
                    "kind": "denied",
                    "reason": "revoked",
                    "sourceIp": "203.0.113.9",
                    "path": "",
                    "pathClass": "denied",
                    "method": "",
                    "requestContext": {
                        "requestId": "req-d1",
                        "http": {"sourceIp": "203.0.113.9"},
                    },
                }
            )
        self.assertEqual(len(sent), 1)
        self.assertIn("method: \n", sent[0]["text"])
        self.assertNotIn("method: GET", sent[0]["text"])

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
        row = table.get_item(
            Key={
                "pk": f"BOARD#{board_public_api.BOARD_KEY}#publicapi#notify",
                "sk": "k1#allowed:finance#1.1.1.1",
            }
        )["Item"]
        self.assertEqual(row["expiresAt"], int(now.timestamp()) + 86400)
