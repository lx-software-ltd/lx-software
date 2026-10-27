#!/usr/bin/env python3
"""Stamp gsi1 keys on ASSET# rows so GET /assets can query them.

The Assets page lists ``gsi1pk = ASSET`` newest first. Rows written before
that index was stamped stay off the list until this script applies. Download
by key still works without the index.

Dry-run is the default and writes nothing. Its JSON ``pending`` count is the
number of rows that would change. ``updated`` is the number written.
Pass ``ASSETS_BUCKET_NAME`` (the AdminApiFn value) so a row with no
``uploadedAt`` takes S3 LastModified. Without it, that row sorts last and the
upload time stays blank.

  AWS_REGION=ap-southeast-1 ASSETS_BUCKET_NAME=<bucket> python3 scripts/backfill-asset-index.py
  AWS_REGION=ap-southeast-1 ASSETS_BUCKET_NAME=<bucket> python3 scripts/backfill-asset-index.py --apply

Requires credentials that can Scan and UpdateItem the records table, HeadObject
on the assets bucket, plus kms:Decrypt and kms:GenerateDataKey on the table
key. The read-only cloud-agent user cannot apply this. The agent shell blocks
``--apply``.
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

from asset_backfill import backfill_asset_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--table",
        default=os.environ.get("RECORDS_TABLE_NAME", "lxsoftware-admin-records"),
        help="Records table name (default: lxsoftware-admin-records)",
    )
    parser.add_argument(
        "--bucket",
        default=os.environ.get("ASSETS_BUCKET_NAME", ""),
        help="Assets bucket used to read LastModified when uploadedAt is missing",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write index attributes. Without this flag the run only counts rows.",
    )
    args = parser.parse_args()
    table = boto3.resource("dynamodb").Table(args.table)
    s3 = boto3.client("s3") if args.bucket else None
    result = backfill_asset_index(
        table,
        dry_run=not args.apply,
        s3_client=s3,
        bucket=args.bucket or None,
    )
    print(json.dumps({"table": args.table, "bucket": args.bucket, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
