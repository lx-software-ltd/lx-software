"""Admin API: http common."""

from __future__ import annotations

import base64
import binascii
import contextvars
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import runtime
from botocore.exceptions import ClientError
from runtime import ADMIN_GROUP, logger

_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("lxsoftware_request_id", default="")

_PROBLEMS = {
    400: ("invalid_request", "Bad Request"),
    401: ("unauthenticated", "Unauthorized"),
    403: ("forbidden", "Forbidden"),
    404: ("not_found", "Not Found"),
    405: ("method_not_allowed", "Method Not Allowed"),
    409: ("conflict", "Conflict"),
    429: ("rate_limited", "Too Many Requests"),
    500: ("internal_error", "Internal Server Error"),
    503: ("unavailable", "Service Unavailable"),
}


def bind_request_id(event: dict[str, Any]) -> contextvars.Token[str]:
    """Remember the HTTP request id for `_json_response`. Empty when there is none.

    The token is what ``request_id_scope`` resets. The public API authorizer
    is another function and does not read this variable. Webhook routes in
    this process enter through ``lambda_handler``.
    """
    found = _request_id(event)
    return _REQUEST_ID.set("" if found == "unknown" else found)


@contextmanager
def request_id_scope(event: Any) -> Iterator[None]:
    """Bind the id for one invocation and clear it before the process is reused."""
    token = bind_request_id(event if isinstance(event, dict) else {})
    try:
        yield
    finally:
        _REQUEST_ID.reset(token)


def _problem_field(out: dict[str, Any], key: str, value: Any) -> None:
    """Replace a handler field that is not already the problem value.

    A provider error number in ``code`` or a record status must not stay.
    An error that already carries the problem value keeps it. No error body
    in this Lambda sets ``code`` or ``status`` today. ``reason`` still
    carries the deny reason. ``message`` and every other key stay.
    """
    if out.get(key) != value:
        out[key] = value


def _with_problem(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    code, title = _PROBLEMS.get(status_code, ("error", "Error"))
    message = payload.get("message")
    detail = message if isinstance(message, str) and message else title
    out = dict(payload)
    out.setdefault("type", "about:blank")
    out.setdefault("title", title)
    _problem_field(out, "status", status_code)
    out.setdefault("detail", detail)
    _problem_field(out, "code", code)
    out.setdefault("request_id", _REQUEST_ID.get())
    return out


def request_id_headers() -> dict[str, str]:
    """The ``x-request-id`` header when this invocation bound one."""
    request_id = _REQUEST_ID.get()
    if not request_id:
        return {}
    return {"x-request-id": request_id}


def html_headers() -> dict[str, str]:
    """HTML response headers, including the request id when one is bound."""
    return {"content-type": "text/html; charset=utf-8", **request_id_headers()}


def _json_response(status_code: int, payload: dict[str, Any] | list[Any] | str) -> dict[str, Any]:
    if status_code >= 400 and isinstance(payload, dict):
        payload = _with_problem(status_code, payload)
    body = _g if isinstance(_g := payload, str) else json.dumps(payload, default=str)
    headers = {"Content-Type": "application/json", **request_id_headers()}
    return {"statusCode": status_code, "headers": headers, "body": body}


def not_found() -> dict[str, Any]:
    return _json_response(404, {"message": "Not found"})


def method_not_allowed() -> dict[str, Any]:
    return _json_response(405, {"message": "Method not allowed"})


def _parse_json_body(event: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _claims(event: dict[str, Any]) -> dict[str, Any]:
    return event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})


def _public_authorizer_context(event: dict[str, Any]) -> dict[str, Any]:
    """Opaque context from the public API Lambda authorizer (simple response).

    API Gateway HTTP API places a Lambda authorizer's ``context`` under
    ``requestContext.authorizer.lambda``. That map holds the key id, scopes and
    write flag — never the raw key. Returns ``{}`` when the request was not
    authorized by that authorizer (e.g. Cognito JWT routes).

    The identifier avoids ``api_key`` so CodeQL does not treat the return value
    as credential material (``py/weak-sensitive-data-hashing``).
    """
    ctx = event.get("requestContext", {}).get("authorizer", {}).get("lambda")
    return _g if isinstance(_g := ctx, dict) else {}


def _groups_include_admin(claims: dict[str, Any]) -> bool:
    raw = claims.get("cognito:groups")
    if raw is None:
        return False
    if isinstance(raw, list):
        return ADMIN_GROUP in raw
    # API Gateway HTTP API JWT authorizer flattens array claims using Java-style
    # toString(), e.g. ["admin"] -> "[admin]" and ["viewer","admin"] -> "[viewer, admin]".
    # Strip the surrounding brackets before splitting on commas so we accept
    # both the bracketed form (HttpApi authorizer) and a plain comma-separated
    # string (REST API or local-decoded claims).
    s = str(raw).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return ADMIN_GROUP in parts


def _require_admin(event: dict[str, Any]) -> dict[str, Any] | None:
    claims = _claims(event)
    if not _groups_include_admin(claims):
        return None
    return claims


def _route(event: dict[str, Any]) -> tuple[str, str]:
    http = event.get("requestContext", {}).get("http", {})
    return http.get("method", ""), http.get("path", "")


# Links already sent keep these paths. Subscribe moved and has no old copy.
_LEGACY_EXACT = {
    "/webhooks/meta": "/v1/webhooks/meta",
    "/webhooks/meta/siutindei": "/v1/webhooks/meta/siutindei",
}
_LEGACY_PREFIX = (
    ("/public/outreach/unsubscribe/", "/v1/public/outreach/unsubscribe/"),
    ("/public/newsletter/confirm/", "/v1/public/newsletter/confirm/"),
    ("/public/newsletter/unsubscribe/", "/v1/public/newsletter/unsubscribe/"),
)
# One deploy of the previous board URL. Callers still send camelCase.
_LEGACY_BOARD = "/public/siu-tin-dei/board"
_LEGACY_BOARD_TARGET = "/v1/partner/siutindei/board"
_WIRE_CONTRACT: dict[str, Any] | None = None


def _legacy_board(path: str) -> bool:
    return path == _LEGACY_BOARD or path.startswith(_LEGACY_BOARD + "/")


def legacy_http_path(path: str) -> str:
    """Map a route that stays forever onto the path the table matches."""
    mapped = _LEGACY_EXACT.get(path)
    if mapped:
        return mapped
    if _legacy_board(path):
        return _LEGACY_BOARD_TARGET + path[len(_LEGACY_BOARD) :]
    for old, new in _LEGACY_PREFIX:
        if path.startswith(old):
            return new + path[len(old) :]
    return path


def http_audience(path: str) -> tuple[str, str]:
    """Return ``(audience, path the route table matches)``.

    Admin paths are the inner path (``/v1/admin`` removed). Partner paths stay
    whole, because ``/finance`` is both an admin route and a partner route.
    """
    path = legacy_http_path(path)
    if path == "/health":
        return "none", path
    if path == "/v1/admin" or path.startswith("/v1/admin/"):
        return "admin", path[len("/v1/admin") :] or "/"
    if path == "/v1/partner" or path.startswith("/v1/partner/"):
        return "partner", path
    if path == "/v1/public" or path.startswith("/v1/public/"):
        return "public", path
    if path == "/v1/webhooks" or path.startswith("/v1/webhooks/"):
        return "webhooks", path[len("/v1") :]
    return "unknown", path


def _wire_contract() -> dict[str, Any]:
    """The product contract, read once per process."""
    global _WIRE_CONTRACT
    if _WIRE_CONTRACT is None:
        import wire_format

        _WIRE_CONTRACT = wire_format.load_contract()
    return _WIRE_CONTRACT


def apply_wire(event: dict[str, Any], respond: Any) -> Any:
    """Convert JSON keys at the HTTP boundary, after the handler returns."""
    import wire_format

    with request_id_scope(event):
        method, path = _route(event)
        contract = _wire_contract()
        if not wire_format.excluded(path, contract):
            event = wire_format.prepare_request(event, contract)
        response = respond(event)
        # The old board path keeps camelCase. The new path is snake_case.
        if _legacy_board(path) or wire_format.excluded(path, contract):
            return response
        prepared = wire_format.prepare_response(response, contract, f"{method} {path}")
        if prepared is None:
            _log_event("warning", tag="wire_format_pass_through", path=path)
            return response
        return prepared


def _request_id(event: dict[str, Any]) -> str:
    return (
        event.get("requestContext", {}).get("requestId", "")
        or event.get("requestContext", {}).get("http", {}).get("requestId", "")
        or "unknown"
    )


def _audit(user_sub: str | None, action: str, target: str, event: dict[str, Any]) -> None:
    if not user_sub:
        return
    try:
        table = runtime._ddb.Table(os.environ["AUDIT_LOG_TABLE_NAME"])
        ts = int(time.time() * 1000)
        table.put_item(
            Item={
                "pk": f"USER#{user_sub}",
                "sk": f"{ts}#{action}",
                "target": target,
                "requestId": _request_id(event),
            }
        )
    except ClientError as exc:
        _log_event(
            "warning",
            tag="audit_write_failed",
            action=action,
            error=exc.response.get("Error", {}).get("Code", "ClientError"),
        )


def _log_event(level: str, **fields: Any) -> None:
    """Emit a single-line JSON log row.

    All non-`tag` fields are PII-safe scalars (sub, content type, S3 key,
    sizes, error codes, request id). Used by the asset upload + statement
    parse endpoints so a future "the upload silently failed" report can be
    diagnosed from CloudWatch alone, without needing the user's browser.
    """
    payload = {k: v for k, v in fields.items() if v is not None}
    line = json.dumps(payload, default=str)
    if level == "warning":
        logger.warning(line)
    elif level == "error":
        logger.error(line)
    else:
        logger.info(line)


def _decode_cursor(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        pad = "=" * ((4 - len(raw) % 4) % 4)
        blob = base64.urlsafe_b64decode(raw + pad)
        return json.loads(blob.decode("utf-8"))
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _utc_iso_z(dt: datetime) -> str:
    """Format an aware or naive datetime as UTC with millisecond precision."""
    from timeutil import format_iso_millis

    return format_iso_millis(dt)


def utc_now() -> datetime:
    from timeutil import utc_now as _utc_now

    return _utc_now()


def now_iso() -> str:
    from timeutil import now_iso as _now_iso

    return _now_iso()


def parse_iso(value: Any) -> datetime | None:
    from timeutil import parse_iso as _parse_iso

    return _parse_iso(value)


def parse_iso_strict(value: str) -> datetime:
    from timeutil import parse_iso_strict as _parse_iso_strict

    return _parse_iso_strict(value)


def _encode_cursor(key: dict[str, Any]) -> str:
    raw = json.dumps(key, separators=(",", ":"), default=str).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _read_http_error(exc: Any, limit: int | None = None) -> bytes:
    """Read an HTTP error body and close it.

    Python 3.14 warns when an urllib HTTP error is garbage-collected
    while it is still open. ``limit`` is passed to ``read`` when set.
    A missing body is ``b""``.
    """
    try:
        if getattr(exc, "fp", None) is None:
            return b""
        data = exc.read() if limit is None else exc.read(limit)
        return data or b""
    finally:
        _close_http_error(exc)


def _close_http_error(exc: Any) -> Any:
    """Close an HTTP error and return it.

    ``raise ... from _close_http_error(exc)`` keeps the original cause.
    The error object is truthy, so ``if cond and _close_http_error(exc)``
    closes it and still enters the branch.
    """
    close = getattr(exc, "close", None)
    if callable(close):
        close()
    return exc
