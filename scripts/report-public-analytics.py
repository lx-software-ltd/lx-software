#!/usr/bin/env python3
"""Read-only traffic report for the public website.

Pulls the GA4 Data API and the Search Console API with the same service
account as ``configure-public-analytics.py`` and prints one Markdown report:

* GA4 totals for the last 7 / 28 / 90 days (sessions, users, new users,
  page views, engagement rate, average session duration)
* GA4 breakdowns for the main window (``--days``, default 28): channel
  group, source / medium, country, landing page, page path, event counts,
  ``contact_click`` by channel, ``faq_toggle`` questions, ``project_open``
  projects, ``cta_click`` pages
* Search Console for the same window: totals, top queries, top pages,
  and sitemap status

Nothing is written to Google. Run it before the monthly content review or
pass ``--json`` to feed another tool.

Usage::

  python3 scripts/report-public-analytics.py [--days 28] [--json] [--no-gsc]
                                              [--out report.md]

Credentials: ``LXSOFTWARE_GOOGLE_SERVICE_ACCOUNT_JSON`` (the key JSON as a
string) or ``GOOGLE_APPLICATION_CREDENTIALS`` (a path). The service account
needs Viewer on the GA4 property and at least Restricted on the Search Console
property, with the Analytics Data API and Search Console API enabled in its
Cloud project.

Environment::

  LXSOFTWARE_GA4_PROPERTY_ID   numeric GA4 property id (required)
  LXSOFTWARE_SITE_URL          site origin; default read from
                               apps/public_www/src/content/site.json
  LXSOFTWARE_GSC_PROPERTY      Search Console property; default is the domain
                               property ``sc-domain:<registrable host>``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
SITE_JSON = ROOT / "apps" / "public_www" / "src" / "content" / "site.json"
DEFAULT_SITE_URL = "https://www.lx-software.com"

DATA_V1BETA = "https://analyticsdata.googleapis.com/v1beta"
WEBMASTERS_V3 = "https://www.googleapis.com/webmasters/v3"
SEARCHCONSOLE_V1 = "https://searchconsole.googleapis.com/v1"
SCOPES = (
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
)

TOTAL_WINDOWS = (7, 28, 90)
TOTAL_METRICS = (
    "sessions",
    "totalUsers",
    "newUsers",
    "screenPageViews",
    "engagementRate",
    "averageSessionDuration",
)
ROW_LIMIT = 15


# --------------------------------------------------------------------------
# HTTP


class ApiError(RuntimeError):
    def __init__(self, status: int, body: Any, url: str):
        super().__init__(f"HTTP {status} for {url}: {json.dumps(body)[:600]}")
        self.status = status
        self.body = body
        self.url = url

    def reason(self) -> str:
        err = self.body.get("error", {}) if isinstance(self.body, dict) else {}
        for d in err.get("details", []) or []:
            if d.get("reason"):
                return str(d["reason"])
        return str(err.get("status") or self.status)


class Api:
    """Thin JSON client over urllib; ``token`` is a bearer token."""

    def __init__(self, token: str):
        self.token = token

    def request(self, method: str, url: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                parsed = json.loads(raw) if raw else {}
            except ValueError:
                parsed = raw.decode(errors="replace")
            raise ApiError(e.code, parsed, url) from None
        return json.loads(raw) if raw else {}

    def get(self, url: str) -> Any:
        return self.request("GET", url)

    def post(self, url: str, body: Any = None) -> Any:
        return self.request("POST", url, body if body is not None else {})


def bearer_token() -> str:
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2 import service_account  # type: ignore
    except ImportError:
        sys.exit("google-auth is required: python3 -m pip install google-auth requests")
    raw = os.environ.get("LXSOFTWARE_GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        creds = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=list(SCOPES))
    else:
        path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if not path:
            sys.exit("Set LXSOFTWARE_GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS")
        creds = service_account.Credentials.from_service_account_file(path, scopes=list(SCOPES))
    creds.refresh(Request())
    return str(creds.token)


# --------------------------------------------------------------------------
# Site settings


def site_url() -> str:
    env = os.environ.get("LXSOFTWARE_SITE_URL", "").strip()
    if env:
        return env.rstrip("/")
    try:
        data = json.loads(SITE_JSON.read_text())
        return str(data["site"]["url"]).rstrip("/")
    except (OSError, KeyError, ValueError):
        return DEFAULT_SITE_URL


def gsc_property(origin: str) -> str:
    """Domain property for the registrable host (``www.`` stripped)."""
    env = os.environ.get("LXSOFTWARE_GSC_PROPERTY", "").strip()
    if env:
        return env
    host = urllib.parse.urlsplit(origin).hostname or origin
    if host.startswith("www."):
        host = host[4:]
    return f"sc-domain:{host}"


# --------------------------------------------------------------------------
# GA4 Data API


def ga_date_range(days: int, today: date) -> dict[str, str]:
    """Yesterday back ``days`` days; today is incomplete and skipped."""
    end = today - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return {"startDate": start.isoformat(), "endDate": end.isoformat()}


def ga_request(
    dimensions: tuple[str, ...],
    metrics: tuple[str, ...],
    date_ranges: list[dict[str, str]],
    *,
    event_name: str | None = None,
    order_by: str | None = None,
    limit: int = ROW_LIMIT,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "dateRanges": date_ranges,
        "dimensions": [{"name": d} for d in dimensions],
        "metrics": [{"name": m} for m in metrics],
        "limit": str(limit),
        "keepEmptyRows": False,
    }
    if event_name:
        body["dimensionFilter"] = {
            "filter": {
                "fieldName": "eventName",
                "stringFilter": {"matchType": "EXACT", "value": event_name},
            }
        }
    if order_by:
        body["orderBys"] = [{"metric": {"metricName": order_by}, "desc": True}]
    return body


def ga_rows(response: dict[str, Any]) -> list[tuple[list[str], list[str]]]:
    rows = []
    for row in response.get("rows", []) or []:
        dims = [d.get("value", "") for d in row.get("dimensionValues", [])]
        mets = [m.get("value", "0") for m in row.get("metricValues", [])]
        rows.append((dims, mets))
    return rows


@dataclass
class Breakdown:
    title: str
    dimensions: tuple[str, ...]
    metrics: tuple[str, ...]
    event_name: str | None = None
    note: str = ""


BREAKDOWNS = (
    Breakdown("Channels", ("sessionDefaultChannelGroup",), ("sessions", "totalUsers", "engagementRate")),
    Breakdown("Source / medium", ("sessionSourceMedium",), ("sessions", "totalUsers", "engagementRate")),
    Breakdown("Countries", ("country",), ("sessions", "totalUsers")),
    Breakdown("Landing pages", ("landingPagePlusQueryString",), ("sessions", "engagementRate")),
    Breakdown("Pages", ("pagePath",), ("screenPageViews", "totalUsers")),
    Breakdown("Events", ("eventName",), ("eventCount", "totalUsers")),
    Breakdown(
        "Contact clicks by channel",
        ("customEvent:channel",),
        ("eventCount",),
        event_name="contact_click",
        note="Which contact button people press (email, WhatsApp, WeChat, LinkedIn, phone).",
    ),
    Breakdown("FAQ questions opened", ("customEvent:question",), ("eventCount",), event_name="faq_toggle"),
    Breakdown("Projects opened", ("customEvent:project",), ("eventCount",), event_name="project_open"),
    Breakdown("CTA clicks by page", ("customEvent:page",), ("eventCount",), event_name="cta_click"),
)


@dataclass
class Table:
    title: str
    columns: list[str]
    rows: list[list[str]]
    note: str = ""
    error: str = ""


@dataclass
class ReportData:
    site: str
    gsc_property: str
    window_days: int
    date_range: dict[str, str]
    totals: Table | None = None
    breakdowns: list[Table] = field(default_factory=list)
    gsc_totals: Table | None = None
    gsc_queries: Table | None = None
    gsc_pages: Table | None = None
    gsc_sitemaps: Table | None = None
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        def table(t: Table | None) -> Any:
            if t is None:
                return None
            return {"title": t.title, "columns": t.columns, "rows": t.rows, "note": t.note, "error": t.error}

        return {
            "site": self.site,
            "gscProperty": self.gsc_property,
            "windowDays": self.window_days,
            "dateRange": self.date_range,
            "totals": table(self.totals),
            "breakdowns": [table(t) for t in self.breakdowns],
            "searchConsole": {
                "totals": table(self.gsc_totals),
                "queries": table(self.gsc_queries),
                "pages": table(self.gsc_pages),
                "sitemaps": table(self.gsc_sitemaps),
            },
            "errors": self.errors,
        }


def fmt_metric(name: str, value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    if name == "engagementRate":
        return f"{number * 100:.0f}%"
    if name == "averageSessionDuration":
        return f"{number:.0f}s"
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:.2f}"


METRIC_LABELS = {
    "sessions": "Sessions",
    "totalUsers": "Users",
    "newUsers": "New users",
    "screenPageViews": "Page views",
    "engagementRate": "Engagement",
    "averageSessionDuration": "Avg. session",
    "eventCount": "Events",
}
DIMENSION_LABELS = {
    "sessionDefaultChannelGroup": "Channel",
    "sessionSourceMedium": "Source / medium",
    "country": "Country",
    "landingPagePlusQueryString": "Landing page",
    "pagePath": "Path",
    "eventName": "Event",
    "customEvent:channel": "Channel",
    "customEvent:question": "Question",
    "customEvent:project": "Project",
    "customEvent:page": "Page",
}


def label(name: str) -> str:
    return METRIC_LABELS.get(name) or DIMENSION_LABELS.get(name) or name


def ga_totals(post: Callable[[str, dict[str, Any]], dict[str, Any]], property_id: str, today: date) -> Table:
    ranges = [ga_date_range(days, today) for days in TOTAL_WINDOWS]
    body = ga_request((), TOTAL_METRICS, ranges, limit=len(TOTAL_WINDOWS))
    response = post(f"{DATA_V1BETA}/properties/{property_id}:runReport", body)
    # With several date ranges and no dimensions the API adds a dateRange
    # dimension (date_range_0, ...) and returns one row per range.
    by_range: dict[str, list[str]] = {}
    for dims, mets in ga_rows(response):
        key = dims[0] if dims else "date_range_0"
        by_range[key] = mets
    rows = []
    for index, days in enumerate(TOTAL_WINDOWS):
        mets = by_range.get(f"date_range_{index}", ["0"] * len(TOTAL_METRICS))
        rows.append([f"Last {days} days"] + [fmt_metric(m, v) for m, v in zip(TOTAL_METRICS, mets)])
    return Table("Totals", ["Window"] + [label(m) for m in TOTAL_METRICS], rows,
                 note="Ends yesterday; today is incomplete and left out.")


def ga_breakdown(
    post: Callable[[str, dict[str, Any]], dict[str, Any]],
    property_id: str,
    spec: Breakdown,
    date_range: dict[str, str],
) -> Table:
    body = ga_request(spec.dimensions, spec.metrics, [date_range], event_name=spec.event_name, order_by=spec.metrics[0])
    columns = [label(d) for d in spec.dimensions] + [label(m) for m in spec.metrics]
    try:
        response = post(f"{DATA_V1BETA}/properties/{property_id}:runReport", body)
    except ApiError as e:
        return Table(spec.title, columns, [], spec.note, error=f"{e.reason()}: {str(e)[:200]}")
    rows = [dims + [fmt_metric(m, v) for m, v in zip(spec.metrics, mets)] for dims, mets in ga_rows(response)]
    return Table(spec.title, columns, rows, spec.note)


# --------------------------------------------------------------------------
# Search Console


def gsc_query_body(date_range: dict[str, str], dimensions: list[str], limit: int = ROW_LIMIT) -> dict[str, Any]:
    body: dict[str, Any] = {
        "startDate": date_range["startDate"],
        "endDate": date_range["endDate"],
        "rowLimit": limit,
        "dataState": "all",
    }
    if dimensions:
        body["dimensions"] = dimensions
    return body


def gsc_rows(response: dict[str, Any]) -> list[list[str]]:
    rows = []
    for row in response.get("rows", []) or []:
        keys = list(row.get("keys", []))
        rows.append(keys + [
            fmt_metric("clicks", str(row.get("clicks", 0))),
            fmt_metric("impressions", str(row.get("impressions", 0))),
            f"{float(row.get('ctr', 0)) * 100:.1f}%",
            f"{float(row.get('position', 0)):.1f}",
        ])
    return rows


GSC_COLUMNS = ["Clicks", "Impressions", "CTR", "Position"]


def gsc_report(
    post: Callable[[str, dict[str, Any]], dict[str, Any]],
    get: Callable[[str], dict[str, Any]],
    prop: str,
    date_range: dict[str, str],
) -> tuple[Table, Table, Table, Table]:
    encoded = urllib.parse.quote(prop, safe="")
    query_url = f"{WEBMASTERS_V3}/sites/{encoded}/searchAnalytics/query"

    def query(title: str, dimensions: list[str]) -> Table:
        try:
            response = post(query_url, gsc_query_body(date_range, dimensions))
        except ApiError as e:
            return Table(title, dimensions + GSC_COLUMNS, [], error=f"{e.reason()}: {str(e)[:200]}")
        rows = gsc_rows(response)
        if not dimensions and not rows:
            rows = [["0", "0", "0.0%", "0.0"]]
        return Table(title, [d.title() for d in dimensions] + GSC_COLUMNS, rows)

    totals = query("Search totals", [])
    queries = query("Top queries", ["query"])
    pages = query("Top pages", ["page"])

    sitemap_table: Table
    try:
        response = get(f"{WEBMASTERS_V3}/sites/{encoded}/sitemaps")
        rows = []
        for sitemap in response.get("sitemap", []) or []:
            submitted = sum(int(c.get("submitted", 0)) for c in sitemap.get("contents", []) or [])
            indexed = sum(int(c.get("indexed", 0)) for c in sitemap.get("contents", []) or [])
            rows.append([
                str(sitemap.get("path", "")),
                str(sitemap.get("lastSubmitted", ""))[:10],
                str(sitemap.get("lastDownloaded", ""))[:10],
                str(submitted),
                str(indexed),
                "yes" if sitemap.get("errors", "0") not in ("0", 0) else "no",
            ])
        sitemap_table = Table("Sitemaps", ["Path", "Submitted", "Downloaded", "URLs", "Indexed", "Errors"], rows,
                              note="Indexed counts stay 0 until Google reports them; use URL Inspection for a single page.")
    except ApiError as e:
        sitemap_table = Table("Sitemaps", [], [], error=f"{e.reason()}: {str(e)[:200]}")
    return totals, queries, pages, sitemap_table


# --------------------------------------------------------------------------
# Rendering


def render_table(table: Table) -> str:
    lines = [f"### {table.title}", ""]
    if table.error:
        lines.append(f"_Not available: {table.error}_")
        lines.append("")
        return "\n".join(lines)
    if not table.rows:
        lines.append("_No rows for this window._")
        lines.append("")
        return "\n".join(lines)
    lines.append("| " + " | ".join(table.columns) + " |")
    lines.append("|" + "|".join(" --- " for _ in table.columns) + "|")
    for row in table.rows:
        cells = [str(c).replace("|", "\\|") for c in row]
        lines.append("| " + " | ".join(cells) + " |")
    if table.note:
        lines.append("")
        lines.append(f"_{table.note}_")
    lines.append("")
    return "\n".join(lines)


def render_markdown(data: ReportData) -> str:
    rng = data.date_range
    out = [
        f"# Public website traffic: {data.site}",
        "",
        f"Window: {rng['startDate']} to {rng['endDate']} ({data.window_days} days). "
        f"Search Console property: `{data.gsc_property}`.",
        "",
        "## Google Analytics 4",
        "",
    ]
    if data.totals:
        out.append(render_table(data.totals))
    for table in data.breakdowns:
        out.append(render_table(table))
    out += ["## Google Search Console", ""]
    for table in (data.gsc_totals, data.gsc_queries, data.gsc_pages, data.gsc_sitemaps):
        if table is not None:
            out.append(render_table(table))
    if data.errors:
        out += ["## Errors", ""] + [f"- {e}" for e in data.errors] + [""]
    return "\n".join(out).rstrip() + "\n"


def explain_access_error(e: ApiError) -> str:
    reason = e.reason()
    if reason == "SERVICE_DISABLED":
        return (
            "An API is disabled for the service account's Cloud project. Enable:\n"
            "  https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com\n"
            "  https://console.cloud.google.com/apis/library/searchconsole.googleapis.com"
        )
    if e.status in (401, 403):
        return (
            "The service account lacks access. Add it as Viewer on the GA4 property "
            "(Admin → Property access management) and as a user on the Search Console property."
        )
    return str(e)


# --------------------------------------------------------------------------
# Main


def build_report(
    api: Api,
    property_id: str,
    origin: str,
    prop: str,
    days: int,
    today: date,
    include_gsc: bool = True,
) -> ReportData:
    date_range = ga_date_range(days, today)
    data = ReportData(site=origin, gsc_property=prop, window_days=days, date_range=date_range)
    try:
        data.totals = ga_totals(api.post, property_id, today)
    except ApiError as e:
        data.errors.append(f"GA4 totals: {explain_access_error(e)}")
        return data
    for spec in BREAKDOWNS:
        data.breakdowns.append(ga_breakdown(api.post, property_id, spec, date_range))
    if include_gsc:
        data.gsc_totals, data.gsc_queries, data.gsc_pages, data.gsc_sitemaps = gsc_report(
            api.post, api.get, prop, date_range
        )
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=28, help="breakdown window in days (default 28)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    parser.add_argument("--no-gsc", action="store_true", help="skip Search Console")
    parser.add_argument("--out", help="also write the report to this file")
    args = parser.parse_args(argv)
    if args.days < 1 or args.days > 365:
        parser.error("--days must be between 1 and 365")

    property_id = os.environ.get("LXSOFTWARE_GA4_PROPERTY_ID", "").strip()
    if not property_id:
        sys.exit("Set LXSOFTWARE_GA4_PROPERTY_ID")
    origin = site_url()
    prop = gsc_property(origin)

    api = Api(bearer_token())
    data = build_report(api, property_id, origin, prop, args.days, date.today(), include_gsc=not args.no_gsc)
    text = json.dumps(data.to_json(), indent=2) + "\n" if args.json else render_markdown(data)
    sys.stdout.write(text)
    if args.out:
        Path(args.out).write_text(text)
    return 1 if data.errors else 0


if __name__ == "__main__":
    sys.exit(main())
