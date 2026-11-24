"""Stored LinkedIn attachments: GIF and MP4, pictures unchanged."""

from __future__ import annotations

import unittest

from test_support import FakeTable, install_aws_stubs

install_aws_stubs()

import linkedin_media  # noqa: E402
import linkedin_store  # noqa: E402
from linkedin_store import LinkedInError  # noqa: E402


def _mp4(size: int, brand: bytes = b"isom") -> bytes:
    data = bytearray(size)
    data[4:8] = b"ftyp"
    data[8:12] = brand
    return bytes(data)


def _gif(size: int = 16) -> bytes:
    data = bytearray(b"GIF89a")
    data.extend(b"\x00" * max(0, size - 6))
    return bytes(data)


class LinkedInMediaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = FakeTable()

    def _draft(self) -> dict:
        return linkedin_store.create_post(self.table, {"body": "A short hook.\n\nOne concrete detail."})

    def test_a_gif_is_stored_and_a_character_photo_is_not(self) -> None:
        doc = self._draft()
        saved = linkedin_store.save_post_image(self.table, doc["postId"], "image/gif", _gif())
        self.assertEqual(saved["image"]["contentType"], "image/gif")
        loaded = linkedin_store.load_post_image(doc["postId"])
        assert loaded is not None  # nosec B101
        self.assertEqual(loaded[0], "image/gif")
        self.assertTrue(loaded[1].startswith(b"GIF89a"))
        with self.assertRaises(LinkedInError) as caught:
            linkedin_store.save_character_photo(self.table, "image/gif", _gif())
        self.assertIn("PNG or JPEG", str(caught.exception))

    def test_a_gif_over_3_mb_or_without_the_header_is_rejected(self) -> None:
        doc = self._draft()
        with self.assertRaises(LinkedInError) as over:
            linkedin_store.save_post_image(
                self.table, doc["postId"], "image/gif", _gif(linkedin_media.GIF_BYTE_MAX + 1)
            )
        self.assertIn("3 MB", str(over.exception))
        with self.assertRaises(LinkedInError) as header:
            linkedin_store.save_post_image(self.table, doc["postId"], "image/gif", b"not-a-gif-file!!")
        self.assertIn("not a GIF", str(header.exception))

    def test_an_h264_mp4_is_stored_and_a_quicktime_file_is_not(self) -> None:
        doc = self._draft()
        blob = _mp4(linkedin_media.VIDEO_BYTE_MIN)
        saved = linkedin_store.save_post_image(self.table, doc["postId"], "video/mp4", blob)
        self.assertEqual(saved["image"]["contentType"], "video/mp4")
        self.assertEqual(saved["image"]["mediaUrn"], "")
        public = linkedin_store.public_image(saved["image"])
        assert public is not None  # nosec B101
        self.assertEqual(public["contentType"], "video/mp4")
        self.assertNotIn("mediaUrn", public)
        with self.assertRaises(LinkedInError) as quicktime:
            linkedin_store.save_post_image(self.table, doc["postId"], "video/mp4", _mp4(80_000, b"qt  "))
        self.assertIn("not an MP4", str(quicktime.exception))

    def test_a_video_under_75_kb_or_over_3_mb_is_rejected(self) -> None:
        doc = self._draft()
        with self.assertRaises(LinkedInError) as small:
            linkedin_store.save_post_image(self.table, doc["postId"], "video/mp4", _mp4(1024))
        self.assertIn("75 KB", str(small.exception))
        with self.assertRaises(LinkedInError) as large:
            linkedin_store.save_post_image(
                self.table, doc["postId"], "video/mp4", _mp4(linkedin_media.VIDEO_BYTE_MAX + 1)
            )
        self.assertIn("3 MB", str(large.exception))

    def test_replacing_the_attachment_drops_a_saved_video_urn(self) -> None:
        doc = self._draft()
        saved = linkedin_store.save_post_image(self.table, doc["postId"], "video/mp4", _mp4(80_000))
        saved["image"]["mediaUrn"] = "urn:li:video:old"
        linkedin_store.put_post(self.table, saved)
        replaced = linkedin_store.save_post_image(self.table, doc["postId"], "image/gif", _gif())
        self.assertEqual(replaced["image"]["mediaUrn"], "")
        self.assertEqual(replaced["image"]["contentType"], "image/gif")

    def test_a_png_over_1_5_mb_is_still_rejected(self) -> None:
        doc = self._draft()
        blob = b"\x89PNG\r\n\x1a\n" + b"x" * linkedin_store.IMAGE_BYTE_MAX
        with self.assertRaises(LinkedInError) as caught:
            linkedin_store.save_post_image(self.table, doc["postId"], "image/png", blob)
        self.assertIn("1.5 MB", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
