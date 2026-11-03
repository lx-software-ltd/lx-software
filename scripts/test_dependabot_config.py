#!/usr/bin/env python3
"""Dependabot ignores must cover packages with no compatible security bump."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".github" / "dependabot.yml"


def _directory_block(text: str, directory: str) -> str:
    marker = f'directory: "{directory}"'
    start = text.find(marker)
    if start < 0:
        raise AssertionError(f"missing Dependabot ecosystem for {directory}")
    next_eco = text.find("package-ecosystem:", start + len(marker))
    return text[start:] if next_eco < 0 else text[start:next_eco]


def _ignored_names(block: str) -> set[str]:
    names: set[str] = set()
    prefix = 'dependency-name: "'
    for line in block.splitlines():
        stripped = line.strip().removeprefix("- ").strip()
        if stripped.startswith(prefix) and stripped.endswith('"'):
            names.add(stripped[len(prefix) : -1])
    return names


class DependabotConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = CONFIG.read_text(encoding="utf-8")

    def test_infrastructure_ignores_unpatched_security_updates(self) -> None:
        names = _ignored_names(_directory_block(self.text, "/backend/infrastructure"))
        self.assertIn("deepmerge", names)
        self.assertIn("minimatch", names)
        self.assertIn("fast-uri", names)

    def test_spa_ecosystems_do_not_ignore_minimatch(self) -> None:
        # A name-only ignore makes security jobs fail with all_versions_ignored.
        # The SPAs pin GHSA-g3hv-75wg-m249 via package.json overrides instead.
        for directory in ("/apps/public_www", "/apps/admin_web"):
            names = _ignored_names(_directory_block(self.text, directory))
            self.assertNotIn("minimatch", names, directory)

    def test_spas_override_minimatch_to_the_patched_line(self) -> None:
        for relative in ("apps/public_www/package.json", "apps/admin_web/package.json"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn('"minimatch": "^11.0.1"', text, relative)


if __name__ == "__main__":
    unittest.main()
