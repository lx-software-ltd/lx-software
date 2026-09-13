"""Executive Board: fire-and-forget self-invocation of AdminApiFn."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

import boto3
from botocore.config import Config

from admin_runtime import _get_lambda_client

# Safari / API Gateway drop the HTTP call if we wait on the default boto3
# client (60s read, multiple retries). A 2s Event invoke is enough to accept
# the request; the worker then runs on its own execution.
INVOKE_EVENT_TIMEOUT_SECONDS = 2


def _function_name() -> str:
    return (
        (os.environ.get("PARSE_WORKER_FUNCTION_NAME") or "").strip()
        or (os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or "").strip()
    )


def invoke_async(payload: dict[str, Any], *, fallback: Callable[[dict[str, Any]], None]) -> None:
    """Invoke this Lambda asynchronously; run ``fallback`` inline when no function name is known.

    The inline fallback keeps unit tests and local runs deterministic.
    """
    fn_name = _function_name()
    if not fn_name:
        fallback(payload)
        return
    _get_lambda_client().invoke(
        FunctionName=fn_name,
        InvocationType="Event",
        Payload=json.dumps(payload).encode("utf-8"),
    )


def try_invoke_event(payload: dict[str, Any]) -> bool:
    """Best-effort ``Event`` invoke with a short timeout. Never runs work inline.

    Returns True when Lambda accepted the event. False when no function name
    is configured or the Invoke call failed / timed out — the caller should
    still return 200 so the browser is not left hanging.
    """
    fn_name = _function_name()
    if not fn_name:
        return False
    client = boto3.client(
        "lambda",
        config=Config(
            connect_timeout=INVOKE_EVENT_TIMEOUT_SECONDS,
            read_timeout=INVOKE_EVENT_TIMEOUT_SECONDS,
            retries={"max_attempts": 1, "mode": "standard"},
        ),
    )
    try:
        client.invoke(
            FunctionName=fn_name,
            InvocationType="Event",
            Payload=json.dumps(payload).encode("utf-8"),
        )
    except Exception:
        return False
    return True
