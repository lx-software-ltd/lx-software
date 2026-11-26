"""The findingalpha codec check skips without a local checkout."""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

_PATH = Path(__file__).resolve().parent / "check-contracts.py"
_SPEC = importlib.util.spec_from_file_location("check_contracts", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
check = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = check
_SPEC.loader.exec_module(check)


class CheckContractsWireCopyTest(unittest.TestCase):
    def test_missing_checkout_prints_the_skip_and_passes(self) -> None:
        out = io.StringIO()
        with patch.object(check, "_findingalpha_checkout", return_value=None), redirect_stdout(out):
            findings = check.wire_copy_findings()
        self.assertEqual(findings, [])
        self.assertEqual(out.getvalue().strip(), "check skipped: findingalpha checkout not found")

    def test_a_directory_that_is_not_a_checkout_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "not-a-repo"
            missing.mkdir()
            with patch.dict("os.environ", {"FINDINGALPHA_CHECKOUT": str(missing)}):
                with patch.object(check, "ROOT", root / "lx-software"):
                    self.assertIsNone(check._findingalpha_checkout())

    def test_the_checker_does_not_hardcode_an_agent_path(self) -> None:
        text = _PATH.read_text(encoding="utf-8")
        self.assertNotIn("/agent/repos", text)
        self.assertIn(check._FINDINGALPHA_CODEC, text)

    def test_a_present_checkout_matches_the_pinned_commit(self) -> None:
        if check._findingalpha_checkout() is None:
            return
        self.assertEqual(check.wire_copy_findings(), [])
