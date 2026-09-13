#!/usr/bin/env python3
"""Mint, list, and revoke public read-only API keys.

Keys authenticate the /public/* GET routes on the admin HTTP API via the
`x-api-key` header (finance, records, FX, and GET /public/siu-tin-dei/board*).
Only the scrypt digest of a key is stored (as
``pk = APIKEY#<digest>``, ``sk = META`` in the records table); the plaintext
key is printed exactly once by ``create``.

New keys expire in 90 days unless ``--expires-at`` is set. Scopes default to
``finance``. Legacy rows with ``scope=read`` and no ``scopes`` list are
treated as finance-only by the authorizer.

Requires AWS credentials with GetItem/PutItem/UpdateItem/Scan on the records
table (plus kms:Decrypt/GenerateDataKey on its CMK) — i.e. an admin identity,
not the read-only cloud-agent user.

Usage:
  python3 scripts/manage-public-api-keys.py create --label "grafana" \\
      [--scopes finance,siutindei-board-ops] [--expires-at 2027-01-01] \\
      [--allowed-cidrs 203.0.113.0/24]
  python3 scripts/manage-public-api-keys.py list
  python3 scripts/manage-public-api-keys.py revoke --key-id <keyId>
"""

from __future__ import annotations

import argparse
import ipaddress
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# Reuse the authorizer's digest helper so mint and verify never drift apart.
_AUTHORIZER_DIR = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "lambda"
    / "public_api_authorizer"
)
sys.path.insert(0, str(_AUTHORIZER_DIR))
from api_key_hash import hash_api_key  # noqa: E402
from api_key_scopes import ALL_SCOPES, SCOPE_FINANCE  # noqa: E402

API_KEY_PK_PREFIX = "APIKEY#"
KEY_PLAINTEXT_PREFIX = "lxpk_"
DEFAULT_TABLE = "lxsoftware-admin-records"
DEFAULT_REGION = "ap-southeast-1"
DEFAULT_EXPIRY_DAYS = 90


def _table(args: argparse.Namespace):
    return boto3.resource("dynamodb", region_name=args.region).Table(args.table)


def _validate_expires_at(raw: str | None) -> str:
    if raw is None:
        return (datetime.now(timezone.utc) + timedelta(days=DEFAULT_EXPIRY_DAYS)).date().isoformat()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        sys.exit(f"error: --expires-at {raw!r} is not an ISO date/datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed <= datetime.now(timezone.utc):
        sys.exit(f"error: --expires-at {raw!r} is in the past")
    return raw


def _parse_scopes(raw: str | None) -> list[str]:
    text = (raw or SCOPE_FINANCE).strip()
    scopes = sorted({part.strip() for part in text.split(",") if part.strip()})
    if not scopes:
        sys.exit("error: --scopes must list at least one scope")
    unknown = [s for s in scopes if s not in ALL_SCOPES]
    if unknown:
        sys.exit(f"error: unknown scopes {unknown}; allowed: {', '.join(sorted(ALL_SCOPES))}")
    return scopes


def _parse_cidrs(raw: str | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        cidr = part.strip()
        if not cidr:
            continue
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            sys.exit(f"error: --allowed-cidrs entry {cidr!r} is not a CIDR")
        out.append(cidr)
    return out


def cmd_create(args: argparse.Namespace) -> None:
    expires_at = _validate_expires_at(args.expires_at)
    scopes = _parse_scopes(args.scopes)
    cidrs = _parse_cidrs(args.allowed_cidrs)
    plaintext = KEY_PLAINTEXT_PREFIX + secrets.token_urlsafe(36)
    digest = hash_api_key(plaintext)
    key_id = uuid.uuid4().hex[:12]
    item = {
        "pk": f"{API_KEY_PK_PREFIX}{digest}",
        "sk": "META",
        "keyId": key_id,
        "label": args.label,
        "scope": "read",
        "scopes": scopes,
        "revoked": False,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "expiresAt": expires_at,
    }
    if cidrs:
        item["allowedCidrs"] = cidrs
    try:
        _table(args).put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(pk)",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            sys.exit("error: hash collision (retry)")
        raise
    print(f"keyId:  {key_id}")
    print(f"label:  {args.label}")
    print(f"scopes: {','.join(scopes)}")
    print(f"expires: {expires_at}")
    if cidrs:
        print(f"cidrs:  {','.join(cidrs)}")
    if args.plaintext_out:
        # CI mode (public repo — logs are world-readable): never print the
        # key; write it to a file for the caller to encrypt/deliver.
        out_path = Path(args.plaintext_out)
        out_path.touch(mode=0o600, exist_ok=False)
        out_path.write_text(plaintext + "\n", encoding="utf-8")
        print(f"API key written to {out_path} (shown nowhere else)")
        return
    print()
    print("API key (shown once, store it now):")
    print(f"  {plaintext}")
    print()
    print("Example:")
    print(f'  curl -H "x-api-key: {plaintext}" <AdminApiBaseUrl>/public/finance')
    if "siutindei-board-ops" in scopes or "siutindei-board-full" in scopes:
        print(f'  curl -H "x-api-key: {plaintext}" <AdminApiBaseUrl>/public/siu-tin-dei/board')


def _scan_keys(args: argparse.Namespace) -> list[dict]:
    table = _table(args)
    items: list[dict] = []
    kwargs: dict = {
        "FilterExpression": "begins_with(pk, :p)",
        "ExpressionAttributeValues": {":p": API_KEY_PK_PREFIX},
    }
    while True:
        res = table.scan(**kwargs)
        items.extend(res.get("Items", []))
        lek = res.get("LastEvaluatedKey")
        if not lek:
            return items
        kwargs["ExclusiveStartKey"] = lek


def cmd_list(args: argparse.Namespace) -> None:
    items = _scan_keys(args)
    if not items:
        print("no API keys found")
        return
    for it in sorted(items, key=lambda x: str(x.get("createdAt", ""))):
        state = "revoked" if it.get("revoked") else "active"
        expires = it.get("expiresAt") or "never"
        scopes = it.get("scopes") or ([SCOPE_FINANCE] if it.get("scope") == "read" else [])
        if isinstance(scopes, list):
            scopes_s = ",".join(str(s) for s in scopes)
        else:
            scopes_s = str(scopes)
        print(
            f"{it.get('keyId')}  {state:8}  label={it.get('label')!r}  "
            f"scopes={scopes_s}  created={it.get('createdAt')}  expires={expires}"
        )


def cmd_revoke(args: argparse.Namespace) -> None:
    matches = [i for i in _scan_keys(args) if i.get("keyId") == args.key_id]
    if not matches:
        sys.exit(f"error: no API key with keyId {args.key_id!r}")
    table = _table(args)
    for it in matches:
        table.update_item(
            Key={"pk": it["pk"], "sk": it["sk"]},
            UpdateExpression="SET revoked = :t",
            ExpressionAttributeValues={":t": True},
        )
        print(f"revoked keyId {args.key_id} (label={it.get('label')!r})")
    print("note: API Gateway caches authorizer verdicts for up to 60 seconds")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--table", default=DEFAULT_TABLE)
    common.add_argument("--region", default=DEFAULT_REGION)
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser(
        "create", parents=[common], help="mint a new read-only API key"
    )
    p_create.add_argument("--label", required=True, help="human-readable key name")
    p_create.add_argument(
        "--scopes",
        default=SCOPE_FINANCE,
        help="comma-separated scopes (default: finance). "
        f"Allowed: {', '.join(sorted(ALL_SCOPES))}",
    )
    p_create.add_argument(
        "--expires-at",
        default=None,
        help=f"ISO date/datetime (default: now + {DEFAULT_EXPIRY_DAYS} days)",
    )
    p_create.add_argument(
        "--allowed-cidrs",
        default=None,
        help="comma-separated CIDRs; when set, other source IPs are denied",
    )
    p_create.add_argument(
        "--plaintext-out",
        default=None,
        help="write the key to this file (mode 0600) instead of printing it; "
        "used by CI where logs must not contain the key",
    )
    p_create.set_defaults(func=cmd_create)

    p_list = sub.add_parser(
        "list", parents=[common], help="list all API keys (hashes never shown)"
    )
    p_list.set_defaults(func=cmd_list)

    p_revoke = sub.add_parser("revoke", parents=[common], help="revoke a key by keyId")
    p_revoke.add_argument("--key-id", required=True)
    p_revoke.set_defaults(func=cmd_revoke)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
