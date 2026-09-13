"""WP7: AWS / security / stores / GitHub accuracy fixes (review M12, M13, L1)."""

from __future__ import annotations

import gzip
import io
import json
import os
import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch
from urllib import error as urlerror

from botocore.exceptions import ClientError

import board_aws
import board_github
import board_security
import board_store
import board_stores
from board_tools import ToolContext
from test_board import _FakeResp
from test_board_t2 import FakeCW, FakeHealth, FakeSecurityHub, FakeAnalyzer
from test_board_t6 import FakeStoresHttp, StoresTestCase
from test_board_tools import ToolsTestCase


def _client_error(code: str, message: str, operation: str) -> ClientError:
    """Works with real botocore and with the stub installed by ``test_board``."""
    payload = {"Error": {"Code": code, "Message": message}}
    exc = ClientError(payload, operation)
    exc.response = payload  # type: ignore[attr-defined]
    return exc


# ---------------------------------------------------------------------------
# AWS: cost scope + Lambda names
# ---------------------------------------------------------------------------

class RecordingCE:
    """Returns rows only for unfiltered queries unless ``filtered_rows`` is set."""

    def __init__(self, *, filtered_rows: bool = False, filtered_error: str | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.filtered_rows = filtered_rows
        self.filtered_error = filtered_error

    def get_cost_and_usage(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if "Filter" in kwargs:
            if self.filtered_error:
                raise _client_error(self.filtered_error, "bad filter", "GetCostAndUsage")
            if not self.filtered_rows:
                return {"ResultsByTime": [{"Groups": []}]}
            return {"ResultsByTime": [{"Groups": [{"Keys": ["AWS Lambda"], "Metrics": {"UnblendedCost": {"Amount": "2.0"}}}]}]}
        return {
            "ResultsByTime": [
                {"Groups": [{"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "99.0"}}}]}
            ]
        }


class RecordingCW(FakeCW):
    def __init__(self) -> None:
        self.metric_calls: list[dict[str, Any]] = []

    def get_metric_data(self, **kwargs: Any) -> dict[str, Any]:
        self.metric_calls.append(kwargs)
        return super().get_metric_data(**kwargs)


class InsightsLimitCW(RecordingCW):
    """CloudWatch Metrics Insights: one SQL Expression per GetMetricData."""

    def get_metric_data(self, **kwargs: Any) -> dict[str, Any]:
        queries = kwargs.get("MetricDataQueries") or []
        if sum(1 for q in queries if q.get("Expression")) > 1:
            raise _client_error(
                "ValidationException",
                "Maximum number of queries (1) exceeded",
                "GetMetricData",
            )
        return super().get_metric_data(**kwargs)


class AwsTestCase(ToolsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.ce = RecordingCE()
        self.cw = RecordingCW()
        os.environ["BOARD_AWS_STACK_PREFIX"] = "siutindei"
        os.environ.pop("BOARD_AWS_LAMBDA_NAMES", None)
        self.addCleanup(lambda: os.environ.pop("BOARD_AWS_LAMBDA_NAMES", None))
        p = patch.object(board_aws, "_client", self._client)
        p.start()
        self.addCleanup(p.stop)

    def _client(self, service: str, **_kwargs: Any) -> Any:
        return {"ce": self.ce, "cloudwatch": self.cw, "health": FakeHealth()}[service]

    def _ctx(self) -> ToolContext:
        return ToolContext(table=self.table, settings=board_store.load_settings(self.table), persona_id="cto")


class TestAwsCostScope(AwsTestCase):
    def test_empty_tag_filter_falls_back_to_account_and_says_so(self) -> None:
        cost = board_aws.op_monthly_cost(self._ctx(), {})
        self.assertEqual(cost["scope"], "account")
        self.assertEqual(cost["totalUsd"], 99.0)
        self.assertIn("whole account", cost["note"])
        self.assertEqual(len(self.ce.calls), 2)
        self.assertIn("Filter", self.ce.calls[0])
        self.assertEqual(self.ce.calls[0]["Filter"]["Tags"]["Key"], "Project")
        self.assertEqual(self.ce.calls[0]["Filter"]["Tags"]["Values"], ["Siu Tin Dei"])
        self.assertNotIn("Filter", self.ce.calls[1])

    def test_filtered_rows_are_labelled_siutindei(self) -> None:
        self.ce.filtered_rows = True
        cost = board_aws.op_monthly_cost(self._ctx(), {})
        self.assertEqual(cost["scope"], "siutindei")
        self.assertEqual(cost["note"], "")
        self.assertEqual(cost["totalUsd"], 2.0)
        self.assertEqual(len(self.ce.calls), 1)
        self.assertEqual(self.ce.calls[0]["Filter"]["Tags"]["Key"], "Project")
        self.assertEqual(self.ce.calls[0]["Filter"]["Tags"]["Values"], ["Siu Tin Dei"])

    def test_cost_project_tag_comes_from_billing_contract(self) -> None:
        self.assertEqual(board_aws.cost_project_tag(), "Siu Tin Dei")

    def test_validation_error_on_filter_also_falls_back(self) -> None:
        self.ce.filtered_error = "ValidationException"
        cost = board_aws.fetch_monthly_cost()
        self.assertEqual(cost["scope"], "account")
        self.assertEqual(cost["totalUsd"], 99.0)

    def test_other_client_errors_surface(self) -> None:
        self.ce.filtered_error = "AccessDeniedException"
        with self.assertRaises(board_aws.AwsToolError):
            board_aws.fetch_monthly_cost()


class TestAwsLambdaNames(AwsTestCase):
    def test_no_names_configured_reports_note_without_querying(self) -> None:
        health = board_aws.op_lambda_health(self._ctx(), {})
        self.assertEqual(health["functions"], [])
        self.assertEqual(health["functionNames"], [])
        self.assertIn("no functions configured", health["note"])
        self.assertEqual(self.cw.metric_calls, [])

    def test_env_names_are_queried_verbatim(self) -> None:
        os.environ["BOARD_AWS_LAMBDA_NAMES"] = " siutindei-prod-api ,siutindei-prod-worker,, siutindei-prod-api "
        self.assertEqual(board_aws.lambda_function_names(), ["siutindei-prod-api", "siutindei-prod-worker"])
        health = board_aws.fetch_lambda_health()
        self.assertEqual([f["function"] for f in health["functions"]], ["siutindei-prod-api", "siutindei-prod-worker"])
        self.assertEqual(health["functionNames"], ["siutindei-prod-api", "siutindei-prod-worker"])
        dims = [
            q["MetricStat"]["Metric"]["Dimensions"][0]["Value"]
            for call in self.cw.metric_calls
            for q in call["MetricDataQueries"]
        ]
        self.assertEqual(sorted(set(dims)), ["siutindei-prod-api", "siutindei-prod-worker"])
        self.assertFalse(any("AdminApiFn" in d for d in dims))

    def test_default_list_is_empty(self) -> None:
        self.assertEqual(board_aws.DEFAULT_LAMBDA_NAMES, ())


# ---------------------------------------------------------------------------
# Security: Cognito tier string + sign-in metrics
# ---------------------------------------------------------------------------

class ModernPoolCognito:
    def describe_user_pool(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "UserPool": {
                "MfaConfiguration": "ON",
                "UserPoolTier": "ESSENTIALS",
                "EstimatedNumberOfUsers": 5,
                "Policies": {"PasswordPolicy": {"MinimumLength": 12}},
                "SchemaAttributes": [{}],
            }
        }


class FailingCW:
    def get_metric_data(self, **_kwargs: Any) -> dict[str, Any]:
        raise _client_error("AccessDeniedException", "no cloudwatch", "GetMetricData")


class TestSecurityCognito(ToolsTestCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["USER_POOL_ID"] = "ap-southeast-1_modern"
        self.addCleanup(lambda: os.environ.pop("USER_POOL_ID", None))
        self.cw: Any = InsightsLimitCW()
        p = patch.object(board_security, "_client", self._client)
        p.start()
        self.addCleanup(p.stop)

    def _client(self, service: str, **_kwargs: Any) -> Any:
        return {
            "cognito-idp": ModernPoolCognito(),
            "cloudwatch": self.cw,
            "securityhub": FakeSecurityHub(),
            "accessanalyzer": FakeAnalyzer(),
        }[service]

    def test_user_pool_tier_string_does_not_crash(self) -> None:
        out = board_security.fetch_cognito()
        self.assertEqual(out["tier"], "ESSENTIALS")
        self.assertIsNone(out["advancedSecurityMode"])
        self.assertEqual(out["mfa"], "ON")
        self.assertIsNone(out["failedSignIns"])
        self.assertEqual(out["signInThrottles24h"], 2)
        self.assertEqual(out["signInSuccesses24h"], 40)
        self.assertIn("no failed-sign-in metric", out["note"])
        self.assertEqual(len(self.cw.metric_calls), 2)
        ids = []
        for call in self.cw.metric_calls:
            queries = call["MetricDataQueries"]
            self.assertEqual(len(queries), 1, "Metrics Insights allows one SQL query per GetMetricData")
            self.assertIn("Expression", queries[0])
            self.assertIn("UserPool = 'ap-southeast-1_modern'", queries[0]["Expression"])
            ids.append(queries[0]["Id"])
        self.assertEqual(ids, ["signInThrottles", "signInSuccesses"])
        self.assertIn("SignInThrottles", self.cw.metric_calls[0]["MetricDataQueries"][0]["Expression"])

    def test_cloudwatch_failure_keeps_posture_and_explains(self) -> None:
        self.cw = FailingCW()
        out = board_security.fetch_cognito()
        self.assertEqual(out["tier"], "ESSENTIALS")
        self.assertIsNone(out["failedSignIns"])
        self.assertIsNone(out["signInThrottles24h"])
        self.assertIn("not measured", out["note"])

    def test_metric_sum_handles_missing_ids(self) -> None:
        rows = [{"Id": "signInThrottles", "Values": [1.0, 2.0]}, {"Id": "signInSuccesses", "Values": []}]
        self.assertEqual(board_security._metric_sum(rows, "signInThrottles"), 3)
        self.assertEqual(board_security._metric_sum(rows, "signInSuccesses"), 0)
        self.assertIsNone(board_security._metric_sum(rows, "other"))


# ---------------------------------------------------------------------------
# Stores: sales reports + honest unavailability
# ---------------------------------------------------------------------------

SALES_TSV = (
    "Provider\tProvider Country\tSKU\tDeveloper\tTitle\tVersion\tProduct Type Identifier\tUnits\t"
    "Developer Proceeds\tBegin Date\tEnd Date\tCustomer Currency\tCountry Code\tCurrency of Proceeds\t"
    "Apple Identifier\tCustomer Price\n"
    "APPLE\tUS\tSKU1\tLX\tsiutindei\t1.4.0\t1F\t7\t0\t09/03/2026\t09/03/2026\tHKD\tHK\tHKD\tapp-1\t0\n"
    "APPLE\tUS\tSKU1\tLX\tsiutindei\t1.4.0\t1F\t3\t0\t09/03/2026\t09/03/2026\tGBP\tGB\tGBP\tapp-1\t0\n"
    "APPLE\tUS\tSKU1\tLX\tsiutindei\t1.4.0\t7F\t20\t0\t09/03/2026\t09/03/2026\tHKD\tHK\tHKD\tapp-1\t0\n"
    "APPLE\tUS\tSKU1\tLX\tsiutindei\t1.4.0\t3F\t2\t0\t09/03/2026\t09/03/2026\tHKD\tHK\tHKD\tapp-1\t0\n"
    "APPLE\tUS\tSKU2\tLX\tother app\t2.0\t1F\t50\t0\t09/03/2026\t09/03/2026\tHKD\tHK\tHKD\tapp-9\t0\n"
    "APPLE\tUS\tSKU1\tLX\tsiutindei\t1.4.0\tIA1\t4\t0\t09/03/2026\t09/03/2026\tHKD\tHK\tHKD\tapp-1\t0\n"
)


class SalesReportHttp(FakeStoresHttp):
    def __init__(self, *, report: bytes | None = None, status: int | None = None) -> None:
        super().__init__()
        self.report = report if report is not None else gzip.compress(SALES_TSV.encode())
        self.status = status

    def __call__(self, req, timeout=None):  # noqa: ARG002
        if "/v1/salesReports" in req.full_url:
            self.calls.append((req.get_method(), req.full_url, None))
            if self.status:
                raise urlerror.HTTPError(
                    req.full_url,
                    self.status,
                    "not found",
                    {},
                    io.BytesIO(b'{"errors":[{"detail":"There were no sales for the date specified."}]}'),
                )
            return _FakeResp(self.report)
        return super().__call__(req, timeout)


class TestStoresSalesReport(StoresTestCase):
    def _use(self, http: FakeStoresHttp) -> None:
        self.http = http
        p = patch.object(board_stores, "_urlopen", http)
        p.start()
        self.addCleanup(p.stop)

    def test_gzip_tsv_is_parsed_for_units(self) -> None:
        os.environ["ASC_VENDOR_NUMBER"] = "88888888"
        self.addCleanup(lambda: os.environ.pop("ASC_VENDOR_NUMBER", None))
        board_stores.reset_caches_for_tests()
        self._use(SalesReportHttp())
        metrics = board_stores.fetch_asc_metrics()
        downloads = metrics["downloads"]
        self.assertTrue(downloads["available"])
        self.assertEqual(downloads["units"], 10)
        self.assertEqual(downloads["firstTimeDownloads"], 10)
        self.assertEqual(downloads["updates"], 20)
        self.assertEqual(downloads["redownloads"], 2)
        self.assertEqual(downloads["rows"], 4, "other apps and IAP rows are excluded")
        self.assertEqual(downloads["topCountries"][0], {"country": "HK", "units": 7})
        self.assertIsNone(metrics["installs"])
        self.assertEqual(metrics["installsNote"], "not available from these APIs")
        url = next(u for m, u, _ in self.http.calls if "/v1/salesReports" in u)
        for needle in (
            "filter%5Bfrequency%5D=DAILY",
            "filter%5BreportType%5D=SALES",
            "filter%5BreportSubType%5D=SUMMARY",
            "filter%5BvendorNumber%5D=88888888",
            "filter%5BreportDate%5D=" + downloads["reportDate"],
        ):
            self.assertIn(needle, url)
        yesterday = (datetime.now(timezone.utc).date().toordinal() - 1)
        self.assertEqual(downloads["reportDate"], datetime.fromordinal(yesterday).date().isoformat())

    def test_missing_vendor_number_is_unavailable_not_zero(self) -> None:
        os.environ.pop("ASC_VENDOR_NUMBER", None)
        board_stores.reset_caches_for_tests()
        self._use(SalesReportHttp())
        metrics = board_stores.fetch_asc_metrics()
        self.assertEqual(metrics["downloads"]["available"], False)
        self.assertIn("ASC_VENDOR_NUMBER", metrics["downloads"]["reason"])
        self.assertNotIn("units", metrics["downloads"])
        self.assertFalse(any("/v1/salesReports" in u for _m, u, _b in self.http.calls))

    def test_apple_404_no_sales_is_unavailable_with_reason(self) -> None:
        os.environ["ASC_VENDOR_NUMBER"] = "88888888"
        self.addCleanup(lambda: os.environ.pop("ASC_VENDOR_NUMBER", None))
        board_stores.reset_caches_for_tests()
        self._use(SalesReportHttp(status=404))
        downloads = board_stores.fetch_asc_downloads("app-1")
        self.assertFalse(downloads["available"])
        self.assertIn("404", downloads["reason"])

    def test_json_error_body_is_unavailable(self) -> None:
        os.environ["ASC_VENDOR_NUMBER"] = "88888888"
        self.addCleanup(lambda: os.environ.pop("ASC_VENDOR_NUMBER", None))
        board_stores.reset_caches_for_tests()
        self._use(SalesReportHttp(report=b'{"errors":[{"detail":"Report not yet available"}]}'))
        downloads = board_stores.fetch_asc_downloads("app-1")
        self.assertFalse(downloads["available"])
        self.assertEqual(downloads["reason"], "Report not yet available")

    def test_parse_helpers(self) -> None:
        parsed = board_stores.parse_sales_report_tsv(SALES_TSV)
        self.assertEqual(parsed["firstTimeDownloads"], 60, "no app filter sums every app")
        self.assertEqual(board_stores._product_kind("F1"), "firstTimeDownloads")
        self.assertEqual(board_stores._product_kind("7T"), "updates")
        self.assertIsNone(board_stores._product_kind("IAY"))
        self.assertEqual(board_stores._gunzip_text(b"plain"), "plain")

    def test_status_summary_reports_vendor_number(self) -> None:
        board_stores.reset_caches_for_tests()
        self.assertFalse(board_stores.status_summary()["appleVendorNumberSet"])


class TestStoresCrashUnavailable(StoresTestCase):
    def test_play_query_failure_is_structured(self) -> None:
        calls: list[str] = []

        def failing(req, timeout=None):  # noqa: ARG001
            calls.append(req.full_url)
            raise urlerror.HTTPError(req.full_url, 403, "forbidden", {}, io.BytesIO(b'{"error":"no reporting access"}'))

        with patch.object(board_stores, "_urlopen", failing):
            out = board_stores.fetch_play_crash_rate("com.siutindei.app")
        self.assertFalse(out["available"])
        self.assertIn("403", out["reason"])
        self.assertTrue(any(u.endswith("/crashRateMetricSet") for u in calls))
        self.assertTrue(any("crashRateMetricSet:query" in u for u in calls))

    def test_apple_empty_metrics_is_unavailable(self) -> None:
        with patch.object(board_stores, "asc", return_value={"productData": []}):
            out = board_stores.fetch_asc_hangs("app-1")
        self.assertFalse(out["available"])
        self.assertIn("no hang data", out["reason"])


# ---------------------------------------------------------------------------
# GitHub: qualifiers, rate limits, releases
# ---------------------------------------------------------------------------

class TestGitHubQualifiers(unittest.TestCase):
    def test_strip_scope_qualifiers(self) -> None:
        cleaned, removed = board_github.strip_scope_qualifiers('crash repo:a/b Org:acme -user:bob user:"x y" label:bug')
        self.assertEqual(cleaned, "crash label:bug")
        self.assertEqual(removed, ["repo:a/b", "Org:acme", "-user:bob", 'user:"x y"'])
        self.assertEqual(board_github.strip_scope_qualifiers("repository:x userland"), ("repository:x userland", []))


class TestGitHubRateLimit(ToolsTestCase):
    def _limit(self, status: int, headers: dict[str, str]) -> None:
        def limited(req, timeout=None):  # noqa: ARG001
            raise urlerror.HTTPError(req.full_url, status, "limited", headers, io.BytesIO(b'{"message":"API rate limit exceeded"}'))

        self.router.github = limited

    def test_remaining_zero_with_reset_raises_without_sleeping(self) -> None:
        reset = int(datetime.now(timezone.utc).timestamp()) + 120
        self._limit(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)})
        with patch("time.sleep", side_effect=AssertionError("must not sleep")):
            with self.assertRaises(board_github.GitHubSnapshotError) as ctx:
                board_github.op_search_issues({"query": "booking"})
        message = str(ctx.exception)
        self.assertTrue(message.startswith("GitHub rate limit; retry after "), message)
        self.assertTrue(message.endswith("s"))
        self.assertTrue(100 <= ctx.exception.retry_after <= 121)
        self.assertEqual(ctx.exception.status, 403)

    def test_retry_after_header_is_honoured(self) -> None:
        self._limit(429, {"retry-after": "30"})
        with self.assertRaises(board_github.GitHubSnapshotError) as ctx:
            board_github.op_get_issue({"number": 42})
        self.assertEqual(str(ctx.exception), "GitHub rate limit; retry after 30s")
        self.assertEqual(ctx.exception.retry_after, 30)

    def test_plain_403_is_not_a_rate_limit(self) -> None:
        self._limit(403, {"X-RateLimit-Remaining": "55"})
        with self.assertRaises(board_github.GitHubSnapshotError) as ctx:
            board_github.op_get_issue({"number": 42})
        self.assertIn("status 403", str(ctx.exception))
        self.assertIsNone(ctx.exception.retry_after)


class TestGitHubReleases(ToolsTestCase):
    def test_releases_default_to_empty_list_and_are_read_only(self) -> None:
        out = board_github.op_list_releases({})
        self.assertEqual(out["items"], [])
        method, path, headers, _ = self.github.requests[0]
        self.assertEqual(method, "GET")
        self.assertEqual(path, "/repos/lx-software-ltd/siutindei/releases?per_page=10")
        self.assertNotIn("Authorization", headers)

    def test_releases_parse_fields(self) -> None:
        def releases(req, timeout=None):  # noqa: ARG001
            return _FakeResp(
                json.dumps(
                    [
                        {"id": 2, "tag_name": "v1.5.0-rc1", "name": None, "draft": True, "prerelease": True, "author": {"login": "lx"}, "created_at": "c", "published_at": None, "body": "x" * 5000, "html_url": "u"},
                    ]
                ).encode()
            )

        self.router.github = releases
        out = board_github.op_list_releases({"limit": 99})
        item = out["items"][0]
        self.assertEqual(item["name"], "v1.5.0-rc1")
        self.assertTrue(item["draft"])
        self.assertTrue(item["prerelease"])
        self.assertLess(len(item["notes"]), board_github.MAX_COMMENT_CHARS + 20)
        self.assertIn("[... truncated]", item["notes"])


if __name__ == "__main__":
    unittest.main()
