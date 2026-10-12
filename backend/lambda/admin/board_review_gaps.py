"""Today's review config-gap list. A read does not write the snapshot."""

from __future__ import annotations

import logging
from typing import Any


def _with_catalog_gap(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        import board_catalog_import

        gap = board_catalog_import.config_gap()
        if gap:
            return [*items, gap]
    except Exception:
        logging.getLogger(__name__).debug("suppressed", exc_info=True)
    return items


def listed_config_gaps(table: Any) -> list[dict[str, Any]] | None:
    """None when the gap cache cannot be read. An empty list is a real empty cache."""
    try:
        import board_duties

        items = board_duties.list_config_gaps(table)
    except Exception:
        return None
    if not isinstance(items, list):
        return None
    return _with_catalog_gap(items)


def attach_live_config_gaps(table: Any, review: dict[str, Any]) -> dict[str, Any]:
    """On-screen list and digest preview follow the cache. The stored snapshot is not written."""
    import board_review

    if not isinstance(review, dict):
        return review
    live = listed_config_gaps(table)
    if live is None:
        return review
    try:
        import board_dmarc_gaps

        active = board_dmarc_gaps.summary_gap_ids(table)
    except Exception:
        active = None
    if active is not None:
        live = [
            row
            for row in live
            if not str(row.get("gapId") or "").startswith("dmarc:") or str(row.get("gapId") or "") in active
        ]
    overlaid = {**review, "configGaps": live}
    overlaid["digestHtml"] = board_review.render_digest_html(overlaid)
    return overlaid


def config_gaps_section(table: Any) -> list[dict[str, Any]]:
    listed = listed_config_gaps(table)
    if listed is None:
        return _with_catalog_gap([])
    return listed


def for_get(table: Any, settings: dict[str, Any], date_hkt: str) -> dict[str, Any]:
    """Stored snapshot, or a compile, then today's live gap list."""
    import board_hk
    import board_review
    import board_store

    review = board_store.get_review_snapshot(table, date_hkt)
    if not review:
        review = board_review.compile(table, settings, date_hkt)
    if date_hkt == board_hk.today_hkt():
        review = attach_live_config_gaps(table, review)
    return review
