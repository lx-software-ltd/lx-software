#!/usr/bin/env python3
"""Routine Dependabot updates open as one batch pull request."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = "b911ce02864881b95506a008a471108db22ce29e"


class DependabotBatchWorkflowTest(unittest.TestCase):
    def test_workflow_opens_one_batch(self) -> None:
        text = (ROOT / ".github" / "workflows" / "dependabot-batch.yml").read_text(encoding="utf-8")
        self.assertIn("name: Dependabot Batch\n", text)
        self.assertIn("workflow_dispatch:\n", text)
        self.assertIn('cron: "15 */2 * * 1-5"', text)
        self.assertIn("permissions:\n  contents: read\n", text)
        self.assertIn("group: dependabot-batch\n", text)
        self.assertIn("cancel-in-progress: false\n", text)
        self.assertIn("runs-on: ubuntu-26.04\n", text)
        self.assertIn("actions: write\n", text)
        self.assertIn("checks: read\n", text)
        self.assertIn("contents: write\n", text)
        self.assertIn("pull-requests: write\n", text)
        self.assertIn(
            f"uses: lx-software-ltd/actions/dependabot-batch@{PIN} # main 2026-11-27\n",
            text,
        )
        self.assertIn("mode: open\n", text)
        self.assertIn("start-gates: dispatch\n", text)
        self.assertNotIn("actions/checkout@", text)
        self.assertNotIn("mode: land", text)


if __name__ == "__main__":
    unittest.main()
