"""Unit tests for Executive Board tools: levels, loop, approvals, GitHub ops."""

from __future__ import annotations

import io
import json
import os
import unittest
from typing import Any
from unittest.mock import patch
from urllib import error as urlerror

from test_board import BoardTestCase, _FakeResp, _completion  # noqa: E402

import board_github  # noqa: E402
import board_store  # noqa: E402
import board_tools  # noqa: E402
import openrouter_client  # noqa: E402
from board_routes import validate_tools_config  # noqa: E402


def _tool_call_completion(calls: list[tuple[str, dict[str, Any]]], text: str = "") -> bytes:
    return json.dumps(
        {
            "model": "test/model",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": text or None,
                        "tool_calls": [
                            {
                                "id": f"call_{i}",
                                "type": "function",
                                "function": {"name": name, "arguments": json.dumps(args)},
                            }
                            for i, (name, args) in enumerate(calls)
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100, "cost": 0.005},
        }
    ).encode("utf-8")


class ScriptedOpenRouter:
    """Returns tool calls until the script is exhausted, then the final text."""

    def __init__(self, script: list[list[tuple[str, dict[str, Any]]]], final_text: str = "Done. Here is what I found.") -> None:
        self.script = list(script)
        self.final_text = final_text
        self.requests: list[dict[str, Any]] = []

    def __call__(self, req, timeout=None):  # noqa: ARG002
        body = json.loads(req.data.decode("utf-8"))
        self.requests.append(body)
        if body.get("tool_choice") == "none" or not body.get("tools") or not self.script:
            return _FakeResp(_completion(self.final_text))
        return _FakeResp(_tool_call_completion(self.script.pop(0)))


class FakeGitHub:
    """Minimal GitHub REST fake keyed on method + path."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, str], Any]] = []
        self.fail_with: int | None = None

    def __call__(self, req, timeout=None):  # noqa: ARG002
        path = req.full_url.replace(board_github.API_ORIGIN, "")
        body = json.loads(req.data.decode("utf-8")) if req.data else None
        self.requests.append((req.get_method(), path, dict(req.headers), body))
        if self.fail_with:
            raise urlerror.HTTPError(req.full_url, self.fail_with, "boom", {}, io.BytesIO(b'{"message":"nope"}'))
        if path.startswith("/search/issues"):
            payload: Any = {
                "total_count": 1,
                "items": [
                    {"number": 42, "title": "Booking flow crashes", "state": "open", "labels": [{"name": "bug"}], "user": {"login": "lx"}, "comments": 2, "html_url": "https://github.com/x/42"}
                ],
            }
        elif path.startswith("/repos/") and path.endswith("/issues") and req.get_method() == "POST":
            payload = {"number": 99, "html_url": "https://github.com/x/99"}
        elif "/comments" in path and req.get_method() == "POST":
            payload = {"id": 7, "html_url": "https://github.com/x/42#7"}
        elif "/labels" in path and req.get_method() == "PUT":
            payload = [{"name": lb} for lb in (body or {}).get("labels", [])]
        elif "/issues/42/comments" in path:
            payload = [{"user": {"login": "lx"}, "created_at": "2026-09-01T00:00:00Z", "body": "Repro attached"}]
        elif "/issues/42" in path:
            payload = {"number": 42, "title": "Booking flow crashes", "state": "open", "body": "Steps...", "labels": [], "user": {"login": "lx"}, "assignees": []}
        elif "/contents/" in path:
            import base64

            payload = {"size": 11, "content": base64.b64encode(b"# siutindei").decode(), "html_url": "u"}
        elif "/actions/runs" in path:
            payload = {"workflow_runs": [{"id": 1, "name": "ci", "head_branch": "main", "status": "completed", "conclusion": "success", "head_commit": {"message": "fix: x\n\nmore"}}]}
        elif "/dependabot/alerts" in path:
            raise urlerror.HTTPError(req.full_url, 403, "forbidden", {}, io.BytesIO(b'{"message":"Dependabot alerts are disabled"}'))
        elif "/code-scanning/alerts" in path:
            payload = []
        else:
            payload = {}
        return _FakeResp(json.dumps(payload).encode("utf-8"))


class HostRouter:
    """``urllib.request.urlopen`` is one global; route by host to the right fake."""

    def __init__(self, openrouter: Any, github: Any) -> None:
        self.openrouter = openrouter
        self.github = github

    def __call__(self, req, timeout=None):
        if req.full_url.startswith(board_github.API_ORIGIN):
            return self.github(req, timeout)
        return self.openrouter(req, timeout)


class ToolsTestCase(BoardTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.github = FakeGitHub()
        self.router = HostRouter(self.openrouter, self.github)
        patcher = patch("urllib.request.urlopen", self.router)
        patcher.start()
        self.addCleanup(patcher.stop)
        board_github.reset_token_cache_for_tests()
        os.environ.pop("GITHUB_READ_TOKEN", None)
        os.environ.pop("BOARD_TOOLS_ENABLED", None)

    def use_script(self, script: list[list[tuple[str, dict[str, Any]]]], final_text: str = "Done.") -> ScriptedOpenRouter:
        scripted = ScriptedOpenRouter(script, final_text)
        self.router.openrouter = scripted
        return scripted

    def chat(self, persona: str, text: str = "hi") -> dict[str, Any]:
        status, body = self.call(f"/siu-tin-dei/board/chat/{persona}", "POST", {"text": text})
        self.assertEqual(status, 202)
        status, job = self.call(f"/siu-tin-dei/board/chat/{persona}/jobs/{body['jobId']}")
        self.assertEqual(status, 200)
        return job

    def propose_issue(self) -> dict[str, Any]:
        self.use_script(
            [[("github_create_issue", {"title": "Add FPS reference to invoices", "body": "Details", "labels": ["billing"], "reason": "Needed for receivables."})]],
            "I have proposed a new issue; it awaits your approval.",
        )
        job = self.chat("cto", "Please open an issue for FPS references")
        call = job["message"]["toolCalls"][0]
        self.assertEqual(call["status"], "pending_approval")
        self.assertTrue(call["approvalId"])
        self.assertEqual([r[0] for r in self.github.requests], [], "nothing must reach GitHub at propose level")
        status, body = self.call("/siu-tin-dei/board/approvals", query="status=pending")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["approvals"]), 1)
        approval = body["approvals"][0]
        self.assertEqual(approval["op"], "github_create_issue")
        self.assertEqual(approval["personaId"], "cto")
        self.assertEqual(approval["reason"], "Needed for receivables.")
        self.assertEqual(approval["arguments"]["labels"], ["billing"])
        _, overview = self.call("/siu-tin-dei/board")
        self.assertEqual(overview["pendingApprovalCount"], 1)
        return approval


# ---------------------------------------------------------------------------
# Levels and registry
# ---------------------------------------------------------------------------

class TestLevels(unittest.TestCase):
    def test_global_mode_caps_configured_level(self) -> None:
        settings = board_store.default_settings()
        self.assertEqual(board_tools.configured_level(settings, "github", "cto"), "act")
        self.assertEqual(board_tools.effective_level(settings, "github", "cto"), "propose")
        self.assertEqual(board_tools.effective_level(settings, "github", "cfo"), "off")
        settings["tools"]["globalMode"] = "readOnly"
        self.assertEqual(board_tools.effective_level(settings, "github", "cto"), "read")
        self.assertEqual(board_tools.effective_level(settings, "board", "cmo"), "read")
        settings["tools"]["globalMode"] = "act"
        self.assertEqual(board_tools.effective_level(settings, "github", "cto"), "act")
        settings["tools"]["enabled"] = False
        self.assertEqual(board_tools.effective_level(settings, "github", "cto"), "off")

    def test_env_kill_switch(self) -> None:
        settings = board_store.default_settings()
        with patch.dict("os.environ", {"BOARD_TOOLS_ENABLED": "false"}):
            self.assertFalse(board_tools.tools_enabled(settings))
            self.assertEqual(board_tools.available_ops(settings, "cto", context="chat"), [])
        with patch.dict("os.environ", {"BOARD_TOOLS_ENABLED": "true"}):
            self.assertTrue(board_tools.tools_enabled(settings))

    def test_available_ops_by_level_and_context(self) -> None:
        settings = board_store.default_settings()
        cto_chat = {op.name: lvl for op, lvl in board_tools.available_ops(settings, "cto", context="chat")}
        self.assertIn("github_search_issues", cto_chat)
        self.assertIn("github_create_issue", cto_chat)
        self.assertEqual(cto_chat["github_create_issue"], "propose")
        self.assertIn("board_add_action", cto_chat)
        cto_meeting = {op.name for op, _ in board_tools.available_ops(settings, "cto", context="meeting")}
        self.assertIn("github_get_file", cto_meeting)
        self.assertIn("board_add_action", cto_meeting)
        self.assertIn("board_update_action", cto_meeting)
        cfo_chat = {op.name for op, _ in board_tools.available_ops(settings, "cfo", context="chat")}
        self.assertFalse(any(n.startswith("github_") for n in cfo_chat))
        self.assertIn("board_list_actions", cfo_chat)
        ceo_chat = {op.name for op, _ in board_tools.available_ops(settings, "ceo", context="chat")}
        self.assertIn("github_search_issues", ceo_chat)
        self.assertNotIn("github_create_issue", ceo_chat, "read level must not expose writes")

    def test_normalize_tools_config_clamps_and_drops_unknowns(self) -> None:
        out = board_store.normalize_tools_config(
            {"globalMode": "bogus", "matrix": {"github": {"cfo": "act", "intern": "act"}, "slack": {"ceo": "act"}}}
        )
        self.assertEqual(out["globalMode"], "propose")
        self.assertEqual(out["matrix"]["github"]["cfo"], "act")
        self.assertNotIn("intern", out["matrix"]["github"])
        self.assertNotIn("slack", out["matrix"])

    def test_validate_tools_config_rejects_bad_input(self) -> None:
        current = board_store.default_tools_config()
        with self.assertRaises(ValueError):
            validate_tools_config({"globalMode": "yolo"}, current)
        with self.assertRaises(ValueError):
            validate_tools_config({"matrix": {"slack": {"ceo": "read"}}}, current)
        with self.assertRaises(ValueError):
            validate_tools_config({"matrix": {"github": {"intern": "read"}}}, current)
        with self.assertRaises(ValueError):
            validate_tools_config({"matrix": {"github": {"ceo": "root"}}}, current)
        out = validate_tools_config({"globalMode": "act", "matrix": {"github": {"cfo": "read"}}}, current)
        self.assertEqual(out["globalMode"], "act")
        self.assertEqual(out["matrix"]["github"]["cfo"], "read")
        self.assertEqual(out["matrix"]["github"]["cto"], "act", "untouched cells keep their value")

    def test_registry_schemas_are_openai_shaped(self) -> None:
        for op in board_tools.REGISTRY.values():
            schema = op.schema()
            self.assertEqual(schema["type"], "function")
            self.assertEqual(schema["function"]["parameters"]["type"], "object")
            if op.is_write:
                self.assertIn("reason", schema["function"]["parameters"]["properties"])
        registry = board_tools.public_registry()
        self.assertEqual(
            [t["id"] for t in registry],
            ["github", "board", "mail", "research", "aws", "security", "product", "meta", "finance", "stores", "staff", "web"],
        )
        self.assertTrue(all(t["operations"] for t in registry))


class TestToolCallParsing(unittest.TestCase):
    def test_extract_tool_calls_handles_string_dict_and_bad_json(self) -> None:
        raw = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {"id": "a", "type": "function", "function": {"name": "x", "arguments": "{\"n\": 1}"}},
                            {"id": "b", "type": "function", "function": {"name": "y", "arguments": {"k": "v"}}},
                            {"id": "c", "type": "function", "function": {"name": "z", "arguments": "{not json"}},
                            {"id": "d", "type": "function", "function": {"arguments": "{}"}},
                        ],
                    }
                }
            ]
        }
        calls = openrouter_client.extract_tool_calls(raw)
        self.assertEqual([c.name for c in calls], ["x", "y", "z"])
        self.assertEqual(calls[0].arguments, {"n": 1})
        self.assertEqual(calls[1].arguments, {"k": "v"})
        self.assertEqual(calls[2].arguments, {})
        entry = calls[1].as_message_entry()
        self.assertEqual(json.loads(entry["function"]["arguments"]), {"k": "v"})
        self.assertEqual(openrouter_client.extract_message_text(raw), "")

    def test_chat_completion_sends_tools_and_requires_parameter_support(self) -> None:
        seen: list[dict[str, Any]] = []

        def fake_urlopen(req, timeout=None):  # noqa: ARG001
            seen.append(json.loads(req.data.decode("utf-8")))
            return _FakeResp(_tool_call_completion([("github_get_issue", {"number": 1})]))

        with patch("openrouter_client.urlrequest.urlopen", fake_urlopen), patch.dict("os.environ", {"OPENROUTER_API_KEY": "k"}):
            openrouter_client.reset_api_key_cache_for_tests()
            completion = openrouter_client.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                model="m",
                secrets_client=None,
                timeout=5,
                tools=[{"type": "function", "function": {"name": "github_get_issue", "parameters": {"type": "object"}}}],
                tool_choice="auto",
            )
        self.assertEqual(seen[0]["provider"], {"data_collection": "deny", "require_parameters": True})
        self.assertEqual(seen[0]["tool_choice"], "auto")
        self.assertEqual(completion.finish_reason, "tool_calls")
        self.assertEqual(completion.tool_calls[0].name, "github_get_issue")
        self.assertIsNone(completion.assistant_message()["content"])


# ---------------------------------------------------------------------------
# Chat loop
# ---------------------------------------------------------------------------

class TestChatToolLoop(ToolsTestCase):
    def test_read_tool_round_trip(self) -> None:
        scripted = self.use_script([[("github_search_issues", {"query": "booking", "state": "open"})]], "Issue #42 is the blocker.")
        job = self.chat("cto", "What is blocking the booking flow?")
        self.assertEqual(job["status"], "succeeded")
        message = job["message"]
        self.assertEqual(message["text"], "Issue #42 is the blocker.")
        self.assertEqual(len(message["toolCalls"]), 1)
        call = message["toolCalls"][0]
        self.assertEqual(call["op"], "github_search_issues")
        self.assertEqual(call["status"], "ok")
        self.assertEqual(call["toolLabel"], "GitHub")
        self.assertIn("booking", call["summary"])
        # Two model rounds: one requesting the tool, one answering with the result in context.
        self.assertEqual(len(scripted.requests), 2)
        first, second = scripted.requests
        self.assertTrue(any(t["function"]["name"] == "github_search_issues" for t in first["tools"]))
        self.assertEqual(second["messages"][-1]["role"], "tool")
        self.assertIn("Booking flow crashes", second["messages"][-1]["content"])
        self.assertEqual(second["messages"][-2]["tool_calls"][0]["function"]["name"], "github_search_issues")
        self.assertIn("TOOLS:", second["messages"][2]["content"])
        self.assertIn("CONTEXT DATA", second["messages"][1]["content"])
        # Anonymous GitHub read: no Authorization header, public repo.
        method, path, headers, _ = self.github.requests[0]
        self.assertEqual(method, "GET")
        self.assertIn("repo%3Alx-software-ltd/siutindei", path)
        self.assertNotIn("Authorization", headers)
        # Usage accumulates over both rounds and the audit row is written.
        self.assertAlmostEqual(message["usage"]["cost"], 0.015)
        status, log = self.call("/siu-tin-dei/board/tools/calls")
        self.assertEqual(status, 200)
        self.assertEqual(log["calls"][0]["op"], "github_search_issues")
        self.assertEqual(log["calls"][0]["context"]["kind"], "chat")
        self.assertEqual(log["calls"][0]["actor"], "persona")

    def test_progress_is_visible_while_job_runs(self) -> None:
        seen: list[list[dict[str, Any]]] = []
        original = board_store.put_chat_job

        def spy(table, doc):
            if doc.get("status") == "processing" and doc.get("toolCalls"):
                seen.append(doc["toolCalls"])
            return original(table, doc)

        self.use_script([[("github_list_workflow_runs", {"limit": 5})]])
        with patch("board_chat.board_store.put_chat_job", spy):
            self.chat("cto")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0]["op"], "github_list_workflow_runs")

    def test_member_without_tools_gets_plain_completion(self) -> None:
        self.call(
            "/siu-tin-dei/board/tools",
            "PUT",
            {
                "matrix": {
                    "board": {"cfo": "off"},
                    "mail": {"cfo": "off"},
                    "research": {"cfo": "off"},
                    "aws": {"cfo": "off"},
                    "product": {"cfo": "off"},
                    "meta": {"cfo": "off"},
                    "finance": {"cfo": "off"},
                }
            },
        )
        scripted = self.use_script([[("github_search_issues", {"query": "x"})]], "Plain answer.")
        job = self.chat("cfo")
        self.assertEqual(job["message"]["text"], "Plain answer.")
        self.assertNotIn("toolCalls", job["message"])
        self.assertNotIn("tools", scripted.requests[0])

    def test_unknown_tool_and_error_results_do_not_break_reply(self) -> None:
        self.github.fail_with = 500
        scripted = self.use_script(
            [[("github_get_issue", {"number": 42}), ("not_a_tool", {})]], "Could not check GitHub right now."
        )
        job = self.chat("cto")
        self.assertEqual(job["status"], "succeeded")
        calls = job["message"]["toolCalls"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["status"], "error")
        self.assertIn("500", calls[0]["error"])
        tool_msgs = [m for m in scripted.requests[1]["messages"] if m["role"] == "tool"]
        self.assertEqual(len(tool_msgs), 2)
        self.assertIn("Unknown tool", tool_msgs[1]["content"])

    def test_round_cap_forces_final_answer(self) -> None:
        endless = [[("github_list_pull_requests", {"state": "open"})] for _ in range(10)]
        scripted = self.use_script(endless, "Final after cap.")
        job = self.chat("cto")
        self.assertEqual(job["message"]["text"], "Final after cap.")
        self.assertEqual(len(job["message"]["toolCalls"]), board_tools.BOARD_MAX_TOOL_ROUNDS_PER_TURN)
        self.assertEqual(scripted.requests[-1]["tool_choice"], "none")
        self.assertEqual(len(scripted.requests), board_tools.BOARD_MAX_TOOL_ROUNDS_PER_TURN + 1)

    def test_call_cap_per_reply(self) -> None:
        many = [("github_get_issue", {"number": n}) for n in range(1, 12)]
        scripted = self.use_script([many], "ok")
        job = self.chat("cto")
        self.assertEqual(len(job["message"]["toolCalls"]), board_tools.BOARD_MAX_TOOL_CALLS_PER_TURN)
        tool_msgs = [m for m in scripted.requests[1]["messages"] if m["role"] == "tool"]
        self.assertEqual(len(tool_msgs), 11)
        self.assertIn("budget", tool_msgs[-1]["content"].lower())

    def test_write_at_propose_level_creates_approval(self) -> None:
        self.propose_issue()

    def test_approve_executes_as_owner(self) -> None:
        approval = self.propose_issue()
        with patch.dict("os.environ", {"GITHUB_READ_TOKEN": "ghp_test"}):
            board_github.reset_token_cache_for_tests()
            status, body = self.call(
                f"/siu-tin-dei/board/approvals/{approval['approvalId']}/approve",
                "POST",
                {"note": "Go ahead", "arguments": {"title": "Add FPS reference to invoices (edited)"}},
            )
        self.assertEqual(status, 200)
        self.assertEqual(body["approval"]["status"], "executed")
        self.assertEqual(body["approval"]["result"]["number"], 99)
        self.assertEqual(body["approval"]["arguments"]["title"], "Add FPS reference to invoices (edited)")
        method, path, headers, sent = self.github.requests[-1]
        self.assertEqual((method, path), ("POST", "/repos/lx-software-ltd/siutindei/issues"))
        self.assertEqual(headers["Authorization"], "Bearer ghp_test")
        self.assertEqual(sent["title"], "Add FPS reference to invoices (edited)")
        _, log = self.call("/siu-tin-dei/board/tools/calls")
        owner_call = next(c for c in log["calls"] if c["actor"] == "owner")
        self.assertEqual(owner_call["status"], "ok")
        self.assertEqual(owner_call["ownerSub"], "admin-sub")
        # A second decision on the same approval is refused.
        status, _ = self.call(f"/siu-tin-dei/board/approvals/{approval['approvalId']}/reject", "POST", {})
        self.assertEqual(status, 409)

    def test_approve_without_write_token_fails_cleanly(self) -> None:
        approval = self.propose_issue()
        status, body = self.call(f"/siu-tin-dei/board/approvals/{approval['approvalId']}/approve", "POST", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["approval"]["status"], "failed")
        self.assertIn("token", body["approval"]["errorMessage"].lower())

    def test_reject_feeds_back_into_context_pack(self) -> None:
        approval = self.propose_issue()
        status, body = self.call(
            f"/siu-tin-dei/board/approvals/{approval['approvalId']}/reject", "POST", {"note": "Not before launch."}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["approval"]["status"], "rejected")
        scripted = self.use_script([], "Understood.")
        self.chat("ceo")
        pack = scripted.requests[0]["messages"][1]["content"]
        self.assertIn("Proposals the founder rejected", pack)
        self.assertIn("Not before launch.", pack)
        status, _ = self.call("/siu-tin-dei/board/approvals/nope/approve", "POST", {})
        self.assertEqual(status, 404)

    def test_pending_proposals_are_shown_to_the_board(self) -> None:
        self.propose_issue()
        scripted = self.use_script([], "Noted.")
        self.chat("cpo")
        pack = scripted.requests[0]["messages"][1]["content"]
        self.assertIn("awaiting the founder's approval", pack)
        self.assertIn("Add FPS reference to invoices", pack)

    def test_write_at_act_level_executes_immediately(self) -> None:
        status, body = self.call("/siu-tin-dei/board/tools", "PUT", {"globalMode": "act"})
        self.assertEqual(status, 200)
        self.assertEqual(body["effective"]["github"]["cto"], "act")
        self.assertEqual(body["effective"]["github"]["cpo"], "propose")
        self.use_script([[("github_comment_issue", {"number": 42, "body": "On it.", "reason": "Unblock."})]], "Commented.")
        with patch.dict("os.environ", {"GITHUB_READ_TOKEN": "ghp_test"}):
            board_github.reset_token_cache_for_tests()
            job = self.chat("cto")
        call = job["message"]["toolCalls"][0]
        self.assertEqual(call["status"], "ok")
        self.assertEqual(self.github.requests[-1][:2], ("POST", "/repos/lx-software-ltd/siutindei/issues/42/comments"))
        _, approvals = self.call("/siu-tin-dei/board/approvals")
        self.assertEqual(approvals["approvals"], [])

    def test_read_only_mode_hides_writes(self) -> None:
        self.call("/siu-tin-dei/board/tools", "PUT", {"globalMode": "readOnly"})
        scripted = self.use_script([], "ok")
        self.chat("cto")
        names = {t["function"]["name"] for t in scripted.requests[0]["tools"]}
        self.assertIn("github_search_issues", names)
        self.assertFalse(any(n in names for n in ("github_create_issue", "github_comment_issue", "board_add_action")))
        self.assertNotIn("RECORD A PROPOSAL", scripted.requests[0]["messages"][2]["content"])

    def test_disabled_tools_switch(self) -> None:
        self.call("/siu-tin-dei/board/tools", "PUT", {"enabled": False})
        scripted = self.use_script([[("github_search_issues", {"query": "x"})]], "ok")
        self.chat("cto")
        self.assertNotIn("tools", scripted.requests[0])
        _, overview = self.call("/siu-tin-dei/board")
        self.assertFalse(overview["toolsEnabled"])


class TestBoardTools(ToolsTestCase):
    def test_add_action_owned_by_member_and_duplicate_rejected(self) -> None:
        self.call("/siu-tin-dei/board/tools", "PUT", {"globalMode": "act"})
        self.use_script(
            [[("board_add_action", {"title": "Open the HKD business account", "detail": "Compare Airwallex and Statrys.", "priority": "now", "effort": "M", "dueInDays": 14, "metric": "Account live", "reason": "Receivables need it."})]],
            "Added.",
        )
        job = self.chat("cfo")
        self.assertEqual(job["message"]["toolCalls"][0]["status"], "ok")
        _, actions = self.call("/siu-tin-dei/board/actions")
        self.assertEqual(len(actions["actions"]), 1)
        action = actions["actions"][0]
        self.assertEqual(action["persona"], "cfo")
        self.assertEqual(action["priority"], "now")
        self.assertEqual(action["source"], "tool")
        self.assertTrue(action["dueAt"])
        scripted = self.use_script([[("board_add_action", {"title": "Open the HKD business account!", "detail": "d", "priority": "next", "reason": "r"})]], "ok")
        self.chat("cfo")
        _, actions = self.call("/siu-tin-dei/board/actions")
        self.assertEqual(len(actions["actions"]), 1)
        self.assertIn("duplicateOf", scripted.requests[1]["messages"][-1]["content"])

    def test_update_action_only_own(self) -> None:
        self.call("/siu-tin-dei/board/tools", "PUT", {"globalMode": "act"})
        self.use_script([[("board_add_action", {"title": "Draft pricing tiers", "detail": "d", "priority": "next", "reason": "r"})]], "ok")
        self.chat("cfo")
        action_id = self.call("/siu-tin-dei/board/actions")[1]["actions"][0]["actionId"]
        scripted = self.use_script([[("board_update_action", {"actionId": action_id, "status": "done", "reason": "r"})]], "ok")
        self.chat("cto")
        self.assertIn("only update actions you own", scripted.requests[1]["messages"][-1]["content"])
        self.use_script([[("board_update_action", {"actionId": action_id, "status": "done", "note": "Tiers drafted.", "reason": "r"})]], "ok")
        self.chat("cfo")
        action = self.call("/siu-tin-dei/board/actions")[1]["actions"][0]
        self.assertEqual(action["status"], "done")
        self.assertIn("[CFO] Tiers drafted.", action["note"])

    def test_board_reads(self) -> None:
        self.call("/siu-tin-dei/board/meetings", "POST", {"mode": "standup"})
        scripted = self.use_script(
            [[("board_list_actions", {"status": "open"}), ("board_get_minutes", {}), ("board_list_meetings", {"limit": 5}), ("board_search_decisions", {"query": "beta"})]],
            "ok",
        )
        self.chat("coo")
        tool_msgs = [json.loads(m["content"]) for m in scripted.requests[-1]["messages"] if m["role"] == "tool"]
        self.assertEqual(tool_msgs[0]["count"], 5)
        self.assertEqual(tool_msgs[1]["minutes"]["headline"], "Ship a closed beta in six weeks.")
        self.assertEqual(len(tool_msgs[2]["items"]), 1)
        self.assertEqual(tool_msgs[3]["count"], 1)


# ---------------------------------------------------------------------------
# Meetings
# ---------------------------------------------------------------------------

class MeetingScriptedOpenRouter:
    """The regular meeting fake, plus one tool call for the CTO's position."""

    def __init__(self) -> None:
        from test_board import FakeOpenRouter

        self.inner = FakeOpenRouter()
        self.requests = self.inner.requests
        self.cto_tool_done = False

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        system = body["messages"][0]["content"]
        user = next((m["content"] for m in reversed(body["messages"]) if m["role"] == "user"), "")
        if (
            "For EACH agenda item" in user
            and "Chief Technology Officer" in system
            and body.get("tools")
            and body.get("tool_choice") != "none"
            and not any(m["role"] == "tool" for m in body["messages"])
        ):
            self.requests.append(body)
            return _FakeResp(_tool_call_completion([("github_list_workflow_runs", {"limit": 3})]))
        return self.inner(req, timeout)


class TestMeetingTools(ToolsTestCase):
    def test_position_tool_calls_become_transcript_entries(self) -> None:
        scripted = MeetingScriptedOpenRouter()
        self.router.openrouter = scripted
        status, body = self.call("/siu-tin-dei/board/meetings", "POST", {"mode": "standup"})
        self.assertEqual(status, 202)
        _, body = self.call(f"/siu-tin-dei/board/meetings/{body['meetingId']}")
        self.assertEqual(body["meeting"]["status"], "succeeded")
        turns = body["turns"]
        tool_turns = [t for t in turns if t.get("kind") == "tool"]
        self.assertEqual(len(tool_turns), 1)
        self.assertEqual(tool_turns[0]["personaId"], "cto")
        self.assertEqual(tool_turns[0]["phase"], "positions")
        self.assertEqual(tool_turns[0]["data"]["calls"][0]["op"], "github_list_workflow_runs")
        self.assertIn("Checked CI runs", tool_turns[0]["text"])
        positions = [t for t in turns if t["phase"] == "positions" and t.get("kind") != "tool"]
        self.assertEqual(len(positions), 8)
        # The tool turn precedes the CTO's position and the position phase still produced 8 statements.
        cto_index = next(i for i, t in enumerate(turns) if t["personaId"] == "cto" and t["phase"] == "positions" and t.get("kind") != "tool")
        self.assertEqual(turns[cto_index - 1]["kind"], "tool")
        # Members were offered only meeting-context operations.
        position_requests = [r for r in scripted.requests if "For EACH agenda item" in r["messages"][-1]["content"] and r.get("tools")]
        offered = {t["function"]["name"] for r in position_requests for t in r["tools"]}
        self.assertIn("board_add_action", offered)
        # The synthesis prompt does not include the tool-turn text.
        synthesis = next(r for r in scripted.requests if "Write the minutes" in r["messages"][-1]["content"])
        self.assertNotIn("Checked CI runs", synthesis["messages"][-1]["content"])
        _, log = self.call("/siu-tin-dei/board/tools/calls")
        self.assertEqual(log["calls"][0]["context"]["kind"], "meeting")
        self.assertEqual(log["calls"][0]["context"]["phase"], "positions")


# ---------------------------------------------------------------------------
# GitHub operations
# ---------------------------------------------------------------------------

class TestGitHubOps(ToolsTestCase):
    def test_get_file_and_issue_and_runs(self) -> None:
        out = board_github.op_get_file({"path": "README.md"})
        self.assertEqual(out["text"], "# siutindei")
        self.assertEqual(out["type"], "file")
        with self.assertRaises(board_github.GitHubSnapshotError):
            board_github.op_get_file({"path": "../etc/passwd"})
        issue = board_github.op_get_issue({"number": 42})
        self.assertEqual(issue["title"], "Booking flow crashes")
        self.assertEqual(issue["recentComments"][0]["body"], "Repro attached")
        runs = board_github.op_list_workflow_runs({"limit": 3})
        self.assertEqual(runs["items"][0]["commitMessage"], "fix: x")
        with self.assertRaises(board_github.GitHubSnapshotError):
            board_github.op_get_issue({"number": "abc"})

    def test_security_alerts_report_missing_access(self) -> None:
        out = board_github.op_list_security_alerts({})
        self.assertEqual(out["dependabot"], [])
        self.assertTrue(any("403" in n for n in out["notes"]))
        self.assertEqual(out["codeScanning"], [])

    def test_writes_require_token(self) -> None:
        with self.assertRaises(board_github.GitHubSnapshotError) as ctx:
            board_github.op_create_issue({"title": "t", "body": "b"})
        self.assertIn("token", str(ctx.exception))
        self.assertEqual(self.github.requests, [])
        with patch.dict("os.environ", {"GITHUB_READ_TOKEN": "ghp_x"}):
            board_github.reset_token_cache_for_tests()
            out = board_github.op_set_labels({"number": 42, "labels": ["bug", "bug", " P1 "]})
        self.assertEqual(out["labels"], ["bug", "P1"])
        self.assertEqual(self.github.requests[-1][3], {"labels": ["bug", "P1"]})

    def test_snapshot_is_enabled_without_token(self) -> None:
        self.assertTrue(board_github.snapshot_enabled())
        self.assertFalse(board_github.write_enabled())
        _, overview = self.call("/siu-tin-dei/board")
        self.assertTrue(overview["repoSnapshotEnabled"])
        self.assertFalse(overview["repoWriteEnabled"])

    def test_search_stays_in_repo_and_strips_scope_qualifiers(self) -> None:
        out = board_github.op_search_issues({"query": "booking REPO:evil/other org:acme user:bob label:bug"})
        self.assertEqual(out["items"][0]["number"], 42)
        self.assertEqual(out["strippedQualifiers"], ["REPO:evil/other", "org:acme", "user:bob"])
        self.assertEqual(out["query"], "repo:lx-software-ltd/siutindei state:open type:issue booking label:bug")
        _, path, _, _ = self.github.requests[0]
        self.assertEqual(path.count("repo%3A"), 1)
        self.assertNotIn("evil", path)

    def test_list_releases(self) -> None:
        inner = self.github

        def with_releases(req, timeout=None):
            if "/releases" in req.full_url:
                inner.requests.append((req.get_method(), req.full_url.replace(board_github.API_ORIGIN, ""), dict(req.headers), None))
                return _FakeResp(
                    json.dumps(
                        [
                            {"id": 1, "tag_name": "v1.4.0", "name": "1.4.0", "draft": False, "prerelease": False, "author": {"login": "lx"}, "published_at": "2026-09-01T00:00:00Z", "body": "Bug fixes", "html_url": "https://github.com/x/releases/v1.4.0"},
                        ]
                    ).encode("utf-8")
                )
            return inner(req, timeout)

        self.router.github = with_releases
        out = board_github.op_list_releases({"limit": 5})
        self.assertEqual(out["items"][0]["tag"], "v1.4.0")
        self.assertEqual(out["items"][0]["notes"], "Bug fixes")
        self.assertFalse(out["items"][0]["draft"])
        self.assertEqual(self.github.requests[0][1], "/repos/lx-software-ltd/siutindei/releases?per_page=5")


if __name__ == "__main__":
    unittest.main()
