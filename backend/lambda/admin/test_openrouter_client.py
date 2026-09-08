"""Unit tests for OpenRouter client attribution and per-service keys."""

from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


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
            _header(headers, "X-OpenRouter-Title"), "LX Admin — Executive Board"
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

    def test_json_secret_falls_back_to_shared_key(self) -> None:
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
            key = openrouter_client.resolve_api_key(
                secrets, service=openrouter_client.SERVICE_EXECUTIVE_BOARD
            )
        self.assertEqual(key, "sk-shared")

    def test_catalog_apps_include_sibling_products(self) -> None:
        sprouts = openrouter_client.resolve_app("evolvesprouts")
        self.assertEqual(sprouts.title, "Evolve Sprouts")
        self.assertEqual(sprouts.referer, "https://evolvesprouts.com")
        product = openrouter_client.resolve_app("siutindei")
        self.assertEqual(product.title, "Siu Tin Dei")
        self.assertEqual(product.referer, "https://siutindei.com")


if __name__ == "__main__":
    unittest.main()
