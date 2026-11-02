"""Published LinkedIn posts for a public API key.

Scope ``lxsoftware-linkedin`` on ``GET /public/lx-software/linkedin/posts``.
Drafts, the connection, tokens, and image bytes stay on the JWT routes.
"""

from __future__ import annotations

from typing import Any

import board_public_api
import linkedin_store

PATH = board_public_api.LINKEDIN_POSTS_PATH


def published_posts(table: Any) -> dict[str, Any]:
    rows = linkedin_store.list_posts(table, status="published", limit=200)
    return {"items": [published_post(row) for row in rows]}


def published_post(doc: dict[str, Any]) -> dict[str, Any]:
    platform = doc.get("platform") if isinstance(doc.get("platform"), dict) else {}
    image = linkedin_store.public_image(doc.get("image") if isinstance(doc.get("image"), dict) else None)
    picture = None
    if image:
        picture = {
            "status": image.get("status") or "",
            "caption": image.get("caption") or "",
        }
    metrics = doc.get("metrics") if isinstance(doc.get("metrics"), dict) else None
    return {
        "postId": doc.get("postId") or "",
        "pillar": doc.get("pillar") or "",
        "seedId": doc.get("seedId") or "",
        "channel": doc.get("channel") or "profile",
        "body": doc.get("body") or "",
        "firstComment": doc.get("firstComment") or "",
        "hashtags": list(doc.get("hashtags") or []),
        "slotAt": doc.get("slotAt") or "",
        "publishedAt": str(platform.get("publishedAt") or ""),
        "url": str(platform.get("url") or ""),
        "metrics": metrics,
        "image": picture,
        "createdAt": doc.get("createdAt") or "",
    }
