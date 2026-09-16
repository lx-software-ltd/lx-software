#!/usr/bin/env python3
"""Sync SES Easy DKIM + MAIL FROM records into Cloudflare and retry verification.

Amazon SES leaves Easy DKIM in FAILED after ~72 hours if the three CNAME
targets are missing *or* if the identity was retried with new tokens while
Cloudflare still has the old ones. FAILED does not self-heal: you must
republish the current tokens and ask SES to check again.

Requires:
  AWS credentials with ses:GetEmailIdentity (and, for --retry,
  ses:PutEmailIdentityDkimAttributes + ses:PutEmailIdentityMailFromAttributes)
  CLOUDFLARE_API_TOKEN with Zone.DNS edit on the parent zone

Usage:
  python3 scripts/sync-ses-sending-dns.py --domain partners.siutindei.com
  python3 scripts/sync-ses-sending-dns.py --domain partners.siutindei.com --retry
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_REGION = "ap-southeast-1"
DEFAULT_ZONE = "siutindei.com"


def dkim_records(identity: dict[str, Any], domain: str) -> list[dict[str, str]]:
    dkim = identity.get("DkimAttributes") if isinstance(identity.get("DkimAttributes"), dict) else {}
    tokens = dkim.get("Tokens") if isinstance(dkim.get("Tokens"), list) else []
    out: list[dict[str, str]] = []
    for tok in tokens:
        token = str(tok or "").strip()
        if not token:
            continue
        out.append(
            {
                "type": "CNAME",
                "name": f"{token}._domainkey.{domain}",
                "content": f"{token}.dkim.amazonses.com",
                "comment": f"SES Easy DKIM for {domain}",
            }
        )
    return out


def mail_from_records(identity: dict[str, Any], domain: str, region: str) -> list[dict[str, Any]]:
    mail_from = identity.get("MailFromAttributes") if isinstance(identity.get("MailFromAttributes"), dict) else {}
    host = str(mail_from.get("MailFromDomain") or f"mail.{domain}").strip()
    if not host:
        return []
    return [
        {
            "type": "MX",
            "name": host,
            "content": f"feedback-smtp.{region}.amazonses.com",
            "priority": 10,
            "comment": f"SES custom MAIL FROM for {domain}",
        },
        {
            "type": "TXT",
            "name": host,
            "content": "v=spf1 include:amazonses.com ~all",
            "comment": f"SES custom MAIL FROM SPF for {domain}",
        },
    ]


def desired_records(identity: dict[str, Any], domain: str, region: str) -> list[dict[str, Any]]:
    return [*dkim_records(identity, domain), *mail_from_records(identity, domain, region)]


def _cf_request(method: str, path: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
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


def list_dns_records(token: str, zone_id: str) -> list[dict[str, Any]]:
    page = 1
    out: list[dict[str, Any]] = []
    while True:
        qs = urllib.parse.urlencode({"per_page": 100, "page": page})
        data = _cf_request("GET", f"/zones/{zone_id}/dns_records?{qs}", token)
        out.extend(data.get("result") or [])
        info = data.get("result_info") or {}
        if page >= int(info.get("total_pages") or 1):
            return out
        page += 1


def upsert_records(
    token: str,
    zone_id: str,
    records: list[dict[str, Any]],
    existing: list[dict[str, Any]],
) -> dict[str, int]:
    by_name_type = {(str(r.get("name")), str(r.get("type"))): r for r in existing}
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    for rec in records:
        name = str(rec["name"])
        rtype = str(rec["type"])
        content = str(rec["content"])
        comment = str(rec.get("comment") or "")
        payload: dict[str, Any] = {
            "type": rtype,
            "name": name,
            "content": content,
            "ttl": 1,
            "proxied": False,
            "comment": comment,
        }
        if rtype == "MX":
            payload["priority"] = int(rec.get("priority") or 10)
        found = by_name_type.get((name, rtype))
        if found and str(found.get("content")) == content and not found.get("proxied"):
            if rtype != "MX" or int(found.get("priority") or 0) == payload["priority"]:
                counts["unchanged"] += 1
                continue
        if found:
            _cf_request("PUT", f"/zones/{zone_id}/dns_records/{found['id']}", token, payload)
            counts["updated"] += 1
        else:
            _cf_request("POST", f"/zones/{zone_id}/dns_records", token, payload)
            counts["created"] += 1
    return counts


def retry_ses(sesv2: Any, domain: str, identity: dict[str, Any]) -> None:
    sesv2.put_email_identity_dkim_attributes(EmailIdentity=domain, SigningEnabled=True)
    mail_from = identity.get("MailFromAttributes") if isinstance(identity.get("MailFromAttributes"), dict) else {}
    host = str(mail_from.get("MailFromDomain") or f"mail.{domain}").strip()
    if host:
        sesv2.put_email_identity_mail_from_attributes(
            EmailIdentity=domain,
            MailFromDomain=host,
            BehaviorOnMxFailure="USE_DEFAULT_VALUE",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default="partners.siutindei.com")
    parser.add_argument("--zone", default=DEFAULT_ZONE)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION") or DEFAULT_REGION)
    parser.add_argument("--retry", action="store_true", help="Re-enable Easy DKIM and MAIL FROM after publishing DNS.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    token = (os.environ.get("CLOUDFLARE_API_TOKEN") or "").strip()
    if not token:
        print("CLOUDFLARE_API_TOKEN is required", file=sys.stderr)
        return 2

    try:
        import boto3
    except ImportError:
        print("boto3 is required", file=sys.stderr)
        return 2

    sesv2 = boto3.client("sesv2", region_name=args.region)
    try:
        ident = sesv2.get_email_identity(EmailIdentity=args.domain)
    except Exception as exc:
        print(
            f"ses:GetEmailIdentity denied or failed for {args.domain}: {exc}\n"
            "Grant cursor-cloud-agent (or this principal) ses:GetEmailIdentity on "
            f"arn:aws:ses:{args.region}:*:identity/{args.domain}. "
            "See docs/deployment/admin-website.md (Read-only debugging identity).",
            file=sys.stderr,
        )
        return 1

    dkim = ident.get("DkimAttributes") if isinstance(ident.get("DkimAttributes"), dict) else {}
    records = desired_records(ident, args.domain, args.region)
    print(
        json.dumps(
            {
                "domain": args.domain,
                "verified": bool(ident.get("VerifiedForSendingStatus")),
                "dkimStatus": dkim.get("Status"),
                "records": records,
            },
            indent=2,
        )
    )
    if not records:
        print("No DKIM tokens on the SES identity; retry Easy DKIM in the SES console first.", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0

    zone_id = resolve_zone_id(token, args.zone)
    existing = list_dns_records(token, zone_id)
    counts = upsert_records(token, zone_id, records, existing)
    print(json.dumps({"cloudflare": counts}, indent=2))

    if args.retry:
        try:
            retry_ses(sesv2, args.domain, ident)
        except Exception as exc:
            print(
                f"SES retry failed: {exc}\n"
                "Grant ses:PutEmailIdentityDkimAttributes and "
                "ses:PutEmailIdentityMailFromAttributes, or click Retry in the SES console.",
                file=sys.stderr,
            )
            return 1
        print("SES Easy DKIM + MAIL FROM retry requested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
