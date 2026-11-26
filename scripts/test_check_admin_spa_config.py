"""The admin SPA config check reads a fake payload and skips when unset."""

from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

_PATH = Path(__file__).resolve().parent / "check_admin_spa_config.py"
_SPEC = importlib.util.spec_from_file_location("check_admin_spa_config", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
check = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = check
_SPEC.loader.exec_module(check)


class CheckAdminSpaConfigTest(unittest.TestCase):
    def test_unset_url_skips(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            code = check.main(environ={})
        self.assertEqual(code, 0)
        self.assertIn("skipped", out.getvalue())

    def test_custom_domain_passes(self) -> None:
        def fetch(_url: str) -> dict:
            return {"apiBaseUrl": "https://api.lx-software.com/"}

        out = io.StringIO()
        with redirect_stdout(out):
            code = check.main(
                environ={"ADMIN_SPA_CONFIG_URL": "https://cdn.example/config.json"},
                fetch=fetch,
            )
        self.assertEqual(code, 0)
        self.assertIn("https://api.lx-software.com", out.getvalue())

    def test_execute_api_base_fails(self) -> None:
        def fetch(_url: str) -> dict:
            return {"apiBaseUrl": "https://abc123.execute-api.ap-southeast-1.amazonaws.com"}

        err = io.StringIO()
        with redirect_stderr(err):
            code = check.main(
                environ={"ADMIN_SPA_CONFIG_URL": "https://cdn.example/config.json"},
                fetch=fetch,
            )
        self.assertEqual(code, 1)
        self.assertIn("execute-api", err.getvalue())
