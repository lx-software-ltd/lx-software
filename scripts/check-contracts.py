#!/usr/bin/env python3
"""Fail if contract artifacts are out of date with contracts/*.json."""

from __future__ import annotations

import difflib
import os
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


# Codec bytes compared with `git show` of this findingalpha commit.
# A missing local checkout skips. No absolute checkout path is hardcoded.
_FINDINGALPHA_CODEC = "d61ab99df00e99df1b649f36a08fab6b9e48ad4d"
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


def _findingalpha_checkout() -> Path | None:
    """A local findingalpha git checkout, or None."""
    raw = os.environ.get("FINDINGALPHA_CHECKOUT", "").strip()
    candidates = [Path(raw)] if raw else []
    candidates.append(ROOT.parent / "findingalpha")
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        probe = subprocess.run(
            ["git", "-C", str(resolved), "rev-parse", "--is-inside-work-tree"],
            check=False,
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0 and probe.stdout.strip() == "true":
            return resolved
    return None


def _git_show(repo: Path, relative: str) -> bytes:
    spec = f"{_FINDINGALPHA_CODEC}:{relative}"
    result = subprocess.run(
        ["git", "-C", str(repo), "show", spec],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"git show {spec} failed")
    return result.stdout


def wire_copy_findings() -> list[str]:
    """One finding per shared codec file that is not byte-identical."""
    sibling = _findingalpha_checkout()
    if sibling is None:
        print("check skipped: findingalpha checkout not found")
        return []
    findings: list[str] = []
    for local, relative in _WIRE_PAIRS:
        try:
            right = _git_show(sibling, relative)
        except RuntimeError as exc:
            findings.append(f"{local.relative_to(ROOT)}: {exc}")
            continue
        left = local.read_bytes()
        if left == right:
            continue
        diff = "".join(
            difflib.unified_diff(
                right.decode("utf-8", errors="replace").splitlines(keepends=True),
                left.decode("utf-8", errors="replace").splitlines(keepends=True),
                fromfile=f"findingalpha@{_FINDINGALPHA_CODEC}:{relative}",
                tofile=str(local.relative_to(ROOT)),
            )
        )
        findings.append(f"{local.relative_to(ROOT)} differs from findingalpha {_FINDINGALPHA_CODEC}\n{diff}")
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
