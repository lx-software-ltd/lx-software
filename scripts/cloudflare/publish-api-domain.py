#!/usr/bin/env python3
"""Point api.lx-software.com at the API Gateway custom domain.

The record matches api.findingalpha.app: a DNS-only CNAME to the regional
hostname (d-<id>.execute-api.<region>.amazonaws.com). It must not target
the <api-id>.execute-api name, and it must not be proxied.

Requires:
  CLOUDFLARE_API_TOKEN   Zone.DNS edit on lx-software.com
  AWS credentials        apigateway:GET for the domain name

Usage:
  python3 scripts/cloudflare/publish-api-domain.py check
  python3 scripts/cloudflare/publish-api-domain.py apply
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_HOSTNAME = "api.lx-software.com"
ZONE_NAME = "lx-software.com"
DEFAULT_REGION = "ap-southeast-1"
CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"


def cloudflare_url(path: str) -> str:
    """A Cloudflare API path. A scheme or parent segment cannot leave this host."""
    if not path.startswith("/") or path.startswith("//") or "\\" in path or ".." in path or "://" in path:
        raise RuntimeError("refusing Cloudflare path")
    return CLOUDFLARE_API + path


def regional_target(domain: dict[str, Any]) -> str:
    configs = domain.get("DomainNameConfigurations") or []
    if not isinstance(configs, list) or not configs:
        raise RuntimeError("API custom domain has no configuration")
    config = configs[0] if isinstance(configs[0], dict) else {}
    target = str(config.get("ApiGatewayDomainName") or "").strip().rstrip(".")
    if not target.startswith("d-") or ".execute-api." not in target:
        raise RuntimeError(f"API custom domain target is not a regional hostname: {target}")
    return target


def cname_is_correct(row: dict[str, Any] | None, target: str) -> bool:
    if not row:
        return False
    content = str(row.get("content") or "").strip().rstrip(".")
    return str(row.get("type")) == "CNAME" and content == target and row.get("proxied") is False


def desired_cname(target: str) -> dict[str, Any]:
    return {
        "type": "CNAME",
        "name": API_HOSTNAME,
        "content": target,
        "ttl": 1,
        "proxied": False,
        "comment": "API Gateway regional domain. DNS only.",
    }


def _cf_request(method: str, path: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    # cloudflare_url rejects a scheme, a protocol-relative path, and '..'.
    req = urllib.request.Request(  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected # nosec B310
        cloudflare_url(path),
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with (
            urllib.request.urlopen(  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected # nosec B310
                req
            ) as resp
        ):
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


def find_cname(token: str, zone_id: str, name: str) -> dict[str, Any] | None:
    qs = urllib.parse.urlencode({"type": "CNAME", "name": name})
    data = _cf_request("GET", f"/zones/{zone_id}/dns_records?{qs}", token)
    rows = data.get("result") or []
    return rows[0] if rows else None


def upsert_cname(token: str, zone_id: str, target: str, existing: dict[str, Any] | None) -> str:
    payload = desired_cname(target)
    if cname_is_correct(existing, target):
        return "unchanged"
    if existing:
        _cf_request("PUT", f"/zones/{zone_id}/dns_records/{existing['id']}", token, payload)
        return "updated"
    _cf_request("POST", f"/zones/{zone_id}/dns_records", token, payload)
    return "created"


def load_target(region: str) -> str:
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required") from exc
    client = boto3.client("apigatewayv2", region_name=region)
    try:
        domain = client.get_domain_name(DomainName=API_HOSTNAME)
    except Exception as exc:
        raise RuntimeError(
            f"{API_HOSTNAME} is not an API Gateway domain yet. Deploy the lxsoftware "
            "stack with ApiCustomDomainCertificateArn set, then rerun."
        ) from exc
    return regional_target(domain)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args not in (["check"], ["apply"]):
        print("usage: publish-api-domain.py check|apply", file=sys.stderr)
        return 2
    token = (os.environ.get("CLOUDFLARE_API_TOKEN") or "").strip()
    if not token:
        print("CLOUDFLARE_API_TOKEN is required", file=sys.stderr)
        return 2
    region = (os.environ.get("AWS_REGION") or DEFAULT_REGION).strip()
    try:
        target = load_target(region)
        zone_id = resolve_zone_id(token, ZONE_NAME)
        current = find_cname(token, zone_id, API_HOSTNAME)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    ok = cname_is_correct(current, target)
    print(json.dumps({"hostname": API_HOSTNAME, "target": target, "ok": ok}))
    if args == ["check"]:
        return 0 if ok else 1
    if ok:
        return 0
    try:
        state = upsert_cname(token, zone_id, target, current)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
