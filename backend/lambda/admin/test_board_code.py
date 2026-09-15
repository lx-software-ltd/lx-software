"""Unit tests for the engineering runner (WP10)."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from test_board import BoardTestCase
from test_board_tools import ToolsTestCase

import board_async
import board_code
import board_github
import board_holds
import board_staff
import board_store
import board_tools
from board_tools import REGISTRY, ToolContext, execute_call


def _enable_staff(table: Any, **staff: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    settings["staff"] = board_store.normalize_staff_config({**(settings.get("staff") or {}), "enabled": True, **staff})
    settings["tools"]["globalMode"] = "act"
    settings["tools"]["matrix"]["code"]["cto"] = "act"
    saved = board_store.save_settings(table, settings)
    for seat in ("architect", "engineer-1", "engineer-2"):
        board_store.save_staff_override(table, seat, {"isActive": True})
    return saved


class FakeActions:
    """Scripted GitHub REST for runner / PR / CI / compare calls."""

    def __init__(self) -> None:
        self.dispatches: list[dict[str, Any]] = []
        self.prs: list[dict[str, Any]] = []
        self.files: dict[int, list[dict[str, Any]]] = {}
        self.checks: dict[str, list[dict[str, Any]]] = {}
        self.runs: list[dict[str, Any]] = []
        self.jobs: dict[int, list[dict[str, Any]]] = {}
        self.job_logs: dict[int, str] = {}
        self.logAccepts: list[str] = []
        self.issues: list[dict[str, Any]] = []
        self.labels: set[str] = set()
        self.labelCreates = 0
        self.issueLabels: list[tuple[int, list[str]]] = []
        self.merges: list[dict[str, Any]] = []
        self.patches: list[dict[str, Any]] = []
        self.comments: list[dict[str, Any]] = []
        self.writeOrder: list[str] = []
        self.compare: dict[str, Any] = {"status": "ahead", "ahead_by": 2, "behind_by": 0, "commits": []}
        self.diff = "diff --git a/app.py b/app.py\n+ok\n"

    def __call__(self, method: str, path: str, *, body: dict[str, Any] | None = None, accept: str = "application/vnd.github+json") -> Any:
        if accept == "application/vnd.github.diff":
            return self.diff
        if method == "POST" and "/actions/workflows/" in path and path.endswith("/dispatches"):
            name = path.split("/workflows/", 1)[1].split("/", 1)[0]
            self.dispatches.append({"workflow": name, "body": body or {}})
            return {}
        if method == "GET" and path.endswith("/pulls?state=open&per_page=50"):
            return [p for p in self.prs if str(p.get("state") or "open") != "closed"]
        if method == "GET" and "/pulls?head=" in path:
            head = path.split("head=", 1)[1].split("&", 1)[0]
            ref = head.split(":", 1)[-1]
            return [p for p in self.prs if ((p.get("head") or {}).get("ref") or "") == ref]
        if method == "GET" and "/pulls/" in path and "/files?" in path:
            number = int(path.split("/pulls/", 1)[1].split("/", 1)[0])
            all_files = list(self.files.get(number) or [])
            page = int((parse_qs(urlparse(path).query).get("page") or ["1"])[0])
            start = (page - 1) * 100
            return all_files[start : start + 100]
        if method == "PATCH" and "/pulls/" in path:
            number = int(path.rstrip("/").rsplit("/", 1)[-1].split("?")[0])
            pr = next((p for p in self.prs if p.get("number") == number), None)
            if pr is None:
                return None
            self.patches.append({"number": number, "body": body or {}})
            self.writeOrder.append("patch")
            if isinstance(body, dict) and body.get("state"):
                pr["state"] = body["state"]
            return pr
        if method == "POST" and "/issues/" in path and path.endswith("/comments"):
            number = int(path.split("/issues/", 1)[1].split("/", 1)[0])
            self.comments.append({"number": number, "body": (body or {}).get("body")})
            self.writeOrder.append("comment")
            return {"id": 1, "html_url": f"https://github.com/x/{number}#issuecomment-1"}
        if method == "GET" and "/pulls/" in path:
            number = int(path.rstrip("/").rsplit("/", 1)[-1].split("?")[0])
            return next((p for p in self.prs if p.get("number") == number), None)
        if method == "GET" and path.endswith("/actions/runs?per_page=30"):
            return {"workflow_runs": list(self.runs)}
        if method == "GET" and "/actions/runs/" in path and path.endswith("/jobs"):
            run_id = int(path.split("/runs/", 1)[1].split("/", 1)[0])
            return {"jobs": list(self.jobs.get(run_id) or [])}
        if method == "GET" and "/actions/jobs/" in path and path.endswith("/logs"):
            self.logAccepts.append(accept)
            job_id = int(path.split("/jobs/", 1)[1].split("/", 1)[0])
            return self.job_logs.get(job_id, "")
        if method == "GET" and "/check-runs" in path:
            sha = path.split("/commits/", 1)[1].split("/", 1)[0]
            return {"check_runs": list(self.checks.get(sha) or [])}
        if method == "GET" and path.endswith("/status"):
            return {"state": "pending"}
        if method == "PUT" and "/issues/" in path and path.endswith("/labels"):
            number = int(path.split("/issues/", 1)[1].split("/", 1)[0])
            names = [str(x) for x in ((body or {}).get("labels") or []) if x]
            self.issueLabels.append((number, names))
            self.writeOrder.append("labels")
            for issue in self.issues:
                if int(issue.get("number") or 0) != number:
                    continue
                issue["labels"] = [{"name": n} for n in names]
            return [{"name": n} for n in names]
        if method == "GET" and "/issues/" in path and "/comments" not in path and "/labels" not in path and "?" not in path:
            number = int(path.rstrip("/").rsplit("/", 1)[-1])
            return next((i for i in self.issues if int(i.get("number") or 0) == number), None)
        if method == "GET" and "/issues?" in path:
            items = [i for i in self.issues if isinstance(i, dict)]
            if "labels=board-ready" in path:
                items = [
                    i
                    for i in items
                    if any(
                        (lab.get("name") if isinstance(lab, dict) else lab) == "board-ready"
                        for lab in (i.get("labels") or [])
                    )
                ]
            return items
        if method == "GET" and "/labels/" in path:
            name = path.rstrip("/").rsplit("/", 1)[-1]
            return {"name": name} if name in self.labels else None
        if method == "POST" and "/issues/" in path and path.endswith("/labels"):
            number = int(path.split("/issues/", 1)[1].split("/", 1)[0])
            names = [str(x) for x in ((body or {}).get("labels") or []) if x]
            self.issueLabels.append((number, names))
            for issue in self.issues:
                if int(issue.get("number") or 0) != number:
                    continue
                existing = issue.setdefault("labels", [])
                have = {
                    (lab.get("name") if isinstance(lab, dict) else lab)
                    for lab in existing
                }
                for name in names:
                    if name not in have:
                        existing.append({"name": name})
            return [{"name": n} for n in names]
        if method == "POST" and path.endswith("/labels"):
            name = str((body or {}).get("name") or "")
            if name:
                self.labels.add(name)
                self.labelCreates += 1
            return body or {}
        if method == "POST" and path.endswith("/merges"):
            self.merges.append(body or {})
            self.compare = {"status": "identical", "ahead_by": 0, "behind_by": 0, "commits": []}
            return {"sha": "abcmerged000"}
        if method == "GET" and "/compare/" in path:
            return self.compare
        return {}


def _pr(number: int = 7, *, issue: int = 42, base: str = "staging", sha: str = "abc123") -> dict[str, Any]:
    return {
        "number": number,
        "title": f"board: #{issue} add booking",
        "body": f"Implements #{issue}\n\nTask: task-1",
        "draft": True,
        "state": "open",
        "merged": False,
        "html_url": f"https://github.com/lx-software-ltd/siutindei/pull/{number}",
        "base": {"ref": base},
        "head": {"ref": "board/task-1", "sha": sha},
    }


def _green(sha: str = "abc123") -> list[dict[str, Any]]:
    return [{"name": "ci", "status": "completed", "conclusion": "success"}]


class PathPolicyTests(unittest.TestCase):
    def test_protected_paths_include_renames(self) -> None:
        files = [{"filename": "src/other/x.ts", "previous_filename": "src/auth/x.ts", "changes": 2}]
        self.assertEqual(board_code.files_protected(files), ["src/auth/x.ts"])
        self.assertTrue(board_code.path_is_protected("infra/cdk.ts"))
        self.assertTrue(board_code.path_is_protected(".github/workflows/x.yml"))
        self.assertFalse(board_code.path_is_protected("src/authorize.py"))

    def test_content_kind_paths(self) -> None:
        self.assertTrue(board_code.path_is_content("content/en/sha-tin.md"))
        self.assertFalse(board_code.path_is_content("src/content.ts"))

    def test_review_json_accept_and_changes(self) -> None:
        parsed = board_code.parse_review_verdict('notes\n```json\n{"verdict":"accept","notes":[]}\n```\n')
        self.assertEqual(parsed["verdict"], "accept")
        parsed = board_code.parse_review_verdict('{"verdict":"changes","notes":["fix the test"]}')
        self.assertEqual(parsed["verdict"], "changes")
        self.assertEqual(parsed["notes"], ["fix the test"])


class RunnerTests(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        os.environ.pop("ASSETS_BUCKET_NAME", None)
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        patcher = patch.object(board_async, "invoke_async", side_effect=lambda payload, *, fallback=None: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.gh = FakeActions()
        gh_patch = patch.object(board_github, "_request", side_effect=self.gh)
        gh_patch.start()
        self.addCleanup(gh_patch.stop)
        os.environ["GITHUB_READ_TOKEN"] = "ghp_test"
        board_github.reset_token_cache_for_tests()
        self.addCleanup(lambda: os.environ.pop("GITHUB_READ_TOKEN", None))
        self.addCleanup(board_github.reset_token_cache_for_tests)
        self.settings = _enable_staff(self.table)
        board_code.reset_lookup_caches_for_tests()
        self.addCleanup(board_code.reset_lookup_caches_for_tests)
        self.ctx = ToolContext(self.table, self.settings, "cto", display_name="CTO", kind="task", task_id="task-1")

    def test_run_task_dispatch_payload(self) -> None:
        out = board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "Add the booking form.", "kind": "feature"})
        self.assertEqual(out["workflow"], "board-agent.yml")
        self.assertEqual(self.gh.dispatches[0]["body"]["ref"], "staging")
        self.assertEqual(
            self.gh.dispatches[0]["body"]["inputs"],
            {"task_id": "task-1", "issue": "42", "brief": "Add the booking form.", "kind": "feature"},
        )

    def test_run_task_refuses_second_engineer_on_same_issue(self) -> None:
        self.gh.prs.append(_pr(issue=42))
        with self.assertRaises(board_code.CodeError):
            board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "again", "kind": "feature"})

    def test_failed_run_without_pr_does_not_block_retry(self) -> None:
        board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "Add the booking form.", "kind": "feature"})
        self.assertTrue(board_code.issue_has_open_board_pr(42, self.table))
        self.gh.runs.append(
            {
                "name": "board-agent task-1",
                "status": "completed",
                "conclusion": "failure",
                "html_url": "https://example/run-fail",
            }
        )
        out = board_code.op_get_run(self.ctx, {"taskId": "task-1"})
        self.assertEqual(out["conclusion"], "failure")
        stored = board_code._get_run(self.table, "task-1")  # noqa: SLF001
        self.assertEqual(stored["conclusion"], "failure")
        self.assertFalse(board_code.issue_has_open_board_pr(42, self.table))
        self.assertTrue(stored.get("failedAt"))

    def test_run_task_refuses_in_flight_duplicate(self) -> None:
        board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "Add the booking form.", "kind": "feature"})
        with self.assertRaises(board_code.CodeError) as raised:
            board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "Add the booking form again.", "kind": "feature"})
        self.assertIn("already in flight", str(raised.exception))
        self.assertEqual(len(self.gh.dispatches), 1)

    def test_run_task_cooldown_expiry_allows_retry(self) -> None:
        board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "Add the booking form.", "kind": "feature"})
        stored = board_code._get_run(self.table, "task-1")  # noqa: SLF001
        stored["dispatchedAt"] = (datetime.now(timezone.utc) - timedelta(seconds=901)).strftime("%Y-%m-%dT%H:%M:%SZ")
        board_code._put_run(self.table, "task-1", stored)  # noqa: SLF001
        out = board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "Retry after cooldown.", "kind": "feature"})
        self.assertEqual(out["rounds"], 2)
        self.assertEqual(len(self.gh.dispatches), 2)

    def test_run_task_caps_rounds(self) -> None:
        board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "Add the booking form.", "kind": "feature"})
        stored = board_code._get_run(self.table, "task-1")  # noqa: SLF001
        stored["dispatchedAt"] = (datetime.now(timezone.utc) - timedelta(seconds=901)).strftime("%Y-%m-%dT%H:%M:%SZ")
        board_code._put_run(self.table, "task-1", stored)  # noqa: SLF001
        board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "Second run.", "kind": "feature"})
        stored = board_code._get_run(self.table, "task-1")  # noqa: SLF001
        stored["dispatchedAt"] = (datetime.now(timezone.utc) - timedelta(seconds=901)).strftime("%Y-%m-%dT%H:%M:%SZ")
        board_code._put_run(self.table, "task-1", stored)  # noqa: SLF001
        with self.assertRaises(board_code.CodeError) as raised:
            board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "Third run.", "kind": "feature"})
        self.assertIn("two runs already made", str(raised.exception))

    def test_get_run_returns_failure_line(self) -> None:
        board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "Add the booking form.", "kind": "feature"})
        self.gh.runs.append(
            {
                "id": 99,
                "name": "board-agent task-1",
                "status": "completed",
                "conclusion": "failure",
                "html_url": "https://example/run-fail",
            }
        )
        self.gh.jobs[99] = [{"id": 7, "conclusion": "failure", "name": "Guard protected paths"}]
        self.gh.job_logs[7] = "pull request changes 439 lines (max 400)\n##[error]Process completed"
        out = board_code.op_get_run(self.ctx, {"taskId": "task-1"})
        self.assertEqual(out["failureLine"], "pull request changes 439 lines (max 400)")
        self.assertEqual(self.gh.logAccepts, ["application/vnd.github.raw"])

    def test_extract_failure_line_picks_last_match(self) -> None:
        log = "setup\npull request changes 12 lines (max 400)\nmypy: Incompatible return value type\n"
        self.assertEqual(board_code.extract_failure_line(log), "mypy: Incompatible return value type")

    def test_extract_failure_line_prefers_pytest_failed(self) -> None:
        log = (
            "mypy: Incompatible return value type\n"
            "FAILED backend/test_x.py::test_y - AssertionError: expected 1\n"
            "===== 1 failed =====\n"
        )
        self.assertEqual(
            board_code.extract_failure_line(log),
            "FAILED backend/test_x.py::test_y - AssertionError: expected 1",
        )

    def test_revision_reuses_original_run_task_id(self) -> None:
        board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "Add the booking form.", "kind": "feature"})
        self.gh.prs.append(_pr(issue=42))
        stored = board_code._get_run(self.table, "task-1")  # noqa: SLF001
        stored["prNumber"] = 7
        stored["failedAt"] = board_store.now_iso()
        stored["conclusion"] = "failure"
        stored["failureLine"] = 'mypy: got "str", expected "UUID"'
        board_code._put_run(self.table, "task-1", stored)  # noqa: SLF001
        board_store.put_task(
            self.table,
            {
                "taskId": "revise-1",
                "status": "running",
                "assignee": "engineer-2",
                "eventRef": {
                    "kind": "code-implement",
                    "id": "issue:42:r2",
                    "issueNumber": 42,
                    "prNumber": 7,
                },
            },
        )
        revise_ctx = ToolContext(
            self.table, self.settings, "cto", display_name="CTO", kind="task", task_id="revise-1"
        )
        out = board_code.op_run_task(revise_ctx, {"issueNumber": 42, "brief": "Fix mypy on PR 498.", "kind": "fix"})
        self.assertEqual(out["taskId"], "task-1")
        self.assertNotIn("failureLine", out)
        self.assertEqual(self.gh.dispatches[-1]["body"]["inputs"]["task_id"], "task-1")
        self.assertEqual(self.gh.dispatches[-1]["body"]["inputs"]["kind"], "fix")

    def test_revision_remaps_when_engineer_passes_pr_number_as_issue(self) -> None:
        board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "Add the booking form.", "kind": "feature"})
        self.gh.prs.append(_pr(issue=42))
        stored = board_code._get_run(self.table, "task-1")  # noqa: SLF001
        stored["prNumber"] = 7
        stored["failedAt"] = board_store.now_iso()
        stored["conclusion"] = "failure"
        board_code._put_run(self.table, "task-1", stored)  # noqa: SLF001
        board_store.put_task(
            self.table,
            {
                "taskId": "revise-pr-as-issue",
                "status": "running",
                "assignee": "engineer-1",
                "eventRef": {
                    "kind": "code-implement",
                    "id": "issue:42:r2",
                    "issueNumber": 42,
                    "prNumber": 7,
                },
            },
        )
        revise_ctx = ToolContext(
            self.table, self.settings, "cto", display_name="CTO", kind="task", task_id="revise-pr-as-issue"
        )
        out = board_code.op_run_task(
            revise_ctx, {"issueNumber": 7, "brief": "Fix CI on this PR.", "kind": "fix"}
        )
        self.assertEqual(out["taskId"], "task-1")
        self.assertEqual(out["issue"], 42)
        self.assertEqual(self.gh.dispatches[-1]["body"]["inputs"]["issue"], "42")
        self.assertEqual(self.gh.dispatches[-1]["body"]["inputs"]["task_id"], "task-1")

    def test_validate_run_task_rejects_pull_request_number(self) -> None:
        self.gh.issues.append(
            {"number": 7, "title": "A pull request", "state": "open", "pull_request": {"url": "https://example"}}
        )
        reason = board_code.validate_run_task({"issueNumber": 7})
        self.assertIn("pull request", reason or "")

    def test_validate_run_task_allows_pr_number_on_revision_task(self) -> None:
        board_code._put_run(self.table, "task-1", {"taskId": "task-1", "prNumber": 7, "issue": 42})  # noqa: SLF001
        board_store.put_task(
            self.table,
            {
                "taskId": "revise-ok",
                "status": "running",
                "eventRef": {"kind": "code-implement", "prNumber": 7, "issueNumber": 42},
            },
        )
        ctx = ToolContext(self.table, self.settings, "cto", kind="task", task_id="revise-ok")
        self.assertIsNone(board_code.validate_run_task({"issueNumber": 7}, ctx))

    def test_validate_run_task_refuses_pr_number_without_stored_issue(self) -> None:
        board_store.put_task(
            self.table,
            {
                "taskId": "revise-stub",
                "status": "running",
                "eventRef": {"kind": "code-implement", "prNumber": 7},
            },
        )
        ctx = ToolContext(self.table, self.settings, "cto", kind="task", task_id="revise-stub")
        reason = board_code.validate_run_task({"issueNumber": 7}, ctx)
        self.assertIn("issue number", reason or "")

    def test_revision_allowed_when_original_already_used_dispatch_cap(self) -> None:
        board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "Add the booking form.", "kind": "feature"})
        self.gh.prs.append(_pr(issue=42))
        stored = board_code._get_run(self.table, "task-1")  # noqa: SLF001
        stored["prNumber"] = 7
        stored["rounds"] = 2
        stored["dispatchRounds"] = 2
        stored["lastStaffTaskId"] = "task-1"
        stored["failedAt"] = board_store.now_iso()
        stored["conclusion"] = "failure"
        stored["failureLine"] = "pull request changes 439 lines (max 400)"
        board_code._put_run(self.table, "task-1", stored)  # noqa: SLF001
        board_store.put_task(
            self.table,
            {
                "taskId": "revise-cap",
                "status": "running",
                "assignee": "engineer-2",
                "eventRef": {
                    "kind": "code-implement",
                    "id": "issue:42:r2",
                    "issueNumber": 42,
                    "prNumber": 7,
                },
            },
        )
        revise_ctx = ToolContext(
            self.table, self.settings, "cto", display_name="CTO", kind="task", task_id="revise-cap"
        )
        out = board_code.op_run_task(revise_ctx, {"issueNumber": 42, "brief": "Split the PR.", "kind": "fix"})
        self.assertEqual(out["taskId"], "task-1")
        self.assertEqual(out["dispatchRounds"], 1)
        self.assertNotIn("failureLine", board_code._get_run(self.table, "task-1"))  # noqa: SLF001

    def test_review_changes_uses_review_rounds_not_dispatch_count(self) -> None:
        board_code._put_run(  # noqa: SLF001
            self.table,
            "task-1",
            {"issue": 42, "kind": "feature", "rounds": 2, "reviewRounds": 0},
        )
        board_staff._blob_put(  # noqa: SLF001
            board_staff._deliverable_key("rev-rounds", "markdown"),  # noqa: SLF001
            b'```json {"verdict":"changes","notes":["split the PR"]}\n```',
        )
        task = {
            "taskId": "rev-rounds",
            "status": "delivered",
            "assignee": "architect",
            "deliverableKey": board_staff._deliverable_key("rev-rounds", "markdown"),  # noqa: SLF001
            "eventRef": {"kind": "code-review", "id": "pr:7", "prNumber": 7, "taskId": "task-1"},
        }
        board_store.put_task(self.table, task)
        self.gh.prs.append(_pr())
        self.gh.files[7] = [{"filename": "app.py", "changes": 4}]
        self.gh.checks["abc123"] = _green()
        out = board_code.on_review_delivered(self.table, self.settings, task)
        self.assertEqual(out.get("verdict"), "changes")
        self.assertNotEqual(out.get("stopped"), "max rounds")
        self.assertEqual(board_code._get_run(self.table, "task-1").get("reviewRounds"), 1)  # noqa: SLF001

    def test_revise_brief_includes_failure_line(self) -> None:
        board_code._put_run(  # noqa: SLF001
            self.table,
            "task-1",
            {"issue": 42, "kind": "feature", "rounds": 1, "failureLine": 'mypy: got "str", expected "UUID"'},
        )
        board_staff._blob_put(  # noqa: SLF001
            board_staff._deliverable_key("rev-1", "markdown"),  # noqa: SLF001
            b'```json {"verdict":"changes","notes":["CI failed"]}\n```',
        )
        task = {
            "taskId": "rev-1",
            "status": "delivered",
            "assignee": "architect",
            "deliverableKey": board_staff._deliverable_key("rev-1", "markdown"),  # noqa: SLF001
            "eventRef": {"kind": "code-review", "id": "pr:7", "prNumber": 7, "taskId": "task-1"},
        }
        board_store.put_task(self.table, task)
        self.gh.prs.append(_pr())
        self.gh.files[7] = [{"filename": "app.py", "changes": 4}]
        self.gh.checks["abc123"] = _green()
        out = board_code.on_review_delivered(self.table, self.settings, task)
        follow = board_store.get_task(self.table, out["taskId"])
        self.assertIn("CI failure: mypy: got", follow["brief"])
        self.assertIn("Call code_run_task ONCE", follow["brief"])
        self.assertIn("Do not poll CI", follow["brief"])
        self.assertEqual(follow["eventRef"]["kind"], "code-implement")

    def test_review_changes_skips_pending_only_notes(self) -> None:
        board_code._put_run(self.table, "task-1", {"issue": 42, "kind": "feature", "reviewRounds": 0})  # noqa: SLF001
        board_staff._blob_put(  # noqa: SLF001
            board_staff._deliverable_key("rev-pending", "markdown"),  # noqa: SLF001
            b'```json {"verdict":"changes","notes":["CI is pending; not ready for review yet as the CI must pass"]}\n```',
        )
        task = {
            "taskId": "rev-pending",
            "status": "delivered",
            "assignee": "architect",
            "deliverableKey": board_staff._deliverable_key("rev-pending", "markdown"),  # noqa: SLF001
            "eventRef": {"kind": "code-review", "id": "pr:7", "prNumber": 7, "taskId": "task-1"},
        }
        board_store.put_task(self.table, task)
        self.gh.prs.append(_pr())
        self.gh.files[7] = [{"filename": "app.py", "changes": 4}]
        self.gh.checks["abc123"] = _green()
        out = board_code.on_review_delivered(self.table, self.settings, task)
        self.assertEqual(out.get("skipped"), "ci pending")
        self.assertFalse(out.get("taskId"))

    def test_owner_revision_ref_sets_event_ref(self) -> None:
        self.gh.prs.append(_pr(number=498, issue=489))
        ref = board_code.owner_revision_ref(self.table, 498)
        self.assertEqual(ref["kind"], "code-implement")
        self.assertEqual(ref["prNumber"], 498)
        self.assertEqual(ref["issueNumber"], 489)

    def test_owner_revision_ref_requires_issue_when_pr_has_none(self) -> None:
        self.gh.prs.append({**_pr(number=500, issue=0), "title": "no issue", "body": "orphan"})
        with self.assertRaises(board_code.CodeRefused):
            board_code.owner_revision_ref(self.table, 500)
        ref = board_code.owner_revision_ref(self.table, 500, issue_number=42)
        self.assertEqual(ref["issueNumber"], 42)

    def test_run_task_refuses_revision_when_pr_has_no_issue(self) -> None:
        self.gh.prs.append({**_pr(number=7, issue=0), "title": "orphan", "body": "no issue"})
        board_store.put_task(
            self.table,
            {
                "taskId": "revise-stub",
                "status": "running",
                "eventRef": {"kind": "code-implement", "prNumber": 7},
            },
        )
        ctx = ToolContext(self.table, self.settings, "cto", kind="task", task_id="revise-stub")
        with self.assertRaises(board_code.CodeRefused) as raised:
            board_code.op_run_task(ctx, {"issueNumber": 7, "brief": "Fix CI.", "kind": "fix"})
        self.assertIn("no linked GitHub issue", str(raised.exception))
        self.assertEqual(self.gh.dispatches, [])

    def test_brief_mismatch_flags_when_issue_nouns_absent(self) -> None:
        self.gh.issues.append(
            {"number": 42, "title": "Upgrade extract-zip for CVE-2026-99999", "state": "open"}
        )
        board_store.put_task(self.table, {"taskId": "task-1", "status": "running", "flags": []})
        out = board_code.op_run_task(
            self.ctx, {"issueNumber": 42, "brief": "Accept area_name on locations.", "kind": "feature"}
        )
        self.assertTrue(out.get("briefMismatch"))
        task = board_store.get_task(self.table, "task-1")
        self.assertIn("brief_mismatch", task.get("flags") or [])

    def test_action_required_run_still_blocks_issue(self) -> None:
        board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "Add the booking form.", "kind": "feature"})
        self.gh.runs.append(
            {
                "name": "board-agent task-1",
                "status": "completed",
                "conclusion": "action_required",
                "html_url": "https://example/run-wait",
            }
        )
        out = board_code.op_get_run(self.ctx, {"taskId": "task-1"})
        self.assertEqual(out["conclusion"], "action_required")
        stored = board_code._get_run(self.table, "task-1")  # noqa: SLF001
        self.assertFalse(stored.get("failedAt"))
        self.assertTrue(board_code.issue_has_open_board_pr(42, self.table))

    def test_get_run_does_not_create_row_for_unknown_task(self) -> None:
        out = board_code.op_get_run(self.ctx, {"taskId": "never-dispatched"})
        self.assertEqual(out["runStatus"], "unknown")
        self.assertEqual(board_code._get_run(self.table, "never-dispatched"), {})  # noqa: SLF001
        self.assertNotIn("never-dispatched", board_code._run_index(self.table))  # noqa: SLF001

    def test_lockfile_changes_do_not_count_toward_line_limit(self) -> None:
        files = [
            {"filename": "apps/public_www/package-lock.json", "changes": 1800},
            {"filename": "apps/public_www/src/lib/uuid.ts", "changes": 12},
        ]
        self.assertEqual(board_code.changed_lines(files), 12)
        self.assertTrue(board_code.path_is_lockfile("apps/public_www/package-lock.json"))

    def test_get_run_matches_task_id_in_run_name(self) -> None:
        self.gh.runs.append({"name": "board-agent task-1", "status": "completed", "conclusion": "success", "html_url": "https://example/run"})
        self.gh.prs.append(_pr())
        out = board_code.op_get_run(self.ctx, {"taskId": "task-1"})
        self.assertEqual(out["prNumber"], 7)
        self.assertEqual(out["conclusion"], "success")

    def test_architect_accepted_salvaged_accept(self) -> None:
        board_staff._blob_put(  # noqa: SLF001
            board_staff._deliverable_key("rev-salvage", "markdown"),  # noqa: SLF001
            b'```json {"verdict":"accept","notes":["looks good"]}\n```',
        )
        task = {
            "taskId": "rev-salvage",
            "status": "needs_owner",
            "flags": ["salvaged"],
            "assignee": "architect",
            "deliverableKey": board_staff._deliverable_key("rev-salvage", "markdown"),  # noqa: SLF001
            "eventRef": {"kind": "code-review", "id": "pr:7", "prNumber": 7, "headSha": "abc123"},
        }
        board_store.put_task(self.table, task)
        board_store.put_task_review(
            self.table,
            "rev-salvage",
            {"seq": 1, "verdict": "accept", "notes": "ok", "at": board_store.now_iso(), "by": "manager"},
        )
        self.gh.prs.append(_pr())
        self.assertTrue(board_code.architect_accepted(self.table, 7))

    def test_architect_accepted_needs_owner_without_salvage_is_false(self) -> None:
        board_staff._blob_put(  # noqa: SLF001
            board_staff._deliverable_key("rev-no", "markdown"),  # noqa: SLF001
            b'```json {"verdict":"accept","notes":["looks good"]}\n```',
        )
        board_store.put_task(
            self.table,
            {
                "taskId": "rev-no",
                "status": "needs_owner",
                "flags": [],
                "deliverableKey": board_staff._deliverable_key("rev-no", "markdown"),  # noqa: SLF001
                "eventRef": {"kind": "code-review", "id": "pr:7", "prNumber": 7, "headSha": "abc123"},
            },
        )
        self.gh.prs.append(_pr())
        self.assertFalse(board_code.architect_accepted(self.table, 7))

    def test_merge_guard_matrix(self) -> None:
        self.gh.prs.append(_pr())
        self.gh.files[7] = [{"filename": "lib/app.py", "additions": 10, "deletions": 2, "changes": 12}]
        self.gh.checks["abc123"] = _green()
        self.assertIn("architect review", board_code.merge_guard(self.ctx, {"prNumber": 7}) or "")

        self.gh.checks["abc123"] = [{"name": "ci", "status": "completed", "conclusion": "failure"}]
        self.assertIn("CI", board_code.merge_guard(self.ctx, {"prNumber": 7}) or "")

        self.gh.checks["abc123"] = _green()
        self.gh.prs[0]["base"] = {"ref": "main"}
        self.assertIn("staging", board_code.merge_guard(self.ctx, {"prNumber": 7}) or "")
        self.gh.prs[0]["base"] = {"ref": "staging"}

        self.gh.files[7] = [{"filename": "src/auth/login.ts", "changes": 3}]
        self._deliver_accept(7)
        self.assertIn("protected path", board_code.merge_guard(self.ctx, {"prNumber": 7}) or "")

        self.gh.files[7] = [{"filename": "lib/app.py", "changes": 401}]
        self.assertIn("401 lines", board_code.merge_guard(self.ctx, {"prNumber": 7}) or "")

        self.gh.files[7] = [{"filename": "lib/app.py", "changes": 12}]
        self.assertIsNone(board_code.merge_guard(self.ctx, {"prNumber": 7}))

        self.gh.prs[0]["state"] = "closed"
        self.assertIn("not open", board_code.merge_guard(self.ctx, {"prNumber": 7}) or "")
        self.gh.prs[0]["state"] = "open"
        self.gh.prs[0]["merged"] = True
        self.gh.prs[0]["merged_at"] = "2026-09-15T00:00:00Z"
        self.assertIn("already merged", board_code.merge_guard(self.ctx, {"prNumber": 7}) or "")

    def test_content_kind_allows_2000_lines_inside_content(self) -> None:
        self.gh.prs.append(_pr())
        self.gh.files[7] = [{"filename": "content/en/guide.md", "changes": 1500}]
        self.gh.checks["abc123"] = _green()
        self._deliver_accept(7)
        self.assertIsNone(board_code.merge_guard(self.ctx, {"prNumber": 7, "kind": "content"}))
        self.gh.files[7] = [{"filename": "content/en/guide.md", "changes": 2001}]
        self.assertIn("2001 lines", board_code.merge_guard(self.ctx, {"prNumber": 7, "kind": "content"}) or "")
        self.gh.files[7] = [{"filename": "src/page.tsx", "changes": 10}]
        self.assertIn("content/**", board_code.merge_guard(self.ctx, {"prNumber": 7, "kind": "content"}) or "")

    def test_merge_dispatches_merge_workflow(self) -> None:
        self.gh.prs.append(_pr())
        self.gh.files[7] = [{"filename": "lib/app.py", "changes": 12}]
        self.gh.checks["abc123"] = _green()
        self._deliver_accept(7)
        out = board_code.op_merge_staging(self.ctx, {"prNumber": 7})
        self.assertEqual(out["workflow"], "board-merge-staging.yml")
        self.assertEqual(self.gh.dispatches[0]["body"]["inputs"]["pr_number"], "7")

    def test_merge_refuses_when_ci_flips_after_accept(self) -> None:
        self.gh.prs.append(_pr())
        self.gh.files[7] = [{"filename": "lib/app.py", "changes": 12}]
        self.gh.checks["abc123"] = _green()
        self._deliver_accept(7)
        self.gh.checks["abc123"] = [{"name": "ci", "status": "completed", "conclusion": "failure"}]
        out = board_code.op_merge_staging(self.ctx, {"prNumber": 7})
        self.assertIn("CI", out.get("error") or "")
        self.assertEqual(self.gh.dispatches, [])

    def test_merge_refuses_new_head_sha_after_accept(self) -> None:
        self.gh.prs.append(_pr())
        self.gh.files[7] = [{"filename": "lib/app.py", "changes": 12}]
        self.gh.checks["abc123"] = _green()
        self._deliver_accept(7)
        self.gh.prs[0]["head"] = {"ref": "board/task-1", "sha": "fff999"}
        self.gh.checks["fff999"] = _green()
        out = board_code.op_merge_staging(self.ctx, {"prNumber": 7})
        self.assertIn("architect review", out.get("error") or "")

    def test_pr_files_paginates_and_refuses_protected_on_later_page(self) -> None:
        files = [{"filename": f"lib/f{i}.py", "changes": 1} for i in range(119)]
        files.append({"filename": "src/auth/secret.ts", "changes": 1})
        self.gh.prs.append({**_pr(), "changed_files": 120})
        self.gh.files[7] = files
        self.gh.checks["abc123"] = _green()
        self._deliver_accept(7)
        reason = board_code.merge_guard(self.ctx, {"prNumber": 7})
        self.assertIn("protected path", reason or "")

    def test_promote_refuses_when_staging_behind(self) -> None:
        self.gh.compare = {"status": "behind", "ahead_by": 0, "behind_by": 3, "commits": []}
        out = board_code.op_promote(self.ctx, {"kind": "production"})
        self.assertIn("behind", out["error"])
        tasks = board_store.list_tasks(self.table, "queued") + board_store.list_tasks(self.table, "running")
        match = next(t for t in tasks if (t.get("eventRef") or {}).get("id") == "rebase-staging")
        self.assertEqual(match["assignee"], "cto")
        self.assertEqual(match["assigneeKind"], "persona")
        self.assertIn("code_sync_staging", match["brief"])
        self.assertIn("engineer-1", match["brief"])
        self.assertEqual(self.gh.dispatches, [])

    def test_promote_dispatches_when_ahead(self) -> None:
        self.gh.compare = {
            "status": "ahead",
            "ahead_by": 1,
            "behind_by": 0,
            "commits": [{"sha": "deadbeef", "commit": {"message": "board: #42"}}],
        }
        out = board_code.op_promote(self.ctx, {"kind": "production"})
        self.assertEqual(out["workflow"], "board-promote.yml")
        self.assertEqual(self.gh.dispatches[0]["body"]["ref"], "main")

    def test_poll_creates_architect_review_task(self) -> None:
        board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "Add booking.", "kind": "feature"})
        self.gh.runs.append({"name": "board-agent task-1", "status": "completed", "conclusion": "success"})
        self.gh.prs.append(_pr())
        self.gh.checks["abc123"] = _green()
        created = board_code.poll_runs(self.table, self.settings)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["assignee"], "architect")
        self.assertEqual(created[0]["eventRef"]["id"], "pr:7")
        again = board_code.poll_runs(self.table, self.settings)
        self.assertEqual(again, [])

    def test_poll_skips_review_while_ci_pending(self) -> None:
        board_code.op_run_task(self.ctx, {"issueNumber": 42, "brief": "Add booking.", "kind": "feature"})
        self.gh.runs.append({"name": "board-agent task-1", "status": "completed", "conclusion": "success"})
        self.gh.prs.append(_pr())
        self.gh.checks["abc123"] = [{"name": "ci", "status": "in_progress", "conclusion": ""}]
        self.assertEqual(board_code.poll_runs(self.table, self.settings), [])
        stored = board_code._get_run(self.table, "task-1")  # noqa: SLF001
        stored["prSeenAt"] = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        stored["ciState"] = "pending"
        board_code._put_run(self.table, "task-1", stored)  # noqa: SLF001
        created = board_code.poll_runs(self.table, self.settings)
        self.assertEqual(len(created), 1)
        self.assertIn("CI still pending after 60 min", created[0]["brief"])
        self.assertEqual(created[0]["eventRef"]["id"], "pr:7:pending-ci")
        created[0]["status"] = "delivered"
        board_store.put_task(self.table, created[0])
        board_staff._blob_put(  # noqa: SLF001
            created[0]["deliverableKey"] or board_staff._deliverable_key(created[0]["taskId"], "markdown"),
            b'```json\n{"verdict":"changes","notes":["CI still pending"]}\n```',
        )
        board_code.reset_lookup_caches_for_tests()
        self.gh.checks["abc123"] = _green()
        settled = board_code.poll_runs(self.table, self.settings)
        self.assertEqual(len(settled), 1)
        self.assertEqual(settled[0]["eventRef"]["id"], "pr:7")

    def test_assign_oldest_board_ready_when_under_two_prs(self) -> None:
        self.gh.issues = [
            {"number": 9, "title": "Older ready", "labels": [{"name": "board-ready"}]},
            {"number": 11, "title": "Newer ready", "labels": [{"name": "board-ready"}]},
        ]
        created = board_code.maybe_assign_ready_issues(self.table, self.settings)
        self.assertEqual(created[0]["eventRef"]["issueNumber"], 9)
        self.assertIn(created[0]["assignee"], ("engineer-1", "engineer-2"))

    def test_daily_tick_opens_cto_sync_when_behind(self) -> None:
        self.gh.compare = {
            "status": "diverged",
            "ahead_by": 1,
            "behind_by": 12,
            "html_url": "https://github.com/lx-software-ltd/siutindei/compare/main...staging",
            "commits": [],
        }
        out = board_code.handle_tick(self.table, self.settings)
        self.assertTrue(out["stagingSync"])
        open_tasks = board_store.list_tasks(self.table, "queued") + board_store.list_tasks(self.table, "running")
        tasks = [t for t in open_tasks if (t.get("eventRef") or {}).get("id") == "rebase-staging"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["assignee"], "cto")
        self.assertIn("12 commit", tasks[0]["brief"])
        self.assertIn("do not force-push", tasks[0]["brief"])
        again = board_code.handle_tick(self.table, self.settings)
        self.assertFalse(again["stagingSync"])
        open_again = board_store.list_tasks(self.table, "queued") + board_store.list_tasks(self.table, "running")
        self.assertEqual(
            len([t for t in open_again if (t.get("eventRef") or {}).get("id") == "rebase-staging"]),
            1,
        )

    def test_assign_falls_back_to_security_issues_without_board_ready(self) -> None:
        self.gh.issues = [
            {
                "number": 169,
                "title": "TODO: Replace with area-based filter",
                "created_at": "2026-02-09T00:00:00Z",
            },
            {
                "number": 486,
                "title": "Upgrade js-yaml",
                "labels": [{"name": "security"}, {"name": "high"}],
                "created_at": "2026-09-14T00:00:00Z",
            },
            {
                "number": 484,
                "title": "Implement dashboard",
                "created_at": "2026-09-14T00:00:00Z",
            },
            {
                "number": 485,
                "title": "Create Documentation",
                "labels": [{"name": "documentation"}],
                "created_at": "2026-09-14T00:00:00Z",
            },
        ]
        created = board_code.maybe_assign_ready_issues(self.table, self.settings)
        self.assertEqual([t["eventRef"]["issueNumber"] for t in created], [486])
        self.assertIn(board_code.BOARD_READY_LABEL, self.gh.labels)
        self.assertIn((486, [board_code.BOARD_READY_LABEL]), self.gh.issueLabels)
        again = board_code.maybe_assign_ready_issues(self.table, self.settings)
        self.assertEqual(again, [])
        self.assertEqual(self.gh.labelCreates, 1)

    def test_github_compare_and_sync_ops_are_registered(self) -> None:
        self.assertIn("github_compare", REGISTRY)
        self.assertIn("code_sync_staging", REGISTRY)
        self.assertTrue(REGISTRY["code_sync_staging"].is_write)
        out = board_github.op_compare({"base": "main", "head": "staging"})
        self.assertEqual(out["behindBy"], int(self.gh.compare.get("behind_by") or 0))
        self.assertEqual(out["aheadBy"], int(self.gh.compare.get("ahead_by") or 0))

    def test_sync_staging_merges_main_into_staging(self) -> None:
        self.gh.compare = {"status": "diverged", "ahead_by": 1, "behind_by": 12, "commits": []}
        out = board_code.op_sync_staging(self.ctx, {"reason": "Keep staging current."})
        self.assertTrue(out["ok"])
        self.assertEqual(self.gh.merges[0]["base"], "staging")
        self.assertEqual(self.gh.merges[0]["head"], "main")
        self.assertEqual(out["preview"]["behindBy"], 0)

    def test_accept_sync_task_holds_when_staging_still_behind(self) -> None:
        self.gh.compare = {"status": "diverged", "ahead_by": 1, "behind_by": 12, "commits": []}
        task = board_staff.create_task(
            self.table,
            self.settings,
            assignee="cto",
            origin="event",
            brief="sync staging",
            deliverable_type="markdown",
            event_ref={"kind": "ops", "id": "rebase-staging"},
            created_by="t",
        )
        task["status"] = "review"
        task["flags"] = []
        task["lastReview"] = {"verdict": "accept"}
        board_store.put_task(self.table, task)
        out = board_staff._accept_task(self.table, task, board_store.now_iso())  # noqa: SLF001
        self.assertEqual(out["status"], "needs_owner")
        self.assertIn("staging_behind", out.get("flags") or [])

    def test_accept_sync_task_holds_when_compare_errors(self) -> None:
        self.gh.compare = {"error": "GitHub rate limit; retry after 60s"}
        with patch.object(board_code, "staging_preview", return_value={"error": "GitHub rate limit; retry after 60s"}):
            task = board_staff.create_task(
                self.table,
                self.settings,
                assignee="cto",
                origin="event",
                brief="sync staging",
                deliverable_type="markdown",
                event_ref={"kind": "ops", "id": "rebase-staging"},
                created_by="t",
            )
            task["status"] = "review"
            task["flags"] = []
            task["lastReview"] = {"verdict": "accept"}
            board_store.put_task(self.table, task)
            out = board_staff._accept_task(self.table, task, board_store.now_iso())  # noqa: SLF001
        self.assertEqual(out["status"], "needs_owner")
        self.assertIn("staging_behind", out.get("flags") or [])
        self.assertTrue(any("could not verify" in str(q) for q in (out.get("openQuestions") or [])))

    def test_daily_tick_skips_when_staging_current(self) -> None:
        self.gh.compare = {"status": "identical", "ahead_by": 0, "behind_by": 0, "commits": []}
        out = board_code.handle_tick(self.table, self.settings)
        self.assertFalse(out["stagingSync"])
        self.assertFalse(
            any((t.get("eventRef") or {}).get("id") == "rebase-staging" for t in board_store.list_tasks(self.table, "queued"))
        )

    def test_classify_merge_and_promote(self) -> None:
        merge = REGISTRY["code_merge_staging"]
        promote = REGISTRY["code_promote"]
        self.assertEqual(board_holds.classify(merge, self.ctx, {"prNumber": 7}, self.settings), ("code_staging", "code_staging"))
        self.assertEqual(
            board_holds.classify(REGISTRY["code_sync_staging"], self.ctx, {"reason": "Keep staging current."}, self.settings),
            ("code_staging", "code_staging"),
        )
        self.assertEqual(
            board_holds.classify(REGISTRY["code_close_pr"], self.ctx, {"prNumber": 7, "reason": "Veto."}, self.settings),
            ("code_close", "code_close"),
        )
        self.assertTrue(REGISTRY["code_close_pr"].always_propose)
        self.assertTrue(REGISTRY["code_close_pr"].is_write)
        self.assertTrue(board_holds.action_class_exempt(REGISTRY["code_close_pr"]))
        self.assertEqual(REGISTRY["code_close_pr"].action_class, "code_close")

    def test_close_guard_matrix(self) -> None:
        self.assertIn("prNumber", board_code.close_guard(self.ctx, {}) or "")
        self.gh.prs.append(_pr())
        self.assertIsNone(board_code.close_guard(self.ctx, {"prNumber": 7}))

        self.gh.prs[0]["head"] = {"ref": "cursor/human-branch", "sha": "abc123"}
        self.assertIn("board/*", board_code.close_guard(self.ctx, {"prNumber": 7}) or "")
        self.gh.prs[0]["head"] = {"ref": "board/task-1", "sha": "abc123"}

        self.gh.prs[0]["base"] = {"ref": "main"}
        self.assertIn("staging", board_code.close_guard(self.ctx, {"prNumber": 7}) or "")
        self.gh.prs[0]["base"] = {"ref": "staging"}

        self.gh.prs[0]["merged"] = True
        self.assertIn("already merged", board_code.close_guard(self.ctx, {"prNumber": 7}) or "")
        self.gh.prs[0]["merged"] = False

        self.gh.prs[0]["state"] = "closed"
        self.assertIn("not open", board_code.close_guard(self.ctx, {"prNumber": 7}) or "")

    def test_close_pr_closes_board_branch_and_comments(self) -> None:
        self.gh.prs.append(_pr())
        out = board_code.op_close_pr(self.ctx, {"prNumber": 7, "reason": "Founder vetoed the merge."})
        self.assertTrue(out["ok"])
        self.assertEqual(out["state"], "closed")
        self.assertEqual(self.gh.patches[0]["body"]["state"], "closed")
        self.assertEqual(self.gh.prs[0]["state"], "closed")
        self.assertTrue(out["commented"])
        self.assertEqual(self.gh.comments[0]["number"], 7)
        self.assertIn("Founder vetoed the merge.", self.gh.comments[0]["body"])
        self.assertFalse(board_code.issue_has_open_board_pr(42, self.table))
        self.assertEqual(self.gh.writeOrder[:2], ["patch", "comment"])
        self.assertEqual([row["number"] for row in self.gh.comments], [7])

    def test_close_pr_abandons_linked_issue(self) -> None:
        self.gh.prs.append(_pr())
        self.gh.issues.append(
            {
                "number": 42,
                "title": "Update uuid",
                "labels": [{"name": "board-ready"}, {"name": "security"}],
                "created_at": "2026-09-14T00:00:00Z",
            }
        )
        out = board_code.op_close_pr(self.ctx, {"prNumber": 7, "reason": "Founder vetoed the merge."})
        self.assertEqual(out["issue"], 42)
        self.assertTrue(out["issueRelabeled"])
        self.assertTrue(out["issueCommented"])
        labels = {str(lab.get("name")) for lab in self.gh.issues[0]["labels"]}
        self.assertIn(board_code.BOARD_CLOSED_LABEL, labels)
        self.assertNotIn(board_code.BOARD_READY_LABEL, labels)
        self.assertEqual([c["number"] for c in self.gh.comments], [7, 42])
        self.assertEqual(board_code.maybe_assign_ready_issues(self.table, self.settings), [])

    def test_board_closed_label_skips_assign(self) -> None:
        self.gh.issues.append(
            {
                "number": 42,
                "title": "Update uuid",
                "labels": [{"name": "security"}, {"name": board_code.BOARD_CLOSED_LABEL}],
                "created_at": "2026-09-14T00:00:00Z",
            }
        )
        self.assertEqual(board_code.maybe_assign_ready_issues(self.table, self.settings), [])

    def test_close_pr_rejects_pending_merge_approval(self) -> None:
        self.gh.prs.append(_pr())
        merge_task = board_staff.create_task(
            self.table,
            self.settings,
            assignee="engineer-1",
            origin="event",
            brief="Architect accepted PR #7. Call code_merge_staging.",
            deliverable_type="pr",
            event_ref={"kind": "code-merge", "id": "pr:7", "prNumber": 7},
            created_by="t",
        )
        merge_ctx = ToolContext(
            self.table,
            self.settings,
            "cto",
            display_name="CTO",
            kind="task",
            task_id=str(merge_task["taskId"]),
            actor="persona",
        )
        approval = board_tools.create_approval(
            merge_ctx,
            REGISTRY["code_merge_staging"],
            {"prNumber": 7, "reason": "Merge to staging."},
            summary="Merge PR #7",
        )
        merge_task["status"] = "waiting_approval"
        merge_task["blockedOn"] = [approval["approvalId"]]
        board_store.put_task(self.table, merge_task)
        out = board_code.op_close_pr(self.ctx, {"prNumber": 7, "reason": "Founder vetoed the merge."})
        self.assertEqual(out["rejectedMergeApprovals"], 1)
        saved = board_store.get_approval(self.table, approval["approvalId"])
        self.assertEqual(saved["status"], "rejected")
        self.assertEqual(saved["decidedBySub"], "system:close-pr")
        resumed = board_store.get_task(self.table, merge_task["taskId"])
        self.assertEqual(resumed["status"], "running")

    def test_close_pr_is_always_an_approval(self) -> None:
        self.gh.prs.append(_pr())
        ctx = ToolContext(self.table, self.settings, "cto", display_name="CTO", kind="chat", actor="persona")
        out = execute_call(ctx, REGISTRY["code_close_pr"], {"prNumber": 7, "reason": "Founder vetoed the merge."})
        self.assertEqual(out.status, "pending_approval")
        self.assertEqual(self.gh.patches, [])
        pending = [a for a in board_store.list_approvals(self.table) if a.get("op") == "code_close_pr"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["preview"]["head"], "board/task-1")

    def test_close_pr_stays_approval_when_internal_holds_are_on(self) -> None:
        self.gh.prs.append(_pr())
        holds = ((self.settings.get("boundaries") or {}).get("holds") or {})
        holds["internal"] = 24
        holds["code_close"] = 24
        ctx = ToolContext(self.table, self.settings, "cto", display_name="CTO", kind="chat", actor="persona")
        hold = board_holds.maybe_hold(
            ctx, REGISTRY["code_close_pr"], {"prNumber": 7, "reason": "Veto."}, summary="Close PR #7"
        )
        self.assertIsNone(hold)
        out = execute_call(ctx, REGISTRY["code_close_pr"], {"prNumber": 7, "reason": "Founder vetoed the merge."})
        self.assertEqual(out.status, "pending_approval")
        self.assertEqual(self.gh.patches, [])

    def test_owner_approve_close_pr_executes(self) -> None:
        self.gh.prs.append(_pr())
        ctx = ToolContext(self.table, self.settings, "cto", display_name="CTO", kind="chat", actor="persona")
        queued = execute_call(ctx, REGISTRY["code_close_pr"], {"prNumber": 7, "reason": "Founder vetoed the merge."})
        self.assertEqual(queued.status, "pending_approval")
        decided = board_tools.decide_approval(
            self.table, self.settings, queued.approval_id, approve=True, owner_sub="admin-sub"
        )
        self.assertEqual(decided["status"], "executed")
        self.assertEqual(self.gh.patches[0]["body"]["state"], "closed")
        self.assertTrue((decided.get("result") or {}).get("ok"))
        self.assertEqual(self.gh.prs[0]["state"], "closed")

    def test_close_pr_refuses_without_write_token(self) -> None:
        self.gh.prs.append(_pr())
        os.environ.pop("GITHUB_READ_TOKEN", None)
        board_github.reset_token_cache_for_tests()
        with self.assertRaises(board_code.CodeError) as raised:
            board_code.op_close_pr(self.ctx, {"prNumber": 7, "reason": "Veto."})
        self.assertIn("token", str(raised.exception))
        self.assertEqual(self.gh.patches, [])

    def _deliver_accept(self, pr_number: int) -> None:
        task = board_staff.create_task(
            self.table,
            self.settings,
            assignee="architect",
            origin="event",
            brief="review",
            deliverable_type="markdown",
            event_ref={"kind": "code-review", "id": f"pr:{pr_number}", "prNumber": pr_number, "headSha": "abc123"},
            created_by="t",
            status="review",
        )
        key = board_staff._deliverable_key(str(task["taskId"]), "markdown")  # noqa: SLF001
        board_staff._blob_put(key, b'```json\n{"verdict":"accept","notes":[]}\n```')  # noqa: SLF001
        task["deliverableKey"] = key
        task["status"] = "delivered"
        board_store.put_task(self.table, task)


class PromoteAlwaysApprovalTests(ToolsTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["BOARD_STAFF_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("BOARD_STAFF_ENABLED", None))
        self.settings = _enable_staff(self.table)

    def test_persona_promote_is_always_an_approval(self) -> None:
        ctx = ToolContext(self.table, self.settings, "cto", display_name="CTO", kind="chat", actor="persona")
        out = execute_call(ctx, REGISTRY["code_promote"], {"kind": "production", "reason": "Ship Friday."})
        self.assertEqual(out.status, "pending_approval")
        pending = [a for a in board_store.list_approvals(self.table) if a.get("op") == "code_promote"]
        self.assertEqual(len(pending), 1)

    def test_review_page_queues_the_same_approval(self) -> None:
        gh = FakeActions()
        gh.compare = {
            "status": "ahead",
            "ahead_by": 1,
            "behind_by": 0,
            "commits": [{"sha": "aa", "commit": {"message": "ready"}}],
        }
        with patch.object(board_github, "_request", side_effect=gh):
            out = board_code.queue_promote_approval(self.table, self.settings, "admin-sub")
        self.assertEqual(out["approval"]["op"], "code_promote")
        self.assertEqual(out["preview"]["aheadBy"], 1)


class GithubRequestTests(unittest.TestCase):
    def test_strips_authorization_on_cross_host_redirect(self) -> None:
        req = board_github.urlrequest.Request(  # noqa: S310
            "https://api.github.com/repos/x/y/actions/jobs/1/logs",
            headers={"Authorization": "Bearer tok", "Accept": "application/vnd.github.raw"},
        )

        class _Headers(dict):
            def get_all(self, name: str, failobj: Any = None) -> Any:
                if name.lower() == "location":
                    return ["https://results.blob.core.windows.net/logs/1"]
                return failobj

        location = "https://results.blob.core.windows.net/logs/1"
        followed = board_github._StripAuthOnHostChange().redirect_request(  # noqa: SLF001
            req, None, 302, "Found", _Headers({"Location": location}), location
        )
        self.assertIsNotNone(followed)
        assert followed is not None
        self.assertNotIn("authorization", {key.lower() for key in followed.headers})

    def test_raw_accept_returns_plain_text(self) -> None:
        class _Resp:
            def __init__(self) -> None:
                self._sent = False

            def read(self, n: int = -1) -> bytes:
                if self._sent:
                    return b""
                self._sent = True
                return b"pull request changes 439 lines (max 400)\n"

            def __enter__(self) -> "_Resp":
                return self

            def __exit__(self, *_a: object) -> bool:
                return False

        class _Opener:
            def open(self, req: Any, timeout: Any = None) -> _Resp:  # noqa: ARG002
                self.accept = req.get_header("Accept")
                return _Resp()

        opener = _Opener()
        with (
            patch.object(board_github, "_token", return_value="tok"),
            patch.object(board_github, "_opener", return_value=opener),
        ):
            out = board_github._request(  # noqa: SLF001
                "GET",
                "/repos/x/y/actions/jobs/1/logs",
                accept="application/vnd.github.raw",
            )
        self.assertEqual(out, "pull request changes 439 lines (max 400)\n")
        self.assertTrue(str(opener.accept).endswith("raw"))

    def test_urlopen_patch_does_not_bypass_opener(self) -> None:
        class _Resp:
            def __init__(self) -> None:
                self._sent = False

            def read(self, n: int = -1) -> bytes:  # noqa: ARG002
                if self._sent:
                    return b""
                self._sent = True
                return b'{"ok": true}'

            def __enter__(self) -> "_Resp":
                return self

            def __exit__(self, *_a: object) -> bool:
                return False

        class _Opener:
            def open(self, req: Any, timeout: Any = None) -> _Resp:  # noqa: ARG002
                return _Resp()

        def boom(*_a: object, **_k: object) -> None:
            raise AssertionError("urlopen must not be used by _request")

        opener = _Opener()
        with (
            patch.object(board_github, "_token", return_value="tok"),
            patch.object(board_github, "_opener", return_value=opener),
            patch.object(board_github.urlrequest, "urlopen", boom),
        ):
            out = board_github._request("GET", "/repos/x/y")  # noqa: SLF001
        self.assertEqual(out, {"ok": True})


if __name__ == "__main__":
    unittest.main()
