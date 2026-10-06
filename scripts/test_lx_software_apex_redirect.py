#!/usr/bin/env python3
"""Unit tests for the apex → www redirect helper (no network)."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "cloudflare" / "publish-apex-redirect.py"
WORKER = Path(__file__).resolve().parent / "cloudflare" / "lx-software-apex-redirect.js"


def _load_module():
    spec = importlib.util.spec_from_file_location("publish_apex_redirect", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ApexRedirectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()

    def test_keeps_path_and_query(self) -> None:
        self.assertEqual(
            self.mod.canonical_www_url("https://lx-software.com/about?utm=gbp"),
            "https://www.lx-software.com/about?utm=gbp",
        )

    def test_http_root_becomes_https_www(self) -> None:
        self.assertEqual(
            self.mod.canonical_www_url("http://lx-software.com/"),
            "https://www.lx-software.com/",
        )

    def test_does_not_emit_a_literal_star(self) -> None:
        self.assertNotIn("*", self.mod.canonical_www_url("https://lx-software.com/about"))

    def test_worker_source_uses_the_same_host(self) -> None:
        source = WORKER.read_text()
        self.assertIn(self.mod.CANONICAL_HOST, source)
        self.assertIn("301", source)
        self.assertNotIn("www.lx-software.com/*", source)

    def test_single_redirect_keeps_path_and_rejects_a_literal_star(self) -> None:
        payload = self.mod.apex_redirect_payload()
        self.assertTrue(self.mod.apex_redirect_is_correct(payload))
        self.assertNotIn("*", self.mod.APEX_TARGET_EXPRESSION)
        broken = {
            "enabled": True,
            "expression": self.mod.LEGACY_APEX_REDIRECT_EXPRESSION,
            "action": "redirect",
            "action_parameters": {
                "from_value": {
                    "preserve_query_string": True,
                    "status_code": 301,
                    "target_url": {"expression": self.mod.LITERAL_STAR_TARGET_EXPRESSION},
                }
            },
        }
        self.assertTrue(self.mod.is_apex_redirect_rule(broken))
        self.assertTrue(self.mod.is_literal_star_www_redirect(broken))
        self.assertFalse(self.mod.apex_redirect_is_correct(broken))
        lookalike = {
            "enabled": True,
            "expression": '(http.host eq "evil-lx-software.com")',
            "action": "redirect",
            "action_parameters": {
                "from_value": {
                    "target_url": {
                        "expression": 'concat("https://evil.example", http.request.uri.path)'
                    }
                }
            },
        }
        self.assertFalse(self.mod.is_apex_redirect_rule(lookalike))


if __name__ == "__main__":
    unittest.main()
