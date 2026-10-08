#!/usr/bin/env python3
"""Ruleset verifier: a disabled main ruleset fails; a real job name passes."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent / "verify_github_rulesets.py"
_SPEC = importlib.util.spec_from_file_location("verify_github_rulesets", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
rulesets = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rulesets)


def _main_ruleset(*, enforcement: str = "active", contexts: list[str] | None = None, reviews: int = 0) -> dict:
    checks = [{"context": context} for context in (contexts if contexts is not None else ["test"])]
    return {
        "name": "main-protection",
        "target": "branch",
        "enforcement": enforcement,
        "conditions": {"ref_name": {"include": ["refs/heads/main"]}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {"required_approving_review_count": reviews},
            },
            {"type": "required_status_checks", "parameters": {"required_status_checks": checks}},
        ],
    }


def _tag_ruleset() -> dict:
    return {
        "name": "release-tags",
        "target": "tag",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["refs/tags/v*"]}},
        "rules": [{"type": "deletion"}],
    }


class RulesetEvaluationTest(unittest.TestCase):
    def test_disabled_main_ruleset_fails(self) -> None:
        errors, warnings = rulesets.evaluate(
            rulesets=[_main_ruleset(enforcement="disabled"), _tag_ruleset()],
            legacy_tags=None,
            job_names={"test", "lint"},
        )
        self.assertEqual(warnings, [])
        self.assertTrue(any("not active" in error for error in errors))

    def test_missing_main_ruleset_fails(self) -> None:
        errors, _warnings = rulesets.evaluate(rulesets=[_tag_ruleset()], legacy_tags=None, job_names={"test"})
        self.assertEqual(errors, ["No active ruleset targets main."])

    def test_active_ruleset_with_matching_job_passes(self) -> None:
        errors, warnings = rulesets.evaluate(
            rulesets=[_main_ruleset(), _tag_ruleset()],
            legacy_tags=None,
            job_names={"test", "lint"},
        )
        self.assertEqual(errors, [])
        self.assertTrue(any("approving review" in warning for warning in warnings))
        self.assertTrue(any("'lint'" in warning for warning in warnings))

    def test_required_review_is_a_warning(self) -> None:
        errors, warnings = rulesets.evaluate(
            rulesets=[_main_ruleset(reviews=1, contexts=["test", "lint"]), _tag_ruleset()],
            legacy_tags=None,
            job_names={"test", "lint"},
        )
        self.assertEqual(errors, [])
        self.assertTrue(any("cannot approve" in warning for warning in warnings))

    def test_unknown_required_context_fails(self) -> None:
        errors, _warnings = rulesets.evaluate(
            rulesets=[_main_ruleset(contexts=["test"]), _tag_ruleset()],
            legacy_tags=None,
            job_names={"lint"},
        )
        self.assertTrue(any("does not match a job name" in error for error in errors))

    def test_missing_force_push_block_fails(self) -> None:
        ruleset = _main_ruleset()
        ruleset["rules"] = [rule for rule in ruleset["rules"] if rule["type"] != "non_fast_forward"]
        errors, _warnings = rulesets.evaluate(
            rulesets=[ruleset, _tag_ruleset()], legacy_tags=None, job_names={"test", "lint"}
        )
        self.assertTrue(any("force pushes" in error for error in errors))

    def test_missing_tag_protection_fails(self) -> None:
        errors, _warnings = rulesets.evaluate(rulesets=[_main_ruleset()], legacy_tags=None, job_names={"test", "lint"})
        self.assertTrue(any("v* tags" in error for error in errors))

    def test_job_names_ignore_step_names(self) -> None:
        text = """
name: Test
on: pull_request
jobs:
  test:
    name: test
    steps:
      - name: Require every test job
        run: echo ok
"""
        self.assertEqual(rulesets.job_names_in_workflow(text), {"test"})

    def test_this_repo_names_the_aggregator_jobs(self) -> None:
        names = rulesets.workflow_job_names()
        self.assertIn("test", names)
        self.assertIn("lint", names)

    def test_legacy_403_is_treated_as_absent(self) -> None:
        self.assertTrue(rulesets.legacy_read_is_absent("gh api failed: HTTP 403"))


if __name__ == "__main__":
    unittest.main()
