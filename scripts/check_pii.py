#!/usr/bin/env python3
"""Fail when tracked source contains a denylisted personal-data value.

``scripts/pii-denylist.sha256`` stores SHA-256 hex digests only. A hit is
reported as a path and line number, without the matched text.

Normalization, applied to each line and to each pair of consecutive lines:

- lowercase
- drop ASCII apostrophes and right single quotation marks
- hash emails matched in that text
- hash the digits of a phone-like run when the digit length is 8 to 20
- replace every other character outside ``[a-z0-9.+@]`` with a space
- hash each token (a leading ``@`` is stripped, and leading or trailing
  ``.`` is stripped so sentence punctuation does not hide a match) and each
  2- to 6-token window
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DENYLIST_PATH = ROOT / "scripts" / "pii-denylist.sha256"
SCAN_SUFFIXES = {
    ".css",
    ".dart",
    ".html",
    ".js",
    ".md",
    ".mdc",
    ".mjs",
    ".py",
    ".sh",
    ".sql",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}
EMAIL_RE = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}")
PHONE_RE = re.compile(r"\d[\d\s().+\-]{6,}\d")
TOKEN_RE = re.compile(r"[^a-z0-9.+@]+")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_denylist() -> set[str]:
    hashes: set[str] = set()
    for line in DENYLIST_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip().lower()
        if not stripped or stripped.startswith("#"):
            continue
        hashes.add(stripped)
    return hashes


def _candidates(text: str) -> set[str]:
    lowered = text.lower().replace("’", "").replace("'", "")
    found: set[str] = set()
    found.update(EMAIL_RE.findall(lowered))
    for match in PHONE_RE.findall(lowered):
        digits = re.sub(r"\D", "", match)
        if 8 <= len(digits) <= 20:
            found.add(digits)
    tokens: list[str] = []
    for token in TOKEN_RE.sub(" ", lowered).split():
        if token.startswith("@"):
            token = token[1:]
        token = token.strip(".")
        if token:
            tokens.append(token)
    for size in range(1, 7):
        for index in range(0, len(tokens) - size + 1):
            found.add(" ".join(tokens[index : index + size]))
    return found


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    paths: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        path = ROOT / raw.decode("utf-8")
        if path.suffix.lower() in SCAN_SUFFIXES:
            paths.append(path)
    return paths


def _matching_lines(path: Path, denied: set[str]) -> list[int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    hits: list[int] = []
    for index, line in enumerate(lines, start=1):
        windows = [line]
        if index < len(lines):
            windows.append(f"{line} {lines[index]}")
        for window in windows:
            if any(_digest(candidate) in denied for candidate in _candidates(window)):
                hits.append(index)
                break
    return hits


def main() -> int:
    if not DENYLIST_PATH.is_file():
        print(f"missing denylist: {DENYLIST_PATH}", file=sys.stderr)
        return 1
    denied = _load_denylist()
    failures = 0
    for path in _tracked_files():
        try:
            hits = _matching_lines(path, denied)
        except OSError as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            return 1
        for line_number in hits:
            relative = path.relative_to(ROOT)
            print(f"{relative}:{line_number}: denylisted personal data")
            failures += 1
    if failures:
        print(
            f"pii check failed: {failures} line(s) match the hashed denylist",
            file=sys.stderr,
        )
        return 1
    print("pii check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
