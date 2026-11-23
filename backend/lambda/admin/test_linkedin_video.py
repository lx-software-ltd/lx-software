"""LinkedIn video upload and publish."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from test_support import FakeTable, install_aws_stubs

install_aws_stubs()

import linkedin  # noqa: E402
import linkedin_api  # noqa: E402
import linkedin_image  # noqa: E402
import linkedin_media  # noqa: E402
import linkedin_store  # noqa: E402
import linkedin_video  # noqa: E402
import runtime  # noqa: E402
from linkedin_api import LinkedInApiError  # noqa: E402
from linkedin_store import HKT  # noqa: E402
from timeutil import format_iso_millis  # noqa: E402


def _recent_slot(minutes: int = 20) -> str:
    return format_iso_millis(datetime.now(HKT) - timedelta(minutes=minutes))


def _mp4(size: int = 80_000) -> bytes:
    data = bytearray(size)
    data[4:8] = b"ftyp"
    data[8:12] = b"isom"
    return bytes(data)


def _connection() -> dict:
    return {
        "accessToken": "token-1",
        "refreshToken": "refresh-1",
        "tokenExpiresAt": "2099-01-01T00:00:00.000Z",
        "memberId": "member1",
        "memberName": "Example Member",
        "channel": "profile",
    }


class LinkedInVideoUploadTests(unittest.TestCase):
    def tearDown(self) -> None:
        linkedin_api.set_transport_for_tests(None)

    def test_upload_puts_each_range_and_finalizes_in_order(self) -> None:
        data = _mp4(10)
        seen: list[tuple[str, str, dict, bytes | None]] = []

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            seen.append((method, url, headers, body))
            if url.endswith("/videos?action=initializeUpload"):
                payload = {
                    "value": {
                        "video": "urn:li:video:1",
                        "uploadToken": "",
                        "uploadInstructions": [
                            {"uploadUrl": "https://upload.example/0", "firstByte": 0, "lastByte": 4},
                            {"uploadUrl": "https://upload.example/1", "firstByte": 5, "lastByte": 9},
                        ],
                    }
                }
                return 200, {}, json.dumps(payload).encode()
            if url == "https://upload.example/0":
                return 200, {"ETag": '"part-a"'}, b""
            if url == "https://upload.example/1":
                return 200, {"ETag": 'W/"part-b"'}, b""
            if url.endswith("/videos?action=finalizeUpload"):
                return 200, {}, b""
            return 404, {}, b'{"message":"missing"}'

        linkedin_api.set_transport_for_tests(transport)
        urn = linkedin_video.upload_video("token", "urn:li:person:member1", data)
        self.assertEqual(urn, "urn:li:video:1")
        init = json.loads(seen[0][3] or b"{}")
        self.assertEqual(init["initializeUploadRequest"]["fileSizeBytes"], len(data))
        self.assertNotIn("authorization", {key.lower() for key in seen[1][2]})
        self.assertEqual(seen[1][3], data[0:5])
        self.assertEqual(seen[2][3], data[5:10])
        final = json.loads(seen[3][3] or b"{}")
        self.assertEqual(
            final["finalizeUploadRequest"],
            {"video": "urn:li:video:1", "uploadToken": "", "uploadedPartIds": ["part-a", "part-b"]},
        )

    def test_a_part_without_an_etag_fails(self) -> None:
        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers, body
            if url.endswith("/videos?action=initializeUpload"):
                payload = {
                    "value": {
                        "video": "urn:li:video:1",
                        "uploadToken": "tok",
                        "uploadInstructions": [
                            {"uploadUrl": "https://upload.example/0", "firstByte": 0, "lastByte": 9}
                        ],
                    }
                }
                return 200, {}, json.dumps(payload).encode()
            return 200, {}, b""

        linkedin_api.set_transport_for_tests(transport)
        with self.assertRaises(LinkedInApiError):
            linkedin_video.upload_video("token", "urn:li:person:member1", _mp4(10))


class LinkedInVideoPublishTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = FakeTable()
        patcher = patch.object(runtime, "_ddb")
        mock_ddb = patcher.start()
        self.addCleanup(patcher.stop)
        mock_ddb.Table.return_value = self.table
        self.env = patch.dict(
            "os.environ",
            {"RECORDS_TABLE_NAME": "records-test", "LINKEDIN_ENABLED": "true", "LINKEDIN_PUBLISH_ENABLED": "true"},
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        linkedin_store.save_connection(self.table, _connection())
        linkedin_store.save_settings(
            self.table,
            {**linkedin_store.default_settings(), "notifyEmail": "owner@example.com"},
        )

    def tearDown(self) -> None:
        linkedin_api.set_transport_for_tests(None)

    def _approved(self, body: str = "A short hook.\n\nWith a clip.") -> dict:
        doc = linkedin_store.create_post(self.table, {"body": body, "hashtags": []})
        doc["status"] = "approved"
        doc["slotAt"] = _recent_slot()
        return linkedin_store.put_post(self.table, doc)

    def test_a_gif_still_uses_the_image_upload(self) -> None:
        doc = self._approved()
        linkedin_store.save_post_image(self.table, doc["postId"], "image/gif", b"GIF89a" + b"x" * 10)
        posts: list[bytes] = []

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers
            if url.endswith("/images?action=initializeUpload"):
                return 200, {}, b'{"value":{"uploadUrl":"https://upload.example/img","image":"urn:li:image:9"}}'
            if url == "https://upload.example/img":
                return 201, {}, b""
            if url.endswith("/posts"):
                posts.append(body or b"")
                return 201, {"x-restli-id": "urn:li:share:9"}, b""
            return 200, {}, b'{"likesSummary":{"totalLikes":0},"commentsSummary":{"aggregatedTotalComments":0}}'

        linkedin_api.set_transport_for_tests(transport)
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true", "LINKEDIN_ENABLED": "true"}):
            with patch.object(linkedin, "send_notice", return_value=True):
                result = linkedin.handle_publish_due({})
        self.assertEqual(result["published"], 1)
        self.assertIn(b"urn:li:image:9", posts[0])

    def test_a_processing_video_waits_and_the_next_tick_posts_it(self) -> None:
        doc = self._approved()
        linkedin_store.save_post_image(self.table, doc["postId"], "video/mp4", _mp4())
        calls: list[str] = []
        status = {"value": "PROCESSING"}

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers, body
            calls.append(url)
            if url.endswith("/videos?action=initializeUpload"):
                payload = {
                    "value": {
                        "video": "urn:li:video:7",
                        "uploadToken": "",
                        "uploadInstructions": [
                            {"uploadUrl": "https://upload.example/v", "firstByte": 0, "lastByte": len(_mp4()) - 1}
                        ],
                    }
                }
                return 200, {}, json.dumps(payload).encode()
            if url == "https://upload.example/v":
                return 200, {"ETag": '"only"'}, b""
            if url.endswith("/videos?action=finalizeUpload"):
                return 200, {}, b""
            if "/videos/" in url:
                return 200, {}, json.dumps({"status": status["value"]}).encode()
            if url.endswith("/posts"):
                return 201, {"x-restli-id": "urn:li:share:7"}, b""
            return 200, {}, b'{"likesSummary":{"totalLikes":1},"commentsSummary":{"aggregatedTotalComments":0}}'

        linkedin_api.set_transport_for_tests(transport)
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true", "LINKEDIN_ENABLED": "true"}):
            with patch.object(linkedin, "send_notice", return_value=True):
                first = linkedin.handle_publish_due({})
        stored = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(first["published"], 0)
        self.assertEqual(stored["status"], "approved")
        self.assertEqual(int(stored.get("publishAttempts") or 0), 0)
        self.assertEqual(stored["image"]["mediaUrn"], "urn:li:video:7")
        self.assertEqual(stored["image"]["mediaOwner"], "urn:li:person:member1")
        self.assertEqual(stored.get("publishError") or "", "")
        self.assertFalse(stored.get("dueNotifiedAt"))
        self.assertEqual(sum(1 for url in calls if url.endswith("/videos?action=initializeUpload")), 1)

        status["value"] = "AVAILABLE"
        calls.clear()
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true", "LINKEDIN_ENABLED": "true"}):
            with patch.object(linkedin, "send_notice", return_value=True):
                second = linkedin.handle_publish_due({})
        posted = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(second["published"], 1)
        self.assertEqual(posted["status"], "published")
        self.assertEqual(posted["platform"]["urn"], "urn:li:share:7")
        self.assertFalse(any(url.endswith("/videos?action=initializeUpload") for url in calls))
        self.assertTrue(any("/videos/" in url for url in calls))

    def test_a_failed_video_process_can_be_uploaded_again(self) -> None:
        doc = self._approved()
        linkedin_store.save_post_image(self.table, doc["postId"], "video/mp4", _mp4())
        doc = linkedin_store.get_post(self.table, doc["postId"])
        doc["image"]["mediaUrn"] = "urn:li:video:bad"
        doc["image"]["mediaOwner"] = "urn:li:person:member1"
        linkedin_store.put_post(self.table, doc)

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers, body
            if "/videos/" in url:
                return 200, {}, b'{"status":"PROCESSING_FAILED"}'
            return 404, {}, b""

        linkedin_api.set_transport_for_tests(transport)
        with self.assertRaises(LinkedInApiError):
            linkedin.publish_one(self.table, linkedin_store.get_post(self.table, doc["postId"]))
        stored = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(stored["image"].get("mediaUrn") or "", "")
        self.assertEqual(linkedin_media.VIDEO_BYTE_MAX, 3_000_000)
        self.assertEqual(linkedin_media.VIDEO_BYTE_MIN, 75_000)

    def test_a_processing_video_does_not_block_the_next_post_or_send_a_failure(self) -> None:
        video = self._approved("A short hook.\n\nThe clip.")
        video["slotAt"] = _recent_slot(40)
        linkedin_store.put_post(self.table, video)
        linkedin_store.save_post_image(self.table, video["postId"], "video/mp4", _mp4())
        later = self._approved("A short hook.\n\nThe text.")
        later["slotAt"] = _recent_slot(10)
        linkedin_store.put_post(self.table, later)
        posts: list[bytes] = []

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers
            if url.endswith("/videos?action=initializeUpload"):
                payload = {
                    "value": {
                        "video": "urn:li:video:wait",
                        "uploadToken": "",
                        "uploadInstructions": [
                            {"uploadUrl": "https://upload.example/v", "firstByte": 0, "lastByte": len(_mp4()) - 1}
                        ],
                    }
                }
                return 200, {}, json.dumps(payload).encode()
            if url == "https://upload.example/v":
                return 200, {"ETag": '"only"'}, b""
            if url.endswith("/videos?action=finalizeUpload"):
                return 200, {}, b""
            if "/videos/" in url:
                return 200, {}, b'{"status":"WAITING_UPLOAD"}'
            if url.endswith("/posts"):
                posts.append(body or b"")
                return 201, {"x-restli-id": "urn:li:share:later"}, b""
            return 200, {}, b'{"likesSummary":{"totalLikes":0},"commentsSummary":{"aggregatedTotalComments":0}}'

        linkedin_api.set_transport_for_tests(transport)
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true", "LINKEDIN_ENABLED": "true"}):
            with patch.object(linkedin, "send_notice", return_value=True) as send:
                result = linkedin.handle_publish_due({})
        waiting = linkedin_store.get_post(self.table, video["postId"])
        posted = linkedin_store.get_post(self.table, later["postId"])
        self.assertEqual(result["published"], 1)
        self.assertEqual(result["reminded"], 0)
        self.assertEqual(send.call_count, 0)
        self.assertEqual(waiting["status"], "approved")
        self.assertEqual(waiting.get("publishError") or "", "")
        self.assertEqual(int(waiting.get("publishAttempts") or 0), 0)
        self.assertFalse(waiting.get("dueNotifiedAt"))
        self.assertEqual(posted["status"], "published")
        self.assertIn(b"The text.", posts[0])

        waiting["slotAt"] = "2020-01-01T00:30:00.000Z"
        linkedin_store.put_post(self.table, waiting)
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true", "LINKEDIN_ENABLED": "true"}):
            with patch.object(linkedin, "send_notice", return_value=True) as send:
                stale = linkedin.handle_publish_due({})
        self.assertEqual(stale["reminded"], 1)
        self.assertIn("three hours", send.call_args.args[2])
        self.assertNotIn("still processing", send.call_args.args[2])

    def test_a_redraw_keeps_the_video_id_and_a_later_tick_does_not_upload_again(self) -> None:
        doc = self._approved()
        linkedin_store.save_post_image(self.table, doc["postId"], "video/mp4", _mp4())
        with patch("board_async.try_invoke_event", return_value=True):
            queued = linkedin_image.queue_for_post(
                self.table, doc["postId"], scene="A desk.", caption="New line.", force=True
            )
        self.assertEqual(queued["image"]["status"], "pending")
        self.assertEqual(queued["image"]["held"]["contentType"], "video/mp4")
        uploads: list[str] = []

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers, body
            uploads.append(url)
            if url.endswith("/videos?action=initializeUpload"):
                payload = {
                    "value": {
                        "video": "urn:li:video:held",
                        "uploadToken": "",
                        "uploadInstructions": [
                            {"uploadUrl": "https://upload.example/v", "firstByte": 0, "lastByte": len(_mp4()) - 1}
                        ],
                    }
                }
                return 200, {}, json.dumps(payload).encode()
            if url == "https://upload.example/v":
                return 200, {"ETag": '"only"'}, b""
            if url.endswith("/videos?action=finalizeUpload"):
                return 200, {}, b""
            if "/videos/" in url:
                return 200, {}, b'{"status":"PROCESSING"}'
            return 404, {}, b""

        linkedin_api.set_transport_for_tests(transport)
        with self.assertRaises(LinkedInApiError):
            linkedin.publish_one(self.table, linkedin_store.get_post(self.table, doc["postId"]))
        stored = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(stored["image"]["held"]["mediaUrn"], "urn:li:video:held")
        self.assertEqual(stored["image"]["held"]["mediaOwner"], "urn:li:person:member1")
        self.assertEqual(stored["image"].get("mediaUrn") or "", "")
        uploads.clear()
        with self.assertRaises(LinkedInApiError):
            linkedin.publish_one(self.table, stored)
        self.assertFalse(any(url.endswith("/videos?action=initializeUpload") for url in uploads))

    def test_a_video_for_the_profile_is_uploaded_again_for_the_page(self) -> None:
        doc = self._approved()
        linkedin_store.save_post_image(self.table, doc["postId"], "video/mp4", _mp4())
        stored = linkedin_store.get_post(self.table, doc["postId"])
        stored["image"]["mediaUrn"] = "urn:li:video:person"
        stored["image"]["mediaOwner"] = "urn:li:person:member1"
        linkedin_store.put_post(self.table, stored)
        connection = _connection()
        connection["channel"] = "page"
        connection["organizationId"] = "99"
        linkedin_store.save_connection(self.table, connection)
        owners: list[str] = []

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers
            if url.endswith("/videos?action=initializeUpload"):
                owners.append(str(json.loads(body or b"{}")["initializeUploadRequest"]["owner"]))
                payload = {
                    "value": {
                        "video": "urn:li:video:page",
                        "uploadToken": "",
                        "uploadInstructions": [
                            {"uploadUrl": "https://upload.example/v", "firstByte": 0, "lastByte": len(_mp4()) - 1}
                        ],
                    }
                }
                return 200, {}, json.dumps(payload).encode()
            if url == "https://upload.example/v":
                return 200, {"ETag": '"only"'}, b""
            if url.endswith("/videos?action=finalizeUpload"):
                return 200, {}, b""
            if "/videos/" in url:
                return 200, {}, b'{"status":"AVAILABLE"}'
            if url.endswith("/posts"):
                return 201, {"x-restli-id": "urn:li:share:page"}, b""
            return 200, {}, b'{"likesSummary":{"totalLikes":0},"commentsSummary":{"aggregatedTotalComments":0}}'

        linkedin_api.set_transport_for_tests(transport)
        posted = linkedin.publish_one(self.table, linkedin_store.get_post(self.table, doc["postId"]))
        self.assertEqual(owners, ["urn:li:organization:99"])
        self.assertEqual(posted["status"], "published")


if __name__ == "__main__":
    unittest.main()
