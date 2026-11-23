"""cdk_append_nonempty_param skips blanks and never prints the value."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent / "deploy" / "cdk-params.sh"


def _run(value: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; ADMIN_LX_PARAM_ARGS=(); '
            'cdk_append_nonempty_param "lxsoftware:SiutindeiBoardMetaVerifyToken" "$2"; '
            'printf "count=%s\\n" "${#ADMIN_LX_PARAM_ARGS[@]}"; '
            'printf "args=%s\\n" "${ADMIN_LX_PARAM_ARGS[*]}"',
            "bash",
            str(_SCRIPT),
            value,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


class CdkAppendNonemptyParamTest(unittest.TestCase):
    def test_empty_and_whitespace_do_not_append(self) -> None:
        for value in ("", "   ", "\t"):
            result = _run(value)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            self.assertIn("count=0", result.stdout)
            self.assertNotIn("SiutindeiBoardMetaVerifyToken", result.stdout)

    def test_nonempty_appends_without_echoing_on_stderr(self) -> None:
        result = _run("verify-token-example")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("count=2", result.stdout)
        self.assertIn(
            "--parameters lxsoftware:SiutindeiBoardMetaVerifyToken=verify-token-example",
            result.stdout,
        )


class CdkResolvePlaceholderTest(unittest.TestCase):
    def test_secret_placeholder_is_prefixed_and_not_printed_on_stderr(self) -> None:
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "params.json"
            path.write_text(
                '{"PublicWebsiteCertificateArn": "<FROM_GITHUB_SECRET: CDK_PARAM_PUBLIC_WEBSITE_CERTIFICATE_ARN>"}',
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["CDK_PARAM_PUBLIC_WEBSITE_CERTIFICATE_ARN"] = "cert-example"
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; cdk_load_param_args "$2"; printf "%s\\n" "${PUBLIC_PARAM_ARGS[@]}"',
                    "bash",
                    str(_SCRIPT),
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn(
            "lxsoftware-public-www:PublicWebsiteCertificateArn=cert-example",
            result.stdout,
        )
