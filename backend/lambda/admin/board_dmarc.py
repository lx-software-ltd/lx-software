"""Parse inbound DMARC aggregate reports and evaluate them on the cache refresh.

Ingest (``board_mail.ingest_bytes``) calls :func:`ingest_message` for bulk
mail that :func:`board_mail.is_dmarc_or_feedback_report` recognises. Parsing
is stdlib-only and stays on when staff is off. :func:`evaluate` writes
``dmarc:summary``; it does not call the network and does not start tasks.
"""

from __future__ import annotations

import gzip
import io
import os
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any
from xml.etree import ElementTree

import board_hk
import board_mail
import board_store
from contract_constants import BOARD_KEY, BOARD_MAIL_MESSAGE_TTL_DAYS
from http_common import _log_event

SUMMARY_CACHE = "dmarc:summary"
MAX_XML_BYTES = 5 * 1024 * 1024
MAX_ZIP_MEMBERS = 32
MAX_SOURCES = 500
SUMMARY_SOURCE_CAP = 40
SUMMARY_FINDING_CAP = 30
SUMMARY_TTL_SECONDS = 7 * 86400
CONSUMER_MAIL_DOMAINS = frozenset({"google.com", "gmail.com", "icloud.com"})

_SK_UNSAFE = re.compile(r"[^A-Za-z0-9._@+-]")
_PATH_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class DmarcParseError(ValueError):
    """One attachment could not be read as a DMARC aggregate."""


def _expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() > deadline


def _sk(value: str) -> str:
    cleaned = _SK_UNSAFE.sub("_", str(value or ""))[:120]
    return cleaned or "_"


def _path_part(value: str) -> str:
    cleaned = _PATH_UNSAFE.sub("_", str(value or ""))[:80]
    return cleaned or "report"


def _local(tag: str) -> str:
    return str(tag or "").rsplit("}", 1)[-1]


def _child(el: ElementTree.Element | None, name: str) -> ElementTree.Element | None:
    if el is None:
        return None
    for child in list(el):
        if _local(child.tag) == name:
            return child
    return None


def _text(el: ElementTree.Element | None, name: str) -> str:
    found = _child(el, name)
    if found is None or found.text is None:
        return ""
    return str(found.text).strip()


def _unix_to_iso(value: str) -> tuple[str, int]:
    try:
        n = int(str(value or "").strip())
    except (TypeError, ValueError):
        return "", 0
    if n <= 0:
        return "", 0
    return datetime.fromtimestamp(n, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), n


def _ttl() -> int:
    return int(time.time()) + BOARD_MAIL_MESSAGE_TTL_DAYS * 86400


def _reject_dtd(xml: bytes) -> None:
    lowered = xml.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise DmarcParseError("XML DTD rejected")


def _gunzip(data: bytes) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as handle:
            out = handle.read(MAX_XML_BYTES + 1)
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise DmarcParseError(f"gzip: {exc}") from exc
    if len(out) > MAX_XML_BYTES:
        raise DmarcParseError("decompressed gzip exceeds 5 MB")
    return out


def _looks_like_xml(name: str, data: bytes) -> bool:
    stripped = data.lstrip()[:800].lower()
    if name.lower().endswith(".xml"):
        return True
    return stripped.startswith(b"<?xml") or b"<feedback" in stripped or b"<report_metadata" in stripped


def _maybe_xml(name: str, data: bytes) -> list[bytes]:
    lower = name.lower()
    if lower.endswith(".gz") or lower.endswith(".gzip") or data[:2] == b"\x1f\x8b":
        data = _gunzip(data)
        if lower.endswith(".gzip"):
            lower = lower[: -len(".gzip")]
        elif lower.endswith(".gz"):
            lower = lower[: -len(".gz")]
    if _looks_like_xml(lower, data):
        _reject_dtd(data)
        return [data]
    return []


def _from_zip(payload: bytes) -> list[bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise DmarcParseError(f"zip: {exc}") from exc
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if len(infos) > MAX_ZIP_MEMBERS:
        raise DmarcParseError("zip has too many members")
    out: list[bytes] = []
    total = 0
    for info in infos:
        if info.flag_bits & 0x1:
            raise DmarcParseError("encrypted zip member")
        if info.file_size > MAX_XML_BYTES:
            raise DmarcParseError("zip member exceeds 5 MB")
        with archive.open(info) as handle:
            data = handle.read(MAX_XML_BYTES + 1)
        if len(data) > MAX_XML_BYTES:
            raise DmarcParseError("decompressed zip member exceeds 5 MB")
        total += len(data)
        if total > MAX_XML_BYTES:
            raise DmarcParseError("decompressed zip exceeds 5 MB")
        out.extend(_maybe_xml(info.filename or "", data))
    return out


def _extract_xml(name: str, content_type: str, payload: bytes) -> list[bytes]:
    if len(payload) > MAX_XML_BYTES:
        raise DmarcParseError("attachment exceeds 5 MB")
    lower = name.lower()
    ctype = content_type.lower()
    if "gzip" in ctype or lower.endswith(".gz") or lower.endswith(".gzip") or payload[:2] == b"\x1f\x8b":
        return _maybe_xml(lower or "report.gz", payload)
    if lower.endswith(".zip") or ctype in ("application/zip", "application/x-zip-compressed") or payload[:2] == b"PK":
        return _from_zip(payload)
    if lower.endswith(".xml") or ctype in ("text/xml", "application/xml"):
        return _maybe_xml(lower or "report.xml", payload)
    stripped = payload.lstrip()
    if stripped.startswith(b"<?xml") or stripped.startswith(b"<feedback"):
        return _maybe_xml("report.xml", payload)
    return []


def _iter_parts(msg: EmailMessage) -> list[tuple[str, str, bytes]]:
    found: list[tuple[str, str, bytes]] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, (bytes, bytearray)) or not payload:
            continue
        name = os.path.basename(part.get_filename() or "")
        ctype = part.get_content_type()
        disposition = str(part.get_content_disposition() or "")
        blob = bytes(payload)
        if disposition == "attachment" or name or _extract_interest(name, ctype, blob):
            found.append((name, ctype, blob))
    return found


def _extract_interest(name: str, content_type: str, payload: bytes) -> bool:
    lower = name.lower()
    ctype = content_type.lower()
    if lower.endswith((".zip", ".gz", ".gzip", ".xml")):
        return True
    if "gzip" in ctype or ctype in ("application/zip", "application/x-zip-compressed", "text/xml", "application/xml"):
        return True
    return payload[:2] in (b"PK", b"\x1f\x8b") or payload.lstrip()[:5] == b"<?xml"


def _parse_auth(auth: ElementTree.Element | None) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    dkim: list[dict[str, str]] = []
    spf: list[dict[str, str]] = []
    if auth is None:
        return dkim, spf
    for el in list(auth):
        kind = _local(el.tag)
        if kind == "dkim" and len(dkim) < 8:
            dkim.append(
                {
                    "domain": _text(el, "domain").lower()[:200],
                    "selector": _text(el, "selector")[:80],
                    "result": _text(el, "result").lower()[:40],
                }
            )
        elif kind == "spf" and len(spf) < 8:
            spf.append(
                {
                    "domain": _text(el, "domain").lower()[:200],
                    "result": _text(el, "result").lower()[:40],
                }
            )
    return dkim, spf


def _empty_source(ip: str) -> dict[str, Any]:
    return {
        "sourceIp": ip,
        "count": 0,
        "bothFail": 0,
        "dkimPassSpfFail": 0,
        "aligned": 0,
        "quarantine": 0,
        "reject": 0,
        "dispositions": {},
        "headerFrom": [],
        "dkimAuth": [],
        "spfAuth": [],
        "latestCount": 0,
        "latestEnd": 0,
    }


def _merge_auth(into: list[dict[str, str]], extra: list[dict[str, str]]) -> None:
    seen = {tuple(sorted(row.items())) for row in into}
    for row in extra:
        key = tuple(sorted(row.items()))
        if key in seen or len(into) >= 8:
            continue
        into.append(row)
        seen.add(key)


def _add_unique(into: list[str], value: str, *, limit: int = 8) -> None:
    if value and value not in into and len(into) < limit:
        into.append(value)


def parse_aggregate_xml(xml: bytes) -> dict[str, Any] | None:
    """Return one aggregate report, or None when the XML is not one."""
    _reject_dtd(xml)
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise DmarcParseError(f"xml: {exc}") from exc
    feedback = root if _local(root.tag) == "feedback" else None
    if feedback is None:
        for el in root.iter():
            if _local(el.tag) == "feedback":
                feedback = el
                break
    if feedback is None:
        return None
    meta = _child(feedback, "report_metadata")
    report_id = _text(meta, "report_id")
    if meta is None or not report_id:
        return None
    begin_iso, begin_unix = _unix_to_iso(_text(_child(meta, "date_range"), "begin"))
    end_iso, end_unix = _unix_to_iso(_text(_child(meta, "date_range"), "end"))
    policy_el = _child(feedback, "policy_published")
    try:
        pct = int(_text(policy_el, "pct") or "100")
    except ValueError:
        pct = 100
    policy = {
        "domain": _text(policy_el, "domain").lower()[:200],
        "p": (_text(policy_el, "p") or "").lower()[:20],
        "sp": (_text(policy_el, "sp") or "").lower()[:20],
        "adkim": (_text(policy_el, "adkim") or "").lower()[:8],
        "aspf": (_text(policy_el, "aspf") or "").lower()[:8],
        "pct": max(0, min(100, pct)),
    }
    sources: dict[str, dict[str, Any]] = {}
    header_from: list[str] = []
    record_count = 0
    message_count = 0
    aligned_count = 0
    for rec in list(feedback):
        if _local(rec.tag) != "record":
            continue
        row = _child(rec, "row")
        if row is None:
            continue
        record_count += 1
        try:
            count = max(0, int(_text(row, "count") or "0"))
        except ValueError:
            count = 0
        evaluated = _child(row, "policy_evaluated")
        disposition = (_text(evaluated, "disposition") or "none").lower()
        dkim = (_text(evaluated, "dkim") or "").lower()
        spf = (_text(evaluated, "spf") or "").lower()
        ident = _child(rec, "identifiers")
        header = _text(ident, "header_from").lower()[:200]
        dkim_auth, spf_auth = _parse_auth(_child(rec, "auth_results"))
        ip = _text(row, "source_ip")[:64] or "unknown"
        src = sources.setdefault(ip, _empty_source(ip))
        src["count"] += count
        message_count += count
        aligned = dkim == "pass" or spf == "pass"
        if aligned:
            src["aligned"] += count
            aligned_count += count
        if dkim == "fail" and spf == "fail":
            src["bothFail"] += count
        if dkim == "pass" and spf == "fail":
            src["dkimPassSpfFail"] += count
        if disposition == "quarantine":
            src["quarantine"] += count
        elif disposition == "reject":
            src["reject"] += count
        bucket = src["dispositions"]
        bucket[disposition or "none"] = int(bucket.get(disposition or "none") or 0) + count
        _add_unique(src["headerFrom"], header)
        _add_unique(header_from, header)
        _merge_auth(src["dkimAuth"], dkim_auth)
        _merge_auth(src["spfAuth"], spf_auth)
        if end_unix >= int(src["latestEnd"] or 0):
            src["latestEnd"] = end_unix
            src["latestCount"] = count
    ranked = sorted(sources.values(), key=lambda row: int(row["count"]), reverse=True)
    truncated = len(ranked) > MAX_SOURCES
    kept = []
    for row in ranked[:MAX_SOURCES]:
        published = {k: v for k, v in row.items() if k != "latestEnd"}
        kept.append(published)
    return {
        "orgName": _text(meta, "org_name")[:120] or "unknown",
        "email": _text(meta, "email")[:200],
        "reportId": report_id[:180],
        "dateBegin": begin_iso,
        "dateEnd": end_iso,
        "dateBeginUnix": begin_unix,
        "dateEndUnix": end_unix,
        "policy": policy,
        "headerFrom": header_from[:20],
        "recordCount": record_count,
        "messageCount": message_count,
        "alignedCount": aligned_count,
        "sources": kept,
        "sourcesTruncated": truncated,
    }


def _reports_pk() -> str:
    return board_store.board_pk("dmarc#reports")


def _id_key(org: str, report_id: str) -> dict[str, str]:
    return {"pk": board_store.board_pk("dmarc#ids"), "sk": f"ID#{_sk(org)}#{_sk(report_id)}"}


def _claim_report_id(table: Any, org: str, report_id: str, thread_id: str) -> bool:
    try:
        table.put_item(
            Item={
                **_id_key(org, report_id),
                "orgName": org,
                "reportId": report_id,
                "threadId": thread_id,
                "expiresAt": _ttl(),
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as exc:
        code = ""
        response = getattr(exc, "response", None)
        if isinstance(response, dict):
            code = str((response.get("Error") or {}).get("Code") or "")
        if code == "ConditionalCheckFailedException" or type(exc).__name__ == "ConditionalCheckFailedException":
            return False
        raise
    return True


def _release_report_id(table: Any, org: str, report_id: str) -> None:
    try:
        table.delete_item(Key=_id_key(org, report_id))
    except Exception as exc:
        _log_event("warning", tag="board_dmarc_parse_failed", error=f"dedupe rollback: {exc}"[:200])


def _store_raw(org: str, report_id: str, xml: bytes) -> str:
    key = f"board/{BOARD_KEY}/dmarc/{_path_part(org)}/{_path_part(report_id)}.xml.gz"
    try:
        import board_staff

        board_staff._blob_put(key, gzip.compress(xml))  # noqa: SLF001
    except Exception as exc:
        _log_event("warning", tag="board_dmarc_raw_store_failed", error=str(exc)[:200])
        return ""
    return key


def _load_meta(table: Any) -> dict[str, Any]:
    return board_store._get_state(table, "dmarc#meta") or {}  # noqa: SLF001


def _save_meta(table: Any, doc: dict[str, Any]) -> None:
    board_store._put_state(table, "dmarc#meta", doc)  # noqa: SLF001


def _touch_google(table: Any, received_at: str) -> None:
    meta = _load_meta(table)
    current = str(meta.get("lastGoogleReceivedAt") or "")
    if received_at and received_at >= current:
        meta["lastGoogleReceivedAt"] = received_at
        _save_meta(table, meta)


def _bump_forensic(table: Any) -> None:
    meta = _load_meta(table)
    try:
        count = int(meta.get("forensicCount") or 0)
    except (TypeError, ValueError):
        count = 0
    meta["forensicCount"] = count + 1
    meta["lastForensicAt"] = board_store.now_iso()
    _save_meta(table, meta)


def _touch_thread(table: Any, thread_id: str, org: str, report_id: str, record_count: int) -> None:
    if not thread_id:
        return
    thread = board_store.get_mail_thread(table, thread_id)
    if not thread:
        return
    token = f"{org}:{report_id}"
    ids = [str(item) for item in (thread.get("dmarcReportIds") or []) if item]
    if token not in ids:
        ids.append(token)
    try:
        prior = int(thread.get("dmarcRecordCount") or 0)
    except (TypeError, ValueError):
        prior = 0
    thread["dmarcReportIds"] = ids[:50]
    thread["dmarcRecordCount"] = prior + max(0, int(record_count))
    board_store.put_mail_thread(table, thread)


def _store_report(table: Any, report: dict[str, Any], xml: bytes, *, thread_id: str) -> bool:
    org = str(report.get("orgName") or "unknown")
    report_id = str(report.get("reportId") or "")
    if not report_id:
        return False
    if not _claim_report_id(table, org, report_id, thread_id):
        return False
    received_at = board_store.now_iso()
    raw_key = _store_raw(org, report_id, xml)
    doc = {**report, "rawKey": raw_key, "threadId": thread_id, "receivedAt": received_at}
    end = str(doc.get("dateEnd") or received_at)
    try:
        table.put_item(
            Item={
                "pk": _reports_pk(),
                "sk": f"REPORT#{_sk(end)}#{_sk(org)}#{_sk(report_id)}",
                "expiresAt": _ttl(),
                **board_store._to_ddb_nested(doc),  # noqa: SLF001
            }
        )
    except Exception:
        _release_report_id(table, org, report_id)
        raise
    _touch_thread(table, thread_id, org, report_id, int(report.get("recordCount") or 0))
    if "google" in org.lower():
        _touch_google(table, received_at)
    return True


def list_reports(table: Any) -> list[dict[str, Any]]:
    items = board_store._query_all(  # noqa: SLF001
        table,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": _reports_pk(), ":prefix": "REPORT#"},
    )
    now = int(time.time())
    out: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        try:
            expires = int(raw.get("expiresAt") or 0)
        except (TypeError, ValueError):
            expires = 0
        if expires and expires < now:
            continue
        doc = {k: v for k, v in board_store._strip_keys(raw).items() if k != "expiresAt"}  # noqa: SLF001
        out.append(doc)
    return out


def ingest_message(
    table: Any,
    msg: EmailMessage,
    *,
    thread_id: str,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Parse aggregate XML off ``msg``. Failures are logged and not raised."""
    if _expired(deadline):
        _log_event("warning", tag="board_dmarc_parse_failed", thread=thread_id, error="deadline")
        return {"reports": 0, "duplicates": 0, "errors": 1, "forensic": False, "skipped": "deadline"}
    stored = 0
    duplicates = 0
    errors = 0
    saw_aggregate = False
    try:
        parts = _iter_parts(msg)
    except Exception as exc:
        _log_event("warning", tag="board_dmarc_parse_failed", thread=thread_id, error=str(exc)[:200])
        return {"reports": 0, "duplicates": 0, "errors": 1, "forensic": False}
    for name, ctype, payload in parts:
        if _expired(deadline):
            errors += 1
            _log_event("warning", tag="board_dmarc_parse_failed", thread=thread_id, error="deadline")
            break
        try:
            blobs = _extract_xml(name, ctype, payload)
        except DmarcParseError as exc:
            errors += 1
            _log_event("warning", tag="board_dmarc_parse_failed", thread=thread_id, error=str(exc)[:200])
            continue
        for xml in blobs:
            if _expired(deadline):
                errors += 1
                _log_event("warning", tag="board_dmarc_parse_failed", thread=thread_id, error="deadline")
                break
            try:
                report = parse_aggregate_xml(xml)
            except DmarcParseError as exc:
                errors += 1
                _log_event("warning", tag="board_dmarc_parse_failed", thread=thread_id, error=str(exc)[:200])
                continue
            if report is None:
                continue
            saw_aggregate = True
            try:
                if _store_report(table, report, xml, thread_id=thread_id):
                    stored += 1
                else:
                    duplicates += 1
            except Exception as exc:
                errors += 1
                _log_event("warning", tag="board_dmarc_parse_failed", thread=thread_id, error=str(exc)[:200])
    forensic = False
    if not saw_aggregate and errors == 0:
        _bump_forensic(table)
        forensic = True
    return {"reports": stored, "duplicates": duplicates, "errors": errors, "forensic": forensic}


# ---------------------------------------------------------------------------
# Evaluation (no network)
# ---------------------------------------------------------------------------


def _dmarc_settings(settings: dict[str, Any]) -> dict[str, Any]:
    return board_store.normalize_dmarc_config((settings or {}).get("dmarc"))


def known_sender_domains(settings: dict[str, Any]) -> set[str]:
    out = {"amazonses.com", board_mail.mail_domain()}
    outreach = (os.environ.get("OUTREACH_SENDING_DOMAIN") or "partners.siutindei.com").strip().lower().rstrip(".")
    if outreach:
        out.add(outreach)
    for domain in _dmarc_settings(settings).get("knownSenderDomains") or []:
        if domain:
            out.add(str(domain).lower())
    return {d for d in out if d}


def _match_known(domain: str, known: set[str]) -> str:
    candidate = str(domain or "").strip().lower().rstrip(".")
    if not candidate:
        return ""
    for item in known:
        if candidate == item or candidate.endswith("." + item):
            return item
    return ""


def _parse_received(report: dict[str, Any]) -> datetime | None:
    raw = str(report.get("receivedAt") or "")
    if not raw:
        return None
    try:
        return board_hk.parse_iso(raw)
    except ValueError:
        return None


def _period_end(report: dict[str, Any]) -> datetime | None:
    try:
        unix = int(report.get("dateEndUnix") or 0)
    except (TypeError, ValueError):
        unix = 0
    if unix > 0:
        return datetime.fromtimestamp(unix, tz=timezone.utc)
    return _parse_received(report)


def _in_window(report: dict[str, Any], now: datetime, days: int) -> bool:
    end = _period_end(report)
    if end is None:
        return False
    return now - timedelta(days=days) <= end <= now + timedelta(hours=36)


def _stats(reports: list[dict[str, Any]]) -> dict[str, Any]:
    messages = 0
    aligned = 0
    orgs: set[str] = set()
    for report in reports:
        messages += int(report.get("messageCount") or 0)
        aligned += int(report.get("alignedCount") or 0)
        org = str(report.get("orgName") or "")
        if org:
            orgs.add(org)
    pct = round(100.0 * aligned / messages, 1) if messages else 0.0
    return {
        "messages": messages,
        "aligned": aligned,
        "alignedPct": pct,
        "reports": len(reports),
        "orgs": len(orgs),
    }


def _merge_sources(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[tuple[int, str, dict[str, Any]]] = []
    for report in reports:
        try:
            end_unix = int(report.get("dateEndUnix") or 0)
        except (TypeError, ValueError):
            end_unix = 0
        order.append((end_unix, str(report.get("receivedAt") or ""), report))
    order.sort(key=lambda item: (item[0], item[1]))
    for end_unix, _received, report in order:
        for src in report.get("sources") or []:
            if not isinstance(src, dict):
                continue
            ip = str(src.get("sourceIp") or "")
            if not ip:
                continue
            row = merged.setdefault(ip, _empty_source(ip))
            row["count"] += int(src.get("count") or 0)
            row["bothFail"] += int(src.get("bothFail") or 0)
            row["dkimPassSpfFail"] += int(src.get("dkimPassSpfFail") or 0)
            row["aligned"] += int(src.get("aligned") or 0)
            row["quarantine"] += int(src.get("quarantine") or 0)
            row["reject"] += int(src.get("reject") or 0)
            for key, value in (src.get("dispositions") or {}).items():
                bucket = row["dispositions"]
                bucket[str(key)] = int(bucket.get(str(key)) or 0) + int(value or 0)
            for header in src.get("headerFrom") or []:
                _add_unique(row["headerFrom"], str(header))
            _merge_auth(row["dkimAuth"], [a for a in (src.get("dkimAuth") or []) if isinstance(a, dict)])
            _merge_auth(row["spfAuth"], [a for a in (src.get("spfAuth") or []) if isinstance(a, dict)])
            if end_unix >= int(row.get("latestEnd") or 0):
                row["latestEnd"] = end_unix
                row["latestCount"] = int(src.get("count") or 0)
    rows = sorted(merged.values(), key=lambda item: int(item["count"]), reverse=True)
    published = []
    for row in rows:
        published.append({k: v for k, v in row.items() if k != "latestEnd"})
    return published


def _auth_domains(source: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for row in list(source.get("dkimAuth") or []) + list(source.get("spfAuth") or []):
        if isinstance(row, dict):
            _add_unique(found, str(row.get("domain") or ""))
    return found


def _disposition_word(source: dict[str, Any]) -> str:
    if int(source.get("reject") or 0):
        return "reject"
    if int(source.get("quarantine") or 0):
        return "quarantine"
    return "none"


def _load_seen_headers(table: Any) -> list[str]:
    doc = board_store._get_state(table, "dmarc#header-from") or {}  # noqa: SLF001
    return [str(item).lower() for item in (doc.get("domains") or []) if item]


def _save_seen_headers(table: Any, domains: list[str]) -> None:
    board_store._put_state(table, "dmarc#header-from", {"domains": domains[:200]})  # noqa: SLF001


def _header_bases(reports: list[dict[str, Any]]) -> set[str]:
    bases = {board_mail.mail_domain()}
    outreach = (os.environ.get("OUTREACH_SENDING_DOMAIN") or "partners.siutindei.com").strip().lower().rstrip(".")
    if outreach:
        bases.add(outreach)
    for report in reports:
        domain = str((report.get("policy") or {}).get("domain") or "").lower().rstrip(".")
        if domain:
            bases.add(domain)
    return {b for b in bases if b}


def _is_new_header(domain: str, bases: set[str], seen: set[str]) -> bool:
    candidate = domain.lower().rstrip(".")
    if not candidate or candidate in seen or candidate in bases:
        return False
    return True


def _fmt_hkt(iso: str) -> str:
    if not iso:
        return "never"
    try:
        local = board_hk.as_hkt(board_hk.parse_iso(iso))
    except ValueError:
        return iso
    return local.strftime("%Y-%m-%d %H:%M HKT")


def _org_rows(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for report in reports:
        org = str(report.get("orgName") or "unknown")
        row = grouped.setdefault(org, {"org": org, "reports": 0, "lastReceivedAt": ""})
        row["reports"] += 1
        received = str(report.get("receivedAt") or "")
        if received >= str(row["lastReceivedAt"]):
            row["lastReceivedAt"] = received
    return sorted(grouped.values(), key=lambda item: str(item["lastReceivedAt"]), reverse=True)


def _build_line(
    day: dict[str, Any],
    last_google: str,
    findings: list[dict[str, Any]],
) -> str:
    prefix = "DMARC (reports received in the last 24 h)"
    if int(day.get("reports") or 0) == 0:
        text = f"{prefix}: no aggregate reports."
    else:
        text = (
            f"{prefix}: {int(day['messages'])} messages, {float(day['alignedPct']):.1f} % aligned, "
            f"{int(day['orgs'])} orgs reporting."
        )
    if last_google:
        text += f" Last Google report {_fmt_hkt(last_google)}."
    else:
        text += " No Google report received yet."
    actionable = [row for row in findings if row.get("severity") != "info"]
    info = [row for row in findings if row.get("severity") == "info"]
    if actionable:
        noun = "finding" if len(actionable) == 1 else "findings"
        text += f" {len(actionable)} {noun}: {actionable[0].get('summary')}"
    elif info:
        text += f" {len(info)} info: {info[0].get('summary')}"
    else:
        text += " No problems."
    return text


def _note_gaps(table: Any, findings: list[dict[str, Any]]) -> None:
    import board_duties

    for finding in findings:
        kind = finding.get("kind")
        evidence = finding.get("evidence") if isinstance(finding.get("evidence"), dict) else {}
        if kind == "own_sender_failing":
            sender = str(evidence.get("sender") or "sender")
            board_duties.note_config_gap(
                table,
                gap_id=f"dmarc:{sender}",
                reason=(
                    f"DMARC failure for known sender {sender} at {evidence.get('sourceIp') or 'unknown ip'}. "
                    "Check SES Easy DKIM, SPF and the published DMARC record."
                ),
            )
        elif kind == "unknown_source_failing":
            for domain in evidence.get("authDomains") or []:
                matched = _match_known(str(domain), set(CONSUMER_MAIL_DOMAINS))
                if not matched:
                    continue
                board_duties.note_config_gap(
                    table,
                    gap_id=f"dmarc:{matched}",
                    reason=(
                        f"Auth domain {matched} failed DMARC and is not in settings.dmarc.knownSenderDomains. "
                        "Add it if this is mail you send from Gmail or iCloud; otherwise treat the source as spoofing."
                    ),
                )


def evaluate(table: Any, settings: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Write ``dmarc:summary``. Deterministic; no DNS and no LLM."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    cfg = _dmarc_settings(settings)
    enabled = bool(cfg.get("enabled", True))
    known = known_sender_domains(settings)
    reports = list_reports(table)
    day = [row for row in reports if (_parse_received(row) or moment) >= moment - timedelta(hours=24) and _parse_received(row)]
    week = [row for row in reports if _in_window(row, moment, 7)]
    month = [row for row in reports if _in_window(row, moment, 30)]
    sources = _merge_sources(week)
    findings: list[dict[str, Any]] = []
    try:
        spoof_at = int(cfg.get("spoofAlertCount") or 20)
    except (TypeError, ValueError):
        spoof_at = 20
    if enabled:
        for source in sources:
            domains = _auth_domains(source)
            sender = ""
            for domain in domains:
                sender = _match_known(domain, known)
                if sender:
                    break
            both = int(source.get("bothFail") or 0)
            bad_disp = int(source.get("quarantine") or 0) + int(source.get("reject") or 0)
            ip = str(source.get("sourceIp") or "")
            evidence = {
                "sourceIp": ip,
                "count": int(source.get("count") or 0),
                "latestCount": int(source.get("latestCount") or 0),
                "dkim": "fail" if both else ("pass" if int(source.get("dkimPassSpfFail") or 0) or int(source.get("aligned") or 0) else "fail"),
                "spf": "fail" if both or int(source.get("dkimPassSpfFail") or 0) else "pass",
                "disposition": _disposition_word(source),
                "authDomains": domains,
                "headerFrom": list(source.get("headerFrom") or []),
            }
            if sender and (both or bad_disp):
                evidence["sender"] = sender
                findings.append(
                    {
                        "id": "own_sender_failing",
                        "kind": "own_sender_failing",
                        "severity": "high",
                        "fingerprint": f"own_sender_failing:{sender}:{ip}",
                        "summary": (
                            f"own sender {sender} at {ip} "
                            f"({evidence['count']} msgs, dkim {evidence['dkim']}, spf {evidence['spf']}, "
                            f"disposition {evidence['disposition']})"
                        ),
                        "evidence": evidence,
                    }
                )
                continue
            if (
                not sender
                and int(source.get("dkimPassSpfFail") or 0) > 0
                and both == 0
                and bad_disp == 0
            ):
                findings.append(
                    {
                        "id": "forwarding_noise",
                        "kind": "forwarding_noise",
                        "severity": "info",
                        "fingerprint": f"forwarding_noise:{ip}",
                        "summary": f"forwarding {ip} (dkim pass, spf fail, {evidence['count']} msgs)",
                        "evidence": evidence,
                    }
                )
                continue
            if not sender and (both or bad_disp):
                latest = int(source.get("latestCount") or 0)
                severity = "high" if latest >= spoof_at else "medium"
                findings.append(
                    {
                        "id": "unknown_source_failing",
                        "kind": "unknown_source_failing",
                        "severity": severity,
                        "fingerprint": f"unknown_source_failing:{ip}",
                        "summary": (
                            f"unknown source {ip} ({evidence['count']} msgs, spf {evidence['spf']}, "
                            f"dkim {evidence['dkim']})"
                        ),
                        "evidence": evidence,
                    }
                )
        expected = cfg.get("expectedPolicy") or {}
        newest: dict[str, dict[str, Any]] = {}
        for report in week:
            domain = str((report.get("policy") or {}).get("domain") or "")
            if not domain:
                continue
            current = newest.get(domain)
            end = int(report.get("dateEndUnix") or 0)
            if current is None or end >= int(current.get("dateEndUnix") or 0):
                newest[domain] = report
        for domain, report in newest.items():
            policy = report.get("policy") or {}
            reasons: list[str] = []
            if str(policy.get("p") or "") != str(expected.get("p") or ""):
                reasons.append(f"p={policy.get('p') or 'unset'}")
            if int(policy.get("pct") or 0) != int(expected.get("pct") or 0):
                reasons.append(f"pct={policy.get('pct')}")
            sp = str(policy.get("sp") or "")
            expected_sp = str(expected.get("sp") or "")
            if expected_sp:
                if sp != expected_sp:
                    reasons.append(f"sp={sp or 'unset'}")
            elif sp and sp != str(policy.get("p") or ""):
                reasons.append(f"sp={sp}")
            if reasons:
                detail = ", ".join(reasons)
                findings.append(
                    {
                        "id": "policy_drift",
                        "kind": "policy_drift",
                        "severity": "medium",
                        "fingerprint": f"policy_drift:{domain}:{policy.get('p')}:{policy.get('sp')}:{policy.get('pct')}",
                        "summary": f"policy drift for {domain}: {detail}",
                        "evidence": {"domain": domain, "policy": policy, "expected": expected},
                    }
                )
        bases = _header_bases(reports)
        seen = _load_seen_headers(table)
        seen_set = set(seen)
        fresh: list[str] = []
        for report in week:
            for domain in report.get("headerFrom") or []:
                candidate = str(domain or "").lower().rstrip(".")
                if not candidate or candidate in fresh or candidate in seen_set:
                    continue
                if _is_new_header(candidate, bases, seen_set):
                    findings.append(
                        {
                            "id": "new_header_from_domain",
                            "kind": "new_header_from_domain",
                            "severity": "medium",
                            "fingerprint": f"new_header_from_domain:{candidate}",
                            "summary": f"new header_from domain {candidate}",
                            "evidence": {"domain": candidate},
                        }
                    )
                fresh.append(candidate)
        if fresh or seen:
            combined: list[str] = []
            for domain in seen + fresh:
                if domain not in combined:
                    combined.append(domain)
            _save_seen_headers(table, combined)
        last_google = str(_load_meta(table).get("lastGoogleReceivedAt") or "")
        for report in reports:
            if "google" not in str(report.get("orgName") or "").lower():
                continue
            received = str(report.get("receivedAt") or "")
            if received > last_google:
                last_google = received
        try:
            silence_days = int(cfg.get("silenceDays") or 3)
        except (TypeError, ValueError):
            silence_days = 3
        if last_google:
            try:
                age = moment - board_hk.parse_iso(last_google)
            except ValueError:
                age = timedelta(0)
            if age > timedelta(days=silence_days):
                findings.append(
                    {
                        "id": "reports_silent",
                        "kind": "reports_silent",
                        "severity": "medium",
                        "fingerprint": "reports_silent:google",
                        "summary": (
                            f"no Google DMARC report for {age.days} days (last {_fmt_hkt(last_google)})"
                        ),
                        "evidence": {"lastGoogleReceivedAt": last_google, "silenceDays": silence_days},
                    }
                )
        _note_gaps(table, findings)
    else:
        last_google = str(_load_meta(table).get("lastGoogleReceivedAt") or "")
        findings = []
    last_any = ""
    for report in reports:
        received = str(report.get("receivedAt") or "")
        if received > last_any:
            last_any = received
    if not enabled:
        pass
    day_stats = _stats(day)
    payload = {
        "generatedAt": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "enabled": enabled,
        "windowDays": {"7": _stats(week), "30": _stats(month)},
        "last24h": day_stats,
        "lastReportReceivedAt": last_any,
        "lastGoogleReceivedAt": last_google,
        "orgs": _org_rows(month),
        "sources": sources[:SUMMARY_SOURCE_CAP],
        "sourcesTruncated": len(sources) > SUMMARY_SOURCE_CAP,
        "findings": findings[:SUMMARY_FINDING_CAP],
        "forensicCount": int(_load_meta(table).get("forensicCount") or 0),
        "line": _build_line(day_stats, last_google, findings[:SUMMARY_FINDING_CAP]),
    }
    board_store.put_cache(table, SUMMARY_CACHE, payload, ttl_seconds=SUMMARY_TTL_SECONDS)
    return payload


def refresh(table: Any) -> dict[str, Any]:
    settings = board_store.load_settings(table)
    summary = evaluate(table, settings)
    return {"ok": True, "findings": len(summary.get("findings") or [])}


def read_summary(table: Any) -> dict[str, Any] | None:
    hit = board_store.get_cache(table, SUMMARY_CACHE)
    payload = hit.get("payload") if isinstance(hit, dict) else None
    return payload if isinstance(payload, dict) else None


def summary_for_review(table: Any) -> dict[str, Any]:
    payload = read_summary(table)
    if payload:
        return payload
    return {
        "line": "DMARC (reports received in the last 24 h): no summary yet.",
        "findings": [],
    }


def op_summary(ctx: Any, _args: dict[str, Any]) -> dict[str, Any]:
    cached = read_summary(ctx.table)
    if cached and cached.get("generatedAt"):
        return {**cached, "cached": True}
    summary = evaluate(ctx.table, ctx.settings)
    return {**summary, "cached": False}
