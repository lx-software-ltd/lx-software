"""Unit tests for shared HTTP helpers."""

from __future__ import annotations

import io
import unittest
import urllib.error
from email.message import Message

from test_support import install_aws_stubs

install_aws_stubs()

import json  # noqa: E402

from http_common import (  # noqa: E402
    _close_http_error,
    _json_response,
    _parse_json_body,
    _read_http_error,
    bind_request_id,
    request_id_scope,
)


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


class ErrorBodyTests(unittest.TestCase):
    def tearDown(self) -> None:
        bind_request_id({})

    def test_an_error_keeps_message_and_reason_and_adds_problem_members(self) -> None:
        bind_request_id({"requestContext": {"requestId": "req-1"}})
        response = _json_response(403, {"message": "Forbidden", "reason": "writes_disabled"})
        body = json.loads(response["body"])
        self.assertEqual(body["message"], "Forbidden")
        self.assertEqual(body["reason"], "writes_disabled")
        self.assertEqual(body["type"], "about:blank")
        self.assertEqual(body["title"], "Forbidden")
        self.assertEqual(body["status"], 403)
        self.assertEqual(body["detail"], "Forbidden")
        self.assertEqual(body["code"], "forbidden")
        self.assertEqual(body["request_id"], "req-1")
        self.assertEqual(response["headers"]["x-request-id"], "req-1")

    def test_a_success_body_stays_unchanged(self) -> None:
        bind_request_id({"requestContext": {"requestId": "req-2"}})
        response = _json_response(200, {"message": "saved", "ok": True})
        self.assertEqual(json.loads(response["body"]), {"message": "saved", "ok": True})
        self.assertEqual(response["headers"]["x-request-id"], "req-2")

    def test_the_header_is_omitted_when_the_request_has_no_id(self) -> None:
        bind_request_id({})
        response = _json_response(404, {"message": "Not found"})
        self.assertNotIn("x-request-id", response["headers"])
        self.assertEqual(json.loads(response["body"])["code"], "not_found")

    def test_a_second_invocation_does_not_report_the_first_request_id(self) -> None:
        def invoke(event: dict) -> dict:
            with request_id_scope(event):
                return _json_response(404, {"message": "Not found"})

        first = invoke({"requestContext": {"requestId": "req-first"}})
        self.assertEqual(json.loads(first["body"])["request_id"], "req-first")
        self.assertEqual(first["headers"]["x-request-id"], "req-first")
        # A later read in this process, before the next bind, must not keep req-first.
        between = _json_response(500, {"message": "later"})
        self.assertNotIn("req-first", between["body"])
        self.assertNotIn("x-request-id", between["headers"])
        second = invoke({})
        body = json.loads(second["body"])
        self.assertEqual(body["request_id"], "")
        self.assertNotIn("req-first", second["body"])
        self.assertNotIn("x-request-id", second["headers"])

    def test_a_conflicting_code_or_status_is_replaced_by_the_problem_value(self) -> None:
        # No handler error body sets these today. A provider number or a
        # record status must not stay in the problem members.
        response = _json_response(
            400,
            {"message": "Bad request", "reason": "field", "code": 190, "status": "APPROVED"},
        )
        body = json.loads(response["body"])
        self.assertEqual(body["message"], "Bad request")
        self.assertEqual(body["reason"], "field")
        self.assertEqual(body["code"], "invalid_request")
        self.assertEqual(body["status"], 400)

    def test_an_existing_problem_code_and_status_are_kept(self) -> None:
        response = _json_response(400, {"message": "Bad request", "code": "invalid_request", "status": 400})
        body = json.loads(response["body"])
        self.assertEqual(body["code"], "invalid_request")
        self.assertEqual(body["status"], 400)
        self.assertEqual(body["message"], "Bad request")

    def test_html_responses_carry_the_request_id(self) -> None:
        import board_newsletter
        import board_outreach

        bind_request_id({"requestContext": {"requestId": "req-html"}})
        for response in (
            board_newsletter._html_response(200, "<p>ok</p>"),
            board_outreach._html_response(200, "<p>ok</p>"),
        ):
            self.assertEqual(response["headers"]["content-type"], "text/html; charset=utf-8")
            self.assertEqual(response["headers"]["x-request-id"], "req-html")
        bind_request_id({})
        bare = board_newsletter._html_response(200, "<p>ok</p>")
        self.assertNotIn("x-request-id", bare["headers"])

    def test_plain_text_responses_carry_the_request_id(self) -> None:
        import os
        from unittest.mock import patch

        import board_meta
        import board_newsletter
        import board_outreach

        bind_request_id({"requestContext": {"requestId": "req-plain"}})
        event = {"requestContext": {"http": {"sourceIp": "203.0.113.9"}}}
        with (
            patch.object(board_newsletter.board_store, "records_table", return_value=object()),
            patch.object(board_newsletter, "_rate_limited", return_value=True),
            patch.object(board_outreach.board_store, "records_table", return_value=object()),
            patch.object(board_outreach, "_rate_limited", return_value=True),
        ):
            limited = (
                board_newsletter.handle_unsubscribe(event, "POST", "bad-token"),
                board_outreach.handle_unsubscribe(event, "POST", "bad-token"),
            )
        for response in limited:
            self.assertEqual(response["statusCode"], 429)
            self.assertEqual(response["headers"]["Content-Type"], "text/plain")
            self.assertEqual(response["headers"]["x-request-id"], "req-plain")
            self.assertEqual(response["body"], "")

        with (
            patch.object(board_newsletter.board_store, "records_table", return_value=object()),
            patch.object(board_newsletter.board_store, "get_newsletter_sub", return_value=None),
            patch.object(board_newsletter, "_rate_limited", return_value=False),
            patch.object(board_outreach.board_store, "records_table", return_value=object()),
            patch.object(board_outreach.board_store, "get_prospect", return_value=None),
            patch.object(board_outreach, "_rate_limited", return_value=False),
            patch.dict(os.environ, {"BOARD_LINK_SIGNING_SECRET": "link-secret-for-tests"}),
        ):
            newsletter_token = board_newsletter.make_token("u", "parents", "abc")
            outreach_token = board_outreach.make_unsub_token("prospect-1")
            accepted = (
                board_newsletter.handle_unsubscribe(event, "POST", newsletter_token),
                board_outreach.handle_unsubscribe(event, "POST", outreach_token),
            )
            rejected = (
                board_newsletter.handle_unsubscribe(event, "POST", "bad-token"),
                board_outreach.handle_unsubscribe(event, "POST", "bad-token"),
            )
        for response in accepted:
            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(response["headers"]["x-request-id"], "req-plain")
        for response in rejected:
            self.assertEqual(response["statusCode"], 400)
            self.assertEqual(response["headers"]["x-request-id"], "req-plain")

        with patch.dict(os.environ, {"META_VERIFY_TOKEN": "verify-me"}):
            challenge = board_meta.handle_http(
                {"rawQueryString": "hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=abc123"},
                "GET",
            )
            denied = board_meta.handle_http(
                {"rawQueryString": "hub.mode=subscribe&hub.verify_token=nope&hub.challenge=x"},
                "GET",
            )
        self.assertEqual(challenge["statusCode"], 200)
        self.assertEqual(challenge["body"], "abc123")
        self.assertEqual(challenge["headers"]["Content-Type"], "text/plain")
        self.assertEqual(challenge["headers"]["x-request-id"], "req-plain")
        self.assertEqual(denied["statusCode"], 403)
        self.assertEqual(denied["headers"]["x-request-id"], "req-plain")
        bind_request_id({})
        bare_meta = board_meta.handle_http(
            {"rawQueryString": "hub.mode=subscribe&hub.verify_token=nope&hub.challenge=x"},
            "GET",
        )
        self.assertNotIn("x-request-id", bare_meta["headers"])


class _UnreadableHTTPError(urllib.error.HTTPError):
    def read(self, n: int = -1) -> bytes:
        raise OSError("read failed")


class HttpErrorCloseTests(unittest.TestCase):
    def test_read_returns_body_and_closes(self) -> None:
        err = urllib.error.HTTPError("https://example.test", 503, "down", Message(), io.BytesIO(b"nope"))
        self.assertEqual(_read_http_error(err), b"nope")
        self.assertTrue(err.fp.closed)

    def test_read_closes_when_body_read_fails(self) -> None:
        err = _UnreadableHTTPError("https://example.test", 500, "boom", Message(), io.BytesIO(b"x"))
        with self.assertRaises(OSError):
            _read_http_error(err)
        self.assertTrue(err.fp.closed)

    def test_read_without_body_is_empty_and_closed(self) -> None:
        err = urllib.error.HTTPError("https://example.test", 404, "missing", Message(), None)
        self.assertEqual(_read_http_error(err, 20), b"")
        self.assertTrue(err.fp.closed)

    def test_close_returns_the_same_error(self) -> None:
        err = urllib.error.HTTPError("https://example.test", 429, "slow", Message(), io.BytesIO(b"wait"))
        self.assertIs(_close_http_error(err), err)
        self.assertTrue(err.fp.closed)
