"""One test per fault found in the review of the Messages inbox."""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import board_meta
import board_meta_attachments
import board_meta_backfill
import board_meta_inbox
import board_meta_ingest
import board_meta_store
import board_meta_triage
import board_meta_whatsapp
import board_public_api
import board_routes
import board_staff
import board_store
import board_tools
import board_triage
import runtime
from test_board import BoardTestCase
from test_board_t5 import MetaTestCase

NUMBER = "85291234567"


def wa(mid: str, text: str, ts: int, sender: str = NUMBER) -> dict[str, Any]:
    return {"from": sender, "id": mid, "timestamp": str(ts), "type": "text", "text": {"body": text}}


def wa_change(field: str, value: dict[str, Any]) -> dict[str, Any]:
    return {"object": "whatsapp_business_account", "entry": [{"id": "waba-1", "changes": [{"field": field, "value": value}]}]}


def wa_messages(*messages: dict[str, Any], contacts: list | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"messages": list(messages)}
    if contacts:
        value["contacts"] = contacts
    return wa_change("messages", value)


def wa_history(*messages: dict[str, Any]) -> dict[str, Any]:
    return wa_change("history", {"history": [{"threads": [{"id": NUMBER, "messages": list(messages)}]}]})


def dm(mid: str, text: str, ts_ms: int, *, echo: bool = False, obj: str = "page", attachments: list | None = None) -> dict[str, Any]:
    own = "page-1" if obj == "page" else "ig-1"
    sender, recipient = (own, "psid-1") if echo else ("psid-1", own)
    message: dict[str, Any] = {"mid": mid, "text": text}
    if echo:
        message["is_echo"] = True
    if attachments:
        message["attachments"] = attachments
    return {
        "object": obj,
        "entry": [{"id": own, "messaging": [{"sender": {"id": sender}, "recipient": {"id": recipient}, "timestamp": ts_ms, "message": message}]}],
    }


def graph_time(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S+0000")


class InboxCase(MetaTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        patcher = patch.object(board_store, "records_table", return_value=self.table)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Staff blobs use the in-memory store unless a test needs the bucket.
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        # A created task is checked as created. The seat does not start working on it here.
        runner = patch.object(board_staff, "run_step", lambda payload: None)
        runner.start()
        self.addCleanup(runner.stop)
        self.staff(True)

    def staff(self, enabled: bool) -> None:
        settings = board_store.load_settings(self.table)
        settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": enabled})
        board_store.save_settings(self.table, settings)

    def quiet(self) -> Any:
        return patch.object(board_meta_ingest, "follow_up", lambda items: None)

    def ingest(self, payload: dict[str, Any], *, follow: bool = False) -> dict[str, Any]:
        if follow:
            return board_meta.ingest_webhook(self.table, payload)
        with self.quiet():
            return board_meta.ingest_webhook(self.table, payload)

    def only_thread(self) -> dict[str, Any]:
        threads = board_store.list_meta_threads(self.table)
        self.assertEqual(len(threads), 1, threads)
        return threads[0]

    def messages(self, thread_id: str) -> list[dict[str, Any]]:
        return sorted(board_store.list_meta_messages(self.table, thread_id), key=lambda row: row["receivedAt"])

    def open_tasks(self) -> list[dict[str, Any]]:
        return [task for status in board_triage.OPEN_TASK_STATUSES for task in board_store.list_tasks(self.table, status)]

    def ctx(self, settings: dict[str, Any] | None = None) -> board_tools.ToolContext:
        return board_tools.ToolContext(table=self.table, settings=settings or board_store.load_settings(self.table), persona_id="coo", actor="persona")

    def organisation(self, stage: str = "contacted", **extra: Any) -> None:
        board_store.put_prospect(
            self.table,
            {"prospectId": "org-1", "name": "Harbour Club", "type": "provider", "stage": stage, "phone": f"+{NUMBER}", **extra},
        )


class HistoryTests(InboxCase):
    def test_imported_history_is_read_and_is_not_triaged(self) -> None:
        with patch.object(board_meta_triage, "route_unmatched") as routed:
            out = self.ingest(wa_history(wa("old-1", "a question from March", 1_690_000_000), wa("old-2", "and another", 1_690_000_100)), follow=True)
        self.assertEqual(out, {"stored": 2, "duplicates": 0})
        routed.assert_not_called()
        thread = self.only_thread()
        self.assertFalse(thread["unread"])
        self.assertEqual(thread["unreadCount"], 0)
        self.assertEqual(self.open_tasks(), [])

    def test_imported_history_still_links_an_organisation(self) -> None:
        self.organisation()
        self.ingest(wa_history(wa("old-1", "Saturday 9am at the court", 1_690_000_000)), follow=True)
        self.assertEqual(self.only_thread()["prospectId"], "org-1")
        self.assertEqual(_nn(board_store.get_prospect(self.table, "org-1"))["stage"], "replied")
        self.assertEqual(len(self.open_tasks()), 1)

    def test_a_live_message_is_unread_and_goes_to_triage(self) -> None:
        with patch.object(board_meta_triage, "route_unmatched") as routed:
            self.ingest(wa_messages(wa("new-1", "is there a class today?", 1_700_000_000)), follow=True)
        routed.assert_called_once()
        self.assertTrue(self.only_thread()["unread"])

    def test_decline_code_is_found_wherever_meta_puts_it(self) -> None:
        self.ingest(wa_change("history", {"history": [{"errors": [{"code": 2593109, "title": "declined"}]}]}))
        self.assertTrue(board_meta_whatsapp.status(self.table)["historyDeclined"])
        self.assertEqual(board_store.list_meta_threads(self.table), [])

    def test_contact_names_wait_for_the_thread(self) -> None:
        contact = {"type": "contact", "contact": {"full_name": "Harbour Club", "phone_number": NUMBER}}
        self.ingest(wa_change("smb_app_state_sync", {"state_sync": [contact]}))
        self.assertEqual(board_store.list_meta_threads(self.table), [])
        self.ingest(wa_history(wa("old-1", "hello", 1_690_000_000)))
        self.assertEqual(self.only_thread()["displayName"], "Harbour Club")


class ThreadSummaryTests(InboxCase):
    def test_an_older_message_does_not_replace_the_latest(self) -> None:
        self.ingest(wa_messages(wa("w-new", "newest message", 1_700_000_900)))
        self.ingest(wa_messages(wa("w-old", "older message", 1_600_000_000)))
        thread = self.only_thread()
        self.assertEqual(thread["text"], "newest message")
        self.assertTrue(thread["lastInboundAt"].startswith("2023-11-14"))
        self.assertEqual(thread["messageCount"], 2)

    def test_one_delivery_writes_each_thread_once(self) -> None:
        calls: list[str] = []
        real = board_store.put_meta_thread
        def _record(table: Any, doc: dict[str, Any]) -> Any:
            calls.append(doc["threadId"])
            return real(table, doc)

        with patch.object(board_store, "put_meta_thread", side_effect=_record):
            self.ingest(wa_messages(*[wa(f"w-{i}", f"message {i}", 1_700_000_000 + i) for i in range(30)]))
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.only_thread()["messageCount"], 30)

    def test_a_board_reply_and_its_echo_are_one_row(self) -> None:
        self.ingest(dm("m-in", "hello", 1_700_000_000_000))
        thread = self.only_thread()
        sent = {"ok": True, "messageId": "m-out", "threadId": thread["threadId"]}
        board_meta_inbox.record_outbound(self.ctx(), {"threadId": thread["threadId"], "message": "Call me on 9123 4567"}, sent)
        out = self.ingest(dm("m-out", "Call me on 9123 4567", 1_700_000_050_000, echo=True))
        self.assertEqual(out, {"stored": 0, "duplicates": 1})
        rows = [row for row in self.messages(thread["threadId"]) if row["messageId"] == "m-out"]
        self.assertEqual(len(rows), 1)
        self.assertNotIn("9123", rows[0]["textMasked"])
        self.assertIn("9123", rows[0]["text"])
        self.assertEqual(self.only_thread()["lastDirection"], "out")

    def test_whatsapp_and_instagram_echoes_stay_in_the_customer_thread(self) -> None:
        self.ingest(wa_messages(wa("w-in", "hello", 1_700_000_000)))
        self.ingest(wa_change("smb_message_echoes", {"message_echoes": [{"from": "85250001111", "to": NUMBER, "id": "w-out", "timestamp": "1700000100", "type": "text", "text": {"body": "hi there"}}]}))
        thread = self.only_thread()
        self.assertEqual([row["direction"] for row in self.messages(thread["threadId"])], ["in", "out"])
        self.assertFalse(board_meta._in_window({**thread, "lastInboundAt": ""}))
        self.ingest(dm("ig-in", "hello", 1_700_000_000_000, obj="instagram"))
        self.ingest(dm("ig-out", "hi", 1_700_000_100_000, obj="instagram", echo=True))
        instagram = [t for t in board_store.list_meta_threads(self.table) if t["channel"] == "instagram"]
        self.assertEqual(len(instagram), 1)
        self.assertEqual(instagram[0]["messageCount"], 2)


class BackfillTests(InboxCase):
    def conversation(self, *messages: dict[str, Any]) -> list[dict[str, Any]]:
        people = {"data": [{"id": "psid-1", "name": "Ada Wong"}, {"id": "page-1", "name": "Siu Tin Dei"}]}
        return [{"id": "t_conv", "participants": people, "messages": {"data": list(messages)}}]

    def run_backfill(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        def pages(_method: str, _path: str, params: dict[str, Any], **_kwargs: Any) -> list[dict[str, Any]]:
            return rows if params["platform"] == "messenger" else []

        with patch.object(board_meta, "graph_pages", side_effect=pages), patch.object(board_meta_backfill.board_meta_token, "linked_ig_user_id", return_value=""):
            return board_meta_backfill.backfill(self.table)

    def test_catch_up_stores_nothing_twice_and_keeps_a_read_thread_read(self) -> None:
        self.ingest(dm("m-1", "hello from a parent", 1_700_000_000_123))
        thread = self.only_thread()
        board_meta_inbox.mark_read(self.table, thread["threadId"])
        rows = self.conversation(
            {"id": "m-2", "message": "our reply from the page", "from": {"id": "page-1"}, "created_time": "2023-11-14T22:20:00+0000"},
            {"id": "m-1", "message": "hello from a parent", "from": {"id": "psid-1"}, "created_time": "2023-11-14T22:13:20+0000"},
        )
        with self.quiet():
            self.assertEqual(self.run_backfill(rows), {"inserted": 1})
            self.assertEqual(self.run_backfill(rows), {"inserted": 0})
        thread = self.only_thread()
        self.assertEqual([(row["messageId"], row["direction"]) for row in self.messages(thread["threadId"])], [("m-1", "in"), ("m-2", "out")])
        self.assertFalse(thread["unread"])
        self.assertEqual(thread["lastMessageAt"], "2023-11-14T22:20:00.000Z")
        self.assertEqual(thread["lastDirection"], "out")
        self.assertEqual(thread["displayName"], "Ada Wong")

    def test_catch_up_marks_a_message_the_webhook_missed_today(self) -> None:
        recent = datetime.now(timezone.utc) - timedelta(minutes=20)
        rows = self.conversation({"id": "m-9", "message": "are you open today?", "from": {"id": "psid-1"}, "created_time": graph_time(recent)})
        with patch.object(board_meta_triage, "route_unmatched") as routed:
            self.run_backfill(rows)
        thread = self.only_thread()
        self.assertTrue(thread["unread"])
        self.assertTrue(board_meta._in_window(thread))
        routed.assert_called_once()

    def test_catch_up_skips_a_conversation_without_the_other_party(self) -> None:
        rows = [{"id": "t_conv", "messages": {"data": [{"id": "m-1", "message": "x", "from": {"id": "page-1"}, "created_time": "2023-11-14T22:20:00+0000"}]}}]
        with self.quiet():
            self.assertEqual(self.run_backfill(rows), {"inserted": 0})
        self.assertEqual(board_store.list_meta_threads(self.table), [])


class MediaTests(InboxCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["ASSETS_BUCKET_NAME"] = "assets-test"
        self.s3 = MagicMock()
        self.s3.generate_presigned_url.side_effect = lambda _op, Params, ExpiresIn: f"https://signed.example/{Params['Key']}"
        patcher = patch.object(runtime, "_s3", self.s3)
        patcher.start()
        self.addCleanup(patcher.stop)

    def owner_get(self, path: str) -> tuple[int, dict[str, Any]]:
        out = board_routes.handle_board_route(BoardTestCase.event(path, "GET"), "GET", path, "owner")
        assert out is not None
        return out["statusCode"], json.loads(out["body"])

    def test_a_page_photo_is_stored_and_opens_for_the_owner(self) -> None:
        photo = [{"type": "image", "payload": {"url": "https://cdn.example.com/photo.jpg"}}]
        with patch.object(board_meta_attachments, "_fetch", return_value=b"jpeg-bytes") as fetch:
            self.ingest(dm("m-pic", "the timetable", 1_700_000_000_000, attachments=photo), follow=True)
        fetch.assert_called_once()
        thread = self.only_thread()
        stored = self.messages(thread["threadId"])[0]["attachments"][0]
        self.assertTrue(stored["key"].startswith("board/meta-media/"))
        self.assertNotIn("url", stored)
        status, body = self.owner_get(f"/siutindei/board/messages/{thread['threadId']}")
        attachment = body["messages"][0]["attachments"][0]
        self.assertTrue(attachment["stored"])
        self.assertNotIn("key", attachment)
        status, body = self.owner_get(f"/siutindei/board/messages/{thread['threadId']}/media/{attachment['ref']}")
        self.assertEqual(status, 200)
        self.assertTrue(body["url"].startswith("https://signed.example/board/meta-media/"))

    def test_a_whatsapp_photo_is_fetched_by_media_id_with_the_token(self) -> None:
        image = {"from": NUMBER, "id": "wamid.pic==", "timestamp": "1700000000", "type": "image", "image": {"id": "media-77", "mime_type": "image/jpeg", "caption": "Timetable"}}
        self.graph.queue.append({"url": "https://lookaside.example.com/media-77", "mime_type": "image/jpeg"})
        seen: dict[str, Any] = {}

        def fetch(url: str, headers: dict[str, str]) -> bytes:
            seen.update({"url": url, "auth": headers.get("Authorization")})
            return b"jpeg-bytes"

        with patch.object(board_meta_attachments, "_fetch", side_effect=fetch):
            self.ingest(wa_messages(image), follow=True)
        self.assertEqual(seen, {"url": "https://lookaside.example.com/media-77", "auth": "Bearer token-local"})
        thread = self.only_thread()
        self.assertEqual(self.messages(thread["threadId"])[0]["attachments"][0]["size"], len(b"jpeg-bytes"))
        self.assertEqual(self.s3.put_object.call_args.kwargs["ContentType"], "image/jpeg")

    def test_history_media_is_fetched_when_the_owner_first_opens_it(self) -> None:
        image = {"from": NUMBER, "id": "old-pic", "timestamp": "1690000000", "type": "image", "image": {"id": "media-old", "mime_type": "image/jpeg"}}
        with patch.object(board_meta_attachments, "_fetch", return_value=b"old-bytes") as fetch:
            self.ingest(wa_history(image), follow=True)
            fetch.assert_not_called()
            thread = self.only_thread()
            _, body = self.owner_get(f"/siutindei/board/messages/{thread['threadId']}")
            attachment = body["messages"][0]["attachments"][0]
            self.assertFalse(attachment["stored"])
            self.graph.queue.append({"url": "https://lookaside.example.com/media-old", "mime_type": "image/jpeg"})
            status, body = self.owner_get(f"/siutindei/board/messages/{thread['threadId']}/media/{attachment['ref']}")
        self.assertEqual(status, 200)
        fetch.assert_called_once()

    def test_media_meta_no_longer_serves_is_reported(self) -> None:
        image = {"from": NUMBER, "id": "gone", "timestamp": "1690000000", "type": "image", "image": {"id": "media-gone"}}
        self.ingest(wa_history(image))
        thread = self.only_thread()
        _, body = self.owner_get(f"/siutindei/board/messages/{thread['threadId']}")
        ref = body["messages"][0]["attachments"][0]["ref"]
        with patch.object(board_meta_attachments, "_fetch", return_value=None):
            status, body = self.owner_get(f"/siutindei/board/messages/{thread['threadId']}/media/{ref}")
        self.assertEqual(status, 404)
        self.assertIn("no longer available", body["message"])
        status, _ = self.owner_get(f"/siutindei/board/messages/{thread['threadId']}/media/not-a-ref")
        self.assertEqual(status, 404)

    def test_a_file_a_browser_could_run_is_downloaded_not_shown(self) -> None:
        url = board_meta_attachments.presign({"key": "board/meta-media/t/m/0", "mime": "text/html"})
        self.assertTrue(url)
        params = self.s3.generate_presigned_url.call_args.kwargs["Params"]
        self.assertEqual(params["ResponseContentDisposition"], "attachment")
        self.assertEqual(params["ResponseContentType"], "application/octet-stream")
        self.assertEqual(board_meta_attachments.presign({"key": "somewhere/else", "mime": "image/png"}), "")


class MaskingTests(InboxCase):
    def setUp(self) -> None:
        super().setUp()
        contacts = [{"wa_id": NUMBER, "profile": {"name": "Ada Wong"}}]
        self.ingest(wa_messages(wa("w-1", "Please call 9123 4567", 1_700_000_000), contacts=contacts))
        self.thread_id = self.only_thread()["threadId"]

    def test_staff_tools_get_an_alias_in_place_of_the_name(self) -> None:
        listed = board_meta_inbox.op_list_threads(self.ctx(), {})["threads"][0]
        detail = board_meta_inbox.op_get_thread(self.ctx(), {"threadId": self.thread_id})
        self.assertRegex(listed["displayName"], r"^phone#\d+$")
        self.assertEqual(detail["messages"][0]["senderName"], listed["displayName"])
        self.assertNotIn("Ada", json.dumps([listed, detail]))
        self.assertNotIn("9123", json.dumps([listed, detail]))
        self.assertNotIn("ref", detail["messages"][0])

    def test_the_owner_still_sees_the_name_and_the_number(self) -> None:
        owner = board_meta_inbox.thread_for_owner(self.table, self.thread_id)
        assert owner is not None
        self.assertEqual(owner["thread"]["displayName"], "Ada Wong")
        self.assertEqual(owner["thread"]["phone"], NUMBER)
        self.assertIn("9123", owner["messages"][0]["text"])

    def test_a_key_without_pii_gets_no_name_number_or_account_id(self) -> None:
        def as_key(path: str, body: dict[str, Any]) -> dict[str, Any]:
            out = board_public_api.redact_board_response(path, {"statusCode": 200, "body": json.dumps(body)}, ["siutindei-board-full"])
            return json.loads(out["body"])

        listed = as_key("/v1/partner/siutindei/board/messages", board_meta_inbox.list_for_owner(self.table))
        self.assertEqual(listed["threads"][0]["displayName"], "contact#hidden")
        self.assertEqual(listed["threads"][0]["phone"], "phone#hidden")
        detail = as_key(f"/v1/partner/siutindei/board/messages/{self.thread_id}", _nn(board_meta_inbox.thread_for_owner(self.table, self.thread_id)))
        self.assertEqual(detail["messages"][0]["senderName"], "contact#hidden")
        self.assertNotIn("Ada", json.dumps([listed, detail]))
        self.assertNotIn("9123", json.dumps([listed, detail]))
        board_store.put_cache(self.table, "meta:whatsapp", {"phoneNumberId": "222", "wabaId": "111", "connectedAt": "2026-11-18T00:00:00.000Z", "displayPhoneNumber": "+852 5000 1111"})
        status = as_key("/v1/partner/siutindei/board/messages/status", board_meta_inbox.status(self.table))
        self.assertTrue(status["whatsapp"]["connected"])
        for hidden in ("phoneNumberId", "wabaId", "displayPhoneNumber", "verifiedName"):
            self.assertNotIn(hidden, status["whatsapp"])


class OrganisationTests(InboxCase):
    def test_an_organisation_behind_two_hundred_other_prospects_is_found(self) -> None:
        for i in range(205):
            board_store.put_prospect(self.table, {"prospectId": f"d-{i:03d}", "name": f"Studio number {i}", "type": "provider", "stage": "discovered", "phone": ""})
        self.organisation()
        index = board_meta_triage.ProspectIndex(self.table)
        found = index.match({"channel": "whatsapp", "senderId": NUMBER})
        self.assertEqual((found or {}).get("prospectId"), "org-1")

    def test_an_instagram_thread_matches_on_the_exact_name(self) -> None:
        self.organisation(phone="")
        index = board_meta_triage.ProspectIndex(self.table)
        self.assertEqual((index.match({"channel": "instagram", "senderId": "igsid-1", "displayName": "Harbour  CLUB"}) or {}).get("prospectId"), "org-1")
        self.assertIsNone(index.match({"channel": "instagram", "senderId": "igsid-2", "displayName": "Harbour"}))
        self.assertIsNone(index.match({"channel": "page", "senderId": "psid-3", "displayName": ""}))

    def test_a_listed_organisation_keeps_its_stage(self) -> None:
        for stage in ("listed", "onboarding", "declined", "suppressed"):
            self.organisation(stage)
            self.ingest(wa_messages(wa(f"w-{stage}", "Saturday 9am", 1_700_000_000)), follow=True)
            self.assertEqual(_nn(board_store.get_prospect(self.table, "org-1"))["stage"], stage)
        self.assertEqual(len(self.open_tasks()), 1)

    def test_staff_switched_off_raises_nothing_and_still_links_the_thread(self) -> None:
        self.organisation()
        self.staff(False)
        self.ingest(wa_messages(wa("w-1", "Saturday 9am", 1_700_000_000)), follow=True)
        self.assertEqual(self.only_thread()["prospectId"], "org-1")
        self.assertEqual(self.open_tasks(), [])

    def test_one_failing_message_does_not_stop_the_rest(self) -> None:
        self.organisation()
        self.ingest(dm("m-a", "first", 1_700_000_000_000))
        self.ingest(wa_messages(wa("w-b", "Saturday 9am", 1_700_000_000)))
        items = [{"threadId": t["threadId"], "messageId": "m-a" if t["channel"] == "page" else "w-b", "mode": "live"} for t in board_store.list_meta_threads(self.table)]
        items.sort(key=lambda item: item["messageId"])
        with patch.object(board_meta_triage, "route_unmatched", side_effect=board_staff.StaffError("boom")):
            board_meta_inbox.handle_after_ingest({"items": items})
        self.assertEqual(len(self.open_tasks()), 1)

    def test_a_later_message_is_added_to_the_open_catalog_task(self) -> None:
        self.organisation()
        self.ingest(wa_messages(wa("w-1", "Saturday 9am", 1_700_000_000)), follow=True)
        self.ingest(wa_messages(wa("w-2", "Sorry, 10am. Call 9123 4567", 1_700_000_500)), follow=True)
        tasks = self.open_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["deliverableType"], "json")
        self.assertGreater(int(tasks[0].get("scratchpadChars") or 0), 0)

    def test_a_reply_addressed_by_number_is_held_for_an_organisation(self) -> None:
        self.organisation()
        self.ingest(wa_messages(wa("w-1", "Saturday 9am", int(datetime.now(timezone.utc).timestamp()))), follow=True)
        thread = self.only_thread()
        settings = board_store.load_settings(self.table)
        settings["tools"]["globalMode"] = "act"
        settings["tools"]["allowList"] = [f"+{NUMBER}"]
        settings = board_store.save_settings(self.table, settings)
        guard = board_tools.REGISTRY["meta_reply_whatsapp"].act_guard
        for args in ({"threadId": thread["threadId"]}, {"to": f"+{NUMBER}"}):
            assert guard is not None
            self.assertIn("owner's approval", guard(self.ctx(settings), {**args, "message": "Thanks", "reason": "reply"}) or "")
        self.assertIsNone(board_meta_inbox.organisation_hold(self.table, {"to": "+85260002222"}))


class ProfileTests(InboxCase):
    def test_a_page_thread_gets_the_sender_name_once(self) -> None:
        self.graph.queue.append({"name": "Ada Wong", "id": "psid-1"})
        with patch.object(board_meta_triage, "route_unmatched"):
            self.ingest(dm("m-1", "hello", 1_700_000_000_000), follow=True)
            self.assertEqual(self.only_thread()["displayName"], "Ada Wong")
            before = len(self.graph.calls)
            self.ingest(dm("m-2", "again", 1_700_000_100_000), follow=True)
        self.assertEqual(len(self.graph.calls), before)

    def test_a_refused_profile_read_is_not_repeated(self) -> None:
        import board_meta_profile

        self.ingest(dm("m-1", "hello", 1_700_000_000_000))
        self.graph.queue.append(board_meta.MetaError("Meta Graph 400: no permission", status=400))
        board_meta_profile.fill_name(self.table, self.only_thread())
        asked = len(self.graph.calls)
        board_meta_profile.fill_name(self.table, self.only_thread())
        self.assertEqual(asked, 1)
        self.assertEqual(len(self.graph.calls), asked)
        self.assertEqual(self.only_thread()["displayName"], "")


class WhatsAppConnectTests(InboxCase):
    def numbers(self, **extra: Any) -> dict[str, Any]:
        return {"data": [{"id": "222", "display_phone_number": "+852 5000 1111", "verified_name": "Siu Tin Dei", **extra}]}

    def test_connect_checks_the_number_with_meta_first(self) -> None:
        self.graph.queue.extend([self.numbers(is_on_biz_app=True, platform_type="CLOUD_API"), {"success": True}])
        out = board_meta_whatsapp.connect(self.table, {"wabaId": "111", "phoneNumberId": "222"})
        self.assertTrue(out["connected"])
        self.assertTrue(out["onBusinessApp"])
        self.assertEqual(out["displayPhoneNumber"], "+852 5000 1111")
        self.assertEqual([call[0] for call in self.graph.calls[-2:]], ["GET", "POST"])
        self.assertIn("111/subscribed_apps", self.graph.calls[-1][1])

    def test_connect_refuses_a_number_meta_does_not_list(self) -> None:
        self.graph.queue.append(self.numbers())
        with self.assertRaises(board_meta.MetaError) as raised:
            board_meta_whatsapp.connect(self.table, {"wabaId": "111", "phoneNumberId": "999"})
        self.assertIn("does not list", str(raised.exception))
        self.assertFalse(board_meta_whatsapp.status(self.table)["connected"])
        self.assertFalse([call for call in self.graph.calls if call[0] == "POST"])

    def test_an_id_in_the_environment_alone_is_not_connected(self) -> None:
        self.assertEqual(board_meta_whatsapp.status(self.table)["phoneNumberId"], "wa-phone-1")
        self.assertFalse(board_meta_whatsapp.status(self.table)["connected"])
        with self.assertRaises(board_meta.MetaError):
            board_meta_whatsapp.sync_history(self.table)

    def test_a_failed_import_step_can_be_retried_and_a_finished_one_cannot(self) -> None:
        self.graph.queue.extend([self.numbers(), {"success": True}])
        board_meta_whatsapp.connect(self.table, {"wabaId": "111", "phoneNumberId": "222"})
        sent: list[str] = []
        fail = {"history": True}

        def graph(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            sync_type = kwargs["body"]["sync_type"]
            sent.append(sync_type)
            if sync_type == "history" and fail["history"]:
                raise board_meta.MetaError("Meta Graph 400: try later", status=400)
            return {"request_id": f"req-{sync_type}"}

        with patch.object(board_meta, "graph", side_effect=graph):
            with self.assertRaises(board_meta.MetaError):
                board_meta_whatsapp.sync_history(self.table)
            status = board_meta_whatsapp.status(self.table)["sync"]
            self.assertFalse(status["done"])
            self.assertIn("try later", status["history"]["error"])
            fail["history"] = False
            done = board_meta_whatsapp.sync_history(self.table)
            with self.assertRaises(board_meta.MetaError) as again:
                board_meta_whatsapp.sync_history(self.table)
        self.assertTrue(done["done"])
        self.assertEqual(sent, ["smb_app_state_sync", "history", "history"])
        self.assertIn("already ran", str(again.exception))

    def test_a_second_click_while_the_import_runs_is_refused(self) -> None:
        self.graph.queue.extend([self.numbers(), {"success": True}])
        board_meta_whatsapp.connect(self.table, {"wabaId": "111", "phoneNumberId": "222"})
        outcomes: list[str] = []

        def graph(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            if kwargs["body"]["sync_type"] == "smb_app_state_sync":
                try:
                    board_meta_whatsapp.sync_history(self.table)
                except board_meta.MetaError as exc:
                    outcomes.append(str(exc))
            return {"request_id": "req"}

        with patch.object(board_meta, "graph", side_effect=graph):
            board_meta_whatsapp.sync_history(self.table)
        self.assertEqual(outcomes, ["WhatsApp history sync is already running"])


class RouteTests(InboxCase):
    def test_subscribing_the_page_names_the_fields(self) -> None:
        path = "/siutindei/board/messages/connect/page"
        self.graph.queue.append({"success": True})
        out = board_routes.handle_board_route(BoardTestCase.event(path, "POST", {}), "POST", path, "owner")
        assert out is not None
        self.assertEqual(out["statusCode"], 200)
        self.assertIn("message_echoes", json.loads(out["body"])["fields"])
        self.assertIn("page-1/subscribed_apps", self.graph.calls[-1][1])
        with patch.dict(os.environ, {"META_PAGE_ID": ""}):
            out = board_routes.handle_board_route(BoardTestCase.event(path, "POST", {}), "POST", path, "owner")
        assert out is not None
        self.assertEqual(out["statusCode"], 400)

    def test_a_stored_timestamp_has_one_format(self) -> None:
        self.assertEqual(board_meta_store.received_at("1700000000", "x"), "2023-11-14T22:13:20.000Z")
        self.assertEqual(board_meta_store.received_at(1_700_000_000_123, "x"), "2023-11-14T22:13:20.123Z")
        self.assertEqual(board_meta_store.received_at("2023-11-14T22:13:20+0000", "x"), "2023-11-14T22:13:20.000Z")
        self.assertEqual(board_meta_store.received_at("", "fallback"), "fallback")
        self.assertEqual(board_meta_store.received_at("not a date", "fallback"), "fallback")


if __name__ == "__main__":
    unittest.main()

from typing import TypeVar

_T = TypeVar("_T")

def _nn(value: _T | None) -> _T:
    assert value is not None
    return value
