"""Public API-key GET mirrors of /siu-tin-dei/board (scope B)."""

from __future__ import annotations

import json
import os
from typing import Any

from unittest.mock import patch

from dispatch import lambda_handler
from test_board import BoardTestCase
import board_async


class PublicBoardReadTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))

    def public_call(
        self, path: str, method: str = "GET", query: str = ""
    ) -> tuple[int, Any]:
        ev = self.event(path, method, query=query)
        ev["requestContext"]["authorizer"] = {
            "lambda": {
                "keyId": "k123",
                "label": "test",
                "scope": "read",
                "scopes": "finance,siutindei-board-ops,siutindei-board-full,siutindei-pii,siutindei-assets",
            }
        }
        out = lambda_handler(ev, None)
        return out["statusCode"], json.loads(out["body"])

    def test_overview_and_staff_surfaces(self) -> None:
        status, body = self.public_call("/public/siu-tin-dei/board")
        self.assertEqual(status, 200)
        self.assertIn("settings", body)
        self.assertIn("members", body)
        self.assertIn("usageToday", body)

        status, body = self.public_call("/public/siu-tin-dei/board/staff")
        self.assertEqual(status, 200)
        self.assertTrue(body.get("envEnabled"))
        self.assertIn("seats", body)

        status, body = self.public_call("/public/siu-tin-dei/board/tasks")
        self.assertEqual(status, 200)
        self.assertEqual(body["tasks"], [])

        status, body = self.public_call("/public/siu-tin-dei/board/breakers")
        self.assertEqual(status, 200)
        self.assertIn("breakers", body)

        status, body = self.public_call("/public/siu-tin-dei/board/review")
        self.assertEqual(status, 200)
        self.assertIn("review", body)

        status, body = self.public_call("/public/siu-tin-dei/board/holds")
        self.assertEqual(status, 200)
        self.assertIn("holds", body)

        status, body = self.public_call("/public/siu-tin-dei/board/tools")
        self.assertEqual(status, 200)
        self.assertIn("effective", body)

        status, body = self.public_call("/public/siu-tin-dei/board/tools/calls")
        self.assertEqual(status, 200)
        self.assertIn("calls", body)

    def test_owner_mail_and_meetings_are_readable(self) -> None:
        status, body = self.public_call("/public/siu-tin-dei/board/mail")
        self.assertEqual(status, 200)
        self.assertIn("threads", body)

        status, body = self.public_call("/public/siu-tin-dei/board/meetings")
        self.assertEqual(status, 200)
        self.assertIn("meetings", body)

        status, body = self.public_call("/public/siu-tin-dei/board/chat/ceo")
        self.assertEqual(status, 200)

    def test_write_paths_stay_closed(self) -> None:
        for path, method in (
            ("/public/siu-tin-dei/board/tasks", "POST"),
            ("/public/siu-tin-dei/board/breakers/tool:task/reset", "POST"),
            ("/public/siu-tin-dei/board/settings", "PUT"),
            ("/public/siu-tin-dei/board/charter", "PUT"),
        ):
            status, body = self.public_call(path, method)
            self.assertEqual(status, 404, msg=f"{method} {path}")
            self.assertEqual(body["message"], "Not found")

    def test_put_only_board_paths_are_not_gettable(self) -> None:
        for path in (
            "/public/siu-tin-dei/board/charter",
            "/public/siu-tin-dei/board/settings",
            "/public/siu-tin-dei/board/brief",
            "/public/siu-tin-dei/board/boundaries",
        ):
            status, _ = self.public_call(path)
            self.assertEqual(status, 404, msg=path)

    def test_api_key_cannot_use_jwt_board_path(self) -> None:
        status, _ = self.public_call("/siu-tin-dei/board")
        self.assertEqual(status, 401)

    def test_finance_only_key_cannot_read_board(self) -> None:
        ev = self.event("/public/siu-tin-dei/board/breakers")
        ev["requestContext"]["authorizer"] = {
            "lambda": {"keyId": "k-fin", "label": "fin", "scope": "read", "scopes": "finance"}
        }
        out = lambda_handler(ev, None)
        self.assertEqual(out["statusCode"], 404)

    def test_legacy_read_scope_is_finance_only(self) -> None:
        ev = self.event("/public/siu-tin-dei/board")
        ev["requestContext"]["authorizer"] = {
            "lambda": {"keyId": "k-legacy", "label": "old", "scope": "read"}
        }
        out = lambda_handler(ev, None)
        self.assertEqual(out["statusCode"], 404)
        ev = self.event("/public/finance")
        ev["requestContext"]["authorizer"] = {
            "lambda": {"keyId": "k-legacy", "label": "old", "scope": "read"}
        }
        out = lambda_handler(ev, None)
        self.assertEqual(out["statusCode"], 200)

    def test_public_records_still_hides_board_rows(self) -> None:
        import board_store

        table = board_store.records_table()
        board_store.save_settings(table, board_store.load_settings(table))
        status, body = self.public_call("/public/records")
        self.assertEqual(status, 200)
        pks = [str(item.get("pk") or "") for item in body["items"]]
        self.assertFalse(any(pk.startswith("BOARD#") for pk in pks))


class PublicBoardWriteTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        os.environ["PUBLIC_API_WRITES_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.addCleanup(lambda: os.environ.pop("PUBLIC_API_WRITES_ENABLED", None))
        import board_store

        table = board_store.records_table()
        settings = board_store.load_settings(table)
        settings["staff"]["enabled"] = True
        board_store.save_settings(table, settings)
        patcher = patch.object(board_async, "invoke_async", lambda payload, fallback=None: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def public_call(
        self,
        path: str,
        method: str = "GET",
        *,
        body: dict | None = None,
        write: str = "1",
        scopes: str = "finance,siutindei-board-ops,siutindei-board-full,siutindei-pii,siutindei-assets",
        key_id: str = "k123",
    ) -> tuple[int, Any]:
        ev = self.event(path, method, body=body)
        ev["requestContext"]["authorizer"] = {
            "lambda": {
                "keyId": key_id,
                "label": "test",
                "scope": "read",
                "scopes": scopes,
                "write": write,
            }
        }
        out = lambda_handler(ev, None)
        return out["statusCode"], json.loads(out["body"])

    def test_create_task_and_put_charter(self) -> None:
        status, body = self.public_call(
            "/public/siu-tin-dei/board/tasks",
            "POST",
            body={"assignee": "support", "brief": "Triage inbound"},
            scopes="siutindei-board-ops",
        )
        self.assertEqual(status, 201, msg=body)
        self.assertEqual(body["task"]["brief"], "Triage inbound")
        self.assertEqual(body["task"]["assignee"], "support")
        self.assertEqual(body["task"]["createdBy"], "apikey:k123")

        status, body = self.public_call(
            "/public/siu-tin-dei/board/charter",
            "PUT",
            body={"vision": "V", "mission": "M"},
            scopes="siutindei-board-full",
        )
        self.assertEqual(status, 200, msg=body)
        self.assertEqual(body["charter"]["vision"], "V")
        audit = [
            item
            for item in self.table.items.values()
            if str(item.get("pk") or "") == "USER#apikey:k123"
        ]
        self.assertTrue(any("BOARD_CHARTER_PUT" in str(item.get("sk") or "") for item in audit))
        self.assertTrue(any("BOARD_TASK_CREATE" in str(item.get("sk") or "") for item in audit))

    def test_put_prospect_needs_pii(self) -> None:
        import board_store

        board_store.put_prospect(
            self.table,
            {
                "prospectId": "p1",
                "name": "Cafe",
                "type": "restaurant",
                "stage": "discovered",
                "createdAt": "2026-09-01T00:00:00+00:00",
                "updatedAt": "2026-09-01T00:00:00+00:00",
            },
        )
        status, body = self.public_call(
            "/public/siu-tin-dei/board/prospects/p1",
            "PUT",
            body={"note": "from key"},
            scopes="siutindei-board-full",
        )
        self.assertEqual(status, 404, msg=body)
        status, body = self.public_call(
            "/public/siu-tin-dei/board/prospects/p1",
            "PUT",
            body={"note": "from key"},
            scopes="siutindei-board-full,siutindei-pii",
        )
        self.assertEqual(status, 200, msg=body)
        self.assertEqual(body["prospect"]["ownerNote"], "from key")

    def test_owner_ops_and_settings_tools_stay_closed(self) -> None:
        status, body = self.public_call(
            "/public/siu-tin-dei/board/approvals/a1/approve", "POST", body={"note": "ok"}
        )
        self.assertEqual(status, 404)
        status, body = self.public_call("/public/siu-tin-dei/board/code/promote", "POST", body={})
        self.assertEqual(status, 404)
        status, body = self.public_call(
            "/public/siu-tin-dei/board/ramp/mail_reply/promote", "POST", body={}
        )
        self.assertEqual(status, 404)
        status, body = self.public_call(
            "/public/siu-tin-dei/board/tools", "PUT", body={"globalMode": "act"}
        )
        self.assertEqual(status, 404)
        status, body = self.public_call(
            "/public/siu-tin-dei/board/settings",
            "PUT",
            body={"tools": {"globalMode": "act"}},
        )
        self.assertEqual(status, 400)
        self.assertIn("tools", body["message"])

    def test_kill_switch_and_missing_write_flag(self) -> None:
        status, _ = self.public_call(
            "/public/siu-tin-dei/board/tasks",
            "POST",
            body={"assignee": "support", "brief": "x"},
            write="0",
        )
        self.assertEqual(status, 404)
        os.environ["PUBLIC_API_WRITES_ENABLED"] = "false"
        status, _ = self.public_call(
            "/public/siu-tin-dei/board/charter",
            "PUT",
            body={"vision": "V", "mission": "M"},
        )
        self.assertEqual(status, 404)

    def test_finance_write_stays_closed(self) -> None:
        status, body = self.public_call("/public/finance", "PUT", body={})
        self.assertEqual(status, 404)
        self.assertEqual(body["message"], "Not found")
