"""WP5 — mail ingest hardening: dedupe rollback, size caps, PDF handling, header injection."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import board_mail
import board_store
from botocore.exceptions import ClientError
from contract_constants import BOARD_MAIL_BODY_MAX_CHARS
from test_board_mail import MailTestCase, build_mail


def _client_error(code: str = "ValidationException") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "Item size has exceeded the maximum allowed size"}}, "PutItem")


def _fail_once(real, exc: Exception):
    calls = {"n": 0}

    def _wrapped(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise exc
        return real(*args, **kwargs)

    return _wrapped


class TestDedupeRollback(MailTestCase):
    """M9: a failed message write must not leave a Message-ID marker behind."""

    def _marker_rows(self) -> list[dict]:
        return [dict(i) for (pk, sk), i in self.table.items.items() if sk.startswith("MSGID#")]

    def _message_rows(self) -> list[dict]:
        return [dict(i) for (pk, sk), i in self.table.items.items() if sk.startswith("MSG#")]

    def test_put_message_client_error_then_redelivery_is_indexed(self) -> None:
        raw = build_mail()
        real = board_store.put_mail_message
        with patch.object(board_store, "put_mail_message", _fail_once(real, _client_error())):
            with self.assertRaises(ClientError):
                board_mail.ingest_bytes(self.table, raw)
        self.assertEqual(self._marker_rows(), [])
        self.assertEqual(self._message_rows(), [])
        self.assertIsNone(board_store.get_mail_thread_for_msgid(self.table, board_mail.msgid_digest("<abc123@mail.gmail.com>")))
        self.assertEqual(board_store.list_mail_threads(self.table), [])

        second = board_mail.ingest_bytes(self.table, raw)
        self.assertFalse(second["duplicate"])
        self.assertTrue(second["messageId"])
        self.assertEqual(len(self._marker_rows()), 1)
        self.assertEqual(len(board_store.list_mail_messages(self.table, second["threadId"])), 1)
        self.assertEqual(board_store.get_mail_thread(self.table, second["threadId"])["messageCount"], 1)
        # And a third delivery is now a genuine duplicate.
        self.assertTrue(board_mail.ingest_bytes(self.table, raw)["duplicate"])

    def test_put_message_runtime_error_also_rolls_back(self) -> None:
        raw = build_mail()
        real = board_store.put_mail_message
        with patch.object(board_store, "put_mail_message", _fail_once(real, RuntimeError("boom"))):
            with self.assertRaises(RuntimeError):
                board_mail.ingest_bytes(self.table, raw)
        self.assertEqual(self._marker_rows(), [])
        self.assertFalse(board_mail.ingest_bytes(self.table, raw)["duplicate"])

    def test_put_thread_failure_removes_marker_and_message(self) -> None:
        raw = build_mail()
        real = board_store.put_mail_thread
        with patch.object(board_store, "put_mail_thread", _fail_once(real, _client_error("ProvisionedThroughputExceededException"))):
            with self.assertRaises(ClientError):
                board_mail.ingest_bytes(self.table, raw)
        self.assertEqual(self._marker_rows(), [])
        self.assertEqual(self._message_rows(), [], "orphan message row must be rolled back")
        result = board_mail.ingest_bytes(self.table, raw)
        self.assertFalse(result["duplicate"])
        self.assertEqual(len(board_store.list_mail_messages(self.table, result["threadId"])), 1)

    def test_rollback_delete_failure_is_logged_and_original_error_raised(self) -> None:
        raw = build_mail()
        real = board_store.put_mail_message
        with patch.object(board_store, "put_mail_message", _fail_once(real, RuntimeError("original"))), patch.object(
            self.table, "delete_item", side_effect=RuntimeError("ddb down")
        ), patch.object(board_mail, "_log_event") as log:
            with self.assertRaisesRegex(RuntimeError, "original"):
                board_mail.ingest_bytes(self.table, raw)
        tags = [c.kwargs.get("tag") for c in log.call_args_list]
        self.assertIn("board_mail_ingest_rolled_back", tags)
        self.assertIn("board_mail_rollback_failed", tags)


class TestSizeCaps(MailTestCase):
    def test_oversized_mail_is_capped_and_flagged(self) -> None:
        attachments = [(f"notes-{i:02d}.txt", "text/plain", (f"A{i:02d}" * 5000 + "\n").encode()) for i in range(20)]
        raw = build_mail(text="B" * 30000, attachments=attachments)
        self.assertGreater(len(raw), 400 * 1024, "synthetic mail must itself exceed the DynamoDB item limit")
        result = board_mail.ingest_bytes(self.table, raw)
        self.assertFalse(result["duplicate"])

        rows = [i for (pk, sk), i in self.table.items.items() if sk.startswith("MSG#")]
        self.assertEqual(len(rows), 1)
        item = rows[0]
        serialized = json.dumps(item, default=str).encode("utf-8")
        self.assertLess(len(serialized), 300 * 1024, f"stored item is {len(serialized)} bytes")
        self.assertIs(item["truncated"], True)
        self.assertEqual(len(item["text"]), BOARD_MAIL_BODY_MAX_CHARS)
        self.assertEqual(len(item["attachments"]), 20)
        total_text = sum(len(a.get("text", "")) for a in item["attachments"])
        self.assertLessEqual(total_text, board_mail.ATTACHMENT_TEXT_TOTAL_MAX_CHARS)
        self.assertEqual(len(item["attachments"][0]["text"]), 15001)  # per-part cap wins first
        self.assertEqual(item["attachments"][-1]["text"], "")  # budget exhausted
        self.assertEqual(item["attachmentsSkipped"], [])
        # Sizes are still reported for parts whose text was dropped.
        self.assertEqual(item["attachments"][-1]["size"], 15001)

    def test_small_mail_is_not_flagged(self) -> None:
        result = self.ingest()
        message = board_store.list_mail_messages(self.table, result["threadId"])[0]
        self.assertIs(message["truncated"], False)
        self.assertEqual(message["attachmentsSkipped"], [])

    def test_more_than_max_attachments_sets_truncated(self) -> None:
        attachments = [(f"f{i}.csv", "text/csv", b"a,b\n") for i in range(board_mail.MAX_ATTACHMENTS + 3)]
        parsed = board_mail.parse_mime(build_mail(attachments=attachments))
        self.assertEqual(len(parsed.attachments), board_mail.MAX_ATTACHMENTS)
        self.assertTrue(parsed.truncated)

    def test_huge_recipient_lists_are_capped(self) -> None:
        to = ", ".join(f"p{i}@example.org" for i in range(200)) + ", hello@siutindei.com"
        parsed = board_mail.parse_mime(build_mail(to=to))
        self.assertEqual(len(parsed.to), board_mail.MAX_ADDRESSES_PER_HEADER)
        self.assertTrue(parsed.truncated)
        # Mailbox detection still finds the own-domain address beyond the cap.
        self.assertEqual(parsed.mailbox, "unknown@siutindei.com")
        parsed = board_mail.parse_mime(build_mail(to="hello@siutindei.com, " + ", ".join(f"p{i}@example.org" for i in range(3))))
        self.assertFalse(parsed.truncated)
        self.assertEqual(parsed.mailbox, "hello@siutindei.com")

    def test_persona_view_exposes_truncation_and_skipped(self) -> None:
        raw = build_mail(
            text="T" * (BOARD_MAIL_BODY_MAX_CHARS + 10),
            attachments=[("invoice.pdf", "application/pdf", b"%PDF-1.4 fake"), ("a.txt", "text/plain", b"hello wendy@gmail.com")],
        )
        result = board_mail.ingest_bytes(self.table, raw)
        detail = board_mail.masked_thread_detail(self.table, result["threadId"])
        message = detail["messages"][0]
        self.assertTrue(message["truncated"])
        self.assertEqual(message["attachmentsSkipped"], ["invoice.pdf"])
        self.assertNotIn("wendy@gmail.com", message["attachments"][1]["text"])
        self.assertIn("contact#", message["attachments"][1]["text"])


class TestPdfAttachments(MailTestCase):
    def test_pdf_attachments_are_listed_as_skipped_without_text(self) -> None:
        raw = build_mail(
            attachments=[
                ("prices.pdf", "application/pdf", b"%PDF-1.4 fake"),
                ("Scan 001.PDF", "application/octet-stream", b"%PDF-1.4 by extension"),
                ("list.csv", "text/csv", b"a,b\n1,2\n"),
                ("photo.jpg", "image/jpeg", b"\xff\xd8\xff"),
            ]
        )
        parsed = board_mail.parse_mime(raw)
        self.assertEqual(parsed.attachments_skipped, ["prices.pdf", "Scan 001.PDF"])
        self.assertFalse(parsed.truncated)
        self.assertEqual([a["name"] for a in parsed.attachments], ["prices.pdf", "Scan 001.PDF", "list.csv", "photo.jpg"])
        self.assertTrue(all("text" not in a for a in parsed.attachments if a["name"] != "list.csv"))
        result = board_mail.ingest_bytes(self.table, raw)
        message = board_store.list_mail_messages(self.table, result["threadId"])[0]
        self.assertEqual(message["attachmentsSkipped"], ["prices.pdf", "Scan 001.PDF"])
        self.assertTrue(board_store.get_mail_thread(self.table, result["threadId"])["hasAttachments"])


class TestHeaderInjection(MailTestCase):
    def _raw(self, **headers: str) -> bytes:
        """Hand-built MIME so folded / injected header bytes reach the parser verbatim."""
        lines = [
            "From: " + headers.pop("From", "Wendy Chan <wendy.chan@gmail.com>"),
            "To: hello@siutindei.com",
            "Subject: " + headers.pop("Subject", "Swimming class for my daughter"),
            "Date: Fri, 04 Sep 2026 10:15:00 +0800",
            "Message-ID: " + headers.pop("Message-ID", "<abc123@mail.gmail.com>"),
        ]
        lines += [f"{k}: {v}" for k, v in headers.items()]
        return ("\r\n".join(lines) + "\r\n\r\nHi there.\r\n").encode("utf-8")

    def test_folded_subject_and_from_are_single_line(self) -> None:
        raw = self._raw(
            Subject="Swimming class for my daughter\r\n X-Injected: yes\r\n Bcc: evil@attacker.example",
            From='"Wendy\r\n Chan\r\n X-Evil: 1" <wendy.chan@gmail.com>',
        )
        parsed = board_mail.parse_mime(raw)
        for value in (parsed.subject, parsed.from_name):
            self.assertNotIn("\r", value)
            self.assertNotIn("\n", value)
        self.assertEqual(parsed.subject, "Swimming class for my daughter X-Injected: yes Bcc: evil@attacker.example")
        self.assertEqual(parsed.from_address, "wendy.chan@gmail.com")
        self.assertEqual(parsed.to, ["hello@siutindei.com"])
        # Nothing leaked into the recipient lists or mailbox detection.
        self.assertNotIn("evil@attacker.example", [*parsed.to, *parsed.cc])
        self.assertEqual(parsed.mailbox, "hello@siutindei.com")

    def test_reply_to_injected_subject_produces_exactly_one_subject_header(self) -> None:
        raw = self._raw(Subject="Swimming class\r\n Bcc: evil@attacker.example\r\n X-Injected: yes")
        thread_id = board_mail.ingest_bytes(self.table, raw)["threadId"]
        plan = board_mail.outgoing_plan(self.table, "mail_reply", {"threadId": thread_id, "body": "Two places left."})
        # Even if a stored subject somehow carried CR/LF, sending must not split headers.
        plan["subject"] = "Re: Swimming class\r\nBcc: evil@attacker.example\r\nX-Injected: yes"
        plan["inReplyTo"] = "<abc123@mail.gmail.com>\r\nX-Also: bad"
        sent = board_mail.send_plan(self.table, plan, sent_by="test:coo")
        self.assertTrue(sent["ok"])
        outbound = self.ses.last_raw()
        self.assertEqual(outbound.get_all("Subject"), ["Re: Swimming class Bcc: evil@attacker.example X-Injected: yes"])
        self.assertIsNone(outbound.get("Bcc"))
        self.assertIsNone(outbound.get("X-Injected"))
        self.assertIsNone(outbound.get("X-Also"))
        self.assertEqual(outbound["In-Reply-To"], "<abc123@mail.gmail.com> X-Also: bad")
        self.assertEqual(self.ses.sent[0]["Destination"]["ToAddresses"], ["wendy.chan@gmail.com"])
        # The outbound copy is threaded with the original via In-Reply-To/References.
        messages = board_store.list_mail_messages(self.table, thread_id)
        self.assertEqual([m["direction"] for m in messages], ["in", "out"])

    def test_folded_message_ids_still_thread_and_dedupe(self) -> None:
        first = board_mail.ingest_bytes(self.table, self._raw(**{"Message-ID": "<abc123@mail.gmail.com>\r\n "}))
        self.assertEqual(board_mail.msgid_digest("<abc123@mail.gmail.com>\r\n "), board_mail.msgid_digest("<abc123@mail.gmail.com>"))
        # Same id without folding → duplicate.
        again = board_mail.ingest_bytes(self.table, self._raw(**{"Message-ID": "<abc123@mail.gmail.com>"}))
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["threadId"], first["threadId"])
        # A reply whose In-Reply-To is folded onto a continuation line joins the thread.
        reply = board_mail.ingest_bytes(
            self.table,
            self._raw(
                **{
                    "Subject": "Totally different subject",
                    "Message-ID": "<r1@mail.gmail.com>",
                    "In-Reply-To": "\r\n <abc123@mail.gmail.com>",
                }
            ),
        )
        self.assertFalse(reply["duplicate"])
        self.assertEqual(reply["threadId"], first["threadId"])
        self.assertEqual(board_store.get_mail_thread(self.table, first["threadId"])["messageCount"], 2)

    def test_subject_with_injected_prefix_threads_by_normalised_subject(self) -> None:
        first = board_mail.ingest_bytes(self.table, self._raw())
        follow = board_mail.ingest_bytes(
            self.table,
            self._raw(**{"Subject": "RE:\r\n Swimming class for my daughter", "Message-ID": "<abc124@mail.gmail.com>"}),
        )
        self.assertEqual(follow["threadId"], first["threadId"])


class TestMissingMessageId(MailTestCase):
    def test_same_bytes_dedupe_and_different_bytes_do_not(self) -> None:
        raw = build_mail(message_id=None)
        first = board_mail.ingest_bytes(self.table, raw)
        self.assertFalse(first["duplicate"])
        message = board_store.list_mail_messages(self.table, first["threadId"])[0]
        self.assertEqual(message["rfcMessageId"], board_mail.synthetic_message_id(raw))
        self.assertTrue(message["rfcMessageId"].startswith("<sha256-"))
        self.assertTrue(message["rfcMessageId"].endswith("@siutindei.com>"))

        again = board_mail.ingest_bytes(self.table, raw)
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["threadId"], first["threadId"])
        self.assertEqual(board_store.get_mail_thread(self.table, first["threadId"])["messageCount"], 1)

        other = board_mail.ingest_bytes(self.table, build_mail(message_id=None, text="A different body."))
        self.assertFalse(other["duplicate"])
        self.assertEqual(other["threadId"], first["threadId"])  # same subject + counterpart
        self.assertEqual(board_store.get_mail_thread(self.table, first["threadId"])["messageCount"], 2)
        self.assertNotEqual(
            board_store.list_mail_messages(self.table, first["threadId"])[1]["rfcMessageId"],
            message["rfcMessageId"],
        )

    def test_synthetic_id_is_deterministic_and_content_bound(self) -> None:
        a = board_mail.synthetic_message_id(b"x")
        self.assertEqual(a, board_mail.synthetic_message_id(b"x"))
        self.assertNotEqual(a, board_mail.synthetic_message_id(b"y"))
        self.assertEqual(board_mail.msgid_digest(a), board_mail.msgid_digest(a + "\r\n"))

    def test_missing_message_id_rollback_then_redelivery(self) -> None:
        raw = build_mail(message_id=None)
        real = board_store.put_mail_message
        with patch.object(board_store, "put_mail_message", _fail_once(real, RuntimeError("boom"))):
            with self.assertRaises(RuntimeError):
                board_mail.ingest_bytes(self.table, raw)
        self.assertFalse(board_mail.ingest_bytes(self.table, raw)["duplicate"])
        self.assertTrue(board_mail.ingest_bytes(self.table, raw)["duplicate"])


if __name__ == "__main__":
    unittest.main()
