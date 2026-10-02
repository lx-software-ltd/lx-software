"""Tool operations for the github family."""

from __future__ import annotations

from typing import Any

import board_github
from board_tools_core import (
    REASON_PARAM,
    ToolContext,
    ToolOp,
    _gh,
    _int_param,
    _obj,
    _short,
    _str_param,
    _summ,
)
from contract_constants import (
    BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
)


def _summ_search(args: dict[str, Any]) -> str:
    q = _short(args.get("query") or "")
    return f"Searched GitHub {args.get('type') or 'issue'}s" + (f" for '{q}'" if q else "") + f" ({args.get('state') or 'open'})"

def _summ_labels(args: dict[str, Any]) -> str:
    labels = args.get("labels") if isinstance(args.get("labels"), list) else []
    return f"Set labels on #{args.get('number')}: {', '.join(str(x) for x in labels) or '(none)'}"

def _validate_github_create_issue(_ctx: ToolContext, args: dict[str, Any]) -> str | None:
    return board_github.validate_create_issue(args)

def ops() -> list[ToolOp]:
    return [
        ToolOp(
            name="github_search_issues",
            tool_id="github",
            kind="read",
            description="Search issues or pull requests in the siutindei repository by keywords. Use before proposing new work to avoid duplicates.",
            parameters=_obj(
                {
                    "query": _str_param("Keywords (GitHub search syntax allowed, e.g. 'label:bug booking').", max_len=200),
                    "state": _str_param("Filter by state.", enum=["open", "closed", "all"]),
                    "type": _str_param("issue, pr or any.", enum=["issue", "pr", "any"]),
                    "limit": _int_param("Max results (1-20).", maximum=20),
                }
            ),
            run=_gh(board_github.op_search_issues),
            summarize=_summ_search,
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
        ToolOp(
            name="github_get_issue",
            tool_id="github",
            kind="read",
            description="Read one issue or pull request in full, including its most recent comments.",
            parameters=_obj({"number": _int_param("Issue or PR number.", maximum=100000)}, ["number"]),
            run=_gh(board_github.op_get_issue),
            summarize=_summ("Read issue #{number}"),
        ),
        ToolOp(
            name="github_list_pull_requests",
            tool_id="github",
            kind="read",
            description="List pull requests (newest updated first).",
            parameters=_obj(
                {
                    "state": _str_param("open, closed or all.", enum=["open", "closed", "all"]),
                    "limit": _int_param("Max results (1-20).", maximum=20),
                }
            ),
            run=_gh(board_github.op_list_pull_requests),
            summarize=_summ("Listed {state} pull requests"),
        ),
        ToolOp(
            name="github_list_releases",
            tool_id="github",
            kind="read",
            description="List recent GitHub releases (tag, draft/prerelease, notes). Discussions are not available (GraphQL only).",
            parameters=_obj({"limit": _int_param("Max results (1-20).", maximum=20)}),
            run=_gh(board_github.op_list_releases),
            summarize=_summ("Listed releases"),
        ),
        ToolOp(
            name="github_list_workflow_runs",
            tool_id="github",
            kind="read",
            description="List recent GitHub Actions runs (CI status, conclusions, branch).",
            parameters=_obj(
                {
                    "branch": _str_param("Optional branch filter.", max_len=100),
                    "limit": _int_param("Max results (1-20).", maximum=20),
                }
            ),
            run=_gh(board_github.op_list_workflow_runs),
            summarize=_summ("Checked CI runs"),
        ),
        ToolOp(
            name="github_list_commits",
            tool_id="github",
            kind="read",
            description="List recent commits. Pass sha or branch (e.g. staging) — without it this is the default branch only.",
            parameters=_obj(
                {
                    "path": _str_param("Optional file or directory path.", max_len=200),
                    "sha": _str_param("Commit SHA or branch name (GitHub sha=).", max_len=100),
                    "branch": _str_param("Alias for sha.", max_len=100),
                    "limit": _int_param("Max results (1-20).", maximum=20),
                }
            ),
            run=_gh(board_github.op_list_commits),
            summarize=_summ("Listed recent commits"),
        ),
        ToolOp(
            name="github_compare",
            tool_id="github",
            kind="read",
            description="Compare two refs (behindBy / aheadBy / commits). Defaults to main...staging. Use this to verify a staging sync.",
            parameters=_obj(
                {
                    "base": _str_param("Base ref (default main).", max_len=100),
                    "head": _str_param("Head ref (default staging).", max_len=100),
                }
            ),
            run=_gh(board_github.op_compare),
            summarize=_summ("Compared {base}...{head}"),
        ),
        ToolOp(
            name="github_get_file",
            tool_id="github",
            kind="read",
            description="Read a file (text, truncated) or list a directory in the repository.",
            parameters=_obj(
                {
                    "path": _str_param("Path from the repository root, e.g. README.md or docs/architecture.", max_len=200),
                    "ref": _str_param("Optional branch or tag.", max_len=100),
                },
                ["path"],
            ),
            run=_gh(board_github.op_get_file),
            summarize=_summ("Read {path}"),
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
        ToolOp(
            name="github_list_security_alerts",
            tool_id="github",
            kind="read",
            description="List open Dependabot and code-scanning alerts (needs a token with security_events access; otherwise reports why).",
            parameters=_obj({"limit": _int_param("Max alerts per kind (1-50).", maximum=50)}),
            run=_gh(board_github.op_list_security_alerts),
            summarize=_summ("Checked security alerts"),
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
        ToolOp(
            name="github_get_security_alert",
            tool_id="github",
            kind="read",
            description="Read one Dependabot, code-scanning or secret-scanning alert by number, including CVE/GHSA, vulnerable range and patched version.",
            parameters=_obj(
                {
                    "kind": _str_param(
                        "Alert family from the task brief (gh:dependabot:N → dependabot).",
                        enum=["dependabot", "codeScanning", "secretScanning"],
                    ),
                    "number": _int_param("Alert number from GitHub (e.g. 153).", maximum=100000),
                },
                ["kind", "number"],
            ),
            run=_gh(board_github.op_get_security_alert),
            summarize=_summ("Read {kind} alert #{number}"),
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
        ToolOp(
            name="github_create_issue",
            tool_id="github",
            kind="write",
            always_propose=True,
            description="Open a new GitHub issue. Search first; never duplicate an open issue.",
            parameters=_obj(
                {
                    "title": _str_param("Short imperative title.", max_len=200),
                    "body": _str_param("Markdown body: context, acceptance criteria, links.", max_len=4000),
                    "labels": {"type": "array", "items": {"type": "string"}, "description": "Optional labels."},
                    "reason": REASON_PARAM,
                },
                ["title", "body", "reason"],
            ),
            run=_gh(board_github.op_create_issue),
            summarize=_summ("Open GitHub issue: {title}"),
            validate=_validate_github_create_issue,
        ),
        ToolOp(
            name="github_comment_issue",
            tool_id="github",
            kind="write",
            description="Add a comment to an existing issue or pull request.",
            parameters=_obj(
                {
                    "number": _int_param("Issue or PR number.", maximum=100000),
                    "body": _str_param("Markdown comment.", max_len=4000),
                    "reason": REASON_PARAM,
                },
                ["number", "body", "reason"],
            ),
            run=_gh(board_github.op_comment_issue),
            summarize=_summ("Comment on #{number}"),
        ),
        ToolOp(
            name="github_set_labels",
            tool_id="github",
            kind="write",
            description="Replace the labels on an issue or pull request. Include board-ready (keep existing labels) when an issue is ready for code_run_task.",
            parameters=_obj(
                {
                    "number": _int_param("Issue or PR number.", maximum=100000),
                    "labels": {"type": "array", "items": {"type": "string"}, "description": "Full label set to apply."},
                    "reason": REASON_PARAM,
                },
                ["number", "labels", "reason"],
            ),
            run=_gh(board_github.op_set_labels),
            summarize=_summ_labels,
        ),
    ]
