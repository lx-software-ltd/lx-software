#!/usr/bin/env python3
"""Unit tests for the read-only GA4 / Search Console report (no network)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "report-public-analytics.py"
CONFIGURE = ROOT / "scripts" / "configure-public-analytics.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


report = _load(SCRIPT, "report_public_analytics")
configure = _load(CONFIGURE, "configure_public_analytics_for_report")


def _ga_response(rows):
    return {
        "rows": [
            {
                "dimensionValues": [{"value": d} for d in dims],
                "metricValues": [{"value": m} for m in mets],
            }
            for dims, mets in rows
        ]
    }


class FakeApi:
    def __init__(self, responses=None, fail=None):
        self.responses = responses or {}
        self.fail = fail or {}
        self.calls = []

    def post(self, url, body=None):
        self.calls.append(("POST", url, body))
        if url in self.fail:
            raise report.ApiError(*self.fail[url], url)
        canned = self.responses.get(url)
        if callable(canned):
            return canned(body)
        return canned or {}

    def get(self, url):
        self.calls.append(("GET", url, None))
        if url in self.fail:
            raise report.ApiError(*self.fail[url], url)
        return self.responses.get(url, {})


RUN_REPORT = f"{report.DATA_V1BETA}/properties/42:runReport"
GSC_QUERY = f"{report.WEBMASTERS_V3}/sites/sc-domain%3Aexample.com/searchAnalytics/query"
GSC_SITEMAPS = f"{report.WEBMASTERS_V3}/sites/sc-domain%3Aexample.com/sitemaps"


def _run_report(body):
    dims = [d["name"] for d in body["dimensions"]]
    metrics = [m["name"] for m in body["metrics"]]
    if not dims and len(body["dateRanges"]) == 3:
        return _ga_response([
            (["date_range_0"], ["10", "8", "7", "20", "0.5", "61.4"]),
            (["date_range_1"], ["103", "94", "80", "118", "0.62", "45.2"]),
            (["date_range_2"], ["250", "200", "150", "400", "0.6", "50"]),
        ])
    event = (body.get("dimensionFilter") or {}).get("filter", {}).get("stringFilter", {}).get("value")
    if event == "contact_click":
        return _ga_response([(["email"], ["5"]), (["whatsapp"], ["3"])])
    if dims == ["sessionDefaultChannelGroup"]:
        return _ga_response([(["Direct"], ["60", "55", "0.7"]), (["Organic Search"], ["40", "39", "0.5"])])
    return {"rowCount": 0} if "eventName" in dims else _ga_response([(["x"], ["1"] * len(metrics))])


class DateRangeTests(unittest.TestCase):
    def test_range_ends_yesterday(self):
        rng = report.ga_date_range(28, date(2026, 10, 4))
        self.assertEqual(rng, {"startDate": "2026-09-06", "endDate": "2026-10-03"})

    def test_seven_day_range(self):
        rng = report.ga_date_range(7, date(2026, 10, 4))
        self.assertEqual(rng, {"startDate": "2026-09-27", "endDate": "2026-10-03"})


class SettingsTests(unittest.TestCase):
    def test_gsc_domain_property_strips_www(self):
        self.assertEqual(report.gsc_property("https://www.lx-software.com"), "sc-domain:lx-software.com")

    def test_site_url_from_site_json(self):
        self.assertEqual(report.site_url(), "https://www.lx-software.com")


class RequestTests(unittest.TestCase):
    def test_event_filter_and_order(self):
        body = report.ga_request(("customEvent:channel",), ("eventCount",), [{"startDate": "a", "endDate": "b"}],
                                 event_name="contact_click", order_by="eventCount")
        self.assertEqual(body["dimensionFilter"]["filter"]["stringFilter"]["value"], "contact_click")
        self.assertEqual(body["orderBys"], [{"metric": {"metricName": "eventCount"}, "desc": True}])
        self.assertEqual(body["limit"], str(report.ROW_LIMIT))

    def test_breakdowns_only_use_registered_params(self):
        """Every customEvent:<param> dimension must be a registered GA4 custom dimension."""
        params = set(configure.SITE_EVENT_PARAMS)
        events = set(configure.SITE_EVENT_NAMES)
        for spec in report.BREAKDOWNS:
            for dim in spec.dimensions:
                if dim.startswith("customEvent:"):
                    self.assertIn(dim.split(":", 1)[1], params, spec.title)
            if spec.event_name:
                self.assertIn(spec.event_name, events, spec.title)


class FormatTests(unittest.TestCase):
    def test_metric_formatting(self):
        self.assertEqual(report.fmt_metric("engagementRate", "0.6234"), "62%")
        self.assertEqual(report.fmt_metric("averageSessionDuration", "45.6"), "46s")
        self.assertEqual(report.fmt_metric("sessions", "1234"), "1,234")
        self.assertEqual(report.fmt_metric("sessions", "n/a"), "n/a")

    def test_render_table_escapes_pipes_and_notes(self):
        table = report.Table("T", ["A", "B"], [["x|y", "1"]], note="hint")
        text = report.render_table(table)
        self.assertIn("| x\\|y | 1 |", text)
        self.assertIn("_hint_", text)

    def test_render_table_error_and_empty(self):
        self.assertIn("_Not available: boom_", report.render_table(report.Table("T", [], [], error="boom")))
        self.assertIn("_No rows for this window._", report.render_table(report.Table("T", ["A"], [])))


class BuildReportTests(unittest.TestCase):
    def _api(self, **kwargs):
        responses = {
            RUN_REPORT: _run_report,
            GSC_QUERY: lambda body: (
                {"rows": [{"keys": [], "clicks": 12, "impressions": 300, "ctr": 0.04, "position": 8.25}]}
                if "dimensions" not in body
                else {"rows": [{"keys": ["fractional cto hong kong"], "clicks": 4, "impressions": 90, "ctr": 0.044, "position": 6.1}]}
            ),
            GSC_SITEMAPS: {
                "sitemap": [{
                    "path": "https://www.example.com/sitemap.xml",
                    "lastSubmitted": "2026-10-01T09:00:00.000Z",
                    "lastDownloaded": "2026-10-03T02:00:00.000Z",
                    "errors": "0",
                    "contents": [{"type": "web", "submitted": "9", "indexed": "0"}],
                }]
            },
        }
        return FakeApi(responses, **kwargs)

    def test_full_report(self):
        api = self._api()
        data = report.build_report(api, "42", "https://www.example.com", "sc-domain:example.com", 28, date(2026, 10, 4))
        self.assertEqual(data.errors, [])
        self.assertEqual(data.totals.rows[1], ["Last 28 days", "103", "94", "80", "118", "62%", "45s"])
        titles = [t.title for t in data.breakdowns]
        self.assertEqual(titles, [b.title for b in report.BREAKDOWNS])
        channels = data.breakdowns[0]
        self.assertEqual(channels.columns, ["Channel", "Sessions", "Users", "Engagement"])
        self.assertEqual(channels.rows[0], ["Direct", "60", "55", "70%"])
        contact = next(t for t in data.breakdowns if t.title == "Contact clicks by channel")
        self.assertEqual(contact.rows, [["email", "5"], ["whatsapp", "3"]])
        events = next(t for t in data.breakdowns if t.title == "Events")
        self.assertEqual(events.rows, [])
        self.assertEqual(data.gsc_totals.rows, [["12", "300", "4.0%", "8.2"]])
        self.assertEqual(data.gsc_queries.rows[0][0], "fractional cto hong kong")
        self.assertEqual(data.gsc_sitemaps.rows[0], ["https://www.example.com/sitemap.xml", "2026-10-01", "2026-10-03", "9", "0", "no"])

        md = report.render_markdown(data)
        self.assertIn("# Public website traffic: https://www.example.com", md)
        self.assertIn("Window: 2026-09-06 to 2026-10-03 (28 days)", md)
        self.assertIn("| Last 28 days | 103 | 94 | 80 | 118 | 62% | 45s |", md)
        self.assertIn("### Top queries", md)
        self.assertNotIn("## Errors", md)

        as_json = data.to_json()
        self.assertEqual(as_json["windowDays"], 28)
        self.assertEqual(as_json["searchConsole"]["totals"]["rows"], [["12", "300", "4.0%", "8.2"]])

        # One totals call, one per breakdown, three GSC queries, one sitemap list.
        posts = [c for c in api.calls if c[0] == "POST"]
        self.assertEqual(len(posts), 1 + len(report.BREAKDOWNS) + 3)
        self.assertEqual(posts[0][2]["dateRanges"], [
            {"startDate": "2026-09-27", "endDate": "2026-10-03"},
            {"startDate": "2026-09-06", "endDate": "2026-10-03"},
            {"startDate": "2026-07-06", "endDate": "2026-10-03"},
        ])
        self.assertEqual([c for c in api.calls if c[0] == "GET"], [("GET", GSC_SITEMAPS, None)])

    def test_skip_gsc(self):
        api = self._api()
        data = report.build_report(api, "42", "https://www.example.com", "sc-domain:example.com", 7, date(2026, 10, 4),
                                   include_gsc=False)
        self.assertIsNone(data.gsc_totals)
        self.assertFalse(any("webmasters" in c[1] for c in api.calls))

    def test_totals_failure_short_circuits(self):
        api = self._api(fail={RUN_REPORT: (403, {"error": {"status": "PERMISSION_DENIED", "details": [{"reason": "SERVICE_DISABLED"}]}})})
        data = report.build_report(api, "42", "https://www.example.com", "sc-domain:example.com", 28, date(2026, 10, 4))
        self.assertEqual(len(data.errors), 1)
        self.assertIn("analyticsdata.googleapis.com", data.errors[0])
        self.assertEqual(data.breakdowns, [])
        self.assertIn("## Errors", report.render_markdown(data))

    def test_gsc_failure_is_reported_per_table(self):
        api = self._api(fail={GSC_QUERY: (403, {"error": {"status": "PERMISSION_DENIED"}})})
        data = report.build_report(api, "42", "https://www.example.com", "sc-domain:example.com", 28, date(2026, 10, 4))
        self.assertEqual(data.errors, [])
        self.assertTrue(data.gsc_queries.error.startswith("PERMISSION_DENIED"))
        self.assertEqual(data.gsc_sitemaps.rows[0][3], "9")


if __name__ == "__main__":
    unittest.main()
