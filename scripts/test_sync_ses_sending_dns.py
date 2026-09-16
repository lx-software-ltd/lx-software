#!/usr/bin/env python3
"""Unit tests for SES → Cloudflare DKIM record mapping (no network)."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "sync-ses-sending-dns.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("sync_ses_sending_dns", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SyncSesSendingDnsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()

    def test_dkim_records_from_tokens(self) -> None:
        ident = {"DkimAttributes": {"Status": "FAILED", "Tokens": ["abc", "def", ""]}}
        rows = self.mod.dkim_records(ident, "partners.siutindei.com")
        self.assertEqual(
            [(r["name"], r["content"]) for r in rows],
            [
                (
                    "abc._domainkey.partners.siutindei.com",
                    "abc.dkim.amazonses.com",
                ),
                (
                    "def._domainkey.partners.siutindei.com",
                    "def.dkim.amazonses.com",
                ),
            ],
        )

    def test_mail_from_mx_and_spf(self) -> None:
        ident = {"MailFromAttributes": {"MailFromDomain": "mail.partners.siutindei.com"}}
        rows = self.mod.mail_from_records(ident, "partners.siutindei.com", "ap-southeast-1")
        self.assertEqual(rows[0]["type"], "MX")
        self.assertEqual(rows[0]["content"], "feedback-smtp.ap-southeast-1.amazonses.com")
        self.assertEqual(rows[0]["priority"], 10)
        self.assertEqual(rows[1]["content"], "v=spf1 include:amazonses.com ~all")

    def test_desired_records_combine(self) -> None:
        ident = {
            "DkimAttributes": {"Tokens": ["tok1"]},
            "MailFromAttributes": {"MailFromDomain": "mail.example.com"},
        }
        rows = self.mod.desired_records(ident, "example.com", "ap-southeast-1")
        self.assertEqual([r["type"] for r in rows], ["CNAME", "MX", "TXT"])


if __name__ == "__main__":
    unittest.main()
