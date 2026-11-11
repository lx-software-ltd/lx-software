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

    def test_redirect_must_be_a_permanent_redirect_that_keeps_the_query(self) -> None:
        payload = self.mod.apex_redirect_payload()
        self.assertTrue(self.mod.apex_redirect_is_correct(payload))
        dropped_query = {
            **payload,
            "action_parameters": {
                "from_value": {
                    **payload["action_parameters"]["from_value"],
                    "preserve_query_string": False,
                }
            },
        }
        temporary = {
            **payload,
            "action_parameters": {
                "from_value": {
                    **payload["action_parameters"]["from_value"],
                    "status_code": 302,
                }
            },
        }
        self.assertFalse(self.mod.apex_redirect_is_correct(dropped_query))
        self.assertFalse(self.mod.apex_redirect_is_correct(temporary))

    def test_live_probes_cover_a_query_string(self) -> None:
        queried = [href for href in self.mod.LIVE_PROBES if "?" in href]
        self.assertGreaterEqual(len(queried), 2)
        for href in self.mod.LIVE_PROBES:
            expected = self.mod.canonical_www_url(href)
            self.assertNotIn("*", expected)
            if "?" in href:
                self.assertIn("utm=gbp", expected)

    def test_custom_domain_leaves_mail_records_and_replaces_a_dummy_address(self) -> None:
        blocks = self.mod.apex_address_record_blocks_worker
        self.assertFalse(blocks({"name": "lx-software.com", "type": "MX", "content": "mx.example.com"}))
        self.assertFalse(blocks({"name": "lx-software.com", "type": "TXT", "content": "v=spf1"}))
        self.assertFalse(
            blocks(
                {
                    "name": "lx-software.com",
                    "type": "AAAA",
                    "content": "100::",
                    "meta": {"read_only": True},
                }
            )
        )
        self.assertTrue(blocks({"name": "lx-software.com", "type": "A", "content": "192.0.2.1"}))
        self.assertTrue(blocks({"name": "lx-software.com", "type": "CNAME", "content": "origin.example.net"}))
        self.assertFalse(blocks({"name": "www.lx-software.com", "type": "A", "content": "192.0.2.1"}))
        self.assertTrue(
            self.mod.custom_domain_is_correct(
                {"hostname": "lx-software.com", "service": "lx-software-apex-redirect", "enabled": True}
            )
        )
        self.assertFalse(
            self.mod.custom_domain_is_correct(
                {"hostname": "lx-software.com", "service": "other-worker", "enabled": True}
            )
        )
        self.assertFalse(self.mod.custom_domain_is_correct(None))


if __name__ == "__main__":
    unittest.main()
