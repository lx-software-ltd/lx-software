"""Copy message media to the assets bucket. Runs on the follow-up, or when the owner first opens it."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib import request as urlrequest

import board_meta
import board_meta_token
import board_store
from contract_constants import BOARD_TOOLS_CONTRACT
from http_common import _log_event

_MAX_BYTES = int(BOARD_TOOLS_CONTRACT["limits"]["metaMediaMaxBytes"])
_PREFIX = "board/meta-media"
_INLINE = ("image/", "audio/", "video/", "application/pdf")


def fetch_pending(table: Any, message: dict[str, Any]) -> bool:
    """Store every attachment that is not stored yet. True when the message row changed."""
    attachments = message.get("attachments") or []
    changed = False
    for index, item in enumerate(attachments):
        if not isinstance(item, dict) or item.get("key"):
            continue
        found = _download(item, whatsapp=message.get("channel") == "whatsapp")
        if found is None:
            continue
        body, mime = found
        key = f"{_PREFIX}/{message.get('threadId')}/{hashlib.sha256(str(message.get('messageId')).encode()).hexdigest()[:16]}/{index}"
        if _put(key, body, mime):
            item.update({"key": key, "size": len(body), "sha256": hashlib.sha256(body).hexdigest(), "mime": mime})
            item.pop("url", None)
            changed = True
    if changed:
        board_store.put_meta_message(table, message)
    return changed


def presign(item: dict[str, Any]) -> str:
    key = str(item.get("key") or "")
    if not key.startswith(_PREFIX + "/"):
        return ""
    mime = str(item.get("mime") or "application/octet-stream")
    # Anything a browser could run is downloaded, never shown from the bucket's origin.
    inline = mime.startswith(_INLINE)
    try:
        import runtime
        from config import assets_bucket

        bucket = assets_bucket()
        if not bucket:
            return ""
        params = {
            "Bucket": bucket,
            "Key": key,
            "ResponseContentDisposition": "inline" if inline else "attachment",
            "ResponseContentType": mime if inline else "application/octet-stream",
        }
        return runtime._s3.generate_presigned_url("get_object", Params=params, ExpiresIn=900)
    except Exception as exc:
        _log_event("warning", tag="board_meta_media_presign_failed", error=str(exc)[:200])
        return ""


def _download(item: dict[str, Any], *, whatsapp: bool) -> tuple[bytes, str] | None:
    mime = str(item.get("mime") or "")
    url = str(item.get("url") or "")
    headers = {"User-Agent": "lxsoftware-board-meta"}
    media_id = str(item.get("mediaId") or "")
    if not url and whatsapp and media_id:
        # WhatsApp sends an id. Graph trades it for a short-lived URL that needs the same token.
        try:
            info = board_meta.graph("GET", media_id)
        except board_meta.MetaError as exc:
            _log_event("info", tag="board_meta_media_lookup_failed", error=str(exc)[:200])
            return None
        url = str(info.get("url") or "")
        mime = mime or str(info.get("mime_type") or "")
        headers["Authorization"] = f"Bearer {board_meta_token.board_token()}"
    body = _fetch(url, headers)
    if body is None:
        return None
    return body, mime or "application/octet-stream"


def _fetch(url: str, headers: dict[str, str]) -> bytes | None:
    if not url.startswith("https://"):
        return None
    try:
        with urlrequest.urlopen(urlrequest.Request(url, method="GET", headers=headers), timeout=10) as resp:  # noqa: S310 # nosec B310
            body = resp.read(_MAX_BYTES + 1)
    except Exception as exc:
        _log_event("info", tag="board_meta_media_fetch_failed", error=str(exc)[:200])
        return None
    if not body or len(body) > _MAX_BYTES:
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
