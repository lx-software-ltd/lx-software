#!/usr/bin/env python3
"""Block destructive and production-mutating shell commands before Cursor runs them."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

FORCE_PUSH = re.compile(r"(?:^|\s)(?:--force(?:\s|=|$)|--force-with-lease(?:\s|=|$))")
GIT_PUSH = re.compile(r"\bgit\s+push\b", re.IGNORECASE)
SEGMENT_SPLIT = re.compile(r"\s*(?:&&|\|\||[;|\n])\s*")
SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
GIT_RESET_HARD = re.compile(r"\bgit\s+reset\b[^\n]*--hard\b", re.IGNORECASE)
GIT_DELETE = re.compile(r"\bgit\s+(push\b[^\n]*--delete|branch\s+-D)\b", re.IGNORECASE)
RM_RF = re.compile(r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*[fF]|-[a-zA-Z]*[fF][a-zA-Z]*[rR])\b")
AWS_DELETE_TOKEN = re.compile(r"^(delete|terminate)-[a-z0-9-]+$", re.IGNORECASE)
AMEND = re.compile(r"\bgit\s+commit\b[^\n]*(--amend\b|(^|\s)-[^ \n]*amend)")
API_KEY_VERBS = {"create", "revoke", "set-write"}
SHELLS = {"bash", "sh", "zsh", "dash"}
WRAPPERS = {"sudo", "command", "time", "nice", "nohup", "env"}
PYTHONS = {"python", "python3"}
PROTECTED_REFS = {"main", "refs/heads/main"}


def _segments(command: str) -> list[str]:
    return [part.strip() for part in SEGMENT_SPLIT.split(command) if part.strip()]


def _tokens(segment: str) -> list[str]:
    """Split a segment on whitespace, keeping quoted text as one token."""
    tokens: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for char in segment:
        if quote:
            if char == quote:
                quote = None
            else:
                buf.append(char)
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
            continue
        buf.append(char)
    if buf:
        tokens.append("".join(buf))
    return tokens


def _name(token: str) -> str:
    return Path(token).name


def _command_indexes(tokens: list[str]) -> list[int]:
    """Indexes of tokens that are programs, including a script after an interpreter."""
    indexes: list[int] = []

    def walk(start: int) -> None:
        i = start
        while i < len(tokens) and ENV_ASSIGNMENT.match(tokens[i]):
            i += 1
        if i >= len(tokens):
            return
        indexes.append(i)
        name = _name(tokens[i])
        if name in WRAPPERS or tokens[i] in {".", "source"}:
            j = i + 1
            while j < len(tokens) and (tokens[j].startswith("-") or (name == "env" and "=" in tokens[j])):
                j += 1
            walk(j)
            return
        if name in SHELLS:
            j = i + 1
            while j < len(tokens) and tokens[j].startswith("-"):
                if tokens[j] == "-c":
                    return
                j += 1
            if j < len(tokens):
                indexes.append(j)
            return
        if name in PYTHONS or name.startswith("python3."):
            j = i + 1
            if j < len(tokens) and tokens[j] == "-m":
                return
            while j < len(tokens) and tokens[j].startswith("-"):
                j += 1
            if j < len(tokens) and tokens[j].endswith(".py"):
                indexes.append(j)
            return
        if name == "npx":
            j = i + 1
            while j < len(tokens) and tokens[j].startswith("-"):
                j += 1
            if j < len(tokens):
                indexes.append(j)

    walk(0)
    return indexes


def _runs(tokens: list[str], indexes: list[int], names: set[str]) -> list[int]:
    return [i for i in indexes if _name(tokens[i]) in names or tokens[i] in names]


def _script_indexes(tokens: list[str], indexes: list[int], suffix: str) -> list[int]:
    return [i for i in indexes if tokens[i].endswith(suffix) or _name(tokens[i]) == suffix]


def _is_force_push(segment: str) -> bool:
    """True for --force, --force-with-lease, -f, and +refspec pushes."""
    if not GIT_PUSH.search(segment):
        return False
    if FORCE_PUSH.search(segment):
        return True
    for token in segment.split():
        if token.startswith("--"):
            continue
        if token.startswith("-") and "f" in token[1:]:
            return True
        if token.startswith("+") or ":+" in token:
            return True
    return False


def _push_targets_protected(segment: str) -> bool:
    if not GIT_PUSH.search(segment):
        return False
    for token in segment.split():
        if token.startswith("-"):
            continue
        destination = token.split(":")[-1].lstrip("+")
        bare = token.lstrip("+")
        if destination in PROTECTED_REFS and (bare in PROTECTED_REFS or ":" in token):
            return True
    return False


def _deletes_protected_ref(segment: str) -> bool:
    if not GIT_DELETE.search(segment):
        return False
    return "main" in segment.split()


def _repo_root() -> Path:
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    return here


def _rm_path_blocked(part: str, root: Path) -> bool:
    if part in {".", "./", "*"}:
        return True
    if not part.startswith("/"):
        pieces = [piece for piece in part.removeprefix("./").split("/") if piece not in {"", "."}]
        return (not pieces) or ".." in pieces or "*" in pieces
    if part in {"/tmp", "/var/tmp"} or part.startswith(("/tmp/", "/var/tmp/")):
        return False
    resolved = Path(part).resolve()
    if resolved == root:
        return True
    try:
        resolved.relative_to(root)
    except ValueError:
        return True
    return False


def _rm_blocked(segment: str) -> bool:
    match = RM_RF.search(segment)
    if not match:
        return False
    remainder = segment[match.end() :].strip()
    if not remainder:
        return True
    paths = [part for part in remainder.split() if not part.startswith("-")]
    if not paths:
        return True
    root = _repo_root()
    return any(_rm_path_blocked(part, root) for part in paths)


def _later(tokens: list[str], index: int) -> list[str]:
    return tokens[index + 1 :]


def _live_mutation(tokens: list[str], indexes: list[int]) -> str | None:
    if any("scripts/deploy/" in tokens[i] for i in indexes):
        return "Deploy scripts are blocked. Use the GitHub Actions deploy workflow."
    if _script_indexes(tokens, indexes, "manage-public-api-keys.py") and any(
        token.lower() in API_KEY_VERBS for token in tokens
    ):
        return "Creating, revoking, or changing a public API key is blocked in the agent shell."
    if _script_indexes(tokens, indexes, "mint-openrouter-app-keys.py") and "--dry-run" not in tokens:
        return "Minting OpenRouter keys is blocked. Re-run with --dry-run to preview."
    if _script_indexes(tokens, indexes, "configure-public-analytics.py") and "apply" in tokens:
        return "configure-public-analytics.py apply is blocked. Use check."
    if _script_indexes(tokens, indexes, "publish-apex-redirect.py") and "apply" in tokens:
        return "publish-apex-redirect.py apply is blocked. Use check."
    if _script_indexes(tokens, indexes, "publish-public-media.sh"):
        return "publish-public-media.sh is blocked in the agent shell."
    for index in _runs(tokens, indexes, {"aws"}):
        if "set-active-receipt-rule-set" in _later(tokens, index):
            return "Activating an SES receipt rule set is blocked in the agent shell."
    return None


def _denied(segment: str) -> tuple[str, str] | None:
    tokens = _tokens(segment)
    indexes = _command_indexes(tokens)
    git_running = bool(_runs(tokens, indexes, {"git"}))
    if git_running and _is_force_push(segment):
        return "deny", "Force-push is blocked. Push a normal fast-forward or open a pull request."
    if git_running and _push_targets_protected(segment):
        return "deny", "Pushing to main is blocked. Open a pull request instead."
    if git_running and _deletes_protected_ref(segment):
        return "deny", "Deleting main is blocked."
    if git_running and GIT_RESET_HARD.search(segment):
        return "deny", "git reset --hard is blocked."
    if _runs(tokens, indexes, {"rm"}) and _rm_blocked(segment):
        return "deny", "rm -rf outside the repository or /tmp is blocked."
    for index in _runs(tokens, indexes, {"cdk"}):
        if any(token in {"deploy", "destroy"} for token in _later(tokens, index)):
            return "deny", "cdk deploy and cdk destroy are blocked. Use the deployment workflow."
    for index in _runs(tokens, indexes, {"aws"}):
        if any(AWS_DELETE_TOKEN.match(token) for token in _later(tokens, index)):
            return "deny", "aws delete-* and terminate-* commands are blocked."
    message = _live_mutation(tokens, indexes)
    if message:
        return "deny", message
    return None


def _prompted(segment: str) -> tuple[str, str] | None:
    tokens = _tokens(segment)
    if _runs(tokens, _command_indexes(tokens), {"git"}) and AMEND.search(segment):
        return (
            "ask",
            "git commit --amend rewrites history. Confirm this is the commit you just created and have not pushed.",
        )
    return None


def _nested_commands(segment: str) -> list[str]:
    tokens = _tokens(segment)
    indexes = _command_indexes(tokens)
    nested: list[str] = []
    for index in indexes:
        if _name(tokens[index]) not in SHELLS:
            continue
        for follow in range(index + 1, len(tokens)):
            if tokens[follow] == "-c" and follow + 1 < len(tokens):
                nested.append(tokens[follow + 1])
                break
            if not tokens[follow].startswith("-"):
                break
    for match in SUBSTITUTION.finditer(segment):
        inner = match.group(1) if match.group(1) is not None else match.group(2)
        if inner and inner.strip():
            nested.append(inner)
    return nested


def decide(command: str) -> tuple[str, str]:
    """Return (permission, agent_message). permission is allow, deny, or ask."""
    return _decide(command, 0)


def _decide(command: str, depth: int) -> tuple[str, str]:
    ask: tuple[str, str] | None = None
    for segment in _segments(command):
        denied = _denied(segment)
        if denied is not None:
            return denied
        prompted = _prompted(segment)
        if prompted is not None and ask is None:
            ask = prompted
        if depth < 2:
            for nested in _nested_commands(segment):
                inner = _decide(nested, depth + 1)
                if inner[0] == "deny":
                    return inner
                if inner[0] == "ask" and ask is None:
                    ask = inner
    if ask is not None:
        return ask
    return "allow", ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        print(json.dumps({"permission": "deny", "agent_message": "Shell hook received invalid JSON."}))
        return 0
    command = str(payload.get("command") or "")
    permission, message = decide(command)
    result: dict[str, str] = {"permission": permission}
    if message:
        result["agent_message"] = message
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
