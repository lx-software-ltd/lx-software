"""Tests for Executive Board mail: PII masking, ingest, routes, tools, sending."""

from __future__ import annotations

import io
import json
import os
import unittest
from email.message import EmailMessage
from typing import Any
from unittest.mock import patch

import board_mail
import board_pii
import board_store
import board_tools
import inbound_email_handler
from dispatch import lambda_handler
from test_board import BoardTestCase, FakeTable
from test_board_tools import ToolsTestCase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_mail(
    *,
    frm: str = "Wendy Chan <wendy.chan@gmail.com>",
    to: str = "hello@siutindei.com",
    cc: str | None = None,
    subject: str = "Swimming class for my daughter",
    text: str | None = "Hi, does the Tuen Mun class have space on Saturdays? My number is 9123 4567.",
    html: str | None = None,
    message_id: str | None = "<abc123@mail.gmail.com>",
    in_reply_to: str | None = None,
    references: str | None = None,
    attachments: list[tuple[str, str, bytes]] | None = None,
    headers: dict[str, str] | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = frm
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg["Date"] = "Fri, 04 Sep 2026 10:15:00 +0800"
    if message_id:
        msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    for k, v in (headers or {}).items():
        msg[k] = v
    if text is not None:
        msg.set_content(text)
        if html is not None:
            msg.add_alternative(html, subtype="html")
    elif html is not None:
        msg.set_content(html, subtype="html")
    for name, ctype, payload in attachments or []:
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(payload, maintype=maintype, subtype=subtype, filename=name)
    return msg.as_bytes()


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.deleted: list[tuple[str, str]] = []

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def delete_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        self.deleted.append((Bucket, Key))
        self.objects.pop((Bucket, Key), None)
        return {}

    def put_object(self, **_: Any) -> dict[str, Any]:  # pragma: no cover - statement path only
        return {}


class FakeSES:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail_with: Exception | None = None
        self.identity: dict[str, Any] | Exception = {
            "VerifiedForSendingStatus": True,
            "DkimAttributes": {"Status": "SUCCESS"},
        }
        self.account: dict[str, Any] | Exception = {
            "ProductionAccessEnabled": True,
            "SendQuota": {"Max24HourSend": 50000.0, "SentLast24Hours": 12.0},
        }

    def send_email(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail_with:
            raise self.fail_with
        self.sent.append(kwargs)
        return {"MessageId": f"ses-{len(self.sent)}"}

    def get_email_identity(self, **kwargs: Any) -> dict[str, Any]:
        if isinstance(self.identity, Exception):
            raise self.identity
        return self.identity

    def get_account(self) -> dict[str, Any]:
        if isinstance(self.account, Exception):
            raise self.account
        return self.account

    def last_raw(self) -> EmailMessage:
        from email import policy
        from email.parser import BytesParser

        return BytesParser(policy=policy.default).parsebytes(self.sent[-1]["Content"]["Raw"]["Data"])


class MailTestCase(ToolsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.ses = FakeSES()
        patcher = patch.object(board_mail, "_ses_client", lambda: self.ses)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = {
            "BOARD_MAIL_SENDING_ENABLED": "true",
            "BOARD_MAIL_DOMAIN": "siutindei.com",
            "BOARD_MAIL_INBOUND_ADDRESS": "siutindei-board@inbound.lx-software.com",
        }
        patcher_env = patch.dict("os.environ", env, clear=False)
        patcher_env.start()
        self.addCleanup(patcher_env.stop)
        board_mail._health_cache = None  # noqa: SLF001
        self.addCleanup(setattr, board_mail, "_health_cache", None)

    def ingest(self, **kwargs: Any) -> dict[str, Any]:
        return board_mail.ingest_bytes(self.table, build_mail(**kwargs))


# ---------------------------------------------------------------------------
# PII
# ---------------------------------------------------------------------------

class TestPseudonymizer(BoardTestCase):
    def test_aliases_are_stable_and_persisted(self) -> None:
        p = board_pii.Pseudonymizer(self.table, own_domains={"siutindei.com"})
        first = p.alias_for_address("Wendy.Chan@gmail.com")
        again = p.alias_for_address("wendy.chan@gmail.com ")
        self.assertEqual(first, "contact#1")
        self.assertEqual(first, again)
        self.assertEqual(p.alias_for_address("other@example.org"), "contact#2")
        p.save()
        fresh = board_pii.Pseudonymizer(self.table, own_domains={"siutindei.com"})
        self.assertEqual(fresh.alias_for_address("wendy.chan@gmail.com"), "contact#1")
        self.assertEqual(fresh.resolve("contact#2"), "other@example.org")
        self.assertIsNone(fresh.resolve("contact#99"))

    def test_own_domain_addresses_are_not_masked(self) -> None:
        p = board_pii.Pseudonymizer(self.table, own_domains={"siutindei.com"})
        self.assertEqual(p.alias_for_address("hello@siutindei.com"), "hello@siutindei.com")
        masked = p.mask_text("Write to hello@siutindei.com or wendy@gmail.com, call +852 9123 4567 or 2345 6789.")
        self.assertIn("hello@siutindei.com", masked)
        self.assertNotIn("wendy@gmail.com", masked)
        self.assertNotIn("9123 4567", masked)
        self.assertNotIn("2345 6789", masked)
        self.assertIn("contact#1", masked)
        self.assertIn("phone#2", masked)
        self.assertIn("phone#3", masked)
        # Dates and amounts survive.
        self.assertEqual(p.mask_text("Invoice 2026-09-04 for HKD 1,250.00"), "Invoice 2026-09-04 for HKD 1,250.00")

    def test_unmask_round_trip(self) -> None:
        p = board_pii.Pseudonymizer(self.table, own_domains={"siutindei.com"})
        masked = p.mask_text("Dear wendy@gmail.com")
        self.assertEqual(p.unmask_text(masked), "Dear wendy@gmail.com")
        self.assertEqual(p.resolve("wendy@gmail.com"), "wendy@gmail.com")


# ---------------------------------------------------------------------------
# Parsing and ingest
# ---------------------------------------------------------------------------

class TestParseAndIngest(MailTestCase):
    def test_parse_html_only_and_attachments(self) -> None:
        raw = build_mail(
            text=None,
            html="<html><body><p>Hello <b>there</b></p><p>Price list attached.</p><script>x()</script></body></html>",
            attachments=[("prices.pdf", "application/pdf", b"%PDF-1.4 fake"), ("list.csv", "text/csv", b"a,b\n1,2\n")],
        )
        parsed = board_mail.parse_mime(raw)
        self.assertEqual(parsed.text, "Hello there\nPrice list attached.")
        self.assertEqual(parsed.mailbox, "hello@siutindei.com")
        self.assertEqual(parsed.from_address, "wendy.chan@gmail.com")
        self.assertEqual(parsed.from_name, "Wendy Chan")
        self.assertEqual([a["name"] for a in parsed.attachments], ["prices.pdf", "list.csv"])
        self.assertEqual(parsed.attachments[1]["text"], "a,b\n1,2\n")
        self.assertNotIn("text", parsed.attachments[0])
        # No local PDF text extractor in the Lambda bundle: PDFs are named, not read.
        self.assertEqual(parsed.attachments_skipped, ["prices.pdf"])
        self.assertFalse(parsed.truncated)
        self.assertEqual(parsed.date, "2026-09-04T02:15:00.000Z")

    def test_mailbox_detection_prefers_delivery_headers(self) -> None:
        raw = build_mail(to="parents-list@googlegroups.com", headers={"X-Original-To": "Billing@SiuTinDei.com"})
        self.assertEqual(board_mail.parse_mime(raw).mailbox, "billing@siutindei.com")
        raw = build_mail(to="someone@else.com", cc="Finance <finance@siutindei.com>")
        self.assertEqual(board_mail.parse_mime(raw).mailbox, "finance@siutindei.com")
        raw = build_mail(to="someone@else.com")
        self.assertEqual(board_mail.parse_mime(raw).mailbox, "unknown@siutindei.com")

    def test_normalize_subject_strips_reply_prefixes(self) -> None:
        self.assertEqual(board_mail.normalize_subject("RE: Fwd:  Re[2]: Swimming  class"), "swimming class")
        self.assertEqual(board_mail.normalize_subject(""), "")

    def test_ingest_threads_by_references_then_subject(self) -> None:
        first = self.ingest()
        self.assertFalse(first["duplicate"])
        reply = self.ingest(
            frm="hello@siutindei.com",
            to="wendy.chan@gmail.com",
            subject="Re: Swimming class for my daughter",
            text="Yes, two places left.",
            message_id="<r1@siutindei.com>",
            in_reply_to="<abc123@mail.gmail.com>",
        )
        self.assertEqual(reply["threadId"], first["threadId"])
        # No References headers, same normalised subject and counterpart → same thread.
        follow_up = self.ingest(
            subject="RE: Swimming class for my daughter",
            text="Great, booking two.",
            message_id="<abc124@mail.gmail.com>",
        )
        self.assertEqual(follow_up["threadId"], first["threadId"])
        other = self.ingest(subject="Invoice query", to="billing@siutindei.com", message_id="<z9@x.com>")
        self.assertNotEqual(other["threadId"], first["threadId"])

        threads = board_store.list_mail_threads(self.table)
        self.assertEqual(len(threads), 2)
        main = next(t for t in threads if t["threadId"] == first["threadId"])
        self.assertEqual(main["messageCount"], 3)
        self.assertEqual(main["mailbox"], "hello@siutindei.com")
        self.assertEqual(main["participants"], ["wendy.chan@gmail.com"])
        self.assertTrue(main["unread"])
        self.assertEqual(main["snippet"], "Great, booking two.")
        messages = board_store.list_mail_messages(self.table, first["threadId"])
        self.assertEqual([m["direction"] for m in messages], ["in", "in", "in"])
        self.assertEqual(messages[0]["from"], {"address": "wendy.chan@gmail.com", "name": "Wendy Chan"})

    def test_duplicate_message_id_is_skipped(self) -> None:
        first = self.ingest()
        again = self.ingest()
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["threadId"], first["threadId"])
        self.assertEqual(board_store.get_mail_thread(self.table, first["threadId"])["messageCount"], 1)

    def test_inbound_handler_routes_board_prefix_and_deletes_raw(self) -> None:
        s3 = FakeS3()
        key = "inbound-raw/siutindei/abcdef"
        s3.objects[("inbound-bucket", key)] = build_mail()
        event = {
            "Records": [
                {
                    "eventSource": "aws:s3",
                    "s3": {"bucket": {"name": "inbound-bucket"}, "object": {"key": key}},
                }
            ]
        }
        env = {"INBOUND_MAIL_BUCKET_NAME": "inbound-bucket", "ASSETS_BUCKET_NAME": "assets", "INBOUND_RAW_MAIL_PREFIX": "inbound-raw"}
        with patch.dict(os.environ, env), patch.object(inbound_email_handler, "_s3", s3):
            out = inbound_email_handler.lambda_handler(event, None)
        self.assertEqual(out, {"ok": True})
        self.assertEqual(s3.deleted, [("inbound-bucket", key)])
        threads = board_store.list_mail_threads(self.table)
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["subject"], "Swimming class for my daughter")
        self.assertTrue(inbound_email_handler.is_board_mail_s3_key(ses_drop_path=key, raw_mail_prefix="inbound-raw"))
        self.assertFalse(
            inbound_email_handler.is_board_mail_s3_key(ses_drop_path="inbound-raw/hillmarton/x", raw_mail_prefix="inbound-raw")
        )
        self.assertIsNone(
            inbound_email_handler.house_key_from_raw_mail_s3_key(ses_drop_path=key, raw_mail_prefix="inbound-raw")
        )


# ---------------------------------------------------------------------------
# Owner routes
# ---------------------------------------------------------------------------

class TestMailRoutes(MailTestCase):
    def seed(self) -> tuple[str, str]:
        a = self.ingest()["threadId"]
        b = self.ingest(
            frm="Coach Lam <lam@swimhk.example>",
            to="providers@siutindei.com",
            subject="Listing photos",
            text="Attached are our new photos.",
            message_id="<p1@swimhk.example>",
        )["threadId"]
        return a, b

    def test_list_filters_and_mailbox_counts(self) -> None:
        a, b = self.seed()
        status, body = self.call("/siu-tin-dei/board/mail")
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 2)
        self.assertEqual({t["threadId"] for t in body["threads"]}, {a, b})
        self.assertEqual(
            [{k: v for k, v in m.items() if k != "lastMessageAt"} for m in body["mailboxes"]],
            [
                {"address": "hello@siutindei.com", "threadCount": 1, "unreadCount": 1},
                {"address": "providers@siutindei.com", "threadCount": 1, "unreadCount": 1},
            ],
        )
        self.assertTrue(all(m["lastMessageAt"] for m in body["mailboxes"]))
        self.assertEqual(body["status"]["unreadCount"], 2)
        self.assertTrue(body["status"]["sendEnabled"])
        # The list carries live SES health so "sending on" means something.
        health = body["status"]["sendHealth"]
        self.assertTrue(health["identityVerified"])
        self.assertEqual(health["dkimStatus"], "SUCCESS")
        self.assertTrue(health["productionAccess"])
        self.assertEqual(health["dailyQuota"], 50000)
        self.assertEqual(health["errors"], [])
        # The owner sees real addresses.
        self.assertIn("wendy.chan@gmail.com", [t["lastFrom"] for t in body["threads"]])

        status, body = self.call("/siu-tin-dei/board/mail", query="mailbox=providers%40siutindei.com")
        self.assertEqual([t["threadId"] for t in body["threads"]], [b])
        status, body = self.call("/siu-tin-dei/board/mail", query="q=swimming+daughter")
        self.assertEqual([t["threadId"] for t in body["threads"]], [a])
        status, body = self.call("/siu-tin-dei/board/mail", query="q=lam")
        self.assertEqual([t["threadId"] for t in body["threads"]], [b])

    def test_send_health_reports_unverified_identity_and_read_denials(self) -> None:
        from botocore.exceptions import ClientError

        self.ses.identity = {"VerifiedForSendingStatus": False, "DkimAttributes": {"Status": "PENDING"}}
        self.ses.account = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "not authorized to perform ses:GetAccount"}},
            "GetAccount",
        )
        health = board_mail.sending_health(force=True)
        self.assertFalse(health["identityVerified"])
        self.assertEqual(health["dkimStatus"], "PENDING")
        self.assertIsNone(health["productionAccess"])
        self.assertEqual(len(health["errors"]), 1)
        self.assertIn("GetAccount: AccessDeniedException", health["errors"][0])
        # Cached: a fixed account is not visible until the TTL passes or force=True.
        self.ses.account = {"ProductionAccessEnabled": True}
        self.assertIsNone(board_mail.sending_health()["productionAccess"])
        self.assertTrue(board_mail.sending_health(force=True)["productionAccess"])
        # Sending switched off short-circuits without calling SES.
        with patch.dict(os.environ, {"BOARD_MAIL_SENDING_ENABLED": "false"}):
            off = board_mail.sending_health(force=True)
        self.assertIsNone(off["identityVerified"])
        self.assertIn("switched off", off["errors"][0])

    def test_selftest_sends_to_the_signed_in_owner_without_indexing(self) -> None:
        ev = self.event("/siu-tin-dei/board/mail/selftest", "POST", {})
        ev["requestContext"]["authorizer"]["jwt"]["claims"]["email"] = "Owner@Example.com"
        out = lambda_handler(ev, None)
        body = json.loads(out["body"])
        self.assertEqual(out["statusCode"], 200, body)
        self.assertTrue(body["ok"])
        self.assertEqual(body["to"], "owner@example.com")
        self.assertEqual(body["from"], "hello@siutindei.com")
        self.assertEqual(body["sesMessageId"], "ses-1")
        self.assertTrue(body["health"]["identityVerified"])
        sent = self.ses.sent[0]
        self.assertEqual(sent["FromEmailAddress"], "hello@siutindei.com")
        self.assertEqual(sent["Destination"]["ToAddresses"], ["owner@example.com"])
        raw = self.ses.last_raw()
        self.assertEqual(raw["Subject"], board_mail.SELFTEST_SUBJECT)
        self.assertIn("hello@siutindei.com", raw.get_content())
        # A test never lands in the company mail index.
        self.assertEqual(board_store.list_mail_threads(self.table), [])

    def test_selftest_surfaces_the_ses_refusal(self) -> None:
        from botocore.exceptions import ClientError

        deny = (
            "User: arn:aws:sts::588024549699:assumed-role/lxsoftware-AdminApiFnServiceRole3DBF280A-R5kCD57g90Z1/"
            "lxsoftware-AdminApiFnA81506EE-Dtien8OG6FVk is not authorized to perform: ses:SendRawEmail on resource: "
            "arn:aws:ses:ap-southeast-1:588024549699:identity/hello@siutindei.com because no identity-based policy "
            "allows the ses:SendRawEmail action"
        )
        self.ses.fail_with = ClientError({"Error": {"Code": "AccessDeniedException", "Message": deny}}, "SendEmail")
        ev = self.event("/siu-tin-dei/board/mail/selftest", "POST", {})
        ev["requestContext"]["authorizer"]["jwt"]["claims"]["email"] = "owner@example.com"
        out = lambda_handler(ev, None)
        body = json.loads(out["body"])
        self.assertEqual(out["statusCode"], 502)
        self.assertIn("AccessDeniedException", body["message"])
        # The resource ARN survives: it is the field the earlier 300-char cap lost.
        self.assertIn("identity/hello@siutindei.com", body["message"])
        self.assertIn("health", body)
        code, detail, resource = board_mail.describe_ses_error(self.ses.fail_with)
        self.assertEqual(code, "AccessDeniedException")
        self.assertEqual(resource, "arn:aws:ses:ap-southeast-1:588024549699:identity/hello@siutindei.com")
        self.assertIn("because no identity-based policy", detail)

        # No email claim: refused before SES is called.
        self.ses.fail_with = None
        status, body = self.call("/siu-tin-dei/board/mail/selftest", "POST", {})
        self.assertEqual(status, 502)
        self.assertIn("no usable email", body["message"])
        self.assertEqual(self.ses.sent, [])

    def test_thread_detail_owner_and_board_views(self) -> None:
        a, _ = self.seed()
        status, body = self.call(f"/siu-tin-dei/board/mail/{a}")
        self.assertEqual(status, 200)
        self.assertEqual(body["thread"]["threadId"], a)
        self.assertEqual(len(body["messages"]), 1)
        self.assertIn("9123 4567", body["messages"][0]["text"])
        self.assertEqual(body["messages"][0]["from"]["address"], "wendy.chan@gmail.com")

        status, masked = self.call(f"/siu-tin-dei/board/mail/{a}", query="view=board")
        self.assertEqual(status, 200)
        self.assertEqual(masked["messages"][0]["from"], "contact#1")
        self.assertNotIn("9123 4567", masked["messages"][0]["text"])
        self.assertIn("phone#2", masked["messages"][0]["text"])
        self.assertEqual(masked["messages"][0]["to"], ["hello@siutindei.com"])

        self.assertEqual(self.call("/siu-tin-dei/board/mail/deadbeefdeadbeef")[0], 404)
        self.assertEqual(self.call("/siu-tin-dei/board/mail/not-a-thread!")[0], 404)

    def test_mark_read_and_overview_counts(self) -> None:
        a, _ = self.seed()
        status, overview = self.call("/siu-tin-dei/board")
        self.assertEqual(overview["unreadMailCount"], 2)
        self.assertEqual(overview["mail"]["threadCount"], 2)
        status, body = self.call(f"/siu-tin-dei/board/mail/{a}/read", "POST", {})
        self.assertEqual(status, 200)
        self.assertFalse(body["thread"]["unread"])
        self.assertEqual(self.call("/siu-tin-dei/board")[1]["unreadMailCount"], 1)
        status, body = self.call(f"/siu-tin-dei/board/mail/{a}/read", "POST", {"read": False})
        self.assertTrue(body["thread"]["unread"])
        self.assertEqual(self.call(f"/siu-tin-dei/board/mail/{a}/read", "POST", {"read": "yes"})[0], 400)
        self.assertEqual(self.call("/siu-tin-dei/board/mail/deadbeefdeadbeef/read", "POST", {})[0], 404)

    def test_allow_list_validation_and_normalisation(self) -> None:
        status, body = self.call(
            "/siu-tin-dei/board/tools",
            "PUT",
            {"allowList": [" Coach@SwimHK.example ", "@Vendor.example", "coach@swimhk.example", ""]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["config"]["allowList"], ["coach@swimhk.example", "@vendor.example"])
        self.assertEqual(body["mailDomain"], "siutindei.com")
        self.assertTrue(body["mailSendEnabled"])
        status, body = self.call(
            "/siu-tin-dei/board/tools",
            "PUT",
            {"allowList": ["coach@swimhk.example", "@vendor.example", "+852 9123 4567"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["config"]["allowList"], ["coach@swimhk.example", "@vendor.example", "+85291234567"])
        status, body = self.call("/siu-tin-dei/board/tools", "PUT", {"allowList": ["not-an-address"]})
        self.assertEqual(status, 400)
        self.assertIn("not-an-address", body["message"])
        status, body = self.call("/siu-tin-dei/board/tools", "PUT", {"allowList": "coach@swimhk.example"})
        self.assertEqual(status, 400)
        # Untouched by a matrix-only update.
        status, body = self.call("/siu-tin-dei/board/tools", "PUT", {"matrix": {"mail": {"cpo": "propose"}}})
        self.assertEqual(body["config"]["allowList"], ["coach@swimhk.example", "@vendor.example", "+85291234567"])
        self.assertEqual(body["config"]["matrix"]["mail"]["cpo"], "propose")

    def test_context_pack_mentions_unread_counts_only(self) -> None:
        import board_context
        import board_personas

        self.seed()
        settings = board_store.load_settings(self.table)
        pack = board_context.build_context_pack(self.table, settings, roster=board_personas.effective_roster({}))
        self.assertEqual(pack["mail"]["unreadCount"], 2)
        self.assertIn("Company email: 2 threads indexed, 2 unread", pack["text"])
        self.assertNotIn("wendy", pack["text"].lower())
        self.assertNotIn("Swimming class", pack["text"])


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class TestMailTools(MailTestCase):
    def seed_thread(self) -> str:
        return self.ingest()["threadId"]

    def offered(self, persona: str, context: str = "chat") -> set[str]:
        settings = board_store.load_settings(self.table)
        return {op.name for op, _lvl in board_tools.available_ops(settings, persona, context=context)}

    def test_default_matrix_offers_mail_by_role(self) -> None:
        self.assertIn("mail_reply", self.offered("coo"))
        self.assertIn("mail_list_threads", self.offered("cpo"))
        self.assertNotIn("mail_reply", self.offered("cpo"))
        self.assertIn("mail_reply", self.offered("ceo"))  # propose
        self.assertIn("mail_send", self.offered("cmo"))
        self.call("/siu-tin-dei/board/tools", "PUT", {"matrix": {"mail": {"cto": "off"}}})
        self.assertFalse({n for n in self.offered("cto") if n.startswith("mail_")})

    def test_read_tools_return_masked_data(self) -> None:
        thread_id = self.seed_thread()
        scripted = self.use_script(
            [[("mail_list_threads", {"unreadOnly": True})], [("mail_get_thread", {"threadId": thread_id})]],
            "One unread enquiry from contact#1 about Saturday swimming.",
        )
        job = self.chat("coo", "Anything new in the inbox?")
        self.assertEqual(job["status"], "succeeded")
        calls = job["message"]["toolCalls"]
        self.assertEqual([c["op"] for c in calls], ["mail_list_threads", "mail_get_thread"])
        self.assertTrue(all(c["status"] == "ok" for c in calls))
        self.assertEqual(calls[0]["toolLabel"], "Email")
        listing = json.loads(scripted.requests[1]["messages"][-1]["content"])
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["items"][0]["lastFrom"], "contact#1")
        self.assertEqual(listing["items"][0]["participants"], ["contact#1"])
        detail = json.loads(scripted.requests[2]["messages"][-1]["content"])
        self.assertEqual(detail["messages"][0]["from"], "contact#1")
        self.assertNotIn("wendy", json.dumps(detail).lower())
        self.assertNotIn("9123", json.dumps(detail))
        self.assertIn("phone#2", detail["messages"][0]["text"])

    def test_reply_at_act_to_unlisted_recipient_becomes_approval_with_preview(self) -> None:
        thread_id = self.seed_thread()
        self.call("/siu-tin-dei/board/tools", "PUT", {"globalMode": "act"})
        self.use_script(
            [[("mail_reply", {"threadId": thread_id, "body": "Dear contact#1,\n\nYes, two places are left on Saturday.\n\nThe siutindei team", "reason": "Enquiry waiting 1 day"})]],
            "I have proposed a reply for your approval.",
        )
        job = self.chat("coo", "Reply to the swimming enquiry.")
        call = job["message"]["toolCalls"][0]
        self.assertEqual(call["status"], "pending_approval")
        self.assertEqual(self.ses.sent, [])
        status, body = self.call("/siu-tin-dei/board/approvals")
        approval = body["approvals"][0]
        self.assertEqual(approval["op"], "mail_reply")
        self.assertIn("contact#1", approval["downgradeReason"])
        preview = approval["preview"]
        self.assertEqual(preview["from"], "hello@siutindei.com")
        self.assertEqual(preview["to"], ["wendy.chan@gmail.com"])
        self.assertEqual(preview["subject"], "Re: Swimming class for my daughter")
        self.assertIn("Dear wendy.chan@gmail.com", preview["text"])
        self.assertTrue(preview["sendEnabled"])

        status, body = self.call(f"/siu-tin-dei/board/approvals/{approval['approvalId']}/approve", "POST", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["approval"]["status"], "executed")
        self.assertEqual(len(self.ses.sent), 1)
        sent = self.ses.sent[0]
        self.assertEqual(sent["Destination"]["ToAddresses"], ["wendy.chan@gmail.com"])
        self.assertEqual(sent["FromEmailAddress"], "hello@siutindei.com")
        self.assertNotIn("FromEmailAddressIdentityArn", sent)
        raw = self.ses.last_raw()
        self.assertIn("hello@siutindei.com", raw["From"])
        self.assertEqual(raw["In-Reply-To"], "<abc123@mail.gmail.com>")
        self.assertIn("<abc123@mail.gmail.com>", raw["References"])
        self.assertEqual(raw["Subject"], "Re: Swimming class for my daughter")
        self.assertIn("Dear wendy.chan@gmail.com", raw.get_content())
        # Outbound copy is indexed into the same thread and the thread is marked read.
        messages = board_store.list_mail_messages(self.table, thread_id)
        self.assertEqual([m["direction"] for m in messages], ["in", "out"])
        self.assertEqual(messages[1]["mailbox"], "hello@siutindei.com")
        thread = board_store.get_mail_thread(self.table, thread_id)
        self.assertFalse(thread["unread"])
        self.assertEqual(thread["messageCount"], 2)
        # The result handed back to the model is masked again.
        self.assertEqual(body["approval"]["result"]["to"], ["contact#1"])

    def test_reply_at_act_to_allow_listed_recipient_sends_immediately(self) -> None:
        thread_id = self.seed_thread()
        self.call("/siu-tin-dei/board/tools", "PUT", {"globalMode": "act", "allowList": ["@gmail.com"]})
        self.use_script([[("mail_reply", {"threadId": thread_id, "body": "Two places left.", "reason": "r"})]], "Sent.")
        job = self.chat("coo")
        call = job["message"]["toolCalls"][0]
        self.assertEqual(call["status"], "ok")
        self.assertEqual(len(self.ses.sent), 1)
        status, body = self.call("/siu-tin-dei/board/approvals")
        self.assertEqual(body["approvals"], [])

    def test_propose_level_records_approval_without_guard(self) -> None:
        thread_id = self.seed_thread()
        self.use_script([[("mail_reply", {"threadId": thread_id, "body": "Hello", "reason": "r"})]], "Proposed.")
        job = self.chat("ceo")
        call = job["message"]["toolCalls"][0]
        self.assertEqual(call["status"], "pending_approval")
        approval = self.call("/siu-tin-dei/board/approvals")[1]["approvals"][0]
        self.assertNotIn("downgradeReason", approval)
        self.assertEqual(approval["preview"]["to"], ["wendy.chan@gmail.com"])

    def test_send_new_mail_with_alias_and_owner_edit(self) -> None:
        self.seed_thread()
        # Learn the alias by reading first.
        board_mail.masked_thread_detail(self.table, board_store.list_mail_threads(self.table)[0]["threadId"])
        self.use_script(
            [[("mail_send", {"fromMailbox": "billing", "to": ["contact#1"], "subject": "Invoice 0042", "body": "Please find your invoice.", "reason": "r"})]],
            "Proposed.",
        )
        job = self.chat("cfo")
        self.assertEqual(job["message"]["toolCalls"][0]["status"], "pending_approval")
        approval = self.call("/siu-tin-dei/board/approvals")[1]["approvals"][0]
        self.assertEqual(approval["preview"]["from"], "billing@siutindei.com")
        self.assertEqual(approval["preview"]["to"], ["wendy.chan@gmail.com"])
        status, body = self.call(
            f"/siu-tin-dei/board/approvals/{approval['approvalId']}/approve",
            "POST",
            {"arguments": {"body": "Please find invoice 0042 attached to the portal."}},
        )
        self.assertEqual(body["approval"]["status"], "executed")
        self.assertIn("portal", body["approval"]["preview"]["text"])
        raw = self.ses.last_raw()
        self.assertEqual(raw["Subject"], "Invoice 0042")
        self.assertIn("portal", raw.get_content())
        threads = board_store.list_mail_threads(self.table)
        new_thread = next(t for t in threads if t["subject"] == "Invoice 0042")
        self.assertEqual(new_thread["mailbox"], "billing@siutindei.com")
        self.assertFalse(new_thread["unread"])

    def test_forward_quotes_last_message(self) -> None:
        thread_id = self.seed_thread()
        self.call("/siu-tin-dei/board/tools", "PUT", {"globalMode": "act", "allowList": ["coach@swimhk.example"]})
        self.use_script(
            [[("mail_forward", {"threadId": thread_id, "to": ["coach@swimhk.example"], "note": "Can you take two more on Saturday?", "reason": "r"})]],
            "Forwarded.",
        )
        job = self.chat("coo")
        self.assertEqual(job["message"]["toolCalls"][0]["status"], "ok")
        raw = self.ses.last_raw()
        self.assertEqual(raw["Subject"], "Fwd: Swimming class for my daughter")
        self.assertEqual(self.ses.sent[0]["Destination"]["ToAddresses"], ["coach@swimhk.example"])
        content = raw.get_content()
        self.assertIn("Can you take two more", content)
        self.assertIn("> Hi, does the Tuen Mun class", content)

    def test_errors_are_reported_to_the_model(self) -> None:
        thread_id = self.seed_thread()
        self.call("/siu-tin-dei/board/tools", "PUT", {"globalMode": "act", "allowList": ["@gmail.com"]})
        scripted = self.use_script(
            [
                [
                    ("mail_reply", {"threadId": "0000000000", "body": "x", "reason": "r"}),
                    ("mail_send", {"fromMailbox": "hello", "to": ["contact#77"], "subject": "s", "body": "b", "reason": "r"}),
                    ("mail_send", {"fromMailbox": "ceo@other.com", "to": ["a@b.co"], "subject": "s", "body": "b", "reason": "r"}),
                ]
            ],
            "Could not send.",
        )
        job = self.chat("coo")
        calls = job["message"]["toolCalls"]
        self.assertEqual([c["status"] for c in calls], ["error", "error", "error"])
        self.assertIn("not found", calls[0]["error"])
        self.assertIn("Unknown contact", calls[1]["error"])
        self.assertIn("siutindei.com mailbox", calls[2]["error"])
        self.assertEqual(self.ses.sent, [])
        # Sending switched off: the executor explains instead of failing.
        with patch.dict(os.environ, {"BOARD_MAIL_SENDING_ENABLED": "false"}):
            self.use_script([[("mail_reply", {"threadId": thread_id, "body": "x", "reason": "r"})]], "Off.")
            job = self.chat("coo")
        self.assertEqual(job["message"]["toolCalls"][0]["status"], "error")
        self.assertIn("switched off", job["message"]["toolCalls"][0]["error"])
        self.assertEqual(len(scripted.requests), 2)

    def test_ses_access_denied_becomes_mail_error(self) -> None:
        from botocore.exceptions import ClientError

        thread_id = self.seed_thread()
        self.call("/siu-tin-dei/board/tools", "PUT", {"globalMode": "act", "allowList": ["@gmail.com"]})
        self.ses.fail_with = ClientError(
            {
                "Error": {
                    "Code": "AccessDeniedException",
                    "Message": "not authorized to perform ses:SendRawEmail on identity/hello@siutindei.com",
                }
            },
            "SendEmail",
        )
        self.use_script([[("mail_reply", {"threadId": thread_id, "body": "x", "reason": "r"})]], "Failed.")
        job = self.chat("coo")
        call = job["message"]["toolCalls"][0]
        self.assertEqual(call["status"], "error")
        self.assertIn("SES refused to send", call["error"])
        self.assertIn("AccessDeniedException", call["error"])
        self.assertEqual(self.ses.sent, [])

    def test_contact_history(self) -> None:
        self.seed_thread()
        self.ingest(subject="Second question", message_id="<abc999@mail.gmail.com>", to="billing@siutindei.com")
        settings = board_store.load_settings(self.table)
        ctx = board_tools.ToolContext(table=self.table, settings=settings, persona_id="coo")
        board_tools.execute_call(ctx, board_tools.REGISTRY["mail_list_threads"], {})
        out = board_tools.execute_call(ctx, board_tools.REGISTRY["mail_contact_history"], {"contact": "contact#1"})
        self.assertEqual(out.status, "ok")
        self.assertEqual(out.result["threadCount"], 2)
        bad = board_tools.execute_call(ctx, board_tools.REGISTRY["mail_contact_history"], {"contact": "contact#9"})
        self.assertEqual(bad.status, "error")


if __name__ == "__main__":
    unittest.main()
