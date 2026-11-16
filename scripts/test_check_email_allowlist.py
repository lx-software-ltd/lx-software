"""The deploy allow-list check rejects a bad entry and does not print it."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent / "check_email_allowlist.sh"


def _run(value: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; check_email_allowlist "$2"',
            "bash",
            str(_SCRIPT),
            value,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


class CheckEmailAllowlistTest(unittest.TestCase):
    def test_one_address_and_a_spaced_list_pass(self) -> None:
        for value in ("admin@example.com", " Admin@Example.com , other@example.com "):
            result = _run(value)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "")

    def test_empty_and_whitespace_fail_without_echoing_the_value(self) -> None:
        for value in ("", "   ", "\t"):
            result = _run(value)
            self.assertEqual(result.returncode, 1)
            self.assertIn("is empty", result.stderr)
            self.assertEqual(result.stdout, "")
            if value:
                self.assertNotIn(value, result.stderr)

    def test_a_non_email_entry_fails_by_position(self) -> None:
        result = _run("admin@example.com,typo")
        self.assertEqual(result.returncode, 1)
        self.assertIn("entry 2", result.stderr)
        self.assertNotIn("typo", result.stderr)
        self.assertNotIn("admin@example.com", result.stderr)

    def test_blank_and_undotted_entries_fail(self) -> None:
        for value, position in (
            ("admin@example.com,", "2"),
            ("admin@example.com, ", "2"),
            (",admin@example.com", "1"),
            ("admin@localhost", "1"),
            ("a@@example.com", "1"),
            ("admin@example.com other@example.com", "1"),
        ):
            result = _run(value)
            self.assertEqual(result.returncode, 1, value)
            self.assertIn(f"entry {position}", result.stderr)
            self.assertNotIn("example.com", result.stderr)
            self.assertNotIn("localhost", result.stderr)
