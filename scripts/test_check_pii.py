"""Normalization rules for the hashed personal-data check."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent / "check_pii.py"
_SPEC = importlib.util.spec_from_file_location("check_pii", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
check_pii = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_pii)


class CheckPiiTest(unittest.TestCase):
    def test_trailing_period_does_not_stick_to_name_tokens(self) -> None:
        candidates = check_pii._candidates("Hello Sam Rivera.")
        self.assertIn("sam rivera", candidates)
        self.assertIn("rivera", candidates)
        self.assertNotIn("sam rivera.", candidates)
        self.assertNotIn("rivera.", candidates)

    def test_email_trailing_period_is_stripped_from_tokens(self) -> None:
        candidates = check_pii._candidates("Write user@example.com.")
        self.assertIn("user@example.com", candidates)
        self.assertNotIn("user@example.com.", candidates)

    def test_interior_dots_stay_in_tokens(self) -> None:
        candidates = check_pii._candidates("See note.v2 today.")
        self.assertIn("note.v2", candidates)

    def test_handle_strips_at_sign_and_trailing_period(self) -> None:
        candidates = check_pii._candidates("Follow @Mei.C.")
        self.assertIn("mei.c", candidates)
        self.assertNotIn("@mei.c", candidates)
        self.assertNotIn("mei.c.", candidates)

    def test_scan_suffixes_cover_source_docs_and_styles(self) -> None:
        self.assertTrue(
            {
                ".py",
                ".ts",
                ".tsx",
                ".js",
                ".mjs",
                ".dart",
                ".sql",
                ".md",
                ".mdc",
                ".yml",
                ".yaml",
                ".sh",
                ".html",
                ".css",
            }
            <= check_pii.SCAN_SUFFIXES
        )

    def test_phone_digits_are_candidates_without_separators(self) -> None:
        candidates = check_pii._candidates("Call +852 5111 1111.")
        self.assertIn("85251111111", candidates)

    def test_matching_line_reports_the_line_not_the_value(self) -> None:
        denied = {check_pii._digest("sam rivera")}
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
            handle.write("Hello there.\nHello Sam Rivera.\n")
            path = Path(handle.name)
        try:
            # The line before a hit is included because consecutive lines are
            # scanned as one window.
            self.assertEqual(check_pii._matching_lines(path, denied), [1, 2])
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
