"""Small HTTP/internal route table for the admin Lambda."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Route:
    method: str
    pattern: str
    handler: Callable[..., Any]
    auth: str
    kind: str = "exact"
    match: Callable[[str, str], bool] | None = None


def route_matches(route: Route, method: str, path: str) -> bool:
    if route.match is not None:
        return route.match(method, path)
    if route.kind == "any":
        return True
    if route.method not in ("*", method):
        return False
    if route.kind == "exact":
        return path == route.pattern
    if route.kind == "prefix":
        return path.startswith(route.pattern)
    return False
