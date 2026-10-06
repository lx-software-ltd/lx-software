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


if __name__ == "__main__":
    unittest.main()
