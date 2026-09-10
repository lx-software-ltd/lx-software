"""Unit tests for the engineering runner (WP10)."""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import patch

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
    return board_store.save_settings(table, settings)


class FakeActions:
    """Scripted GitHub REST for runner / PR / CI / compare calls."""

    def __init__(self) -> None:
        self.dispatches: list[dict[str, Any]] = []
        self.prs: list[dict[str, Any]] = []
        self.files: dict[int, list[dict[str, Any]]] = {}
        self.checks: dict[str, list[dict[str, Any]]] = {}
        self.runs: list[dict[str, Any]] = []
        self.issues: list[dict[str, Any]] = []
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
            return list(self.prs)
        if method == "GET" and "/pulls?head=" in path:
            head = path.split("head=", 1)[1].split("&", 1)[0]
            ref = head.split(":", 1)[-1]
            return [p for p in self.prs if ((p.get("head") or {}).get("ref") or "") == ref]
        if method == "GET" and "/pulls/" in path and path.endswith("/files?per_page=100"):
            number = int(path.split("/pulls/", 1)[1].split("/", 1)[0])
            return list(self.files.get(number) or [])
        if method == "GET" and "/pulls/" in path:
            number = int(path.rstrip("/").rsplit("/", 1)[-1].split("?")[0])
            return next((p for p in self.prs if p.get("number") == number), None)
        if method == "GET" and path.endswith("/actions/runs?per_page=30"):
            return {"workflow_runs": list(self.runs)}
        if method == "GET" and "/check-runs" in path:
            sha = path.split("/commits/", 1)[1].split("/", 1)[0]
            return {"check_runs": list(self.checks.get(sha) or [])}
        if method == "GET" and path.endswith("/status"):
            return {"state": "pending"}
        if method == "GET" and "/issues?" in path:
            return list(self.issues)
        if method == "GET" and "/compare/" in path:
            return self.compare
        return {}


def _pr(number: int = 7, *, issue: int = 42, base: str = "staging", sha: str = "abc123") -> dict[str, Any]:
    return {
        "number": number,
        "title": f"board: #{issue} add booking",
        "body": f"Implements #{issue}\n\nTask: task-1",
        "draft": True,
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
        self.settings = _enable_staff(self.table)
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

    def test_get_run_matches_task_id_in_run_name(self) -> None:
        self.gh.runs.append({"name": "board-agent task-1", "status": "completed", "conclusion": "success", "html_url": "https://example/run"})
        self.gh.prs.append(_pr())
        out = board_code.op_get_run(self.ctx, {"taskId": "task-1"})
        self.assertEqual(out["prNumber"], 7)
        self.assertEqual(out["conclusion"], "success")

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
        out = board_code.op_merge_staging(self.ctx, {"prNumber": 7})
        self.assertEqual(out["workflow"], "board-merge-staging.yml")
        self.assertEqual(self.gh.dispatches[0]["body"]["inputs"]["pr_number"], "7")

    def test_promote_refuses_when_staging_behind(self) -> None:
        self.gh.compare = {"status": "behind", "ahead_by": 0, "behind_by": 3, "commits": []}
        out = board_code.op_promote(self.ctx, {"kind": "production"})
        self.assertIn("behind", out["error"])
        tasks = board_store.list_tasks(self.table, "needs_owner")
        self.assertTrue(any((t.get("eventRef") or {}).get("id") == "rebase-staging" for t in tasks))
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
        created = board_code.poll_runs(self.table, self.settings)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["assignee"], "architect")
        self.assertEqual(created[0]["eventRef"]["id"], "pr:7")
        again = board_code.poll_runs(self.table, self.settings)
        self.assertEqual(again, [])

    def test_assign_oldest_board_ready_when_under_two_prs(self) -> None:
        self.gh.issues = [
            {"number": 9, "title": "Older ready", "pull_request": None},
            {"number": 11, "title": "Newer ready"},
        ]
        created = board_code.maybe_assign_ready_issues(self.table, self.settings)
        self.assertEqual(created[0]["eventRef"]["issueNumber"], 9)
        self.assertIn(created[0]["assignee"], ("engineer-1", "engineer-2"))

    def test_classify_merge_and_promote(self) -> None:
        merge = REGISTRY["code_merge_staging"]
        promote = REGISTRY["code_promote"]
        self.assertEqual(board_holds.classify(merge, self.ctx, {"prNumber": 7}, self.settings), ("code_staging", "code_staging"))
        self.assertEqual(board_holds.classify(promote, self.ctx, {"kind": "production"}, self.settings), ("code_production", "code_production"))

    def _deliver_accept(self, pr_number: int) -> None:
        task = board_staff.create_task(
            self.table,
            self.settings,
            assignee="architect",
            origin="event",
            brief="review",
            deliverable_type="markdown",
            event_ref={"kind": "code-review", "id": f"pr:{pr_number}", "prNumber": pr_number},
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


if __name__ == "__main__":
    unittest.main()
