#!/usr/bin/env python3
"""Unit tests for the GA4 / GTM drift planner (no network)."""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "configure-public-analytics.py"
ANALYTICS_TS = ROOT / "apps" / "public_www" / "src" / "lib" / "analytics.ts"


def _load_module():
    spec = importlib.util.spec_from_file_location("configure_public_analytics", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def _ts_array(source: str, name: str) -> tuple[str, ...]:
    match = re.search(rf"export const {name} = \[(.*?)\] as const", source, re.S)
    assert match, name
    return tuple(re.findall(r"'([a-z_]+)'", match.group(1)))


class FakeApi:
    def __init__(self, responses: dict[str, object] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, str, object]] = []

    def _key(self, url: str) -> str:
        return url.split("?")[0]

    def get(self, url, **params):
        self.calls.append(("GET", url, params))
        return self.responses.get(self._key(url), {})

    def post(self, url, body=None):
        self.calls.append(("POST", url, body))
        canned = self.responses.get(("POST", self._key(url)))
        return canned if canned is not None else {"triggerId": "7", "path": url + "/1"}

    def patch(self, url, body, update_mask):
        self.calls.append(("PATCH", url, (body, update_mask)))
        return {}

    def delete(self, url):
        self.calls.append(("DELETE", url, None))
        return {}


def _stream(measurement_id="G-TEST123456", uri="https://www.lx-software.com"):
    return {
        "name": "properties/1/dataStreams/9",
        "type": "WEB_DATA_STREAM",
        "displayName": "lx-software.com",
        "webStreamData": {"measurementId": measurement_id, "defaultUri": uri},
    }


class CatalogueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()

    def test_matches_analytics_ts(self) -> None:
        source = ANALYTICS_TS.read_text(encoding="utf-8")
        self.assertEqual(_ts_array(source, "SITE_EVENT_NAMES"), self.mod.SITE_EVENT_NAMES)
        self.assertEqual(_ts_array(source, "SITE_EVENT_PARAMS"), self.mod.SITE_EVENT_PARAMS)

    def test_key_events_are_site_events(self) -> None:
        for name in self.mod.KEY_EVENTS:
            self.assertIn(name, self.mod.SITE_EVENT_NAMES)

    def test_event_regex(self) -> None:
        regex = self.mod.site_event_regex(("a_b", "c"))
        self.assertEqual(regex, "^(a_b|c)$")
        full = re.compile(self.mod.site_event_regex())
        for name in self.mod.SITE_EVENT_NAMES:
            self.assertTrue(full.match(name))
        self.assertIsNone(full.match("gtm.js"))
        self.assertIsNone(full.match("contact_click_extra"))


class Ga4PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()

    def _state(self, **overrides):
        base = dict(
            property={"displayName": "LX Software", "timeZone": "Asia/Hong_Kong", "currencyCode": "HKD"},
            retention={"eventDataRetention": "FOURTEEN_MONTHS", "resetUserDataOnNewActivity": True},
            streams=[_stream()],
            stream=_stream(),
            enhanced=dict(self.mod.ENHANCED_MEASUREMENT),
            redaction={"emailRedactionEnabled": True},
            custom_dimensions=[
                {"parameterName": p, "scope": "EVENT"} for p in self.mod.SITE_EVENT_PARAMS
            ],
            key_events=[{"eventName": k} for k in self.mod.KEY_EVENTS],
        )
        base.update(overrides)
        return self.mod.Ga4State(**base)

    def test_no_drift_when_configured(self) -> None:
        report = self.mod.Report()
        self.mod.plan_ga4(self._state(), "1", "https://www.lx-software.com", report)
        self.assertEqual(report.changes, [])
        self.assertTrue(any("retention 14 months" in line for line in report.ok))

    def test_fresh_property_drift(self) -> None:
        state = self._state(
            property={"displayName": "LX Software", "timeZone": "America/Los_Angeles", "currencyCode": "USD"},
            retention={"eventDataRetention": "TWO_MONTHS"},
            enhanced={"streamEnabled": True, "pageChangesEnabled": False, "scrollsEnabled": True},
            redaction={},
            custom_dimensions=[],
            key_events=[],
        )
        report = self.mod.Report()
        self.mod.plan_ga4(state, "1", "https://www.lx-software.com", report)
        api = FakeApi()
        for change in report.fixable:
            change.apply(api)
        patches = {url: body for method, url, body in api.calls if method == "PATCH"}
        posts = [(url, body) for method, url, body in api.calls if method == "POST"]

        prop_body, prop_mask = patches[f"{self.mod.ADMIN_V1BETA}/properties/1"]
        self.assertEqual(prop_body, {"timeZone": "Asia/Hong_Kong", "currencyCode": "HKD"})
        self.assertEqual(prop_mask, "timeZone,currencyCode")

        ret_body, _ = patches[f"{self.mod.ADMIN_V1BETA}/properties/1/dataRetentionSettings"]
        self.assertEqual(ret_body, {"eventDataRetention": "FOURTEEN_MONTHS", "resetUserDataOnNewActivity": True})

        em_body, em_mask = patches[f"{self.mod.ADMIN_V1ALPHA}/properties/1/dataStreams/9/enhancedMeasurementSettings"]
        self.assertIn("pageChangesEnabled", em_body)
        self.assertNotIn("scrollsEnabled", em_body)
        self.assertEqual(set(em_mask.split(",")), set(em_body))

        red_body, _ = patches[f"{self.mod.ADMIN_V1ALPHA}/properties/1/dataStreams/9/dataRedactionSettings"]
        self.assertEqual(red_body, {"emailRedactionEnabled": True})

        dims = [b["parameterName"] for u, b in posts if u.endswith("/customDimensions")]
        self.assertEqual(tuple(dims), self.mod.SITE_EVENT_PARAMS)
        self.assertTrue(all(b["scope"] == "EVENT" for u, b in posts if u.endswith("/customDimensions")))
        keys = [b["eventName"] for u, b in posts if u.endswith("/keyEvents")]
        self.assertEqual(tuple(keys), self.mod.KEY_EVENTS)
        self.assertEqual(report.manual, [])

    def test_missing_stream_is_manual(self) -> None:
        report = self.mod.Report()
        self.mod.plan_ga4(self._state(streams=[], stream=None, enhanced=None, redaction=None), "1", "https://www.lx-software.com", report)
        self.assertEqual(len(report.manual), 1)
        self.assertIn("no web data stream", report.manual[0].summary)
        self.assertEqual(report.fixable, [])

    def test_pick_web_stream_prefers_site_host(self) -> None:
        other = _stream("G-OTHER", "https://staging.example.com")
        chosen = self.mod.pick_web_stream([other, _stream()], "https://www.lx-software.com/")
        self.assertEqual(chosen["webStreamData"]["measurementId"], "G-TEST123456")
        self.assertEqual(self.mod.pick_web_stream([other], "https://www.lx-software.com"), other)
        self.assertIsNone(self.mod.pick_web_stream([{"type": "IOS_APP_DATA_STREAM"}], "https://x"))


def _live_container(mod, measurement_id="G-TEST123456", complete=True):
    live = {
        "containerVersionId": "2",
        "tag": [
            {
                "name": "Google tag",
                "type": "googtag",
                "parameter": [{"type": "template", "key": "tagId", "value": measurement_id}],
            }
        ],
        "trigger": [],
        "variable": [],
        "builtInVariable": [],
    }
    if complete:
        live["builtInVariable"] = [{"type": "event"}]
        live["variable"] = [mod.dl_variable_body(p) for p in mod.SITE_EVENT_PARAMS]
        trigger = dict(mod.event_trigger_body(), triggerId="7")
        live["trigger"] = [trigger]
        live["tag"].append(mod.event_tag_body(measurement_id, "7"))
    return live


class GtmPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()
        self.container = {"publicId": "GTM-TEST123", "name": "www.lx-software.com", "path": "accounts/1/containers/2"}

    def test_live_matches(self) -> None:
        report = self.mod.Report()
        plan = self.mod.plan_gtm(_live_container(self.mod), "G-TEST123456", self.container, report)
        self.assertTrue(plan.empty())
        self.assertEqual(report.changes, [])

    def test_only_google_tag_published(self) -> None:
        report = self.mod.Report()
        plan = self.mod.plan_gtm(_live_container(self.mod, complete=False), "G-TEST123456", self.container, report)
        self.assertFalse(plan.google_tag)
        self.assertEqual(tuple(plan.variables), self.mod.SITE_EVENT_PARAMS)
        self.assertTrue(plan.trigger)
        self.assertTrue(plan.event_tag)
        self.assertTrue(plan.builtin_event)
        summaries = " | ".join(c.summary for c in report.changes)
        self.assertIn("Custom Event trigger", summaries)
        self.assertIn("GA4 event tag", summaries)

    def test_empty_container_plans_google_tag(self) -> None:
        report = self.mod.Report()
        plan = self.mod.plan_gtm({}, "G-TEST123456", self.container, report)
        self.assertTrue(plan.google_tag)

    def test_wrong_measurement_id_is_manual(self) -> None:
        report = self.mod.Report()
        plan = self.mod.plan_gtm(_live_container(self.mod, "G-OLD"), "G-TEST123456", self.container, report)
        self.assertFalse(plan.google_tag)
        self.assertTrue(any("Google tag carries" in c.summary for c in report.changes))

    def test_stale_trigger_regex_and_missing_param_are_reported(self) -> None:
        live = _live_container(self.mod)
        live["trigger"][0]["customEventFilter"][0]["parameter"][1]["value"] = "^(contact_click)$"
        rows = self.mod.param(live["tag"][1], "eventSettingsTable")
        rows.pop()
        report = self.mod.Report()
        self.mod.plan_gtm(live, "G-TEST123456", self.container, report)
        summaries = [c.summary for c in report.changes]
        self.assertTrue(any("expected '^(" in s for s in summaries))
        self.assertTrue(any("does not forward: source" in s for s in summaries))

    def test_apply_creates_workspace_entities_and_publishes(self) -> None:
        live = _live_container(self.mod, complete=False)
        report = self.mod.Report()
        plan = self.mod.plan_gtm(live, "G-TEST123456", self.container, report)
        ws = "accounts/1/containers/2/workspaces/5"
        api = FakeApi(
            {
                ("POST", f"{self.mod.TAGMANAGER_V2}/accounts/1/containers/2/workspaces"): {"path": ws},
                ("POST", f"{self.mod.TAGMANAGER_V2}/{ws}/triggers"): {"triggerId": "42"},
                ("POST", f"{self.mod.TAGMANAGER_V2}/{ws}:create_version"): {
                    "containerVersion": {"path": "accounts/1/containers/2/versions/3"}
                },
            }
        )
        version = self.mod.apply_gtm(api, "accounts/1/containers/2", live, plan, "G-TEST123456", publish=True)
        self.assertEqual(version, "accounts/1/containers/2/versions/3")
        urls = [u for m, u, b in api.calls if m == "POST"]
        self.assertIn(f"{self.mod.TAGMANAGER_V2}/{ws}/built_in_variables?type=event", urls)
        self.assertEqual(urls.count(f"{self.mod.TAGMANAGER_V2}/{ws}/variables"), len(self.mod.SITE_EVENT_PARAMS))
        tags = [b for m, u, b in api.calls if u == f"{self.mod.TAGMANAGER_V2}/{ws}/tags"]
        self.assertEqual([t["type"] for t in tags], ["gaawe"])
        self.assertEqual(tags[0]["firingTriggerId"], ["42"])
        self.assertEqual(self.mod.param(tags[0], "eventName"), "{{Event}}")
        forwarded = {
            {m["key"]: m["value"] for m in row["map"]}["parameter"]
            for row in self.mod.param(tags[0], "eventSettingsTable")
        }
        self.assertEqual(forwarded, set(self.mod.SITE_EVENT_PARAMS))
        self.assertEqual(urls[-1], f"{self.mod.TAGMANAGER_V2}/accounts/1/containers/2/versions/3:publish")
        self.assertFalse(any(m == "DELETE" for m, u, b in api.calls))

    def test_apply_deletes_workspace_on_failure(self) -> None:
        live = {}
        report = self.mod.Report()
        plan = self.mod.plan_gtm(live, "G-TEST123456", self.container, report)
        ws = "accounts/1/containers/2/workspaces/5"

        class Failing(FakeApi):
            def post(self, url, body=None):
                if url.endswith(":create_version"):
                    raise self.mod_error
                return super().post(url, body)

        api = Failing({("POST", f"{self.mod.TAGMANAGER_V2}/accounts/1/containers/2/workspaces"): {"path": ws}})
        api.mod_error = self.mod.ApiError(400, {"error": {"status": "INVALID_ARGUMENT"}}, "x")
        with self.assertRaises(self.mod.ApiError):
            self.mod.apply_gtm(api, "accounts/1/containers/2", live, plan, "G-TEST123456", publish=True)
        self.assertEqual(api.calls[-1][:2], ("DELETE", f"{self.mod.TAGMANAGER_V2}/{ws}"))

    def test_service_disabled_message(self) -> None:
        err = self.mod.ApiError(
            403,
            {"error": {"status": "PERMISSION_DENIED", "details": [{"reason": "SERVICE_DISABLED"}]}},
            "https://analyticsadmin.googleapis.com/v1beta/properties/1",
        )
        text = self.mod.explain_access_error(err)
        self.assertIn("analyticsadmin.googleapis.com", text)
        self.assertIn("tagmanager.googleapis.com", text)


if __name__ == "__main__":
    unittest.main()
