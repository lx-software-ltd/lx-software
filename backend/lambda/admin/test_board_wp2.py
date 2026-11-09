"""WP2: WhatsApp / Meta correctness — webhook parsing, idempotence, thread binding, Graph client."""

from __future__ import annotations

import io
import unittest
from datetime import datetime, timedelta, timezone
from email.message import Message
from typing import Any
from urllib import error as urlerror

import board_meta
import board_meta_token
import board_store
from board_tools import REGISTRY, ToolContext, execute_call
from test_board_t5 import PAGE_TOKEN, MetaTestCase

NUMBER_A = "85291234567"
NUMBER_B = "85298765432"


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _wa_payload(*messages: dict[str, Any], contacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"messaging_product": "whatsapp", "messages": list(messages)}
    if contacts is not None:
        value["contacts"] = contacts
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": value}]}],
    }


def _wa_message(mid: str, text: str, *, sender: str | None = NUMBER_A, ts: int | None = None) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "id": mid,
        "timestamp": str(ts if ts is not None else int(datetime.now(timezone.utc).timestamp())),
        "type": "text",
        "text": {"body": text},
    }
    if sender is not None:
        msg["from"] = sender
    return msg


def _http_error(status: int, body: str = '{"error":{"message":"bad token"}}') -> urlerror.HTTPError:
    return urlerror.HTTPError("https://graph.facebook.com/x", status, "Bad Request", Message(), io.BytesIO(body.encode()))


class TestWebhookParsing(MetaTestCase):
    def test_from_without_contacts_lands_in_one_thread(self) -> None:
        payload = _wa_payload(_wa_message("wamid.1", "Hi there"), _wa_message("wamid.2", "Still here"))
        out = board_meta.ingest_webhook(self.table, payload)
        self.assertEqual(out["stored"], 2)
        threads = board_store.list_meta_threads(self.table)
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["senderId"], NUMBER_A)
        self.assertEqual(threads[0]["threadId"], board_meta.whatsapp_thread_id(NUMBER_A))
        self.assertEqual(threads[0]["messageCount"], 2)

    def test_contacts_wa_id_used_when_from_is_missing(self) -> None:
        payload = _wa_payload(_wa_message("wamid.3", "No from here", sender=None), contacts=[{"wa_id": NUMBER_B}])
        board_meta.ingest_webhook(self.table, payload)
        threads = board_store.list_meta_threads(self.table)
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["senderId"], NUMBER_B)
        # A later message with an explicit ``from`` for the same number joins the same thread.
        board_meta.ingest_webhook(self.table, _wa_payload(_wa_message("wamid.4", "Again", sender=NUMBER_B)))
        threads = board_store.list_meta_threads(self.table)
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["messageCount"], 2)

    def test_page_echo_messages_are_skipped(self) -> None:
        payload = {
            "object": "page",
            "entry": [
                {
                    "id": "page-1",
                    "time": 1_700_000_000_000,
                    "messaging": [
                        {
                            "sender": {"id": "page-1"},
                            "recipient": {"id": "psid-1"},
                            "timestamp": 1_700_000_000_000,
                            "message": {"mid": "m.echo", "is_echo": True, "text": "Our own reply"},
                        },
                        {
                            "sender": {"id": "psid-1"},
                            "recipient": {"id": "page-1"},
                            "timestamp": 1_700_000_001_000,
                            "message": {"mid": "m.in", "text": "A real inbound DM"},
                        },
                    ],
                }
            ],
        }
        out = board_meta.ingest_webhook(self.table, payload)
        self.assertEqual(out["stored"], 1)
        threads = board_store.list_meta_threads(self.table)
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["senderId"], "psid-1")
        self.assertEqual(threads[0]["channel"], "page")

    def test_comment_with_string_from_does_not_crash(self) -> None:
        payload = {
            "object": "page",
            "entry": [
                {
                    "id": "page-1",
                    "changes": [
                        {
                            "field": "feed",
                            "value": {
                                "item": "comment",
                                "comment_id": "c9",
                                "id": "c9",
                                "from": "user-77",
                                "message": "Ping me on 9123 4567",
                                "created_time": 1_700_000_000,
                            },
                        }
                    ],
                }
            ],
        }
        out = board_meta.ingest_webhook(self.table, payload)
        self.assertEqual(out["stored"], 1)
        thread = board_store.list_meta_threads(self.table)[0]
        self.assertEqual(thread["senderId"], "user-77")
        self.assertEqual(thread["kind"], "comment")
        self.assertNotIn("9123", thread["lastTextMasked"])

    def test_redelivered_webhook_is_idempotent(self) -> None:
        payload = _wa_payload(_wa_message("wamid.dup", "Hello once", ts=1_700_000_000))
        first = board_meta.ingest_webhook(self.table, payload)
        second = board_meta.ingest_webhook(self.table, payload)
        self.assertEqual(first, {"stored": 1, "duplicates": 0})
        self.assertEqual(second, {"stored": 0, "duplicates": 1})
        thread = board_store.list_meta_threads(self.table)[0]
        self.assertEqual(thread["messageCount"], 1)
        self.assertEqual(len(board_store.list_meta_messages(self.table, thread["threadId"])), 1)
        # Marking the thread read survives a redelivery of an already-stored message.
        board_store.put_meta_thread(self.table, {**thread, "unread": False})
        board_meta.ingest_webhook(self.table, payload)
        self.assertFalse(board_store.get_meta_thread(self.table, thread["threadId"])["unread"])


class TestWhatsAppBinding(MetaTestCase):
    def _act_ctx(self, allow: list[str]) -> ToolContext:
        settings = board_store.load_settings(self.table)
        settings["tools"]["globalMode"] = "act"
        settings["tools"]["allowList"] = allow
        board_store.save_settings(self.table, settings)
        return ToolContext(table=self.table, settings=settings, persona_id="coo", actor="persona")

    def _put_thread(self, number: str, *, age: timedelta = timedelta(0)) -> str:
        thread_id = board_meta.whatsapp_thread_id(number)
        board_store.put_meta_thread(
            self.table,
            {
                "threadId": thread_id,
                "channel": "whatsapp",
                "senderId": number,
                "lastInboundAt": _iso(datetime.now(timezone.utc) - age),
                "unread": True,
            },
        )
        return thread_id

    def test_window_of_one_number_cannot_reach_another(self) -> None:
        ctx = self._act_ctx([f"+{NUMBER_A}", f"+{NUMBER_B}"])
        thread_a = self._put_thread(NUMBER_A)
        # Model passes A's open thread but addresses B: bound to B's (non-existent) window.
        out = execute_call(
            ctx,
            REGISTRY["meta_reply_whatsapp"],
            {"to": f"+{NUMBER_B}", "threadId": thread_a, "message": "Hi B", "reason": "Cross-thread."},
        )
        self.assertEqual(out.status, "pending_approval")
        self.assertNotIn("Hi B", str([b for _m, _u, b in self.graph.calls]))
        # B without any stored thread has no window either.
        no_thread = execute_call(
            ctx,
            REGISTRY["meta_reply_whatsapp"],
            {"to": f"+{NUMBER_B}", "message": "Hi B", "reason": "No thread."},
        )
        self.assertEqual(no_thread.status, "pending_approval")
        self.assertIn("no open WhatsApp window", no_thread.result["message"])
        # A's own window is honoured.
        ok = execute_call(
            ctx,
            REGISTRY["meta_reply_whatsapp"],
            {"to": f"+{NUMBER_A}", "message": "Hi A", "reason": "In window."},
        )
        self.assertEqual(ok.status, "ok")
        self.assertEqual(self.graph.calls[-1][2]["to"], NUMBER_A)

    def test_template_outside_window_proposes_inside_acts(self) -> None:
        ctx = self._act_ctx([f"+{NUMBER_A}", f"+{NUMBER_B}"])
        # Template with no thread at all → pending approval.
        out = execute_call(
            ctx,
            REGISTRY["meta_reply_whatsapp"],
            {"to": f"+{NUMBER_B}", "template": "hello_world", "reason": "Cold template."},
        )
        self.assertEqual(out.status, "pending_approval")
        self.assertIn("template", out.result["message"])
        # Template with a closed window → pending approval.
        self._put_thread(NUMBER_B, age=timedelta(hours=30))
        closed = execute_call(
            ctx,
            REGISTRY["meta_reply_whatsapp"],
            {"to": f"+{NUMBER_B}", "template": "hello_world", "reason": "Closed window."},
        )
        self.assertEqual(closed.status, "pending_approval")
        self.assertFalse(self.graph.calls)
        # Template inside the window is allowed to act.
        self._put_thread(NUMBER_A)
        ok = execute_call(
            ctx,
            REGISTRY["meta_reply_whatsapp"],
            {"to": f"+{NUMBER_A}", "template": "hello_world", "reason": "Open window."},
        )
        self.assertEqual(ok.status, "ok")
        self.assertEqual(self.graph.calls[-1][2]["type"], "template")
        self.assertEqual(self.graph.calls[-1][2]["template"]["name"], "hello_world")

    def test_reply_by_thread_id_alone_resolves_recipient(self) -> None:
        # ``threadId``-only calls go through the op directly until the
        # meta_reply_whatsapp schema makes ``to`` optional (see WP2 report).
        ctx = self._act_ctx([f"+{NUMBER_A}"])
        thread_id = self._put_thread(NUMBER_A)
        args = {"threadId": thread_id, "message": "Hello from the thread", "reason": "Thread only."}
        self.assertIsNone(board_meta.act_guard_whatsapp(ctx, args))
        out = board_meta.op_reply_whatsapp(ctx, args)
        self.assertTrue(out["ok"])
        self.assertEqual(out["to"], NUMBER_A)
        self.assertEqual(out["threadId"], thread_id)
        self.assertEqual(self.graph.calls[-1][2]["to"], NUMBER_A)
        preview = board_meta.owner_preview_message(ctx, {"threadId": thread_id, "message": "x"}, op="meta_reply_whatsapp")
        self.assertEqual(preview["to"], [NUMBER_A])
        self.assertEqual(preview["from"], "whatsapp")
        # A thread paired with a different number is refused outright, in the guard and in the op.
        mismatch = {"threadId": thread_id, "to": f"+{NUMBER_B}", "message": "x"}
        self.assertIn("does not belong", board_meta.act_guard_whatsapp(ctx, mismatch))
        with self.assertRaises(board_meta.MetaError):
            board_meta.op_reply_whatsapp(ctx, mismatch)
        # Unknown thread and no ``to``: nothing to send to.
        self.assertIn("required", board_meta.act_guard_whatsapp(ctx, {"threadId": "nope", "message": "x"}))

    def test_reply_dm_by_thread_and_allow_list_guard(self) -> None:
        board_meta.ingest_webhook(
            self.table,
            {
                "object": "page",
                "entry": [
                    {
                        "id": "page-1",
                        "messaging": [
                            {
                                "sender": {"id": "1234567890"},
                                "recipient": {"id": "page-1"},
                                "timestamp": 1_700_000_001_000,
                                "message": {"mid": "m.dm", "text": "Is Saturday free?"},
                            }
                        ],
                    }
                ],
            },
        )
        thread_id = board_store.list_meta_threads(self.table)[0]["threadId"]
        args = {"threadId": thread_id, "message": "Yes", "reason": "Reply."}
        ctx = self._act_ctx([])
        self.assertEqual(
            board_meta.act_guard_allow_list(ctx, args, field="recipientId"),
            "1234567890 is not on the allow-list",
        )
        ctx = self._act_ctx(["1234567890"])
        self.assertIsNone(board_meta.act_guard_allow_list(ctx, args, field="recipientId"))
        ok = board_meta.op_reply_dm(ctx, args)
        self.assertEqual(ok["recipientId"], "1234567890")
        self.assertEqual(ok["threadId"], thread_id)
        self.assertEqual(self.graph.calls[-1][2]["recipient"]["id"], "1234567890")
        preview = board_meta.owner_preview_message(ctx, {"threadId": thread_id, "message": "Yes"}, op="meta_reply_dm")
        self.assertEqual(preview["to"], ["1234567890"])
        self.assertIn(
            "does not belong",
            board_meta.act_guard_allow_list(ctx, {"threadId": thread_id, "recipientId": "other"}, field="recipientId"),
        )
        # Backward compatible: recipientId alone (today's schema) still works end to end.
        legacy = execute_call(
            ctx,
            REGISTRY["meta_reply_dm"],
            {"recipientId": "1234567890", "message": "Yes", "reason": "Listed."},
        )
        self.assertEqual(legacy.status, "ok")


class TestRelayLead(MetaTestCase):
    def test_relay_lead_records_action_and_hands_off_on_whatsapp(self) -> None:
        owner = self._ctx("coo", actor="owner")
        out = board_meta.op_relay_lead(
            owner,
            {
                "providerEmail": "studio@example.com",
                "providerPhone": f"+{NUMBER_B}",
                "template": "new_lead",
                "parentEmail": "parent@example.com",
                "summary": "Saturday swim for a 6-year-old",
            },
        )
        self.assertTrue(out["ok"])
        self.assertFalse(out["sent"])
        actions = board_store.list_actions(self.table)
        self.assertEqual(len(actions), 1)
        action = actions[0]
        self.assertEqual(action["actionId"], out["actionId"])
        self.assertEqual(action["status"], "open")
        self.assertEqual(action["source"], "approval")
        self.assertEqual(action["persona"], "coo")
        self.assertIn("studio@example.com", action["title"])
        self.assertIn("Saturday swim", action["detail"])
        self.assertTrue(action["dueAt"])
        # The WhatsApp template hand-off went to the provider's number.
        wa = [b for m, url, b in self.graph.calls if m == "POST" and "/wa-phone-1/messages" in url]
        self.assertEqual(len(wa), 1)
        self.assertEqual(wa[0]["to"], NUMBER_B)
        self.assertEqual(wa[0]["template"]["name"], "new_lead")
        preview = board_meta.owner_preview_message(
            owner,
            {"providerEmail": "studio@example.com", "providerPhone": f"+{NUMBER_B}", "parentEmail": "parent@example.com"},
            op="meta_relay_lead",
        )
        self.assertEqual(preview["to"], ["studio@example.com", f"+{NUMBER_B}", "parent@example.com"])

    def test_relay_lead_email_only_still_records_action(self) -> None:
        out = board_meta.op_relay_lead(
            self._ctx("coo", actor="owner"),
            {"providerEmail": "studio@example.com", "parentEmail": "parent@example.com", "summary": "Lead"},
        )
        self.assertEqual(len(board_store.list_actions(self.table)), 1)
        self.assertNotIn("whatsapp", out)
        self.assertFalse(self.graph.calls)
        with self.assertRaises(board_meta.MetaError):
            board_meta.op_relay_lead(
                self._ctx("coo", actor="owner"),
                {"providerPhone": f"+{NUMBER_B}", "parentEmail": "parent@example.com"},
            )

    def test_relay_guard_checks_provider_phone(self) -> None:
        settings = board_store.load_settings(self.table)
        settings["tools"]["allowList"] = ["parent@example.com"]
        ctx = ToolContext(table=self.table, settings=settings, persona_id="coo", actor="persona")
        args = {"providerPhone": f"+{NUMBER_B}", "template": "new_lead", "parentEmail": "parent@example.com"}
        self.assertIn("allow-list", board_meta.act_guard_relay(ctx, args))
        settings["tools"]["allowList"].append(f"+{NUMBER_B}")
        self.assertIsNone(board_meta.act_guard_relay(ctx, args))


class TestGraphClient(MetaTestCase):
    def test_token_travels_in_bearer_header_not_url(self) -> None:
        board_meta.graph("GET", "me", params={"fields": "id", "appsecret_proof": "abc"})
        self.assertEqual(self.graph.tokens, ["Bearer token-local"])
        _m, url, _b = self.graph.calls[0]
        self.assertNotIn("token-local", url)
        self.assertNotIn("access_token", url)
        self.assertIn("appsecret_proof=abc", url)

    def test_page_scoped_matches_the_page_and_its_object_ids(self) -> None:
        self.assertTrue(board_meta_token.page_scoped("page-1/feed", "page-1"))
        self.assertTrue(board_meta_token.page_scoped("page-1_777_888/comments", "page-1"))
        self.assertFalse(board_meta_token.page_scoped("page-1x/feed", "page-1"))
        self.assertFalse(board_meta_token.page_scoped("me", "page-1"))
        self.assertFalse(board_meta_token.page_scoped("page-1/feed", ""))

    def test_page_edges_use_an_exchanged_page_token_once_per_container(self) -> None:
        board_meta.graph("GET", "page-1/feed", params={"limit": 1})
        board_meta.graph("POST", "page-1/feed", body={"message": "hi"})
        board_meta.graph("GET", "page-1_777/comments")
        board_meta.graph("POST", "page-1_777_888/comments", body={"message": "reply"})
        # One exchange, made with the System User token, serves every Page call.
        self.assertEqual(self.graph.exchanges, ["Bearer token-local"])
        self.assertEqual(self.graph.tokens, [f"Bearer {PAGE_TOKEN}"] * 4)
        for _m, url, _b in self.graph.calls:
            self.assertNotIn(PAGE_TOKEN, url)
            self.assertNotIn("access_token", url)

    def test_non_page_paths_keep_the_system_user_token(self) -> None:
        board_meta.graph("GET", "me")
        board_meta.graph("GET", "ig-1/insights", params={"metric": "reach", "period": "day"})
        board_meta.graph("GET", "act_99/insights")
        board_meta.graph("POST", "wa-phone-1/messages", body={"to": "1"})
        # A bare "page-1x" prefix is not the Page: only "page-1" or "page-1_…" are.
        board_meta.graph("GET", "page-1x/feed")
        self.assertEqual(self.graph.exchanges, [])
        self.assertEqual(self.graph.tokens, ["Bearer token-local"] * 5)

    def test_failed_exchange_falls_back_to_the_system_user_token(self) -> None:
        self.graph.page_token = None
        board_meta.graph("GET", "page-1/feed")
        board_meta.graph("GET", "page-1/feed")
        # Nothing is cached on failure, so the next call tries the exchange again.
        self.assertEqual(len(self.graph.exchanges), 2)
        self.assertEqual(self.graph.tokens, ["Bearer token-local"] * 2)
        # Meta's own error still surfaces when the fallback call fails too.
        self.graph.queue.append(_http_error(400, '{"error":{"code":190,"error_subcode":2069032}}'))
        with self.assertRaises(board_meta.MetaError) as caught:
            board_meta.graph("GET", "page-1/feed")
        self.assertIn("2069032", str(caught.exception))
        self.graph.page_token = PAGE_TOKEN
        board_meta.graph("GET", "page-1/feed")
        self.assertEqual(self.graph.tokens[-1], f"Bearer {PAGE_TOKEN}")

    def test_page_insights_default_metric_is_still_served_by_meta(self) -> None:
        board_meta.op_page_insights(self._ctx(), {})
        _m, url, _b = self.graph.calls[-1]
        # ``page_impressions*`` was retired on 2025-11-15; one retired metric fails the whole request.
        self.assertIn("metric=page_media_view%2Cpage_total_media_view_unique%2Cpage_post_engagements", url)
        self.assertNotIn("page_impressions", url)
        self.assertNotIn("page_engaged_users", url)
        self.assertEqual(self.graph.tokens[-1], f"Bearer {PAGE_TOKEN}")

    def test_ig_insights_default_metric_uses_views_and_total_value(self) -> None:
        out = board_meta.op_ig_insights(self._ctx(), {})
        _m, url, _b = self.graph.calls[-1]
        self.assertIn("/ig-1/insights", url)
        self.assertIn("metric=reach%2Cviews%2Cprofile_views", url)
        self.assertIn("metric_type=total_value", url)
        self.assertNotIn("impressions", url)
        self.assertEqual(out["igUserId"], "ig-1")
        self.assertNotIn("resolvedFrom", out)

    def test_ig_insights_falls_back_to_the_page_linked_account(self) -> None:
        rejected = '{"error":{"message":"(#100) Tried accessing nonexisting field (insights)","code":100}}'
        self.graph.queue.append(_http_error(400, rejected))
        out = board_meta.op_ig_insights(self._ctx(), {})
        urls = [url for _m, url, _b in self.graph.calls]
        self.assertTrue(any("/ig-1/insights" in u for u in urls))
        self.assertTrue(any("/page-1?fields=instagram_business_account" in u for u in urls))
        self.assertTrue(any("/17841000000000001/insights" in u for u in urls))
        self.assertEqual(out["igUserId"], "17841000000000001")
        self.assertEqual(out["resolvedFrom"], "page")
        self.assertEqual(out["configuredIgUserId"], "ig-1")
        # The linked id is cached, so a second rejected read costs one lookup, not two.
        self.graph.queue.append(_http_error(400, rejected))
        board_meta.op_ig_insights(self._ctx(), {})
        lookups = [u for _m, u, _b in self.graph.calls if "fields=instagram_business_account" in u]
        self.assertEqual(len(lookups), 1)

    def test_ig_insights_reraises_other_errors_without_lookup(self) -> None:
        self.graph.queue.append(_http_error(400, '{"error":{"message":"(#100) The value must be a valid insights metric","code":100}}'))
        with self.assertRaises(board_meta.MetaError) as caught:
            board_meta.op_ig_insights(self._ctx(), {"metric": "impressions"})
        self.assertIn("valid insights metric", str(caught.exception))
        self.assertFalse(any("fields=instagram_business_account" in u for _m, u, _b in self.graph.calls))

    def test_http_error_becomes_meta_error_with_status(self) -> None:
        unauthorized = _http_error(401)
        self.graph.queue.append(unauthorized)
        with self.assertRaises(board_meta.MetaError) as caught:
            board_meta.graph("GET", "me")
        self.assertEqual(caught.exception.status, 401)
        self.assertIn("401", str(caught.exception))
        self.assertIn("bad token", str(caught.exception))
        self.assertTrue(unauthorized.fp.closed)
        # Through a tool op the error is a structured tool failure, not a crash.
        upstream = _http_error(500, "upstream")
        self.graph.queue.append(upstream)
        out = execute_call(self._ctx("cmo"), REGISTRY["meta_page_insights"], {})
        self.assertEqual(out.status, "error")
        self.assertIn("500", out.result["error"])
        self.assertTrue(upstream.fp.closed)

    def test_graph_pages_follows_after_cursor_and_caps(self) -> None:
        self.graph.queue.extend(
            [
                {"data": [{"id": "p1"}, {"id": "p2"}], "paging": {"cursors": {"after": "CUR1"}, "next": "https://next"}},
                {"data": [{"id": "p3"}], "paging": {"cursors": {"after": "CUR2"}, "next": "https://next2"}},
                {"data": [{"id": "p4"}], "paging": {"cursors": {}}},
            ]
        )
        rows = board_meta.graph_pages("GET", "page-1/feed", {"limit": 2})
        self.assertEqual([r["id"] for r in rows], ["p1", "p2", "p3", "p4"])
        self.assertEqual(len(self.graph.calls), 3)
        self.assertIn("after=CUR1", self.graph.calls[1][1])
        self.assertIn("after=CUR2", self.graph.calls[2][1])
        # Capped: the third page is never requested when the limit is reached.
        self.graph.calls.clear()
        self.graph.queue.extend(
            [
                {"data": [{"id": "a"}, {"id": "b"}], "paging": {"cursors": {"after": "X"}, "next": "n"}},
                {"data": [{"id": "c"}, {"id": "d"}], "paging": {"cursors": {"after": "Y"}, "next": "n"}},
                {"data": [{"id": "e"}], "paging": {"cursors": {"after": "Z"}, "next": "n"}},
            ]
        )
        rows = board_meta.graph_pages("GET", "page-1/feed", {}, limit=3)
        self.assertEqual([r["id"] for r in rows], ["a", "b", "c"])
        self.assertEqual(len(self.graph.calls), 2)

    def test_list_comments_uses_pagination(self) -> None:
        self.graph.queue.extend(
            [
                {
                    "data": [{"id": "p1", "message": "one", "comments": {"data": [{"id": "c1", "from": "u1", "message": "hi"}]}}],
                    "paging": {"cursors": {"after": "AFTER"}, "next": "https://next"},
                },
                {"data": [{"id": "p2", "message": "two", "comments": {"data": []}}]},
            ]
        )
        out = board_meta.op_list_comments(self._ctx(), {"limit": 5})
        self.assertEqual(out["count"], 2)
        self.assertEqual([p["id"] for p in out["posts"]], ["p1", "p2"])
        self.assertTrue(out["posts"][0]["comments"][0]["from"].startswith("contact#"))
        self.assertIn("after=AFTER", self.graph.calls[1][1])


if __name__ == "__main__":
    unittest.main()
