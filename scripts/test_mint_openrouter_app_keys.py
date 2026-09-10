"""Tests for scripts/mint-openrouter-app-keys.py."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "mint-openrouter-app-keys.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("mint_openrouter_app_keys", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MintOpenRouterAppKeysTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()

    def test_plaintext_out_writes_keys_and_hides_them_from_stdout(self) -> None:
        created: list[str] = []

        def fake_request(method: str, token: str, *, body: dict | None = None) -> dict:
            self.assertEqual(token, "mgmt-test")
            if method == "GET":
                return {"data": []}
            self.assertEqual(method, "POST")
            name = str((body or {}).get("name"))
            created.append(name)
            # Official create response: plaintext is top-level `key`.
            return {
                "data": {"name": name, "hash": "unused"},
                "key": f"sk-test-{name.replace(':', '-')}",
            }

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "minted.txt"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch.object(self.mod, "_request", side_effect=fake_request),
                patch.dict(
                    os.environ,
                    {"OPENROUTER_MANAGEMENT_API_KEY": "mgmt-test"},
                    clear=False,
                ),
                patch("sys.argv", ["mint-openrouter-app-keys.py", "--plaintext-out", str(out)]),
                patch("sys.stdout", stdout),
                patch("sys.stderr", stderr),
            ):
                rc = self.mod.main()
            self.assertEqual(rc, 0)
            payload = out.read_text(encoding="utf-8")
            admin = json.loads(
                payload.split("# Sibling product secrets", 1)[0]
                .split("Do not commit these values.\n", 1)[1]
            )
            self.assertEqual(admin["statement-parser"], "sk-test-lxsoftware-statement-parser")
            self.assertEqual(admin["executive-board"], "sk-test-lxsoftware-executive-board")
            self.assertIn("sk-test-lxsoftware-evolvesprouts", payload)
            self.assertIn("sk-test-lxsoftware-siutindei", payload)
            self.assertNotIn("sk-test-", stdout.getvalue())
            self.assertIn("key material written to", stderr.getvalue())
            self.assertEqual(
                set(created),
                {
                    "lxsoftware:statement-parser",
                    "lxsoftware:executive-board",
                    "lxsoftware:evolvesprouts",
                    "lxsoftware:siutindei",
                },
            )

    def test_dry_run_skips_existing_names(self) -> None:
        def fake_request(method: str, token: str, *, body: dict | None = None) -> dict:
            del token, body
            self.assertEqual(method, "GET")
            return {
                "data": [
                    {"name": "lxsoftware:statement-parser"},
                    {"name": "lxsoftware:executive-board"},
                ]
            }

        stdout = io.StringIO()
        with (
            patch.object(self.mod, "_request", side_effect=fake_request),
            patch.dict(
                os.environ,
                {"OPENROUTER_MANAGEMENT_API_KEY": "mgmt-test"},
                clear=False,
            ),
            patch("sys.argv", ["mint-openrouter-app-keys.py", "--dry-run"]),
            patch("sys.stdout", stdout),
        ):
            rc = self.mod.main()
        self.assertEqual(rc, 0)
        text = stdout.getvalue()
        self.assertIn("skip statement-parser (lxsoftware:statement-parser) already exists", text)
        self.assertIn("would create lxsoftware:evolvesprouts", text)

    def test_missing_management_key_exits_2(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_MANAGEMENT_API_KEY"}
        stderr = io.StringIO()
        with (
            patch.dict(os.environ, env, clear=True),
            patch("sys.argv", ["mint-openrouter-app-keys.py"]),
            patch("sys.stderr", stderr),
        ):
            rc = self.mod.main()
        self.assertEqual(rc, 2)
        self.assertIn("OPENROUTER_MANAGEMENT_API_KEY", stderr.getvalue())

    def test_plaintext_from_create_response_prefers_top_level_key(self) -> None:
        self.assertEqual(
            self.mod.plaintext_from_create_response(
                {
                    "data": {"name": "lxsoftware:statement-parser", "hash": "abc"},
                    "key": "sk-test-top",
                }
            ),
            "sk-test-top",
        )

    def test_plaintext_from_create_response_falls_back_to_nested_key(self) -> None:
        self.assertEqual(
            self.mod.plaintext_from_create_response(
                {"data": {"key": "sk-test-nested"}}
            ),
            "sk-test-nested",
        )

    def test_plaintext_from_create_response_empty_when_only_metadata(self) -> None:
        self.assertEqual(
            self.mod.plaintext_from_create_response(
                {"data": {"name": "lxsoftware:statement-parser", "hash": "abc"}}
            ),
            "",
        )


if __name__ == "__main__":
    unittest.main()
