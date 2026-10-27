"""Stamp gsi1 on existing ASSET# rows. Used by scripts/backfill-asset-index.py."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from assets import (
    ASSET_INDEX_UNKNOWN_TIME,
    ASSET_PK_PREFIX,
    asset_index_attributes,
    owner_from_inbound_key,
)

ASSET_BACKFILL_SCAN_LIMIT = 200
_MISSING_OBJECT_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


def _client_error_code(exc: BaseException) -> str:
    """Read a DynamoDB or S3 error code. Tests stub a second ``ClientError`` class."""
    if type(exc).__name__ != "ClientError":
        return ""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return ""
    error = response.get("Error")
    if not isinstance(error, dict):
        return ""
    return str(error.get("Code", ""))


def backfill_asset_index(
    table: Any,
    *,
    dry_run: bool = True,
    house_by_key: dict[str, str] | None = None,
    s3_client: Any = None,
    bucket: str | None = None,
) -> dict[str, Any]:
    """Stamp ``gsi1`` on ``ASSET#`` META rows so the Assets list can query them.

    ``dry_run`` reports ``pending`` and writes nothing. ``updated`` counts rows
    written. House values missing on the row come from the inbound key, then
    from ``house_by_key``. When ``house_by_key`` is omitted, statement lines
    are read once. A missing ``uploadedAt`` is read from S3 when ``bucket`` is set.
    """
    if house_by_key is None:
        from finance_store import _source_key_to_house_map

        house_by_key = _source_key_to_house_map(table)
    updated = 0
    pending = 0
    skipped = 0
    start_key: dict[str, Any] | None = None
    while True:
        page = _backfill_asset_index_page(
            table,
            start_key,
            dry_run=dry_run,
            house_by_key=house_by_key,
            s3_client=s3_client,
            bucket=bucket or "",
        )
        updated += page["updated"]
        pending += page["pending"]
        skipped += page["skipped"]
        start_key = page["nextKey"]
        if not start_key:
            break
    return {"updated": updated, "pending": pending, "skipped": skipped, "dryRun": dry_run}


def _backfill_asset_index_page(
    table: Any,
    start_key: dict[str, Any] | None,
    *,
    dry_run: bool,
    house_by_key: dict[str, str],
    s3_client: Any,
    bucket: str,
) -> dict[str, Any]:
    from ddb_convert import _from_ddb

    kwargs: dict[str, Any] = {
        "Limit": ASSET_BACKFILL_SCAN_LIMIT,
        "FilterExpression": "begins_with(pk, :asset)",
        "ExpressionAttributeValues": {":asset": ASSET_PK_PREFIX},
    }
    if start_key:
        kwargs["ExclusiveStartKey"] = start_key
    result = table.scan(**kwargs)
    updated = 0
    pending = 0
    skipped = 0
    for raw in result.get("Items", []):
        item = _from_ddb(raw)
        if item.get("sk") != "META" or (item.get("gsi1pk") and item.get("gsi1sk")):
            skipped += 1
            continue
        outcome = _stamp_asset_index(
            table,
            item,
            dry_run=dry_run,
            house_by_key=house_by_key,
            s3_client=s3_client,
            bucket=bucket,
        )
        if outcome == "pending":
            pending += 1
        elif outcome == "updated":
            updated += 1
        else:
            skipped += 1
    return {
        "updated": updated,
        "pending": pending,
        "skipped": skipped,
        "nextKey": result.get("LastEvaluatedKey"),
    }


def _uploaded_at_for_index(item: dict[str, Any], s3_key: str, s3_client: Any, bucket: str) -> str | None:
    """Stored upload time, else S3 LastModified. Never the 1970 sort placeholder."""
    stored = str(item.get("uploadedAt") or "").strip()
    if stored == ASSET_INDEX_UNKNOWN_TIME:
        stored = ""
    if stored:
        return stored
    if s3_client is None or not bucket or not s3_key:
        return None
    try:
        head = s3_client.head_object(Bucket=bucket, Key=s3_key)
    except Exception as exc:
        code = _client_error_code(exc)
        if code in _MISSING_OBJECT_CODES:
            return None
        raise
    last_mod = head.get("LastModified")
    if not isinstance(last_mod, datetime):
        return None
    from http_common import _utc_iso_z

    return _utc_iso_z(last_mod)


def _stamp_asset_index(
    table: Any,
    item: dict[str, Any],
    *,
    dry_run: bool,
    house_by_key: dict[str, str],
    s3_client: Any = None,
    bucket: str = "",
) -> str:
    """Return ``pending``, ``updated``, or ``skipped``. A deleted row is skipped."""
    pk = str(item.get("pk") or "")
    s3_key = pk[len(ASSET_PK_PREFIX) :] if pk.startswith(ASSET_PK_PREFIX) else pk
    uploaded = _uploaded_at_for_index(item, s3_key, s3_client, bucket)
    file_name = str(item.get("fileName") or "").strip() or os.path.basename(s3_key)
    house = str(item.get("house") or "").strip() or owner_from_inbound_key(s3_key) or house_by_key.get(s3_key) or ""
    index = asset_index_attributes(s3_key, uploaded or "")
    assignments = ["gsi1pk = :gpk", "gsi1sk = :gsk", "fileName = :fn"]
    values: dict[str, Any] = {":gpk": index["gsi1pk"], ":gsk": index["gsi1sk"], ":fn": file_name}
    if uploaded:
        assignments.append("uploadedAt = :ua")
        values[":ua"] = uploaded
    if house:
        assignments.append("house = :house")
        values[":house"] = house
    if dry_run:
        return "pending"
    try:
        table.update_item(
            Key={"pk": pk, "sk": "META"},
            UpdateExpression="SET " + ", ".join(assignments),
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(pk)",
        )
    except Exception as exc:
        if _client_error_code(exc) == "ConditionalCheckFailedException":
            return "skipped"
        raise
    return "updated"
