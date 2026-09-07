#!/usr/bin/env python3
"""Unit tests for verify-board-secrets.py (no live AWS)."""

from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent / "verify-board-secrets.py"
_SPEC = importlib.util.spec_from_file_location("verify_board_secrets", _SCRIPT)
assert _SPEC and _SPEC.loader
v = importlib.util.module_from_spec(_SPEC)
sys.modules["verify_board_secrets"] = v
_SPEC.loader.exec_module(v)


ASC_OK = json.dumps(
    {
        "keyId": "ABC123",
        "issuerId": "00000000-0000-0000-0000-000000000000",
        "privateKey": "-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----",
    }
)
SA_OK = json.dumps(
    {
        "client_email": "sa@x.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----",
    }
)


class ValidateTests(unittest.TestCase):
    def test_openrouter_plain_and_json(self) -> None:
        self.assertEqual(v.validate_openrouter("sk-or-v1-abcdef12"), [])
        self.assertEqual(v.validate_openrouter('{"openrouter_api_key":"sk-or-v1-abcdef12"}'), [])
        self.assertTrue(v.validate_openrouter(""))
        self.assertTrue(v.validate_openrouter('{"nope":1}'))

    def test_github_prefix_is_hint_not_block(self) -> None:
        errs = v.validate_github("not-a-github-token-value")
        self.assertTrue(any("does not start with" in e for e in errs))
        self.assertFalse(v.failed([{"status": "ok", "required": False}]))

    def test_github_ok(self) -> None:
        self.assertEqual([e for e in v.validate_github("github_pat_abc12345") if "does not start" not in e], [])

    def test_asc(self) -> None:
        self.assertEqual(v.validate_asc(ASC_OK), [])
        self.assertIn("must be JSON", v.validate_asc("not-json")[0])
        self.assertTrue(any("keyId" in e for e in v.validate_asc('{"issuerId":"x","privateKey":"-----BEGIN PRIVATE KEY-----"}')))

    def test_play_sa(self) -> None:
        self.assertEqual(v.validate_google_sa(SA_OK), [])
        self.assertTrue(v.validate_google_sa('{"client_email":"no-at"}'))

    def test_db(self) -> None:
        self.assertEqual(v.validate_db('{"username":"board_api","password":"p"}'), [])
        self.assertTrue(any("username" in e for e in v.validate_db("{}")))


class RenderTests(unittest.TestCase):
    def test_failed_required_missing(self) -> None:
        rows = [{"status": "missing", "required": True}]
        self.assertTrue(v.failed(rows))
        self.assertFalse(v.failed([{"status": "missing", "required": False}]))
        self.assertTrue(v.failed([{"status": "bad-format", "required": False}]))

    def test_render_hides_values(self) -> None:
        text = v.render(
            [
                {
                    "label": "GitHub PAT",
                    "param": "GitHubReadTokenSecretArn",
                    "required": False,
                    "tools": "writes",
                    "status": "ok",
                    "detail": "wired to the stack",
                }
            ],
            [("MetaPageId", "Page", "set")],
        )
        self.assertIn("OK", text)
        self.assertIn("GitHub PAT", text)
        self.assertNotIn("github_pat_", text)


class CliFakeAwsTests(unittest.TestCase):
    def test_verify_reports_wired_openrouter_and_missing_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "aws"
            secrets = {
                "arn:aws:secretsmanager:ap-southeast-1:1:secret:or": {
                    "Name": "lxsoftware-admin-openrouter-api-secret-Hzerh6",
                    "ARN": "arn:aws:secretsmanager:ap-southeast-1:1:secret:or",
                    "SecretString": "sk-or-v1-livekeyvalue",
                }
            }
            fake.write_text(
                "#!/usr/bin/env python3\n"
                + _FAKE_AWS_PY.format(secrets=json.dumps(secrets)),
                encoding="utf-8",
            )
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            proc = subprocess.run(
                [
                    "python3",
                    str(Path(__file__).resolve().parent / "verify-board-secrets.py"),
                    "--aws",
                    str(fake),
                    "--region",
                    "ap-southeast-1",
                    "--stack",
                    "lxsoftware",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("OK", proc.stdout)
        self.assertIn("OpenRouter", proc.stdout)
        self.assertIn("MISS", proc.stdout)
        self.assertNotIn("sk-or-v1-livekeyvalue", proc.stdout)


_FAKE_AWS_PY = r'''
import json, sys
args = sys.argv[1:]
if args and args[0] == "--region":
    args = args[2:]
# drop --output json
args = [a for a in args if a != "--output" and a != "json"]
SECRETS = json.loads("""{secrets}""")
if args[:2] == ["cloudformation", "describe-stacks"]:
    print(json.dumps({{
        "Stacks": [{{
            "Parameters": [
                {{"ParameterKey": "OpenRouterApiKeySecretArn", "ParameterValue": "arn:aws:secretsmanager:ap-southeast-1:1:secret:or"}},
                {{"ParameterKey": "MetaPageId", "ParameterValue": ""}},
            ]
        }}]
    }}))
    raise SystemExit(0)
if args[:2] == ["secretsmanager", "get-secret-value"]:
    sid = args[args.index("--secret-id") + 1]
    row = SECRETS.get(sid)
    if not row:
        raise SystemExit(1)
    print(json.dumps(row))
    raise SystemExit(0)
if args[:2] == ["secretsmanager", "describe-secret"]:
    sid = args[args.index("--secret-id") + 1]
    row = SECRETS.get(sid)
    if not row:
        raise SystemExit(1)
    print(json.dumps(row))
    raise SystemExit(0)
if args[:2] == ["secretsmanager", "list-secrets"]:
    print(json.dumps({{"SecretList": []}}))
    raise SystemExit(0)
raise SystemExit(1)
'''


if __name__ == "__main__":
    unittest.main()
