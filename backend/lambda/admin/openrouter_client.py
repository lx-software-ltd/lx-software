"""Shared OpenRouter Chat Completions client.

Used by the statement parser and the Executive Board. Owns API key
resolution (env var or Secrets Manager, cached per container), the HTTP
call with bounded retries, response text extraction, usage / cost
accounting, and per-app attribution so the LX Software OpenRouter invoice
can be tagged across this admin and sibling products.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from contract_constants import OPENROUTER_APPS as OPENROUTER_APP_CATALOG

DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_TIMEOUT_SECONDS = 60
_RETRYABLE_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_MODEL_WALK_STATUSES = frozenset({429, 502, 503})
_MAX_RETRIES_DEFAULT = 2
_MAX_FALLBACK_MODELS = 3
# Cap wait so a 429 cannot eat a whole meeting-phase timeout (100s).
_MAX_RETRY_SLEEP_SECONDS = 20.0
# Skip a retry when sleep plus another attempt cannot finish inside ``timeout``.
_MIN_RETRY_REMAINING_SECONDS = 1.0
# A full-call TimeoutError is a deadline, not a truncated body — do not
# retry it with the same timeout (that doubles a hung 90 s call).
_TRANSIENT_READ_ERRORS = (
    http.client.IncompleteRead,
    http.client.RemoteDisconnected,
    ConnectionResetError,
    BrokenPipeError,
)
_ADMIN_ORIGIN = "https://admin.lx-software.com"
_OWNER_SAFE_RE = re.compile(r"[^a-zA-Z0-9_-]+")

SERVICE_STATEMENT_PARSER = "statement-parser"
SERVICE_EXECUTIVE_BOARD = "executive-board"

_api_key_cache: dict[str, str] = {}


class OpenRouterError(RuntimeError):
    """Transport or API failure talking to OpenRouter."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class ToolCall:
    """One function call requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""

    def as_message_entry(self) -> dict[str, Any]:
        """Shape expected inside an assistant message's ``tool_calls`` list."""
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.raw_arguments or json.dumps(self.arguments)},
        }


@dataclass
class ChatCompletion:
    text: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""

    @property
    def cost_usd(self) -> float:
        value = self.usage.get("cost")
        return float(value) if isinstance(value, (int, float)) else 0.0

    def assistant_message(self) -> dict[str, Any]:
        """Replay this completion as the assistant turn in a follow-up request."""
        msg: dict[str, Any] = {"role": "assistant", "content": self.text or None}
        if self.tool_calls:
            msg["tool_calls"] = [tc.as_message_entry() for tc in self.tool_calls]
        return msg


@dataclass(frozen=True)
class OpenRouterApp:
    """OpenRouter app attribution for one internal service."""

    service_id: str
    title: str
    referer: str


def _apps_from_catalog() -> dict[str, OpenRouterApp]:
    out: dict[str, OpenRouterApp] = {}
    for row in OPENROUTER_APP_CATALOG:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id") or "").strip()
        if not sid:
            continue
        out[sid] = OpenRouterApp(
            service_id=sid,
            title=str(row.get("title") or sid),
            referer=str(row.get("referer") or _ADMIN_ORIGIN),
        )
    return out


_APPS_BY_ID = _apps_from_catalog()


def resolve_app(service_id: str | None) -> OpenRouterApp:
    sid = (service_id or "").strip()
    if sid in _APPS_BY_ID:
        return _APPS_BY_ID[sid]
    return OpenRouterApp(
        service_id="lxsoftware-admin",
        title="lxsoftware-admin",
        referer=_ADMIN_ORIGIN,
    )


def attribution_user(*, service: str, owner: str | None) -> str | None:
    """Stable OpenRouter ``user`` id: ``{service}:{owner}`` (no PII)."""
    sid = (service or "").strip() or "lxsoftware-admin"
    raw = (owner or "").strip()
    if not raw:
        return sid
    safe = _OWNER_SAFE_RE.sub("-", raw)[:40].strip("-") or "unknown"
    return f"{sid}:{safe}"


def endpoint_url() -> str:
    return os.getenv("OPENROUTER_CHAT_COMPLETIONS_URL", "").strip() or DEFAULT_ENDPOINT


def normalize_fallback_models(primary: str, candidates: list[str] | tuple[str, ...] | None) -> list[str]:
    """Deduped fallback slugs, excluding the primary, capped for the OpenRouter ``models`` field."""
    primary_slug = (primary or "").strip()
    seen = {primary_slug} if primary_slug else set()
    out: list[str] = []
    for raw in candidates or ():
        slug = str(raw or "").strip()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append(slug)
        if len(out) >= _MAX_FALLBACK_MODELS:
            break
    return out


def chat_completion(
    *,
    messages: list[dict[str, Any]],
    model: str,
    secrets_client: Any,
    timeout: int,
    json_mode: bool = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
    plugins: list[dict[str, Any]] | None = None,
    include_usage: bool = True,
    deny_data_collection: bool = True,
    max_retries: int = _MAX_RETRIES_DEFAULT,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    service: str = SERVICE_STATEMENT_PARSER,
    owner: str | None = None,
    fallback_models: list[str] | tuple[str, ...] | None = None,
) -> ChatCompletion:
    """POST one chat completion and return the assistant text plus usage.

    With ``deny_data_collection`` (the default) OpenRouter only routes to
    providers that do not retain prompts. ``tools`` follows the OpenAI
    function-calling schema; requested calls come back in ``tool_calls``.

    ``fallback_models`` is sent as OpenRouter's ``models`` list so a
    rate-limited or down primary (typical for DeepSeek's shared pool) fails
    over inside the same request. After a 429/502/503 the client also walks
    the remaining slugs as the next primary, sharing the same wall-clock
    ``timeout`` so the walk cannot stack another full request.

    ``service`` selects app-attribution headers and the named API key for
    that catalog app (``contracts/openrouter-apps.json``). The secret JSON
    must include a field matching the app id.
    """
    payload: dict[str, Any] = {"model": model, "messages": messages}
    user_id = attribution_user(service=service, owner=owner)
    if user_id:
        payload["user"] = user_id
    fallbacks = normalize_fallback_models(model, fallback_models)
    provider: dict[str, Any] = {}
    if deny_data_collection:
        provider["data_collection"] = "deny"
    if tools:
        payload["tools"] = tools
        # Skip providers that cannot honour the tools parameter instead of
        # silently dropping it.
        provider["require_parameters"] = True
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
    if provider:
        payload["provider"] = provider
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if plugins:
        payload["plugins"] = plugins
    if include_usage:
        payload["usage"] = {"include": True}

    api_key = resolve_api_key(secrets_client, service=service)
    chain = [model, *fallbacks] if str(model or "").strip() else list(fallbacks)
    last_error: OpenRouterError | None = None
    raw: dict[str, Any] | None = None
    current = model
    deadline = _clock() + max(1.0, float(timeout))
    for index, current in enumerate(chain):
        remaining = deadline - _clock()
        if remaining < _MIN_RETRY_REMAINING_SECONDS:
            break
        payload["model"] = current
        rest = chain[index + 1 :]
        if rest:
            payload["models"] = rest[:_MAX_FALLBACK_MODELS]
        else:
            payload.pop("models", None)
        try:
            body_text = post_json(
                url=endpoint_url(),
                api_key=api_key,
                payload=payload,
                timeout=max(1, int(remaining)),
                max_retries=max_retries if index == 0 else min(1, max_retries),
                service=service,
            )
            raw = _load_json_object(body_text, what="OpenRouter response")
            break
        except OpenRouterError as exc:
            last_error = exc
            if exc.status in _MODEL_WALK_STATUSES and index < len(chain) - 1:
                continue
            raise
    if raw is None:
        if last_error:
            raise last_error
        raise OpenRouterError("OpenRouter request failed: no model produced a response")
    text = extract_message_text(raw)
    return ChatCompletion(
        text=text,
        model=str(raw.get("model") or current),
        usage=normalize_usage(raw.get("usage")),
        raw=raw,
        tool_calls=extract_tool_calls(raw),
        finish_reason=str((raw.get("choices") or [{}])[0].get("finish_reason") or ""),
    )


def extract_tool_calls(payload: dict[str, Any]) -> list[ToolCall]:
    """Parse ``choices[0].message.tool_calls``; malformed entries are skipped."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return []
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return []
    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list):
        return []
    out: list[ToolCall] = []
    for index, entry in enumerate(raw_calls):
        if not isinstance(entry, dict):
            continue
        function = entry.get("function")
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        raw_args = function.get("arguments")
        arguments: dict[str, Any] = {}
        if isinstance(raw_args, dict):
            arguments = raw_args
            raw_args = json.dumps(raw_args)
        elif isinstance(raw_args, str) and raw_args.strip():
            try:
                parsed = json.loads(raw_args)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                arguments = parsed
        else:
            raw_args = "{}"
        out.append(
            ToolCall(
                id=str(entry.get("id") or f"call_{index}"),
                name=name,
                arguments=arguments,
                raw_arguments=str(raw_args),
            )
        )
    return out


def _http_header_value(value: str) -> str:
    """HTTP header values must be latin-1; urllib raises on em dashes etc."""
    cleaned = (
        value.replace("\r", " ")
        .replace("\n", " ")
        .replace("\u2014", "-")
        .replace("\u2013", "-")
    )
    return cleaned.encode("latin-1", "replace").decode("latin-1")


def attribution_headers(service: str) -> dict[str, str]:
    """Headers OpenRouter uses to split Activity / Analytics by app."""
    app = resolve_app(service)
    return {
        "HTTP-Referer": _http_header_value(app.referer),
        "X-OpenRouter-Title": _http_header_value(app.title),
        "X-Title": _http_header_value(app.title),
        "X-OpenRouter-App-Visibility": "hidden",
    }


def _retry_sleep_seconds(attempt: int, *, status: int | None, retry_after: float | None) -> float:
    """Backoff for one retry. ``attempt`` is 1-based after increment."""
    base = 3.0 if status == 429 else 1.5
    exponential = min(_MAX_RETRY_SLEEP_SECONDS, base * (2 ** (attempt - 1)))
    if retry_after is not None and retry_after > 0:
        return min(_MAX_RETRY_SLEEP_SECONDS, max(exponential, retry_after))
    return exponential


def _retry_after_seconds(exc: urlerror.HTTPError) -> float | None:
    headers = getattr(exc, "headers", None)
    if headers is None:
        return None
    raw = ""
    try:
        raw = str(headers.get("Retry-After") or headers.get("retry-after") or "").strip()
    except Exception:
        return None
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _clock() -> float:
    """Retry-budget clock.

    Tool-loop tests patch ``time.monotonic`` to simulate spend. Using that
    here would steal their loop budget on every OpenRouter call. ``perf_counter``
    is the same kind of clock in production and stays real in those tests.
    """
    return time.perf_counter()


def _can_retry(*, deadline: float, sleep_s: float) -> bool:
    """True when sleep plus another attempt can still finish before ``deadline``."""
    return _clock() + max(0.0, sleep_s) + _MIN_RETRY_REMAINING_SECONDS < deadline


def post_json(
    *,
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout: int,
    max_retries: int = _MAX_RETRIES_DEFAULT,
    service: str = SERVICE_STATEMENT_PARSER,
) -> str:
    # ``timeout`` is the wall-clock budget for this call, including backoff
    # and retries. Each attempt uses only the time left so a late 5xx cannot
    # stack another full OpenRouter timeout and kill the Lambda.
    deadline = _clock() + max(1.0, float(timeout))
    attempt = 0
    while True:
        # First attempt keeps the caller's timeout. Later attempts use only
        # the leftover budget so retries cannot stack another full timeout.
        if attempt == 0:
            req_timeout = max(1, int(timeout))
        else:
            remaining = deadline - _clock()
            if remaining <= 0:
                raise OpenRouterError("OpenRouter request timed out: retry budget exhausted")
            req_timeout = max(1, int(remaining))
        data = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(  # noqa: S310 - URL is trusted (env-configured)
            url=url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                **attribution_headers(service),
            },
        )
        try:
            with urlrequest.urlopen(req, timeout=req_timeout) as resp:  # noqa: S310
                return resp.read().decode("utf-8")
        except urlerror.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:  # pragma: no cover - defensive
                body = ""
            if exc.code in _RETRYABLE_STATUSES and attempt < max_retries:
                sleep_s = _retry_sleep_seconds(
                    attempt + 1, status=exc.code, retry_after=_retry_after_seconds(exc)
                )
                if _can_retry(deadline=deadline, sleep_s=sleep_s):
                    attempt += 1
                    time.sleep(sleep_s)
                    continue
            preview = body.replace("\n", " ").strip()
            if len(preview) > 500:
                preview = f"{preview[:500]}..."
            detail = f": {preview}" if preview else ""
            raise OpenRouterError(
                f"OpenRouter request failed with status {exc.code}{detail}",
                status=exc.code,
            ) from exc
        except urlerror.URLError as exc:
            sleep_s = _retry_sleep_seconds(attempt + 1, status=None, retry_after=None)
            if attempt < max_retries and _can_retry(deadline=deadline, sleep_s=sleep_s):
                attempt += 1
                time.sleep(sleep_s)
                continue
            raise OpenRouterError(
                f"OpenRouter request transport error: {exc.reason}"
            ) from exc
        except _TRANSIENT_READ_ERRORS as exc:
            sleep_s = _retry_sleep_seconds(attempt + 1, status=None, retry_after=None)
            if attempt < max_retries and _can_retry(deadline=deadline, sleep_s=sleep_s):
                attempt += 1
                time.sleep(sleep_s)
                continue
            raise OpenRouterError(f"OpenRouter response was truncated: {exc}") from exc
        except TimeoutError as exc:
            raise OpenRouterError(f"OpenRouter request timed out: {exc}") from exc


def extract_message_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise OpenRouterError("OpenRouter response choices are missing")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise OpenRouterError("OpenRouter response choice has invalid shape")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise OpenRouterError("OpenRouter response message is missing")
    content = message.get("content")
    if isinstance(content, list):
        text_parts = [
            str(item.get("text"))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "\n".join(part for part in text_parts if part)
    return str(content or "")


def strip_code_fences(text: str) -> str:
    return (
        text.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )


def parse_json_object_text(text: str) -> dict[str, Any]:
    """Parse assistant text that should be a single JSON object.

    Tolerates markdown code fences and leading / trailing prose around the
    first balanced ``{...}`` block.
    """
    cleaned = strip_code_fences(text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise OpenRouterError("Model response is not a JSON object") from None
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise OpenRouterError("Model response is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise OpenRouterError("Model response payload is not an object")
    return parsed


def normalize_usage(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"promptTokens": 0, "completionTokens": 0, "totalTokens": 0, "cost": 0.0}
    prompt = _as_int(raw.get("prompt_tokens"))
    completion = _as_int(raw.get("completion_tokens"))
    total = _as_int(raw.get("total_tokens")) or (prompt + completion)
    cost_raw = raw.get("cost")
    cost = float(cost_raw) if isinstance(cost_raw, (int, float)) else 0.0
    return {
        "promptTokens": prompt,
        "completionTokens": completion,
        "totalTokens": total,
        "cost": round(cost, 6),
    }


def add_usage(total: dict[str, Any] | None, delta: dict[str, Any] | None) -> dict[str, Any]:
    base = normalize_usage(
        {
            "prompt_tokens": (total or {}).get("promptTokens", 0),
            "completion_tokens": (total or {}).get("completionTokens", 0),
            "total_tokens": (total or {}).get("totalTokens", 0),
            "cost": (total or {}).get("cost", 0.0),
        }
    )
    extra = delta or {}
    return {
        "promptTokens": base["promptTokens"] + _as_int(extra.get("promptTokens")),
        "completionTokens": base["completionTokens"]
        + _as_int(extra.get("completionTokens")),
        "totalTokens": base["totalTokens"] + _as_int(extra.get("totalTokens")),
        "cost": round(base["cost"] + float(extra.get("cost") or 0.0), 6),
    }


def catalog_app_ids() -> frozenset[str]:
    return frozenset(
        str(row["id"])
        for row in OPENROUTER_APP_CATALOG
        if isinstance(row, dict) and row.get("id")
    )


def resolve_api_key(secrets_client: Any, *, service: str = "") -> str:
    """Resolve the OpenRouter API key from env var or Secrets Manager.

    Catalog apps (see ``contracts/openrouter-apps.json``) each have a named
    key in the JSON secret. Sibling products mint a key on the same
    OpenRouter account and store it in *their* secret.
    """
    cache_key = (service or "").strip() or "*"
    cached = _api_key_cache.get(cache_key)
    if cached is not None:
        return cached
    direct = os.getenv("OPENROUTER_API_KEY", "").strip()
    if direct:
        _api_key_cache[cache_key] = direct
        return direct
    secret_arn = os.getenv("OPENROUTER_API_KEY_SECRET_ARN", "").strip()
    if not secret_arn:
        raise OpenRouterError(
            "OpenRouter API key is not configured (set OPENROUTER_API_KEY_SECRET_ARN)"
        )
    raw = read_secret_raw(secrets_client, secret_arn, what="OpenRouter API key")
    key = _pick_openrouter_key(raw, service=cache_key if cache_key != "*" else "")
    _api_key_cache[cache_key] = key
    return key


def _pick_openrouter_key(raw: str, *, service: str) -> str:
    catalog = catalog_app_ids()
    if not raw.startswith("{"):
        if service in catalog:
            raise OpenRouterError(
                f"OpenRouter secret must be JSON with a {service!r} named key; "
                "a plain-string secret cannot split the invoice by app"
            )
        return raw
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise OpenRouterError("OpenRouter API key secret JSON must be an object")
    if service:
        named = payload.get(service)
        if isinstance(named, str) and named.strip():
            return named.strip()
        if service in catalog:
            raise OpenRouterError(
                f"OpenRouter secret JSON is missing {service!r}; "
                "each catalog app needs its own named key"
            )
    for key_name in (
        "openrouter_api_key",
        "OPENROUTER_API_KEY",
        "api_key",
        "key",
        "token",
    ):
        candidate = payload.get(key_name)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    raise OpenRouterError("OpenRouter API key is missing in secret JSON")


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
        raise OpenRouterError(f"{what} secret is empty")
    raw = secret_string.strip()
    if not raw:
        raise OpenRouterError(f"{what} value is blank")
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
            raise OpenRouterError(f"{what} secret JSON must be an object")
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
        raise OpenRouterError(f"{what} is missing in secret JSON")
    return raw


def reset_api_key_cache_for_tests() -> None:
    global _api_key_cache
    _api_key_cache = {}


def _load_json_object(text: str, *, what: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OpenRouterError(f"{what} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise OpenRouterError(f"{what} must be a JSON object")
    return payload


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0
