"""Upload one draft MP4 and wait until LinkedIn can post it.

The Videos API is a different call from the Images API: initialize, PUT each
byte range, finalize, then read status. A video that is still processing is
not a failed publish.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

import linkedin_api
import linkedin_store
from linkedin_api import REST, LinkedInApiError, _api_headers, _call, _error_message, _expect


def _part_id(headers: dict[str, str]) -> str:
    raw = str(headers.get("etag") or "").strip()
    if raw.startswith("W/"):
        raw = raw[2:].strip()
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    return raw


def _instructions(value: dict[str, Any]) -> list[dict[str, Any]]:
    raw = value.get("uploadInstructions")
    if not isinstance(raw, list) or not raw:
        raise LinkedInApiError("LinkedIn did not return a video upload.")
    rows: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict) or not str(row.get("uploadUrl") or ""):
            raise LinkedInApiError("LinkedIn did not return a video upload.")
        rows.append(row)
    return rows


def upload_video(token: str, owner: str, data: bytes) -> str:
    """Register, upload, and finalize. Returns the video URN. Does not poll."""
    status, _headers, payload = _call(
        "POST",
        f"{REST}/videos?action=initializeUpload",
        _api_headers(token, json_body=True),
        json.dumps(
            {
                "initializeUploadRequest": {
                    "owner": owner,
                    "fileSizeBytes": len(data),
                    "uploadCaptions": False,
                    "uploadThumbnail": False,
                }
            }
        ).encode("utf-8"),
        timeout=60,
    )
    parsed = _expect(status, payload, ok={200})
    value = parsed.get("value") if isinstance(parsed.get("value"), dict) else {}
    video_urn = str(value.get("video") or "")
    upload_token = value.get("uploadToken")
    if not video_urn or not isinstance(upload_token, str):
        raise LinkedInApiError("LinkedIn did not return a video upload.")
    part_ids: list[str] = []
    for part in _instructions(value):
        first = int(part.get("firstByte") or 0)
        last_byte = part.get("lastByte")
        if last_byte is None:
            raise LinkedInApiError("LinkedIn returned a video upload outside the file.")
        last = int(last_byte)
        if last < first or last >= len(data):
            raise LinkedInApiError("LinkedIn returned a video upload outside the file.")
        # The upload URL is pre-signed. LinkedIn's sample sends only Content-Type.
        # The image upload is the call that still sends Authorization.
        put_status, put_headers, put_payload = _call(
            "PUT",
            str(part["uploadUrl"]),
            {"Content-Type": "application/octet-stream"},
            data[first : last + 1],
            timeout=60,
        )
        if put_status not in {200, 201}:
            raise LinkedInApiError(_error_message(put_payload, put_status), status=put_status)
        part_id = _part_id(put_headers)
        if not part_id:
            raise LinkedInApiError("LinkedIn did not confirm a video part.")
        part_ids.append(part_id)
    final_status, _final_headers, final_payload = _call(
        "POST",
        f"{REST}/videos?action=finalizeUpload",
        _api_headers(token, json_body=True),
        json.dumps(
            {
                "finalizeUploadRequest": {
                    "video": video_urn,
                    "uploadToken": upload_token,
                    "uploadedPartIds": part_ids,
                }
            }
        ).encode("utf-8"),
        timeout=60,
    )
    _expect(final_status, final_payload, ok={200})
    return video_urn


def video_status(token: str, video_urn: str) -> str:
    encoded = urllib.parse.quote(video_urn, safe="")
    status, _headers, payload = _call(
        "GET",
        f"{REST}/videos/{encoded}",
        _api_headers(token),
        None,
        timeout=20,
    )
    parsed = _expect(status, payload, ok={200})
    return str(parsed.get("status") or "")


def _stored_urn(chosen: dict[str, Any], author: str) -> str:
    """A video id can be reused only for the profile or page that uploaded it."""
    urn = str(chosen.get("mediaUrn") or "")
    if urn and str(chosen.get("mediaOwner") or "") == author:
        return urn
    return ""


def _remember_media(table: Any, post_id: str, urn: str, owner: str) -> None:
    """Write the video id onto the picture publishing will read, including a held redraw."""
    doc = linkedin_store.get_post(table, post_id)
    if not doc:
        raise LinkedInApiError("The attached video could not be loaded.")
    image = dict(doc.get("image") or {})
    chosen = linkedin_store.publishable_image(image) or image
    chosen["mediaUrn"] = urn
    chosen["mediaOwner"] = owner
    doc["image"] = image
    linkedin_store.put_post(table, doc)


def _ready_video_urn(table: Any, doc: dict[str, Any], token: str, author: str, chosen: dict[str, Any]) -> str:
    post_id = str(doc["postId"])
    urn = _stored_urn(chosen, author)
    if not urn:
        loaded = linkedin_store.load_post_image(post_id)
        if not loaded:
            raise LinkedInApiError("The attached video could not be loaded.")
        urn = upload_video(token, author, loaded[1])
        _remember_media(table, post_id, urn, author)
    status = video_status(token, urn)
    if status == "PROCESSING_FAILED":
        _remember_media(table, post_id, "", "")
        raise LinkedInApiError("LinkedIn could not process the video.")
    if status != "AVAILABLE":
        waiting = LinkedInApiError("The video is still processing on LinkedIn.", counts_attempt=False)
        waiting.defer = True
        raise waiting
    return urn


def attachment_for_publish(table: Any, doc: dict[str, Any], token: str, author: str) -> tuple[str, str, bool]:
    """Media URN, alt text, and whether a picture was skipped because it was not ready."""
    image_meta = doc.get("image") if isinstance(doc.get("image"), dict) else None
    chosen = linkedin_store.publishable_image(image_meta)
    if not chosen:
        skipped = bool(image_meta and str(image_meta.get("status") or "") in ("pending", "failed"))
        return "", "", skipped
    if str(chosen.get("contentType") or "") == "video/mp4":
        return _ready_video_urn(table, doc, token, author, chosen), "", False
    loaded = linkedin_store.load_post_image(str(doc["postId"]))
    if not loaded:
        raise LinkedInApiError("The attached image could not be loaded.")
    alt = linkedin_store.caption_alt(str(chosen.get("caption") or ""))
    return linkedin_api.upload_image(token, author, loaded[1]), alt, False


def publish_ready(table: Any, publish_one: Any, *, record_failure: Any, log: Any) -> int:
    """Post one due draft. A video that is still processing does not take the slot or send mail."""
    published = 0
    for row in linkedin_store.posts_ready_to_publish(table):
        post_id = str(row.get("postId") or "")
        try:
            publish_one(table, row)
        except Exception as exc:  # noqa: BLE001 — a real failure stops this tick; processing does not
            if getattr(exc, "defer", False):
                continue
            log(str(exc)[:240])
            try:
                counts = exc.counts_attempt if isinstance(exc, LinkedInApiError) else True
                record_failure(table, post_id, str(exc), count_attempt=counts)
            except linkedin_store.LinkedInError:
                log("post not found")
            break
        published += 1
        break
    return published
