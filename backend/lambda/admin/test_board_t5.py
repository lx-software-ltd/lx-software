"""T5: Meta webhook, Graph reads/writes, WhatsApp 24-hour guard, lead relay."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch
from urllib import request as urlrequest

import board_context
import board_meta
import board_store
import dispatch
from board_tools import REGISTRY, ToolContext, execute_call
from test_board import BoardTestCase
from test_board_tools import ToolsTestCase


class FakeGraph:
    """Stands in for ``board_meta._urlopen``.

    ``queue`` entries are served first (a dict payload, or an exception to raise);
    otherwise the URL picks a canned payload. ``tokens`` records each
    ``Authorization`` header so tests can prove the token never rides the URL.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.tokens: list[str] = []
        self.queue: list[Any] = []

    def __call__(self, req: urlrequest.Request, timeout=None):  # noqa: ARG002
        method = req.get_method()
        url = req.full_url
        body = json.loads(req.data.decode("utf-8")) if req.data else None
        self.calls.append((method, url, body))
        self.tokens.append(str(req.get_header("Authorization") or ""))
        if self.queue:
            payload = self.queue.pop(0)
            if isinstance(payload, BaseException):
                raise payload
        elif "/insights" in url:
            if "/act_" in url:
                payload: Any = {"data": [{"spend": "0.00", "impressions": "1", "clicks": "0"}]}
            else:
                payload = {"data": [{"name": "page_impressions", "values": [{"value": 12}]}]}
        elif "/message_templates" in url:
            payload = {
                "data": [
                    {"name": "hello_world", "status": "APPROVED", "language": "en", "category": "UTILITY"}
                ]
            }
        elif "fields=whatsapp_business_account" in url or "whatsapp_business_account" in url:
            payload = {"whatsapp_business_account": {"id": "waba-1"}}
        elif "/feed" in url and method == "GET":
            payload = {
                "data": [
                    {
                        "id": "p1",
                        "message": "Hello from wendy.chan@gmail.com",
                        "comments": {"data": [{"id": "c1", "from": {"id": "u1"}, "message": "Call 9123 4567"}]},
                    }
                ]
            }
        elif method == "POST":
            payload = {"id": "created-1", "message_id": "mid-1", "messages": [{"id": "wa-1"}]}
        else:
            payload = {"data": []}

        class _Resp:
            def read(self) -> bytes:
                return json.dumps(payload).encode()

            def __enter__(self) -> "_Resp":
                return self

            def __exit__(self, *args: Any) -> None:
                return None

        return _Resp()


class MetaTestCase(ToolsTestCase):
    def setUp(self) -> None:
        super().setUp()
        board_meta.reset_caches_for_tests()
        os.environ["META_BOARD_TOKEN"] = "token-local"
        os.environ["META_APP_SECRET"] = "app-secret"
        os.environ["META_VERIFY_TOKEN"] = "verify-me"
        os.environ["META_PAGE_ID"] = "page-1"
        os.environ["META_IG_USER_ID"] = "ig-1"
        os.environ["META_WA_PHONE_NUMBER_ID"] = "wa-phone-1"
        os.environ["META_AD_ACCOUNT_ID"] = "act_99"
        self.addCleanup(board_meta.reset_caches_for_tests)
        self.graph = FakeGraph()
        p = patch.object(board_meta, "_urlopen", self.graph)
        p.start()
        self.addCleanup(p.stop)

    def _ctx(self, persona: str = "cmo", *, actor: str = "persona", global_mode: str = "propose") -> ToolContext:
        settings = board_store.load_settings(self.table)
        settings["tools"]["globalMode"] = global_mode
        return ToolContext(
            table=self.table,
            settings=settings,
            persona_id=persona,
            display_name=persona.upper(),
            actor=actor,
            owner_sub="owner-1" if actor == "owner" else "",
        )


class TestWebhook(MetaTestCase):
    def test_verify_handshake(self) -> None:
        ev = {
            "requestContext": {"http": {"method": "GET", "path": "/webhooks/meta"}, "requestId": "w1"},
            "rawQueryString": "hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=abc123",
        }
        out = dispatch.lambda_handler(ev, None)
        self.assertEqual(out["statusCode"], 200)
        self.assertEqual(out["body"], "abc123")
        self.assertEqual(out["headers"]["Content-Type"], "text/plain")

    def test_tenant_webhook_path_uses_the_same_handler(self) -> None:
        ev = {
            "requestContext": {
                "http": {"method": "GET", "path": "/webhooks/meta/siutindei"},
                "requestId": "w1b",
            },
            "rawQueryString": "hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=tenant",
        }
        out = dispatch.lambda_handler(ev, None)
        self.assertEqual(out["statusCode"], 200)
        self.assertEqual(out["body"], "tenant")

    def test_verify_rejects_wrong_token(self) -> None:
        ev = {
            "requestContext": {"http": {"method": "GET", "path": "/webhooks/meta"}, "requestId": "w2"},
            "rawQueryString": "hub.mode=subscribe&hub.verify_token=nope&hub.challenge=x",
        }
        out = dispatch.lambda_handler(ev, None)
        self.assertEqual(out["statusCode"], 403)

    def test_post_requires_valid_hmac_and_masks_pii(self) -> None:
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messages": [
                                    {
                                        "id": "wamid.1",
                                        "from": "85291234567",
                                        "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                                        "text": {"body": "Hi, email me at parent@example.com or 9123 4567"},
                                    }
                                ]
                            },
                        }
                    ]
                }
            ],
        }
        raw = json.dumps(payload).encode()
        sig = hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
        ev = {
            "requestContext": {"http": {"method": "POST", "path": "/webhooks/meta"}, "requestId": "w3"},
            "rawQueryString": "",
            "headers": {"X-Hub-Signature-256": f"sha256={sig}"},
            "body": raw.decode(),
        }
        with patch.object(board_store, "records_table", return_value=self.table):
            out = dispatch.lambda_handler(ev, None)
        self.assertEqual(out["statusCode"], 200)
        threads = board_store.list_meta_threads(self.table)
        self.assertEqual(len(threads), 1)
        self.assertIn("contact#", threads[0]["lastTextMasked"])
        self.assertNotIn("parent@example.com", threads[0]["lastTextMasked"])
        # Unsigned body is rejected.
        ev["headers"] = {"X-Hub-Signature-256": "sha256=deadbeef"}
        with patch.object(board_store, "records_table", return_value=self.table):
            bad = dispatch.lambda_handler(ev, None)
        self.assertEqual(bad["statusCode"], 403)


class TestMetaTools(MetaTestCase):
    def test_reads_mask_graph_comments_and_use_graph(self) -> None:
        ctx = self._ctx()
        insights = board_meta.op_page_insights(ctx, {})
        self.assertEqual(insights["count"], 1)
        comments = board_meta.op_list_comments(ctx, {})
        self.assertNotIn("wendy.chan@gmail.com", json.dumps(comments))
        self.assertIn("contact#", comments["posts"][0]["message"])
        self.assertIn("phone#", comments["posts"][0]["comments"][0]["message"])
        spend = board_meta.op_ad_spend(ctx, {})
        self.assertEqual(spend["adAccountId"], "act_99")
        self.assertTrue(any("/page-1/insights" in url for _m, url, _b in self.graph.calls))

    def test_writes_are_proposals_for_cmo(self) -> None:
        ctx = self._ctx("cmo")
        out = execute_call(ctx, REGISTRY["meta_propose_post"], {"message": "Hello HK", "reason": "Launch week."})
        self.assertEqual(out.status, "pending_approval")
        self.assertFalse(self.graph.calls)

    def test_owner_publish_hits_graph(self) -> None:
        owner = self._ctx("cmo", actor="owner")
        out = execute_call(owner, REGISTRY["meta_propose_post"], {"message": "Hello HK", "reason": "Approved."})
        self.assertEqual(out.status, "ok")
        self.assertTrue(any(m == "POST" and "/page-1/feed" in url for m, url, _ in self.graph.calls))

    def test_whatsapp_act_requires_window_and_allow_list(self) -> None:
        now = datetime.now(timezone.utc)
        # The window is keyed by the recipient number, so the stored thread id
        # must be the one the webhook would derive for that number.
        settings = board_store.load_settings(self.table)
        settings["tools"]["globalMode"] = "act"
        settings["tools"]["allowList"] = ["+85291234567"]
        board_store.save_settings(self.table, settings)
        ctx = ToolContext(table=self.table, settings=settings, persona_id="coo", actor="persona")
        board_store.put_meta_thread(
            self.table,
            {
                "threadId": board_meta.whatsapp_thread_id("+85291234567"),
                "channel": "whatsapp",
                "senderId": "85291234567",
                "lastInboundAt": (now - timedelta(hours=30)).isoformat().replace("+00:00", "Z"),
                "unread": True,
            },
        )
        blocked_window = execute_call(
            ctx,
            REGISTRY["meta_reply_whatsapp"],
            {"to": "+85291234567", "message": "Hi", "reason": "Follow up."},
        )
        self.assertEqual(blocked_window.status, "pending_approval")
        self.assertIn("24-hour", blocked_window.result["message"])
        board_store.put_meta_thread(
            self.table,
            {
                "threadId": board_meta.whatsapp_thread_id("+85291234567"),
                "channel": "whatsapp",
                "senderId": "85291234567",
                "lastInboundAt": now.isoformat().replace("+00:00", "Z"),
                "unread": True,
            },
        )
        blocked_list = execute_call(
            ctx,
            REGISTRY["meta_reply_whatsapp"],
            {"to": "+85299999999", "message": "Hi", "reason": "Follow up."},
        )
        self.assertEqual(blocked_list.status, "pending_approval")
        self.assertIn("allow-list", blocked_list.result["message"])
        ok = execute_call(
            ctx,
            REGISTRY["meta_reply_whatsapp"],
            {"to": "+85291234567", "message": "Hi", "reason": "In window."},
        )
        self.assertEqual(ok.status, "ok")
        self.assertEqual(ok.result["threadId"], board_meta.whatsapp_thread_id("+85291234567"))

    def test_ad_set_over_cap_is_forced_to_propose(self) -> None:
        ctx = self._ctx("cmo", global_mode="act")
        out = execute_call(
            ctx,
            REGISTRY["meta_create_ad_set"],
            {"name": "Boost", "dailyBudgetUsd": 10, "reason": "Too spendy."},
        )
        self.assertEqual(out.status, "pending_approval")
        self.assertIn("cap", out.result["message"])

    def test_relay_lead_always_proposes_off_allow_list(self) -> None:
        ctx = self._ctx("coo", global_mode="act")
        out = execute_call(
            ctx,
            REGISTRY["meta_relay_lead"],
            {
                "providerEmail": "studio@example.com",
                "parentEmail": "parent@example.com",
                "summary": "Saturday swim",
                "reason": "Lead from the site CTA.",
            },
        )
        self.assertEqual(out.status, "pending_approval")

    def test_context_pack_mentions_unread_whatsapp(self) -> None:
        board_store.put_meta_thread(
            self.table,
            {
                "threadId": "th-1",
                "channel": "whatsapp",
                "unread": True,
                "lastInboundAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
        settings = board_store.load_settings(self.table)
        pack = board_context.build_context_pack(self.table, settings, roster=[])
        self.assertIn("Meta:", pack["text"])
        self.assertIn("WhatsApp", pack["text"])


class TestMetaUnavailable(BoardTestCase):
    def test_graph_without_token(self) -> None:
        board_meta.reset_caches_for_tests()
        os.environ.pop("META_BOARD_TOKEN", None)
        os.environ.pop("META_BOARD_TOKEN_SECRET_ARN", None)
        with self.assertRaises(board_meta.MetaError):
            board_meta.graph("GET", "me")


if __name__ == "__main__":
    unittest.main()
