"""LinkedIn posts for a public API key.

Scope ``lxsoftware-linkedin`` on ``GET /public/lx-software/linkedin/posts``.
With no query the read is published posts. ``?status=`` selects
``drafted``, ``approved``, ``published``, ``archived``, ``failed``, a
comma-separated list of those, or ``all``. The connection, tokens, and
image bytes stay on the JWT routes.
"""

from __future__ import annotations

from typing import Any

import board_public_api
import linkedin_store
from ddb_convert import _from_ddb_nested

PATH = board_public_api.LINKEDIN_POSTS_PATH
_STATUS_ERROR = "status must be drafted, approved, published, archived, failed, or all"
# DynamoDB pages the index. Fifty pages is far past a personal posting history;
# hitting it sets truncated instead of dropping the rest quietly.
_PAGE_CAP = 50
_COUNTS = ("impressions", "reactions", "comments")
_HIDDEN = ("pk", "sk", "gsi1pk", "gsi1sk", "expiresAt")


def published_posts(table: Any) -> dict[str, Any]:
    """Published posts only. The default read, and what the older tests call."""
    _code, payload = posts_response(table, None)
    return payload


def posts_response(table: Any, query: Any) -> tuple[int, dict[str, Any]]:
    """``(status_code, body)`` for the public posts route.

    ``query`` is the API Gateway ``queryStringParameters`` map. Missing or
    blank ``status`` means published posts, and that body has no top-level
    ``status`` key. An unknown status is 400.
    """
    wanted = _statuses(query)
    if wanted is None:
        return 400, {"message": _STATUS_ERROR}
    rows: list[dict[str, Any]] = []
    truncated = False
    for name in wanted:
        found, cut = _all_with_status(table, name)
        rows.extend(found)
        truncated = truncated or cut
    rows.sort(key=lambda doc: (str(doc.get("slotAt") or "9"), str(doc.get("createdAt") or "")))
    payload: dict[str, Any] = {"items": [published_post(row) for row in rows]}
    if _asked(query):
        payload["status"] = list(wanted)
    if truncated:
        payload["truncated"] = True
    return 200, payload


def _asked(query: Any) -> bool:
    return isinstance(query, dict) and bool(str(query.get("status") or "").strip())


def _statuses(query: Any) -> tuple[str, ...] | None:
    """Statuses to read. ``None`` when the caller named one this route does not serve."""
    raw = ""
    if isinstance(query, dict):
        raw = str(query.get("status") or "").strip().lower()
    if not raw:
        return ("published",)
    if raw == "all":
        return tuple(linkedin_store.STATUSES)
    chosen: list[str] = []
    for part in raw.split(","):
        name = part.strip()
        if not name or name in chosen:
            continue
        if name not in linkedin_store.STATUSES:
            return None
        chosen.append(name)
    return tuple(chosen) if chosen else None


def published_post(doc: dict[str, Any]) -> dict[str, Any]:
    platform = doc.get("platform") if isinstance(doc.get("platform"), dict) else {}
    image = linkedin_store.public_image(doc.get("image") if isinstance(doc.get("image"), dict) else None)
    picture = None
    if image:
        picture = {
            "status": image.get("status") or "",
            "caption": image.get("caption") or "",
        }
    return {
        "postId": doc.get("postId") or "",
        "status": doc.get("status") or "",
        "pillar": doc.get("pillar") or "",
        "seedId": doc.get("seedId") or "",
        "channel": doc.get("channel") or "profile",
        "body": doc.get("body") or "",
        "firstComment": doc.get("firstComment") or "",
        "hashtags": list(doc.get("hashtags") or []),
        "slotAt": doc.get("slotAt") or "",
        "publishedAt": str(platform.get("publishedAt") or ""),
        "url": str(platform.get("url") or ""),
        "metrics": _counts(doc.get("metrics")),
        "image": picture,
        "createdAt": doc.get("createdAt") or "",
    }


def _counts(metrics: Any) -> dict[str, Any] | None:
    if not isinstance(metrics, dict):
        return None
    counts = {key: metrics[key] for key in _COUNTS if key in metrics}
    return counts or None


def _all_with_status(table: Any, status: str) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    start: dict[str, Any] | None = None
    seen: set[str] = set()
    for _ in range(_PAGE_CAP):
        kwargs: dict[str, Any] = {
            "IndexName": "gsi1",
            "KeyConditionExpression": "gsi1pk = :pk",
            "ExpressionAttributeValues": {":pk": f"LINKEDIN#posts#{status}"},
            "ScanIndexForward": True,
        }
        if start:
            kwargs["ExclusiveStartKey"] = start
        res = table.query(**kwargs)
        if not isinstance(res, dict):
            break
        for row in res.get("Items") or []:
            if not isinstance(row, dict):
                continue
            doc = _from_ddb_nested({k: v for k, v in row.items() if k not in _HIDDEN})
            if isinstance(doc, dict):
                rows.append(doc)
        last = res.get("LastEvaluatedKey")
        token = repr(last)
        if not isinstance(last, dict) or token in seen:
            return rows, False
        seen.add(token)
        start = last
    return rows, True
