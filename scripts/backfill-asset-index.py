#!/usr/bin/env python3
"""Stamp gsi1 keys on ASSET# rows so GET /assets can query them.

The Assets page lists ``gsi1pk = ASSET`` newest first. Rows written before
that index was stamped stay off the list until this script applies. Download
by key still works without the index.

Dry-run is the default and writes nothing.

  AWS_REGION=ap-southeast-1 python3 scripts/backfill-asset-index.py
  AWS_REGION=ap-southeast-1 python3 scripts/backfill-asset-index.py --apply

Requires credentials that can Scan and UpdateItem the records table, plus
kms:Decrypt and kms:GenerateDataKey on its key. The read-only cloud-agent
user cannot apply this.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import boto3

_ADMIN_LAMBDA_DIR = Path(__file__).resolve().parents[1] / "backend" / "lambda" / "admin"
sys.path.insert(0, str(_ADMIN_LAMBDA_DIR))

from assets import backfill_asset_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--table",
        default=os.environ.get("RECORDS_TABLE_NAME", "lxsoftware-admin-records"),
        help="Records table name (default: lxsoftware-admin-records)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write index attributes. Without this flag the run only counts rows.",
    )
    args = parser.parse_args()
    table = boto3.resource("dynamodb").Table(args.table)
    result = backfill_asset_index(table, dry_run=not args.apply)
    print(json.dumps({"table": args.table, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
