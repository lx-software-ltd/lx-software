#!/usr/bin/env python3
"""Fail if contract artifacts are out of date with contracts/*.json."""

from __future__ import annotations

import difflib
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
    ROOT / "backend" / "lambda" / "admin" / "contracts" / "board-staff.json",
    ROOT / "backend" / "lambda" / "admin" / "contracts" / "openrouter-apps.json",
    ROOT / "backend" / "lambda" / "admin" / "contracts" / "aws-billing.json",
    ROOT / "backend" / "lambda" / "admin" / "contracts" / "public-api-scopes.json",
    ROOT / "backend" / "lambda" / "admin" / "contracts" / "wire-format.json",
    ROOT / "backend" / "lambda" / "public_api_authorizer" / "public_api_scopes_generated.py",
]


# Byte-identical with findingalpha. A missing sibling checkout is skipped.
_WIRE_PAIRS = (
    (
        ROOT / "backend" / "lambda" / "admin" / "wire_format.py",
        "backend/lambda/engine/wire_format.py",
    ),
    (
        ROOT / "apps" / "admin_web" / "src" / "lib" / "wireFormat.ts",
        "apps/admin_web/src/lib/wireFormat.ts",
    ),
)


def _findingalpha_root() -> Path | None:
    for candidate in (Path("/agent/repos/findingalpha"), ROOT.parent / "findingalpha"):
        if (candidate / "backend" / "lambda" / "engine" / "wire_format.py").is_file():
            return candidate
    return None


def wire_copy_findings() -> list[str]:
    """One finding per shared codec file that is not byte-identical."""
    sibling = _findingalpha_root()
    if sibling is None:
        print("wire format sibling check skipped: findingalpha checkout not found")
        return []
    findings: list[str] = []
    for local, relative in _WIRE_PAIRS:
        other = sibling / relative
        left = local.read_bytes()
        right = other.read_bytes()
        if left == right:
            continue
        diff = "".join(
            difflib.unified_diff(
                right.decode("utf-8", errors="replace").splitlines(keepends=True),
                left.decode("utf-8", errors="replace").splitlines(keepends=True),
                fromfile=str(other),
                tofile=str(local.relative_to(ROOT)),
            )
        )
        findings.append(f"{local.relative_to(ROOT)} differs from {other}\n{diff}")
    return findings


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
    copies = wire_copy_findings()
    if stale or copies:
        if stale:
            print(
                "Contract artifacts are out of date. Run: python3 scripts/sync-contracts.py",
                file=sys.stderr,
            )
            for path in stale:
                print(f"  - {path}", file=sys.stderr)
        for finding in copies:
            print(finding, file=sys.stderr)
        return 1
    print("Contract artifacts are up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
