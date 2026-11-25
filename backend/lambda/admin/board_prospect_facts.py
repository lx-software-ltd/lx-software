"""Facts already stored on a prospect, and a score call that survives contact lookup."""

from __future__ import annotations

from typing import Any

import board_store
from http_common import _log_event


def public_for_score(prospect: dict[str, Any], *, website: str, pseud: Any) -> dict[str, Any]:
    """Rubric inputs that do not need a homepage.

    ``rating`` with ``reviewCount``, ``placesTypes``, ``source`` and
    ``category`` are enough for the lines that mention a Google rating,
    a venue, children's activities, or a restaurant.
    """
    stored = prospect.get("raw")
    raw: dict[str, Any] = stored if isinstance(stored, dict) else {}
    review_count = raw.get("userRatingCount")
    if review_count is None:
        review_count = raw.get("reviewCount")
    if review_count is None:
        review_count = raw.get("user_ratings_total")
    types = raw.get("types") if raw.get("types") is not None else raw.get("placesTypes")
    category = raw.get("category") or raw.get("openDataCategory") or prospect.get("category") or ""
    phone = str(prospect.get("phone") or "")
    return {
        "name": prospect.get("name"),
        "type": prospect.get("type"),
        "district": prospect.get("district"),
        "website": website,
        "rating": raw.get("rating"),
        "reviewCount": review_count,
        "placesTypes": list(types) if isinstance(types, (list, tuple)) else [],
        "source": prospect.get("source") or "",
        "category": category,
        "email": pseud.alias_for_address(str(prospect.get("email") or "")),
        "phone": pseud.alias_for("phone", phone) if phone else "",
    }


def score_and_qualify(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Score, qualify, then look up a contact. A contact failure still returns the score."""
    import board_prospects

    row = board_store.get_prospect(ctx.table, str(args.get("id") or args.get("prospectId") or ""))
    if not row:
        return {"error": "prospect not found"}
    score_n, note = board_prospects.score(ctx.table, ctx.settings, row)
    row = board_prospects.qualify(ctx.table, ctx.settings, row)
    contact = ""
    try:
        board_prospects.find_contact(ctx.table, ctx.settings, row)
    except Exception as exc:
        _log_event("warning", tag="board_score_contact_failed", error=str(exc)[:200])
        contact = "lookup failed"
    row = board_store.get_prospect(ctx.table, str(row.get("prospectId") or "")) or row
    out: dict[str, Any] = {
        "score": score_n,
        "note": note,
        "prospect": board_prospects.mask_row(ctx.table, row),
    }
    if contact:
        out["contact"] = contact
    return out
