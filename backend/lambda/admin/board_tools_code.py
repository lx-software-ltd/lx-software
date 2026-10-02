"""Tool operations for the code family."""

from __future__ import annotations

from typing import Any

from board_tools_core import (
    REASON_PARAM,
    ToolContext,
    ToolOp,
    _int_param,
    _obj,
    _str_param,
    _summ,
)


def _validate_code_run_task(ctx: ToolContext, args: dict[str, Any]) -> str | None:
    import board_code

    return board_code.validate_run_task(args, ctx)

def _code_run_task(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_code

    return board_code.op_run_task(ctx, args)

def _code_get_run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_code

    return board_code.op_get_run(ctx, args)

def _code_review_pr(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_code

    return board_code.op_review_pr(ctx, args)

def _code_merge_staging(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_code

    return board_code.op_merge_staging(ctx, args)

def _code_promote(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_code

    return board_code.op_promote(ctx, args)

def _code_sync_staging(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_code

    return board_code.op_sync_staging(ctx, args)

def _code_merge_guard(ctx: ToolContext, args: dict[str, Any]) -> str | None:
    import board_code

    return board_code.merge_guard(ctx, args)

def _code_close_pr(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_code

    return board_code.op_close_pr(ctx, args)

def _code_close_guard(ctx: ToolContext, args: dict[str, Any]) -> str | None:
    import board_code

    return board_code.close_guard(ctx, args)

def _preview_code_close_pr(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any] | None:
    import board_code

    return board_code.preview_close_pr(ctx, args)

def ops() -> list[ToolOp]:
    return [
        ToolOp(
            name="code_run_task",
            tool_id="code",
            kind="write",
            description=(
                "Dispatch the coding runner. Opens a draft PR on board/{taskId} from staging. Does not merge. "
                "CI rejects PRs over 400 lines (2000 for content/**); split the brief. "
                "One open board PR per issue — for a second slice, open a new issue first. "
                "If a run is already in flight, call code_get_run instead of dispatching again."
            ),
            parameters=_obj(
                {
                    "issueNumber": _int_param("GitHub issue number.", minimum=1, maximum=100000),
                    "brief": _str_param("What to implement. Include acceptance criteria.", max_len=4000),
                    "kind": _str_param("feature, fix or content (SEO).", enum=["feature", "fix", "content"]),
                    "reason": REASON_PARAM,
                },
                ["issueNumber", "brief"],
            ),
            run=_code_run_task,
            summarize=_summ("Dispatched the coding runner"),
            contexts=("chat", "meeting", "task"),
            validate=_validate_code_run_task,
        ),
        ToolOp(
            name="code_get_run",
            tool_id="code",
            kind="read",
            description="Poll the Actions run and draft PR for a runner task_id.",
            parameters=_obj({"taskId": _str_param("Staff or runner task id.", max_len=40)}),
            run=_code_get_run,
            summarize=_summ("Polled a coding run"),
            contexts=("chat", "meeting", "task"),
        ),
        ToolOp(
            name="code_review_pr",
            tool_id="code",
            kind="read",
            description="Read a pull request: diff stats, paths, CI, and a 30 000 character diff for architect review.",
            parameters=_obj({"prNumber": _int_param("Pull request number.", minimum=1, maximum=100000)}, ["prNumber"]),
            run=_code_review_pr,
            summarize=_summ("Reviewed a pull request"),
            contexts=("chat", "meeting", "task"),
            timeout_seconds=25,
        ),
        ToolOp(
            name="code_merge_staging",
            tool_id="code",
            kind="write",
            description="Merge a board/* PR into staging after CI, architect accept, size and path checks. Held as code_staging.",
            parameters=_obj(
                {
                    "prNumber": _int_param("Pull request number.", minimum=1, maximum=100000),
                    "kind": _str_param("feature, fix or content.", enum=["feature", "fix", "content"]),
                    "reason": REASON_PARAM,
                },
                ["prNumber"],
            ),
            run=_code_merge_staging,
            summarize=_summ("Merged a pull request to staging"),
            contexts=("chat", "meeting", "task"),
            act_guard=_code_merge_guard,
            always_propose=True,
        ),
        ToolOp(
            name="code_close_pr",
            tool_id="code",
            kind="write",
            description=(
                "Close a board/* pull request without merging (founder veto, superseded work, "
                "or a review that will not be revised). Does not delete the branch. Always an "
                "Approval (not a hold). After a vetoed merge, call this instead of retrying "
                "code_merge_staging. Relabels the linked GitHub issue: removes board-ready and "
                "adds board-closed so the runner will not pick it up again until an architect "
                "re-adds board-ready."
            ),
            parameters=_obj(
                {
                    "prNumber": _int_param("Pull request number.", minimum=1, maximum=100000),
                    "reason": REASON_PARAM,
                },
                ["prNumber", "reason"],
            ),
            run=_code_close_pr,
            summarize=_summ("Closed pull request #{prNumber}"),
            contexts=("chat", "meeting", "task"),
            act_guard=_code_close_guard,
            validate=_code_close_guard,
            preview=_preview_code_close_pr,
            always_propose=True,
            action_class="code_close",
        ),
        ToolOp(
            name="code_promote",
            tool_id="code",
            kind="write",
            description="Open or update the staging→main promotion PR. Always an Approval; the owner merges in GitHub.",
            parameters=_obj(
                {
                    "kind": _str_param("Always production in v1.", enum=["production"]),
                    "reason": REASON_PARAM,
                }
            ),
            run=_code_promote,
            summarize=_summ("Proposed a staging promotion"),
            contexts=("chat", "meeting", "task"),
            always_propose=True,
            action_class="code_production",
        ),
        ToolOp(
            name="code_sync_staging",
            tool_id="code",
            kind="write",
            description="Merge main into staging so staging is current (GitHub merges API). Confirm with github_compare. Does not force-push. Act-level calls follow the code_staging hold.",
            parameters=_obj({"reason": REASON_PARAM}),
            run=_code_sync_staging,
            summarize=_summ("Synced staging with main"),
            contexts=("chat", "meeting", "task"),
            action_class="code_staging",
        ),
    ]
