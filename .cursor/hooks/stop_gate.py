#!/usr/bin/env python3
"""Re-prompt the agent when local harness checks fail at the end of a turn.

Cloud agents do not fire the stop hook. CI runs the same scripts.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKS = (
    [sys.executable, str(ROOT / "scripts" / "validate_agent_rules.py")],
    [sys.executable, str(ROOT / "scripts" / "check-contracts.py")],
    [sys.executable, str(ROOT / "scripts" / "check_pii.py")],
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
    for command in CHECKS:
        result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
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
