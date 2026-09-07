"""T2: research / aws / security read tools and the hourly cache refresh."""

from __future__ import annotations

import json
import os
import unittest
from typing import Any
from unittest.mock import patch

import board_aws
import board_cache
import board_context
import board_research
import board_security
import board_store
import dispatch
from test_board import BoardTestCase, _FakeResp
from test_board_tools import ToolsTestCase


class FakeBrave:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.calls = 0

    def __call__(self, req, timeout=None):  # noqa: ARG002
        if "api.search.brave.com" not in getattr(req, "full_url", ""):
            raise AssertionError(f"unexpected url {req.full_url}")
        self.calls += 1
        self.queries.append(req.full_url)
        return _FakeResp(
            json.dumps(
                {
                    "web": {
                        "results": [
                            {
                                "title": "Tuen Mun swimming classes",
                                "url": "https://example.com/tuen-mun",
                                "description": "Saturday slots for ages 5-8.",
                            }
                        ]
                    }
                }
            ).encode()
        )


class FakeCE:
    def get_cost_and_usage(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "ResultsByTime": [
                {
                    "Groups": [
                        {"Keys": ["AWS Lambda"], "Metrics": {"UnblendedCost": {"Amount": "12.5"}}},
                        {"Keys": ["Amazon DynamoDB"], "Metrics": {"UnblendedCost": {"Amount": "3.25"}}},
                    ]
                }
            ]
        }


class FakeCW:
    def describe_alarms(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "MetricAlarms": [
                {
                    "AlarmName": "siutindei-AdminApiFn-errors",
                    "Namespace": "AWS/Lambda",
                    "MetricName": "Errors",
                    "StateReason": "Threshold crossed",
                    "StateUpdatedTimestamp": "2026-09-01T00:00:00Z",
                },
                {
                    "AlarmName": "unrelated-prod-cpu",
                    "Namespace": "AWS/EC2",
                    "MetricName": "CPUUtilization",
                    "StateReason": "other account noise",
                },
            ]
        }

    def get_metric_data(self, **kwargs: Any) -> dict[str, Any]:
        canned = {"errors": [1], "duration": [120.5], "signInThrottles": [2, 0], "signInSuccesses": [40]}
        ids = [q.get("Id") for q in kwargs.get("MetricDataQueries") or []]
        return {"MetricDataResults": [{"Id": i, "Values": canned.get(i, [])} for i in ids]}


class FakeHealth:
    last_call: dict[str, Any] = {}

    def describe_events(self, **kwargs: Any) -> dict[str, Any]:
        type(self).last_call = kwargs
        return {
            "events": [
                {
                    "arn": "arn:aws:health:ap-southeast-1::event/LAMBDA/1",
                    "service": "LAMBDA",
                    "region": "ap-southeast-1",
                    "statusCode": "open",
                    "eventTypeCode": "AWS_LAMBDA_OPERATIONAL_ISSUE",
                    "startTime": "2026-09-01T00:00:00Z",
                }
            ]
        }


class FakeSecurityHub:
    def get_findings(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "Findings": [
                {
                    "Id": "finding-1",
                    "Title": "S3 bucket is public",
                    "Severity": {"Label": "HIGH"},
                    "ProductName": "Security Hub",
                    "Resources": [{"Id": "arn:aws:s3:::example"}],
                    "UpdatedAt": "2026-09-01T00:00:00Z",
                }
            ]
        }


class FakeAnalyzer:
    def list_analyzers(self) -> dict[str, Any]:
        return {"analyzers": [{"arn": "arn:aws:access-analyzer:ap-southeast-1:1:analyzer/account"}]}

    def list_findings(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "findings": [
                {
                    "id": "aa-1",
                    "status": "ACTIVE",
                    "resourceType": "AWS::S3::Bucket",
                    "resource": "arn:aws:s3:::example",
                    "principal": {"AWS": "*"},
                    "updatedAt": "2026-09-01T00:00:00Z",
                }
            ]
        }


class FakeCognito:
    def describe_user_pool(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "UserPool": {
                "MfaConfiguration": "OPTIONAL",
                "EstimatedNumberOfUsers": 3,
                "Policies": {"PasswordPolicy": {"MinimumLength": 14}},
                "SchemaAttributes": [{}, {}],
                "UserPoolAddOns": {"AdvancedSecurityMode": "AUDIT"},
            }
        }


def _aws_client(service: str, **_kwargs: Any) -> Any:
    return {
        "ce": FakeCE(),
        "cloudwatch": FakeCW(),
        "health": FakeHealth(),
        "securityhub": FakeSecurityHub(),
        "accessanalyzer": FakeAnalyzer(),
        "cognito-idp": FakeCognito(),
    }[service]


class ResearchTestCase(ToolsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.brave = FakeBrave()
        os.environ["SEARCH_API_KEY"] = "brave-local"
        board_research.reset_key_cache_for_tests()
        self.addCleanup(lambda: os.environ.pop("SEARCH_API_KEY", None))
        self.addCleanup(board_research.reset_key_cache_for_tests)
        patcher = patch("board_research.urlrequest.urlopen", self.brave)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestResearch(ResearchTestCase):
    def test_search_is_cached_for_24h(self) -> None:
        from board_tools import ToolContext

        tctx = ToolContext(table=self.table, settings=board_store.load_settings(self.table), persona_id="cfo")
        first = board_research.op_search(tctx, {"query": "Tuen Mun swimming"})
        second = board_research.op_search(tctx, {"query": "Tuen Mun swimming"})
        self.assertEqual(self.brave.calls, 1)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["results"][0]["title"], "Tuen Mun swimming classes")

    def test_unknown_district_is_rejected(self) -> None:
        tctx = __import__("board_tools", fromlist=["ToolContext"]).ToolContext(
            table=self.table, settings=board_store.load_settings(self.table), persona_id="cmo"
        )
        with self.assertRaises(board_research.ResearchError):
            board_research.op_venues(tctx, {"district": "manhattan"})

    def test_venues_valid_district(self) -> None:
        tctx = __import__("board_tools", fromlist=["ToolContext"]).ToolContext(
            table=self.table, settings=board_store.load_settings(self.table), persona_id="cmo"
        )
        out = board_research.op_venues(tctx, {"district": "tuen mun", "kind": "swimming"})
        self.assertEqual(len(out["results"]), 1)
        self.assertIn("tuen mun", self.brave.queries[0].lower().replace("+", " "))


class TestAwsAndSecurity(ToolsTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["USER_POOL_ID"] = "ap-southeast-1_test"
        os.environ["BOARD_AWS_STACK_PREFIX"] = "siutindei"
        os.environ["BOARD_AWS_LAMBDA_NAMES"] = "siutindei-api, siutindei-worker"
        self.addCleanup(lambda: os.environ.pop("USER_POOL_ID", None))
        self.addCleanup(lambda: os.environ.pop("BOARD_AWS_LAMBDA_NAMES", None))
        p1 = patch.object(board_aws, "_client", _aws_client)
        p2 = patch.object(board_security, "_client", _aws_client)
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)
        # GitHub alerts: reuse FakeGitHub from ToolsTestCase via HostRouter already patched.

    def test_cost_alarms_and_lambda_health(self) -> None:
        from board_tools import ToolContext

        tctx = ToolContext(table=self.table, settings=board_store.load_settings(self.table), persona_id="cto")
        cost = board_aws.op_monthly_cost(tctx, {})
        self.assertEqual(cost["totalUsd"], 15.75)
        self.assertEqual(cost["byService"][0]["service"], "AWS Lambda")
        self.assertEqual(cost["scope"], "siutindei")
        self.assertEqual(cost["note"], "")
        cached = board_aws.op_monthly_cost(tctx, {})
        self.assertTrue(cached["cached"])
        alarms = board_aws.op_alarms(tctx, {})
        names = [a["name"] for a in alarms["alarms"]]
        self.assertIn("siutindei-AdminApiFn-errors", names)
        self.assertNotIn("unrelated-prod-cpu", names)
        health = board_aws.op_lambda_health(tctx, {})
        self.assertEqual(health["functionNames"], ["siutindei-api", "siutindei-worker"])
        self.assertEqual(health["functions"][0]["function"], "siutindei-api")
        self.assertEqual(health["functions"][0]["errors24h"], 1)

    def test_budget_alert_propose_then_execute(self) -> None:
        from board_tools import ToolContext, execute_call, REGISTRY

        settings = board_store.load_settings(self.table)
        tctx = ToolContext(table=self.table, settings=settings, persona_id="cto", display_name="CTO")
        outcome = execute_call(
            tctx,
            REGISTRY["aws_propose_budget_alert"],
            {"monthlyUsd": 40, "thresholdPercent": 80, "reason": "Cost jumped last month."},
        )
        self.assertEqual(outcome.status, "pending_approval")
        # Owner executes
        owner = ToolContext(table=self.table, settings=settings, persona_id="cto", actor="owner", owner_sub="owner-1")
        ran = execute_call(
            owner,
            REGISTRY["aws_propose_budget_alert"],
            {"monthlyUsd": 40, "thresholdPercent": 80, "reason": "Cost jumped last month."},
        )
        self.assertEqual(ran.status, "ok")
        actions = board_store.list_actions(self.table)
        self.assertTrue(any("budget alert" in str(a.get("title") or "").lower() for a in actions))

    def test_security_findings_and_cognito(self) -> None:
        from board_tools import ToolContext

        tctx = ToolContext(table=self.table, settings=board_store.load_settings(self.table), persona_id="ciso")
        findings = board_security.op_hub_findings(tctx, {})
        self.assertEqual(findings["openHighOrCritical"], 2)
        self.assertEqual(findings["securityHub"]["findings"][0]["title"], "S3 bucket is public")
        cognito = board_security.op_cognito(tctx, {})
        self.assertEqual(cognito["mfa"], "OPTIONAL")
        self.assertEqual(cognito["advancedSecurityMode"], "AUDIT")
        self.assertIsNone(cognito["failedSignIns"])
        self.assertEqual(cognito["signInThrottles24h"], 2)
        self.assertEqual(cognito["signInSuccesses24h"], 40)
        self.assertNotIn("Users", cognito)

    def test_cache_refresh_and_context_digest(self) -> None:
        notes = board_cache.refresh_all(self.table)
        self.assertEqual(notes["aws"]["aws:monthly_cost"], "ok")
        self.assertEqual(notes["security"]["security:cognito"], "ok")
        self.assertEqual(FakeHealth.last_call.get("maxResults"), 20)
        self.assertNotIn("maxResults", FakeHealth.last_call.get("filter") or {})
        settings = board_store.load_settings(self.table)
        pack = board_context.build_context_pack(self.table, settings, roster=[])
        self.assertIn("AWS", pack["text"])
        self.assertIn("Security:", pack["text"])

    def test_schedule_trigger_dispatch(self) -> None:
        with patch.object(board_store, "records_table", return_value=self.table):
            dispatch.lambda_handler({"internal": "board_cache_refresh"}, None)
        self.assertIsNotNone(board_store.get_cache(self.table, "aws:monthly_cost"))

    def test_schedule_trigger_skips_other_board(self) -> None:
        with patch.object(board_store, "records_table", return_value=self.table):
            out = board_cache.handle_schedule_trigger({"boardKey": "lxSoftware"})
        self.assertEqual(out, {"ok": True, "skipped": "other_board"})
        self.assertIsNone(board_store.get_cache(self.table, "aws:monthly_cost"))


class TestResearchUnavailable(BoardTestCase):
    def test_no_key_raises(self) -> None:
        board_research.reset_key_cache_for_tests()
        os.environ.pop("SEARCH_API_KEY", None)
        os.environ.pop("SEARCH_API_KEY_SECRET_ARN", None)
        os.environ.pop("OPENROUTER_API_KEY", None)
        os.environ.pop("OPENROUTER_API_KEY_SECRET_ARN", None)
        from board_tools import ToolContext

        tctx = ToolContext(table=self.table, settings=board_store.load_settings(self.table), persona_id="ceo")
        with self.assertRaises(board_research.ResearchError):
            board_research.op_search(tctx, {"query": "hello"})


if __name__ == "__main__":
    unittest.main()
