"""Hong Kong open-data loaders for market intelligence.

Verified 2026-09-10 (do not silently swap URLs):

FEHD licensed restaurants
  Portal: https://data.gov.hk/en-data/dataset/hk-fehd-fehdlmis-restaurant-licences
  Format at build time: **XML** (not CSV). English and Traditional Chinese
  files are published separately and refresh daily ~09:00.
  English XML: http://www.fehd.gov.hk/english/licensing/license/text/LP_Restaurants_EN.XML
  Chinese XML: http://www.fehd.gov.hk/tc_chi/licensing/license/text/LP_Restaurants_TC.XML
  Tags used: TYPE / TYPE_OF_LICENCE, DIST / DISTRICT, ADR / ADDRESS,
  EN_NAME / NAME, TC_NAME / CNAME. CSV fixtures use
  name_en,name_zh,address_en,address_zh,district.

EDB school location and information
  Portal: https://data.gov.hk/en-data/dataset/hk-edb-schinfo-school-location-and-information
  Format: CSV (English + Traditional Chinese columns in one file).
  Columns used: ENGLISH NAME, 中文名稱, ENGLISH ADDRESS, 中文地址,
  DISTRICT / 分區, SCHOOL LEVEL / 學校類型.
  Spec PDF: https://www.edb.gov.hk/attachment/en/student-parents/sch-info/datagovhk/DataSpec_School_Location_and_Information_en.pdf

LCSD facility JSON (data.gov.hk / lcsd.gov.hk datagovhk):
  Parks / leisure venues: https://www.lcsd.gov.hk/datagovhk/facility/facility-lwv.json
  Children's playgrounds: https://www.lcsd.gov.hk/datagovhk/facility/facility-cpg.json
  Sports centres:         https://www.lcsd.gov.hk/datagovhk/facility/facility-sc.json
  Swimming pools:         https://www.lcsd.gov.hk/datagovhk/facility/facility-sp.json
  Public libraries:       https://www.lcsd.gov.hk/datagovhk/facility/facility-lib.json
  Children's play rooms:  https://www.lcsd.gov.hk/datagovhk/facility/facility-cpr.json
  Field names vary (Name_en / name_en / ENGLISH NAME). Parsers are tolerant.

SWD child care centres
  Portal: https://data.gov.hk/en-data/dataset/hk-swd-swdfcsd-list-of-child-care-centres
  CSV columns used: centre / name, address, district, telephone / phone.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from defusedxml import ElementTree as ET

import board_hk
import board_store
from http_common import _log_event

FEHD_EN_URL = "http://www.fehd.gov.hk/english/licensing/license/text/LP_Restaurants_EN.XML"
FEHD_ZH_URL = "http://www.fehd.gov.hk/tc_chi/licensing/license/text/LP_Restaurants_TC.XML"
EDB_CSV_URL = "https://www.edb.gov.hk/attachment/en/student-parents/sch-info/sch-search/sch-location-info/SCH_LOC_EDB.csv"
SWD_CCC_URL = "https://www.swd.gov.hk/storage/asset/section/2913/en/List_of_Child_Care_Centres.csv"
ROW_CAP = 8000
CACHE_TTL = 7 * 86400
LCSD_FACILITY_FEEDS: tuple[tuple[str, str, str], ...] = (
    ("lcsd_park", "https://www.lcsd.gov.hk/datagovhk/facility/facility-lwv.json", "Outdoor activity"),
    ("lcsd_playground", "https://www.lcsd.gov.hk/datagovhk/facility/facility-cpg.json", "Outdoor activity"),
    ("lcsd_sports_centre", "https://www.lcsd.gov.hk/datagovhk/facility/facility-sc.json", "Sport"),
    ("lcsd_swimming_pool", "https://www.lcsd.gov.hk/datagovhk/facility/facility-sp.json", "Sport"),
    ("lcsd_library", "https://www.lcsd.gov.hk/datagovhk/facility/facility-lib.json", "Indoor fun"),
    ("lcsd_playroom", "https://www.lcsd.gov.hk/datagovhk/facility/facility-cpr.json", "Indoor fun"),
)
EDB_KG_MARKERS = ("kindergarten", "幼稚園", "kg", "child care", "幼兒", "nursery")
SWD_NAME_KEYS = ("name_en", "ENGLISH NAME", "Centre Name (English)", "Centre Name", "NAME", "name")
SWD_ZH_KEYS = ("name_zh", "中文名稱", "Centre Name (Chinese)", "中文名稱")
SWD_ADDR_KEYS = ("address_en", "ENGLISH ADDRESS", "Address", "ADDRESS", "address")
SWD_ADDR_ZH_KEYS = ("address_zh", "中文地址")
SWD_DIST_KEYS = ("district", "DISTRICT", "分區", "District")
SWD_PHONE_KEYS = ("phone", "Telephone", "Tel", "電話")
LCSD_NAME_KEYS = ("Name_en", "name_en", "ENGLISH NAME", "Name", "name")
LCSD_ZH_KEYS = ("Name_tc", "Name_zh", "name_zh", "中文名稱", "Name_chi")
LCSD_ADDR_KEYS = ("Address_en", "address_en", "ENGLISH ADDRESS", "Address", "address")
LCSD_ADDR_ZH_KEYS = ("Address_tc", "address_zh", "中文地址")
LCSD_DIST_KEYS = ("District_en", "district", "DISTRICT", "District", "分區")
LCSD_PHONE_KEYS = ("Phone", "phone", "Telephone", "Tel")
LCSD_HOURS_KEYS = ("Opening_hours_en", "OpeningHours", "opening_hours", "Opening_hours")
LCSD_LAT_KEYS = ("Latitude", "latitude", "lat", "LAT")
LCSD_LNG_KEYS = ("Longitude", "longitude", "lng", "LONG")
LCSD_URL_KEYS = ("Website", "website", "URL", "url")

FEHD_NAME_KEYS = ("name_en", "EN_NAME", "NAME", "ENGLISH NAME", "SS")
FEHD_ZH_KEYS = ("name_zh", "TC_NAME", "CNAME", "中文名稱")
FEHD_ADDR_KEYS = ("address_en", "ADR", "ADDRESS", "ENGLISH ADDRESS")
FEHD_ADDR_ZH_KEYS = ("address_zh", "中文地址")
FEHD_DIST_KEYS = ("district", "DIST", "DISTRICT", "分區")


def _text(node: ET.Element | None) -> str:
    if node is None or node.text is None:
        return ""
    return " ".join(node.text.split())


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    lower = {str(k).strip().lower(): v for k, v in row.items()}
    for key in keys:
        value = row.get(key)
        if value:
            return str(value).strip()
        value = lower.get(key.lower())
        if value:
            return str(value).strip()
    return ""


def _map_row(row: dict[str, Any]) -> dict[str, Any]:
    address = _first(row, FEHD_ADDR_KEYS) or _first(row, FEHD_ADDR_ZH_KEYS)
    district = _first(row, FEHD_DIST_KEYS) or board_hk.district_from_address(address)
    return {
        "nameEn": _first(row, FEHD_NAME_KEYS),
        "nameZh": _first(row, FEHD_ZH_KEYS),
        "addressEn": _first(row, FEHD_ADDR_KEYS),
        "addressZh": _first(row, FEHD_ADDR_ZH_KEYS),
        "district": district,
    }


def parse_fehd_xml(body: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        _log_event("warning", tag="board_opendata_schema_changed", dataset="fehd", reason="xml parse")
        return []
    rows: list[dict[str, Any]] = []
    for node in root.iter():
        tag = (node.tag or "").split("}")[-1].upper()
        if tag not in {"LP", "LICENCE", "LICENSE", "PREMISES", "RECORD", "ROW"}:
            continue
        raw = {(child.tag or "").split("}")[-1]: _text(child) for child in list(node)}
        if not raw:
            continue
        mapped = _map_row(raw)
        if mapped["nameEn"] or mapped["nameZh"]:
            rows.append(mapped)
        if len(rows) >= ROW_CAP:
            break
    if not rows:
        _log_event("warning", tag="board_opendata_schema_changed", dataset="fehd", reason="no licence rows")
    return rows


def parse_fehd_csv(body: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(body))
    if not reader.fieldnames:
        _log_event("warning", tag="board_opendata_schema_changed", dataset="fehd", reason="empty csv")
        return []
    rows: list[dict[str, Any]] = []
    for raw in reader:
        mapped = _map_row({k: (v or "") for k, v in raw.items()})
        if mapped["nameEn"] or mapped["nameZh"]:
            rows.append(mapped)
        if len(rows) >= ROW_CAP:
            break
    if not rows:
        _log_event("warning", tag="board_opendata_schema_changed", dataset="fehd", reason="required columns missing")
    return rows


def parse_edb_csv(body: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(body))
    rows: list[dict[str, Any]] = []
    for raw in reader:
        address = _first(raw, ("ENGLISH ADDRESS", "中文地址"))
        mapped = {
            "nameEn": _first(raw, ("ENGLISH NAME",)),
            "nameZh": _first(raw, ("中文名稱",)),
            "addressEn": _first(raw, ("ENGLISH ADDRESS",)),
            "addressZh": _first(raw, ("中文地址",)),
            "district": _first(raw, ("DISTRICT", "分區")) or board_hk.district_from_address(address),
            "level": _first(raw, ("SCHOOL LEVEL", "學校類型")),
        }
        if mapped["nameEn"] or mapped["nameZh"]:
            rows.append(mapped)
        if len(rows) >= ROW_CAP:
            break
    if not rows:
        _log_event("warning", tag="board_opendata_schema_changed", dataset="edb", reason="required columns missing")
    return rows


def _cached(table: Any, name: str) -> dict[str, Any] | None:
    hit = board_store.get_cache(table, name)
    if hit and isinstance(hit.get("payload"), dict):
        return hit["payload"]
    return None


def _store(table: Any, name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {"rows": rows[:ROW_CAP], "fetchedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    board_store.put_cache(table, name, payload, ttl_seconds=CACHE_TTL)
    return payload


def _download(url: str) -> str:
    import board_crawl

    result = board_crawl.fetch(url, max_bytes=8_000_000, timeout=20)
    if result.status >= 400:
        raise OSError(f"opendata {url} status {result.status}")
    return result.text


def fehd_licensed_premises(table: Any | None = None) -> dict[str, Any]:
    table = table if table is not None else board_store.records_table()
    cached = _cached(table, "opendata:fehd")
    try:
        en = _download(FEHD_EN_URL)
        rows = parse_fehd_xml(en) if "<" in en[:200] else parse_fehd_csv(en)
        return _store(table, "opendata:fehd", rows)
    except Exception as exc:
        _log_event("warning", tag="board_opendata_fetch_failed", dataset="fehd", error=str(exc)[:200])
        if cached:
            return cached
        return {"rows": [], "fetchedAt": ""}


def edb_schools(table: Any | None = None) -> dict[str, Any]:
    table = table if table is not None else board_store.records_table()
    cached = _cached(table, "opendata:edb")
    try:
        body = _download(EDB_CSV_URL)
        return _store(table, "opendata:edb", parse_edb_csv(body))
    except Exception as exc:
        _log_event("warning", tag="board_opendata_fetch_failed", dataset="edb", error=str(exc)[:200])
        if cached:
            return cached
        return {"rows": [], "fetchedAt": ""}


def _as_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _rows_from_json(body: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [r for r in parsed if isinstance(r, dict)]
    if isinstance(parsed, dict):
        for key in ("features", "records", "data", "rows", "facilities"):
            raw = parsed.get(key)
            if isinstance(raw, list):
                out: list[dict[str, Any]] = []
                for item in raw:
                    if isinstance(item, dict) and isinstance(item.get("properties"), dict):
                        out.append({**item["properties"], **{k: item.get(k) for k in ("geometry",) if k in item}})
                    elif isinstance(item, dict):
                        out.append(item)
                return out
    return []


def parse_lcsd_json(body: str, *, facility_kind: str, category: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in _rows_from_json(body):
        address = _first(raw, LCSD_ADDR_KEYS) or _first(raw, LCSD_ADDR_ZH_KEYS)
        mapped = {
            "nameEn": _first(raw, LCSD_NAME_KEYS),
            "nameZh": _first(raw, LCSD_ZH_KEYS),
            "addressEn": _first(raw, LCSD_ADDR_KEYS),
            "addressZh": _first(raw, LCSD_ADDR_ZH_KEYS),
            "district": _first(raw, LCSD_DIST_KEYS) or board_hk.district_from_address(address),
            "phone": _first(raw, LCSD_PHONE_KEYS),
            "openingHours": _first(raw, LCSD_HOURS_KEYS),
            "lat": _as_float(_first(raw, LCSD_LAT_KEYS) or raw.get("Latitude")),
            "lng": _as_float(_first(raw, LCSD_LNG_KEYS) or raw.get("Longitude")),
            "officialUrl": _first(raw, LCSD_URL_KEYS),
            "facilityKind": facility_kind,
            "category": category,
            "source": "lcsd",
            "sourceId": str(raw.get("OBJECTID") or raw.get("id") or raw.get("ID") or "")[:80],
        }
        if mapped["nameEn"] or mapped["nameZh"]:
            rows.append(mapped)
        if len(rows) >= ROW_CAP:
            break
    return rows


def parse_swd_csv(body: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(body))
    rows: list[dict[str, Any]] = []
    for raw in reader:
        address = _first(raw, SWD_ADDR_KEYS) or _first(raw, SWD_ADDR_ZH_KEYS)
        mapped = {
            "nameEn": _first(raw, SWD_NAME_KEYS),
            "nameZh": _first(raw, SWD_ZH_KEYS),
            "addressEn": _first(raw, SWD_ADDR_KEYS),
            "addressZh": _first(raw, SWD_ADDR_ZH_KEYS),
            "district": _first(raw, SWD_DIST_KEYS) or board_hk.district_from_address(address),
            "phone": _first(raw, SWD_PHONE_KEYS),
            "facilityKind": "swd_child_care",
            "category": "Class",
            "source": "swd",
            "sourceId": "",
        }
        if mapped["nameEn"] or mapped["nameZh"]:
            mapped["sourceId"] = f"{mapped['nameEn']}|{mapped['nameZh']}"[:80]
            rows.append(mapped)
        if len(rows) >= ROW_CAP:
            break
    if not rows:
        _log_event("warning", tag="board_opendata_schema_changed", dataset="swd", reason="required columns missing")
    return rows


def is_kindergarten(row: dict[str, Any]) -> bool:
    level = str(row.get("level") or "").lower()
    return any(marker in level for marker in EDB_KG_MARKERS)


def edb_kindergartens(table: Any | None = None) -> dict[str, Any]:
    payload = edb_schools(table)
    rows = [r for r in (payload.get("rows") or []) if is_kindergarten(r)]
    for row in rows:
        row["facilityKind"] = "edb_kindergarten"
        row["category"] = "Class"
        row["source"] = "edb"
        row["sourceId"] = f"{row.get('nameEn') or ''}|{row.get('nameZh') or ''}"[:80]
    return {**payload, "rows": rows[:ROW_CAP]}


def lcsd_facilities(table: Any | None = None) -> dict[str, Any]:
    table = table if table is not None else board_store.records_table()
    cached = _cached(table, "opendata:lcsd")
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        for kind, url, category in LCSD_FACILITY_FEEDS:
            try:
                body = _download(url)
            except Exception as exc:
                errors.append(f"{kind}:{exc}"[:120])
                continue
            parsed = parse_lcsd_json(body, facility_kind=kind, category=category)
            if not parsed:
                _log_event("warning", tag="board_opendata_schema_changed", dataset=kind, reason="no facility rows")
            rows.extend(parsed)
        if rows:
            return _store(table, "opendata:lcsd", rows)
    except Exception as exc:
        _log_event("warning", tag="board_opendata_fetch_failed", dataset="lcsd", error=str(exc)[:200])
    if cached:
        return cached
    if errors:
        _log_event("warning", tag="board_opendata_fetch_failed", dataset="lcsd", error="; ".join(errors)[:200])
    return {"rows": [], "fetchedAt": ""}


def swd_child_care_centres(table: Any | None = None) -> dict[str, Any]:
    table = table if table is not None else board_store.records_table()
    cached = _cached(table, "opendata:swd")
    try:
        body = _download(SWD_CCC_URL)
        rows = parse_swd_csv(body) if "," in body[:400] else parse_lcsd_json(body, facility_kind="swd_child_care", category="Class")
        for row in rows:
            row.setdefault("facilityKind", "swd_child_care")
            row.setdefault("category", "Class")
            row.setdefault("source", "swd")
        return _store(table, "opendata:swd", rows)
    except Exception as exc:
        _log_event("warning", tag="board_opendata_fetch_failed", dataset="swd", error=str(exc)[:200])
        if cached:
            return cached
        return {"rows": [], "fetchedAt": ""}


def lcsd_programmes(table: Any | None = None) -> dict[str, Any]:
    """Alias for outreach `kind=lcsd`: facility rows, not programme listings."""
    return lcsd_facilities(table)
