"""Fetch inbound media off the webhook path. Bytes live under board/meta-media/ for 90 days."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib import request as urlrequest

import board_store
from contract_constants import BOARD_TOOLS_CONTRACT
from http_common import _log_event

_LIMITS = BOARD_TOOLS_CONTRACT["limits"]
_MAX_BYTES = int(_LIMITS["metaMediaMaxBytes"])
_PREFIX = "board/meta-media"


def fetch_pending(table: Any, thread: dict[str, Any], message: dict[str, Any]) -> None:
    attachments = [item for item in message.get("attachments") or [] if isinstance(item, dict) and not item.get("key")]
    if not attachments:
        return
    changed = False
    for index, item in enumerate(attachments):
        url = str(item.get("url") or "")
        if not url:
            continue
        body = _fetch(url)
        if body is None:
            continue
        key = f"{_PREFIX}/{thread.get('threadId')}/{message.get('messageId')}/{index}"
        if _put(key, body, str(item.get("mime") or "application/octet-stream")):
            item["key"] = key
            item["size"] = len(body)
            item["sha256"] = hashlib.sha256(body).hexdigest()
            item.pop("url", None)
            changed = True
    if changed:
        message["attachments"] = attachments
        board_store.put_meta_message(table, message)


def presign(key: str) -> str:
    if not key.startswith(_PREFIX + "/"):
        return ""
    try:
        import runtime
        from config import assets_bucket

        bucket = assets_bucket()
        if not bucket:
            return ""
        return runtime._s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=900)
    except Exception as exc:
        _log_event("warning", tag="board_meta_media_presign_failed", error=str(exc)[:200])
        return ""


def _fetch(url: str) -> bytes | None:
    if not url.startswith("https://"):
        return None
    try:
        with urlrequest.urlopen(urlrequest.Request(url, method="GET"), timeout=10) as resp:  # noqa: S310
            body = resp.read(_MAX_BYTES + 1)
    except Exception as exc:
        _log_event("info", tag="board_meta_media_fetch_failed", error=str(exc)[:200])
        return None
    if len(body) > _MAX_BYTES:
        return None
    return body


def _put(key: str, body: bytes, mime: str) -> bool:
    try:
        import runtime
        from config import assets_bucket

        bucket = assets_bucket()
        if not bucket:
            return False
        runtime._s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=mime or "application/octet-stream")
        return True
    except Exception as exc:
        _log_event("warning", tag="board_meta_media_put_failed", error=str(exc)[:200])
        return False
