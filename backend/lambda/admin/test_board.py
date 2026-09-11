"""Unit tests for the Executive Board (no AWS or network calls)."""

from __future__ import annotations

import json
import re
import sys
import types
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch


def _install_stubs() -> None:
    if "boto3" not in sys.modules or not isinstance(sys.modules["boto3"], MagicMock):
        sys.modules["boto3"] = MagicMock()
    if "botocore.exceptions" not in sys.modules:
        botocore = types.ModuleType("botocore")
        exceptions = types.ModuleType("botocore.exceptions")

        class BotoCoreError(Exception):
            pass

        class ClientError(BotoCoreError):
            pass

        exceptions.BotoCoreError = BotoCoreError
        exceptions.ClientError = ClientError
        botocore.exceptions = exceptions
        sys.modules["botocore"] = botocore
        sys.modules["botocore.exceptions"] = exceptions
    elif not hasattr(sys.modules["botocore.exceptions"], "BotoCoreError"):
        class BotoCoreError(Exception):
            pass

        sys.modules["botocore.exceptions"].BotoCoreError = BotoCoreError


_install_stubs()

from botocore.exceptions import ClientError  # noqa: E402

# 12:00 HKT — outside default quiet hours [22, 8]. CI around 14:00 UTC is 22:00 HKT
# and otherwise flakes hold-window tests (quiet shift pushes executeAt past 24h).
BOARD_DAYTIME_UTC = datetime(2026, 9, 11, 4, 0, tzinfo=timezone.utc)


class _FrozenBoardDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return BOARD_DAYTIME_UTC if tz is None else BOARD_DAYTIME_UTC.astimezone(tz)


def freeze_board_daytime(test_case: unittest.TestCase, *module_names: str) -> None:
    """Pin datetime.now in hold / quiet-hour modules so those tests ignore wall clock."""
    for name in module_names or ("board_holds", "board_policy"):
        patcher = patch(f"{name}.datetime", _FrozenBoardDateTime)
        patcher.start()
        test_case.addCleanup(patcher.stop)

import board_actions  # noqa: E402
import board_chat  # noqa: E402
import board_meeting  # noqa: E402
import board_personas  # noqa: E402
import board_store  # noqa: E402
import openrouter_client  # noqa: E402
from board_routes import validate_settings  # noqa: E402
from contract_constants import BOARD_KEY  # noqa: E402
from dispatch import lambda_handler  # noqa: E402


# ---------------------------------------------------------------------------
# In-memory DynamoDB table
# ---------------------------------------------------------------------------

class FakeTable:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.scan_calls: list[dict[str, Any]] = []

    @staticmethod
    def _key(item: dict[str, Any]) -> tuple[str, str]:
        return (str(item["pk"]), str(item["sk"]))

    def get_item(self, Key: dict[str, Any], **_: Any) -> dict[str, Any]:
        item = self.items.get(self._key(Key))
        return {"Item": dict(item)} if item else {}

    def put_item(
        self,
        Item: dict[str, Any],
        ConditionExpression: str | None = None,
        ExpressionAttributeNames: dict[str, str] | None = None,
        ExpressionAttributeValues: dict[str, Any] | None = None,
        **_: Any,
    ) -> dict:
        key = self._key(Item)
        if ConditionExpression and not self._evaluate(
            ConditionExpression, self.items.get(key) or {}, ExpressionAttributeNames or {}, ExpressionAttributeValues or {}
        ):
            raise self._conditional_error()
        self.items[key] = dict(Item)
        return {}

    def delete_item(self, Key: dict[str, Any], **_: Any) -> dict:
        self.items.pop(self._key(Key), None)
        return {}

    def query(
        self,
        KeyConditionExpression: str,
        ExpressionAttributeValues: dict[str, Any],
        IndexName: str | None = None,
        ScanIndexForward: bool = True,
        Limit: int | None = None,
        ExclusiveStartKey: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pk_attr, sk_attr = ("gsi1pk", "gsi1sk") if IndexName == "gsi1" else ("pk", "sk")
        clauses = [c.strip() for c in KeyConditionExpression.split(" AND ")]
        pk_value = None
        prefix = None
        for clause in clauses:
            m = re.fullmatch(r"(\w+) = (:\w+)", clause)
            if m:
                pk_value = ExpressionAttributeValues[m.group(2)]
                continue
            m = re.fullmatch(r"begins_with\((\w+), (:\w+)\)", clause)
            if m:
                prefix = ExpressionAttributeValues[m.group(2)]
        rows = [
            dict(i)
            for i in self.items.values()
            if i.get(pk_attr) == pk_value and (prefix is None or str(i.get(sk_attr, "")).startswith(prefix))
        ]
        rows.sort(key=lambda i: str(i.get(sk_attr, "")), reverse=not ScanIndexForward)
        if ExclusiveStartKey:
            skipped = False
            rest: list[dict[str, Any]] = []
            for row in rows:
                if not skipped:
                    same_index = row.get(pk_attr) == ExclusiveStartKey.get(pk_attr) and row.get(sk_attr) == ExclusiveStartKey.get(sk_attr)
                    same_item = row.get("pk") == ExclusiveStartKey.get("pk") and row.get("sk") == ExclusiveStartKey.get("sk")
                    if same_index and (ExclusiveStartKey.get("pk") is None or same_item):
                        skipped = True
                    continue
                rest.append(row)
            rows = rest
        last_key = None
        if Limit is not None and len(rows) > Limit:
            last = rows[Limit - 1]
            last_key = {k: last[k] for k in ("pk", "sk") if k in last}
            if IndexName == "gsi1":
                last_key["gsi1pk"] = last.get("gsi1pk")
                last_key["gsi1sk"] = last.get("gsi1sk")
            rows = rows[:Limit]
        out: dict[str, Any] = {"Items": rows}
        if last_key:
            out["LastEvaluatedKey"] = last_key
        return out

    def scan(self, **kwargs: Any) -> dict[str, Any]:
        self.scan_calls.append(kwargs)
        rows = list(self.items.values())
        filt = kwargs.get("FilterExpression")
        values = kwargs.get("ExpressionAttributeValues") or {}
        if isinstance(filt, str) and "NOT begins_with" in filt:
            prefixes = [str(v) for v in values.values()]
            rows = [
                r
                for r in rows
                if not any(str(r["pk"]).startswith(p) for p in prefixes)
            ]
        elif isinstance(filt, str) and "begins_with(pk," in filt.replace(" ", ""):
            prefix = str(values.get(":asset") or next(iter(values.values()), ""))
            rows = [r for r in rows if str(r["pk"]).startswith(prefix)]
        return {"Items": [dict(r) for r in rows[: kwargs.get("Limit", 50)]]}

    def update_item(
        self,
        Key: dict[str, Any],
        UpdateExpression: str,
        ExpressionAttributeValues: dict[str, Any],
        ConditionExpression: str | None = None,
        ExpressionAttributeNames: dict[str, str] | None = None,
    ) -> dict:
        key = self._key(Key)
        item = dict(self.items.get(key) or {"pk": Key["pk"], "sk": Key["sk"]})
        names = ExpressionAttributeNames or {}
        if ConditionExpression and not self._evaluate(ConditionExpression, item, names, ExpressionAttributeValues):
            raise self._conditional_error()
        for section in re.split(r"\b(?=SET\b|ADD\b)", UpdateExpression):
            section = section.strip()
            if section.startswith("SET"):
                for assignment in section[3:].split(","):
                    attr, value = [p.strip() for p in assignment.split("=")]
                    item[names.get(attr, attr)] = ExpressionAttributeValues[value]
            elif section.startswith("ADD"):
                for addition in section[3:].split(","):
                    attr, value = addition.strip().split()
                    attr = names.get(attr, attr)
                    current = item.get(attr, 0)
                    item[attr] = current + ExpressionAttributeValues[value]
        self.items[key] = item
        return {}

    @staticmethod
    def _evaluate(expr: str, item: dict[str, Any], names: dict[str, str], values: dict[str, Any]) -> bool:
        """Evaluate the subset of DynamoDB condition expressions the code under test uses.

        Grammar: ``OR`` < ``AND`` < ``NOT`` < comparison / function / parenthesised group.
        A comparison involving a missing attribute (``None``) is false, matching DynamoDB.
        """
        tokens = re.findall(r"#\w+|:\w+|<>|<=|>=|[<>=(),]|\w+", expr)
        pos = 0

        def peek() -> str | None:
            return tokens[pos] if pos < len(tokens) else None

        def take() -> str:
            nonlocal pos
            tok = tokens[pos]
            pos += 1
            return tok

        def expect(tok: str) -> None:
            got = take()
            if got != tok:
                raise ValueError(f"expected {tok!r}, got {got!r} in {expr!r}")

        def attr_name(tok: str) -> str:
            return names[tok] if tok.startswith("#") else tok

        def operand() -> Any:
            tok = take()
            if tok.isdigit():
                return int(tok)
            if tok.startswith(":"):
                return values[tok]
            return item.get(attr_name(tok))

        def compare(op: str, left: Any, right: Any) -> bool:
            if op == "=":
                return left == right
            if op == "<>":
                return left != right
            if left is None or right is None:
                return False
            try:
                return {"<": left < right, ">": left > right, "<=": left <= right, ">=": left >= right}[op]
            except TypeError:
                return False

        def primary() -> bool:
            tok = peek()
            if tok == "(":
                take()
                result = or_expr()
                expect(")")
                return result
            if tok == "NOT":
                take()
                return not primary()
            if tok in ("attribute_exists", "attribute_not_exists"):
                take()
                expect("(")
                present = attr_name(take()) in item
                expect(")")
                return present if tok == "attribute_exists" else not present
            if tok == "begins_with":
                take()
                expect("(")
                subject = operand()
                expect(",")
                prefix = operand()
                expect(")")
                return isinstance(subject, str) and isinstance(prefix, str) and subject.startswith(prefix)
            left = operand()
            if peek() in ("=", "<>", "<", ">", "<=", ">="):
                return compare(take(), left, operand())
            return bool(left)

        def and_expr() -> bool:
            result = primary()
            while peek() == "AND":
                take()
                result = primary() and result
            return result

        def or_expr() -> bool:
            result = and_expr()
            while peek() == "OR":
                take()
                result = and_expr() or result
            return result

        result = or_expr()
        if pos != len(tokens):
            raise ValueError(f"unexpected trailing tokens in {expr!r}")
        return result

    @staticmethod
    def _conditional_error() -> ClientError:
        response = {"Error": {"Code": "ConditionalCheckFailedException"}}
        err = ClientError(response, "ConditionalWrite")
        if not getattr(err, "response", None):
            err.response = response
        return err


# ---------------------------------------------------------------------------
# OpenRouter fake
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _completion(content: Any) -> bytes:
    text = content if isinstance(content, str) else json.dumps(content)
    return json.dumps(
        {
            "model": "test/model",
            "choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cost": 0.01},
        }
    ).encode("utf-8")


class FakeOpenRouter:
    """Answers each prompt kind with a plausible payload and records requests."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def __call__(self, req, timeout=None):  # noqa: ARG002
        body = json.loads(req.data.decode("utf-8"))
        self.requests.append(body)
        user = next((m["content"] for m in reversed(body["messages"]) if m["role"] == "user"), "")
        if "Draft the agenda" in user:
            return _FakeResp(
                _completion(
                    {
                        "items": [
                            {"title": "Launch date", "question": "When do we go live?", "whyNow": "Runway."},
                            {"title": "Pricing", "question": "What take rate?", "whyNow": "Revenue."},
                            {"title": "Providers", "question": "How many providers first?", "whyNow": "Supply."},
                        ]
                    }
                )
            )
        if "For EACH agenda item" in user:
            system = body["messages"][0]["content"]
            who = re.search(r"You are (.+?), ", system).group(1) if "You are " in system else "x"
            return _FakeResp(
                _completion(
                    {
                        "items": [
                            {
                                "agendaIndex": 1,
                                "position": f"{who} says ship a closed beta in six weeks.",
                                "risks": ["Scope creep"],
                                "proposedActions": [
                                    {
                                        "title": f"{who}: pick the beta launch date",
                                        "detail": "Put a date in the calendar.",
                                        "priority": "now",
                                        "effort": "S",
                                        "dueInDays": 3,
                                        "metric": "Date published.",
                                    }
                                ],
                            }
                        ]
                    }
                )
            )
        if "most consequential disagreements" in user:
            return _FakeResp(
                _completion(
                    {
                        "conflicts": [
                            {
                                "topic": "Beta scope",
                                "summary": "CTO and CPO disagree on scope.",
                                "askedOf": ["cto", "cpo"],
                                "question": "What is the minimum?",
                            }
                        ]
                    }
                )
            )
        if "The chair asks you specifically" in user:
            return _FakeResp(_completion("I concede: keep the beta to search plus booking requests."))
        if "Write the minutes" in user:
            return _FakeResp(
                _completion(
                    {
                        "headline": "Ship a closed beta in six weeks.",
                        "discussion": [{"agendaIndex": 1, "summary": "Agreed on beta.", "consensus": "agree"}],
                        "decisions": [{"text": "Closed beta in six weeks", "proposedBy": "ceo", "rationale": "Runway"}],
                        "risks": [{"text": "Provider supply too thin", "owner": "coo", "severity": "high"}],
                        "actions": [
                            {"title": "Pick the beta launch date", "detail": "Calendar it.", "persona": "ceo", "priority": "now", "effort": "S", "dueInDays": 3, "metric": "Date set"},
                            {"title": "Call 10 activity providers", "detail": "Book calls.", "persona": "coo", "priority": "now", "effort": "M", "dueInDays": 7, "metric": "10 calls"},
                            {"title": "Draft privacy notice", "detail": "PDPO.", "persona": "ciso", "priority": "now", "effort": "M", "dueInDays": 14, "metric": "Published"},
                            {"title": "Set pricing experiment", "detail": "Two tiers.", "persona": "cfo", "priority": "now", "effort": "S", "dueInDays": 10, "metric": "Live"},
                            {"title": "Publish the launch waitlist page", "detail": "Landing page.", "persona": "cmo", "priority": "next", "effort": "S", "dueInDays": 14, "metric": "50 sign-ups"},
                        ],
                        "questionsForOwner": ["How much can you spend on ads?"],
                    }
                )
            )
        return _FakeResp(
            _completion(
                "Focus on providers first.\nSUGGEST_MEETING: {\"mode\": \"deepDive\", \"topic\": \"Provider onboarding\"}"
            )
        )


# ---------------------------------------------------------------------------
# Base fixture
# ---------------------------------------------------------------------------

class BoardTestCase(unittest.TestCase):
    def setUp(self) -> None:
        import runtime

        self.table = FakeTable()
        patcher_ddb = patch.object(runtime, "_ddb")
        mock_ddb = patcher_ddb.start()
        self.addCleanup(patcher_ddb.stop)
        mock_ddb.Table.return_value = self.table
        env = {
            "RECORDS_TABLE_NAME": "records-test",
            "AUDIT_LOG_TABLE_NAME": "audit-test",
            "ASSETS_BUCKET_NAME": "assets-test",
            "OPENROUTER_API_KEY": "sk-test",
        }
        patcher_env = patch.dict("os.environ", env, clear=False)
        patcher_env.start()
        self.addCleanup(patcher_env.stop)
        for var in ("AWS_LAMBDA_FUNCTION_NAME", "PARSE_WORKER_FUNCTION_NAME", "GITHUB_READ_TOKEN_SECRET_ARN"):
            patcher = patch.dict("os.environ", {}, clear=False)
            patcher.start()
            self.addCleanup(patcher.stop)
            import os

            os.environ.pop(var, None)
        self.openrouter = FakeOpenRouter()
        patcher_http = patch("openrouter_client.urlrequest.urlopen", self.openrouter)
        patcher_http.start()
        self.addCleanup(patcher_http.stop)
        patcher_sleep = patch("openrouter_client.time.sleep", lambda *_: None)
        patcher_sleep.start()
        self.addCleanup(patcher_sleep.stop)
        openrouter_client.reset_api_key_cache_for_tests()

    @staticmethod
    def event(path: str, method: str = "GET", body: dict | None = None, query: str = "") -> dict:
        ev: dict[str, Any] = {
            "requestContext": {
                "http": {"method": method, "path": path},
                "requestId": "req-board-1",
                "authorizer": {"jwt": {"claims": {"sub": "admin-sub", "cognito:groups": "[admin]"}}},
            },
            "rawQueryString": query,
        }
        if body is not None:
            ev["body"] = json.dumps(body)
        return ev

    def call(self, path: str, method: str = "GET", body: dict | None = None, query: str = "") -> tuple[int, Any]:
        out = lambda_handler(self.event(path, method, body, query), None)
        return out["statusCode"], json.loads(out["body"])


# ---------------------------------------------------------------------------
# Personas and charter
# ---------------------------------------------------------------------------

class TestPersonas(unittest.TestCase):
    def test_roster_has_eight_fixed_roles(self) -> None:
        roster = board_personas.effective_roster({})
        self.assertEqual([p["id"] for p in roster], ["ceo", "cfo", "coo", "cpo", "cto", "cio", "ciso", "cmo"])
        for p in roster:
            self.assertTrue(p["vision"] and p["mission"] and p["mandate"])
            self.assertFalse(any(p["isOverridden"].values()))

    def test_override_wins_and_changes_hash(self) -> None:
        base = board_personas.effective_roster({})
        cto_default = next(p for p in base if p["id"] == "cto")
        roster = board_personas.effective_roster(
            {"cto": {"mandate": "Ship the Flutter app first.", "displayName": "Ada"}}
        )
        cto = next(p for p in roster if p["id"] == "cto")
        self.assertEqual(cto["mandate"], "Ship the Flutter app first.")
        self.assertEqual(cto["displayName"], "Ada")
        self.assertEqual(cto["vision"], cto_default["vision"])
        self.assertTrue(cto["isOverridden"]["mandate"])
        self.assertFalse(cto["isOverridden"]["vision"])
        self.assertNotEqual(cto["profileHash"], cto_default["profileHash"])

    def test_system_prompt_quotes_charter_fields_verbatim(self) -> None:
        roster = board_personas.effective_roster(
            {"cmo": {"vision": "VISION-X", "mission": "MISSION-Y", "mandate": "MANDATE-Z"}}
        )
        cmo = next(p for p in roster if p["id"] == "cmo")
        prompt = board_personas.render_system_prompt(cmo, {"vision": "Company V", "mission": "Company M"})
        self.assertIn("Your vision: VISION-X", prompt)
        self.assertIn("Your mission: MISSION-Y", prompt)
        self.assertIn("Your mandate: MANDATE-Z", prompt)
        self.assertIn("Company vision: Company V", prompt)
        self.assertIn("Company mission: Company M", prompt)

    def test_validate_override_rejects_long_and_non_string(self) -> None:
        with self.assertRaises(ValueError):
            board_personas.validate_member_override({"vision": "x" * 2001})
        with self.assertRaises(ValueError):
            board_personas.validate_member_override({"mandate": 12})
        self.assertEqual(board_personas.validate_member_override({"vision": "   "}), {})


class TestSettingsValidation(unittest.TestCase):
    def test_settings_validation(self) -> None:
        current = board_store.default_settings()
        out = validate_settings(
            {"schedule": {"morningEnabled": True}, "dailyBudgetUsd": 7.5, "models": {"chat": "x/y"}},
            current,
        )
        self.assertTrue(out["schedule"]["morningEnabled"])
        self.assertFalse(out["schedule"]["eveningEnabled"])
        self.assertEqual(out["dailyBudgetUsd"], 7.5)
        self.assertEqual(out["models"]["chat"], "x/y")
        with self.assertRaises(ValueError):
            validate_settings({"defaultChair": "intern"}, current)
        with self.assertRaises(ValueError):
            validate_settings({"dailyBudgetUsd": 1000}, current)


# ---------------------------------------------------------------------------
# Routes: overview, charter, members, brief, settings
# ---------------------------------------------------------------------------

class TestBoardRoutes(BoardTestCase):
    def test_overview_lists_members_and_defaults(self) -> None:
        status, body = self.call("/siu-tin-dei/board")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["members"]), 8)
        self.assertEqual(body["settings"]["defaultChair"], "ceo")
        self.assertEqual(body["openActionCount"], 0)
        self.assertEqual(body["usageToday"]["budgetUsd"], 15.0)
        self.assertEqual(body["pendingApprovalCount"], 0)
        self.assertTrue(body["toolsEnabled"])
        self.assertEqual(body["settings"]["tools"]["globalMode"], "propose")
        self.assertEqual(body["settings"]["tools"]["matrix"]["github"]["cto"], "act")

    def test_member_put_and_reset(self) -> None:
        status, body = self.call(
            "/siu-tin-dei/board/members/cto", "PUT", {"mandate": "Own the Flutter release.", "displayName": "Ada"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["member"]["mandate"], "Own the Flutter release.")
        self.assertTrue(body["member"]["isOverridden"]["mandate"])
        _, overview = self.call("/siu-tin-dei/board")
        cto = next(m for m in overview["members"] if m["id"] == "cto")
        self.assertEqual(cto["displayName"], "Ada")
        status, body = self.call("/siu-tin-dei/board/members/cto", "DELETE")
        self.assertEqual(status, 200)
        self.assertFalse(body["member"]["isOverridden"]["mandate"])

    def test_member_unknown_and_validation(self) -> None:
        status, _ = self.call("/siu-tin-dei/board/members/intern", "PUT", {"mandate": "x"})
        self.assertEqual(status, 404)
        status, body = self.call("/siu-tin-dei/board/members/cfo", "PUT", {"vision": "x" * 3000})
        self.assertEqual(status, 400)
        self.assertIn("2000", body["message"])

    def test_charter_brief_settings_roundtrip(self) -> None:
        status, body = self.call("/siu-tin-dei/board/charter", "PUT", {"vision": "V", "mission": "M"})
        self.assertEqual(status, 200)
        self.assertEqual(body["charter"]["vision"], "V")
        status, body = self.call("/siu-tin-dei/board/brief", "PUT", {"markdown": "# Brief\nWe are pre-launch."})
        self.assertEqual(status, 200)
        status, body = self.call(
            "/siu-tin-dei/board/settings", "PUT", {"schedule": {"eveningEnabled": True}, "shareFinanceSummary": True}
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["settings"]["schedule"]["eveningEnabled"])
        _, overview = self.call("/siu-tin-dei/board")
        self.assertEqual(overview["charter"]["mission"], "M")
        self.assertIn("pre-launch", overview["brief"]["markdown"])
        self.assertTrue(overview["settings"]["shareFinanceSummary"])

    def test_updates_post_and_list(self) -> None:
        status, _ = self.call("/siu-tin-dei/board/updates", "POST", {"text": "Signed two providers."})
        self.assertEqual(status, 201)
        status, body = self.call("/siu-tin-dei/board/updates")
        self.assertEqual(status, 200)
        self.assertEqual(body["updates"][0]["text"], "Signed two providers.")

    def test_records_scan_excludes_board_rows(self) -> None:
        self.call("/siu-tin-dei/board/brief", "PUT", {"markdown": "secret strategy"})
        self.table.put_item(Item={"pk": "RECORD#1", "sk": "A"})
        self.table.put_item(Item={"pk": "PARSE_JOB#j1", "sk": "META", "status": "failed"})
        status, body = self.call("/records")
        self.assertEqual(status, 200)
        pks = [i["pk"] for i in body["items"]]
        self.assertIn("RECORD#1", pks)
        self.assertFalse(any(pk.startswith("BOARD#") for pk in pks))
        self.assertFalse(any(pk.startswith("PARSE_JOB#") for pk in pks))
        self.assertIn("NOT begins_with(pk, :board)", self.table.scan_calls[-1]["FilterExpression"])
        self.assertEqual(self.table.scan_calls[-1]["ExpressionAttributeValues"][":board"], "BOARD#")
        self.assertEqual(
            self.table.scan_calls[-1]["ExpressionAttributeValues"][":openrouter"], "OPENROUTER#"
        )
        self.assertEqual(
            self.table.scan_calls[-1]["ExpressionAttributeValues"][":parsejob"], "PARSE_JOB#"
        )
        self.assertIn("NOT begins_with(pk, :parsejob)", self.table.scan_calls[-1]["FilterExpression"])

    def test_assets_list_returns_only_asset_rows(self) -> None:
        self.table.put_item(Item={"pk": "RECORD#1", "sk": "A"})
        self.table.put_item(Item={"pk": "PARSE_JOB#j1", "sk": "META", "status": "failed"})
        self.table.put_item(
            Item={
                "pk": "ASSET#inbound/hillmarton/" + ("a" * 32) + "/00_stmt.pdf",
                "sk": "META",
                "fileName": "stmt.pdf",
                "house": "hillmarton",
                "size": 12,
            }
        )
        status, body = self.call("/assets")
        self.assertEqual(status, 200)
        pks = [i["pk"] for i in body["items"]]
        self.assertTrue(all(pk.startswith("ASSET#") for pk in pks))
        self.assertEqual(len(pks), 1)
        self.assertIn("begins_with(pk, :asset)", self.table.scan_calls[-1]["FilterExpression"])

    def test_openrouter_usage_endpoint_groups_by_app(self) -> None:
        import openrouter_usage

        openrouter_usage.add_usage_day(
            self.table,
            service=openrouter_client.SERVICE_EXECUTIVE_BOARD,
            owner="siuTinDei",
            usage={"promptTokens": 10, "completionTokens": 2, "totalTokens": 12, "cost": 0.5},
            date_iso="2026-09-02",
        )
        openrouter_usage.add_usage_day(
            self.table,
            service=openrouter_client.SERVICE_STATEMENT_PARSER,
            owner="lxSoftware",
            usage={"promptTokens": 4, "completionTokens": 1, "totalTokens": 5, "cost": 0.2},
            date_iso="2026-09-03",
        )
        status, body = self.call("/openrouter/usage", query="from=2026-09-01&to=2026-09-08")
        self.assertEqual(status, 200)
        self.assertEqual(body["payer"]["id"], "lxSoftware")
        self.assertAlmostEqual(body["total"]["cost"], 0.7)
        by_id = {app["id"]: app for app in body["apps"]}
        self.assertAlmostEqual(by_id["executive-board"]["cost"], 0.5)
        self.assertAlmostEqual(by_id["statement-parser"]["cost"], 0.2)
        self.assertIn("evolvesprouts", by_id)
        self.table.put_item(Item={"pk": "RECORD#1", "sk": "A"})
        _, records = self.call("/records")
        pks = [i["pk"] for i in records["items"]]
        self.assertIn("RECORD#1", pks)
        self.assertFalse(any(str(pk).startswith("OPENROUTER#") for pk in pks))

    def test_non_admin_forbidden(self) -> None:
        ev = self.event("/siu-tin-dei/board")
        ev["requestContext"]["authorizer"]["jwt"]["claims"]["cognito:groups"] = "[viewer]"
        out = lambda_handler(ev, None)
        self.assertEqual(out["statusCode"], 403)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class TestChat(BoardTestCase):
    def test_message_roundtrip_with_inline_worker(self) -> None:
        self.call("/siu-tin-dei/board/members/ceo", "PUT", {"mandate": "MANDATE-VERBATIM"})
        status, body = self.call("/siu-tin-dei/board/chat/ceo", "POST", {"text": "What should I do first?"})
        self.assertEqual(status, 202)
        job_id = body["jobId"]
        status, job = self.call(f"/siu-tin-dei/board/chat/ceo/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["message"]["role"], "assistant")
        self.assertEqual(job["message"]["suggestedMeeting"], {"mode": "deepDive", "topic": "Provider onboarding"})
        self.assertNotIn("SUGGEST_MEETING", job["message"]["text"])
        status, thread = self.call("/siu-tin-dei/board/chat/ceo")
        self.assertEqual([m["role"] for m in thread["messages"]], ["user", "assistant"])
        system_prompt = self.openrouter.requests[0]["messages"][0]["content"]
        self.assertIn("Your mandate: MANDATE-VERBATIM", system_prompt)
        self.assertIn("CONTEXT DATA", self.openrouter.requests[0]["messages"][1]["content"])
        self.assertEqual(self.openrouter.requests[0]["provider"]["data_collection"], "deny")
        usage = board_store.load_usage_day(self.table)
        self.assertEqual(usage["calls"], 1)
        self.assertAlmostEqual(usage["cost"], 0.01)
        import openrouter_usage

        ledger = openrouter_usage.list_usage(
            self.table, from_day=openrouter_usage.utc_today(), to_day=openrouter_usage.utc_today()
        )
        by_id = {app["id"]: app for app in ledger["apps"]}
        self.assertEqual(ledger["payer"]["id"], "lxSoftware")
        self.assertAlmostEqual(by_id["executive-board"]["cost"], 0.01)
        self.assertEqual(by_id["executive-board"]["owners"][0]["id"], "siuTinDei")
        self.assertAlmostEqual(ledger["total"]["cost"], 0.01)

    def test_budget_exhausted_refuses_new_messages(self) -> None:
        self.call("/siu-tin-dei/board/settings", "PUT", {"dailyBudgetUsd": 0.5})
        board_store.add_usage_day(self.table, {"promptTokens": 1, "completionTokens": 1, "totalTokens": 2, "cost": 0.6})
        status, body = self.call("/siu-tin-dei/board/chat/cfo", "POST", {"text": "hi"})
        self.assertEqual(status, 429)
        self.assertIn("budget", body["message"].lower())

    def test_clear_thread(self) -> None:
        self.call("/siu-tin-dei/board/chat/cmo", "POST", {"text": "hello"})
        status, body = self.call("/siu-tin-dei/board/chat/cmo", "DELETE")
        self.assertEqual(status, 200)
        self.assertEqual(body["removed"], 2)
        _, thread = self.call("/siu-tin-dei/board/chat/cmo")
        self.assertEqual(thread["messages"], [])

    def test_extract_suggested_meeting_tolerates_bad_json(self) -> None:
        text, suggestion = board_chat.extract_suggested_meeting("Reply\nSUGGEST_MEETING: {not json}")
        self.assertIsNone(suggestion)
        self.assertEqual(text, "Reply")


# ---------------------------------------------------------------------------
# Meetings and actions
# ---------------------------------------------------------------------------

class TestMeetings(BoardTestCase):
    def test_standup_runs_all_phases_inline(self) -> None:
        status, body = self.call("/siu-tin-dei/board/meetings", "POST", {"mode": "standup"})
        self.assertEqual(status, 202)
        meeting_id = body["meetingId"]
        status, body = self.call(f"/siu-tin-dei/board/meetings/{meeting_id}")
        self.assertEqual(status, 200)
        meeting = body["meeting"]
        self.assertEqual(meeting["status"], "succeeded")
        self.assertEqual(meeting["phase"], "done")
        self.assertEqual(len(meeting["agenda"]), 3)
        self.assertEqual(meeting["minutes"]["headline"], "Ship a closed beta in six weeks.")
        phases = [t["phase"] for t in body["turns"]]
        self.assertEqual(phases.count("agenda"), 1)
        self.assertEqual(phases.count("positions"), 8)
        self.assertEqual(phases.count("synthesis"), 1)
        self.assertNotIn("challenge", phases)
        self.assertEqual(meeting["usage"]["calls"] if "calls" in meeting["usage"] else 10, 10)
        self.assertAlmostEqual(meeting["usage"]["cost"], 0.10)
        # Minutes cap "now" actions at three; the fourth is demoted.
        priorities = [a["priority"] for a in meeting["minutes"]["actions"]]
        self.assertEqual(priorities.count("now"), 3)
        self.assertEqual(len(meeting["createdActionIds"]), 5)
        status, actions = self.call("/siu-tin-dei/board/actions", query="status=open")
        self.assertEqual(len(actions["actions"]), 5)
        self.assertEqual(actions["actions"][0]["priority"], "now")
        self.assertEqual(len(board_store.load_decision_log(self.table)), 1)
        # Every persona was briefed with its own system prompt and the context pack.
        position_requests = [r for r in self.openrouter.requests if "For EACH agenda item" in r["messages"][-1]["content"]]
        self.assertEqual(len(position_requests), 8)
        self.assertTrue(all("CONTEXT DATA" in r["messages"][1]["content"] for r in position_requests))

    def test_deep_dive_requires_topic_and_runs_challenge(self) -> None:
        status, body = self.call("/siu-tin-dei/board/meetings", "POST", {"mode": "deepDive"})
        self.assertEqual(status, 400)
        status, body = self.call("/siu-tin-dei/board/meetings", "POST", {"mode": "deepDive", "topic": "Provider onboarding"})
        self.assertEqual(status, 202)
        _, body = self.call(f"/siu-tin-dei/board/meetings/{body['meetingId']}")
        phases = [t["phase"] for t in body["turns"]]
        self.assertEqual(phases.count("challenge"), 3)  # chair summary + two rebuttals
        self.assertEqual(body["meeting"]["agenda"][0]["title"], "Provider onboarding")
        self.assertEqual(body["meeting"]["status"], "succeeded")

    def test_second_meeting_reaffirms_duplicate_actions(self) -> None:
        self.call("/siu-tin-dei/board/meetings", "POST", {"mode": "standup"})
        _, first = self.call("/siu-tin-dei/board/actions", query="status=open")
        self.assertEqual(len(first["actions"]), 5)
        status, body = self.call("/siu-tin-dei/board/meetings", "POST", {"mode": "standup"})
        self.assertEqual(status, 202)
        _, meeting = self.call(f"/siu-tin-dei/board/meetings/{body['meetingId']}")
        self.assertEqual(meeting["meeting"]["createdActionIds"], [])
        self.assertEqual(len(meeting["meeting"]["reaffirmedActionIds"]), 5)
        _, second = self.call("/siu-tin-dei/board/actions", query="status=open")
        self.assertEqual(len(second["actions"]), 5)
        self.assertEqual(len(second["actions"][0]["reaffirmedByMeetingIds"]), 1)

    def test_action_status_and_note_update(self) -> None:
        self.call("/siu-tin-dei/board/meetings", "POST", {"mode": "standup"})
        _, body = self.call("/siu-tin-dei/board/actions")
        action_id = body["actions"][0]["actionId"]
        status, body = self.call(f"/siu-tin-dei/board/actions/{action_id}", "PUT", {"status": "done", "note": "Done Monday"})
        self.assertEqual(status, 200)
        self.assertEqual(body["action"]["status"], "done")
        self.assertEqual(body["action"]["note"], "Done Monday")
        status, _ = self.call(f"/siu-tin-dei/board/actions/{action_id}", "PUT", {"status": "bogus"})
        self.assertEqual(status, 400)
        _, listing = self.call("/siu-tin-dei/board/actions", query="status=open")
        self.assertEqual(len(listing["actions"]), 4)

    def test_cancel_running_meeting(self) -> None:
        doc = {
            "meetingId": "m1",
            "status": "running",
            "mode": "standup",
            "phase": "positions",
            "phaseState": "running",
            "createdAt": board_store.now_iso(),
            "updatedAt": board_store.now_iso(),
        }
        board_store.put_meeting(self.table, doc)
        status, body = self.call("/siu-tin-dei/board/meetings/m1/cancel", "POST")
        self.assertEqual(status, 200)
        self.assertEqual(body["meeting"]["status"], "cancelled")
        status, _ = self.call("/siu-tin-dei/board/meetings", "POST", {"mode": "standup"})
        self.assertEqual(status, 202, "a cancelled meeting must not block a new one")

    def test_running_meeting_blocks_second_start(self) -> None:
        board_store.put_meeting(
            self.table,
            {"meetingId": "m2", "status": "running", "mode": "standup", "phase": "agenda", "createdAt": board_store.now_iso(), "updatedAt": board_store.now_iso()},
        )
        status, body = self.call("/siu-tin-dei/board/meetings", "POST", {"mode": "standup"})
        self.assertEqual(status, 409)
        self.assertIn("already running", body["message"])

    def test_stale_running_meeting_is_marked_failed(self) -> None:
        board_store.put_meeting(
            self.table,
            {"meetingId": "old", "status": "running", "mode": "standup", "phase": "positions", "createdAt": "2020-01-01T00:00:00.000Z", "updatedAt": "2020-01-01T00:00:00.000Z"},
        )
        _, body = self.call("/siu-tin-dei/board/meetings/old")
        self.assertEqual(body["meeting"]["status"], "failed")
        self.assertIn("stalled", body["meeting"]["errorMessage"])

    def test_phase_claim_is_idempotent(self) -> None:
        board_store.put_meeting(
            self.table,
            {"meetingId": "m3", "status": "running", "mode": "standup", "phase": "agenda", "phaseState": "pending", "createdAt": board_store.now_iso(), "updatedAt": board_store.now_iso()},
        )
        self.assertTrue(board_store.claim_meeting_phase(self.table, "m3", expected_phase="agenda", stale_before_iso="2000-01-01T00:00:00.000Z"))
        self.assertFalse(board_store.claim_meeting_phase(self.table, "m3", expected_phase="agenda", stale_before_iso="2000-01-01T00:00:00.000Z"))
        self.assertFalse(board_store.claim_meeting_phase(self.table, "m3", expected_phase="positions", stale_before_iso="2000-01-01T00:00:00.000Z"))

    def test_schedule_trigger_respects_settings(self) -> None:
        lambda_handler({"internal": "board_meeting", "slot": "morning"}, None)
        self.assertEqual(board_store.list_meetings(self.table), [])
        self.call("/siu-tin-dei/board/settings", "PUT", {"schedule": {"morningEnabled": True}})
        lambda_handler({"internal": "board_meeting", "slot": "morning"}, None)
        meetings = board_store.list_meetings(self.table)
        self.assertEqual(len(meetings), 1)
        self.assertEqual(meetings[0]["trigger"], "schedule:morning")
        self.assertEqual(meetings[0]["status"], "succeeded")
        lambda_handler({"internal": "board_meeting", "slot": "evening"}, None)
        self.assertEqual(len(board_store.list_meetings(self.table)), 1)

    def test_schedule_trigger_ignores_other_board_key(self) -> None:
        self.call("/siu-tin-dei/board/settings", "PUT", {"schedule": {"morningEnabled": True}})
        lambda_handler(
            {"internal": "board_meeting", "slot": "morning", "boardKey": "lxSoftware"},
            None,
        )
        self.assertEqual(board_store.list_meetings(self.table), [])
        lambda_handler(
            {"internal": "board_meeting", "slot": "morning", "boardKey": BOARD_KEY},
            None,
        )
        self.assertEqual(len(board_store.list_meetings(self.table)), 1)


class TestBoardKeyRouting(unittest.TestCase):
    def test_missing_or_blank_board_key_is_this_board(self) -> None:
        self.assertTrue(board_store.event_targets_this_board(None))
        self.assertTrue(board_store.event_targets_this_board({}))
        self.assertTrue(board_store.event_targets_this_board({"boardKey": ""}))
        self.assertTrue(board_store.event_targets_this_board({"boardKey": BOARD_KEY}))
        self.assertFalse(board_store.event_targets_this_board({"boardKey": "lxSoftware"}))


class TestNormalizers(unittest.TestCase):
    def test_normalize_minutes_defaults_unknown_persona_to_chair(self) -> None:
        minutes = board_meeting.normalize_minutes(
            {
                "headline": "H",
                "actions": [{"title": "Do X", "persona": "intern", "priority": "urgent", "effort": "XL", "dueInDays": "soon"}],
                "risks": [{"text": "R", "owner": "nobody", "severity": "extreme"}],
            },
            agenda=[{"title": "A", "question": "Q"}],
            persona_ids={"ceo", "cto"},
            default_persona="ceo",
        )
        self.assertEqual(minutes["actions"][0]["persona"], "ceo")
        self.assertEqual(minutes["actions"][0]["priority"], "next")
        self.assertEqual(minutes["actions"][0]["effort"], "M")
        self.assertIsNone(minutes["actions"][0]["dueInDays"])
        self.assertEqual(minutes["risks"][0]["severity"], "medium")

    def test_similarity(self) -> None:
        self.assertEqual(board_actions.similarity("Pick the beta launch date", "pick the beta launch date!"), 1.0)
        self.assertGreaterEqual(board_actions.similarity("Pick the beta launch date", "Pick the beta launch date now"), 0.8)
        self.assertLess(board_actions.similarity("Pick the beta launch date", "Call ten providers"), 0.3)

    def test_normalize_agenda_inserts_topic_first(self) -> None:
        items = board_meeting.normalize_agenda(
            [{"title": "Pricing", "question": "What take rate?"}], topic="Provider onboarding"
        )
        self.assertEqual(items[0]["title"], "Provider onboarding")
        self.assertEqual(items[1]["title"], "Pricing")

    def test_usage_normalization(self) -> None:
        usage = openrouter_client.normalize_usage({"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001})
        self.assertEqual(usage["totalTokens"], 15)
        total = openrouter_client.add_usage(usage, usage)
        self.assertEqual(total["promptTokens"], 20)
        self.assertAlmostEqual(total["cost"], 0.002)

    def test_parse_json_object_text_tolerates_prose(self) -> None:
        parsed = openrouter_client.parse_json_object_text("Sure! ```json\n{\"a\": 1}\n``` done")
        self.assertEqual(parsed, {"a": 1})
        with self.assertRaises(openrouter_client.OpenRouterError):
            openrouter_client.parse_json_object_text("no json here")


if __name__ == "__main__":
    unittest.main()
