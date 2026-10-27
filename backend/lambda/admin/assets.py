"""Admin API: assets."""

from __future__ import annotations

import os
from typing import Any

import board_store
import runtime
from botocore.exceptions import ClientError
from contract_constants import FINANCE_STATEMENT_OWNER_KEYS, STATEMENT_BOOK_LABELS
from http_common import (
    _audit,
    _decode_cursor,
    _encode_cursor,
    _json_response,
    _log_event,
    _request_id,
)
from runtime import ALLOWED_UPLOAD_CONTENT_TYPES

ASSET_PK_PREFIX = "ASSET#"
ASSET_INDEX_PK = "ASSET"
ASSET_INDEX_UNKNOWN_TIME = "1970-01-01T00:00:00.000Z"
ASSET_PAGE_SIZE = 50
ASSET_FILTER_READ_CAP = 1000
_STALE_CURSOR_MESSAGE = "cursor expired"
_PUBLIC_HIDDEN = frozenset({"gsi1pk", "gsi1sk"})
_INBOUND_OWNER_SEGMENTS = frozenset(key.lower() for key in FINANCE_STATEMENT_OWNER_KEYS)
_OWNER_DISPLAY_LABELS = {
    "hillmarton": "32 Hillmarton",
    "morrison": "The Morrison",
    **STATEMENT_BOOK_LABELS,
}


class _StaleAssetCursor(Exception):
    """The list cursor was not produced by the asset index query."""


def asset_index_attributes(s3_key: str, uploaded_at: str) -> dict[str, str]:
    """Index attributes for one confirmed asset, newest-last in ascending order."""
    stamp = uploaded_at.strip() or ASSET_INDEX_UNKNOWN_TIME
    return {"gsi1pk": ASSET_INDEX_PK, "gsi1sk": f"{stamp}#{s3_key}"}


def asset_index_for_persist(table: Any, asset_pk: str, s3_key: str, fallback_uploaded_at: str) -> dict[str, str]:
    """Sort by the row's stored ``uploadedAt`` when it already has one."""
    loaded = table.get_item(Key={"pk": asset_pk, "sk": "META"})
    prior = loaded.get("Item") if isinstance(loaded, dict) else None
    stored = str(prior.get("uploadedAt") or "").strip() if isinstance(prior, dict) else ""
    if stored == ASSET_INDEX_UNKNOWN_TIME:
        stored = ""
    return asset_index_attributes(s3_key, stored or fallback_uploaded_at)


def owner_from_inbound_key(s3_key: str) -> str | None:
    """Canonical finance owner encoded in ``inbound/{owner}/{batch}/…``."""
    if not s3_key.startswith("inbound/"):
        return None
    parts = s3_key.split("/")
    if len(parts) < 4:
        return None
    segment = parts[1].strip().lower()
    if segment not in _INBOUND_OWNER_SEGMENTS:
        return None
    for key in FINANCE_STATEMENT_OWNER_KEYS:
        if key.lower() == segment:
            return key
    return None


def present_asset_item(item: dict[str, Any]) -> dict[str, Any]:
    """List/read shape: no index attributes; fill file name and inbound owner."""
    out = {k: v for k, v in item.items() if k not in _PUBLIC_HIDDEN}
    pk = out.get("pk")
    s3_key = ""
    if isinstance(pk, str) and pk.startswith(ASSET_PK_PREFIX):
        s3_key = pk[len(ASSET_PK_PREFIX) :]
    if s3_key and not str(out.get("fileName") or "").strip():
        out["fileName"] = os.path.basename(s3_key)
    if s3_key and not str(out.get("house") or "").strip():
        owner = owner_from_inbound_key(s3_key)
        if owner:
            out["house"] = owner
    return out


def confirmed_asset_item(
    *,
    key: str,
    user_sub: str,
    head: dict[str, Any],
    body: dict[str, Any],
    house: str | None,
    uploaded_at: str,
) -> dict[str, Any]:
    """META row written by ``POST /assets/confirm``."""
    item: dict[str, Any] = {
        "pk": f"{ASSET_PK_PREFIX}{key}",
        "sk": "META",
        "size": int(head["ContentLength"]),
        "s3Etag": str(head.get("ETag", "")).strip('"'),
        "ownerSub": user_sub,
        "clientSha256": body.get("sha256"),
        "clientReportedSize": body.get("size"),
        "note": "size and s3Etag are from S3 head_object; client fields are informational only",
        "uploadedAt": uploaded_at,
        "fileName": os.path.basename(key),
        **asset_index_attributes(key, uploaded_at),
    }
    if house is not None:
        item["house"] = house
    return item


def _is_allowed_upload_content_type(content_type: str) -> bool:
    if not isinstance(content_type, str):
        return False
    ct = content_type.strip().lower()
    if ct.startswith("image/"):
        return True
    return ct in ALLOWED_UPLOAD_CONTENT_TYPES


def _normalize_public_asset_key(raw: Any) -> str | None:
    """Return a downloadable assets-bucket key, or None if invalid.

    Allows ``uploads/*`` (browser uploads) and
    ``inbound/{owner}/{batch}/…`` (SES → inbound-email Lambda). Owner may be
    a house (``hillmarton``) or a statement book (``lxSoftware``). Other
    prefixes are rejected.
    """
    if raw is None:
        return None
    key = str(raw).strip()
    if not key or ".." in key:
        return None
    if key.startswith("uploads/"):
        return key
    if key.startswith("inbound/"):
        parts = key.split("/")
        if len(parts) < 4:
            return None
        house_seg = parts[1].strip()
        if house_seg.lower() not in _INBOUND_OWNER_SEGMENTS:
            return None
        batch = parts[2]
        if len(batch) != 32 or any(c not in "0123456789abcdef" for c in batch.lower()):
            return None
        return key
    return None


def _asset_object_key(row: dict[str, Any]) -> str:
    pk = row.get("pk")
    if isinstance(pk, str) and pk.startswith(ASSET_PK_PREFIX):
        return pk[len(ASSET_PK_PREFIX) :]
    return ""


def _asset_matches(row: dict[str, Any], needle: str) -> bool:
    """Case-insensitive match on file name, object key, owner key, and owner label."""
    query = needle.strip().lower()
    if not query:
        return True
    s3_key = _asset_object_key(row)
    file_name = str(row.get("fileName") or "").strip() or (os.path.basename(s3_key) if s3_key else "")
    house = str(row.get("house") or "").strip() or (owner_from_inbound_key(s3_key) or "")
    haystack = "\n".join((file_name, s3_key, house, _OWNER_DISPLAY_LABELS.get(house, ""))).lower()
    return query in haystack


def _asset_index_key(row: dict[str, Any]) -> dict[str, str]:
    return {
        "gsi1pk": ASSET_INDEX_PK,
        "gsi1sk": str(row["gsi1sk"]),
        "pk": str(row["pk"]),
        "sk": "META",
    }


def _asset_query_start(raw: Any) -> dict[str, str] | None:
    """Accept only a cursor from this index. An old table-scan cursor is stale."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _StaleAssetCursor
    gsk = raw.get("gsi1sk")
    pk = raw.get("pk")
    if (
        raw.get("gsi1pk") != ASSET_INDEX_PK
        or raw.get("sk") != "META"
        or not isinstance(gsk, str)
        or not gsk
        or not isinstance(pk, str)
        or not pk.startswith(ASSET_PK_PREFIX)
    ):
        raise _StaleAssetCursor
    return _asset_index_key({"gsi1sk": gsk, "pk": pk})


def _query_asset_page(table: Any, start: dict[str, str] | None, limit: int) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "IndexName": "gsi1",
        "KeyConditionExpression": "gsi1pk = :pk",
        "ExpressionAttributeValues": {":pk": ASSET_INDEX_PK},
        "ScanIndexForward": False,
        "Limit": limit,
    }
    if start:
        kwargs["ExclusiveStartKey"] = start
    try:
        return table.query(**kwargs)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ValidationException":
            raise _StaleAssetCursor from exc
        raise


def _assets_page(table: Any, start: dict[str, str] | None, needle: str) -> tuple[list[dict[str, Any]], Any]:
    """One page of assets. A filter keeps reading the index until the page fills or the cap is hit."""
    from ddb_convert import _from_ddb

    if not needle:
        result = _query_asset_page(table, start, ASSET_PAGE_SIZE)
        decoded = [_from_ddb(raw) for raw in result.get("Items", [])]
        items = [present_asset_item(row) for row in decoded if row.get("sk") == "META"]
        return items, result.get("LastEvaluatedKey")

    matches: list[dict[str, Any]] = []
    examined = 0
    exclusive = start
    resume: Any = None
    while len(matches) < ASSET_PAGE_SIZE and examined < ASSET_FILTER_READ_CAP:
        result = _query_asset_page(table, exclusive, min(100, ASSET_FILTER_READ_CAP - examined))
        decoded = [_from_ddb(raw) for raw in result.get("Items", [])]
        examined += len(decoded)
        resume = result.get("LastEvaluatedKey")
        for index, row in enumerate(decoded):
            if row.get("sk") != "META" or not _asset_matches(row, needle):
                continue
            matches.append(present_asset_item(row))
            if len(matches) == ASSET_PAGE_SIZE:
                more = index < len(decoded) - 1 or resume
                return matches, _asset_index_key(row) if more else None
        if not resume:
            return matches, None
        exclusive = _asset_query_start(resume)
    return matches, resume


def _assets_list_response(event: dict[str, Any]) -> dict[str, Any]:
    """Return one page of confirmed assets, newest first, or one asset by key."""
    from urllib.parse import parse_qs

    qs = event.get("rawQueryString") or ""
    params = parse_qs(qs)
    key_raw = params.get("key", [""])[0]
    if key_raw:
        return _asset_meta_response(key_raw)
    cursor_raw = params.get("cursor", [""])[0]
    try:
        start_key = _asset_query_start(_decode_cursor(cursor_raw) if cursor_raw else None)
        table = board_store.records_table()
        items, last = _assets_page(table, start_key, params.get("q", [""])[0].strip()[:200])
    except _StaleAssetCursor:
        return _json_response(400, {"message": _STALE_CURSOR_MESSAGE})
    next_cursor = _encode_cursor(last) if last else None
    return _json_response(200, {"items": items, "nextCursor": next_cursor})


def _asset_meta_response(raw_key: Any) -> dict[str, Any]:
    """One confirmed asset for a deep link. Does not require the list index."""
    from ddb_convert import _from_ddb

    norm = _normalize_public_asset_key(raw_key)
    if norm is None:
        return _json_response(400, {"message": "key is required"})
    table = board_store.records_table()
    meta = table.get_item(Key={"pk": f"{ASSET_PK_PREFIX}{norm}", "sk": "META"})
    if "Item" not in meta:
        return _json_response(404, {"message": "Asset not found"})
    return _json_response(200, {"item": present_asset_item(_from_ddb(meta["Item"]))})


def _asset_download_presigned_response(
    event: dict[str, Any],
    user_sub: str | None,
    raw_key: Any,
) -> dict[str, Any]:
    """Issue a presigned GET for a confirmed asset (GET ?key=… or POST JSON body).

    Any admin may download any confirmed ``uploads/*`` or ``inbound/*`` object
    so statement lines and the Assets page work across uploaders and email
    ingestion.
    """
    norm = _normalize_public_asset_key(raw_key)
    if norm is None:
        return _json_response(400, {"message": "key is required"})
    table = board_store.records_table()
    meta = table.get_item(Key={"pk": f"ASSET#{norm}", "sk": "META"})
    if "Item" not in meta:
        _log_event(
            "warning",
            tag="asset_download_url_rejected",
            reason="not_confirmed",
            sub=user_sub,
            key=norm[:512],
            request_id=_request_id(event),
        )
        return _json_response(404, {"message": "Asset not found"})
    bucket = os.environ["ASSETS_BUCKET_NAME"]
    try:
        head_dl = runtime._s3.head_object(Bucket=bucket, Key=norm)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            _log_event(
                "warning",
                tag="asset_download_url_missing_object",
                sub=user_sub,
                key=norm[:512],
                s3_error_code=code,
                request_id=_request_id(event),
            )
            return _json_response(404, {"message": "Object not found in bucket"})
        raise
    params: dict[str, Any] = {"Bucket": bucket, "Key": norm}
    ct_dl = head_dl.get("ContentType")
    if isinstance(ct_dl, str) and ct_dl.strip():
        params["ResponseContentType"] = ct_dl.strip()
    url = runtime._s3.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=300,
    )
    _log_event(
        "info",
        tag="asset_download_url_issued",
        sub=user_sub,
        key=norm[:512],
        expires_in_seconds=300,
        request_id=_request_id(event),
    )
    _audit(user_sub, "ASSET_DOWNLOAD_URL", norm, event)
    return _json_response(200, {"url": url, "expiresIn": 300})


def _asset_delete_response(
    event: dict[str, Any],
    user_sub: str | None,
    raw_key: Any,
) -> dict[str, Any]:
    """Remove a confirmed asset object from S3 and delete its META row.

    Same key rules and confirmation requirement as download URLs: only
    ``uploads/*`` or validated ``inbound/*`` keys with an existing ``ASSET#``
    META record may be deleted.
    """
    norm = _normalize_public_asset_key(raw_key)
    if norm is None:
        return _json_response(400, {"message": "key is required"})
    table = board_store.records_table()
    ddb_key = {"pk": f"ASSET#{norm}", "sk": "META"}
    meta = table.get_item(Key=ddb_key)
    if "Item" not in meta:
        _log_event(
            "warning",
            tag="asset_delete_rejected",
            reason="not_confirmed",
            sub=user_sub,
            key=norm[:512],
            request_id=_request_id(event),
        )
        return _json_response(404, {"message": "Asset not found"})
    bucket = os.environ["ASSETS_BUCKET_NAME"]
    try:
        runtime._s3.delete_object(Bucket=bucket, Key=norm)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        _log_event(
            "warning",
            tag="asset_delete_s3_error",
            sub=user_sub,
            key=norm[:512],
            s3_error_code=code,
            request_id=_request_id(event),
        )
        raise
    table.delete_item(Key=ddb_key)
    _log_event(
        "info",
        tag="asset_delete_ok",
        sub=user_sub,
        key=norm[:512],
        request_id=_request_id(event),
    )
    _audit(user_sub, "ASSET_DELETE", norm, event)
    return _json_response(200, {"ok": True, "key": norm})
