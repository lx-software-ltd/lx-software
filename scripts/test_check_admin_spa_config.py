"""The admin SPA config check reads a fake payload and skips when unset."""

from __future__ import annotations

import email.message
import importlib.util
import io
import sys
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from http.client import HTTPResponse
from pathlib import Path
from typing import cast
from unittest.mock import patch

_PATH = Path(__file__).resolve().parent / "check_admin_spa_config.py"
_SPEC = importlib.util.spec_from_file_location("check_admin_spa_config", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
check = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = check
_SPEC.loader.exec_module(check)


class _Resp:
    def __init__(self, code: int, headers: email.message.Message, body: bytes = b"") -> None:
        self.code = code
        self.msg = "Found"
        self.headers = headers
        self._body = body

    def info(self) -> email.message.Message:
        return self.headers

    def read(self, n: int = -1) -> bytes:
        return self._body if n < 0 else self._body[:n]

    def close(self) -> None:
        return None

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class CheckAdminSpaConfigTest(unittest.TestCase):
    def test_unset_url_skips(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            code = check.main(environ={})
        self.assertEqual(code, 0)
        self.assertIn("skipped", out.getvalue())

    def test_custom_domain_passes(self) -> None:
        def fetch(_url: str) -> dict:
            return {"apiBaseUrl": "https://api.lx-software.com/"}

        out = io.StringIO()
        with redirect_stdout(out):
            code = check.main(
                environ={"ADMIN_SPA_CONFIG_URL": "https://cdn.example/config.json"},
                fetch=fetch,
            )
        self.assertEqual(code, 0)
        self.assertIn("https://api.lx-software.com", out.getvalue())

    def test_refuses_a_non_https_url(self) -> None:
        with self.assertRaises(ValueError):
            check._fetch("file:///etc/passwd")

    def test_http_redirect_is_refused_without_a_network(self) -> None:
        class _ToHttp(urllib.request.HTTPSHandler):
            def https_open(self, _req: urllib.request.Request) -> HTTPResponse:
                headers = email.message.Message()
                headers["Location"] = "http://evil.example/config.json"
                return cast(HTTPResponse, _Resp(302, headers))

        def opener() -> urllib.request.OpenerDirector:
            return urllib.request.build_opener(check._HttpsOnlyRedirect, _ToHttp)

        with patch.object(check, "_opener", opener):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                check._fetch("https://cdn.example/config.json")
        self.assertIn("non-https", str(ctx.exception))

    def test_oversized_body_is_refused_without_a_network(self) -> None:
        class _Huge(urllib.request.HTTPSHandler):
            def https_open(self, _req: urllib.request.Request) -> HTTPResponse:
                headers = email.message.Message()
                return cast(
                    HTTPResponse,
                    _Resp(200, headers, b"{" + b"x" * (check._MAX_CONFIG_BYTES + 1)),
                )

        def opener() -> urllib.request.OpenerDirector:
            return urllib.request.build_opener(check._HttpsOnlyRedirect, _Huge)

        with patch.object(check, "_opener", opener):
            with self.assertRaises(ValueError) as ctx:
                check._fetch("https://cdn.example/config.json")
        self.assertIn(str(check._MAX_CONFIG_BYTES), str(ctx.exception))

    def test_deploy_script_runs_this_check(self) -> None:
        script = Path(__file__).resolve().parent / "deploy" / "check-admin-spa-settings.sh"
        text = script.read_text(encoding="utf-8")
        self.assertIn('python3 "$(dirname "$0")/../check_admin_spa_config.py"', text)

    def test_execute_api_base_fails(self) -> None:
        def fetch(_url: str) -> dict:
            return {"apiBaseUrl": "https://abc123.execute-api.ap-southeast-1.amazonaws.com"}

        err = io.StringIO()
        with redirect_stderr(err):
            code = check.main(
                environ={"ADMIN_SPA_CONFIG_URL": "https://cdn.example/config.json"},
                fetch=fetch,
            )
        self.assertEqual(code, 1)
        self.assertIn("execute-api", err.getvalue())
