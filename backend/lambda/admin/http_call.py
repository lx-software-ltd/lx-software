"""The only test entry to the HTTP handler.

Tests build camelCase bodies and query names. This helper puts them on the
wire, calls the handler, and returns a JSON body in camelCase. The response
must round-trip, and no checked key may be camelCase or have two
single-letter segments in a row.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import dispatch
import wire_format


def http_call(event: dict[str, Any], context: Any = None, *, raw: bool = False) -> dict[str, Any]:
    del context
    if not _is_http(event):
        return dispatch.lambda_handler(event, None)
    contract = wire_format.load_contract()
    method, path = _route(event)
    if wire_format.excluded(path, contract):
        return dispatch.lambda_handler(event, None)
    _assert_request_round_trip(event, contract)
    response = dispatch.lambda_handler(_to_wire_event(event, contract), None)
    if raw or not _is_json_response(response):
        return response
    route = f"{method} {path}"
    parsed = json.loads(response["body"])
    for key in wire_format.iter_checked_keys(parsed, contract, route):
        if wire_format.bad_wire_key(key):
            raise AssertionError(f"wire key {key!r} on {route}")
    back = wire_format.from_wire(parsed, contract, route)
    if wire_format.to_wire(back, contract, route) != parsed:
        raise AssertionError(f"response does not round-trip on {route}")
    returned = dict(response)
    returned["body"] = json.dumps(back)
    return returned


def _is_http(event: dict[str, Any]) -> bool:
    http = (event.get("requestContext") or {}).get("http") or {}
    return "path" in http or "method" in http


def _route(event: dict[str, Any]) -> tuple[str, str]:
    http = (event.get("requestContext") or {}).get("http") or {}
    return str(http.get("method") or ""), str(http.get("path") or "")


def _assert_request_round_trip(event: dict[str, Any], contract: dict[str, Any]) -> None:
    parsed = _json_body(event)
    if parsed is None:
        return
    wire = wire_format.to_wire(parsed, contract)
    if wire_format.from_wire(wire, contract) != parsed:
        raise AssertionError("request body does not round-trip")


def _to_wire_event(event: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(event)
    body = event.get("body")
    if event.get("isBase64Encoded") and isinstance(body, str) and body:
        try:
            text = base64.b64decode(body, validate=True).decode("utf-8")
            parsed = json.loads(text)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            parsed = None
        if parsed is not None:
            encoded = json.dumps(wire_format.to_wire(parsed, contract)).encode("utf-8")
            prepared["body"] = base64.b64encode(encoded).decode("ascii")
    elif isinstance(body, str) and body:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            prepared["body"] = json.dumps(wire_format.to_wire(parsed, contract))
    query = event.get("queryStringParameters")
    if isinstance(query, dict):
        prepared["queryStringParameters"] = {_wire_key(str(key), contract): value for key, value in query.items()}
    raw = event.get("rawQueryString")
    if isinstance(raw, str) and raw:
        prepared["rawQueryString"] = _raw_to_wire(raw, contract)
    params = event.get("pathParameters")
    if isinstance(params, dict):
        prepared["pathParameters"] = {_wire_key(str(key), contract): value for key, value in params.items()}
    return prepared


def _raw_to_wire(raw: str, contract: dict[str, Any]) -> str:
    from urllib.parse import parse_qsl, urlencode

    pairs = parse_qsl(raw, keep_blank_values=True)
    return urlencode([(_wire_key(key, contract), value) for key, value in pairs])


def _wire_key(key: str, contract: dict[str, Any]) -> str:
    renamed = wire_format.to_wire({key: None}, contract)
    return next(iter(renamed))


def _json_body(event: dict[str, Any]) -> Any:
    body = event.get("body")
    if not isinstance(body, str) or not body or event.get("isBase64Encoded"):
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def _is_json_response(response: dict[str, Any]) -> bool:
    if not isinstance(response, dict) or response.get("isBase64Encoded") or not isinstance(response.get("body"), str):
        return False
    headers = response.get("headers") or {}
    if not isinstance(headers, dict):
        return False
    for key, value in headers.items():
        if str(key).lower() == "content-type" and isinstance(value, str) and "json" in value.lower():
            return True
    return False
