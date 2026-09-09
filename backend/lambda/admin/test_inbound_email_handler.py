"""Tests for inbound SES mail PDF extraction."""

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
    extract_first_pdf_attachment,
    extract_pdf_attachments,
    house_key_from_raw_mail_s3_key,
    inbound_mailbox_from_raw_s3_key,
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
        s3.objects[("inbound-bucket", key)] = _pdf_mail(
            to="32-hillmarton@inbound.lx-software.com"
        )
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


class TestRecordInboundAssetMeta(unittest.TestCase):
    def test_creates_meta_with_original_filename(self) -> None:
        import runtime
        from botocore.exceptions import ClientError

        table = MagicMock()
        table.update_item.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException"}},
            "UpdateItem",
        )
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
        self.assertEqual(stored[0]["pk"], f"ASSET#{key}")
        self.assertEqual(stored[0]["fileName"], "January.pdf")
        self.assertEqual(stored[0]["house"], "hillmarton")
        self.assertEqual(stored[0]["size"], 99)


if __name__ == "__main__":
    unittest.main()
