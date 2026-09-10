"""Fetch, robots, pacing and digest helpers for market intelligence."""

from __future__ import annotations

import hashlib
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import board_mail
import board_store
from contract_constants import (
    BOARD_STAFF_CRAWL_MAX_BYTES,
    BOARD_STAFF_CRAWL_RPS,
)
from http_common import _log_event

USER_AGENT = "SiuTinDeiBoardBot/1.0 (+https://siutindei.com/bot)"
_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style|nav|footer)\b[^>]*>.*?</\1>")
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_LONG_DIGITS_RE = re.compile(r"\b\d{7,}\b")
_WS_RE = re.compile(r"\s+")


@dataclass
class FetchResult:
    status: int
    final_url: str
    content_type: str
    text: str
    hash: str


def url_digest(url: str) -> str:
    return hashlib.sha256((url or "").encode("utf-8")).hexdigest()[:16]


def html_to_text(markup: str) -> str:
    cleaned = _SCRIPT_STYLE_RE.sub(" ", markup or "")
    return board_mail.html_to_text(cleaned)


def normalise(text: str) -> str:
    out = _ISO_DATE_RE.sub(" ", text or "")
    out = _TIME_RE.sub(" ", out)
    out = _LONG_DIGITS_RE.sub(" ", out)
    return _WS_RE.sub(" ", out).strip()


def digest(text: str) -> str:
    return (text or "")[:6000]


def _opener() -> Any:
    return urllib.request.build_opener()


def fetch(url: str, *, max_bytes: int = BOARD_STAFF_CRAWL_MAX_BYTES, timeout: int = 10) -> FetchResult:
    req = urllib.request.Request(  # noqa: S310 - caller supplies allow-listed URLs
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain,*/*;q=0.8"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read(max_bytes + 1)
            status = int(getattr(resp, "status", None) or resp.getcode() or 200)
            final = str(getattr(resp, "url", None) or url)
            ctype = str(resp.headers.get("Content-Type") or "")
    except urllib.error.HTTPError as exc:
        raw = exc.read(max_bytes) if exc.fp else b""
        status = int(exc.code)
        final = url
        ctype = str(exc.headers.get("Content-Type") or "") if exc.headers else ""
    except urllib.error.URLError as exc:
        raise TimeoutError(str(exc.reason)[:200]) from exc
    text = raw[:max_bytes].decode("utf-8", errors="replace")
    body_hash = hashlib.sha256(normalise(html_to_text(text) if "html" in ctype.lower() or "<html" in text[:200].lower() else text).encode("utf-8")).hexdigest()
    return FetchResult(status=status, final_url=final, content_type=ctype, text=text, hash=body_hash)


def robots_allows(table: Any, url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    cached = board_store.get_cache(table, f"crawl:robots:{parsed.netloc}")
    parser = urllib.robotparser.RobotFileParser()
    if cached and isinstance(cached.get("payload"), dict) and "body" in cached["payload"]:
        parser.parse(str(cached["payload"]["body"]).splitlines())
    else:
        try:
            result = fetch(robots_url, max_bytes=100_000, timeout=8)
            body = result.text if result.status < 400 else ""
        except Exception:
            body = ""
        board_store.put_cache(table, f"crawl:robots:{parsed.netloc}", {"body": body}, ttl_seconds=86400)
        parser.parse(body.splitlines())
    try:
        return bool(parser.can_fetch(USER_AGENT, url))
    except Exception:
        return True


def pace_host(table: Any, host: str) -> None:
    key = f"crawl:host:{host}"
    hit = board_store.get_cache(table, key)
    last = ""
    if hit and isinstance(hit.get("payload"), dict):
        last = str(hit["payload"].get("lastFetchAt") or "")
    if last:
        try:
            prev = datetime.fromisoformat(last.replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - prev).total_seconds()
            wait = (1.0 / max(1, BOARD_STAFF_CRAWL_RPS)) - elapsed
            if wait > 0:
                time.sleep(min(wait, 2.0))
        except ValueError:
            pass
    board_store.put_cache(
        table,
        key,
        {"lastFetchAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
        ttl_seconds=86400,
    )


def backoff_host(table: Any, host: str, days: int = 7) -> None:
    board_store.put_cache(table, f"crawl:backoff:{host}", {"until": days}, ttl_seconds=days * 86400)
    _log_event("warning", tag="board_crawl_backoff", host=host, days=days)


def host_backed_off(table: Any, host: str) -> bool:
    return bool(board_store.get_cache(table, f"crawl:backoff:{host}"))


def put_digest(watch_id: str, url: str, date_iso: str, text: str) -> str:
    digest_key = f"board/siuTinDei/intel/{watch_id}/{url_digest(url)}/{date_iso}.txt"
    import board_staff

    board_staff._blob_put(digest_key, digest(text).encode("utf-8"))  # noqa: SLF001 - shared blob helper
    return digest_key
