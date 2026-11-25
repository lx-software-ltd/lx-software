"""Content duties follow perWeek. Zero counts are a pause, not an empty plan."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import board_hk
import board_store

_SOCIAL = ("facebook", "instagram", "instagram_story")


def _count(per: dict[str, Any], key: str) -> int:
    try:
        return int(per.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _per_week(cfg: dict[str, Any]) -> dict[str, Any]:
    raw = cfg.get("perWeek")
    return raw if isinstance(raw, dict) else {}


def skip_plan(cfg: dict[str, Any]) -> bool:
    """True when every social channel is 0 and no seo items are due."""
    per = _per_week(cfg)
    return all(_count(per, channel) == 0 for channel in _SOCIAL) and _count(per, "seo") <= 0


def social_sentence(cfg: dict[str, Any]) -> str:
    per = _per_week(cfg)
    parts = [f"{_count(per, channel)} {channel}" for channel in _SOCIAL]
    total = sum(_count(per, channel) for channel in _SOCIAL)
    return f"Social week is {total} items ({', '.join(parts)}); seo items are extra."


def plan_brief(cfg: dict[str, Any], context: str) -> str:
    return (
        'Plan next week\'s content calendar as JSON {"items":[...]} with slotAt, channel, '
        f"pillar, copyEn, copyZh, hashtags, template, fields, linkPath. Pillars: {cfg.get('pillars')}. "
        f"Per week: {cfg.get('perWeek')}. Windows HKT: {cfg.get('windowsHkt')}. "
        f"{social_sentence(cfg)} "
        "Stage it with content_stage_items in batches of at most 6 items, then task_finish "
        'with {"items":[]}. Staged items are merged into the deliverable. Do not put the '
        "full week in one task_finish. Do not invent photos of children.\n\n" + context
    )


def published_recently(table: Any, *, days: int = 7) -> bool:
    cutoff = board_hk.to_iso(datetime.now(timezone.utc) - timedelta(days=days))
    for row in board_store.list_content(table, "published", limit=80):
        stamp = str(row.get("publishedAt") or "")
        if stamp and stamp >= cutoff:
            return True
    return False
