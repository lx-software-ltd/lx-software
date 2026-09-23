"""DMARC aggregate parsing and the daily evaluator."""

from __future__ import annotations

import gzip
import io
import time
import zipfile
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any
from unittest.mock import patch

import board_dmarc
import board_duties
import board_mail
import board_review
import board_staff
import board_store
from test_board import BoardTestCase
from test_board_mail import build_mail


def _xml(
    *,
    org: str = "google.com",
    report_id: str = "8293631891377217499",
    source_ip: str = "203.0.113.9",
    count: int = 14,
    dkim: str = "fail",
    spf: str = "fail",
    disposition: str = "none",
    dkim_domain: str = "evil.example",
    spf_domain: str = "evil.example",
    header_from: str = "siutindei.com",
    policy_domain: str = "siutindei.com",
    p: str = "quarantine",
    sp: str = "",
    pct: int = 100,
    begin: int = 0,
    end: int = 0,
) -> bytes:
    now = int(datetime.now(timezone.utc).timestamp())
    begin = begin or now - 86400
    end = end or now - 3600
    sp_xml = f"<sp>{sp}</sp>" if sp else ""
    body = f"""<?xml version="1.0" encoding="UTF-8" ?>
<feedback>
  <report_metadata>
    <org_name>{org}</org_name>
    <email>noreply-dmarc-support@google.com</email>
    <report_id>{report_id}</report_id>
    <date_range><begin>{begin}</begin><end>{end}</end></date_range>
  </report_metadata>
  <policy_published>
    <domain>{policy_domain}</domain>
    <adkim>r</adkim>
    <aspf>r</aspf>
    <p>{p}</p>
    {sp_xml}
    <pct>{pct}</pct>
  </policy_published>
  <record>
    <row>
      <source_ip>{source_ip}</source_ip>
      <count>{count}</count>
      <policy_evaluated>
        <disposition>{disposition}</disposition>
        <dkim>{dkim}</dkim>
        <spf>{spf}</spf>
      </policy_evaluated>
    </row>
    <identifiers><header_from>{header_from}</header_from></identifiers>
    <auth_results>
      <dkim><domain>{dkim_domain}</domain><selector>s1</selector><result>{dkim}</result></dkim>
      <spf><domain>{spf_domain}</domain><result>{spf}</result></spf>
    </auth_results>
  </record>
</feedback>
"""
    return body.encode()


def _message_with(name: str, ctype: str, payload: bytes, *, subject: str | None = None) -> EmailMessage:
    raw = build_mail(
        frm="Google <noreply-dmarc-support@google.com>",
        to="dmarc@siutindei.com",
        subject=subject or "Report domain: siutindei.com Submitter: google.com Report-ID: 1",
        text="",
        message_id=f"<{name}@google.com>",
        attachments=[(name, ctype, payload)],
    )
    from email import policy
    from email.parser import BytesParser

    return BytesParser(policy=policy.default).parsebytes(raw)


class DmarcParseTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.blobs: dict[str, bytes] = {}

        def _put(key: str, body: bytes) -> None:
            self.blobs[key] = body

        patcher = patch.object(board_staff, "_blob_put", side_effect=_put)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_google_zip_and_yahoo_gzip_parse(self) -> None:
        xml = _xml(report_id="google-1", count=10, dkim="pass", spf="pass", dkim_domain="amazonses.com", spf_domain="siutindei.com")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("google.com!siutindei.com!google-1.xml", xml)
        google = _message_with("google.com!siutindei.com!google-1.zip", "application/zip", buf.getvalue())
        out = board_dmarc.ingest_message(self.table, google, thread_id="thr-g")
        self.assertEqual(out["reports"], 1)
        self.assertFalse(out["forensic"])

        yahoo_xml = _xml(org="Yahoo", report_id="yahoo-1", count=2, dkim="pass", spf="pass", dkim_domain="amazonses.com", spf_domain="amazonses.com")
        yahoo = _message_with("yahoo.xml.gz", "application/gzip", gzip.compress(yahoo_xml))
        out = board_dmarc.ingest_message(self.table, yahoo, thread_id="thr-y")
        self.assertEqual(out["reports"], 1)
        reports = board_dmarc.list_reports(self.table)
        self.assertEqual(len(reports), 2)
        google_row = next(row for row in reports if row["reportId"] == "google-1")
        self.assertEqual(google_row["messageCount"], 10)
        self.assertEqual(google_row["alignedCount"], 10)
        self.assertEqual(google_row["sources"][0]["sourceIp"], "203.0.113.9")
        self.assertTrue(google_row["rawKey"].endswith(".xml.gz"))
        stored = gzip.decompress(self.blobs[google_row["rawKey"]])
        self.assertIn(b"<report_id>google-1</report_id>", stored)

    def test_plain_xml_and_duplicate_report_id(self) -> None:
        msg = _message_with("report.xml", "application/xml", _xml(report_id="plain-1"))
        first = board_dmarc.ingest_message(self.table, msg, thread_id="thr-1")
        again = board_dmarc.ingest_message(self.table, msg, thread_id="thr-1")
        self.assertEqual(first["reports"], 1)
        self.assertEqual(again["duplicates"], 1)
        self.assertEqual(len(board_dmarc.list_reports(self.table)), 1)

    def test_malformed_xml_and_doctype_are_rejected(self) -> None:
        broken = _message_with("bad.xml", "application/xml", b"<feedback><report_metadata>")
        out = board_dmarc.ingest_message(self.table, broken, thread_id="thr-bad")
        self.assertEqual(out["errors"], 1)
        self.assertEqual(out["reports"], 0)
        self.assertFalse(out["forensic"])
        dtd = b"""<?xml version="1.0"?>
<!DOCTYPE feedback [<!ENTITY x "boom">]>
<feedback><report_metadata><report_id>x</report_id></report_metadata></feedback>
"""
        out = board_dmarc.ingest_message(self.table, _message_with("dtd.xml", "text/xml", dtd), thread_id="thr-dtd")
        self.assertEqual(out["errors"], 1)
        self.assertEqual(board_dmarc.list_reports(self.table), [])

    def test_oversized_payload_is_rejected(self) -> None:
        xml = _xml(report_id="big")
        with patch.object(board_dmarc, "MAX_XML_BYTES", 80):
            out = board_dmarc.ingest_message(
                self.table,
                _message_with("big.xml", "application/xml", xml),
                thread_id="thr-big",
            )
        self.assertEqual(out["errors"], 1)
        self.assertEqual(out["reports"], 0)

    def test_deadline_skips_parsing(self) -> None:
        out = board_dmarc.ingest_message(
            self.table,
            _message_with("report.xml", "application/xml", _xml()),
            thread_id="thr-late",
            deadline=time.monotonic() - 1,
        )
        self.assertEqual(out.get("skipped"), "deadline")
        self.assertEqual(board_dmarc.list_reports(self.table), [])

    def test_forensic_report_is_counted_without_a_body(self) -> None:
        raw = build_mail(
            frm="Google <noreply-dmarc-support@google.com>",
            to="dmarc@siutindei.com",
            subject="Report domain: siutindei.com Submitter: google.com Report-ID: forensic",
            text="A feedback report with no aggregate XML.",
            message_id="<forensic@google.com>",
        )
        from email import policy
        from email.parser import BytesParser

        msg = BytesParser(policy=policy.default).parsebytes(raw)
        out = board_dmarc.ingest_message(self.table, msg, thread_id="thr-f")
        self.assertTrue(out["forensic"])
        self.assertEqual(out["reports"], 0)
        meta = board_store._get_state(self.table, "dmarc#meta") or {}  # noqa: SLF001
        self.assertEqual(meta.get("forensicCount"), 1)
        self.assertNotIn("text", meta)

    def test_ingest_bytes_records_report_ids_on_the_thread(self) -> None:
        xml = _xml(report_id="via-mail", count=3, dkim="pass", spf="pass", dkim_domain="amazonses.com", spf_domain="amazonses.com")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("report.xml", xml)
        result = board_mail.ingest_bytes(
            self.table,
            build_mail(
                frm="Google <noreply-dmarc-support@google.com>",
                to="dmarc@siutindei.com",
                subject="Report domain: siutindei.com Submitter: google.com Report-ID: via-mail",
                text="",
                message_id="<via-mail@google.com>",
                attachments=[("report.zip", "application/zip", buf.getvalue())],
            ),
        )
        thread = board_store.get_mail_thread(self.table, result["threadId"])
        self.assertEqual(thread["disposition"], "archived")
        self.assertFalse(thread["unread"])
        self.assertEqual(thread["dmarcReportIds"], ["google.com:via-mail"])
        self.assertEqual(thread["dmarcRecordCount"], 1)

    def test_failed_report_write_drops_the_raw_blob(self) -> None:
        deleted: list[str] = []
        real_put = self.table.put_item

        def _put(Item: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            if str(Item.get("sk", "")).startswith("REPORT#"):
                raise RuntimeError("ddb down")
            return real_put(Item=Item, **kwargs)

        self.table.put_item = _put  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(self.table, "put_item", real_put))
        with patch.object(board_staff, "_blob_delete", side_effect=lambda key: deleted.append(key)):
            out = board_dmarc.ingest_message(
                self.table,
                _message_with("lost.xml", "application/xml", _xml(report_id="lost")),
                thread_id="thr-lost",
            )
        self.assertEqual(out["errors"], 1)
        self.assertEqual(out["reports"], 0)
        self.assertEqual(len(deleted), 1)
        self.assertTrue(deleted[0].endswith("/lost.xml.gz"))
        self.assertEqual(board_dmarc.list_reports(self.table), [])


class DmarcEvaluateTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch.object(board_staff, "_blob_put", side_effect=lambda key, body: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.settings = board_store.load_settings(self.table)

    def _ingest(self, xml: bytes, *, thread_id: str = "thr") -> None:
        board_dmarc.ingest_message(self.table, _message_with(f"{thread_id}.xml", "application/xml", xml), thread_id=thread_id)

    def _findings(self, summary: dict[str, Any], kind: str) -> list[dict[str, Any]]:
        return [row for row in summary["findings"] if row["kind"] == kind]

    def test_aligned_mail_has_no_problem(self) -> None:
        self._ingest(
            _xml(
                report_id="ok",
                dkim="pass",
                spf="pass",
                dkim_domain="amazonses.com",
                spf_domain="siutindei.com",
                count=142,
            )
        )
        summary = board_dmarc.evaluate(self.table, self.settings)
        self.assertEqual(summary["last24h"]["messages"], 142)
        self.assertEqual(summary["last24h"]["alignedPct"], 100.0)
        self.assertEqual(summary["windowDays"]["7"]["orgs"], 1)
        self.assertTrue(summary["line"].startswith("DMARC (reports received in the last 24 h):"))
        self.assertIn("No problems.", summary["line"])
        self.assertEqual(self._findings(summary, "own_sender_failing"), [])
        self.assertEqual(self._findings(summary, "new_header_from_domain"), [])
        self.assertEqual(self._findings(summary, "policy_drift"), [])

    def test_own_sender_failing_is_high_and_a_config_gap(self) -> None:
        self._ingest(
            _xml(
                report_id="ses",
                dkim="fail",
                spf="fail",
                dkim_domain="amazonses.com",
                spf_domain="siutindei.com",
                source_ip="1.2.3.4",
                count=4,
            )
        )
        summary = board_dmarc.evaluate(self.table, self.settings)
        rows = self._findings(summary, "own_sender_failing")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["severity"], "high")
        self.assertIn("amazonses.com", rows[0]["summary"])
        gaps = board_duties.list_config_gaps(self.table)
        self.assertTrue(any(row.get("gapId") == "dmarc:amazonses.com" for row in gaps))

    def test_unknown_source_severity_follows_the_daily_count(self) -> None:
        self._ingest(_xml(report_id="spoof-low", count=14, source_ip="203.0.113.9"))
        low = board_dmarc.evaluate(self.table, self.settings)
        row = self._findings(low, "unknown_source_failing")[0]
        self.assertEqual(row["severity"], "medium")
        self.assertIn("203.0.113.9", row["summary"])
        self._ingest(_xml(report_id="spoof-high", count=20, source_ip="203.0.113.10"))
        high = board_dmarc.evaluate(self.table, self.settings)
        match = next(item for item in self._findings(high, "unknown_source_failing") if "203.0.113.10" in item["summary"])
        self.assertEqual(match["severity"], "high")

    def test_forwarding_is_info_only(self) -> None:
        self._ingest(
            _xml(
                report_id="fwd",
                dkim="pass",
                spf="fail",
                dkim_domain="example.net",
                spf_domain="example.net",
                source_ip="198.51.100.4",
                count=3,
            )
        )
        summary = board_dmarc.evaluate(self.table, self.settings)
        rows = self._findings(summary, "forwarding_noise")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["severity"], "info")
        self.assertEqual(self._findings(summary, "unknown_source_failing"), [])

    def test_policy_drift_and_new_header_from(self) -> None:
        self._ingest(
            _xml(
                report_id="drift",
                p="none",
                pct=50,
                header_from="mail.siutindei.com",
                dkim="pass",
                spf="pass",
                dkim_domain="amazonses.com",
                spf_domain="amazonses.com",
            )
        )
        first = board_dmarc.evaluate(self.table, self.settings)
        self.assertEqual(len(self._findings(first, "policy_drift")), 1)
        self.assertIn("p=none", self._findings(first, "policy_drift")[0]["summary"])
        headers = self._findings(first, "new_header_from_domain")
        self.assertEqual([row["evidence"]["domain"] for row in headers], ["mail.siutindei.com"])
        second = board_dmarc.evaluate(self.table, self.settings)
        self.assertEqual(self._findings(second, "new_header_from_domain"), [])
        self.assertEqual(len(self._findings(second, "policy_drift")), 1)

    def test_google_silence_and_its_absence(self) -> None:
        self._ingest(
            _xml(
                report_id="old-google",
                dkim="pass",
                spf="pass",
                dkim_domain="amazonses.com",
                spf_domain="amazonses.com",
            )
        )
        old = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        old_end = int((datetime.now(timezone.utc) - timedelta(days=10)).timestamp())
        for item in self.table.items.values():
            if str(item.get("sk", "")).startswith("REPORT#"):
                item["receivedAt"] = old
                item["dateEnd"] = old
                item["dateEndUnix"] = old_end
        meta = board_store._get_state(self.table, "dmarc#meta") or {}  # noqa: SLF001
        meta["lastGoogleReceivedAt"] = old
        board_store._put_state(self.table, "dmarc#meta", meta)  # noqa: SLF001
        summary = board_dmarc.evaluate(self.table, self.settings)
        silent = self._findings(summary, "reports_silent")
        self.assertEqual(len(silent), 1)
        self.assertEqual(silent[0]["severity"], "medium")
        self.assertNotIn("reports_silent", {row["kind"] for row in board_dmarc.evaluate(self.table, {**self.settings, "dmarc": {"silenceDays": 30}})["findings"]})

    def test_disabled_check_keeps_numbers_and_drops_findings(self) -> None:
        self._ingest(_xml(report_id="off", count=5))
        settings = {**self.settings, "dmarc": {"enabled": False}}
        summary = board_dmarc.evaluate(self.table, settings)
        self.assertFalse(summary["enabled"])
        self.assertEqual(summary["findings"], [])
        self.assertEqual(summary["last24h"]["messages"], 5)
        self.assertIn("No problems.", summary["line"])

    def test_consumer_mail_domain_opens_a_config_gap(self) -> None:
        self._ingest(
            _xml(
                report_id="gmail",
                dkim_domain="google.com",
                spf_domain="gmail.com",
                source_ip="203.0.113.50",
            )
        )
        board_dmarc.evaluate(self.table, self.settings)
        gaps = board_duties.list_config_gaps(self.table)
        self.assertTrue(any(str(row.get("gapId") or "").startswith("dmarc:google.com") for row in gaps))

    def test_review_section_says_when_no_summary_exists(self) -> None:
        review = board_review.compile(self.table, self.settings, "2026-09-22")
        self.assertIn("no summary yet", review["dmarc"]["line"])
        self.assertIn("DMARC", review["digestHtml"])
        self.assertEqual(set(review["dmarc"]), {"line", "findings"})

    def test_spoofed_known_domain_is_not_our_sender(self) -> None:
        self._ingest(
            _xml(
                report_id="spoof-ses",
                dkim="fail",
                spf="fail",
                dkim_domain="amazonses.com",
                spf_domain="amazonses.com",
                header_from="attacker.example",
                source_ip="198.51.100.8",
                count=14,
            )
        )
        summary = board_dmarc.evaluate(self.table, self.settings)
        self.assertEqual(self._findings(summary, "own_sender_failing"), [])
        row = self._findings(summary, "unknown_source_failing")[0]
        self.assertEqual(row["severity"], "medium")
        self.assertEqual(row["evidence"]["dkim"], "fail")
        self.assertEqual(row["evidence"]["spf"], "fail")
        gaps = board_duties.list_config_gaps(self.table)
        self.assertFalse(any(str(row.get("gapId") or "") == "dmarc:amazonses.com" for row in gaps))

    def test_small_unknown_source_stays_info(self) -> None:
        self._ingest(_xml(report_id="tiny", count=1, source_ip="203.0.113.77"))
        summary = board_dmarc.evaluate(self.table, self.settings)
        row = self._findings(summary, "unknown_source_failing")[0]
        self.assertEqual(row["severity"], "info")

    def test_mixed_results_are_not_called_pass(self) -> None:
        self._ingest(
            _xml(report_id="mix-a", dkim="pass", spf="fail", count=2, source_ip="203.0.113.9", dkim_domain="evil.example", spf_domain="evil.example")
        )
        self._ingest(
            _xml(report_id="mix-b", dkim="fail", spf="fail", count=2, source_ip="203.0.113.9", dkim_domain="evil.example", spf_domain="evil.example")
        )
        summary = board_dmarc.evaluate(self.table, self.settings)
        row = self._findings(summary, "unknown_source_failing")[0]
        self.assertEqual(row["evidence"]["dkim"], "mixed")
        self.assertEqual(row["evidence"]["spf"], "fail")

    def test_read_tool_does_not_evaluate(self) -> None:
        from types import SimpleNamespace

        self._ingest(_xml(report_id="unread", header_from="fresh.example"))
        out = board_dmarc.op_summary(SimpleNamespace(table=self.table, settings=self.settings), {})
        self.assertFalse(out["cached"])
        self.assertIn("no summary yet", out["line"])
        self.assertIsNone(board_store.get_cache(self.table, "dmarc:summary"))
        self.assertFalse(board_store._get_state(self.table, "dmarc#header-from"))  # noqa: SLF001

    def test_stale_summary_is_called_out_on_review(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        board_store.put_cache(
            self.table,
            "dmarc:summary",
            {"generatedAt": old, "line": "DMARC (reports received in the last 24 h): no aggregate reports. No problems.", "findings": [], "sources": [{"sourceIp": "x"}]},
        )
        review = board_review.compile(self.table, self.settings, "2026-09-22")
        self.assertIn("older than the hourly refresh", review["dmarc"]["line"])
        self.assertNotIn("sources", review["dmarc"])

    def test_refresh_failure_does_not_stop_the_cache_job(self) -> None:
        import board_cache

        with patch.object(board_dmarc, "refresh", side_effect=RuntimeError("boom")):
            notes = board_cache.refresh_all(self.table)
        self.assertIn("boom", notes["dmarc"]["error"])
        self.assertIn("aws", notes)


class DmarcTaskTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        import os

        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        patcher = patch("board_async.invoke_async", side_effect=lambda payload, fallback=None: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        settings = board_store.load_settings(self.table)
        settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True})
        self.settings = board_store.save_settings(self.table, settings)

    def test_medium_finding_opens_one_task_and_info_does_not(self) -> None:
        board_store.save_staff_override(self.table, "security-analyst", {"isActive": True})
        board_store.put_cache(
            self.table,
            "dmarc:summary",
            {
                "findings": [
                    {
                        "kind": "unknown_source_failing",
                        "severity": "medium",
                        "fingerprint": "unknown_source_failing:203.0.113.9",
                        "summary": "unknown source 203.0.113.9 (14 msgs, spf fail, dkim fail)",
                        "evidence": {"sourceIp": "203.0.113.9", "count": 14},
                    },
                    {
                        "kind": "forwarding_noise",
                        "severity": "info",
                        "fingerprint": "forwarding_noise:198.51.100.4",
                        "summary": "forwarding 198.51.100.4 (dkim pass, spf fail, 3 msgs)",
                        "evidence": {"sourceIp": "198.51.100.4"},
                    },
                ]
            },
        )
        first = board_duties.triage_ops_signals(self.table, self.settings)
        self.assertEqual(first["dmarc"], 1)
        tasks = board_store.list_tasks(self.table, "queued") + board_store.list_tasks(self.table, "running")
        match = [task for task in tasks if (task.get("eventRef") or {}).get("id") == "dmarc:unknown_source_failing:203.0.113.9"]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["assignee"], "security-analyst")
        self.assertIn("security_dmarc_summary", match[0]["brief"])
        self.assertIn("security_open_remediation", match[0]["brief"])
        again = board_duties.triage_ops_signals(self.table, self.settings)
        self.assertEqual(again["dmarc"], 0)
        open_tasks = board_store.list_tasks(self.table, "queued") + board_store.list_tasks(self.table, "running")
        self.assertEqual(
            len([task for task in open_tasks if "forwarding_noise" in str((task.get("eventRef") or {}).get("id"))]),
            0,
        )

    def test_inactive_analyst_assigns_ciso(self) -> None:
        board_store.put_cache(
            self.table,
            "dmarc:summary",
            {
                "findings": [
                    {
                        "kind": "reports_silent",
                        "severity": "medium",
                        "fingerprint": "reports_silent:google",
                        "summary": "no Google DMARC report for 4 days",
                        "evidence": {},
                    }
                ]
            },
        )
        board_duties.triage_ops_signals(self.table, self.settings)
        tasks = board_store.list_tasks(self.table, "queued") + board_store.list_tasks(self.table, "running")
        self.assertEqual(tasks[0]["assignee"], "ciso")

    def test_stale_summary_opens_one_task_and_skips_old_findings(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        board_store.put_cache(
            self.table,
            "dmarc:summary",
            {
                "generatedAt": old,
                "findings": [
                    {
                        "kind": "unknown_source_failing",
                        "severity": "medium",
                        "fingerprint": "unknown_source_failing:203.0.113.9",
                        "summary": "unknown source 203.0.113.9",
                        "evidence": {},
                    }
                ],
            },
        )
        out = board_duties.triage_ops_signals(self.table, self.settings)
        self.assertEqual(out["dmarc"], 1)
        tasks = board_store.list_tasks(self.table, "queued") + board_store.list_tasks(self.table, "running")
        ids = [(task.get("eventRef") or {}).get("id") for task in tasks]
        self.assertIn("dmarc:summary_stale", ids)
        self.assertNotIn("dmarc:unknown_source_failing:203.0.113.9", ids)
