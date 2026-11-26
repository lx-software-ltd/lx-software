"""The deploy settings script rejects an execute-api admin API URL."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent / "deploy" / "check-admin-spa-settings.sh"


def _run(api_url: str) -> tuple[subprocess.CompletedProcess[str], str]:
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "github-output"
        env = os.environ.copy()
        env["JSON"] = json.dumps(
            {
                "CognitoDomain": "https://auth.example.com",
                "AdminApiBaseUrl": api_url,
                "UserPoolClientId": "client-1",
            }
        )
        env["STACK_NAME"] = "lxsoftware"
        env["GITHUB_OUTPUT"] = str(output)
        result = subprocess.run(
            ["bash", str(_SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        written = output.read_text(encoding="utf-8") if output.is_file() else ""
        return result, written


class CheckAdminSpaSettingsTest(unittest.TestCase):
    def test_the_script_does_not_fetch_a_config(self) -> None:
        text = _SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("check_admin_spa_config.py", text)
        self.assertNotIn("ADMIN_SPA_CONFIG_URL", text)

    def test_custom_domain_passes(self) -> None:
        result, written = _run("https://api.lx-software.com")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("api_url=https://api.lx-software.com", written)

    def test_execute_api_url_fails(self) -> None:
        result, written = _run("https://abc123.execute-api.ap-southeast-1.amazonaws.com")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("execute-api", result.stderr)
        self.assertNotIn("api_url=", written)
