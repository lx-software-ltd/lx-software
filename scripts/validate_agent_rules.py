#!/usr/bin/env python3
"""Check that agent rules stay short, scoped, and traceable."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = ROOT / ".cursor" / "rules"
SKILLS_DIR = ROOT / ".cursor" / "skills"
AGENTS_LIMIT = 60
RULE_LIMIT = 80
SKILL_LIMIT = 160
POINTER_LIMIT = 8
CORE_RULE = "00-repository-core.mdc"

REQUIRED_RULES = {
    CORE_RULE: True,
    "admin-web.mdc": False,
    "public-www.mdc": False,
    "infrastructure-cdk.mdc": False,
    "backend-admin.mdc": False,
    "board.mdc": False,
    "linkedin.mdc": False,
    "public-api.mdc": False,
    "scripts.mdc": False,
}
REQUIRED_SKILLS = (
    "verify-change",
    "add-board-tool",
    "add-admin-route",
    "admin-record-table",
    "edit-contracts",
    "cdk-parameter",
    "public-www-page",
    "cursor-cloud",
)
FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
WHY_SHA = re.compile(r"\b([0-9a-f]{7,40})\b")


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _front_matter(text: str) -> dict[str, str]:
    match = FRONT_MATTER.match(text)
    if not match:
        raise ValueError("missing front matter")
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.startswith(" "):
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def _body(text: str) -> str:
    match = FRONT_MATTER.match(text)
    if not match:
        return text
    return text[match.end() :]


def _repo_is_shallow() -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "true"


def _why_is_real(tag: str) -> bool:
    shas = WHY_SHA.findall(tag)
    if not shas:
        return "convention" in tag
    for sha in shas:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            return False
    return True


def _check_rule(name: str, path: Path, *, always: bool) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    count = len(_lines(path))
    if count > RULE_LIMIT:
        errors.append(f"{name} is {count} lines; limit is {RULE_LIMIT}")
    try:
        fields = _front_matter(text)
    except ValueError as exc:
        return [*errors, f"{name}: {exc}"]
    expected = "true" if always else "false"
    if fields.get("alwaysApply") != expected:
        errors.append(f"{name} alwaysApply must be {expected}")
    if not always and not fields.get("globs"):
        errors.append(f"{name} must set globs")
    if always and fields.get("globs"):
        errors.append(f"{name} is always applied and must not set globs")
    body = _body(text)
    match = FRONT_MATTER.match(text)
    start = text[: match.end()].count("\n") + 1 if match else 1
    shallow = _repo_is_shallow()
    for offset, line in enumerate(body.splitlines()):
        if not line.startswith("- "):
            continue
        line_number = start + offset
        if "[why:" not in line:
            errors.append(f"{name}:{line_number} rule bullet is missing [why:]")
            continue
        tag = line.split("[why:", 1)[1]
        if _why_is_real(tag):
            continue
        if shallow and WHY_SHA.findall(tag):
            errors.append(
                f"{name}:{line_number} [why:] commit is not in this shallow clone; fetch full history (fetch-depth: 0)"
            )
            continue
        errors.append(f"{name}:{line_number} [why:] is not a known commit or convention")
    return errors


def validate() -> list[str]:
    errors: list[str] = []
    agents = ROOT / "AGENTS.md"
    pointer = ROOT / ".cursorrules"
    if not agents.exists():
        errors.append("Missing AGENTS.md")
    else:
        count = len(_lines(agents))
        if count > AGENTS_LIMIT:
            errors.append(f"AGENTS.md is {count} lines; limit is {AGENTS_LIMIT}")
        text = agents.read_text(encoding="utf-8")
        for required in ("## Zones", "docs/architecture/zones.md", "## Cursor Cloud"):
            if required not in text:
                errors.append(f"AGENTS.md is missing {required}")
    if not pointer.exists():
        errors.append("Missing .cursorrules pointer")
    else:
        count = len(_lines(pointer))
        text = pointer.read_text(encoding="utf-8")
        if count > POINTER_LIMIT:
            errors.append(f".cursorrules is {count} lines; keep it a pointer of at most {POINTER_LIMIT}")
        if "AGENTS.md" not in text or ".cursor/rules/" not in text:
            errors.append(".cursorrules must point at AGENTS.md and .cursor/rules/")
    for relative in (
        "docs/architecture/zones.md",
        "docs/plans/_template.md",
        "docs/research/_template.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".cursor/hooks.json",
        "BUGBOT.md",
    ):
        if not (ROOT / relative).exists():
            errors.append(f"Missing {relative}")

    found_rules = {path.name: path for path in RULES_DIR.glob("*.mdc")} if RULES_DIR.exists() else {}
    for name in REQUIRED_RULES:
        if name not in found_rules:
            errors.append(f"Missing rule {name}")
    for name, path in sorted(found_rules.items()):
        errors.extend(_check_rule(name, path, always=name == CORE_RULE))

    found_skills = {path.parent.name for path in SKILLS_DIR.glob("*/SKILL.md")} if SKILLS_DIR.exists() else set()
    for skill in sorted(set(REQUIRED_SKILLS) - found_skills):
        errors.append(f"Missing skill {skill}")
    for skill in sorted(found_skills):
        path = SKILLS_DIR / skill / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        count = len(_lines(path))
        if count > SKILL_LIMIT:
            errors.append(f"{skill}/SKILL.md is {count} lines; limit is {SKILL_LIMIT}")
        try:
            fields = _front_matter(text)
        except ValueError as exc:
            errors.append(f"{skill}: {exc}")
            continue
        if fields.get("name") != skill:
            errors.append(f"{skill} front matter name must be {skill}")
        if not fields.get("description"):
            errors.append(f"{skill} is missing a description")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("Agent rules check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Agent rules check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
