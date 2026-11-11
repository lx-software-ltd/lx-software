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

    def test_attach_refusal_is_only_http_409(self) -> None:
        self.assertTrue(self.mod.attach_was_refused(RuntimeError(
            "Cloudflare PUT /accounts/acct/workers/domains failed: 409 conflict"
        )))
        self.assertFalse(self.mod.attach_was_refused(RuntimeError(
            'Cloudflare PUT /accounts/acct/workers/domains failed: 400 {"code":409}'
        )))
        self.assertFalse(self.mod.attach_was_refused(RuntimeError(
            "Cloudflare PUT /accounts/acct/workers/domains failed: 403"
        )))

    def _fake_cf(self, calls: list[tuple[str, str]], *, refuse_first_put: bool):
        def fake(method, path, token, payload=None, **kwargs):
            calls.append((method, path))
            if method == "GET" and "workers/domains" in path:
                return {
                    "result": [{
                        "id": "dom1",
                        "hostname": "lx-software.com",
                        "service": "other-worker",
                        "enabled": True,
                    }]
                }
            if method == "GET" and "dns_records" in path:
                return {
                    "result": [{
                        "id": "rec1",
                        "name": "lx-software.com",
                        "type": "A",
                        "content": "192.0.2.1",
                    }]
                }
            puts = sum(1 for item, _path in calls if item == "PUT")
            if method == "PUT" and refuse_first_put and puts == 1:
                raise RuntimeError(
                    "Cloudflare PUT /accounts/acct/workers/domains failed: 409 conflict"
                )
            return {"result": {}}

        return fake

    def test_custom_domain_attach_is_tried_before_any_delete(self) -> None:
        calls: list[tuple[str, str]] = []
        self.mod._cf_request = self._fake_cf(calls, refuse_first_put=True)
        self.assertEqual(self.mod.ensure_custom_domain("t", "acct", "zone"), "replaced")
        put_at = next(i for i, (method, _path) in enumerate(calls) if method == "PUT")
        delete_at = next(i for i, (method, _path) in enumerate(calls) if method == "DELETE")
        self.assertLess(put_at, delete_at)
        self.assertEqual(sum(1 for method, _path in calls if method == "PUT"), 2)
        self.assertEqual(sum(1 for method, _path in calls if method == "DELETE"), 2)

    def test_accepted_attach_does_not_delete_the_existing_domain(self) -> None:
        calls: list[tuple[str, str]] = []
        self.mod._cf_request = self._fake_cf(calls, refuse_first_put=False)
        self.assertEqual(self.mod.ensure_custom_domain("t", "acct", "zone"), "replaced")
        self.assertFalse(any(method == "DELETE" for method, _path in calls))
        self.assertEqual(sum(1 for method, _path in calls if method == "PUT"), 1)

    def test_a_non_conflict_attach_error_is_not_followed_by_a_delete(self) -> None:
        calls: list[tuple[str, str]] = []

        def fake(method, path, token, payload=None, **kwargs):
            calls.append((method, path))
            if method == "GET":
                return {"result": []}
            raise RuntimeError("Cloudflare PUT /accounts/acct/workers/domains failed: 403")

        self.mod._cf_request = fake
        with self.assertRaises(RuntimeError):
            self.mod.ensure_custom_domain("t", "acct", "zone")
        self.assertFalse(any(method == "DELETE" for method, _path in calls))


if __name__ == "__main__":
    unittest.main()
