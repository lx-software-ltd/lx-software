#!/usr/bin/env python3
"""The API hostname record stays a DNS-only CNAME to the regional target."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "cloudflare" / "publish-api-domain.py"


def _load():
    spec = importlib.util.spec_from_file_location("publish_api_domain", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublishApiDomainTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load()

    def test_regional_target_accepts_the_gateway_hostname_only(self) -> None:
        target = "d-02n1z1wg6e.execute-api.ap-southeast-1.amazonaws.com"
        self.assertEqual(
            self.mod.regional_target({"DomainNameConfigurations": [{"ApiGatewayDomainName": target}]}),
            target,
        )
        with self.assertRaises(RuntimeError):
            self.mod.regional_target(
                {
                    "DomainNameConfigurations": [
                        {"ApiGatewayDomainName": "abcd1234.execute-api.ap-southeast-1.amazonaws.com"}
                    ]
                }
            )
        with self.assertRaises(RuntimeError):
            self.mod.regional_target({})

    def test_cloudflare_url_stays_on_the_api_host(self) -> None:
        self.assertEqual(
            self.mod.cloudflare_url("/zones/abc"),
            "https://api.cloudflare.com/client/v4/zones/abc",
        )
        for path in ("file:///etc/passwd", "//evil.example", "/zones/../etc", "https://evil.example"):
            with self.assertRaises(RuntimeError):
                self.mod.cloudflare_url(path)

    def test_cname_must_be_dns_only_and_exact(self) -> None:
        target = "d-abc.execute-api.ap-southeast-1.amazonaws.com"
        self.assertTrue(
            self.mod.cname_is_correct(
                {"type": "CNAME", "content": target, "proxied": False},
                target,
            )
        )
        self.assertFalse(
            self.mod.cname_is_correct(
                {"type": "CNAME", "content": target, "proxied": True},
                target,
            )
        )
        self.assertFalse(self.mod.cname_is_correct(None, target))
        record = self.mod.desired_cname(target)
        self.assertEqual(record["name"], "api.lx-software.com")
        self.assertFalse(record["proxied"])
        self.assertEqual(record["content"], target)


if __name__ == "__main__":
    unittest.main()
