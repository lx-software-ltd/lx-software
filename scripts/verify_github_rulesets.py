#!/usr/bin/env python3
"""Fail when main or release-tag protection is missing or weaker than docs.

Approving-review count is reported and does not fail the check. Pull
requests in this repository are opened by the maintainer, who cannot
approve their own pull request, so the merge gate is the required status
checks. A required context must exactly match a job ``name`` in
``.github/workflows``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAIN_INCLUDES = {"refs/heads/main", "main", "~DEFAULT_BRANCH", "~ALL"}
JOB_KEY = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
JOB_NAME = re.compile(r"^    name:\s*(.+?)\s*$")


def _includes(ruleset: dict[str, Any]) -> list[str]:
    conditions = ruleset.get("conditions") or {}
    ref_name = conditions.get("ref_name") or {}
    include = ref_name.get("include") or []
    return [str(item) for item in include]


def _targets_main_ref(ruleset: dict[str, Any]) -> bool:
    if ruleset.get("target") != "branch":
        return False
    return any(item in MAIN_INCLUDES for item in _includes(ruleset))


def targets_main(ruleset: dict[str, Any]) -> bool:
    return _targets_main_ref(ruleset) and ruleset.get("enforcement") == "active"


def targets_release_tags(ruleset: dict[str, Any]) -> bool:
    if ruleset.get("target") != "tag" or ruleset.get("enforcement") != "active":
        return False
    return any(
        item in {"refs/tags/v*", "refs/tags/v", "~ALL"} or item.startswith("refs/tags/v") for item in _includes(ruleset)
    )


def _rules(rulesets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for ruleset in rulesets:
        collected.extend(rule for rule in (ruleset.get("rules") or []) if isinstance(rule, dict))
    return collected


def _status_contexts(rules: list[dict[str, Any]]) -> list[str]:
    contexts: list[str] = []
    for rule in rules:
        if rule.get("type") != "required_status_checks":
            continue
        parameters = rule.get("parameters") or {}
        for check in parameters.get("required_status_checks") or []:
            context = str(check.get("context") or "") if isinstance(check, dict) else str(check)
            if context:
                contexts.append(context)
    return contexts


def job_names_in_workflow(text: str) -> set[str]:
    """Return job ids and job-level ``name`` values from one workflow file."""
    names: set[str] = set()
    in_jobs = False
    for line in text.splitlines():
        if line.startswith("jobs:"):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if line and not line.startswith(" ") and not line.startswith("#"):
            in_jobs = False
            continue
        key = JOB_KEY.match(line)
        if key:
            names.add(key.group(1))
            continue
        named = JOB_NAME.match(line)
        if named:
            names.add(named.group(1).strip().strip("'\""))
    return names


def workflow_job_names(root: Path | None = None) -> set[str]:
    base = root or ROOT
    names: set[str] = set()
    workflow_dir = base / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return names
    for path in sorted(workflow_dir.glob("*.yml")):
        names.update(job_names_in_workflow(path.read_text(encoding="utf-8")))
    return names


def evaluate_branch_rulesets(rulesets: list[dict[str, Any]], job_names: set[str]) -> tuple[list[str], list[str]]:
    active = [ruleset for ruleset in rulesets if targets_main(ruleset)]
    if not active:
        inactive = [
            ruleset for ruleset in rulesets if _targets_main_ref(ruleset) and ruleset.get("enforcement") != "active"
        ]
        if inactive:
            described = ", ".join(
                f"{ruleset.get('name') or 'unnamed'} ({ruleset.get('enforcement') or 'unset'})" for ruleset in inactive
            )
            return [f"Ruleset targets main but enforcement is not active: {described}."], []
        return ["No active ruleset targets main."], []

    errors: list[str] = []
    warnings: list[str] = []
    rules = _rules(active)
    review_counts = [
        int((rule.get("parameters") or {}).get("required_approving_review_count") or 0)
        for rule in rules
        if rule.get("type") == "pull_request"
    ]
    if not review_counts or max(review_counts) < 1:
        warnings.append("main ruleset does not require an approving review. Status checks are the merge gate.")
    else:
        warnings.append(
            "main ruleset requires an approving review. The pull request author "
            "cannot approve their own pull request, so this blocks every merge "
            "from the maintainer account until another reviewer exists."
        )
    contexts = _status_contexts(rules)
    if "lint" not in contexts:
        warnings.append("main ruleset does not require the 'lint' status check.")
    for context in contexts:
        if context not in job_names:
            errors.append(f"required status check {context!r} does not match a job name in .github/workflows")
    rule_types = {str(rule.get("type")) for rule in rules}
    if "deletion" not in rule_types:
        errors.append("main ruleset does not block deletions.")
    if "non_fast_forward" not in rule_types:
        errors.append("main ruleset does not block force pushes.")
    return errors, warnings


def evaluate_tag_protection(rulesets: list[dict[str, Any]], legacy_tags: list[Any] | None) -> list[str]:
    if any(targets_release_tags(ruleset) for ruleset in rulesets):
        return []
    if legacy_tags:
        return []
    return ["No active ruleset protects v* tags."]


def evaluate(
    *,
    rulesets: list[dict[str, Any]],
    legacy_tags: list[Any] | None,
    job_names: set[str],
) -> tuple[list[str], list[str]]:
    errors, warnings = evaluate_branch_rulesets(rulesets, job_names)
    return errors + evaluate_tag_protection(rulesets, legacy_tags), warnings


def legacy_read_is_absent(detail: str) -> bool:
    """Classic protection endpoints 404 when unset and 403 without admin rights."""
    text = detail.lower()
    return "404" in text or "not found" in text or "403" in text or "resource not accessible" in text


def _gh_json(path: str) -> Any:
    result = subprocess.run(
        ["gh", "api", path],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"gh api {path} failed: {detail}")
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)


def load_live(repo: str) -> tuple[list[dict[str, Any]], list[Any] | None]:
    summaries = _gh_json(f"repos/{repo}/rulesets") or []
    rulesets: list[dict[str, Any]] = []
    for summary in summaries:
        ruleset_id = summary.get("id")
        if ruleset_id is None:
            continue
        detail = _gh_json(f"repos/{repo}/rulesets/{ruleset_id}")
        if isinstance(detail, dict):
            rulesets.append(detail)
    legacy_tags: list[Any] | None
    try:
        tags = _gh_json(f"repos/{repo}/tags/protection")
        legacy_tags = tags if isinstance(tags, list) and tags else None
    except RuntimeError as exc:
        if legacy_read_is_absent(str(exc)):
            legacy_tags = None
        else:
            raise
    return rulesets, legacy_tags


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo:
        print("GITHUB_REPOSITORY is required.", file=sys.stderr)
        return 1
    try:
        rulesets, legacy_tags = load_live(repo)
    except RuntimeError as exc:
        print(f"Ruleset verification could not read GitHub protection: {exc}", file=sys.stderr)
        return 1
    errors, warnings = evaluate(rulesets=rulesets, legacy_tags=legacy_tags, job_names=workflow_job_names())
    for warning in warnings:
        print(f"warning: {warning}")
    if errors:
        print("GitHub ruleset verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("GitHub ruleset verification passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
