"""Route table covers the paths exercised by handler tests."""

from __future__ import annotations

import unittest

from test_support import install_aws_stubs

install_aws_stubs()

from dispatch import EARLY_INTERNAL, HTTP_ROUTES, LATE_INTERNAL  # noqa: E402
from router import route_matches  # noqa: E402

# Paths and methods passed to lambda_handler in test_handler.py.
_HANDLER_CASES = (
    ("GET", "/public/finance", "public"),
    ("PUT", "/public/finance", "public"),
    ("GET", "/public/records", "public"),
    ("GET", "/public/finance/hillmarton", "public"),
    ("POST", "/public/siu-tin-dei/board/tasks", "public"),
    ("GET", "/public/siu-tin-dei/board/charter", "public"),
    ("GET", "/public", "public"),
    ("GET", "/finance", "admin"),
)


def _first_specific_route(method: str, path: str):
    """First route that would claim this request, ignoring catch-all fallthroughs."""
    for route in HTTP_ROUTES:
        if route.kind == "any":
            continue
        if route.auth == "public" and route.kind == "public" and (path == "/public" or path.startswith("/public/")):
            return route
        if route_matches(route, method, path):
            return route
    return None


class RouteTableTests(unittest.TestCase):
    def test_handler_paths_are_in_the_route_table(self) -> None:
        for method, path, auth in _HANDLER_CASES:
            route = _first_specific_route(method, path)
            self.assertIsNotNone(route, path)
            assert route is not None
            self.assertEqual(route.auth, auth, path)

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

    def test_internal_workers_from_handler_tests_are_registered(self) -> None:
        self.assertIn("parse_statement_async", EARLY_INTERNAL)
        self.assertNotIn("parse_statement_async", LATE_INTERNAL)
