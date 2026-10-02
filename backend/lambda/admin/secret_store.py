"""Secrets Manager reads shared by board tools and the OpenRouter client.

``read_secret_raw`` returns the secret payload unchanged. ``read_secret_string``
unwraps a JSON object to a conventional token field. Both raise
``openrouter_client.OpenRouterError`` so existing callers keep their handler.
"""

from __future__ import annotations

import base64
import json
from typing import Any


def _error(message: str) -> Exception:
    from openrouter_client import OpenRouterError

    return OpenRouterError(message)


def read_secret_raw(secrets_client: Any, secret_arn: str, *, what: str) -> str:
    """Fetch a Secrets Manager secret and return the full string payload.

    Unlike :func:`read_secret_string`, this does not unwrap a JSON object to a
    single token field. Service-account blobs (GA4, Play, App Store Connect)
    must stay intact so callers can read ``client_email`` / ``private_key``.
    """
    response = secrets_client.get_secret_value(SecretId=secret_arn)
    secret_string = response.get("SecretString")
    if not secret_string and response.get("SecretBinary"):
        secret_string = base64.b64decode(response["SecretBinary"]).decode("utf-8")
    if not secret_string:
        raise _error(f"{what} secret is empty")
    raw = secret_string.strip()
    if not raw:
        raise _error(f"{what} value is blank")
    return raw


def read_secret_string(secrets_client: Any, secret_arn: str, *, what: str) -> str:
    """Fetch a Secrets Manager secret and return the bare token inside it.

    Accepts either a plain string secret or a JSON object with one of the
    conventional key names.
    """
    raw = read_secret_raw(secrets_client, secret_arn, what=what)
    if raw.startswith("{"):
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise _error(f"{what} secret JSON must be an object")
        for key_name in (
            "openrouter_api_key",
            "OPENROUTER_API_KEY",
            "github_token",
            "GITHUB_TOKEN",
            "api_key",
            "key",
            "token",
        ):
            candidate = payload.get(key_name)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        raise _error(f"{what} is missing in secret JSON")
    return raw
