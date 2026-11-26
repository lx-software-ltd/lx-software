"""Route table covers the paths exercised by handler tests."""

from __future__ import annotations

import unittest

from test_support import install_aws_stubs

install_aws_stubs()

from dispatch import EARLY_INTERNAL, HTTP_ROUTES, LATE_INTERNAL  # noqa: E402
from http_common import http_audience  # noqa: E402
from router import route_matches  # noqa: E402

# Gateway paths. Partner requests never enter the admin route table.
_PARTNER_CASES = (
    ("GET", "/v1/partner/finance"),
    ("GET", "/v1/partner/lx-software/linkedin/posts"),
    ("PUT", "/v1/partner/finance"),
    ("GET", "/v1/partner/records"),
    ("GET", "/v1/partner/finance/hillmarton"),
    ("POST", "/v1/partner/siutindei/board/tasks"),
    ("GET", "/v1/partner/siutindei/board/charter"),
    ("GET", "/v1/partner"),
)
_ADMIN_CASES = (("GET", "/finance", "admin"),)


def _first_specific_route(method: str, path: str):
    """First route that would claim this request, ignoring catch-all fallthroughs."""
    for route in HTTP_ROUTES:
        if route.kind == "any":
            continue
        if route_matches(route, method, path):
            return route
    return None


class RouteTableTests(unittest.TestCase):
    def test_handler_paths_are_in_the_route_table(self) -> None:
        for method, path, auth in _ADMIN_CASES:
            route = _first_specific_route(method, path)
            self.assertIsNotNone(route, path)
            assert route is not None
            self.assertEqual(route.auth, auth, path)
        for _method, path in _PARTNER_CASES:
            audience, routed = http_audience(path)
            self.assertEqual(audience, "partner", path)
            self.assertEqual(routed, path)
            self.assertIsNone(_first_specific_route("GET", path), path)

    def test_get_finance_is_exact_admin_route(self) -> None:
        route = _first_specific_route("GET", "/finance")
        self.assertIsNotNone(route)
        assert route is not None
        self.assertEqual(route.kind, "exact")
        self.assertEqual(route.pattern, "/finance")
        self.assertIsNone(_first_specific_route("PUT", "/finance"))

    def test_health_get_is_unauthenticated_and_post_is_not(self) -> None:
        health = _first_specific_route("GET", "/health")
        self.assertIsNotNone(health)
        assert health is not None
        self.assertEqual(health.auth, "none")
        self.assertIsNone(_first_specific_route("POST", "/health"))

    def test_partner_audience_is_the_partner_prefix_only(self) -> None:
        self.assertEqual(http_audience("/v1/partner/finance")[0], "partner")
        self.assertEqual(http_audience("/v1/partner")[0], "partner")
        self.assertNotEqual(http_audience("/v1/partnerfinance")[0], "partner")
        self.assertEqual(http_audience("/health")[0], "none")
        self.assertEqual(http_audience("/v1/admin/finance"), ("admin", "/finance"))

    def test_only_the_forever_keepers_are_rewritten(self) -> None:
        keepers = {
            "/public/outreach/unsubscribe/tok": ("public", "/v1/public/outreach/unsubscribe/tok"),
            "/public/newsletter/confirm/tok": ("public", "/v1/public/newsletter/confirm/tok"),
            "/public/newsletter/unsubscribe/tok": ("public", "/v1/public/newsletter/unsubscribe/tok"),
        }
        for path, expected in keepers.items():
            self.assertEqual(http_audience(path), expected, path)
        removed = (
            "/me",
            "/finance",
            "/finance/quotes",
            "/aws/usage.pdf",
            "/aws/usage",
            "/fx/v2/rates",
            "/siu-tin-dei",
            "/siu-tin-dei/board/actions",
            "/evolve-sprouts",
            "/evolve-sprouts/summary",
            "/lx-software",
            "/lx-software/linkedin",
            "/lx-software/resume/overview",
            "/public/finance",
            "/public/finance/quotes",
            "/public/records",
            "/public/fx/v2/rates",
            "/public/lx-software/linkedin/posts",
            "/public/newsletter/subscribe",
            "/public/siu-tin-dei/boardroom",
            "/webhooks/meta",
            "/webhooks/meta/siutindei",
            "/public/siu-tin-dei/board",
            "/public/siu-tin-dei/board/actions/a1",
        )
        for path in removed:
            self.assertEqual(http_audience(path), ("unknown", path), path)

    def test_internal_workers_from_handler_tests_are_registered(self) -> None:
        self.assertIn("parse_statement_async", EARLY_INTERNAL)
        self.assertIn("resume_extract", EARLY_INTERNAL)
        self.assertIn("resume_tailor", EARLY_INTERNAL)
        self.assertNotIn("parse_statement_async", LATE_INTERNAL)

    def test_resume_prefix_is_an_admin_route(self) -> None:
        route = _first_specific_route("POST", "/lx-software/resume/tailor")
        self.assertIsNotNone(route)
        assert route is not None
        self.assertEqual(route.auth, "admin")
        self.assertEqual(route.handler, dispatch_handler())


def dispatch_handler():
    from dispatch import _http_resume

    return _http_resume
