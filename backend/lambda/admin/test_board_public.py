"""Public API-key GET mirrors of /siu-tin-dei/board (scope B)."""

from __future__ import annotations

import json
import os
from typing import Any

from dispatch import lambda_handler
from test_board import BoardTestCase


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
