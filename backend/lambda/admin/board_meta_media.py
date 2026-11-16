"""Read the connected Instagram account: recent posts and current stories.

Publishing already uses the Page token. This is the read that was missing,
so a timed-out publish can be checked against what Instagram actually has.
"""

from __future__ import annotations

from typing import Any

import board_meta

_MEDIA_FIELDS = "id,caption,media_type,media_product_type,timestamp,permalink"
_STORY_FIELDS = "id,media_type,timestamp"
_CAPTION_MAX = 400


def _limit(raw: Any) -> int:
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        limit = 25
    return max(1, min(50, limit))


def _post(row: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(row.get("id") or ""),
        "caption": str(row.get("caption") or "")[:_CAPTION_MAX],
        "mediaType": str(row.get("media_type") or ""),
        "productType": str(row.get("media_product_type") or ""),
        "timestamp": str(row.get("timestamp") or ""),
        "permalink": str(row.get("permalink") or ""),
    }


def _story(row: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(row.get("id") or ""),
        "mediaType": str(row.get("media_type") or ""),
        "timestamp": str(row.get("timestamp") or ""),
    }


def list_instagram(*, limit: int = 25) -> dict[str, Any]:
    ig_id = board_meta.ig_user_id()
    if not ig_id:
        raise board_meta.MetaError("META_IG_USER_ID is not set.")
    capped = _limit(limit)
    media = board_meta.graph_pages(
        "GET",
        f"{ig_id}/media",
        {"fields": _MEDIA_FIELDS, "limit": capped},
        limit=capped,
        timeout=board_meta.HTTP_TIMEOUT_SLOW_SECONDS,
    )
    stories: list[dict[str, Any]] = []
    stories_error = ""
    try:
        stories = board_meta.graph_pages(
            "GET",
            f"{ig_id}/stories",
            {"fields": _STORY_FIELDS, "limit": capped},
            limit=capped,
            timeout=board_meta.HTTP_TIMEOUT_SLOW_SECONDS,
        )
    except board_meta.MetaError as exc:
        stories_error = str(exc)[:200]
    return {
        "igUserId": ig_id,
        "media": [_post(row) for row in media],
        "stories": [_story(row) for row in stories],
        "storiesError": stories_error,
    }


def op_list(_ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    return list_instagram(limit=args.get("limit") or 25)
