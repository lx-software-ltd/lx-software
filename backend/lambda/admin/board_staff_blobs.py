"""Staff scratchpad and deliverable blobs."""

from __future__ import annotations

import os
from typing import Any

from contract_constants import (
    BOARD_KEY,
)


def _memory_blobs_enabled() -> bool:
    from config import env_flag

    return env_flag("BOARD_BLOBS_IN_MEMORY")

def _blob_bucket() -> str:
    """S3 bucket, or empty when the in-memory test store is explicitly enabled."""
    from config import assets_bucket

    bucket = assets_bucket()
    if bucket:
        return bucket
    if _memory_blobs_enabled():
        return ""
    raise RuntimeError(
        "ASSETS_BUCKET_NAME is unset. Set BOARD_BLOBS_IN_MEMORY=1 to use the in-memory blob store."
    )

def _blob_put(key: str, body: bytes) -> None:
    from board_staff import _MEMORY_BLOBS
    bucket = _blob_bucket()
    if not bucket:
        _MEMORY_BLOBS[key] = body
        return
    import runtime

    runtime._s3.put_object(Bucket=bucket, Key=key, Body=body)

def _blob_delete(key: str) -> None:
    from board_staff import _MEMORY_BLOBS
    _MEMORY_BLOBS.pop(key, None)
    bucket = _blob_bucket()
    if not bucket:
        return
    import runtime

    runtime._s3.delete_object(Bucket=bucket, Key=key)

def _blob_get(key: str) -> bytes:
    from board_staff import _MEMORY_BLOBS
    if key in _MEMORY_BLOBS:
        return _MEMORY_BLOBS[key]
    bucket = _blob_bucket()
    if not bucket:
        return b""
    import runtime

    try:
        res = runtime._s3.get_object(Bucket=bucket, Key=key)
        return res["Body"].read()
    except Exception:
        return b""

def _scratchpad_key(task_id: str) -> str:
    return f"board/{BOARD_KEY}/staff/{task_id}/scratchpad.md"

def _deliverable_key(task_id: str, deliverable_type: str) -> str:
    ext = {"markdown": "md", "csv": "csv", "json": "json", "messages": "json"}.get(deliverable_type, "md")
    return f"board/{BOARD_KEY}/staff/{task_id}/deliverable.{ext}"

def _scratchpad_limit() -> int:
    """Read the cap from board_staff so tests can patch that module attribute."""
    import board_staff

    return int(board_staff.BOARD_STAFF_SCRATCHPAD_MAX_CHARS)


def _append_scratchpad(task: dict[str, Any], text: str) -> str:
    key = str(task.get("scratchpadKey") or _scratchpad_key(str(task["taskId"])))
    existing = _blob_get(key).decode("utf-8", errors="replace")
    combined = (existing + ("\n\n" if existing and text else "") + text).strip()
    limit = _scratchpad_limit()
    if len(combined) > limit:
        combined = combined[-limit:]
    _blob_put(key, combined.encode("utf-8"))
    return combined

def _prepend_scratchpad(task: dict[str, Any], text: str) -> str:
    key = str(task.get("scratchpadKey") or _scratchpad_key(str(task["taskId"])))
    existing = _blob_get(key).decode("utf-8", errors="replace")
    banner = str(text or "").strip()
    if not banner:
        return existing
    limit = _scratchpad_limit()
    if len(banner) >= limit:
        combined = banner[:limit]
        _blob_put(key, combined.encode("utf-8"))
        return combined
    keep = limit - len(banner) - 2
    if keep <= 0:
        tail = ""
    elif keep < len(existing):
        tail = existing[-keep:]
    else:
        tail = existing
    combined = (banner + ("\n\n" if tail else "") + tail).strip()
    if len(combined) > limit:
        combined = combined[:limit]
    _blob_put(key, combined.encode("utf-8"))
    return combined

def read_deliverable(task: dict[str, Any], *, limit: int = 12000) -> str:
    raw = _blob_get(str(task.get("deliverableKey") or "")).decode("utf-8", errors="replace")
    return raw[:limit]

def presign_deliverable(key: str) -> str:
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if not bucket or not key:
        return ""
    import runtime

    return runtime._s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=900,
    )
