#!/usr/bin/env python3
"""Mint one OpenRouter API key per catalog app on the LX Software account.

Each product (this admin, Evolve Sprouts, later Siu Tin Dei) stores *its*
named key in *its* secret. OpenRouter still bills the LX Software card;
Analytics splits by ``api_key_id``.

Requires a Management API key from
https://openrouter.ai/settings/management-keys (not a regular inference key).

Usage:
  OPENROUTER_MANAGEMENT_API_KEY=sk-or-... python3 scripts/mint-openrouter-app-keys.py
  OPENROUTER_MANAGEMENT_API_KEY=sk-or-... python3 scripts/mint-openrouter-app-keys.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "contracts" / "openrouter-apps.json"
KEYS_URL = "https://openrouter.ai/api/v1/keys"


def load_catalog() -> tuple[str, list[dict]]:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    payer = str(payload.get("payer") or "lxSoftware")
    apps = payload.get("apps")
    if not isinstance(apps, list):
        sys.exit("error: contracts/openrouter-apps.json has no apps list")
    return payer, [row for row in apps if isinstance(row, dict) and row.get("id")]


def _request(method: str, token: str, *, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urlrequest.Request(
        KEYS_URL,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        sys.exit(f"error: OpenRouter {method} {KEYS_URL} -> {exc.code}: {detail}")


def _existing_names(payload: dict) -> set[str]:
    rows = payload.get("data")
    if not isinstance(rows, list):
        return set()
    names: set[str] = set()
    for row in rows:
        if isinstance(row, dict) and row.get("name"):
            names.add(str(row["name"]))
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List catalog keys and which names are already on the account",
    )
    args = parser.parse_args()
    token = os.getenv("OPENROUTER_MANAGEMENT_API_KEY", "").strip()
    if not token:
        print(
            "Set OPENROUTER_MANAGEMENT_API_KEY to a key from "
            "https://openrouter.ai/settings/management-keys",
            file=sys.stderr,
        )
        return 2

    _payer, apps = load_catalog()
    listed = _request("GET", token)
    existing = _existing_names(listed)
    minted: dict[str, str] = {}
    skipped: list[str] = []

    for app in apps:
        app_id = str(app["id"])
        key_name = str(app.get("keyName") or f"lxsoftware:{app_id}")
        if key_name in existing:
            skipped.append(f"{app_id} ({key_name}) already exists")
            continue
        if args.dry_run:
            print(f"would create {key_name} for {app_id}")
            continue
        created = _request("POST", token, body={"name": key_name})
        data = created.get("data") if isinstance(created.get("data"), dict) else created
        plaintext = str((data or {}).get("key") or "").strip()
        if not plaintext:
            sys.exit(f"error: create {key_name} returned no key material")
        minted[app_id] = plaintext
        print(f"created {key_name}", file=sys.stderr)

    if args.dry_run:
        for line in skipped:
            print(f"skip {line}")
        return 0

    admin_json = {app_id: minted[app_id] for app_id, app in (
        (str(row["id"]), row) for row in apps
    ) if app.get("meteredHere") and app_id in minted}
    print("\n# This admin secret (lxsoftware-admin-openrouter-api-secret-*)")
    print("# Merge into the existing JSON. Do not commit these values.")
    print(json.dumps(admin_json or {"#": "no new metered keys; existing names were reused"}, indent=2))

    print("\n# Sibling product secrets (store the named key as a plain string)")
    for app in apps:
        if app.get("meteredHere"):
            continue
        app_id = str(app["id"])
        key_name = str(app.get("keyName") or f"lxsoftware:{app_id}")
        repo = str(app.get("repo") or "")
        if app_id in minted:
            print(f"# {repo}  keyName={key_name}")
            print(minted[app_id])
        else:
            print(f"# {repo}  {key_name} already existed — copy the plaintext from OpenRouter if you still have it, or mint a replacement.")
    for line in skipped:
        print(f"# {line}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
