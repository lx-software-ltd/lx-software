#!/usr/bin/env python3
"""Shell-guard decisions and the post-edit path parser."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load("guard_shell", ROOT / ".cursor" / "hooks" / "guard_shell.py")
post_edit = _load("post_edit", ROOT / ".cursor" / "hooks" / "post_edit.py")
rules = _load("validate_agent_rules", ROOT / "scripts" / "validate_agent_rules.py")


class GuardShellTest(unittest.TestCase):
    def assert_denied(self, command: str) -> None:
        permission, message = guard.decide(command)
        self.assertEqual(permission, "deny", message)
        self.assertTrue(message)

    def test_force_push_forms_are_denied(self) -> None:
        self.assert_denied("git push --force")
        self.assert_denied("git push --force-with-lease")
        self.assert_denied("git push -uf origin feature")
        self.assert_denied("git push origin +main")

    def test_push_to_main_is_denied_and_a_branch_push_is_allowed(self) -> None:
        self.assert_denied("git push origin main")
        self.assert_denied("git push origin HEAD:main")
        permission, _message = guard.decide("git push -u origin cursor/agent-harness-c1ab")
        self.assertEqual(permission, "allow")

    def test_rm_rf_outside_the_repo_is_denied(self) -> None:
        self.assert_denied("rm -rf /")
        self.assert_denied("rm -rf /var")
        permission, _message = guard.decide("rm -rf node_modules")
        self.assertEqual(permission, "allow")
        permission, _message = guard.decide("rm -rf /tmp/cursor-scratch")
        self.assertEqual(permission, "allow")

    def test_rm_f_does_not_block_a_later_push(self) -> None:
        permission, _message = guard.decide("rm -f notes.txt && git push -u origin cursor/topic")
        self.assertEqual(permission, "allow")

    def test_live_mutations_are_denied(self) -> None:
        self.assert_denied("npx cdk deploy lxsoftware")
        self.assert_denied("aws s3api delete-object --bucket example --key a")
        self.assert_denied("bash scripts/deploy/deploy-public-website.sh")
        self.assert_denied("python3 scripts/manage-public-api-keys.py create --label demo")
        self.assert_denied("python3 scripts/mint-openrouter-app-keys.py")
        self.assert_denied("python3 scripts/configure-public-analytics.py apply")
        self.assert_denied("python3 scripts/cloudflare/publish-apex-redirect.py apply")
        self.assert_denied("bash scripts/cloudflare/publish-public-media.sh")
        self.assert_denied("aws ses set-active-receipt-rule-set --rule-set-name example")

    def test_mentioning_a_protected_command_is_allowed(self) -> None:
        for command in (
            "cat scripts/deploy/cdk-params.sh",
            "git diff main -- scripts/deploy/deploy-public-website.sh",
            "git add scripts/deploy/deploy-admin-www.sh",
            "shellcheck scripts/deploy/deploy-public-website.sh",
            "python3 -m ruff check scripts/mint-openrouter-app-keys.py",
            "rg -n 'cdk deploy' docs",
            "sed -n 1,20p scripts/cloudflare/publish-public-media.sh",
            "grep -rn 'aws delete-' .cursor/hooks",
            "rg 'git push --force' .cursor/hooks",
            "rg 'git commit --amend' docs",
        ):
            permission, message = guard.decide(command)
            self.assertEqual(permission, "allow", f"{command}: {message}")

    def test_nested_invocations_are_denied(self) -> None:
        self.assert_denied("scripts/deploy/deploy-public-website.sh")
        self.assert_denied("bash -c 'cdk deploy lxsoftware'")
        self.assert_denied("echo $(aws s3api delete-bucket --bucket example)")

    def test_read_only_script_modes_are_allowed(self) -> None:
        for command in (
            "python3 scripts/manage-public-api-keys.py list",
            "python3 scripts/mint-openrouter-app-keys.py --dry-run",
            "python3 scripts/configure-public-analytics.py check",
            "python3 scripts/cloudflare/publish-apex-redirect.py check",
            "npx cdk diff",
        ):
            permission, message = guard.decide(command)
            self.assertEqual(permission, "allow", message)

    def test_amend_asks(self) -> None:
        permission, message = guard.decide("git commit --amend")
        self.assertEqual(permission, "ask")
        self.assertIn("amend", message)

    def test_invalid_json_denies(self) -> None:
        self.assertEqual(guard.decide("git reset --hard")[0], "deny")


class PostEditPathTest(unittest.TestCase):
    def test_after_file_edit_uses_file_path(self) -> None:
        path = post_edit._edited_path({"file_path": "/tmp/example.py"})
        self.assertEqual(path, Path("/tmp/example.py"))

    def test_write_tool_uses_tool_input_path(self) -> None:
        path = post_edit._edited_path({"cwd": "/tmp", "tool_input": {"path": "notes.md"}})
        self.assertEqual(path, Path("/tmp/notes.md"))

    def test_missing_path_is_none(self) -> None:
        self.assertIsNone(post_edit._edited_path({}))


def _unquote_yaml(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        inner = value[1:-1]
        if value[0] == '"':
            return inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner.replace("''", "'")
    return value


def _plain_yaml_values(text: str) -> list[tuple[str, str]]:
    """Key/value pairs from a simple YAML document, without PyYAML.

    An unquoted value that contains ': ' is the scanner error that made
    `.pre-commit-config.yaml` fail `yaml.safe_load`.
    """
    pairs: list[tuple[str, str]] = []
    for line in text.splitlines():
        content = line.split("#", 1)[0].strip()
        if ": " not in content:
            continue
        key, value = content.split(": ", 1)
        if not value.startswith(("'", '"', "|", ">")) and ": " in value:
            raise ValueError(f"unquoted YAML value contains ': ': {content}")
        pairs.append((key.strip(), _unquote_yaml(value)))
    return pairs


class HarnessConfigTest(unittest.TestCase):
    def test_pre_commit_config_parses(self) -> None:
        text = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        entries = [value for key, value in _plain_yaml_values(text) if key == "entry"]
        eslint = [entry for entry in entries if entry.startswith("bash -c ")]
        self.assertEqual(len(eslint), 2)
        self.assertTrue(all('echo "' in entry and ": run npm ci" in entry for entry in eslint))

    def test_unquoted_colon_in_a_yaml_value_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _plain_yaml_values('entry: echo "app: run"')

    def test_linkedin_rule_globs_match_the_spa_files(self) -> None:
        import glob

        text = (ROOT / ".cursor" / "rules" / "linkedin.mdc").read_text(encoding="utf-8")
        globs = text.split("globs:", 1)[1].splitlines()[0].strip().split(",")
        matched: set[str] = set()
        for pattern in globs:
            matched.update(glob.glob(pattern, root_dir=ROOT, recursive=True))
        for expected in (
            "apps/admin_web/src/components/linkedin/LinkedInTab.tsx",
            "apps/admin_web/src/hooks/useLinkedIn.ts",
            "apps/admin_web/src/lib/linkedinModel.ts",
            "backend/lambda/admin/linkedin_draft.py",
        ):
            self.assertIn(expected, matched)


class AgentRulesTest(unittest.TestCase):
    def test_repository_rules_pass(self) -> None:
        self.assertEqual(rules.validate(), [])

    def test_convention_tag_is_accepted_and_unknown_sha_is_not(self) -> None:
        self.assertTrue(rules._why_is_real("convention"))
        self.assertFalse(rules._why_is_real("deadbee is not a commit"))


if __name__ == "__main__":
    unittest.main()
