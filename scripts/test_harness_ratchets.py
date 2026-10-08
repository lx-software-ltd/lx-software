#!/usr/bin/env python3
"""File-length and test-focus ratchets."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


def _load(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


length = _load("check_file_length")
focus = _load("check_test_focus")


class FileLengthTest(unittest.TestCase):
    def test_over_ceiling_without_an_entry_fails(self) -> None:
        errors = length.problems({"backend/lambda/admin/board_code.py": 501}, {})
        self.assertEqual(len(errors), 1)
        self.assertIn("allowlist 501", errors[0])

    def test_growth_and_shrink_are_both_reported(self) -> None:
        counts = {"backend/lambda/admin/board_code.py": 600}
        self.assertTrue(
            any("grew" in error for error in length.problems(counts, {"backend/lambda/admin/board_code.py": 550}))
        )
        self.assertTrue(
            any("shrank" in error for error in length.problems(counts, {"backend/lambda/admin/board_code.py": 700}))
        )

    def test_file_under_the_ceiling_must_leave_the_allowlist(self) -> None:
        errors = length.problems(
            {"apps/admin_web/src/lib/board/types.ts": 100},
            {"apps/admin_web/src/lib/board/types.ts": 900},
        )
        self.assertTrue(any("remove it" in error for error in errors))

    def test_tests_and_generated_contracts_are_not_scanned(self) -> None:
        self.assertIsNone(length.limit_for("backend/lambda/admin/test_board.py"))
        self.assertIsNone(length.limit_for("apps/admin_web/src/lib/contracts/generated.ts"))
        self.assertEqual(length.limit_for("apps/admin_web/src/lib/board/types.ts"), 800)

    def test_repository_matches_the_allowlist(self) -> None:
        self.assertEqual(length.main(), 0)


class TestFocusTest(unittest.TestCase):
    def test_focused_and_unconditional_skips_fail(self) -> None:
        # The snippets are assembled so this file does not itself match the scanner.
        focused = "it" + ".on" + "ly('x', () => {})"
        empty = "test" + ".sk" + "ip()"
        string_only = "test" + ".sk" + "ip(" + '"later")'
        bare = "@unittest" + ".sk" + "ip"
        self.assertIsNotNone(focus.line_problem(focused, python=False))
        self.assertIsNotNone(focus.line_problem(empty, python=False))
        self.assertIsNotNone(focus.line_problem(string_only, python=False))
        self.assertIsNotNone(focus.line_problem(bare, python=True))

    def test_conditional_skip_and_reasoned_unittest_skip_pass(self) -> None:
        line = 'test.skip(testInfo.project.name !== "phone", "the burger bar is phone-only");'
        self.assertIsNone(focus.line_problem(line, python=False))
        self.assertIsNone(focus.line_problem('@unittest.skip("needs a fixture")', python=True))
        self.assertIsNone(focus.line_problem('@unittest.skipIf(True, "off")', python=True))

    def test_repository_has_no_focused_tests(self) -> None:
        self.assertEqual(focus.main(), 0)


if __name__ == "__main__":
    unittest.main()
