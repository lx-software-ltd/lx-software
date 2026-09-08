#!/usr/bin/env python3
"""Fail if contract artifacts are out of date with contracts/*.json."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYNC = ROOT / "scripts" / "sync-contracts.py"

ARTIFACTS = [
    ROOT / "backend" / "lambda" / "admin" / "contract_constants.py",
    ROOT / "apps" / "admin_web" / "src" / "lib" / "contracts" / "generated.ts",
    ROOT / "backend" / "infrastructure" / "lib" / "shared-contracts.ts",
    ROOT / "backend" / "lambda" / "admin" / "contracts" / "finance.json",
    ROOT / "backend" / "lambda" / "admin" / "contracts" / "executive-board.json",
    ROOT / "backend" / "lambda" / "admin" / "contracts" / "board-timeouts.json",
    ROOT / "backend" / "lambda" / "admin" / "contracts" / "board-tools.json",
    ROOT / "backend" / "lambda" / "admin" / "contracts" / "openrouter-apps.json",
    ROOT / "backend" / "lambda" / "admin" / "contracts" / "aws-billing.json",
]


def main() -> int:
    before = {p: p.read_bytes() if p.exists() else None for p in ARTIFACTS}
    subprocess.run([sys.executable, str(SYNC)], check=True, cwd=ROOT)
    stale: list[str] = []
    for p in ARTIFACTS:
        if not p.exists():
            stale.append(str(p.relative_to(ROOT)))
            continue
        if before.get(p) != p.read_bytes():
            stale.append(str(p.relative_to(ROOT)))
    if stale:
        print(
            "Contract artifacts are out of date. Run: python3 scripts/sync-contracts.py",
            file=sys.stderr,
        )
        for path in stale:
            print(f"  - {path}", file=sys.stderr)
        return 1
    print("Contract artifacts are up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
