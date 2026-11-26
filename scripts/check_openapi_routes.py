#!/usr/bin/env python3
"""Fail when docs/api and the admin route table disagree.

A line reader. No YAML package. Paths are the keys indented two spaces.
Methods are the keys indented four spaces.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "backend" / "infrastructure" / "lib" / "admin-api-routes.ts"
DOCS = ROOT / "docs" / "api"

PATH_LINE = re.compile(r'^  "?(/[^":]+)"?:\s*$')
METHOD_LINE = re.compile(r"^    (get|put|post|patch|delete|head|options):\s*$")
ROUTE = re.compile(r'path:\s*"([^"]+)"\s*,\s*methods:\s*\[([^\]]+)\]')
METHOD_NAME = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b")


def documented() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for file in sorted(DOCS.glob("*.yaml")):
        path = ""
        for line in file.read_text(encoding="utf-8").splitlines():
            path_match = PATH_LINE.match(line)
            if path_match:
                path = path_match.group(1)
                continue
            method_match = METHOD_LINE.match(line)
            if method_match and path:
                found.add((path, method_match.group(1).upper()))
    return found


def declared() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path, methods in ROUTE.findall(ROUTES.read_text(encoding="utf-8")):
        for method in METHOD_NAME.findall(methods):
            found.add((path, method))
    return found


def main() -> int:
    docs = documented()
    code = declared()
    missing = sorted(code - docs)
    extra = sorted(docs - code)
    if not code:
        print("admin-api-routes.ts has no routes", file=sys.stderr)
        return 1
    if missing or extra:
        for path, method in missing:
            print(f"missing from docs/api: {method} {path}", file=sys.stderr)
        for path, method in extra:
            print(f"not in admin-api-routes.ts: {method} {path}", file=sys.stderr)
        return 1
    print(f"openapi routes match admin-api-routes.ts ({len(code)} methods)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
