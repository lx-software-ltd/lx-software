"""Convert JSON keys at the HTTP boundary.

This file is byte-identical in findingalpha and lx-software. Do not edit one copy.
Handlers and storage stay camelCase. Only keys are converted. Values, including
an enum that looks like a key, are left as they are.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode

# A camelCase key has at least one capital. A snake_case key has at least one underscore.
_CAMEL = re.compile(r"^[a-z][a-zA-Z0-9]*$")
_SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z][a-z0-9]*)+$")
_SINGLE_LETTER_PAIR = re.compile(r"(^|_)[a-z]_[a-z](_|$)")

_CONTRACT_NAME = "wire-format.json"


def load_contract(path: Path | None = None) -> dict[str, Any]:
    """The product contract copied next to this module."""
    source = path or Path(__file__).resolve().parent / "contracts" / _CONTRACT_NAME
    return json.loads(source.read_text(encoding="utf-8"))


def excluded(path: str, contract: dict[str, Any]) -> bool:
    """True when the codec skips this path in both directions."""
    for prefix in contract.get("excludedRoutes") or []:
        if path == prefix or path.startswith(prefix):
            return True
    return False


def to_wire(value: Any, contract: dict[str, Any], route: str = "") -> Any:
    """Rename keys for the response body."""
    return _walk(value, contract, inbound=False, data_levels=_root_levels(contract, route))


def from_wire(value: Any, contract: dict[str, Any], route: str = "") -> Any:
    """Rename keys from a request body back to the handler names."""
    return _walk(value, contract, inbound=True, data_levels=_root_levels(contract, route))


def prepare_request(event: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Convert a JSON body, the query names and the path-parameter names."""
    prepared = dict(event)
    prepared["body"] = _request_body(event.get("body"), bool(event.get("isBase64Encoded")), contract)
    if event.get("isBase64Encoded") and prepared["body"] is not event.get("body"):
        prepared["isBase64Encoded"] = False
    query = event.get("queryStringParameters")
    if isinstance(query, dict):
        prepared["queryStringParameters"] = _convert_mapping(query, contract, inbound=True)
    raw = event.get("rawQueryString")
    if isinstance(raw, str) and raw:
        prepared["rawQueryString"] = _convert_raw_query(raw, contract, inbound=True)
    params = event.get("pathParameters")
    if isinstance(params, dict):
        prepared["pathParameters"] = _convert_mapping(params, contract, inbound=True)
    return prepared


def prepare_response(response: dict[str, Any], contract: dict[str, Any], route: str = "") -> dict[str, Any] | None:
    """Convert a JSON body. ``None`` means the body did not parse and was left alone."""
    if not isinstance(response, dict):
        return response
    if response.get("isBase64Encoded"):
        return response
    headers = response.get("headers") or {}
    if not isinstance(headers, dict) or not _is_json(headers):
        return response
    body = response.get("body")
    if not isinstance(body, str):
        return response
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None
    converted = dict(response)
    converted["body"] = json.dumps(to_wire(parsed, contract, route), default=str)
    return converted


def bad_wire_key(key: str) -> bool:
    """A wire key that is still camelCase, or that has two single-letter segments."""
    return _is_camel(key) or _SINGLE_LETTER_PAIR.search(key) is not None


def iter_checked_keys(value: Any, contract: dict[str, Any], route: str = ""):
    """Yield wire keys that are outside a map field and an opaque field."""
    yield from _iter_keys(value, contract, _root_levels(contract, route))


def _root_levels(contract: dict[str, Any], route: str) -> int:
    roots = contract.get("rootMaps") or {}
    level = roots.get(route, 0)
    return int(level) if isinstance(level, int) else 0


def _walk(value: Any, contract: dict[str, Any], *, inbound: bool, data_levels: int) -> Any:
    if data_levels > 0:
        if isinstance(value, dict):
            return {
                key: _walk(child, contract, inbound=inbound, data_levels=data_levels - 1)
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [_walk(child, contract, inbound=inbound, data_levels=data_levels) for child in value]
        return value
    if isinstance(value, list):
        return [_walk(child, contract, inbound=inbound, data_levels=0) for child in value]
    if not isinstance(value, dict):
        return value
    opaque = set(contract.get("opaqueFields") or [])
    maps = contract.get("mapFields") or {}
    out: dict[str, Any] = {}
    for key, child in value.items():
        if _verbatim(key, contract):
            internal = key
            renamed = key
        elif inbound:
            internal = _key_from_wire(key, contract)
            renamed = internal
        else:
            internal = key
            renamed = _key_to_wire(key, contract)
        if internal in opaque or key in opaque:
            out[renamed] = child
            continue
        levels = maps.get(internal, 0)
        if not isinstance(levels, int):
            levels = 0
        out[renamed] = _walk(child, contract, inbound=inbound, data_levels=levels)
    return out


def _iter_keys(value: Any, contract: dict[str, Any], data_levels: int):
    if data_levels > 0:
        if isinstance(value, dict):
            for child in value.values():
                yield from _iter_keys(child, contract, data_levels - 1)
        elif isinstance(value, list):
            for child in value:
                yield from _iter_keys(child, contract, data_levels)
        return
    if isinstance(value, list):
        for child in value:
            yield from _iter_keys(child, contract, 0)
        return
    if not isinstance(value, dict):
        return
    opaque = set(contract.get("opaqueFields") or [])
    maps = contract.get("mapFields") or {}
    for key, child in value.items():
        internal = key if _verbatim(key, contract) else _key_from_wire(key, contract)
        if internal in opaque or key in opaque:
            continue
        yield key
        levels = maps.get(internal, 0)
        if not isinstance(levels, int):
            levels = 0
        yield from _iter_keys(child, contract, levels)


def _verbatim(key: str, contract: dict[str, Any]) -> bool:
    return key in set(contract.get("verbatimKeys") or [])


def _key_to_wire(key: str, contract: dict[str, Any]) -> str:
    if _verbatim(key, contract):
        return key
    renamed = (contract.get("renames") or {}).get(key)
    if isinstance(renamed, str):
        return renamed
    if _is_camel(key):
        return "".join(f"_{char.lower()}" if char.isupper() else char for char in key)
    return key


def _key_from_wire(key: str, contract: dict[str, Any]) -> str:
    if _verbatim(key, contract):
        return key
    reverse = _reverse_renames(contract)
    if key in reverse:
        return reverse[key]
    if _SNAKE.fullmatch(key):
        chars: list[str] = []
        index = 0
        while index < len(key):
            if key[index] == "_" and index + 1 < len(key):
                chars.append(key[index + 1].upper())
                index += 2
            else:
                chars.append(key[index])
                index += 1
        return "".join(chars)
    return key


def _reverse_renames(contract: dict[str, Any]) -> dict[str, str]:
    reverse: dict[str, str] = {}
    for internal, wire in (contract.get("renames") or {}).items():
        if isinstance(wire, str):
            reverse[wire] = str(internal)
    return reverse


def _is_camel(key: str) -> bool:
    return _CAMEL.fullmatch(key) is not None and any(char.isupper() for char in key)


def _convert_mapping(values: dict[str, Any], contract: dict[str, Any], *, inbound: bool) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    for key, value in values.items():
        renamed = _key_from_wire(str(key), contract) if inbound else _key_to_wire(str(key), contract)
        converted[renamed] = value
    return converted


def _convert_raw_query(raw: str, contract: dict[str, Any], *, inbound: bool) -> str:
    pairs = parse_qsl(raw, keep_blank_values=True)
    renamed = [
        (_key_from_wire(key, contract) if inbound else _key_to_wire(key, contract), value) for key, value in pairs
    ]
    return urlencode(renamed)


def _request_body(body: Any, encoded: bool, contract: dict[str, Any]) -> Any:
    if not isinstance(body, str) or not body:
        return body
    text = body
    if encoded:
        import base64
        import binascii

        try:
            text = base64.b64decode(body, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError, binascii.Error):
            return body
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return body
    return json.dumps(from_wire(parsed, contract))


def _is_json(headers: dict[str, Any]) -> bool:
    for key, value in headers.items():
        if str(key).lower() == "content-type" and isinstance(value, str) and "json" in value.lower():
            return True
    return False
