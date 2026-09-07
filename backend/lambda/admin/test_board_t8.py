"""T8: GA4 + GTM reads, multi-property ids, hourly cache."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import board_cache
import board_context
import board_store
import board_web
from board_tools import REGISTRY, ToolContext, execute_call
from test_board_tools import ToolsTestCase


class FakeGoogle:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def __call__(self, method: str, url: str, *, body: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((method, url, body))
        if ":runReport" in url:
            pid = url.rsplit("/properties/", 1)[-1].split(":", 1)[0]
            metrics = [m["name"] for m in (body or {}).get("metrics") or []]
            dimensions = [d["name"] for d in (body or {}).get("dimensions") or []]
            if "pagePath" in dimensions:
                return {
                    "rows": [
                        {
                            "dimensionValues": [{"value": f"/c/{pid}?email=parent@example.com"}],
                            "metricValues": [{"value": "12"}, {"value": "40"}],
                        }
                    ],
                    "totals": [{"metricValues": [{"value": "12"}, {"value": "40"}]}],
                    "rowCount": 1,
                }
            if "sessionSource" in dimensions:
                return {
                    "rows": [
                        {
                            "dimensionValues": [{"value": "google"}, {"value": "organic"}],
                            "metricValues": [{"value": "9"}],
                        }
                    ],
                    "totals": [{"metricValues": [{"value": "9"}]}],
                    "rowCount": 1,
                }
            if "eventName" in dimensions:
                return {
                    "rows": [
                        {
                            "dimensionValues": [{"value": "store_click"}],
                            "metricValues": [{"value": "4"}, {"value": "2"}],
                        }
                    ],
                    "totals": [{"metricValues": [{"value": "4"}, {"value": "2"}]}],
                    "rowCount": 1,
                }
            values = [{"value": "100" if pid == "111" else "50"} for _ in metrics]
            return {"rows": [], "totals": [{"metricValues": values}], "rowCount": 0}
        if url.endswith("/versions:live"):
            cid = url.rsplit("/containers/", 1)[-1].split("/", 1)[0]
            return {
                "containerVersion": {
                    "containerVersionId": f"live-{cid}",
                    "name": "Live",
                    "description": "Published",
                    "fingerprint": "fp-1",
                }
            }
        if "/containers/" in url:
            cid = url.rsplit("/containers/", 1)[-1]
            return {"container": {"name": f"Web {cid}", "publicId": f"GTM-{cid}"}}
        return {}


class WebTestCase(ToolsTestCase):
    def setUp(self) -> None:
        super().setUp()
        board_web.reset_caches_for_tests()
        os.environ["GOOGLE_ANALYTICS_ACCESS_TOKEN"] = "ga-test-token"
        os.environ["GA4_PROPERTY_IDS"] = "properties/111,222"
        os.environ["GTM_CONTAINERS"] = "acc-1:c1,acc-1:c2"
        self.addCleanup(board_web.reset_caches_for_tests)
        self.google = FakeGoogle()
        p = patch.object(board_web, "_google", self.google)
        p.start()
        self.addCleanup(p.stop)

    def _ctx(self, persona: str = "cmo") -> ToolContext:
        settings = board_store.load_settings(self.table)
        return ToolContext(table=self.table, settings=settings, persona_id=persona, actor="persona")


class TestWebTools(WebTestCase):
    def test_sessions_cover_every_property_and_mask_paths(self) -> None:
        out = execute_call(self._ctx(), REGISTRY["web_sessions"], {})
        self.assertEqual(out.status, "ok")
        self.assertEqual(out.result["count"], 2)
        ids = {row["propertyId"] for row in out.result["properties"]}
        self.assertEqual(ids, {"111", "222"})
        pages = out.result["properties"][0]["topPages"]
        self.assertTrue(pages)
        self.assertIn("contact#hidden", pages[0]["pagePath"])
        self.assertNotIn("parent@example.com", pages[0]["pagePath"])
        self.assertEqual(out.result["properties"][0]["totals"]["sessions"], 100)
        self.assertEqual(out.result["properties"][1]["totals"]["sessions"], 50)
        reports = len([c for c in self.google.calls if ":runReport" in c[1]])
        cached = execute_call(self._ctx(), REGISTRY["web_sessions"], {})
        self.assertTrue(cached.result.get("cached"))
        self.assertEqual(len([c for c in self.google.calls if ":runReport" in c[1]]), reports)

    def test_property_filter_and_unknown_id(self) -> None:
        one = execute_call(self._ctx(), REGISTRY["web_sessions"], {"propertyId": "222"})
        self.assertEqual(one.status, "ok")
        self.assertEqual(one.result["count"], 1)
        self.assertEqual(one.result["properties"][0]["propertyId"], "222")
        bad = execute_call(self._ctx(), REGISTRY["web_sessions"], {"propertyId": "999"})
        self.assertEqual(bad.status, "error")
        self.assertIn("GA4_PROPERTY_IDS", bad.result["error"])

    def test_conversions_and_gtm_live(self) -> None:
        conv = execute_call(self._ctx(), REGISTRY["web_conversions"], {})
        self.assertEqual(conv.status, "ok")
        self.assertEqual(conv.result["properties"][0]["events"][0]["eventName"], "store_click")
        gtm = execute_call(self._ctx(), REGISTRY["web_gtm_status"], {})
        self.assertEqual(gtm.status, "ok")
        self.assertEqual(gtm.result["count"], 2)
        self.assertEqual(gtm.result["containers"][0]["publicId"], "GTM-c1")
        self.assertEqual(gtm.result["containers"][0]["live"]["versionId"], "live-c1")
        one = execute_call(self._ctx(), REGISTRY["web_gtm_status"], {"containerId": "c2"})
        self.assertEqual(one.result["count"], 1)
        self.assertEqual(one.result["containers"][0]["containerId"], "c2")

    def test_cache_refresh_and_context_pack(self) -> None:
        notes = board_cache.refresh_all(self.table)
        self.assertEqual(notes["web"]["web:sessions"], "ok")
        self.assertEqual(notes["web"]["web:gtm"], "ok")
        settings = board_store.load_settings(self.table)
        pack = board_context.build_context_pack(self.table, settings, roster=[])
        self.assertIn("Web:", pack["text"])
        self.assertIn("150", pack["text"])
        self.assertEqual(pack["web"]["sessions"], 150)
        self.assertEqual(pack["web"]["properties"], 2)

    def test_ceo_has_web_reads_cfo_does_not(self) -> None:
        settings = board_store.load_settings(self.table)
        import board_tools

        ceo = {op.name for op, _ in board_tools.available_ops(settings, "ceo", context="chat")}
        cfo = {op.name for op, _ in board_tools.available_ops(settings, "cfo", context="chat")}
        self.assertIn("web_sessions", ceo)
        self.assertNotIn("web_sessions", cfo)

    def test_registry_includes_web(self) -> None:
        self.assertIn("web_sessions", REGISTRY)
        self.assertIn("web_conversions", REGISTRY)
        self.assertIn("web_gtm_status", REGISTRY)
        self.assertEqual(REGISTRY["web_sessions"].tool_id, "web")
        self.assertFalse(REGISTRY["web_sessions"].is_write)


class TestWebUnavailable(ToolsTestCase):
    def test_refresh_skips_when_unconfigured(self) -> None:
        board_web.reset_caches_for_tests()
        os.environ.pop("GOOGLE_ANALYTICS_ACCESS_TOKEN", None)
        os.environ.pop("GOOGLE_ANALYTICS_SERVICE_ACCOUNT", None)
        os.environ.pop("GOOGLE_ANALYTICS_SERVICE_ACCOUNT_SECRET_ARN", None)
        os.environ.pop("GA4_PROPERTY_IDS", None)
        os.environ.pop("GTM_CONTAINERS", None)
        notes = board_web.refresh_caches(self.table)
        self.assertEqual(notes["web:sessions"], "skipped")
        self.assertFalse(board_web.configured())


class FakeAnalyticsSecrets:
    def get_secret_value(self, SecretId: str) -> dict[str, str]:  # noqa: N803
        assert SecretId == "arn:ga-sa"
        return {
            "SecretString": (
                '{"client_email":"ga@example.iam.gserviceaccount.com",'
                '"private_key":"-----BEGIN PRIVATE KEY-----\\nMIIB\\n-----END PRIVATE KEY-----\\n",'
                '"propertyIds":["properties/111","222"],'
                '"gtmContainers":[{"accountId":"acc-1","containerId":"c1"},'
                '{"accountId":"acc-1","containerId":"c2"}]}'
            )
        }


class TestWebSecretFromArn(WebTestCase):
    """Production path: ids live in the SA JSON; env CSV params are blank."""

    def setUp(self) -> None:
        super().setUp()
        os.environ.pop("GA4_PROPERTY_IDS", None)
        os.environ.pop("GTM_CONTAINERS", None)
        os.environ.pop("GOOGLE_ANALYTICS_SERVICE_ACCOUNT", None)
        os.environ["GOOGLE_ANALYTICS_SERVICE_ACCOUNT_SECRET_ARN"] = "arn:ga-sa"
        board_web.reset_caches_for_tests()
        secrets = patch.object(board_web, "_get_secretsmanager_client", return_value=FakeAnalyticsSecrets())
        secrets.start()
        self.addCleanup(secrets.stop)
        self.addCleanup(lambda: os.environ.pop("GOOGLE_ANALYTICS_SERVICE_ACCOUNT_SECRET_ARN", None))

    def test_cmo_sessions_and_gtm_read_ids_from_secret_json(self) -> None:
        sessions = execute_call(self._ctx(), REGISTRY["web_sessions"], {})
        self.assertEqual(sessions.status, "ok", sessions.result)
        self.assertEqual(sessions.result["count"], 2)
        gtm = execute_call(self._ctx(), REGISTRY["web_gtm_status"], {})
        self.assertEqual(gtm.status, "ok", gtm.result)
        self.assertEqual(gtm.result["count"], 2)
        self.assertEqual(gtm.result["containers"][0]["publicId"], "GTM-c1")

    def test_token_unwrap_would_drop_the_sa_json(self) -> None:
        from openrouter_client import OpenRouterError, read_secret_raw, read_secret_string

        client = FakeAnalyticsSecrets()
        raw = read_secret_raw(client, "arn:ga-sa", what="Google Analytics service account")
        self.assertIn("client_email", raw)
        with self.assertRaises(OpenRouterError) as raised:
            read_secret_string(client, "arn:ga-sa", what="Google Analytics service account")
        self.assertIn("missing in secret JSON", str(raised.exception))

    def test_cache_refresh_still_warms_web_when_aws_raises(self) -> None:
        import board_aws

        boom = RuntimeError("Unknown parameter in filter: maxResults")
        with patch.object(board_aws, "refresh_caches", side_effect=boom):
            notes = board_cache.refresh_all(self.table)
        self.assertIn("error", notes["aws"])
        self.assertEqual(notes["web"]["web:sessions"], "ok")
        self.assertEqual(notes["web"]["web:gtm"], "ok")
