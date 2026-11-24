"""Admin API: ddb convert."""

from __future__ import annotations

import base64
from decimal import Decimal
from typing import Any


def _to_ddb_nested(obj: Any) -> Any:
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_ddb_nested(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_ddb_nested(v) for v in obj]
    return obj


def _from_ddb_nested(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: _from_ddb_nested(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_ddb_nested(v) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        return base64.b64encode(obj).decode("ascii")
    return obj


def _to_ddb(obj: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in obj.items():
        if isinstance(v, float):
            out[k] = Decimal(str(v))
        else:
            out[k] = v
    return out


def _from_ddb(obj: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in obj.items():
        if isinstance(v, Decimal):
            if v % 1 == 0:
                out[k] = int(v)
            else:
                out[k] = float(v)
        elif isinstance(v, (bytes, bytearray)):
            out[k] = base64.b64encode(v).decode("ascii")
        else:
            out[k] = v
    return out
