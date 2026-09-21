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

LCSD facilities (verified 2026-09-18 — facility-lwv / facility-cpg /
facility-lib 404; do not revive those slugs):
  Inclusive playgrounds: https://www.lcsd.gov.hk/datagovhk/facility/facility-pefac.json
  Sports centres:        https://www.lcsd.gov.hk/datagovhk/facility/facility-sc.json
  Swimming pools:        https://www.lcsd.gov.hk/datagovhk/facility/facility-sp.json
  Children's play rooms: https://www.lcsd.gov.hk/datagovhk/facility/facility-cpr.json
  Parks / zoos / gardens: CSDI FeatureServer lcsd_rcd_1629267205215_19292
  Libraries:              CSDI FeatureServer lcsd_rcd_1629267205214_44807
  Live LCSD JSON uses Name_cn / Address_cn (not Name_tc). Hours are HTML.
  Play-room rows reuse the host sports-centre name — qualify them.

SWD aided standalone child-care centres
  Portal: https://data.gov.hk/en-data/dataset/hk-swd-fcw-list-ccc
  Current: CSDI FeatureServer swd_rcd_1629267205216_48300
  Fallback CSV (UTF-16 TSV, last file 2023-09-12):
  https://www.swd.gov.hk/datagovhk/fcw/list-ccc.csv
"""

from __future__ import annotations

import csv
import gzip
import html
import io
import json
import re
import urllib.request
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from defusedxml import ElementTree as ET

import board_hk
import board_store
from contract_constants import BOARD_KEY
from http_common import _log_event

FEHD_EN_URL = "http://www.fehd.gov.hk/english/licensing/license/text/LP_Restaurants_EN.XML"
FEHD_ZH_URL = "http://www.fehd.gov.hk/tc_chi/licensing/license/text/LP_Restaurants_TC.XML"
EDB_CSV_URL = "https://www.edb.gov.hk/attachment/en/student-parents/sch-info/sch-search/sch-location-info/SCH_LOC_EDB.csv"
SWD_CCC_URL = "https://www.swd.gov.hk/datagovhk/fcw/list-ccc.csv"
ROW_CAP = 8000
CACHE_TTL = 7 * 86400
CSDI_FEATURE_SERVER = "https://portal.csdi.gov.hk/server/rest/services/common/{dataset_id}/FeatureServer/0/query"
LCSD_JSON_FEEDS: tuple[tuple[str, str, str], ...] = (
    ("lcsd_playground", "https://www.lcsd.gov.hk/datagovhk/facility/facility-pefac.json", "Outdoor activity"),
    ("lcsd_sports_centre", "https://www.lcsd.gov.hk/datagovhk/facility/facility-sc.json", "Sport"),
    ("lcsd_swimming_pool", "https://www.lcsd.gov.hk/datagovhk/facility/facility-sp.json", "Sport"),
    ("lcsd_playroom", "https://www.lcsd.gov.hk/datagovhk/facility/facility-cpr.json", "Indoor fun"),
)
LCSD_CSDI_FEEDS: tuple[tuple[str, str, str], ...] = (
    ("lcsd_park", "lcsd_rcd_1629267205215_19292", "Outdoor activity"),
    ("lcsd_library", "lcsd_rcd_1629267205214_44807", "Indoor fun"),
)
SWD_CSDI_DATASET = "swd_rcd_1629267205216_48300"
EDB_KG_MARKERS = ("kindergarten", "幼稚園", "kg", "child care", "幼兒", "nursery")
SWD_NAME_KEYS = (
    "name_en",
    "ENGLISH NAME",
    "Centre Name (English)",
    "Name of Centre",
    "NameEN",
    "Centre Name",
    "NAME",
    "name",
)
SWD_ZH_KEYS = ("name_zh", "中文名稱", "Centre Name (Chinese)", "NameTC", "中心名稱")
SWD_ADDR_KEYS = ("address_en", "ENGLISH ADDRESS", "AddressEN", "Address", "ADDRESS", "address")
SWD_ADDR_ZH_KEYS = ("address_zh", "AddressTC", "地址", "中文地址")
SWD_DIST_KEYS = ("district", "DISTRICT", "DistrictEN", "分區", "District", "區域")
SWD_PHONE_KEYS = ("phone", "Telephone", "Tel. No.", "TelephoneEN", "Tel", "電話")
LCSD_NAME_KEYS = ("Name_en", "NameEN", "name_en", "ENGLISH NAME", "Name", "name")
LCSD_ZH_KEYS = ("Name_cn", "Name_tc", "NameTC", "Name_zh", "name_zh", "中文名稱", "Name_chi")
LCSD_ADDR_KEYS = ("Address_en", "AddressEN", "address_en", "ENGLISH ADDRESS", "Address", "address")
LCSD_ADDR_ZH_KEYS = ("Address_cn", "Address_tc", "AddressTC", "address_zh", "中文地址")
LCSD_DIST_KEYS = ("District_en", "DistrictEN", "district", "DISTRICT", "District", "分區")
LCSD_PHONE_KEYS = ("Phone", "phone", "Telephone", "TelephoneEN", "Tel")
LCSD_HOURS_KEYS = (
    "Opening_hours_en",
    "OpeningHoursEN",
    "OpeningHours",
    "opening_hours",
    "Opening_hours",
)
LCSD_LAT_KEYS = ("Latitude", "LATITUDE", "latitude", "lat", "LAT")
LCSD_LNG_KEYS = ("Longitude", "LONGITUDE", "longitude", "lng", "LONG")
LCSD_URL_KEYS = ("Website", "WebsiteEN", "website", "URL", "url")
LCSD_ID_KEYS = ("OBJECTID", "GIHS", "id", "ID")
_HTML_TAG = re.compile(r"<[^>]+>")
_NA_VALUES = frozenset({"", "n.a.", "n/a", "na", "nil", "none", "-"})

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
        if value not in (None, ""):
            return str(value).strip()
        value = lower.get(key.lower())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def html_plain(value: str) -> str:
    text = html.unescape(value or "")
    text = _HTML_TAG.sub(" ", text)
    return " ".join(text.split())


def _clean_field(value: str) -> str:
    text = html_plain(value)
    return "" if text.lower() in _NA_VALUES else text


def _norm_district(*parts: str) -> str:
    blob = " ".join(part for part in parts if part)
    guessed = board_hk.district_from_address(blob)
    return guessed if guessed != "unknown" else _clean_field(parts[0] if parts else "")


def _qualify_playroom_name(name: str, facility_kind: str) -> str:
    if facility_kind != "lcsd_playroom" or not name:
        return name
    lower = name.lower()
    if "play room" in lower or "playroom" in lower or "兒童遊戲室" in name:
        return name
    return f"{name} Children's Play Room"


def csdi_query_url(dataset_id: str, *, offset: int = 0, count: int = 2000) -> str:
    return (
        f"{CSDI_FEATURE_SERVER.format(dataset_id=dataset_id)}"
        f"?where=1%3D1&outFields=*&f=json&outSR=4326"
        f"&resultRecordCount={max(1, int(count))}&resultOffset={max(0, int(offset))}"
    )


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


def parse_edb_csv(body: str, *, keep_all: bool = False) -> list[dict[str, Any]]:
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
            "sourceId": _first(raw, ("SCHOOL NO.", "SCHOOL NO")),
            "lat": _as_float(_first(raw, ("LATITUDE", "緯度"))),
            "lng": _as_float(_first(raw, ("LONGITUDE", "經度"))),
            "phone": _first(raw, ("TELEPHONE", "聯絡電話")),
            "officialUrl": _first(raw, ("WEBSITE", "網頁")),
        }
        if mapped["nameEn"] or mapped["nameZh"]:
            rows.append(mapped)
        if len(rows) >= ROW_CAP:
            break
    if not keep_all:
        rows = [row for row in rows if is_kindergarten(row)]
    if not rows:
        _log_event("warning", tag="board_opendata_schema_changed", dataset="edb", reason="required columns missing")
    return rows


def _opendata_blob_key(name: str) -> str:
    safe = str(name or "unknown").replace(":", "-")
    return f"board/{BOARD_KEY}/opendata/{safe}.json.gz"


def _blob_payload(raw: bytes) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        doc = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _cached(table: Any, name: str) -> dict[str, Any] | None:
    hit = board_store.get_cache(table, name)
    if not hit or not isinstance(hit.get("payload"), dict):
        return None
    payload = hit["payload"]
    inline = payload.get("rows")
    if isinstance(inline, list) and inline:
        return payload
    key = str(payload.get("s3Key") or "")
    if not key:
        return payload if isinstance(inline, list) else None
    import board_staff

    doc = _blob_payload(board_staff._blob_get(key))  # noqa: SLF001
    if not doc or not isinstance(doc.get("rows"), list):
        return None
    return {
        **payload,
        "rows": doc["rows"],
        "fetchedAt": str(doc.get("fetchedAt") or payload.get("fetchedAt") or ""),
        "s3Key": key,
        "rowCount": int(payload.get("rowCount") or len(doc["rows"])),
    }


def _store(table: Any, name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    capped = rows[:ROW_CAP]
    blob_key = _opendata_blob_key(name)
    body = gzip.compress(
        json.dumps({"rows": capped, "fetchedAt": fetched_at}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    import board_staff

    board_staff._blob_put(blob_key, body)  # noqa: SLF001
    pointer = {"fetchedAt": fetched_at, "rowCount": len(capped), "s3Key": blob_key}
    board_store.put_cache(table, name, pointer, ttl_seconds=CACHE_TTL)
    return {**pointer, "rows": capped}


def _store_best_effort(table: Any, name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        return _store(table, name, rows)
    except Exception as exc:
        _log_event("warning", tag="board_opendata_cache_failed", dataset=name, error=str(exc)[:200])
        return {
            "rows": rows[:ROW_CAP],
            "fetchedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


def _decode_body(raw: bytes) -> str:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    return raw.decode("utf-8", errors="replace")


def _download(url: str) -> str:
    import board_crawl

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or board_crawl.host_is_blocked(parsed.hostname or ""):
        raise OSError(f"opendata refused host {parsed.hostname}")
    req = urllib.request.Request(  # noqa: S310
        url,
        headers={"User-Agent": board_crawl.USER_AGENT, "Accept": "application/json,text/csv,*/*;q=0.8"},
        method="GET",
    )
    try:
        with board_crawl._opener().open(req, timeout=20) as resp:  # noqa: SLF001,S310
            raw = resp.read(8_000_001)
            status = int(getattr(resp, "status", None) or resp.getcode() or 200)
    except Exception as exc:
        raise OSError(f"opendata {url} {exc}") from exc
    if status >= 400:
        raise OSError(f"opendata {url} status {status}")
    return _decode_body(raw[:8_000_000])


def fehd_licensed_premises(table: Any | None = None, *, force: bool = False) -> dict[str, Any]:
    table = table if table is not None else board_store.records_table()
    cached = _cached(table, "opendata:fehd")
    if cached and cached.get("rows") and not force:
        return cached
    try:
        en = _download(FEHD_EN_URL)
        rows = parse_fehd_xml(en) if "<" in en[:200] else parse_fehd_csv(en)
    except Exception as exc:
        _log_event("warning", tag="board_opendata_fetch_failed", dataset="fehd", error=str(exc)[:200])
        if cached:
            return cached
        return {"rows": [], "fetchedAt": ""}
    return _store_best_effort(table, "opendata:fehd", rows)


def edb_schools(table: Any | None = None, *, force: bool = False, keep_all: bool = False) -> dict[str, Any]:
    table = table if table is not None else board_store.records_table()
    cache_name = "opendata:edb:all" if keep_all else "opendata:edb"
    cached = _cached(table, cache_name)
    if cached and cached.get("rows") and not force:
        return cached
    try:
        body = _download(EDB_CSV_URL)
        rows = parse_edb_csv(body, keep_all=keep_all)
    except Exception as exc:
        _log_event("warning", tag="board_opendata_fetch_failed", dataset="edb", error=str(exc)[:200])
        if cached:
            return cached
        return {"rows": [], "fetchedAt": ""}
    return _store_best_effort(table, cache_name, rows)


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


def _map_lcsd_row(raw: dict[str, Any], *, facility_kind: str, category: str) -> dict[str, Any]:
    address = _clean_field(_first(raw, LCSD_ADDR_KEYS) or _first(raw, LCSD_ADDR_ZH_KEYS))
    district = _norm_district(_clean_field(_first(raw, LCSD_DIST_KEYS)), address)
    name_en = _qualify_playroom_name(_clean_field(_first(raw, LCSD_NAME_KEYS)), facility_kind)
    source_id = _first(raw, LCSD_ID_KEYS) or f"{name_en}|{facility_kind}|{district}"
    return {
        "nameEn": name_en,
        "nameZh": _clean_field(_first(raw, LCSD_ZH_KEYS)),
        "addressEn": _clean_field(_first(raw, LCSD_ADDR_KEYS)),
        "addressZh": _clean_field(_first(raw, LCSD_ADDR_ZH_KEYS)),
        "district": district,
        "phone": _clean_field(_first(raw, LCSD_PHONE_KEYS)),
        "openingHours": _clean_field(_first(raw, LCSD_HOURS_KEYS))[:400],
        "lat": _as_float(_first(raw, LCSD_LAT_KEYS) or raw.get("Latitude") or raw.get("LATITUDE")),
        "lng": _as_float(_first(raw, LCSD_LNG_KEYS) or raw.get("Longitude") or raw.get("LONGITUDE")),
        "officialUrl": _clean_field(_first(raw, LCSD_URL_KEYS)),
        "facilityKind": facility_kind,
        "category": category,
        "source": "lcsd",
        "sourceId": source_id[:80],
    }


def parse_lcsd_json(body: str, *, facility_kind: str, category: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in _rows_from_json(body):
        mapped = _map_lcsd_row(raw, facility_kind=facility_kind, category=category)
        if mapped["nameEn"] or mapped["nameZh"]:
            rows.append(mapped)
        if len(rows) >= ROW_CAP:
            break
    return rows


def parse_csdi_features(body: str, *, facility_kind: str, category: str, source: str = "lcsd") -> list[dict[str, Any]]:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return []
    rows: list[dict[str, Any]] = []
    for feat in parsed.get("features") or []:
        if not isinstance(feat, dict):
            continue
        raw = dict(feat.get("attributes") or {})
        geom = feat.get("geometry") if isinstance(feat.get("geometry"), dict) else {}
        if raw.get("LATITUDE") in (None, "") and geom.get("y") is not None:
            raw["LATITUDE"] = geom.get("y")
            raw["LONGITUDE"] = geom.get("x")
        if source == "swd":
            mapped = {
                "nameEn": _clean_field(_first(raw, SWD_NAME_KEYS)),
                "nameZh": _clean_field(_first(raw, SWD_ZH_KEYS)),
                "addressEn": _clean_field(_first(raw, SWD_ADDR_KEYS)),
                "addressZh": _clean_field(_first(raw, SWD_ADDR_ZH_KEYS)),
                "district": _norm_district(_clean_field(_first(raw, SWD_DIST_KEYS)), _first(raw, SWD_ADDR_KEYS)),
                "phone": _clean_field(_first(raw, SWD_PHONE_KEYS)),
                "officialUrl": _clean_field(_first(raw, ("WebsiteEN", "Website", "website"))),
                "lat": _as_float(raw.get("Latitude") or raw.get("LATITUDE")),
                "lng": _as_float(raw.get("Longitude") or raw.get("LONGITUDE")),
                "facilityKind": "swd_child_care",
                "category": "Class",
                "source": "swd",
                "sourceId": str(raw.get("OBJECTID") or "")[:80],
            }
        else:
            mapped = _map_lcsd_row(raw, facility_kind=facility_kind, category=category)
        if mapped.get("nameEn") or mapped.get("nameZh"):
            if not mapped.get("sourceId"):
                mapped["sourceId"] = f"{mapped.get('nameEn')}|{mapped.get('nameZh')}"[:80]
            rows.append(mapped)
        if len(rows) >= ROW_CAP:
            break
    return rows


def parse_swd_csv(body: str) -> list[dict[str, Any]]:
    sample = body[:400]
    dialect = "excel-tab" if sample.count("\t") > sample.count(",") else "excel"
    reader = csv.DictReader(io.StringIO(body), dialect=dialect)
    rows: list[dict[str, Any]] = []
    for raw in reader:
        address = _first(raw, SWD_ADDR_KEYS) or _first(raw, SWD_ADDR_ZH_KEYS)
        mapped = {
            "nameEn": _clean_field(_first(raw, SWD_NAME_KEYS)),
            "nameZh": _clean_field(_first(raw, SWD_ZH_KEYS)),
            "addressEn": _clean_field(_first(raw, SWD_ADDR_KEYS)),
            "addressZh": _clean_field(_first(raw, SWD_ADDR_ZH_KEYS)),
            "district": _norm_district(_clean_field(_first(raw, SWD_DIST_KEYS)), address),
            "phone": _clean_field(_first(raw, SWD_PHONE_KEYS)),
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


def edb_kindergartens(table: Any | None = None, *, force: bool = False) -> dict[str, Any]:
    payload = edb_schools(table, force=force)
    rows = [r for r in (payload.get("rows") or []) if is_kindergarten(r)]
    for row in rows:
        row["facilityKind"] = "edb_kindergarten"
        row["category"] = "Class"
        row["source"] = "edb"
        row["sourceId"] = str(row.get("sourceId") or f"{row.get('nameEn') or ''}|{row.get('nameZh') or ''}")[:80]
    return {**payload, "rows": rows[:ROW_CAP]}


def _fetch_csdi_rows(dataset_id: str, *, facility_kind: str, category: str, source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while len(rows) < ROW_CAP:
        body = _download(csdi_query_url(dataset_id, offset=offset, count=2000))
        parsed = parse_csdi_features(body, facility_kind=facility_kind, category=category, source=source)
        if not parsed:
            break
        rows.extend(parsed)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            break
        if not payload.get("exceededTransferLimit"):
            break
        offset += len(payload.get("features") or [])
        if offset <= 0:
            break
    return rows[:ROW_CAP]


def lcsd_facilities(table: Any | None = None, *, force: bool = False) -> dict[str, Any]:
    table = table if table is not None else board_store.records_table()
    cached = _cached(table, "opendata:lcsd")
    if cached and cached.get("rows") and not force:
        return cached
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        for kind, url, category in LCSD_JSON_FEEDS:
            try:
                body = _download(url)
            except Exception as exc:
                errors.append(f"{kind}:{exc}"[:120])
                continue
            parsed = parse_lcsd_json(body, facility_kind=kind, category=category)
            if not parsed:
                _log_event("warning", tag="board_opendata_schema_changed", dataset=kind, reason="no facility rows")
            rows.extend(parsed)
        for kind, dataset_id, category in LCSD_CSDI_FEEDS:
            try:
                parsed = _fetch_csdi_rows(dataset_id, facility_kind=kind, category=category, source="lcsd")
            except Exception as exc:
                errors.append(f"{kind}:{exc}"[:120])
                continue
            if not parsed:
                _log_event("warning", tag="board_opendata_schema_changed", dataset=kind, reason="no facility rows")
            rows.extend(parsed)
    except Exception as exc:
        _log_event("warning", tag="board_opendata_fetch_failed", dataset="lcsd", error=str(exc)[:200])
        if cached:
            return cached
        return {"rows": [], "fetchedAt": ""}
    if rows:
        return _store_best_effort(table, "opendata:lcsd", rows)
    if cached:
        return cached
    if errors:
        _log_event("warning", tag="board_opendata_fetch_failed", dataset="lcsd", error="; ".join(errors)[:200])
    return {"rows": [], "fetchedAt": ""}


def swd_child_care_centres(table: Any | None = None, *, force: bool = False) -> dict[str, Any]:
    table = table if table is not None else board_store.records_table()
    cached = _cached(table, "opendata:swd")
    if cached and cached.get("rows") and not force:
        return cached
    try:
        rows = _fetch_csdi_rows(SWD_CSDI_DATASET, facility_kind="swd_child_care", category="Class", source="swd")
        if not rows:
            body = _download(SWD_CCC_URL)
            rows = parse_swd_csv(body)
        for row in rows:
            row.setdefault("facilityKind", "swd_child_care")
            row.setdefault("category", "Class")
            row.setdefault("source", "swd")
    except Exception as exc:
        _log_event("warning", tag="board_opendata_fetch_failed", dataset="swd", error=str(exc)[:200])
        if cached:
            return cached
        return {"rows": [], "fetchedAt": ""}
    if rows:
        return _store_best_effort(table, "opendata:swd", rows)
    if cached:
        return cached
    return {"rows": [], "fetchedAt": ""}


def lcsd_programmes(table: Any | None = None) -> dict[str, Any]:
    """Alias for outreach `kind=lcsd`: facility rows, not programme listings."""
    return lcsd_facilities(table)
