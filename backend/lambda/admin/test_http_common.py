"""Unit tests for shared HTTP helpers."""

from __future__ import annotations

import unittest

from test_support import install_aws_stubs

install_aws_stubs()

from http_common import _parse_json_body  # noqa: E402


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
