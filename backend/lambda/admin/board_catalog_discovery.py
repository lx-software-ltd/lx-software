"""Always-on catalog discovery: Places sweep, open-data refresh, competitor indexes."""

from __future__ import annotations

import html
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import board_catalog_bulk
import board_catalog_candidates
import board_hk
import board_opendata
import board_places
import board_staff
import board_store
from contract_constants import (
    BOARD_CATALOG_DISCOVERY_DISTRICTS_PER_DAY,
    BOARD_CATALOG_DISTRICTS,
    BOARD_KEY,
)
from http_common import _log_event

CURSOR_CACHE = "catalog:discovery:cursor"
NAME_LINE = re.compile(r"^(?:[-*•]\s*)?([A-Z][\w'&.\-]{2,}(?:\s+[A-Za-z0-9'&.\-]{2,}){0,8})\s*$")
ANCHOR = re.compile(r"<a\b[^>]*>([^<]{4,80})</a>", re.I)
HEADING = re.compile(r"<h[1-3]\b[^>]*>([^<]{4,80})</h[1-3]>", re.I)
_CHROME_TAGS = frozenset({"nav", "header", "footer", "script", "style", "noscript"})
PAGE_TITLE_NAME = re.compile(
    r"^(kids['’]? activities in |browse |all activities\b|activities in )",
    re.I,
)
NAV_NAME = re.compile(
    r"^(first|last|next|previous|prev|more|show\s+\d+|view all|see all|load more|page\s+\d+)$",
    re.I,
)
NAV_CHARS = re.compile(r"[«»‹›]")

# Site chrome extracted as if it were a listing (Classbee nav, Whizpa directory filters).
CHROME_NAMES = frozenset(
    board_catalog_candidates.norm_name(label)
    for label in (
        "About",
        "All Classes",
        "Back",
        "Browse",
        "Browse Activities",
        "Browse All Activities",
        "Career",
        "Category",
        "Collections",
        "Columnists",
        "Coming Up",
        "Community Culture",
        "Contact",
        "Contact Us",
        "Cookie Policy",
        "Cookies",
        "Education organisations",
        "English",
        "Events",
        "Experiences",
        "Facebook",
        "For providers",
        "Get listed",
        "Guides",
        "Health Psychology",
        "Home",
        "Instagram",
        "Learn more",
        "LinkedIn",
        "Local School",
        "Local School 2",
        "Login",
        "Log in",
        "Menu",
        "More",
        "News",
        "Next",
        "Opinions",
        "Parenthood",
        "Previous",
        "Privacy",
        "Privacy Disclaimer",
        "Privacy Policy",
        "Read more",
        "Search",
        "See more",
        "Show more",
        "Sign in",
        "Sign up",
        "Skip to main content",
        "Special Education",
        "STEAM",
        "Studios",
        "Subscribe",
        "Terms",
        "Terms of Use",
        "Try First",
        "Twitter",
        "Unsubscribe",
        "View all",
        "First",
        "Last",
        "Show 20",
        "Load more",
        "See all",
        "YouTube",
        "中文",
        "繁體",
        "简体",
        "移至主內容",
        "最新資訊",
        "親子教養",
        "健康與心理",
        "STEAM教育",
        "本地學校",
        "海外升學",
        "職業規劃",
        "社會與文化",
        "特殊教育",
        "家庭活動",
        "專欄分享",
        "專欄作家",
        "教育機構",
        "聯絡我們",
        "官立中學",
        "直資中學",
        "國際學校",
    )
)


def _district_names() -> list[str]:
    names: list[str] = []
    for row in BOARD_CATALOG_DISTRICTS:
        if isinstance(row, dict) and row.get("name"):
            names.append(str(row["name"]))
    return names or list(board_hk.DISTRICT_CENTERS.keys())


def _cursor(table: Any) -> dict[str, Any]:
    hit = board_store.get_cache(table, CURSOR_CACHE)
    payload = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else {}
    return {
        "offset": int(payload.get("offset") or 0),
        "lastOpenDataAt": str(payload.get("lastOpenDataAt") or ""),
        "lastPlacesAt": str(payload.get("lastPlacesAt") or ""),
    }


def _save_cursor(table: Any, doc: dict[str, Any]) -> None:
    board_store.put_cache(table, CURSOR_CACHE, doc, ttl_seconds=40 * 86400)


def rotate_districts(table: Any, n: int | None = None) -> list[str]:
    names = _district_names()
    if not names:
        return []
    take = max(1, int(n or BOARD_CATALOG_DISCOVERY_DISTRICTS_PER_DAY))
    cur = _cursor(table)
    start = int(cur.get("offset") or 0) % len(names)
    chosen = [names[(start + i) % len(names)] for i in range(take)]
    cur["offset"] = (start + take) % len(names)
    _save_cursor(table, cur)
    return chosen


def discover_places(table: Any, settings: dict[str, Any], districts: list[str] | None = None) -> dict[str, Any]:
    chosen = districts or rotate_districts(table)
    upserted = 0
    errors: list[str] = []
    for name in chosen:
        try:
            places = board_places.discover(table, name, settings=settings, pages=1, limit=10)
        except board_places.PlacesError as exc:
            errors.append(f"{name}:{exc}"[:160])
            continue
        now = board_store.now_iso()
        for place in places:
            if str(place.get("businessStatus") or "") == "CLOSED_PERMANENTLY":
                cand = {
                    "source": "places",
                    "placeId": place.get("placeId"),
                    "sourceId": place.get("placeId"),
                    "nameEn": place.get("name"),
                    "addressEn": place.get("address"),
                    "district": name,
                }
                if not board_catalog_candidates.is_duplicate(table, cand):
                    doc = board_catalog_candidates.upsert_candidate(table, cand)
                    cid = str(doc.get("candidateId") or "")
                    if cid:
                        board_catalog_candidates.set_status(table, cid, "closed")
                continue
            row = {
                "source": "places",
                "placeId": place.get("placeId"),
                "sourceId": place.get("placeId"),
                "nameEn": place.get("name"),
                "addressEn": place.get("address"),
                "district": name or board_hk.district_from_address(str(place.get("address") or "")),
                "phone": place.get("phone") or "",
                "officialUrl": place.get("website") or "",
                "facilityKind": place.get("facilityKind") or "places_park",
                "types": place.get("types") or [],
                "rating": place.get("rating"),
                "userRatingCount": place.get("userRatingCount"),
                "placesFetchedAt": now,
            }
            hours = place.get("regularOpeningHours") or {}
            if isinstance(hours, dict) and hours.get("weekdayDescriptions"):
                row["openingHours"] = "; ".join(str(x) for x in hours.get("weekdayDescriptions") or [])[:200]
            doc = board_catalog_candidates.upsert_candidate(table, row)
            if not doc.get("skipped"):
                upserted += 1
    cur = _cursor(table)
    cur["lastPlacesAt"] = board_store.now_iso()
    _save_cursor(table, cur)
    return {"districts": chosen, "upserted": upserted, "errors": errors}


def _record_opendata_gap(table: Any, source: str, fetched_at: str, *, row_count: int = 0, reason: str = "") -> None:
    import board_duties

    gap_id = f"opendata-{source}"
    if fetched_at and int(row_count or 0) > 0:
        board_duties.clear_config_gap(table, gap_id)
        return
    board_duties.note_config_gap(
        table,
        gap_id=gap_id,
        reason=reason or f"{source} open-data fetch returned no rows",
    )


def source_needs_refresh(table: Any, source: str) -> bool:
    """True when the open-data cache pointer is missing, empty, or unfetched.

    Reads the Dynamo pointer only — do not pull the S3 gzip just to decide.
    """
    if source not in board_catalog_bulk.OPEN_DATA_SOURCES:
        return False
    hit = board_store.get_cache(table, f"opendata:{source}")
    payload = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else None
    if not payload:
        return True
    if not str(payload.get("fetchedAt") or ""):
        return True
    if "rowCount" not in payload:
        # Legacy pointer written before rowCount: fetchedAt means already fetched.
        return False
    try:
        count = int(payload.get("rowCount") or 0)
    except (TypeError, ValueError):
        count = 0
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    return count <= 0 and not rows


def refresh_open_data(table: Any, *, force: bool = False) -> dict[str, Any]:
    notes: dict[str, Any] = {}
    for source in board_catalog_bulk.OPEN_DATA_SOURCES:
        try:
            reload = force or source_needs_refresh(table, source)
            rows = board_catalog_bulk.load_source_rows(table, source, force=reload)
            cached = board_opendata._cached(table, f"opendata:{source}")  # noqa: SLF001
            fetched_at = str((cached or {}).get("fetchedAt") or "")
            if rows:
                fetched_at = fetched_at or board_store.now_iso()
            _record_opendata_gap(table, source, fetched_at, row_count=len(rows))
            if board_catalog_bulk.needs_chunked_ingest(len(rows)):
                queued = board_catalog_bulk.queue_action(
                    table, "ingest", source, requested_by="discovery", force=False
                )
                notes[source] = {"fetched": len(rows), "fetchedAt": fetched_at, **queued}
            else:
                notes[source] = board_catalog_bulk.ingest_source(table, source, force=False)
        except Exception as exc:
            notes[source] = {"error": str(exc)[:200]}
            _record_opendata_gap(table, source, "", row_count=0, reason=str(exc)[:200])
    cur = _cursor(table)
    cur["lastOpenDataAt"] = board_store.now_iso()
    _save_cursor(table, cur)
    return notes


class _ChromeStripper(HTMLParser):
    """Drop nav/header/footer/script/style so listing regexes never see chrome."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in _CHROME_TAGS:
            self._depth += 1
            return
        if self._depth:
            return
        self.parts.append(self.get_starttag_text() or f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in _CHROME_TAGS:
            self._depth = max(0, self._depth - 1)
            return
        if self._depth:
            return
        self.parts.append(f"</{tag}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in _CHROME_TAGS or self._depth:
            return
        self.parts.append(self.get_starttag_text() or f"<{tag} />")

    def handle_data(self, data: str) -> None:
        if not self._depth:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._depth:
            self.parts.append(f"&#{name};")


def _strip_chrome_html(blob: str) -> str:
    parser = _ChromeStripper()
    try:
        parser.feed(blob or "")
        parser.close()
    except Exception:
        return blob or ""
    return "".join(parser.parts)


def _clean_listing_name(raw: str) -> str:
    name = html.unescape(" ".join(str(raw).split()))
    return name.strip(" \t\n\r-–—·|:;")


def _is_chrome_name(name: str) -> bool:
    key = board_catalog_candidates.norm_name(name)
    if not key or key in CHROME_NAMES:
        return True
    if PAGE_TITLE_NAME.search(name):
        return True
    if NAV_NAME.match(name.strip()):
        return True
    if NAV_CHARS.search(name):
        return True
    if "http" in name.lower():
        return True
    first = name[0]
    if not (first.isalpha() or "\u4e00" <= first <= "\u9fff"):
        return True
    return False


def extract_listing_names(html_or_text: str) -> list[str]:
    """Names only — never copy competitor descriptions or photos."""
    names: list[str] = []
    seen: set[str] = set()
    blob = _strip_chrome_html(html_or_text or "")
    for pattern in (ANCHOR, HEADING):
        for match in pattern.findall(blob):
            name = _clean_listing_name(match)
            key = board_catalog_candidates.norm_name(name)
            if 3 < len(name) < 80 and key and key not in seen and not _is_chrome_name(name):
                seen.add(key)
                names.append(name)
    for line in blob.splitlines():
        match = NAME_LINE.match(line.strip())
        if not match:
            continue
        name = _clean_listing_name(match.group(1))
        key = board_catalog_candidates.norm_name(name)
        if key and key not in seen and not _is_chrome_name(name):
            seen.add(key)
            names.append(name)
        if len(names) >= 80:
            break
    return names[:80]


def resolve_listings_district(watch: dict[str, Any], url: str, _text: str = "") -> str:
    """Prefer an area slug on the page URL, then the watch district.

    City-wide index HTML is not used: the first district token on the page is
    usually a single card or footer, not the listing set.
    """
    from_url = board_hk.district_from_url(url)
    if from_url != "unknown":
        return from_url
    watch_district = board_hk.canonical_district(str(watch.get("district") or ""))
    if watch_district != "unknown":
        return watch_district
    return "unknown"


def ingest_listings_page(table: Any, watch: dict[str, Any], text: str, url: str) -> int:
    host = (urlparse(url).netloc or "").lower()
    names = extract_listing_names(text)
    page_district = resolve_listings_district(watch, url, text)
    n = 0
    for name in names:
        board_catalog_candidates.upsert_candidate(
            table,
            {
                "source": "competitor",
                "sourceId": f"{host}:{board_catalog_candidates.norm_name(name)}"[:80],
                "nameEn": name,
                "district": page_district,
                "officialUrl": "",
                "facilityKind": "competitor",
            },
        )
        n += 1
    _log_event(
        "info",
        tag="board_catalog_listings_index",
        host=host[:80],
        names=n,
        district=page_district,
        watch=str(watch.get("watchId") or ""),
    )
    return n


def run_discovery(table: Any, settings: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    if not board_staff.enabled(settings):
        return {"ok": True, "skipped": "disabled"}
    board_catalog_candidates.seed_listing_mirror(table)
    when = now or board_hk.now_hkt()
    places = discover_places(table, settings)
    open_data: dict[str, Any] = {}
    needs_open = any(
        source_needs_refresh(table, source) for source in board_catalog_bulk.OPEN_DATA_SOURCES
    )
    if when.weekday() == 0 or needs_open or not _cursor(table).get("lastOpenDataAt"):
        open_data = refresh_open_data(table, force=when.weekday() == 0)
    utc = when.astimezone() if when.tzinfo else when
    expired = board_catalog_candidates.expire_stale_places(table, now=utc)
    expired_comp = board_catalog_candidates.expire_stale_competitor(table, now=utc)
    enriched = board_catalog_candidates.enrich_with_places(table, settings)
    return {
        "ok": True,
        "places": places,
        "openData": open_data,
        "placesExpired": expired,
        "competitorsExpired": expired_comp,
        "competitorsEnriched": enriched,
    }


def handle_tick(event: dict[str, Any]) -> dict[str, Any]:
    if not board_store.event_targets_this_board(event):
        return {"ok": True, "skipped": "other-board"}
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    return run_discovery(table, settings)
