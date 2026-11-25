"""Current Meta insight metrics. Retired names are dropped before the Graph call."""

from __future__ import annotations

PAGE_DEFAULT = "page_media_view,page_total_media_view_unique,page_post_engagements"
IG_DEFAULT = "reach,views,profile_views"
PAGE_ALLOWED = frozenset(
    {
        "page_media_view",
        "page_total_media_view_unique",
        "page_post_engagements",
        "page_follows",
        "page_daily_follows_unique",
        "page_video_views",
    }
)
IG_ALLOWED = frozenset(
    {
        "reach",
        "views",
        "profile_views",
        "accounts_engaged",
        "total_interactions",
        "likes",
        "comments",
        "shares",
        "saves",
        "replies",
        "follows_and_unfollows",
        "profile_links_taps",
    }
)


def choose(raw: object, *, kind: str) -> tuple[str, list[str]]:
    """Keep allow-listed names. An empty or fully retired request uses the default set."""
    default = PAGE_DEFAULT if kind == "page" else IG_DEFAULT
    allowed = PAGE_ALLOWED if kind == "page" else IG_ALLOWED
    text = str(raw or "").strip()
    if not text:
        return default, []
    names = [part.strip() for part in text.split(",") if part.strip()]
    kept = [name for name in names if name in allowed]
    ignored = [name for name in names if name not in allowed]
    if not kept:
        return default, ignored
    return ",".join(kept), ignored
