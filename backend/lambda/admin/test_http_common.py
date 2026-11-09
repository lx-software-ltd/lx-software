"""Unit tests for shared HTTP helpers."""

from __future__ import annotations

import io
import unittest
import urllib.error

from test_support import install_aws_stubs

install_aws_stubs()

from http_common import _close_http_error, _parse_json_body, _read_http_error  # noqa: E402


class ParseJsonBodyTests(unittest.TestCase):
    def test_object_body_is_returned(self) -> None:
        self.assertEqual(_parse_json_body({"body": '{"a": 1}'}), {"a": 1})

    def test_non_dict_json_is_empty_object(self) -> None:
        self.assertEqual(_parse_json_body({"body": "[1, 2]"}), {})
        self.assertEqual(_parse_json_body({"body": "null"}), {})
        self.assertEqual(_parse_json_body({"body": '"text"'}), {})
        self.assertEqual(_parse_json_body({"body": "42"}), {})

    def test_invalid_json_is_empty_object(self) -> None:
        self.assertEqual(_parse_json_body({"body": "not-json"}), {})
        self.assertEqual(_parse_json_body({}), {})


class HttpErrorCloseTests(unittest.TestCase):
    def test_read_returns_body_and_closes(self) -> None:
        err = urllib.error.HTTPError("https://example.test", 503, "down", {}, io.BytesIO(b"nope"))
        self.assertEqual(_read_http_error(err), b"nope")
        self.assertTrue(err.fp.closed)

    def test_read_closes_when_body_read_fails(self) -> None:
        err = urllib.error.HTTPError("https://example.test", 500, "boom", {}, io.BytesIO(b"x"))

        def fail() -> bytes:
            raise OSError("read failed")

        err.read = fail  # type: ignore[method-assign]
        with self.assertRaises(OSError):
            _read_http_error(err)
        self.assertTrue(err.fp.closed)

    def test_read_without_body_is_empty_and_closed(self) -> None:
        err = urllib.error.HTTPError("https://example.test", 404, "missing", {}, None)
        self.assertEqual(_read_http_error(err, 20), b"")
        self.assertTrue(err.fp.closed)

    def test_close_returns_the_same_error(self) -> None:
        err = urllib.error.HTTPError("https://example.test", 429, "slow", {}, io.BytesIO(b"wait"))
        self.assertIs(_close_http_error(err), err)
        self.assertTrue(err.fp.closed)
