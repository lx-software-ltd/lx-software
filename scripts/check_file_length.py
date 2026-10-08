#!/usr/bin/env python3
"""Fail when source files grow past their ceiling.

Python under ``backend/lambda`` (not tests) has a 500-line ceiling.
TypeScript under ``apps/**/src`` and ``backend/infrastructure/lib`` has an
800-line ceiling. ``scripts/file-length-allowlist.txt`` records each file
already over its ceiling. A listed file may not grow. Shrinking it requires
lowering the allowance in the same change. Dropping to the ceiling or below
requires removing the entry. Generated contract output is not scanned.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = ROOT / "scripts" / "file-length-allowlist.txt"
PYTHON_LIMIT = 500
TYPESCRIPT_LIMIT = 800


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def limit_for(rel: str) -> int | None:
    """Return the ceiling for a repo-relative path, or None when it is not scanned."""
    path = Path(rel)
    if "node_modules" in path.parts or "dist" in path.parts:
        return None
    if rel.startswith("backend/lambda/") and path.suffix == ".py":
        if path.name.startswith("test_"):
            return None
        return PYTHON_LIMIT
    if rel.endswith("src/lib/contracts/generated.ts"):
        return None
    if path.suffix in {".ts", ".tsx"} and ".test." not in path.name and ".spec." not in path.name:
        if rel.startswith("apps/") and "/src/" in rel:
            return TYPESCRIPT_LIMIT
        if rel.startswith("backend/infrastructure/lib/"):
            return TYPESCRIPT_LIMIT
    return None


def iter_source_files() -> list[Path]:
    roots = (ROOT / "backend" / "lambda", ROOT / "backend" / "infrastructure" / "lib", ROOT / "apps")
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in {"node_modules", "dist"} for part in path.parts):
                continue
            rel = path.relative_to(ROOT).as_posix()
            if limit_for(rel) is None:
                continue
            files.append(path)
    return files


def load_allowlist(text: str | None = None) -> dict[str, int]:
    raw = text if text is not None else ALLOWLIST_PATH.read_text(encoding="utf-8")
    allowed: dict[str, int] = {}
    for line_number, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            rel_path, count_text = stripped.rsplit(None, 1)
            count = int(count_text)
        except ValueError as exc:
            raise SystemExit(f"{ALLOWLIST_PATH}:{line_number}: expected '<path> <lines>'") from exc
        if rel_path in allowed:
            raise SystemExit(f"{ALLOWLIST_PATH}:{line_number}: duplicate entry for {rel_path}")
        ceiling = limit_for(rel_path)
        if ceiling is None:
            raise SystemExit(f"{ALLOWLIST_PATH}:{line_number}: {rel_path} is not a scanned file")
        if count <= ceiling:
            raise SystemExit(
                f"{ALLOWLIST_PATH}:{line_number}: {rel_path} allowance {count} is not above {ceiling}; remove it"
            )
        allowed[rel_path] = count
    return allowed


def problems(counts: dict[str, int], allowed: dict[str, int]) -> list[str]:
    errors: list[str] = []
    for rel, count in sorted(counts.items()):
        ceiling = limit_for(rel)
        if ceiling is None:
            continue
        allowance = allowed.get(rel)
        if count <= ceiling:
            if allowance is not None:
                errors.append(f"{rel} is {count} lines; remove it from the allowlist")
            continue
        if allowance is None:
            errors.append(
                f"{rel} is {count} lines (limit {ceiling}); split it or, if it already exists, allowlist {count}"
            )
        elif count > allowance:
            errors.append(f"{rel} grew from {allowance} to {count} lines")
        elif count < allowance:
            errors.append(f"{rel} shrank from {allowance} to {count} lines; lower its allowlist entry")
    for rel in sorted(set(allowed) - set(counts)):
        errors.append(f"{rel} is allowlisted but was not found")
    return errors


def main() -> int:
    allowed = load_allowlist() if ALLOWLIST_PATH.exists() else {}
    counts = {path.relative_to(ROOT).as_posix(): line_count(path) for path in iter_source_files()}
    errors = problems(counts, allowed)
    if errors:
        print("File length check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("File length check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
