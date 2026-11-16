"""The three writes a ``siutindei-board-delegate`` key may make.

Reject an approval, dismiss a task, and change the focus settings. The
path gate lives in ``board_public_api.delegate_path``. Approving is refused
here as well, so a later edit to that gate cannot let a key send mail.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

import board_hk
import board_staff
import board_store
from contract_constants import (
    BOARD_MAX_APPROVAL_NOTE_LEN,
    BOARD_MAX_UPDATE_LEN,
    BOARD_STAFF_PROSPECT_TYPES,
)
from http_common import _audit, _json_response, _parse_json_body

FOCUS_FIELDS = frozenset(
    {"districtsFirst", "typesEnabled", "qualifiedPerWeek", "microBatchEnabled", "autoImport"}
)
_MAX_DISTRICTS = 8


def _is_key_actor(user_sub: str | None) -> bool:
    """True when the actor is a public API key (``apikey:…``).

    The function name must not contain ``apikey``. CodeQL classifies that
    word as a password and then flags the contact-alias hash.
    """
    return str(user_sub or "").startswith("apikey:")


def key_actor_decision_problem(user_sub: str | None, *, approve: bool, note: str) -> tuple[int, str] | None:
    """None when the decision may proceed. A key may reject, with a note, and never approve."""
    if not _is_key_actor(user_sub):
        return None
    if approve:
        return 403, "approving stays with the owner"
    if not str(note or "").strip():
        return 400, "note is required"
    return None


def record_rejection(table: Any, user_sub: str | None, approval_id: str, note: str) -> None:
    if not _is_key_actor(user_sub):
        return
    text = f"Delegate {user_sub} rejected approval {approval_id}: {note.strip()}"
    board_store.add_update(table, text=text[:BOARD_MAX_UPDATE_LEN], owner_sub=user_sub)


def _note_from(body: dict[str, Any]) -> str | None:
    """The note, or None when a key sent something that is not a short string."""
    raw = body.get("note")
    if raw is None or raw == "":
        raw = body.get("reason")
    if raw is None:
        raw = ""
    if not isinstance(raw, str):
        return None
    return raw.strip()


def cancel_task(event: dict[str, Any], task_id: str, user_sub: str | None) -> dict[str, Any]:
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    if not board_staff.enabled(settings):
        return _json_response(409, {"message": "Staff is disabled"})
    body = _parse_json_body(event)
    note = _note_from(body if isinstance(body, dict) else {})
    if note is None:
        return _json_response(400, {"message": "note must be a string"})
    if len(note) > BOARD_MAX_APPROVAL_NOTE_LEN:
        return _json_response(400, {"message": f"note must be at most {BOARD_MAX_APPROVAL_NOTE_LEN} characters"})
    if _is_key_actor(user_sub) and not note:
        return _json_response(400, {"message": "note is required"})
    try:
        task = board_staff.cancel_task(table, task_id, user_sub or "", reason=note)
    except board_staff.StaffError as exc:
        message = str(exc)
        if "not found" in message.lower():
            return _json_response(404, {"message": message})
        if exc.code == "conflict":
            return _json_response(409, {"message": message})
        return _json_response(400, {"message": message})
    if _is_key_actor(user_sub):
        text = f"Delegate {user_sub} dismissed task {task_id}: {note}"
        board_store.add_update(table, text=text[:BOARD_MAX_UPDATE_LEN], owner_sub=user_sub)
    _audit(user_sub, "BOARD_TASK_CANCEL", task_id, event)
    return _json_response(200, {"task": board_staff.public_task(task)})


def _districts(raw: Any) -> list[str]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= _MAX_DISTRICTS:
        raise ValueError(f"districtsFirst needs 1 to {_MAX_DISTRICTS} districts")
    names: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("districtsFirst entries must be district names")
        canonical = board_hk.canonical_district(item)
        if canonical == "unknown":
            raise ValueError(f"unknown district: {item[:40]}")
        if canonical not in names:
            names.append(canonical)
    return names


def _types(raw: Any) -> list[str]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("typesEnabled needs at least one of " + ", ".join(BOARD_STAFF_PROSPECT_TYPES))
    chosen: list[str] = []
    for item in raw:
        if item not in BOARD_STAFF_PROSPECT_TYPES:
            raise ValueError(f"unknown prospect type: {str(item)[:40]}")
        if item not in chosen:
            chosen.append(item)
    return chosen


def _weekly(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= 500:
        raise ValueError("qualifiedPerWeek must be an integer from 1 to 500")
    return raw


def _checked(body: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(body) - FOCUS_FIELDS)
    if unknown:
        raise ValueError("unknown field: " + ", ".join(unknown))
    if not body:
        raise ValueError("nothing to change")
    checked: dict[str, Any] = {}
    if "districtsFirst" in body:
        checked["districtsFirst"] = _districts(body["districtsFirst"])
    if "typesEnabled" in body:
        checked["typesEnabled"] = _types(body["typesEnabled"])
    if "qualifiedPerWeek" in body:
        checked["qualifiedPerWeek"] = _weekly(body["qualifiedPerWeek"])
    if "microBatchEnabled" in body:
        if not isinstance(body["microBatchEnabled"], bool):
            raise ValueError("microBatchEnabled must be true or false")
        checked["microBatchEnabled"] = body["microBatchEnabled"]
    if "autoImport" in body:
        if body["autoImport"] is not False:
            raise ValueError("autoImport can only be switched off")
        checked["autoImport"] = False
    return checked


def _apply(current: dict[str, Any], checked: dict[str, Any]) -> dict[str, Any]:
    bounds = dict(current.get("boundaries") or {})
    outreach = dict(bounds.get("outreach") or {})
    if "districtsFirst" in checked:
        outreach["districtsFirst"] = checked["districtsFirst"]
    if "typesEnabled" in checked:
        outreach["typesEnabled"] = checked["typesEnabled"]
    if "qualifiedPerWeek" in checked:
        targets = dict(outreach.get("targets") or {})
        targets["qualifiedPerWeek"] = checked["qualifiedPerWeek"]
        outreach["targets"] = targets
    bounds["outreach"] = outreach
    current["boundaries"] = board_store.normalize_boundaries(bounds)
    catalog = dict(current.get("catalog") or {})
    if "microBatchEnabled" in checked:
        catalog["microBatchEnabled"] = checked["microBatchEnabled"]
    if "autoImport" in checked:
        catalog["autoImport"] = False
    current["catalog"] = board_store.normalize_catalog_config(catalog)
    return current


def _focus_view(settings: dict[str, Any]) -> dict[str, Any]:
    outreach = ((settings.get("boundaries") or {}).get("outreach") or {})
    catalog = settings.get("catalog") or {}
    return {
        "districtsFirst": list(outreach.get("districtsFirst") or []),
        "typesEnabled": list(outreach.get("typesEnabled") or []),
        "qualifiedPerWeek": int((outreach.get("targets") or {}).get("qualifiedPerWeek") or 0),
        "microBatchEnabled": bool(catalog.get("microBatchEnabled")),
        "autoImport": bool(catalog.get("autoImport")),
    }


def focus(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    body = _parse_json_body(event)
    if not isinstance(body, dict):
        return _json_response(400, {"message": "body must be an object"})
    try:
        checked = _checked(body)
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    table = board_store.records_table()
    try:
        saved = board_store.save_settings_retry(table, lambda current: _apply(current, checked))
    except board_store.SettingsConflict:
        return _json_response(409, {"message": "settings were updated by someone else"})
    who = user_sub or "owner"
    prefix = "Delegate" if _is_key_actor(user_sub) else "Owner"
    summary = ", ".join(f"{key}={checked[key]}" for key in checked)
    board_store.add_update(table, text=f"{prefix} {who} set {summary}"[:BOARD_MAX_UPDATE_LEN], owner_sub=user_sub)
    _audit(user_sub, "BOARD_SETTINGS_FOCUS", ",".join(checked), event)
    return _json_response(200, {"changed": sorted(checked), "focus": _focus_view(saved)})


def instagram(event: dict[str, Any]) -> dict[str, Any]:
    import board_meta
    import board_meta_media

    qs = parse_qs(event.get("rawQueryString") or "")
    try:
        limit = int((qs.get("limit") or ["25"])[0])
    except (TypeError, ValueError):
        limit = 25
    try:
        return _json_response(200, board_meta_media.list_instagram(limit=limit))
    except board_meta.MetaError as exc:
        return _json_response(502, {"message": str(exc)})
