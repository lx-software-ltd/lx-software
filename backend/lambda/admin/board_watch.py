"""Watchlist CRUD and weekly candidate discovery."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import board_hk
import board_store
from contract_constants import BOARD_STAFF_WATCH_KINDS
from http_common import _log_event

TARGET_QUERIES = (
    "kids activities Hong Kong",
    "children classes booking Hong Kong",
    "kids workshops Hong Kong",
    "family activities Hong Kong this weekend",
    "children sports classes Hong Kong",
    "kids art class Hong Kong",
    "outdoor playground Hong Kong kids",
    "STEM classes for children Hong Kong",
    "parent child activities Hong Kong",
    "kids camp Hong Kong",
    "兒童活動 香港",
    "親子活動 預約",
    "兒童興趣班 香港",
    "親子工作坊 香港",
    "兒童運動班 香港",
    "兒童藝術班 香港",
    "週末親子好去處 香港",
    "兒童 STEM 課程 香港",
    "親子遊樂場 香港",
    "兒童夏令營 香港",
)

IGNORED_DOMAINS = frozenset(
    {
        "google.com",
        "google.com.hk",
        "facebook.com",
        "instagram.com",
        "youtube.com",
        "youtu.be",
        "wikipedia.org",
        "gov.hk",
        "data.gov.hk",
        "tripadvisor.com",
        "tripadvisor.com.hk",
        "klook.com",
        "trip.com",
        "ctrip.com",
        "moneyhero.com.hk",
        "moneyhero.com",
        "scmp.com",
        "timeout.com",
        "timeout.com.hk",
        "lonelyplanet.com",
        "booking.com",
        "expedia.com",
        "airbnb.com",
        "yelp.com",
        "opentable.com",
        "eventbrite.com",
        "meetup.com",
        "reddit.com",
        "medium.com",
        "linkedin.com",
        "pinterest.com",
        "tiktok.com",
        "xiaohongshu.com",
        "openrice.com",
        "info.gov.hk",
        "news.gov.hk",
        # Parenting / lifestyle / travel media. Their round-ups rank for the
        # discovery queries but they list providers; they are not competitors.
        "hk01.com",
        "ulifestyle.com.hk",
        "bowtie.com.hk",
        "kkday.com",
        "sassymamahk.com",
        "sassymamasg.com",
        "littlestepsasia.com",
        "hongkongliving.com",
        "thehoneycombers.com",
        "thehkhub.com",
        "localiiz.com",
        "sundaykiss.com",
        "discoverhongkong.com",
        "traveloka.com",
        "thrillophilia.com",
        "18hall.com",
        "reubird.hk",
        "notesity.hk",
        "champimom.com",
        "yohohongkong.com",
        "travelababies.com",
        "kamadelivery.com",
        "daynightcatering.com",
        "mumonthemove.com",
    }
)
REJECTED_TLDS = (".tw", ".cn", ".sg")
HK_HOST_HINTS = (".hk",)
HK_TEXT_HINTS = ("hong kong", "hongkong", "香港", "kowloon", "new territories", "九龍", "新界")
MAX_ADDS_PER_WEEK = 10
_LISTICLE_RE = re.compile(r"^\s*\d+\s+(best|top)|^\s*(best|top)\s+\d+", re.I)
# Search-result titles that are editorial round-ups rather than a business.
_MEDIA_TITLE_RE = re.compile(
    r"\b\d+\+?\s+(best|top|fun|free|unforgettable|unmissable|exciting|coolest|great|rainy|most)\b"
    r"|\b(best|top)\s+\d+\b"
    r"|^\s*(the\s+)?(best|top)\b"
    r"|\bthings\s+to\s+do\b"
    r"|\bthis\s+weekend\b"
    r"|\bguide\s+to\b"
    r"|好去處|推介|推薦|攻略|懶人包|必去|必試|必看"
    r"|\d+\s*[個大款間項]",
    re.I,
)
SUPPRESSED_STATE = "watch:suppressed"
SUPPRESSED_MAX = 500


def looks_like_media(title: str) -> bool:
    return bool(_MEDIA_TITLE_RE.search(str(title or "")))


def suppressed_hosts(table: Any) -> dict[str, dict[str, Any]]:
    doc = board_store._get_state(table, SUPPRESSED_STATE) or {}
    hosts = doc.get("hosts")
    return dict(hosts) if isinstance(hosts, dict) else {}


def suppress_hosts(table: Any, hosts: list[str], *, name: str = "") -> dict[str, dict[str, Any]]:
    """Remember hosts the owner removed so weekly discovery does not re-add them."""
    current = suppressed_hosts(table)
    now = board_store.now_iso()
    for host in hosts:
        host = str(host or "").strip().lower()
        if host:
            current[host] = {"name": str(name or "")[:200], "at": now}
    if len(current) > SUPPRESSED_MAX:
        oldest = sorted(current.items(), key=lambda kv: str(kv[1].get("at") or ""))
        current = dict(oldest[-SUPPRESSED_MAX:])
    board_store._put_state(table, SUPPRESSED_STATE, {"hosts": current, "updatedAt": now})
    return current


def unsuppress_hosts(table: Any, hosts: list[str]) -> dict[str, dict[str, Any]]:
    current = suppressed_hosts(table)
    changed = False
    for host in hosts:
        if current.pop(str(host or "").strip().lower(), None) is not None:
            changed = True
    if changed:
        board_store._put_state(table, SUPPRESSED_STATE, {"hosts": current, "updatedAt": board_store.now_iso()})
    return current


class WatchError(ValueError):
    """Watchlist request is invalid."""


def _watch_district(raw: Any) -> str:
    """Optional 18-district label stored on the watch (blank = guess per page)."""
    text = str(raw or "").strip()
    if not text:
        return ""
    district = board_hk.canonical_district(text)
    if district == "unknown":
        raise WatchError("district must be a Hong Kong 18-district name")
    return district


def _domain(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _ignored(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in IGNORED_DOMAINS)


def _rejected_tld(host: str) -> bool:
    return any(host.endswith(tld) for tld in REJECTED_TLDS)


def _has_hk_signal(item: dict[str, Any], host: str) -> bool:
    if any(host == hint.lstrip(".") or host.endswith(hint) for hint in HK_HOST_HINTS):
        return True
    blob = " ".join(
        str(item.get(k) or "") for k in ("title", "snippet", "description", "text")
    ).lower()
    return any(hint in blob or hint in host for hint in HK_TEXT_HINTS)


def _candidate_name(item: dict[str, Any], host: str) -> str:
    title = str(item.get("title") or "").strip()
    if not title or _LISTICLE_RE.search(title) or len(title) > 80:
        return host
    return title[:200]


def _adds_this_week(existing: list[dict[str, Any]], week: str) -> int:
    n = 0
    for watch in existing:
        weeks = list(watch.get("seenWeeks") or [])
        if weeks and weeks[0] == week:
            n += 1
    return n


def _utc_now() -> datetime:
    from timeutil import utc_now

    return utc_now()


def public_watch(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in ("pk", "sk", "gsi1pk", "gsi1sk")}


def list_watchlist(table: Any) -> list[dict[str, Any]]:
    return [public_watch(w) for w in board_store.list_watches(table)]


def add_watch(table: Any, body: dict[str, Any]) -> dict[str, Any]:
    name = str(body.get("name") or "").strip()
    if not name:
        raise WatchError("name is required")
    kind = str(body.get("kind") or "competitor")
    if kind not in BOARD_STAFF_WATCH_KINDS and kind != "candidate":
        raise WatchError(f"kind must be one of {', '.join(BOARD_STAFF_WATCH_KINDS)}")
    urls = [str(u).strip() for u in (body.get("urls") or []) if str(u).strip()]
    if not urls:
        raise WatchError("urls must contain at least one URL")
    now = board_store.now_iso()
    doc = {
        "watchId": board_store.new_id(),
        "name": name[:200],
        "kind": kind,
        "urls": urls[:20],
        "district": _watch_district(body.get("district")),
        "appIds": body.get("appIds") if isinstance(body.get("appIds"), dict) else {},
        "socialHandles": [str(x) for x in (body.get("socialHandles") or []) if str(x).strip()][:12],
        "seenWeeks": list(body.get("seenWeeks") or []),
        "createdAt": now,
        "updatedAt": now,
    }
    if not doc["district"]:
        doc.pop("district")
    board_store.put_watch(table, doc)
    # An explicit add wins over an earlier removal.
    unsuppress_hosts(table, [_domain(u) for u in doc["urls"]])
    return public_watch(doc)


def update_watch(table: Any, watch_id: str, body: dict[str, Any]) -> dict[str, Any]:
    existing = board_store.get_watch(table, watch_id)
    if not existing:
        raise KeyError(watch_id)
    if "name" in body and str(body.get("name") or "").strip():
        existing["name"] = str(body["name"]).strip()[:200]
    if "kind" in body:
        kind = str(body.get("kind") or existing.get("kind") or "competitor")
        if kind not in BOARD_STAFF_WATCH_KINDS and kind != "candidate":
            raise WatchError(f"kind must be one of {', '.join(BOARD_STAFF_WATCH_KINDS)}")
        existing["kind"] = kind
    if "urls" in body and isinstance(body.get("urls"), list):
        urls = [str(u).strip() for u in body["urls"] if str(u).strip()]
        if urls:
            existing["urls"] = urls[:20]
    if "appIds" in body and isinstance(body.get("appIds"), dict):
        existing["appIds"] = body["appIds"]
    if "socialHandles" in body and isinstance(body.get("socialHandles"), list):
        existing["socialHandles"] = [str(x) for x in body["socialHandles"] if str(x).strip()][:12]
    if "district" in body:
        district = _watch_district(body.get("district"))
        if district:
            existing["district"] = district
        else:
            existing.pop("district", None)
    existing["updatedAt"] = board_store.now_iso()
    board_store.put_watch(table, existing)
    return public_watch(existing)


def remove_watch(table: Any, watch_id: str, *, suppress: bool = True) -> None:
    """Delete a watch; by default also keep discovery from re-adding its hosts."""
    existing = board_store.get_watch(table, watch_id)
    if not existing:
        raise KeyError(watch_id)
    board_store.delete_watch(table, watch_id)
    if suppress:
        hosts = [_domain(u) for u in (existing.get("urls") or [])]
        suppress_hosts(table, [h for h in hosts if h], name=str(existing.get("name") or ""))


def discover(table: Any, settings: dict[str, Any]) -> dict[str, Any]:
    import board_research

    week = _utc_now().strftime("%G-W%V")
    existing = list_watchlist(table)
    known_hosts = {_domain(u) for w in existing for u in (w.get("urls") or [])}
    suppressed = set(suppressed_hosts(table))
    already_this_week = _adds_this_week(existing, week)
    added = 0
    promoted = 0
    skipped_media = 0
    skipped_suppressed = 0
    ctx = type("Ctx", (), {"table": table, "settings": settings})()
    for query in TARGET_QUERIES:
        try:
            payload = board_research.op_search(ctx, {"query": query, "limit": 8})
        except Exception as exc:
            _log_event("warning", tag="board_watch_discover_search_failed", error=str(exc)[:200], query=query[:80])
            continue
        for item in payload.get("results") or []:
            url = str(item.get("url") or "")
            host = _domain(url)
            if not host or _ignored(host) or _rejected_tld(host):
                continue
            if host in suppressed or any(host.endswith("." + s) for s in suppressed):
                skipped_suppressed += 1
                continue
            if not _has_hk_signal(item if isinstance(item, dict) else {}, host):
                continue
            if host not in known_hosts and looks_like_media(str((item or {}).get("title") or "")):
                skipped_media += 1
                continue
            if added >= max(0, MAX_ADDS_PER_WEEK - already_this_week):
                continue
            homepage = f"https://{host}/"
            match = next((w for w in existing if host in {_domain(u) for u in (w.get("urls") or [])}), None)
            if match:
                weeks = list(match.get("seenWeeks") or [])
                if week not in weeks:
                    weeks.append(week)
                    match["seenWeeks"] = weeks[-8:]
                    if match.get("kind") == "candidate" and len(weeks) >= 2:
                        match["kind"] = "competitor"
                        promoted += 1
                    match["updatedAt"] = board_store.now_iso()
                    board_store.put_watch(table, match)
                continue
            if host in known_hosts:
                continue
            doc = add_watch(
                table,
                {
                    "name": _candidate_name(item if isinstance(item, dict) else {}, host),
                    "kind": "candidate",
                    "urls": [homepage],
                    "seenWeeks": [week],
                },
            )
            existing.append(doc)
            known_hosts.add(host)
            added += 1
    cutoff = (_utc_now() - timedelta(days=60)).strftime("%Y-%m-%d")
    expired = 0
    for watch in list_watchlist(table):
        if watch.get("kind") != "candidate":
            continue
        updated = str(watch.get("updatedAt") or watch.get("createdAt") or "")
        if updated and updated[:10] < cutoff:
            board_store.delete_watch(table, str(watch["watchId"]))
            expired += 1
    return {
        "ok": True,
        "added": added,
        "promoted": promoted,
        "expired": expired,
        "skippedMedia": skipped_media,
        "skippedSuppressed": skipped_suppressed,
        "week": week,
    }
