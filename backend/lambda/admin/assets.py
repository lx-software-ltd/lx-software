"""Admin API: assets."""

from __future__ import annotations

import os
from typing import Any

from botocore.exceptions import ClientError

import runtime
from http_common import (
    _audit,
    _decode_cursor,
    _encode_cursor,
    _json_response,
    _log_event,
    _request_id,
)
from contract_constants import FINANCE_STATEMENT_OWNER_KEYS
from runtime import ALLOWED_UPLOAD_CONTENT_TYPES

ASSET_PK_PREFIX = "ASSET#"
_INBOUND_OWNER_SEGMENTS = frozenset(
    key.lower() for key in FINANCE_STATEMENT_OWNER_KEYS
)


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
        if len(batch) != 32 or any(
            c not in "0123456789abcdef" for c in batch.lower()
        ):
            return None
        return key
    return None


def _assets_list_response(event: dict[str, Any]) -> dict[str, Any]:
    """Scan only ``ASSET#`` rows for the admin Assets page."""
    from urllib.parse import parse_qs

    from ddb_convert import _from_ddb
    from finance_store import _enrich_scan_items_asset_meta

    qs = event.get("rawQueryString") or ""
    cursor_raw = parse_qs(qs).get("cursor", [""])[0]
    start_key = _decode_cursor(cursor_raw)
    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
    kwargs: dict[str, Any] = {
        "Limit": 50,
        "FilterExpression": "begins_with(pk, :asset)",
        "ExpressionAttributeValues": {":asset": ASSET_PK_PREFIX},
    }
    if start_key:
        kwargs["ExclusiveStartKey"] = start_key
    result = table.scan(**kwargs)
    items = [_from_ddb(i) for i in result.get("Items", [])]
    bucket = os.environ.get("ASSETS_BUCKET_NAME") or ""
    items = _enrich_scan_items_asset_meta(items, table=table, bucket=bucket)
    last = result.get("LastEvaluatedKey")
    next_cursor = _encode_cursor(last) if last else None
    return _json_response(200, {"items": items, "nextCursor": next_cursor})


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
    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
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
            return _json_response(
                404, {"message": "Object not found in bucket"}
            )
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
    table = runtime._ddb.Table(os.environ["RECORDS_TABLE_NAME"])
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


