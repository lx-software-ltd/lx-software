#!/usr/bin/env python3
"""Re-prompt the agent when local harness checks fail at the end of a turn.

Cloud agents do not fire the stop hook. CI runs the shared actions.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKS = (
    ["pre-commit", "run", "validate-agent-rules", "--all-files"],
    ["pre-commit", "run", "check-file-length", "--all-files"],
    ["pre-commit", "run", "check-test-focus", "--all-files"],
    [sys.executable, str(ROOT / "scripts" / "check-contracts.py")],
    ["pre-commit", "run", "check-pii", "--all-files"],
)


def _dirty() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("{}")
        return 0
    if payload.get("status") != "completed" or not _dirty():
        print("{}")
        return 0
    failures: list[str] = []
    missing_pre_commit = False
    for command in CHECKS:
        if missing_pre_commit and command[0] == "pre-commit":
            continue
        try:
            result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
        except FileNotFoundError:
            if command[0] == "pre-commit":
                missing_pre_commit = True
                failures.append(
                    "$ pre-commit run\n"
                    "pre-commit is not on PATH. The harness hooks live in "
                    "lx-software-ltd/actions and run through pre-commit. "
                    "The first run needs network to clone that repository."
                )
            else:
                failures.append(f"$ {' '.join(command)}\n{command[0]} is not on PATH.")
            continue
        if result.returncode != 0:
            output = (result.stdout + "\n" + result.stderr).strip()
            failures.append(f"$ {' '.join(command)}\n{output}")
    if not failures:
        print("{}")
        return 0
    message = "Local harness checks failed. Fix them before finishing:\n\n" + "\n\n".join(failures)
    print(json.dumps({"followup_message": message[:6000]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
