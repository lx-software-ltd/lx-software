#!/usr/bin/env python3
"""Publish or check the LX Software apex → www Worker.

The apex A record is a proxied dummy (192.0.2.1). A Page Rule used to
forward to the literal path ``/*``. This script puts a Worker on
``lx-software.com/*`` that 301s to ``https://www.lx-software.com`` and
keeps the path and query.

Requires:
  CLOUDFLARE_API_TOKEN   Workers edit + zone Workers Routes on lx-software.com
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

ZONE_NAME = "lx-software.com"
CANONICAL_HOST = "www.lx-software.com"
SCRIPT_NAME = "lx-software-apex-redirect"
ROUTE_PATTERN = "lx-software.com/*"
WORKER_FILE = Path(__file__).resolve().parent / "lx-software-apex-redirect.js"
COMPATIBILITY_DATE = "2026-10-06"


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
    script = _cf_request("GET", f"/accounts/{account_id}/workers/scripts/{SCRIPT_NAME}", token)
    routes = _cf_request("GET", f"/zones/{zone_id}/workers/routes", token).get("result") or []
    matching = [row for row in routes if str(row.get("pattern")) == ROUTE_PATTERN]
    return {
        "script": script.get("result") or {},
        "routes": matching,
    }


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
    if args.command == "apply":
        put_worker(token, account_id)
        route = ensure_route(token, zone_id)
        print(f"published {SCRIPT_NAME}; route {ROUTE_PATTERN} {route}")
    state = worker_state(token, account_id, zone_id)
    script_id = str((state["script"] or {}).get("id") or SCRIPT_NAME)
    routes = state["routes"]
    ok = bool(routes) and all(str(row.get("script")) == SCRIPT_NAME for row in routes)
    print(f"worker {script_id}; routes {len(routes)}; expected {ROUTE_PATTERN} -> {SCRIPT_NAME}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
