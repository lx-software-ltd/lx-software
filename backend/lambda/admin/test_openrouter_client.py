"""Unit tests for OpenRouter client attribution and per-service keys."""

from __future__ import annotations

import io
import json
import sys
import types
import unittest
from typing import Any
from unittest.mock import MagicMock, patch
from urllib import error as urlerror


def _install_stubs() -> None:
    if "boto3" not in sys.modules:
        sys.modules["boto3"] = MagicMock()
    if "botocore" not in sys.modules:
        botocore = types.ModuleType("botocore")
        exceptions = types.ModuleType("botocore.exceptions")

        class ClientError(Exception):
            pass

        exceptions.ClientError = ClientError
        botocore.exceptions = exceptions
        sys.modules["botocore"] = botocore
        sys.modules["botocore.exceptions"] = exceptions


_install_stubs()

import openrouter_client  # noqa: E402


class _FakeResp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _header(headers: dict[str, str], name: str) -> str | None:
    want = name.lower()
    for key, value in headers.items():
        if key.lower() == want:
            return value
    return None


class TestOpenRouterAttribution(unittest.TestCase):
    def setUp(self) -> None:
        openrouter_client.reset_api_key_cache_for_tests()

    def test_http_header_value_replaces_em_dash(self) -> None:
        self.assertEqual(
            openrouter_client._http_header_value("LX Admin — Statement parser"),
            "LX Admin - Statement parser",
        )
        encoded = openrouter_client._http_header_value(
            "LX Admin — Statement parser"
        ).encode("latin-1")
        self.assertEqual(encoded, b"LX Admin - Statement parser")

    def test_board_headers_and_user(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout=None):  # noqa: ARG001
            captured["headers"] = dict(req.headers)
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResp(
                json.dumps(
                    {
                        "model": "m",
                        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.002},
                    }
                ).encode("utf-8")
            )

        with patch("openrouter_client.urlrequest.urlopen", fake_urlopen), patch.dict(
            "os.environ", {"OPENROUTER_API_KEY": "sk-env"}, clear=False
        ):
            completion = openrouter_client.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                model="m",
                secrets_client=None,
                timeout=5,
                service=openrouter_client.SERVICE_EXECUTIVE_BOARD,
                owner="siuTinDei",
            )

        headers = captured["headers"]
        self.assertEqual(
            _header(headers, "X-OpenRouter-Title"), "LX Admin - Executive Board"
        )
        self.assertEqual(
            _header(headers, "HTTP-Referer"),
            "https://admin.lx-software.com/siu-tin-dei/board",
        )
        self.assertEqual(_header(headers, "X-OpenRouter-App-Visibility"), "hidden")
        body = captured["body"]
        self.assertEqual(body["user"], "executive-board:siuTinDei")
        self.assertEqual(body["usage"], {"include": True})
        self.assertAlmostEqual(completion.cost_usd, 0.002)

    def test_json_secret_picks_per_service_key(self) -> None:
        secrets = MagicMock()
        secrets.get_secret_value.return_value = {
            "SecretString": json.dumps(
                {
                    "openrouter_api_key": "sk-shared",
                    "statement-parser": "sk-parser",
                    "executive-board": "sk-board",
                }
            )
        }
        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_API_KEY_SECRET_ARN": "arn:aws:secretsmanager:eu-west-1:1:secret:x",
                "OPENROUTER_API_KEY": "",
            },
            clear=False,
        ):
            parser_key = openrouter_client.resolve_api_key(
                secrets, service=openrouter_client.SERVICE_STATEMENT_PARSER
            )
            board_key = openrouter_client.resolve_api_key(
                secrets, service=openrouter_client.SERVICE_EXECUTIVE_BOARD
            )
        self.assertEqual(parser_key, "sk-parser")
        self.assertEqual(board_key, "sk-board")

    def test_json_secret_requires_named_key_for_catalog_app(self) -> None:
        secrets = MagicMock()
        secrets.get_secret_value.return_value = {
            "SecretString": json.dumps({"openrouter_api_key": "sk-shared"})
        }
        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_API_KEY_SECRET_ARN": "arn:aws:secretsmanager:eu-west-1:1:secret:x",
                "OPENROUTER_API_KEY": "",
            },
            clear=False,
        ):
            with self.assertRaises(openrouter_client.OpenRouterError) as ctx:
                openrouter_client.resolve_api_key(
                    secrets, service=openrouter_client.SERVICE_EXECUTIVE_BOARD
                )
        self.assertIn("executive-board", str(ctx.exception))

    def test_plain_string_secret_rejected_for_catalog_app(self) -> None:
        secrets = MagicMock()
        secrets.get_secret_value.return_value = {"SecretString": "sk-plain"}
        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_API_KEY_SECRET_ARN": "arn:aws:secretsmanager:eu-west-1:1:secret:x",
                "OPENROUTER_API_KEY": "",
            },
            clear=False,
        ):
            with self.assertRaises(openrouter_client.OpenRouterError) as ctx:
                openrouter_client.resolve_api_key(
                    secrets, service=openrouter_client.SERVICE_STATEMENT_PARSER
                )
        self.assertIn("statement-parser", str(ctx.exception))

    def test_unknown_service_falls_back_to_shared_key(self) -> None:
        secrets = MagicMock()
        secrets.get_secret_value.return_value = {
            "SecretString": json.dumps({"openrouter_api_key": "sk-shared"})
        }
        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_API_KEY_SECRET_ARN": "arn:aws:secretsmanager:eu-west-1:1:secret:x",
                "OPENROUTER_API_KEY": "",
            },
            clear=False,
        ):
            key = openrouter_client.resolve_api_key(secrets, service="ad-hoc-script")
        self.assertEqual(key, "sk-shared")

    def test_catalog_apps_include_sibling_products(self) -> None:
        sprouts = openrouter_client.resolve_app("evolvesprouts")
        self.assertEqual(sprouts.title, "Evolve Sprouts")
        self.assertEqual(sprouts.referer, "https://evolvesprouts.com")
        product = openrouter_client.resolve_app("siutindei")
        self.assertEqual(product.title, "Siu Tin Dei")
        self.assertEqual(product.referer, "https://siutindei.com")

    def test_post_json_success_does_not_read_monotonic(self) -> None:
        """Tool-loop tests patch time.monotonic as a fake clock; do not steal ticks."""

        def fake_urlopen(req, timeout=None):  # noqa: ARG001
            return _FakeResp(json.dumps({"ok": True}).encode("utf-8"))

        with (
            patch("openrouter_client.urlrequest.urlopen", fake_urlopen),
            patch(
                "openrouter_client.time.monotonic",
                side_effect=AssertionError("post_json must not read time.monotonic"),
            ),
        ):
            text = openrouter_client.post_json(
                url="https://openrouter.ai/api/v1/chat/completions",
                api_key="sk-test",
                payload={"model": "m"},
                timeout=5,
            )
        self.assertEqual(json.loads(text), {"ok": True})

    def test_post_json_retries_incomplete_read(self) -> None:
        import http.client

        calls = {"n": 0}
        payload = json.dumps({"ok": True}).encode("utf-8")

        class Boom:
            def read(self) -> bytes:
                raise http.client.IncompleteRead(b"x")

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        def fake_urlopen(req, timeout=None):  # noqa: ARG001
            calls["n"] += 1
            if calls["n"] == 1:
                return Boom()
            return _FakeResp(payload)

        with (
            patch("openrouter_client.urlrequest.urlopen", fake_urlopen),
            patch("openrouter_client.time.sleep", lambda *_a, **_k: None),
        ):
            text = openrouter_client.post_json(
                url="https://openrouter.ai/api/v1/chat/completions",
                api_key="sk-test",
                payload={"model": "m"},
                timeout=5,
            )
        self.assertEqual(calls["n"], 2)
        self.assertEqual(json.loads(text), {"ok": True})

    def test_post_json_does_not_retry_timeout(self) -> None:
        calls = {"n": 0}

        class Boom:
            def read(self) -> bytes:
                raise TimeoutError("timed out")

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        def fake_urlopen(req, timeout=None):  # noqa: ARG001
            calls["n"] += 1
            return Boom()

        with (
            patch("openrouter_client.urlrequest.urlopen", fake_urlopen),
            patch("openrouter_client.time.sleep", lambda *_a, **_k: None),
        ):
            with self.assertRaises(openrouter_client.OpenRouterError) as ctx:
                openrouter_client.post_json(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    api_key="sk-test",
                    payload={"model": "m"},
                    timeout=5,
                )
        self.assertEqual(calls["n"], 1)
        self.assertIn("timed out", str(ctx.exception))


class TestOpenRouterFallbacksAndRetries(unittest.TestCase):
    def setUp(self) -> None:
        openrouter_client.reset_api_key_cache_for_tests()

    def test_normalize_fallback_models_excludes_primary_and_caps(self) -> None:
        self.assertEqual(
            openrouter_client.normalize_fallback_models(
                "deepseek/deepseek-chat",
                [
                    "deepseek/deepseek-chat",
                    " openai/gpt-4.1-mini ",
                    "openai/gpt-4.1-mini",
                    "anthropic/claude-sonnet-4",
                    "google/gemini-2.5-flash",
                    "meta-llama/unused",
                ],
            ),
            ["openai/gpt-4.1-mini", "anthropic/claude-sonnet-4", "google/gemini-2.5-flash"],
        )
        self.assertEqual(openrouter_client.normalize_fallback_models("m", None), [])
        self.assertEqual(openrouter_client.normalize_fallback_models("m", ["", "m"]), [])

    def test_chat_completion_sends_fallback_models(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout=None):  # noqa: ARG001
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResp(
                json.dumps(
                    {
                        "model": "openai/gpt-4.1-mini",
                        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                    }
                ).encode("utf-8")
            )

        with patch("openrouter_client.urlrequest.urlopen", fake_urlopen), patch.dict(
            "os.environ", {"OPENROUTER_API_KEY": "sk-env"}, clear=False
        ):
            completion = openrouter_client.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                model="deepseek/deepseek-chat",
                secrets_client=None,
                timeout=5,
                fallback_models=["deepseek/deepseek-chat", "openai/gpt-4.1-mini", "anthropic/claude-sonnet-4"],
            )
        body = captured["body"]
        self.assertEqual(body["model"], "deepseek/deepseek-chat")
        self.assertEqual(body["models"], ["openai/gpt-4.1-mini", "anthropic/claude-sonnet-4"])
        self.assertEqual(completion.model, "openai/gpt-4.1-mini")

    def test_post_json_retries_429_without_mutating_provider(self) -> None:
        error_body = json.dumps(
            {
                "error": {
                    "message": "Provider returned error",
                    "code": 429,
                    "metadata": {
                        "raw": "deepseek/deepseek-chat is temporarily rate-limited upstream.",
                        "provider_name": "StreamLake",
                        "limit_source": "upstream_provider_shared_pool",
                    },
                }
            }
        ).encode("utf-8")
        calls: dict[str, object] = {"n": 0, "bodies": []}

        def fake_urlopen(req, timeout=None):  # noqa: ARG001
            calls["n"] = int(calls["n"]) + 1
            bodies: list = calls["bodies"]  # type: ignore[assignment]
            bodies.append(json.loads(req.data.decode("utf-8")))
            if calls["n"] == 1:
                raise urlerror.HTTPError(
                    req.full_url,
                    429,
                    "Too Many Requests",
                    {"Retry-After": "1"},
                    io.BytesIO(error_body),
                )
            return _FakeResp(json.dumps({"ok": True}).encode("utf-8"))

        slept: list[float] = []
        with (
            patch("openrouter_client.urlrequest.urlopen", fake_urlopen),
            patch("openrouter_client.time.sleep", lambda seconds: slept.append(seconds)),
        ):
            text = openrouter_client.post_json(
                url="https://openrouter.ai/api/v1/chat/completions",
                api_key="sk-test",
                payload={"model": "deepseek/deepseek-chat", "provider": {"data_collection": "deny"}},
                timeout=20,
            )
        self.assertEqual(calls["n"], 2)
        bodies = calls["bodies"]
        self.assertEqual(bodies[0]["provider"], {"data_collection": "deny"})
        self.assertEqual(bodies[1]["provider"], {"data_collection": "deny"})
        self.assertEqual(slept, [3.0])
        self.assertEqual(json.loads(text), {"ok": True})

    def test_post_json_skips_retry_when_backoff_exceeds_timeout(self) -> None:
        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):  # noqa: ARG001
            calls["n"] += 1
            raise urlerror.HTTPError(
                req.full_url,
                429,
                "Too Many Requests",
                {"Retry-After": "30"},
                io.BytesIO(b'{"error":{"message":"rate limited","code":429}}'),
            )

        with (
            patch("openrouter_client.urlrequest.urlopen", fake_urlopen),
            patch("openrouter_client.time.sleep", lambda *_a, **_k: None),
        ):
            with self.assertRaises(openrouter_client.OpenRouterError) as ctx:
                openrouter_client.post_json(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    api_key="sk-test",
                    payload={"model": "m"},
                    timeout=5,
                    max_retries=2,
                )
        self.assertEqual(calls["n"], 1)
        self.assertEqual(ctx.exception.status, 429)
        self.assertIn("rate limited", str(ctx.exception))

    def test_post_json_gives_up_after_429_retries(self) -> None:
        def fake_urlopen(req, timeout=None):  # noqa: ARG001
            raise urlerror.HTTPError(
                req.full_url,
                429,
                "Too Many Requests",
                {},
                io.BytesIO(b'{"error":{"message":"rate limited","code":429}}'),
            )

        with (
            patch("openrouter_client.urlrequest.urlopen", fake_urlopen),
            patch("openrouter_client.time.sleep", lambda *_a, **_k: None),
        ):
            with self.assertRaises(openrouter_client.OpenRouterError) as ctx:
                openrouter_client.post_json(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    api_key="sk-test",
                    payload={"model": "m"},
                    timeout=5,
                    max_retries=2,
                )
        self.assertEqual(ctx.exception.status, 429)
        self.assertIn("rate limited", str(ctx.exception))

    def test_chat_completion_walks_fallback_model_after_429(self) -> None:
        calls: list[dict[str, Any]] = []

        def fake_urlopen(req, timeout=None):  # noqa: ARG001
            body = json.loads(req.data.decode("utf-8"))
            calls.append(body)
            if body.get("model") == "deepseek/deepseek-chat":
                raise urlerror.HTTPError(
                    req.full_url,
                    429,
                    "Too Many Requests",
                    {},
                    io.BytesIO(b'{"error":{"message":"rate limited","code":429}}'),
                )
            return _FakeResp(
                json.dumps(
                    {
                        "model": body.get("model"),
                        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                    }
                ).encode("utf-8")
            )

        with (
            patch("openrouter_client.urlrequest.urlopen", fake_urlopen),
            patch("openrouter_client.time.sleep", lambda *_a, **_k: None),
            patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-env"}, clear=False),
        ):
            completion = openrouter_client.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                model="deepseek/deepseek-chat",
                secrets_client=None,
                timeout=8,
                max_retries=0,
                fallback_models=["openai/gpt-4.1-mini"],
            )
        self.assertEqual(completion.model, "openai/gpt-4.1-mini")
        self.assertEqual(calls[0]["model"], "deepseek/deepseek-chat")
        self.assertEqual(calls[-1]["model"], "openai/gpt-4.1-mini")

    def test_chat_completion_does_not_walk_on_400(self) -> None:
        calls: list[str] = []

        def fake_post_json(**kwargs: Any) -> str:
            calls.append(str((kwargs.get("payload") or {}).get("model")))
            raise openrouter_client.OpenRouterError("bad request", status=400)

        with (
            patch.object(openrouter_client, "post_json", fake_post_json),
            patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-env"}, clear=False),
        ):
            with self.assertRaises(openrouter_client.OpenRouterError) as ctx:
                openrouter_client.chat_completion(
                    messages=[{"role": "user", "content": "hi"}],
                    model="deepseek/deepseek-chat",
                    secrets_client=None,
                    timeout=8,
                    max_retries=0,
                    fallback_models=["openai/gpt-4.1-mini"],
                )
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(calls, ["deepseek/deepseek-chat"])

    def test_chat_completion_does_not_walk_on_500(self) -> None:
        calls: list[str] = []

        def fake_post_json(**kwargs: Any) -> str:
            calls.append(str((kwargs.get("payload") or {}).get("model")))
            raise openrouter_client.OpenRouterError("upstream", status=500)

        with (
            patch.object(openrouter_client, "post_json", fake_post_json),
            patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-env"}, clear=False),
        ):
            with self.assertRaises(openrouter_client.OpenRouterError) as ctx:
                openrouter_client.chat_completion(
                    messages=[{"role": "user", "content": "hi"}],
                    model="deepseek/deepseek-chat",
                    secrets_client=None,
                    timeout=8,
                    max_retries=0,
                    fallback_models=["openai/gpt-4.1-mini"],
                )
        self.assertEqual(ctx.exception.status, 500)
        self.assertEqual(calls, ["deepseek/deepseek-chat"])

    def test_chat_completion_walk_uses_one_retry_on_fallback(self) -> None:
        seen: list[tuple[str, int]] = []

        def fake_post_json(**kwargs: Any) -> str:
            model = str((kwargs.get("payload") or {}).get("model"))
            retries = int(kwargs.get("max_retries") or 0)
            seen.append((model, retries))
            if model == "deepseek/deepseek-chat":
                raise openrouter_client.OpenRouterError("rate limited", status=429)
            return json.dumps(
                {
                    "model": model,
                    "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                }
            )

        with (
            patch.object(openrouter_client, "post_json", fake_post_json),
            patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-env"}, clear=False),
        ):
            completion = openrouter_client.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                model="deepseek/deepseek-chat",
                secrets_client=None,
                timeout=8,
                max_retries=2,
                fallback_models=["openai/gpt-4.1-mini"],
            )
        self.assertEqual(completion.model, "openai/gpt-4.1-mini")
        self.assertEqual(seen[0], ("deepseek/deepseek-chat", 2))
        self.assertEqual(seen[1], ("openai/gpt-4.1-mini", 1))

    def test_chat_completion_walk_shares_deadline(self) -> None:
        timeouts: list[int] = []
        clocks = iter([0.0, 0.5, 7.5])

        def fake_post_json(**kwargs: Any) -> str:
            timeouts.append(int(kwargs.get("timeout") or 0))
            raise openrouter_client.OpenRouterError("rate limited", status=429)

        with (
            patch.object(openrouter_client, "post_json", fake_post_json),
            patch.object(openrouter_client, "_clock", side_effect=lambda: next(clocks)),
            patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-env"}, clear=False),
        ):
            with self.assertRaises(openrouter_client.OpenRouterError) as ctx:
                openrouter_client.chat_completion(
                    messages=[{"role": "user", "content": "hi"}],
                    model="deepseek/deepseek-chat",
                    secrets_client=None,
                    timeout=8,
                    max_retries=0,
                    fallback_models=["openai/gpt-4.1-mini"],
                )
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(timeouts, [7])

    def test_retry_after_helpers(self) -> None:
        self.assertEqual(
            openrouter_client._retry_sleep_seconds(1, status=429, retry_after=7),
            7.0,
        )
        self.assertEqual(
            openrouter_client._retry_sleep_seconds(1, status=500, retry_after=None),
            1.5,
        )
        self.assertEqual(
            openrouter_client._retry_sleep_seconds(3, status=429, retry_after=99),
            20.0,
        )


if __name__ == "__main__":
    unittest.main()
