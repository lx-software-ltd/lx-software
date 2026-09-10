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

LCSD programmes stay an empty stub (`lcsd_programmes`). No stable public
CSV/XML was verified at WP6; `outreach_open_data(kind=lcsd)` returns the
last cache or an empty list.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any

from defusedxml import ElementTree as ET

import board_hk
import board_store
from http_common import _log_event

FEHD_EN_URL = "http://www.fehd.gov.hk/english/licensing/license/text/LP_Restaurants_EN.XML"
FEHD_ZH_URL = "http://www.fehd.gov.hk/tc_chi/licensing/license/text/LP_Restaurants_TC.XML"
EDB_CSV_URL = "https://www.edb.gov.hk/attachment/en/student-parents/sch-info/sch-search/sch-location-info/SCH_LOC_EDB.csv"
ROW_CAP = 5000
CACHE_TTL = 7 * 86400

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


def lcsd_programmes(table: Any | None = None) -> dict[str, Any]:
    """WP6 consumes this. Empty until that package lands."""
    table = table if table is not None else board_store.records_table()
    cached = _cached(table, "opendata:lcsd")
    return cached or {"rows": [], "fetchedAt": ""}
