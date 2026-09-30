#!/usr/bin/env python3
"""Check and apply the GA4 + Google Tag Manager setup for the public website.

The site (``apps/public_www``) loads one GTM container and pushes the events
listed in ``apps/public_www/src/lib/analytics.ts`` onto ``dataLayer``. This
script makes the Google side match:

GA4 property
  * time zone ``Asia/Hong_Kong``, currency ``HKD``
  * event data retention 14 months, reset on new activity
  * the web data stream for the site URL with every enhanced-measurement
    switch on (page changes for React Router, scroll, outbound click, site
    search, video, file download, form interaction)
  * e-mail redaction on the stream
  * one event-scoped custom dimension per site event parameter, so the
    parameters show up in reports and explorations
  * ``contact_click`` and ``project_open`` marked as key events

GTM web container (live version)
  * a Google tag carrying the stream's measurement id on Initialization
  * one Data Layer variable per site event parameter (``DL - <param>``)
  * one Custom Event trigger matching the site event names
  * one GA4 event tag (event name ``{{Event}}``) that forwards every
    parameter, on that trigger

``check`` prints the drift and exits 1 when anything differs. ``apply``
creates a fresh GTM workspace, writes the missing entities, creates a
version and publishes it (``--no-publish`` leaves the version unpublished).
Existing entities are never deleted.

Credentials: ``LXSOFTWARE_GOOGLE_SERVICE_ACCOUNT_JSON`` (the key JSON
itself) or ``GOOGLE_APPLICATION_CREDENTIALS`` (a path). The service account
needs Editor on the GA4 property and Publish on the GTM container, and the
Google Analytics Admin API plus Tag Manager API must be enabled in the
service account's Cloud project. Requires ``google-auth``.

Usage:
  python3 scripts/configure-public-analytics.py check
  python3 scripts/configure-public-analytics.py apply [--no-publish]

Environment:
  LXSOFTWARE_GA4_PROPERTY_ID   numeric GA4 property id
  LXSOFTWARE_GTM_ACCOUNT_ID    numeric Tag Manager account id
  LXSOFTWARE_CONTAINER_ID      GTM-XXXXXXX public container id
  PUBLIC_SITE_URL              defaults to https://www.lx-software.com
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

# Keep in step with apps/public_www/src/lib/analytics.ts
# (scripts/test_configure_public_analytics.py checks both lists).
SITE_EVENT_NAMES = (
    "contact_click",
    "faq_toggle",
    "project_open",
    "project_navigate",
    "nav_click",
    "page_not_found",
    "media_error",
)
SITE_EVENT_PARAMS = (
    "channel",
    "destination",
    "question",
    "state",
    "project",
    "direction",
    "method",
    "section",
    "path",
    "source",
)
KEY_EVENTS = ("contact_click", "project_open")

DEFAULT_SITE_URL = "https://www.lx-software.com"
TIME_ZONE = "Asia/Hong_Kong"
CURRENCY = "HKD"
RETENTION = "FOURTEEN_MONTHS"
ENHANCED_MEASUREMENT = {
    "streamEnabled": True,
    "scrollsEnabled": True,
    "outboundClicksEnabled": True,
    "siteSearchEnabled": True,
    "videoEngagementEnabled": True,
    "fileDownloadsEnabled": True,
    "pageChangesEnabled": True,
    "formInteractionsEnabled": True,
}

GOOGLE_TAG_NAME = "Google tag - GA4"
EVENT_TAG_NAME = "GA4 event - site events"
EVENT_TRIGGER_NAME = "Site events"
# GTM's built-in "Initialization - All Pages" trigger.
INITIALIZATION_TRIGGER_ID = "2147479573"

ADMIN_V1BETA = "https://analyticsadmin.googleapis.com/v1beta"
ADMIN_V1ALPHA = "https://analyticsadmin.googleapis.com/v1alpha"
TAGMANAGER_V2 = "https://tagmanager.googleapis.com/tagmanager/v2"
SCOPES = (
    "https://www.googleapis.com/auth/analytics.edit",
    "https://www.googleapis.com/auth/tagmanager.edit.containers",
    "https://www.googleapis.com/auth/tagmanager.edit.containerversions",
    "https://www.googleapis.com/auth/tagmanager.publish",
)


def dl_variable_name(param: str) -> str:
    return f"DL - {param}"


def site_event_regex(names: tuple[str, ...] = SITE_EVENT_NAMES) -> str:
    return "^(" + "|".join(re.escape(n) for n in names) + ")$"


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

    def get(self, url: str, **params: str) -> Any:
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        return self.request("GET", url)

    def post(self, url: str, body: Any = None) -> Any:
        return self.request("POST", url, body if body is not None else {})

    def patch(self, url: str, body: Any, update_mask: str) -> Any:
        return self.request("PATCH", f"{url}?updateMask={urllib.parse.quote(update_mask)}", body)

    def delete(self, url: str) -> Any:
        return self.request("DELETE", url)


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
# Plan model


@dataclass
class Change:
    area: str  # "ga4" | "gtm"
    summary: str
    apply: Callable[[Api], Any] | None = None  # None = report only


@dataclass
class Report:
    ok: list[str] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)

    def note(self, line: str) -> None:
        self.ok.append(line)

    def drift(self, area: str, summary: str, apply: Callable[[Api], Any] | None = None) -> None:
        self.changes.append(Change(area, summary, apply))

    @property
    def fixable(self) -> list[Change]:
        return [c for c in self.changes if c.apply is not None]

    @property
    def manual(self) -> list[Change]:
        return [c for c in self.changes if c.apply is None]


# --------------------------------------------------------------------------
# GA4


@dataclass
class Ga4State:
    property: dict
    retention: dict
    streams: list[dict]
    stream: dict | None
    enhanced: dict | None
    redaction: dict | None
    custom_dimensions: list[dict]
    key_events: list[dict]

    @property
    def measurement_id(self) -> str:
        if not self.stream:
            return ""
        return str(self.stream.get("webStreamData", {}).get("measurementId", ""))


def _paged(api: Api, url: str, key: str) -> list[dict]:
    items: list[dict] = []
    token = ""
    while True:
        page = api.get(url, pageSize="200", **({"pageToken": token} if token else {}))
        items.extend(page.get(key, []) or [])
        token = page.get("nextPageToken", "")
        if not token:
            return items


def pick_web_stream(streams: list[dict], site_url: str) -> dict | None:
    host = urllib.parse.urlparse(site_url).hostname or ""
    web = [s for s in streams if s.get("type") == "WEB_DATA_STREAM"]
    for s in web:
        uri = s.get("webStreamData", {}).get("defaultUri", "")
        if (urllib.parse.urlparse(uri).hostname or "") == host:
            return s
    return web[0] if web else None


def read_ga4(api: Api, property_id: str, site_url: str) -> Ga4State:
    base = f"{ADMIN_V1BETA}/properties/{property_id}"
    prop = api.get(base)
    retention = api.get(f"{base}/dataRetentionSettings")
    streams = _paged(api, f"{base}/dataStreams", "dataStreams")
    stream = pick_web_stream(streams, site_url)
    enhanced = redaction = None
    if stream:
        alpha = f"{ADMIN_V1ALPHA}/{stream['name']}"
        enhanced = api.get(f"{alpha}/enhancedMeasurementSettings")
        redaction = api.get(f"{alpha}/dataRedactionSettings")
    dims = _paged(api, f"{base}/customDimensions", "customDimensions")
    keys = _paged(api, f"{base}/keyEvents", "keyEvents")
    return Ga4State(prop, retention, streams, stream, enhanced, redaction, dims, keys)


def plan_ga4(state: Ga4State, property_id: str, site_url: str, report: Report) -> None:
    base = f"{ADMIN_V1BETA}/properties/{property_id}"
    prop = state.property
    report.note(f"GA4 property {property_id}: {prop.get('displayName', '?')}")

    prop_patch: dict[str, str] = {}
    if prop.get("timeZone") != TIME_ZONE:
        prop_patch["timeZone"] = TIME_ZONE
    if prop.get("currencyCode") != CURRENCY:
        prop_patch["currencyCode"] = CURRENCY
    if prop_patch:
        report.drift(
            "ga4",
            f"property {', '.join(f'{k} {prop.get(k)!r} -> {v!r}' for k, v in prop_patch.items())}",
            lambda api: api.patch(base, prop_patch, ",".join(prop_patch)),
        )
    else:
        report.note(f"  time zone {TIME_ZONE}, currency {CURRENCY}")

    ret = state.retention
    ret_patch: dict[str, Any] = {}
    if ret.get("eventDataRetention") != RETENTION:
        ret_patch["eventDataRetention"] = RETENTION
    if ret.get("resetUserDataOnNewActivity") is not True:
        ret_patch["resetUserDataOnNewActivity"] = True
    if ret_patch:
        report.drift(
            "ga4",
            f"data retention {ret.get('eventDataRetention')} -> {RETENTION}, reset on new activity",
            lambda api: api.patch(f"{base}/dataRetentionSettings", ret_patch, ",".join(ret_patch)),
        )
    else:
        report.note("  event data retention 14 months")

    stream = state.stream
    if not stream:
        report.drift(
            "ga4",
            f"no web data stream for {site_url}; create one in Admin -> Data streams "
            "(a new stream means a new measurement id and a GTM change)",
        )
        return
    uri = stream.get("webStreamData", {}).get("defaultUri", "")
    report.note(f"  web stream {stream.get('displayName')} ({state.measurement_id}) for {uri}")
    if (urllib.parse.urlparse(uri).hostname or "") != (urllib.parse.urlparse(site_url).hostname or ""):
        report.drift("ga4", f"web stream URL is {uri!r}, expected host of {site_url}")
    if len([s for s in state.streams if s.get("type") == "WEB_DATA_STREAM"]) > 1:
        report.drift("ga4", "more than one web stream on the property; only the site stream is managed")

    alpha = f"{ADMIN_V1ALPHA}/{stream['name']}"
    enhanced = state.enhanced or {}
    em_patch = {k: v for k, v in ENHANCED_MEASUREMENT.items() if enhanced.get(k) is not v}
    if em_patch:
        report.drift(
            "ga4",
            "enhanced measurement: switch on " + ", ".join(sorted(em_patch)),
            lambda api: api.patch(f"{alpha}/enhancedMeasurementSettings", em_patch, ",".join(em_patch)),
        )
    else:
        report.note("  enhanced measurement: all switches on")

    redaction = state.redaction or {}
    if redaction.get("emailRedactionEnabled") is not True:
        report.drift(
            "ga4",
            "e-mail redaction off on the web stream",
            lambda api: api.patch(
                f"{alpha}/dataRedactionSettings",
                {"emailRedactionEnabled": True},
                "emailRedactionEnabled",
            ),
        )
    else:
        report.note("  e-mail redaction on")

    existing = {d.get("parameterName"): d for d in state.custom_dimensions if d.get("scope") == "EVENT"}
    missing = [p for p in SITE_EVENT_PARAMS if p not in existing]
    for param in missing:
        body = {"parameterName": param, "displayName": param, "scope": "EVENT"}
        report.drift(
            "ga4",
            f"custom dimension (event) {param}",
            lambda api, body=body: api.post(f"{base}/customDimensions", body),
        )
    if not missing:
        report.note(f"  custom dimensions: {', '.join(SITE_EVENT_PARAMS)}")

    have_keys = {k.get("eventName") for k in state.key_events}
    for name in KEY_EVENTS:
        if name in have_keys:
            continue
        body = {"eventName": name, "countingMethod": "ONCE_PER_EVENT"}
        report.drift(
            "ga4",
            f"key event {name}",
            lambda api, body=body: api.post(f"{base}/keyEvents", body),
        )
    if all(name in have_keys for name in KEY_EVENTS):
        report.note(f"  key events: {', '.join(KEY_EVENTS)}")


# --------------------------------------------------------------------------
# GTM


def param(entity: dict, key: str) -> Any:
    for p in entity.get("parameter", []) or []:
        if p.get("key") == key:
            return p.get("value") if "value" in p else p.get("list", p.get("map"))
    return None


def find_container(api: Api, account_id: str, public_id: str) -> dict:
    page = api.get(f"{TAGMANAGER_V2}/accounts/{account_id}/containers")
    for c in page.get("container", []) or []:
        if c.get("publicId", "").upper() == public_id.upper():
            return c
    raise SystemExit(f"container {public_id} not found in GTM account {account_id}")


def read_live(api: Api, container_path: str) -> dict:
    try:
        return api.get(f"{TAGMANAGER_V2}/{container_path}/versions:live")
    except ApiError as e:
        if e.status == 404:
            return {}
        raise


def google_tag_body(measurement_id: str) -> dict:
    return {
        "name": GOOGLE_TAG_NAME,
        "type": "googtag",
        "parameter": [{"type": "template", "key": "tagId", "value": measurement_id}],
        "firingTriggerId": [INITIALIZATION_TRIGGER_ID],
    }


def dl_variable_body(name: str) -> dict:
    return {
        "name": dl_variable_name(name),
        "type": "v",
        "parameter": [
            {"type": "integer", "key": "dataLayerVersion", "value": "2"},
            {"type": "boolean", "key": "setDefaultValue", "value": "false"},
            {"type": "template", "key": "name", "value": name},
        ],
    }


def event_trigger_body() -> dict:
    return {
        "name": EVENT_TRIGGER_NAME,
        "type": "customEvent",
        "customEventFilter": [
            {
                "type": "matchRegex",
                "parameter": [
                    {"type": "template", "key": "arg0", "value": "{{_event}}"},
                    {"type": "template", "key": "arg1", "value": site_event_regex()},
                ],
            }
        ],
    }


def event_tag_body(measurement_id: str, trigger_id: str) -> dict:
    rows = [
        {
            "type": "map",
            "map": [
                {"type": "template", "key": "parameter", "value": p},
                {"type": "template", "key": "parameterValue", "value": "{{" + dl_variable_name(p) + "}}"},
            ],
        }
        for p in SITE_EVENT_PARAMS
    ]
    return {
        "name": EVENT_TAG_NAME,
        "type": "gaawe",
        "parameter": [
            {"type": "boolean", "key": "sendEcommerceData", "value": "false"},
            {"type": "boolean", "key": "enhancedUserId", "value": "false"},
            {"type": "template", "key": "eventName", "value": "{{Event}}"},
            {"type": "template", "key": "measurementIdOverride", "value": measurement_id},
            {"type": "list", "key": "eventSettingsTable", "list": rows},
        ],
        "firingTriggerId": [trigger_id],
    }


@dataclass
class GtmPlan:
    """What ``apply`` must create in a workspace, in dependency order."""

    google_tag: bool = False
    variables: list[str] = field(default_factory=list)
    trigger: bool = False
    event_tag: bool = False
    builtin_event: bool = False

    def empty(self) -> bool:
        return not (self.google_tag or self.variables or self.trigger or self.event_tag or self.builtin_event)


def via_gtm_plan(_api: Api) -> None:
    """Marker for drift that ``apply_gtm`` fixes through the workspace plan."""


def plan_gtm(live: dict, measurement_id: str, container: dict, report: Report) -> GtmPlan:
    plan = GtmPlan()
    tags = live.get("tag", []) or []
    triggers = live.get("trigger", []) or []
    variables = live.get("variable", []) or []
    builtins = {b.get("type") for b in live.get("builtInVariable", []) or []}
    version = live.get("containerVersionId", "none")
    report.note(f"GTM container {container.get('publicId')} ({container.get('name')}), live version {version}")

    googtags = [t for t in tags if t.get("type") == "googtag"]
    if not measurement_id:
        report.drift("gtm", "cannot verify the Google tag without a GA4 web stream")
    elif not googtags:
        report.drift("gtm", f"Google tag with {measurement_id} on Initialization - All Pages", via_gtm_plan)
        plan.google_tag = True
    else:
        ids = [param(t, "tagId") for t in googtags]
        if measurement_id in ids:
            report.note(f"  Google tag {measurement_id} present")
        else:
            # Adding a second Google tag would double-configure gtag; the
            # owner decides which stream the container should feed.
            report.drift("gtm", f"Google tag carries {ids}, GA4 stream is {measurement_id}")
        if len(googtags) > 1:
            report.drift("gtm", f"{len(googtags)} Google tags in the container; expected one")

    have_vars = {v.get("name") for v in variables if v.get("type") == "v"}
    plan.variables = [p for p in SITE_EVENT_PARAMS if dl_variable_name(p) not in have_vars]
    if plan.variables:
        report.drift(
            "gtm",
            "Data Layer variables: " + ", ".join(dl_variable_name(p) for p in plan.variables),
            via_gtm_plan,
        )
    else:
        report.note("  Data Layer variables present for every site event parameter")

    if "event" not in builtins:
        plan.builtin_event = True
        report.drift("gtm", "built-in variable {{Event}}", via_gtm_plan)

    trigger = next(
        (
            t
            for t in triggers
            if t.get("type") == "customEvent" and t.get("name") == EVENT_TRIGGER_NAME
        ),
        None,
    )
    want_regex = site_event_regex()
    if trigger is None:
        plan.trigger = True
        report.drift("gtm", f"Custom Event trigger {EVENT_TRIGGER_NAME!r} for {want_regex}", via_gtm_plan)
    else:
        got = ""
        for f in trigger.get("customEventFilter", []) or []:
            got = param(f, "arg1") or ""
        if got != want_regex:
            report.drift("gtm", f"trigger {EVENT_TRIGGER_NAME!r} matches {got!r}, expected {want_regex!r}")
        else:
            report.note(f"  trigger {EVENT_TRIGGER_NAME!r} covers {len(SITE_EVENT_NAMES)} site events")

    event_tag = next((t for t in tags if t.get("type") == "gaawe" and t.get("name") == EVENT_TAG_NAME), None)
    if event_tag is None:
        plan.event_tag = True
        report.drift(
            "gtm",
            f"GA4 event tag {EVENT_TAG_NAME!r} forwarding {len(SITE_EVENT_PARAMS)} parameters",
            via_gtm_plan,
        )
    else:
        rows = param(event_tag, "eventSettingsTable") or []
        forwarded = set()
        for row in rows:
            entries = {m.get("key"): m.get("value") for m in row.get("map", []) or []}
            if entries.get("parameter"):
                forwarded.add(entries["parameter"])
        missing = [p for p in SITE_EVENT_PARAMS if p not in forwarded]
        mid = param(event_tag, "measurementIdOverride")
        if missing:
            report.drift("gtm", f"event tag does not forward: {', '.join(missing)}")
        elif measurement_id and mid not in (measurement_id, None, ""):
            report.drift("gtm", f"event tag sends to {mid}, GA4 stream is {measurement_id}")
        else:
            report.note(f"  event tag {EVENT_TAG_NAME!r} forwards every parameter")
    return plan


def apply_gtm(api: Api, container_path: str, live: dict, plan: GtmPlan, measurement_id: str, publish: bool) -> str:
    # GTM rejects ":" in workspace and version names.
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H%M UTC")
    ws = api.post(
        f"{TAGMANAGER_V2}/{container_path}/workspaces",
        {"name": f"public-analytics {stamp}"[:64], "description": "scripts/configure-public-analytics.py"},
    )
    ws_path = ws["path"]
    try:
        if plan.builtin_event:
            api.post(f"{TAGMANAGER_V2}/{ws_path}/built_in_variables?type=event")
        if plan.google_tag:
            api.post(f"{TAGMANAGER_V2}/{ws_path}/tags", google_tag_body(measurement_id))
        for p in plan.variables:
            api.post(f"{TAGMANAGER_V2}/{ws_path}/variables", dl_variable_body(p))
        trigger_id = ""
        if plan.trigger:
            trigger_id = api.post(f"{TAGMANAGER_V2}/{ws_path}/triggers", event_trigger_body())["triggerId"]
        else:
            for t in live.get("trigger", []) or []:
                if t.get("name") == EVENT_TRIGGER_NAME:
                    trigger_id = t["triggerId"]
        if plan.event_tag:
            if not trigger_id:
                raise SystemExit("event trigger id unknown; cannot create the event tag")
            api.post(f"{TAGMANAGER_V2}/{ws_path}/tags", event_tag_body(measurement_id, trigger_id))
        version = api.post(
            f"{TAGMANAGER_V2}/{ws_path}:create_version",
            {"name": f"public analytics {stamp}", "notes": "configure-public-analytics.py"},
        )
        if version.get("compilerError"):
            raise SystemExit(f"GTM compiler error: {json.dumps(version)[:800]}")
        version_path = version["containerVersion"]["path"]
        if publish:
            api.post(f"{TAGMANAGER_V2}/{version_path}:publish")
        return version_path
    except Exception:
        try:
            api.delete(f"{TAGMANAGER_V2}/{ws_path}")
        except ApiError:
            pass
        raise


# --------------------------------------------------------------------------
# CLI


def print_report(report: Report) -> None:
    for line in report.ok:
        print(line)
    if report.changes:
        print("\nDrift:")
        for c in report.changes:
            flag = "fix " if c.apply is not None else "manual"
            print(f"  [{c.area}] ({flag}) {c.summary}")


def explain_access_error(e: ApiError) -> str:
    reason = e.reason()
    if reason == "SERVICE_DISABLED":
        return (
            f"{e}\n\nEnable the API in the service account's Cloud project (one click, no billing):\n"
            "  https://console.cloud.google.com/apis/library/analyticsadmin.googleapis.com\n"
            "  https://console.cloud.google.com/apis/library/tagmanager.googleapis.com"
        )
    if e.status in (401, 403):
        return (
            f"{e}\n\nGrant the service account e-mail Editor on the GA4 property "
            "(Admin -> Property access management) and Publish on the GTM container "
            "(Admin -> User management)."
        )
    return str(e)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("check", "apply"))
    ap.add_argument("--no-publish", action="store_true", help="create the GTM version without publishing")
    ap.add_argument("--site-url", default=os.environ.get("PUBLIC_SITE_URL", DEFAULT_SITE_URL))
    args = ap.parse_args(argv)

    property_id = os.environ.get("LXSOFTWARE_GA4_PROPERTY_ID", "").strip()
    account_id = os.environ.get("LXSOFTWARE_GTM_ACCOUNT_ID", "").strip()
    public_id = os.environ.get("LXSOFTWARE_CONTAINER_ID", "").strip().upper()
    for name, value in (
        ("LXSOFTWARE_GA4_PROPERTY_ID", property_id),
        ("LXSOFTWARE_GTM_ACCOUNT_ID", account_id),
        ("LXSOFTWARE_CONTAINER_ID", public_id),
    ):
        if not value:
            sys.exit(f"{name} is not set")

    api = Api(bearer_token())
    report = Report()
    try:
        ga4 = read_ga4(api, property_id, args.site_url)
        plan_ga4(ga4, property_id, args.site_url, report)
        container = find_container(api, account_id, public_id)
        live = read_live(api, container["path"])
        gtm_plan = plan_gtm(live, ga4.measurement_id, container, report)
    except ApiError as e:
        print(explain_access_error(e), file=sys.stderr)
        return 2

    print_report(report)
    if args.command == "check":
        return 1 if report.changes else 0

    for change in report.fixable:
        if change.apply is via_gtm_plan:
            continue
        print(f"apply: {change.summary}")
        change.apply(api)  # type: ignore[misc]
    if gtm_plan.empty():
        print("GTM live version already matches; nothing to publish")
    else:
        try:
            version_path = apply_gtm(api, container["path"], live, gtm_plan, ga4.measurement_id, not args.no_publish)
        except ApiError as e:
            print(explain_access_error(e), file=sys.stderr)
            return 2
        print(f"GTM version {'published' if not args.no_publish else 'created'}: {version_path}")
    if report.manual:
        print("\nStill needs the owner:")
        for c in report.manual:
            print(f"  [{c.area}] {c.summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
