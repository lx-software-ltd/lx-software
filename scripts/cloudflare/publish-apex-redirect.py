#!/usr/bin/env python3
"""Publish or check the LX Software apex → www redirect.

HTTPS is handled by a Single Redirect (it runs before Workers). The
Worker on ``lx-software.com/*`` is the HTTP / fallback path. Both keep
the path and query. A destination of ``https://www.lx-software.com/*``
is a literal star and must not be used.

Requires:
    CLOUDFLARE_API_TOKEN   Workers edit, zone Workers Routes, and
                           Zone Redirect Rules Edit on lx-software.com
    CLOUDFLARE_ACCOUNT_ID  account that owns the zone

Usage:
  python3 scripts/cloudflare/publish-apex-redirect.py check
  python3 scripts/cloudflare/publish-apex-redirect.py apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

LIVE_PROBES = (
    "http://lx-software.com/",
    "http://lx-software.com/privacy",
    "https://lx-software.com/",
    "https://lx-software.com/about",
)

ZONE_NAME = "lx-software.com"
CANONICAL_HOST = "www.lx-software.com"
SCRIPT_NAME = "lx-software-apex-redirect"
ROUTE_PATTERN = "lx-software.com/*"
WORKER_FILE = Path(__file__).resolve().parent / "lx-software-apex-redirect.js"
COMPATIBILITY_DATE = "2026-10-06"
APEX_REDIRECT_DESCRIPTION = "Redirect apex to www and keep path"
APEX_REDIRECT_EXPRESSION = '(http.host eq "lx-software.com")'
LEGACY_APEX_REDIRECT_EXPRESSION = (
    '(http.request.full_uri wildcard r"https://lx-software.com/*")'
)
APEX_TARGET_EXPRESSION = 'concat("https://www.lx-software.com", http.request.uri.path)'
LITERAL_STAR_TARGET_EXPRESSION = (
    "wildcard_replace(http.request.full_uri, "
    r'r"https://lx-software.com/*", '
    r'r"https://www.lx-software.com/*")'
)
APEX_REDIRECT_EXPRESSIONS = frozenset(
    {APEX_REDIRECT_EXPRESSION, LEGACY_APEX_REDIRECT_EXPRESSION}
)
APEX_TARGET_EXPRESSIONS = frozenset(
    {APEX_TARGET_EXPRESSION, LITERAL_STAR_TARGET_EXPRESSION}
)


def canonical_www_url(href: str) -> str:
    parsed = urllib.parse.urlsplit(href)
    path = parsed.path or "/"
    return urllib.parse.urlunsplit(("https", CANONICAL_HOST, path, parsed.query, parsed.fragment))


def _cf_request(
    method: str,
    path: str,
    token: str,
    payload: dict[str, Any] | None = None,
    *,
    raw: bytes | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    data = raw
    headers = {"Authorization": f"Bearer {token}"}
    if raw is None and payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    elif content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4{path}",
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()[:800]
        raise RuntimeError(f"Cloudflare {method} {path} failed: {exc.code} {body}") from exc


def resolve_zone_id(token: str, zone_name: str) -> str:
    qs = urllib.parse.urlencode({"name": zone_name})
    data = _cf_request("GET", f"/zones?{qs}", token)
    zones = data.get("result") or []
    if not zones:
        raise RuntimeError(f"Cloudflare zone {zone_name} not found")
    return str(zones[0]["id"])


def _multipart(fields: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "----lxsoftwareapexredirect"
    chunks: list[bytes] = []
    for name, filename, body, ctype in fields:
        chunks.append(f"--{boundary}\r\n".encode())
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename:
            disposition += f'; filename="{filename}"'
        chunks.append(f"{disposition}\r\nContent-Type: {ctype}\r\n\r\n".encode())
        chunks.append(body)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def put_worker(token: str, account_id: str) -> None:
    source = WORKER_FILE.read_bytes()
    metadata = {
        "main_module": "lx-software-apex-redirect.js",
        "compatibility_date": COMPATIBILITY_DATE,
        "observability": {"enabled": True},
    }
    raw, ctype = _multipart(
        [
            ("metadata", "", json.dumps(metadata).encode(), "application/json"),
            (
                "lx-software-apex-redirect.js",
                "lx-software-apex-redirect.js",
                source,
                "application/javascript+module",
            ),
        ]
    )
    _cf_request(
        "PUT",
        f"/accounts/{account_id}/workers/scripts/{SCRIPT_NAME}",
        token,
        raw=raw,
        content_type=ctype,
    )


def apex_redirect_payload() -> dict[str, Any]:
    return {
        "description": APEX_REDIRECT_DESCRIPTION,
        "enabled": True,
        "expression": APEX_REDIRECT_EXPRESSION,
        "action": "redirect",
        "action_parameters": {
            "from_value": {
                "status_code": 301,
                "preserve_query_string": True,
                "target_url": {"expression": APEX_TARGET_EXPRESSION},
            }
        },
    }


def redirect_target_expression(rule: dict[str, Any]) -> str:
    params = rule.get("action_parameters") or {}
    from_value = params.get("from_value") or {}
    target = from_value.get("target_url") or {}
    if isinstance(target, dict):
        return str(target.get("expression") or target.get("value") or "")
    return str(target or "")


def is_literal_star_www_redirect(rule: dict[str, Any]) -> bool:
    return redirect_target_expression(rule) == LITERAL_STAR_TARGET_EXPRESSION


def is_apex_redirect_rule(rule: dict[str, Any]) -> bool:
    expression = str(rule.get("expression") or "")
    target = redirect_target_expression(rule)
    return expression in APEX_REDIRECT_EXPRESSIONS or target in APEX_TARGET_EXPRESSIONS


def apex_redirect_is_correct(rule: dict[str, Any]) -> bool:
    return (
        bool(rule.get("enabled"))
        and str(rule.get("expression") or "") == APEX_REDIRECT_EXPRESSION
        and redirect_target_expression(rule) == APEX_TARGET_EXPRESSION
        and not is_literal_star_www_redirect(rule)
    )


def get_dynamic_redirect(token: str, zone_id: str) -> dict[str, Any]:
    try:
        return _cf_request(
            "GET",
            f"/zones/{zone_id}/rulesets/phases/http_request_dynamic_redirect/entrypoint",
            token,
        )
    except RuntimeError as exc:
        if " 404 " in str(exc):
            return {}
        raise


def ensure_apex_single_redirect(token: str, zone_id: str) -> str:
    result = (get_dynamic_redirect(token, zone_id).get("result") or {})
    ruleset_id = result.get("id")
    rules = list(result.get("rules") or [])
    desired = apex_redirect_payload()
    match = next((row for row in rules if is_apex_redirect_rule(row)), None)
    phase = f"/zones/{zone_id}/rulesets/phases/http_request_dynamic_redirect/entrypoint"
    if not ruleset_id:
        _cf_request("PUT", phase, token, {"rules": [desired]})
        return "created"
    if match and apex_redirect_is_correct(match):
        return "unchanged"
    if match:
        _cf_request(
            "PATCH",
            f"/zones/{zone_id}/rulesets/{ruleset_id}/rules/{match['id']}",
            token,
            desired,
        )
        return "updated"
    _cf_request("POST", f"/zones/{zone_id}/rulesets/{ruleset_id}/rules", token, desired)
    return "created"


def apex_redirect_state(token: str, zone_id: str) -> dict[str, Any]:
    result = (get_dynamic_redirect(token, zone_id).get("result") or {})
    rules = list(result.get("rules") or [])
    match = next((row for row in rules if is_apex_redirect_rule(row)), None)
    return {
        "rule": match,
        "ok": bool(match and apex_redirect_is_correct(match)),
        "star": bool(match and is_literal_star_www_redirect(match)),
    }


def ensure_route(token: str, zone_id: str) -> str:
    existing = _cf_request("GET", f"/zones/{zone_id}/workers/routes", token).get("result") or []
    for row in existing:
        if str(row.get("pattern")) == ROUTE_PATTERN:
            if str(row.get("script")) == SCRIPT_NAME:
                return "unchanged"
            _cf_request(
                "PUT",
                f"/zones/{zone_id}/workers/routes/{row['id']}",
                token,
                {"pattern": ROUTE_PATTERN, "script": SCRIPT_NAME},
            )
            return "updated"
    _cf_request(
        "POST",
        f"/zones/{zone_id}/workers/routes",
        token,
        {"pattern": ROUTE_PATTERN, "script": SCRIPT_NAME},
    )
    return "created"


def worker_state(token: str, account_id: str, zone_id: str) -> dict[str, Any]:
    scripts = _cf_request("GET", f"/accounts/{account_id}/workers/scripts", token).get("result") or []
    script = next((row for row in scripts if str(row.get("id")) == SCRIPT_NAME), {})
    routes = _cf_request("GET", f"/zones/{zone_id}/workers/routes", token).get("result") or []
    matching = [row for row in routes if str(row.get("pattern")) == ROUTE_PATTERN]
    return {
        "script": script,
        "routes": matching,
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def probe_live() -> list[str]:
    opener = urllib.request.build_opener(_NoRedirect)
    problems: list[str] = []
    for href in LIVE_PROBES:
        req = urllib.request.Request(
            href,
            method="GET",
            headers={"User-Agent": "lx-software-apex-redirect-check/1"},
        )
        try:
            with opener.open(req, timeout=15) as resp:
                location = resp.headers.get("Location", "")
                status = resp.status
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location", "") if exc.headers else ""
            status = exc.code
        except urllib.error.URLError as exc:
            problems.append(f"{href} failed: {exc.reason}")
            continue
        expected = canonical_www_url(href)
        if status != 301 or location != expected:
            problems.append(f"{href} -> {status} {location or '(no Location)'} (want 301 {expected})")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("check", "apply"))
    args = parser.parse_args(argv)
    token = os.environ.get("CLOUDFLARE_API_TOKEN") or ""
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID") or ""
    if not token or not account_id:
        print("CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID are required", file=sys.stderr)
        return 2
    zone_id = resolve_zone_id(token, ZONE_NAME)
    redirect_ok = False
    if args.command == "apply":
        redirect = ensure_apex_single_redirect(token, zone_id)
        put_worker(token, account_id)
        route = ensure_route(token, zone_id)
        print(f"single redirect {redirect}; published {SCRIPT_NAME}; route {ROUTE_PATTERN} {route}")
    try:
        redirect_state = apex_redirect_state(token, zone_id)
        redirect_ok = bool(redirect_state["ok"])
        print(
            "single redirect "
            f"{'ok' if redirect_ok else 'missing or wrong'}; "
            f"literal_star={redirect_state['star']}"
        )
        if redirect_state["star"]:
            print(
                "Single Redirect destination is a literal star path; "
                f"set target_url to {APEX_TARGET_EXPRESSION}",
                file=sys.stderr,
            )
    except RuntimeError as exc:
        print(f"single redirect unread: {exc}", file=sys.stderr)
        if args.command == "apply":
            return 1
    state = worker_state(token, account_id, zone_id)
    script_id = str((state["script"] or {}).get("id") or SCRIPT_NAME)
    routes = state["routes"]
    worker_ok = bool(routes) and all(str(row.get("script")) == SCRIPT_NAME for row in routes)
    print(f"worker {script_id}; routes {len(routes)}; expected {ROUTE_PATTERN} -> {SCRIPT_NAME}")
    live = probe_live()
    for line in live:
        print(f"live {line}")
    return 0 if redirect_ok and worker_ok and not live else 1


if __name__ == "__main__":
    raise SystemExit(main())
