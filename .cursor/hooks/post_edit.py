#!/usr/bin/env python3
"""Format a file after an edit and report lint failures back to the agent."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


def _tool_input(payload: dict) -> dict:
    raw = payload.get("tool_input")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _edited_path(payload: dict) -> Path | None:
    """Resolve the edited file from the documented hook payloads.

    ``afterFileEdit`` sends a top-level ``file_path``. ``postToolUse`` for the
    ``Write`` tool sends ``tool_input.path``.
    """
    candidates: list[str] = []
    top_level = payload.get("file_path")
    if isinstance(top_level, str) and top_level:
        candidates.append(top_level)
    raw = _tool_input(payload)
    for key in ("path", "file_path", "target_notebook"):
        value = raw.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)
    if not candidates:
        return None
    path = Path(candidates[0])
    if not path.is_absolute():
        workspace = payload.get("cwd") or Path.cwd()
        path = Path(str(workspace)) / path
    return path


def _ruff_argv() -> list[str] | None:
    found = shutil.which("ruff")
    if found:
        return [found]
    probe = subprocess.run(
        [sys.executable, "-m", "ruff", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0:
        return [sys.executable, "-m", "ruff"]
    return None


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _nearest_eslint_root(path: Path) -> Path | None:
    for parent in [path.parent, *path.parents]:
        if (parent / "package.json").exists() and (
            (parent / "eslint.config.js").exists() or (parent / "eslint.config.mjs").exists()
        ):
            return parent
        if parent == parent.parent:
            break
    return None


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=False, capture_output=True, text=True)


def format_and_lint(path: Path) -> str:
    """Return additional context for the agent, or an empty string on success."""
    if path.suffix not in TEXT_SUFFIXES or not path.exists():
        return ""
    before = _digest(path)
    notes: list[str] = []
    if path.suffix == ".py":
        ruff = _ruff_argv()
        if ruff is None:
            return (
                "Ruff is not installed, so this Python edit was not formatted. "
                "Install it with python3 -m pip install 'ruff>=0.3.0'."
            )
        _run([*ruff, "format", str(path)])
        check = _run([*ruff, "check", str(path)])
        if check.returncode != 0:
            notes.append((check.stdout or check.stderr).strip())
    else:
        root = _nearest_eslint_root(path)
        if root is None or not (root / "node_modules").exists():
            return ""
        eslint = root / "node_modules" / ".bin" / "eslint"
        if not eslint.exists():
            return ""
        relative = path.relative_to(root) if path.is_relative_to(root) else path
        check = _run([str(eslint), "--fix", "--max-warnings=0", str(relative)], cwd=root)
        if check.returncode != 0:
            notes.append((check.stdout or check.stderr).strip())
    changed = path.exists() and _digest(path) != before
    if changed:
        notes.insert(0, f"Formatted {path}. Re-read it before editing again.")
    if not notes:
        return ""
    return "\n".join(note for note in notes if note)[:4000]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("{}")
        return 0
    path = _edited_path(payload)
    context = format_and_lint(path) if path is not None else ""
    if context:
        print(json.dumps({"additional_context": context}))
    else:
        print("{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
