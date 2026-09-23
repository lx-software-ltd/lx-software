"""Sibling OpenRouter spend is pulled into the usage ledger."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from test_board import FakeTable  # noqa: E402

import openrouter_usage  # noqa: E402
import openrouter_usage_pull as pull  # noqa: E402
import runtime  # noqa: E402


NOW = datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc)
SPROUT_HASH = "aa" * 32
PARSER_HASH = "bb" * 32
SIU_HASH = "cc" * 32


class _Ddb:
    def __init__(self, table: FakeTable) -> None:
        self._table = table

    def Table(self, _name: str) -> FakeTable:
        return self._table


def _keys_page(offset: int) -> dict:
    if offset == 0:
        rows = [
            {
                "name": f"other-{i}",
                "hash": f"{i:064x}",
                "usage": 0,
                "usage_daily": 0,
            }
            for i in range(99)
        ]
        rows.append(
            {
                "name": "lxsoftware:statement-parser",
                "hash": PARSER_HASH,
                "usage": 50,
                "usage_daily": 1,
            }
        )
        return {"data": rows}
    if offset == 100:
        return {
            "data": [
                {
                    "name": "lxsoftware:evolvesprouts",
                    "hash": SPROUT_HASH,
                    "usage": 4.5,
                    "usage_daily": 0.25,
                }
            ]
        }
    return {"data": []}


class TestOpenRouterUsagePull(unittest.TestCase):
    def test_catalog_targets_skip_apps_metered_here(self) -> None:
        ids = [row["id"] for row in pull.ingest_targets()]
        self.assertEqual(ids, ["evolvesprouts", "siutindei"])

    def test_management_field_is_the_only_accepted_secret_shape(self) -> None:
        self.assertEqual(pull.management_key_from_secret('{"management":" sk-mgmt "}'), "sk-mgmt")
        self.assertEqual(pull.management_key_from_secret('{"statement-parser":"sk"}'), "")
        self.assertEqual(pull.management_key_from_secret("sk-plain"), "")

    def test_activity_rows_sum_cost_tokens_and_requests(self) -> None:
        totals = pull.sum_activity_rows(
            [
                {
                    "usage": 1.25,
                    "requests": 3,
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "reasoning_tokens": 5,
                    "byok_usage_inference": 9,
                },
                {"usage": "0.25", "requests": "1", "prompt_tokens": 10, "completion_tokens": 4},
            ]
        )
        self.assertAlmostEqual(totals["cost"], 1.5)
        self.assertEqual(totals["calls"], 4)
        self.assertEqual(totals["promptTokens"], 110)
        self.assertEqual(totals["completionTokens"], 24)
        self.assertEqual(totals["totalTokens"], 139)

    def test_pull_writes_sibling_days_and_leaves_local_metering_alone(self) -> None:
        table = FakeTable()
        openrouter_usage.add_usage_day(
            table,
            service="statement-parser",
            owner="hillmarton",
            usage={"promptTokens": 1, "completionTokens": 1, "totalTokens": 2, "cost": 0.2},
            date_iso="2026-09-21",
        )
        seen: list[str] = []

        def fetch(url: str, token: str) -> dict:
            self.assertEqual(token, "mgmt")
            seen.append(url)
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            if parsed.path.endswith("/keys"):
                return _keys_page(int(qs.get("offset", ["0"])[0]))
            self.assertNotIn("date", qs)
            if "api_key_hash" not in qs:
                return {
                    "data": [
                        {
                            "date": "2026-09-21",
                            "usage": 1.5,
                            "requests": 4,
                            "prompt_tokens": 100,
                            "completion_tokens": 20,
                            "reasoning_tokens": 5,
                        }
                    ]
                }
            self.assertIn(qs["api_key_hash"][0], {SPROUT_HASH, PARSER_HASH})
            return {
                "data": [
                    {
                        "date": "2026-09-21",
                        "usage": 1.5,
                        "requests": 4,
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "reasoning_tokens": 5,
                    }
                ]
            }

        result = pull.pull_sibling_usage(
            table, token="mgmt", fetch=fetch, now=NOW, lookback_days=2
        )
        self.assertTrue(result["ok"])
        by_status = {row["id"]: row["status"] for row in result["apps"]}
        self.assertEqual(by_status["evolvesprouts"], "updated")
        self.assertEqual(by_status["siutindei"], "key_not_found")
        self.assertEqual(by_status["openrouter-other"], "updated")
        self.assertTrue(any(PARSER_HASH in url for url in seen))
        self.assertTrue(any("/keys?" in url and "offset=100" in url for url in seen))
        self.assertEqual(sum(1 for url in seen if "api_key_hash=" in url), 2)
        self.assertEqual(sum(1 for url in seen if url.rstrip("/").endswith("/activity")), 1)

        out = openrouter_usage.list_usage(table, from_day="2026-09-21", to_day="2026-09-22")
        by_id = {app["id"]: app for app in out["apps"]}
        self.assertAlmostEqual(by_id["evolvesprouts"]["cost"], 1.75)
        self.assertEqual(by_id["evolvesprouts"]["calls"], 4)
        self.assertEqual(by_id["evolvesprouts"]["promptTokens"], 100)
        self.assertEqual(by_id["evolvesprouts"]["totalTokens"], 125)
        self.assertTrue(by_id["evolvesprouts"]["ingestUsage"])
        self.assertFalse(by_id["evolvesprouts"]["meteredHere"])
        self.assertEqual(by_id["evolvesprouts"]["owners"][0]["label"], "Evolve Sprouts")
        self.assertAlmostEqual(by_id["statement-parser"]["cost"], 0.2)
        self.assertEqual(by_id["statement-parser"]["calls"], 1)

        again = pull.pull_sibling_usage(
            table, token="mgmt", fetch=fetch, now=NOW, lookback_days=2
        )
        self.assertTrue(again["ok"])
        out = openrouter_usage.list_usage(table, from_day="2026-09-21", to_day="2026-09-22")
        by_id = {app["id"]: app for app in out["apps"]}
        self.assertAlmostEqual(by_id["evolvesprouts"]["cost"], 1.75)
        self.assertEqual(by_id["evolvesprouts"]["calls"], 4)

    def test_zero_usage_key_is_recorded_without_activity_calls(self) -> None:
        table = FakeTable()
        activity: list[str] = []

        def fetch(url: str, token: str) -> dict:
            del token
            if urlparse(url).path.endswith("/activity"):
                activity.append(url)
            return {
                "data": [
                    {
                        "name": "lxsoftware:siutindei",
                        "hash": SIU_HASH,
                        "usage": 0,
                        "usage_daily": 0,
                    }
                ]
            }

        result = pull.pull_sibling_usage(
            table, token="mgmt", fetch=fetch, now=NOW, lookback_days=2
        )
        by_status = {row["id"]: row["status"] for row in result["apps"]}
        self.assertEqual(by_status["siutindei"], "no_usage")
        self.assertEqual(by_status["evolvesprouts"], "key_not_found")
        self.assertEqual(len(activity), 1)
        self.assertNotIn("api_key_hash", activity[0])

    def test_today_falls_back_to_usage_daily_when_activity_omits_it(self) -> None:
        table = FakeTable()

        def fetch(url: str, token: str) -> dict:
            del token
            parsed = urlparse(url)
            if parsed.path.endswith("/keys"):
                return {
                    "data": [
                        {
                            "name": "lxsoftware:evolvesprouts",
                            "hash": SPROUT_HASH,
                            "usage": 2,
                            "usage_daily": 0.4,
                        }
                    ]
                }
            self.assertNotIn("date", parse_qs(parsed.query))
            return {
                "data": [
                    {
                        "date": "2026-09-21",
                        "usage": 1.1,
                        "requests": 2,
                        "prompt_tokens": 8,
                        "completion_tokens": 2,
                    }
                ]
            }

        result = pull.pull_sibling_usage(
            table, token="mgmt", fetch=fetch, now=NOW, lookback_days=2
        )
        self.assertTrue(result["ok"])
        out = openrouter_usage.list_usage(table, from_day="2026-09-21", to_day="2026-09-22")
        rows = {
            row["day"]: row
            for row in out["rows"]
            if row["service"] == "evolvesprouts"
        }
        self.assertAlmostEqual(rows["2026-09-21"]["cost"], 1.1)
        self.assertEqual(rows["2026-09-21"]["calls"], 2)
        self.assertAlmostEqual(rows["2026-09-22"]["cost"], 0.4)
        self.assertEqual(rows["2026-09-22"]["calls"], 0)

    def test_failed_activity_request_keeps_the_previously_saved_total(self) -> None:
        table = FakeTable()
        state = {"fail": False}

        def fetch(url: str, token: str) -> dict:
            del token
            parsed = urlparse(url)
            if parsed.path.endswith("/keys"):
                return {
                    "data": [
                        {
                            "name": "lxsoftware:evolvesprouts",
                            "hash": SPROUT_HASH,
                            "usage": 2,
                            "usage_daily": 0,
                        }
                    ]
                }
            if state["fail"]:
                raise pull.PullHttpError(500, "unavailable")
            return {
                "data": [
                    {
                        "date": "2026-09-21",
                        "usage": 1.5,
                        "requests": 4,
                        "prompt_tokens": 10,
                        "completion_tokens": 1,
                    }
                ]
            }

        first = pull.pull_sibling_usage(
            table, token="mgmt", fetch=fetch, now=NOW, lookback_days=2
        )
        self.assertTrue(first["ok"])
        state["fail"] = True
        second = pull.pull_sibling_usage(
            table, token="mgmt", fetch=fetch, now=NOW, lookback_days=2
        )
        self.assertFalse(second["ok"])
        self.assertEqual(second["reason"], "partial")
        out = openrouter_usage.list_usage(table, from_day="2026-09-21", to_day="2026-09-21")
        by_id = {app["id"]: app for app in out["apps"]}
        self.assertAlmostEqual(by_id["evolvesprouts"]["cost"], 1.5)
        self.assertEqual(by_id["evolvesprouts"]["calls"], 4)

    def test_missing_completed_day_is_zero_until_a_later_pull_fills_it(self) -> None:
        table = FakeTable()
        payloads = [
            [{"date": "2026-09-22", "usage": 0.2, "requests": 1, "prompt_tokens": 1, "completion_tokens": 1}],
            [
                {"date": "2026-09-21", "usage": 1.5, "requests": 4, "prompt_tokens": 10, "completion_tokens": 1},
                {"date": "2026-09-22", "usage": 0.2, "requests": 1, "prompt_tokens": 1, "completion_tokens": 1},
            ],
        ]

        def fetch(url: str, token: str) -> dict:
            del token
            if urlparse(url).path.endswith("/keys"):
                return {
                    "data": [
                        {
                            "name": "lxsoftware:evolvesprouts",
                            "hash": SPROUT_HASH,
                            "usage": 2,
                            "usage_daily": 0,
                        }
                    ]
                }
            if "api_key_hash" not in parse_qs(urlparse(url).query):
                return {"data": []}
            return {"data": payloads.pop(0)}

        pull.pull_sibling_usage(table, token="mgmt", fetch=fetch, now=NOW, lookback_days=2)
        first = openrouter_usage.list_usage(table, from_day="2026-09-21", to_day="2026-09-21")
        self.assertAlmostEqual(_app_cost(first, "evolvesprouts"), 0.0)
        pull.pull_sibling_usage(table, token="mgmt", fetch=fetch, now=NOW, lookback_days=2)
        second = openrouter_usage.list_usage(table, from_day="2026-09-21", to_day="2026-09-21")
        self.assertAlmostEqual(_app_cost(second, "evolvesprouts"), 1.5)

    def test_missing_management_key_is_visible_on_the_bill(self) -> None:
        table = FakeTable()
        with patch.dict(
            os.environ,
            {"RECORDS_TABLE_NAME": "records", "OPENROUTER_API_KEY_SECRET_ARN": ""},
            clear=False,
        ):
            with patch.object(runtime, "_ddb", _Ddb(table)):
                result = pull.handle_pull({"internal": "openrouter_usage_pull"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "management_key_missing")
        listed = openrouter_usage.list_usage(table, from_day="2026-09-01", to_day="2026-09-02")
        self.assertIsNotNone(listed["pull"])
        self.assertEqual(listed["pull"]["reason"], "management_key_missing")

    def test_rejected_management_key_does_not_write_days(self) -> None:
        table = FakeTable()

        def fetch(url: str, token: str) -> dict:
            del url, token
            raise pull.PullHttpError(401, "unauthorized")

        with patch.dict(
            os.environ,
            {
                "RECORDS_TABLE_NAME": "records",
                "OPENROUTER_API_KEY_SECRET_ARN": "arn:aws:secretsmanager:eu-west-1:1:secret:x",
            },
            clear=False,
        ):
            with (
                patch.object(runtime, "_ddb", _Ddb(table)),
                patch("openrouter_usage_pull.http_get_json", fetch),
                patch("admin_runtime._get_secretsmanager_client", return_value=object()),
                patch(
                    "openrouter_client.read_secret_raw",
                    return_value='{"management":"mgmt-key","statement-parser":"sk"}',
                ),
            ):
                result = pull.handle_pull({})
        self.assertEqual(result["reason"], "management_key_rejected")
        listed = openrouter_usage.list_usage(table, from_day="2026-09-21", to_day="2026-09-22")
        self.assertEqual(listed["rows"], [])
        self.assertEqual(listed["pull"]["reason"], "management_key_rejected")

    def test_http_error_replaces_a_previous_ok_status(self) -> None:
        table = FakeTable()
        openrouter_usage.put_pull_status(
            table,
            {
                "ok": True,
                "reason": "",
                "pulledAt": "2026-09-22T07:00:00Z",
                "apps": [{"id": "evolvesprouts", "status": "updated", "days": 2}],
            },
        )

        def fetch(url: str, token: str) -> dict:
            del url, token
            raise pull.PullHttpError(503, "unavailable")

        with patch.dict(
            os.environ,
            {
                "RECORDS_TABLE_NAME": "records",
                "OPENROUTER_API_KEY_SECRET_ARN": "arn:aws:secretsmanager:eu-west-1:1:secret:x",
            },
            clear=False,
        ):
            with (
                patch.object(runtime, "_ddb", _Ddb(table)),
                patch("openrouter_usage_pull.http_get_json", fetch),
                patch("admin_runtime._get_secretsmanager_client", return_value=object()),
                patch(
                    "openrouter_client.read_secret_raw",
                    return_value='{"management":"mgmt-key"}',
                ),
            ):
                result = pull.handle_pull({})
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "http_error")
        listed = openrouter_usage.list_usage(table, from_day="2026-09-21", to_day="2026-09-22")
        self.assertEqual(listed["pull"]["reason"], "http_error")
        self.assertFalse(listed["pull"]["ok"])

    def test_other_is_account_spend_not_on_a_key(self) -> None:
        table = FakeTable()
        scratch_hash = "dd" * 32

        def fetch(url: str, token: str) -> dict:
            del token
            parsed = urlparse(url)
            if parsed.path.endswith("/keys"):
                return {
                    "data": [
                        {
                            "name": "lxsoftware:evolvesprouts",
                            "hash": SPROUT_HASH,
                            "usage": 2,
                            "usage_daily": 0.4,
                        },
                        {
                            "name": "lxsoftware:statement-parser",
                            "hash": PARSER_HASH,
                            "usage": 3,
                            "usage_daily": 0.1,
                        },
                        {
                            "name": "scratch",
                            "hash": scratch_hash,
                            "usage": 1,
                            "usage_daily": 0,
                        },
                    ]
                }
            key_hash = (parse_qs(parsed.query).get("api_key_hash") or [None])[0]
            if key_hash is None:
                return {
                    "data": [
                        {
                            "date": "2026-09-21",
                            "usage": 2.0,
                            "requests": 10,
                            "prompt_tokens": 100,
                            "completion_tokens": 20,
                        },
                        {
                            "date": "2026-09-22",
                            "usage": 0.5,
                            "requests": 2,
                            "prompt_tokens": 10,
                            "completion_tokens": 2,
                        },
                    ]
                }
            if key_hash == SPROUT_HASH:
                return {
                    "data": [
                        {
                            "date": "2026-09-21",
                            "usage": 0.4,
                            "requests": 3,
                            "prompt_tokens": 20,
                            "completion_tokens": 4,
                        }
                    ]
                }
            if key_hash == PARSER_HASH:
                return {
                    "data": [
                        {
                            "date": "2026-09-21",
                            "usage": 0.3,
                            "requests": 2,
                            "prompt_tokens": 10,
                            "completion_tokens": 2,
                        }
                    ]
                }
            return {
                "data": [
                    {
                        "date": "2026-09-21",
                        "usage": 0.2,
                        "requests": 4,
                        "prompt_tokens": 8,
                        "completion_tokens": 1,
                    }
                ]
            }

        result = pull.pull_sibling_usage(
            table, token="mgmt", fetch=fetch, now=NOW, lookback_days=2
        )
        self.assertTrue(result["ok"])
        out = openrouter_usage.list_usage(table, from_day="2026-09-21", to_day="2026-09-22")
        by_id = {app["id"]: app for app in out["apps"]}
        self.assertAlmostEqual(by_id["evolvesprouts"]["cost"], 0.8)
        self.assertEqual(by_id["evolvesprouts"]["calls"], 3)
        self.assertEqual(by_id["statement-parser"]["cost"], 0.0)
        scratch = next(app for app in out["apps"] if app["label"] == "scratch")
        self.assertTrue(scratch["id"].startswith("or-key:scratch-"))
        self.assertEqual(scratch["label"], "scratch")
        self.assertTrue(scratch["ingestUsage"])
        self.assertAlmostEqual(scratch["cost"], 0.2)
        self.assertEqual(scratch["calls"], 4)
        other = by_id["openrouter-other"]
        self.assertEqual(other["label"], "Other")
        self.assertAlmostEqual(other["cost"], 1.1)
        self.assertEqual(other["calls"], 3)

    def test_failed_account_activity_keeps_saved_other(self) -> None:
        table = FakeTable()
        state = {"fail_account": False}

        def fetch(url: str, token: str) -> dict:
            del token
            parsed = urlparse(url)
            if parsed.path.endswith("/keys"):
                return {
                    "data": [
                        {
                            "name": "lxsoftware:evolvesprouts",
                            "hash": SPROUT_HASH,
                            "usage": 1,
                            "usage_daily": 0,
                        }
                    ]
                }
            if "api_key_hash" not in parse_qs(parsed.query):
                if state["fail_account"]:
                    raise pull.PullHttpError(500, "unavailable")
                return {
                    "data": [
                        {
                            "date": "2026-09-21",
                            "usage": 1.25,
                            "requests": 5,
                            "prompt_tokens": 10,
                            "completion_tokens": 2,
                        }
                    ]
                }
            return {
                "data": [
                    {
                        "date": "2026-09-21",
                        "usage": 0.25,
                        "requests": 1,
                        "prompt_tokens": 4,
                        "completion_tokens": 1,
                    }
                ]
            }

        pull.pull_sibling_usage(table, token="mgmt", fetch=fetch, now=NOW, lookback_days=2)
        self.assertAlmostEqual(_app_cost(
            openrouter_usage.list_usage(table, from_day="2026-09-21", to_day="2026-09-21"),
            "openrouter-other",
        ), 1.0)
        state["fail_account"] = True
        second = pull.pull_sibling_usage(
            table, token="mgmt", fetch=fetch, now=NOW, lookback_days=2
        )
        self.assertFalse(second["ok"])
        self.assertEqual(second["reason"], "partial")
        self.assertAlmostEqual(_app_cost(
            openrouter_usage.list_usage(table, from_day="2026-09-21", to_day="2026-09-21"),
            "openrouter-other",
        ), 1.0)


def _app_cost(payload: dict, app_id: str) -> float:
    for app in payload["apps"]:
        if app["id"] == app_id:
            return float(app["cost"])
    raise AssertionError(app_id)


if __name__ == "__main__":
    unittest.main()
