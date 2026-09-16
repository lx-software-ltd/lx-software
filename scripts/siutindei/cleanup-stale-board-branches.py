#!/usr/bin/env python3
"""Delete siutindei ``board/*`` branches that have no open pull request.

The staff tick runs the same sweep (``board_code.sweep_stale_board_branches``)
once the board GitHub token has Contents: write. Use this script when you
want to clean up immediately with a personal ``gh`` login.

    python3 scripts/siutindei/cleanup-stale-board-branches.py
    python3 scripts/siutindei/cleanup-stale-board-branches.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

REPO = "lx-software-ltd/siutindei"
PREFIX = "board/"
PROTECTED = frozenset({"main", "staging", "develop", "master"})


def _gh_json(args: list[str]) -> object:
    raw = subprocess.check_output(["gh", *args], text=True)
    return json.loads(raw) if raw.strip() else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print branches, do not delete")
    parser.add_argument("--repo", default=REPO)
    args = parser.parse_args()
    owner = args.repo.split("/", 1)[0]
    branches = _gh_json(
        ["api", f"repos/{args.repo}/branches?per_page=100", "--jq", "."]
    )
    if not isinstance(branches, list):
        print("failed to list branches", file=sys.stderr)
        return 1
    deleted = []
    kept = []
    for row in branches:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        if not name.startswith(PREFIX) or name in PROTECTED:
            continue
        pulls = _gh_json(
            [
                "api",
                f"repos/{args.repo}/pulls?head={owner}:{name}&state=open&per_page=5",
                "--jq",
                ".",
            ]
        )
        if isinstance(pulls, list) and any(isinstance(pr, dict) for pr in pulls):
            kept.append(name)
            continue
        if args.dry_run:
            print(f"would delete {name}")
            deleted.append(name)
            continue
        try:
            subprocess.check_call(
                ["gh", "api", "-X", "DELETE", f"repos/{args.repo}/git/refs/heads/{name}"]
            )
        except subprocess.CalledProcessError:
            print(
                f"failed to delete {name} (need Contents: write on {args.repo})",
                file=sys.stderr,
            )
            return 1
        print(f"deleted {name}")
        deleted.append(name)
    print(f"kept {len(kept)} open, deleted {len(deleted)} stale")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
