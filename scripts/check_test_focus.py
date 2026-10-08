#!/usr/bin/env python3
"""Reject focused tests and skips that have no condition.

``test.skip(condition, reason)`` stays allowed. ``test.skip()``,
``it.skip("reason")``, ``.only``, ``fit``, ``fdescribe``, ``xit``, and
``@unittest.skip`` without a reason string do not.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEARCH_ROOTS = (
    ROOT / "apps",
    ROOT / "backend" / "lambda",
    ROOT / "backend" / "infrastructure" / "test",
    ROOT / "scripts",
)
FOCUSED = re.compile(r"\.only\s*\(|\bfit\s*\(|\bfdescribe\s*\(|\bxit\s*\(|\bxdescribe\s*\(")
UNCONDITIONAL_SKIP = re.compile(r"\b(?:test|it|describe|context)\.skip\s*\(\s*(?:\)|['\"`])")
UNITTEST_SKIP = re.compile(r"@unittest\.skip(?!If)\b")
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs"}


def _is_test_file(path: Path) -> bool:
    name = path.name
    if path.suffix not in SOURCE_SUFFIXES:
        return False
    if name.startswith("test_") or ".test." in name or ".spec." in name:
        return True
    return "e2e" in path.parts


def iter_files() -> list[Path]:
    files: list[Path] = []
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or not _is_test_file(path):
                continue
            if any(part in {"node_modules", "dist"} for part in path.parts):
                continue
            files.append(path)
    return files


def line_problem(line: str, *, python: bool) -> str | None:
    if FOCUSED.search(line) or UNCONDITIONAL_SKIP.search(line):
        return line.strip()
    if python and UNITTEST_SKIP.search(line) and not re.search(r"['\"]", line):
        return line.strip()
    return None


def main() -> int:
    errors: list[str] = []
    for path in iter_files():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            problem = line_problem(line, python=path.suffix == ".py")
            if problem:
                errors.append(f"{rel}:{line_number}: {problem}")
    if errors:
        print("Test focus check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Test focus check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
