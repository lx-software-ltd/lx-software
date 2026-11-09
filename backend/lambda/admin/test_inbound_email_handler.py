"""Tests for inbound SES statement mail."""

from __future__ import annotations

import io
import json
import os
import unittest
from email.message import EmailMessage
from typing import Any
from unittest.mock import MagicMock, patch

from inbound_email_handler import (
    _record_inbound_asset_meta,
    house_key_from_raw_mail_s3_key,
    inbound_mailbox_from_raw_s3_key,
)
from inbound_statement_sources import (
    BODY_FILENAME,
    MIN_STATEMENT_IMAGE_BYTES,
    extract_first_pdf_attachment,
    extract_pdf_attachments,
    extract_statement_sources,
)


def _pdf_mail(*, to: str = "billing@inbound.lx-software.com") -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "Invoice"
    msg["From"] = "vendor@example.com"
    msg["To"] = to
    msg.set_content("See attached.")
    msg.add_attachment(
        b"%PDF-1.4 invoice",
        maintype="application",
        subtype="pdf",
        filename="invoice.pdf",
    )
    return msg.as_bytes()


class _FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.puts: list[dict[str, Any]] = []
        self.deleted: list[tuple[str, str]] = []

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.puts.append(kwargs)
        return {}

    def delete_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        self.deleted.append((Bucket, Key))
        return {}


class TestExtractFirstPdf(unittest.TestCase):
    def test_multipart_attachment(self) -> None:
        msg = EmailMessage()
        msg["Subject"] = "Stmt"
        msg["From"] = "a@b.com"
        msg["To"] = "32-hillmarton@inbound.lx-software.com"
        msg.set_content("See attached.")
        pdf = b"%PDF-1.4 minimal"
        msg.add_attachment(
            pdf,
            maintype="application",
            subtype="pdf",
            filename="January.pdf",
        )
        raw = msg.as_bytes()
        got = extract_first_pdf_attachment(raw)
        self.assertIsNotNone(got)
        data, name = got
        self.assertEqual(data, pdf)
        self.assertEqual(name, "January.pdf")

    def test_skips_non_pdf(self) -> None:
        msg = EmailMessage()
        msg.set_content("plain")
        msg.add_attachment(b"hello", maintype="text", subtype="plain", filename="x.txt")
        self.assertIsNone(extract_first_pdf_attachment(msg.as_bytes()))

    def test_extracts_multiple_pdfs_in_order(self) -> None:
        msg = EmailMessage()
        msg.set_content("body")
        msg.add_attachment(
            b"%PDF-1 first",
            maintype="application",
            subtype="pdf",
            filename="a.pdf",
        )
        msg.add_attachment(
            b"%PDF-1 second",
            maintype="application",
            subtype="pdf",
            filename="b.pdf",
        )
        parts = extract_pdf_attachments(msg.as_bytes())
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0][0], b"%PDF-1 first")
        self.assertEqual(parts[0][1], "a.pdf")
        self.assertEqual(parts[1][0], b"%PDF-1 second")
        self.assertEqual(parts[1][1], "b.pdf")


class TestHouseKeyFromRawMailKey(unittest.TestCase):
    def test_resolves_hillmarton(self) -> None:
        self.assertEqual(
            house_key_from_raw_mail_s3_key(
                ses_drop_path="inbound-raw/hillmarton/AMAZON_SES_msg",
                raw_mail_prefix="inbound-raw",
            ),
            "hillmarton",
        )

    def test_resolves_morrison(self) -> None:
        self.assertEqual(
            house_key_from_raw_mail_s3_key(
                ses_drop_path="inbound-raw/morrison/x",
                raw_mail_prefix="inbound-raw",
            ),
            "morrison",
        )

    def test_resolves_lx_software_billing_prefix(self) -> None:
        mailbox = inbound_mailbox_from_raw_s3_key(
            ses_drop_path="inbound-raw/lx-software/AMAZON_SES_msg",
            raw_mail_prefix="inbound-raw",
        )
        self.assertIsNotNone(mailbox)
        assert mailbox is not None
        self.assertEqual(mailbox.owner_key, "lxSoftware")
        self.assertEqual(mailbox.line_type_only, "expenditure")
        self.assertEqual(
            house_key_from_raw_mail_s3_key(
                ses_drop_path="inbound-raw/lx-software/AMAZON_SES_msg",
                raw_mail_prefix="inbound-raw",
            ),
            "lxSoftware",
        )

    def test_rejects_unknown_house_segment(self) -> None:
        self.assertIsNone(
            house_key_from_raw_mail_s3_key(
                ses_drop_path="inbound-raw/unknown/x",
                raw_mail_prefix="inbound-raw",
            )
        )

    def test_rejects_wrong_prefix(self) -> None:
        self.assertIsNone(
            house_key_from_raw_mail_s3_key(
                ses_drop_path="other/hillmarton/x",
                raw_mail_prefix="inbound-raw",
            )
        )

    def test_env_json_overrides_defaults(self) -> None:
        env = {
            "INBOUND_STATEMENT_MAILBOXES": json.dumps(
                [
                    {
                        "segment": "lx-software",
                        "ownerKey": "lxSoftware",
                        "lineTypeOnly": "income",
                    }
                ]
            )
        }
        with patch.dict(os.environ, env, clear=False):
            mailbox = inbound_mailbox_from_raw_s3_key(
                ses_drop_path="inbound-raw/lx-software/x",
                raw_mail_prefix="inbound-raw",
            )
            self.assertIsNotNone(mailbox)
            assert mailbox is not None
            self.assertEqual(mailbox.line_type_only, "income")
            self.assertIsNone(
                house_key_from_raw_mail_s3_key(
                    ses_drop_path="inbound-raw/hillmarton/x",
                    raw_mail_prefix="inbound-raw",
                )
            )


class TestInboundParseEnqueue(unittest.TestCase):
    def test_billing_prefix_enqueues_lx_software_expenditure(self) -> None:
        import inbound_email_handler

        s3 = _FakeS3()
        key = "inbound-raw/lx-software/msg1"
        s3.objects[("inbound-bucket", key)] = _pdf_mail()
        event = {
            "Records": [
                {
                    "eventSource": "aws:s3",
                    "s3": {
                        "bucket": {"name": "inbound-bucket"},
                        "object": {"key": key},
                    },
                }
            ]
        }
        env = {
            "INBOUND_MAIL_BUCKET_NAME": "inbound-bucket",
            "ASSETS_BUCKET_NAME": "assets",
            "INBOUND_RAW_MAIL_PREFIX": "inbound-raw",
            "INBOUND_STATEMENT_MAILBOXES": "",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(inbound_email_handler, "_s3", s3),
            patch.object(
                inbound_email_handler,
                "enqueue_parse_statement_async_job",
                return_value="job-billing",
            ) as enq,
            patch.object(
                inbound_email_handler,
                "_record_inbound_asset_meta",
            ) as meta,
        ):
            out = inbound_email_handler.lambda_handler(event, None)
        self.assertEqual(out, {"ok": True})
        enq.assert_called_once()
        meta.assert_called_once()
        self.assertEqual(meta.call_args.kwargs["house"], "lxSoftware")
        self.assertEqual(meta.call_args.kwargs["file_name"], "invoice.pdf")
        self.assertTrue(meta.call_args.kwargs["s3_key"].startswith("inbound/lxSoftware/"))
        kwargs = enq.call_args.kwargs
        self.assertEqual(kwargs["house"], "lxSoftware")
        self.assertEqual(kwargs["line_type_only"], "expenditure")
        self.assertEqual(kwargs["source"], "inbound_mail")
        self.assertEqual(len(kwargs["s3_keys"]), 1)
        self.assertTrue(kwargs["s3_keys"][0].startswith("inbound/lxSoftware/"))
        self.assertTrue(kwargs["s3_keys"][0].endswith("_invoice.pdf"))
        self.assertEqual(s3.deleted, [("inbound-bucket", key)])

    def test_hillmarton_prefix_does_not_filter_line_type(self) -> None:
        import inbound_email_handler

        s3 = _FakeS3()
        key = "inbound-raw/hillmarton/msg1"
        s3.objects[("inbound-bucket", key)] = _pdf_mail(to="32-hillmarton@inbound.lx-software.com")
        event = {
            "Records": [
                {
                    "eventSource": "aws:s3",
                    "s3": {
                        "bucket": {"name": "inbound-bucket"},
                        "object": {"key": key},
                    },
                }
            ]
        }
        env = {
            "INBOUND_MAIL_BUCKET_NAME": "inbound-bucket",
            "ASSETS_BUCKET_NAME": "assets",
            "INBOUND_RAW_MAIL_PREFIX": "inbound-raw",
            "INBOUND_STATEMENT_MAILBOXES": "",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(inbound_email_handler, "_s3", s3),
            patch.object(
                inbound_email_handler,
                "enqueue_parse_statement_async_job",
                return_value="job-h",
            ) as enq,
            patch.object(
                inbound_email_handler,
                "_record_inbound_asset_meta",
            ) as meta,
        ):
            inbound_email_handler.lambda_handler(event, None)
        kwargs = enq.call_args.kwargs
        self.assertEqual(kwargs["house"], "hillmarton")
        self.assertIsNone(kwargs["line_type_only"])
        self.assertEqual(meta.call_args.kwargs["file_name"], "invoice.pdf")
        self.assertEqual(meta.call_args.kwargs["house"], "hillmarton")


def _bill_message(
    *,
    body: str,
    to: str = "billing@inbound.lx-software.com",
    subject: str = "Invoice",
    html: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "vendor@example.com"
    msg["To"] = to
    msg["Date"] = "Mon, 09 Nov 2026 09:00:00 +0000"
    msg.set_content(body)
    if html is not None:
        msg.add_alternative(html, subtype="html")
    return msg


def _run_inbound(key: str, raw: bytes):
    import inbound_email_handler

    s3 = _FakeS3()
    s3.objects[("inbound-bucket", key)] = raw
    event = {
        "Records": [
            {
                "eventSource": "aws:s3",
                "s3": {
                    "bucket": {"name": "inbound-bucket"},
                    "object": {"key": key},
                },
            }
        ]
    }
    env = {
        "INBOUND_MAIL_BUCKET_NAME": "inbound-bucket",
        "ASSETS_BUCKET_NAME": "assets",
        "INBOUND_RAW_MAIL_PREFIX": "inbound-raw",
        "INBOUND_STATEMENT_MAILBOXES": "",
    }
    with (
        patch.dict(os.environ, env, clear=False),
        patch.object(inbound_email_handler, "_s3", s3),
        patch.object(
            inbound_email_handler,
            "enqueue_parse_statement_async_job",
            return_value="job-body",
        ) as enq,
        patch.object(inbound_email_handler, "_record_inbound_asset_meta") as meta,
    ):
        out = inbound_email_handler.lambda_handler(event, None)
    return out, s3, enq, meta


class TestStatementSourcesWithoutPdf(unittest.TestCase):
    def test_plain_body_with_an_amount_becomes_text(self) -> None:
        raw = _bill_message(
            body="Electricity total 88.10 HKD on 2 Nov 2026.",
            subject="November electricity",
        ).as_bytes()
        sources = extract_statement_sources(raw)
        self.assertEqual(len(sources), 1)
        source = sources[0]
        self.assertEqual(source.kind, "body")
        self.assertEqual(source.content_type, "text/plain")
        self.assertEqual(source.filename, BODY_FILENAME)
        text = source.data.decode("utf-8")
        self.assertIn("Subject: November electricity", text)
        self.assertIn("Date:", text)
        self.assertIn("88.10", text)
        self.assertIn("HKD", text)

    def test_a_date_header_alone_is_not_an_amount(self) -> None:
        raw = _bill_message(body="Thanks for the note.", subject="Hello").as_bytes()
        self.assertEqual(extract_statement_sources(raw), [])

    def test_a_whole_amount_next_to_total_is_kept(self) -> None:
        raw = _bill_message(body="Total: 120", subject="Bill").as_bytes()
        sources = extract_statement_sources(raw)
        self.assertEqual([source.kind for source in sources], ["body"])
        self.assertIn(b"Total: 120", sources[0].data)

    def test_prose_with_a_reference_number_is_kept_when_nothing_else_is_attached(self) -> None:
        raw = _bill_message(
            body="Invoice 1042 is due tomorrow. Please record it against the house book.",
            subject="Note",
        ).as_bytes()
        sources = extract_statement_sources(raw)
        self.assertEqual([source.kind for source in sources], ["body"])
        self.assertIn(b"1042", sources[0].data)

    def test_html_amount_wins_over_a_plain_stub(self) -> None:
        raw = _bill_message(
            body="View this message in a browser.",
            html="<html><body><p>Hosting</p><p>Total USD 42.00</p></body></html>",
        ).as_bytes()
        sources = extract_statement_sources(raw)
        self.assertEqual(len(sources), 1)
        text = sources[0].data.decode("utf-8")
        self.assertIn("USD 42.00", text)
        self.assertIn("Hosting", text)
        self.assertNotIn("View this message in a browser.", text)

    def test_amount_in_the_body_is_not_replaced_by_a_signature_image(self) -> None:
        msg = _bill_message(body="Electricity total 88.10 HKD on 2 Nov 2026.")
        msg.add_attachment(
            b"\x89PNG" + b"y" * 80,
            maintype="image",
            subtype="png",
            filename="logo.png",
        )
        sources = extract_statement_sources(msg.as_bytes())
        self.assertEqual([source.kind for source in sources], ["body"])
        self.assertNotIn(b"PNG", sources[0].data)

    def test_receipt_image_is_used_when_the_body_has_no_amount(self) -> None:
        msg = _bill_message(
            body="See photo.",
            subject="Receipt",
            to="the-morrison@inbound.lx-software.com",
        )
        blob = b"\xff\xd8\xff" + b"x" * (MIN_STATEMENT_IMAGE_BYTES + 8)
        msg.add_attachment(blob, maintype="image", subtype="jpeg", filename="receipt.jpg")
        sources = extract_statement_sources(msg.as_bytes())
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].kind, "attachment")
        self.assertEqual(sources[0].content_type, "image/jpeg")
        self.assertEqual(sources[0].filename, "receipt.jpg")
        self.assertEqual(sources[0].data, blob)

    def test_tiny_image_and_a_note_without_an_amount_are_skipped(self) -> None:
        msg = _bill_message(body="Thanks.")
        msg.add_attachment(
            b"\x89PNG" + b"y" * 40,
            maintype="image",
            subtype="png",
            filename="pixel.png",
        )
        self.assertEqual(extract_statement_sources(msg.as_bytes()), [])

    def test_csv_attachment_is_stored_as_text(self) -> None:
        msg = _bill_message(body="See attached.")
        msg.add_attachment(
            b"date,description,amount,currency\n2026-11-01,Hosting,42.00,USD\n",
            maintype="text",
            subtype="csv",
            filename="lines.csv",
        )
        sources = extract_statement_sources(msg.as_bytes())
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].kind, "attachment")
        self.assertEqual(sources[0].content_type, "text/plain")
        self.assertEqual(sources[0].filename, "lines.txt")
        self.assertIn(b"Hosting", sources[0].data)
        self.assertIn(b"42.00", sources[0].data)

    def test_pdf_stays_the_only_source_when_the_body_also_has_an_amount(self) -> None:
        msg = _bill_message(body="Total USD 42.00 for hosting on 1 Nov 2026.")
        pdf = b"%PDF-1.4 invoice"
        msg.add_attachment(pdf, maintype="application", subtype="pdf", filename="invoice.pdf")
        sources = extract_statement_sources(msg.as_bytes())
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].kind, "pdf")
        self.assertEqual(sources[0].content_type, "application/pdf")
        self.assertEqual(sources[0].data, pdf)
        self.assertEqual(sources[0].filename, "invoice.pdf")


class TestInboundBodyEnqueue(unittest.TestCase):
    def test_every_statement_inbox_enqueues_a_body_with_an_amount(self) -> None:
        inboxes = (
            (
                "inbound-raw/lx-software/msg-body",
                "billing@inbound.lx-software.com",
                "lxSoftware",
                "expenditure",
            ),
            (
                "inbound-raw/hillmarton/msg-body",
                "32-hillmarton@inbound.lx-software.com",
                "hillmarton",
                None,
            ),
            (
                "inbound-raw/morrison/msg-body",
                "the-morrison@inbound.lx-software.com",
                "morrison",
                None,
            ),
        )
        body = "Electricity total 88.10 HKD on 2 Nov 2026."
        for key, recipient, house, line_type in inboxes:
            with self.subTest(house=house):
                raw = _bill_message(body=body, to=recipient).as_bytes()
                out, s3, enq, meta = _run_inbound(key, raw)
                self.assertEqual(out, {"ok": True})
                enq.assert_called_once()
                kwargs = enq.call_args.kwargs
                self.assertEqual(kwargs["house"], house)
                self.assertEqual(kwargs["line_type_only"], line_type)
                self.assertEqual(kwargs["source"], "inbound_mail")
                self.assertEqual(len(kwargs["s3_keys"]), 1)
                self.assertTrue(kwargs["s3_keys"][0].endswith(f"_{BODY_FILENAME}"))
                self.assertEqual(len(s3.puts), 1)
                self.assertEqual(s3.puts[0]["ContentType"], "text/plain")
                self.assertIn(b"88.10", s3.puts[0]["Body"])
                self.assertEqual(meta.call_args.kwargs["house"], house)
                self.assertEqual(meta.call_args.kwargs["file_name"], BODY_FILENAME)
                self.assertEqual(s3.deleted, [("inbound-bucket", key)])

    def test_note_without_an_amount_is_not_parsed(self) -> None:
        key = "inbound-raw/lx-software/msg-empty"
        raw = _bill_message(body="Thanks.").as_bytes()
        out, s3, enq, meta = _run_inbound(key, raw)
        self.assertEqual(out, {"ok": True})
        enq.assert_not_called()
        meta.assert_not_called()
        self.assertEqual(s3.puts, [])
        self.assertEqual(s3.deleted, [])

    def test_pdf_upload_keeps_pdf_content_type_when_the_body_has_an_amount(self) -> None:
        key = "inbound-raw/hillmarton/msg-pdf"
        msg = _bill_message(
            body="Total USD 42.00 for hosting on 1 Nov 2026.",
            to="32-hillmarton@inbound.lx-software.com",
        )
        msg.add_attachment(
            b"%PDF-1.4 invoice",
            maintype="application",
            subtype="pdf",
            filename="invoice.pdf",
        )
        _out, s3, enq, _meta = _run_inbound(key, msg.as_bytes())
        enq.assert_called_once()
        self.assertEqual(enq.call_args.kwargs["house"], "hillmarton")
        self.assertIsNone(enq.call_args.kwargs["line_type_only"])
        self.assertEqual(len(s3.puts), 1)
        self.assertEqual(s3.puts[0]["ContentType"], "application/pdf")
        self.assertTrue(s3.puts[0]["Key"].endswith("_invoice.pdf"))
        self.assertEqual(s3.puts[0]["Body"], b"%PDF-1.4 invoice")


class TestRecordInboundAssetMeta(unittest.TestCase):
    def test_creates_meta_with_original_filename(self) -> None:
        import finance_store
        import runtime

        table = MagicMock()

        class _MissingMeta(finance_store.ClientError):
            def __init__(self) -> None:
                super().__init__(
                    {"Error": {"Code": "ConditionalCheckFailedException"}},
                    "UpdateItem",
                )
                self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}

        table.update_item.side_effect = _MissingMeta()
        stored: list[dict] = []

        def _put(**kwargs: Any) -> dict:
            stored.append(kwargs["Item"])
            return {}

        table.put_item.side_effect = _put
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = table
        env = {"RECORDS_TABLE_NAME": "records-test"}
        key = f"inbound/hillmarton/{'a' * 32}/00_January.pdf"
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(runtime, "_ddb", mock_ddb),
        ):
            _record_inbound_asset_meta(
                s3_key=key,
                house="hillmarton",
                file_name="January.pdf",
                size=99,
                owner_sub="inbound-email",
                request_id="req-1",
            )
        self.assertEqual(len(stored), 1)
        update_expr = table.update_item.call_args.kwargs["UpdateExpression"]
        self.assertIn("gsi1pk = if_not_exists(gsi1pk, :gpk)", update_expr)
        self.assertEqual(stored[0]["pk"], f"ASSET#{key}")
        self.assertEqual(stored[0]["fileName"], "January.pdf")
        self.assertEqual(stored[0]["house"], "hillmarton")
        self.assertEqual(stored[0]["size"], 99)
        self.assertEqual(stored[0]["gsi1pk"], "ASSET")
        self.assertTrue(str(stored[0]["gsi1sk"]).endswith(f"#{key}"))


if __name__ == "__main__":
    unittest.main()
