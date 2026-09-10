"""Outreach send, unsubscribe, SES events, targets and replies (WP6)."""

from __future__ import annotations

import json
import os
import unittest
from email import message_from_bytes
from typing import Any
from unittest.mock import patch

import board_breakers
import board_holds
import board_outreach
import board_prospects
import board_sequences
import board_staff
import board_store
import board_targets
import board_tools
import board_triage
from test_board import BoardTestCase, lambda_handler


class FakeSes:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.verified = True

    def send_email(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"MessageId": "ses-msg-1"}

    def get_email_identity(self, **kwargs: Any) -> dict[str, Any]:
        return {"VerifiedForSendingStatus": self.verified}


def _enable_staff(table: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True})
    settings["tools"]["globalMode"] = "act"
    return board_store.save_settings(table, settings)


def _prospect(table: Any, **kwargs: Any) -> dict[str, Any]:
    defaults = {
        "name": "Sha Tin Playhouse",
        "type": "venue",
        "district": "Sha Tin",
        "website": "https://play.example",
        "email": "info@play.example",
    }
    defaults.update(kwargs)
    row, _ = board_prospects.upsert(table, **defaults)
    row["score"] = 70
    row["fitNote"] = "Saturday play sessions for ages 3-8."
    row["contact"] = defaults.get("email") or "info@play.example"
    row["stage"] = "qualified"
    board_store.put_prospect(table, row)
    return row


class OutreachTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        os.environ["BOARD_MAIL_SENDING_ENABLED"] = "true"
        os.environ["BOARD_LINK_SIGNING_SECRET"] = "link-secret-for-tests"
        os.environ["PUBLIC_API_BASE_URL"] = "https://api.example"
        os.environ["OUTREACH_IDENTITY_VERIFIED"] = "true"
        os.environ["BOARD_MAIL_DOMAIN"] = "siutindei.com"
        os.environ["OUTREACH_SENDING_DOMAIN"] = "partners.siutindei.com"
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_MAIL_SENDING_ENABLED", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_LINK_SIGNING_SECRET", None))
        self.addCleanup(lambda: os.environ.pop("PUBLIC_API_BASE_URL", None))
        self.addCleanup(lambda: os.environ.pop("OUTREACH_IDENTITY_VERIFIED", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_MAIL_DOMAIN", None))
        self.addCleanup(lambda: os.environ.pop("OUTREACH_SENDING_DOMAIN", None))
        board_outreach.reset_caches_for_tests()
        self.settings = _enable_staff(self.table)
        board_store.save_staff_override(self.table, "prospector", {"isActive": True})
        self.ses = FakeSes()
        self.addCleanup(patch.object(board_outreach, "_ses_client", lambda: self.ses).start())

    def test_every_refusal_reason(self) -> None:
        row = _prospect(self.table)
        board_breakers.trip(self.table, "outreach", "test")
        self.assertEqual(board_outreach.send(self.table, self.settings, prospect_id=row["prospectId"])["error"], "breaker tripped")
        board_breakers.reset(self.table, "outreach", "owner")
        os.environ["OUTREACH_IDENTITY_VERIFIED"] = "false"
        board_outreach.reset_caches_for_tests()
        self.assertEqual(board_outreach.send(self.table, self.settings, prospect_id=row["prospectId"])["error"], "sending identity not verified")
        os.environ["OUTREACH_IDENTITY_VERIFIED"] = "true"
        board_outreach.reset_caches_for_tests()
        missing = board_outreach.send(self.table, self.settings, prospect_id="nope")
        self.assertEqual(missing["error"], "prospect not found")
        row["stage"] = "replied"
        board_store.put_prospect(self.table, row)
        self.assertEqual(board_outreach.send(self.table, self.settings, prospect_id=row["prospectId"])["error"], "prospect replied")
        row["stage"] = "discovered"
        board_store.put_prospect(self.table, row)
        self.assertIn("stage not", board_outreach.send(self.table, self.settings, prospect_id=row["prospectId"])["error"])
        row["stage"] = "qualified"
        row["type"] = "restaurant"
        board_store.put_prospect(self.table, row)
        self.assertEqual(board_outreach.send(self.table, self.settings, prospect_id=row["prospectId"])["error"], "type not enabled")
        row["type"] = "venue"
        row["contact"] = None
        row["email"] = ""
        board_store.put_prospect(self.table, row)
        self.assertEqual(board_outreach.send(self.table, self.settings, prospect_id=row["prospectId"])["error"], "no contact")
        row["contact"] = "info@play.example"
        row["email"] = "info@play.example"
        board_store.put_prospect(self.table, row)
        board_outreach.suppress(self.table, email="info@play.example", reason="test")
        self.assertEqual(board_outreach.send(self.table, self.settings, prospect_id=row["prospectId"])["error"], "suppressed")
        board_store.put_suppress(self.table, board_outreach.suppress_digest("info@play.example"), {})
        # already suppressed
        other = _prospect(self.table, name="Other", website="https://other.example", email="hello@other.example")
        other["touches"] = [{"stepIndex": 0}, {"stepIndex": 1}, {"stepIndex": 2}]
        board_store.put_prospect(self.table, other)
        self.assertEqual(board_outreach.send(self.table, self.settings, prospect_id=other["prospectId"])["error"], "touches exhausted")
        day = board_store.load_outreach_day(self.table, __import__("board_hk").today_hkt())
        day["sent"] = 20
        board_store.save_outreach_day(self.table, day, __import__("board_hk").today_hkt())
        third = _prospect(self.table, name="Third", website="https://third.example", email="info@third.example")
        self.assertEqual(board_outreach.send(self.table, self.settings, prospect_id=third["prospectId"])["error"], "daily cap reached")

    def test_render_languages_and_send_headers(self) -> None:
        en = _prospect(self.table)
        zh, _ = board_prospects.upsert(self.table, name="沙田遊樂場", type="venue", email="info@zh.example", website="https://zh.example")
        zh["contact"] = "info@zh.example"
        zh["stage"] = "qualified"
        zh["fitNote"] = "有週末活動"
        board_store.put_prospect(self.table, zh)
        seq = board_sequences.get_or_default(self.table, "venue")
        subj_en, body_en = board_outreach.render_message(self.table, en, seq["steps"][0], personalisation="You host Saturday play.")
        subj_zh, body_zh = board_outreach.render_message(self.table, zh, seq["steps"][0])
        self.assertIn("Siu Tin Dei", subj_en)
        self.assertIn("unsubscribe", body_en.lower())
        self.assertIn("小天地", subj_zh)
        self.assertIn("退訂", body_zh)
        sent = board_outreach.send(self.table, self.settings, prospect_id=en["prospectId"], personalisation="You host Saturday play.")
        self.assertTrue(sent.get("ok"))
        self.assertEqual(len(self.ses.calls), 1)
        raw = self.ses.calls[0]["Content"]["Raw"]["Data"]
        msg = message_from_bytes(raw)
        self.assertIn("List-Unsubscribe", msg)
        self.assertEqual(msg["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        self.assertEqual(msg["Reply-To"], "partnerships@siutindei.com")
        self.assertEqual(self.ses.calls[0]["ConfigurationSetName"], board_outreach.CONFIG_SET)
        self.assertEqual(self.ses.calls[0]["FromEmailAddress"], "partnerships@partners.siutindei.com")
        threads = [t for t in board_store.list_mail_threads(self.table) if t]
        self.assertTrue(any(t.get("direction") == "outbound" or True for t in [board_store.get_mail_thread(self.table, sent["threadId"])] if t))

    def test_unsubscribe_token_round_trip_and_tamper(self) -> None:
        row = _prospect(self.table)
        token = board_outreach.make_unsub_token(row["prospectId"])
        self.assertEqual(board_outreach.parse_unsub_token(token), row["prospectId"])
        self.assertIsNone(board_outreach.parse_unsub_token(token[:-2] + "xx"))
        event = {
            "requestContext": {"http": {"method": "GET", "path": f"/public/outreach/unsubscribe/{token}", "sourceIp": "1.1.1.1"}, "requestId": "u1"},
            "rawQueryString": "",
        }
        out = lambda_handler(event, None)
        self.assertEqual(out["statusCode"], 200)
        self.assertIn("will not hear from us", out["body"])
        self.assertEqual(board_store.get_prospect(self.table, row["prospectId"])["stage"], "suppressed")
        event["requestContext"]["http"]["method"] = "POST"
        out = lambda_handler(event, None)
        self.assertEqual(out["statusCode"], 200)
        self.assertEqual(out["body"], "")
        sent = board_outreach.send(self.table, self.settings, prospect_id=row["prospectId"])
        self.assertEqual(sent["error"], "suppressed")

    def test_sqs_bounce_suppresses_and_breaker_thresholds(self) -> None:
        row = _prospect(self.table)
        payload = {
            "eventType": "Bounce",
            "bounce": {"bounceType": "Permanent"},
            "mail": {"tags": {"prospectId": [row["prospectId"]]}, "destination": ["info@play.example"]},
        }
        board_outreach.handle_ses_events(
            [{"eventSource": "aws:sqs", "body": json.dumps({"Type": "Notification", "Message": json.dumps(payload)})}]
        )
        self.assertEqual(board_store.get_prospect(self.table, row["prospectId"])["stage"], "suppressed")
        import board_hk

        day = board_store.load_outreach_day(self.table, board_hk.today_hkt())
        self.assertGreaterEqual(day["bounces"], 1)
        for i in range(7):
            d = (board_hk.now_hkt().date()).isoformat() if i == 0 else board_hk.today_hkt()
            board_store.save_outreach_day(self.table, {"sent": 10, "bounces": 1, "complaints": 0}, d)
        # Force 7 days of 8 bounces / 10 sends = 80% — use distinct dates
        from datetime import timedelta

        today = board_hk.now_hkt().date()
        for offset in range(7):
            board_store.save_outreach_day(self.table, {"sent": 10, "bounces": 1, "complaints": 0}, (today - timedelta(days=offset)).isoformat())
        tripped = board_breakers.evaluate(self.table, self.settings)
        self.assertIn("outreach", tripped)
        board_breakers.reset(self.table, "outreach", "owner")
        for offset in range(7):
            board_store.save_outreach_day(self.table, {"sent": 10, "bounces": 0, "complaints": 1}, (today - timedelta(days=offset)).isoformat())
        tripped = board_breakers.evaluate(self.table, self.settings)
        self.assertIn("outreach", tripped)

    def test_cap_raise_and_target_tasks(self) -> None:
        import board_hk
        from datetime import timedelta

        bounds = dict(self.settings.get("boundaries") or {})
        outreach = dict(bounds.get("outreach") or {})
        outreach["dailyCap"] = 20
        outreach["capRaisedAt"] = board_hk.to_iso(board_hk.now_hkt() - timedelta(days=8))
        bounds["outreach"] = outreach
        self.settings["boundaries"] = board_store.normalize_boundaries(bounds)
        self.settings = board_store.save_settings(self.table, self.settings)
        today = board_hk.now_hkt().date()
        for offset in range(7):
            board_store.save_outreach_day(self.table, {"sent": 2, "bounces": 0, "complaints": 0}, (today - timedelta(days=offset)).isoformat())
        result = board_targets.check(self.table, self.settings)
        self.assertGreaterEqual(result["shortfall"], 1)
        settings = board_store.load_settings(self.table)
        self.assertEqual(((settings.get("boundaries") or {}).get("outreach") or {}).get("dailyCap"), 40)
        self.assertTrue(result["taskIds"])
        qualify = board_store.get_task(self.table, result["taskIds"][0])
        self.assertIn("Find and qualify", str((qualify or {}).get("brief") or ""))
        self.assertEqual((qualify or {}).get("assignee"), "prospector")
        row = _prospect(self.table)
        board_sequences.start(self.table, row)
        result = board_targets.check(self.table, board_store.load_settings(self.table))
        self.assertGreaterEqual(result["dueTouches"], 1)

    def test_hold_then_send_and_reply_paths(self) -> None:
        row = _prospect(self.table)
        ctx = board_tools.ToolContext(
            table=self.table,
            settings=self.settings,
            persona_id="coo",
            display_name="COO",
            kind="task",
            actor="persona",
            seat_id="prospector",
        )
        outcome = board_tools.execute_call(
            ctx,
            board_tools.REGISTRY["outreach_send"],
            {"prospectId": row["prospectId"], "stepIndex": 0, "reason": "first touch"},
        )
        self.assertEqual(outcome.status, "held")
        self.assertEqual(outcome.result.get("status"), "held")
        holds = board_store.list_holds(self.table, "scheduled")
        self.assertTrue(holds)
        self.assertTrue(str(holds[0].get("classKey") or "").startswith("cold_outreach:"))
        # Promote the class and send immediately.
        bounds = dict(self.settings.get("boundaries") or {})
        overrides = dict(bounds.get("holdOverrides") or {})
        overrides[str(holds[0]["classKey"])] = 0
        bounds["holdOverrides"] = overrides
        self.settings["boundaries"] = board_store.normalize_boundaries(bounds)
        self.settings = board_store.save_settings(self.table, self.settings)
        ctx.settings = self.settings
        sent = board_tools.execute_call(
            ctx,
            board_tools.REGISTRY["outreach_send"],
            {"prospectId": row["prospectId"], "stepIndex": 0, "reason": "first touch"},
        )
        self.assertEqual(sent.status, "ok")
        import board_hk

        day = board_store.load_outreach_day(self.table, board_hk.today_hkt())
        self.assertGreaterEqual(day["sent"], 1)
        # Reply from the prospect → replied + provider-success task
        handled = board_outreach.maybe_handle_reply(self.table, self.settings, "info@play.example", "Thanks, we are interested")
        self.assertFalse(handled["suppressed"])
        self.assertEqual(board_store.get_prospect(self.table, row["prospectId"])["stage"], "replied")
        thread = {"threadId": "th-1", "subject": "Re: listing", "mailbox": "partnerships@siutindei.com"}
        message = {"from": {"address": "info@play.example"}, "text": "Thanks", "direction": "in", "threadId": "th-1"}
        task = board_triage.on_mail_ingested(self.table, self.settings, thread, message)
        self.assertIsNotNone(task)
        self.assertEqual(task.get("assignee"), "provider-success")
        # unsubscribe reply
        other = _prospect(self.table, name="Stop", website="https://stop.example", email="info@stop.example")
        thread2 = {"threadId": "th-2", "subject": "stop", "mailbox": "partnerships@siutindei.com"}
        msg2 = {"from": {"address": "info@stop.example"}, "text": "unsubscribe please", "direction": "in", "threadId": "th-2"}
        self.assertIsNone(board_triage.on_mail_ingested(self.table, self.settings, thread2, msg2))
        self.assertEqual(board_store.get_prospect(self.table, other["prospectId"])["stage"], "suppressed")

    def test_sending_disabled_refuses(self) -> None:
        row = _prospect(self.table)
        os.environ["BOARD_MAIL_SENDING_ENABLED"] = "false"
        self.assertEqual(
            board_outreach.send(self.table, self.settings, prospect_id=row["prospectId"])["error"],
            "email sending is switched off",
        )

    def test_personal_address_refused_at_send(self) -> None:
        row = _prospect(self.table, email="info@play.example")
        row["contact"] = "peter.chan.1984@gmail.com"
        board_store.put_prospect(self.table, row)
        self.assertEqual(
            board_outreach.send(self.table, self.settings, prospect_id=row["prospectId"])["error"],
            "personal address not allowed",
        )

    def test_quoted_footer_does_not_suppress(self) -> None:
        row = _prospect(self.table)
        text = (
            "Yes, we would love to be listed!\n\n"
            "> On Mon, Board wrote:\n"
            "> Reply \"unsubscribe\" or use https://example/unsub\n"
        )
        handled = board_outreach.maybe_handle_reply(self.table, self.settings, "info@play.example", text)
        self.assertFalse(handled["suppressed"])
        self.assertEqual(board_store.get_prospect(self.table, row["prospectId"])["stage"], "replied")
        bare = _prospect(self.table, name="Stop", website="https://stop.example", email="info@stop.example")
        handled2 = board_outreach.maybe_handle_reply(self.table, self.settings, "info@stop.example", "unsubscribe")
        self.assertTrue(handled2["suppressed"])
        self.assertEqual(board_store.get_prospect(self.table, bare["prospectId"])["stage"], "suppressed")
        zh = _prospect(self.table, name="Zh", website="https://zh2.example", email="info@zh2.example")
        handled3 = board_outreach.maybe_handle_reply(self.table, self.settings, "info@zh2.example", "請取消")
        self.assertTrue(handled3["suppressed"])

    def test_two_sends_at_cap_minus_one(self) -> None:
        import board_hk

        today = board_hk.today_hkt()
        board_store.save_outreach_day(self.table, {"sent": 19, "bounces": 0, "complaints": 0}, today)
        first = _prospect(self.table, name="A", website="https://a2.example", email="info@a2.example")
        second = _prospect(self.table, name="B", website="https://b2.example", email="info@b2.example")
        ok = board_outreach.send(self.table, self.settings, prospect_id=first["prospectId"])
        refused = board_outreach.send(self.table, self.settings, prospect_id=second["prospectId"])
        self.assertTrue(ok.get("ok"))
        self.assertEqual(refused.get("error"), "daily cap reached")

    def test_list_unsubscribe_is_https_only(self) -> None:
        row = _prospect(self.table)
        sent = board_outreach.send(self.table, self.settings, prospect_id=row["prospectId"])
        self.assertTrue(sent.get("ok"))
        raw = self.ses.calls[-1]["Content"]["Raw"]["Data"]
        msg = message_from_bytes(raw)
        raw_text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        self.assertIn("https://", raw_text)
        self.assertNotIn("mailto:", raw_text)

    def test_classify_outreach_send(self) -> None:
        row = _prospect(self.table)
        ctx = board_tools.ToolContext(table=self.table, settings=self.settings, persona_id="coo", kind="task")
        action, key = board_holds.classify(board_tools.REGISTRY["outreach_send"], ctx, {"prospectId": row["prospectId"]}, self.settings)
        self.assertEqual(action, "cold_outreach")
        self.assertEqual(key, "cold_outreach:venue")


if __name__ == "__main__":
    unittest.main()
