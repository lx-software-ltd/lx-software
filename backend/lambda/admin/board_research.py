"""Executive Board ``research`` tool: Brave Search with a 24-hour cache.

Falls back to an OpenRouter ``:online`` model when no Brave key is set but
OpenRouter is. Results are stored under ``BOARD#…#cache`` so eight personas
in a meeting do not hit the search API eight times for the same query.

Plan: docs/architecture/executive-board-tools-plan.md §4 ``research``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from admin_runtime import _get_secretsmanager_client
from contract_constants import (
    BOARD_RESEARCH_CACHE_TTL_HOURS,
    BOARD_RESEARCH_MAX_RESULTS,
    BOARD_RESEARCH_QUERY_MAX_LEN,
)
from http_common import _log_event
from openrouter_client import OpenRouterError, read_secret_string

import board_budget
import board_deadline
import board_store

BRAVE_ORIGIN = "https://api.search.brave.com"
HTTP_TIMEOUT_SECONDS = 10
HK_DISTRICTS = (
    "central and western",
    "wan chai",
    "eastern",
    "southern",
    "yau tsim mong",
    "sham shui po",
    "kowloon city",
    "wong tai sin",
    "kwun tong",
    "kwai tsing",
    "tsuen wan",
    "tuen mun",
    "yuen long",
    "north",
    "tai po",
    "sha tin",
    "sai kung",
    "islands",
)

_key_cache: str | None = None
_key_checked = False


class ResearchError(RuntimeError):
    """User-facing failure while searching the web."""


def search_configured() -> bool:
    return bool(
        (os.environ.get("SEARCH_API_KEY") or "").strip()
        or (os.environ.get("SEARCH_API_KEY_SECRET_ARN") or "").strip()
        or (os.environ.get("OPENROUTER_API_KEY") or "").strip()
        or (os.environ.get("OPENROUTER_API_KEY_SECRET_ARN") or "").strip()
    )


def reset_key_cache_for_tests() -> None:
    global _key_cache, _key_checked
    _key_cache, _key_checked = None, False


def _brave_key() -> str:
    global _key_cache, _key_checked
    if _key_checked and _key_cache is not None:
        return _key_cache
    direct = (os.environ.get("SEARCH_API_KEY") or "").strip()
    if direct:
        _key_cache, _key_checked = direct, True
        return direct
    arn = (os.environ.get("SEARCH_API_KEY_SECRET_ARN") or "").strip()
    if not arn:
        _key_cache, _key_checked = "", True
        return ""
    try:
        _key_cache = read_secret_string(_get_secretsmanager_client(), arn, what="search API key")
    except OpenRouterError as exc:
        raise ResearchError(str(exc)) from exc
    _key_checked = True
    return _key_cache


def _clamp_query(raw: Any) -> str:
    text = " ".join(str(raw or "").split())
    if not text:
        raise ResearchError("query is required")
    return text[:BOARD_RESEARCH_QUERY_MAX_LEN]


def _cache_name(kind: str, query: str) -> str:
    digest = hashlib.sha256(f"{kind}\n{query.lower()}".encode("utf-8")).hexdigest()[:24]
    return f"research:{kind}:{digest}"


def _from_cache(table: Any, name: str) -> dict[str, Any] | None:
    hit = board_store.get_cache(table, name)
    if not hit:
        return None
    payload = hit.get("payload")
    if not isinstance(payload, dict):
        return None
    return {**payload, "cached": True, "fetchedAt": hit.get("fetchedAt")}


def _store(table: Any, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    doc = board_store.put_cache(
        table,
        name,
        payload,
        ttl_seconds=BOARD_RESEARCH_CACHE_TTL_HOURS * 3600,
    )
    return {**payload, "cached": False, "fetchedAt": doc.get("fetchedAt")}


def _brave_search(query: str, *, count: int) -> list[dict[str, Any]]:
    key = _brave_key()
    if not key:
        raise ResearchError("Brave Search is not configured")
    params = urlparse.urlencode({"q": query, "count": str(count), "country": "HK", "search_lang": "en"})
    req = urlrequest.Request(  # noqa: S310 - fixed Brave origin
        f"{BRAVE_ORIGIN}/res/v1/web/search?{params}",
        method="GET",
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": key,
            "User-Agent": "lxsoftware-admin-board",
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=board_deadline.remaining(HTTP_TIMEOUT_SECONDS)) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
    except urlerror.HTTPError as exc:
        raise ResearchError(f"Brave Search returned status {exc.code}") from exc
    except urlerror.URLError as exc:
        raise ResearchError(f"Brave Search transport error: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise ResearchError("Brave Search returned invalid JSON") from exc
    web = body.get("web") if isinstance(body, dict) else None
    items = (web.get("results") if isinstance(web, dict) else None) or []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "title": str(item.get("title") or "")[:200],
                "url": str(item.get("url") or "")[:500],
                "snippet": re.sub(r"<[^>]+>", "", str(item.get("description") or ""))[:400],
            }
        )
        if len(out) >= count:
            break
    return out


def _openrouter_online(table: Any, query: str, *, count: int) -> list[dict[str, Any]]:
    """Last-resort fallback when no Brave key is set; billed against the daily board budget."""
    completion = board_budget.board_completion(
        table=table,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a research assistant. Answer with a JSON array of at most "
                    f"{count} objects {{title, url, snippet}} for public web pages that "
                    "answer the query. No extra text."
                ),
            },
            {"role": "user", "content": query},
        ],
        model="openrouter/auto:online",
        max_tokens=1200,
        temperature=0.1,
        timeout=HTTP_TIMEOUT_SECONDS + 15,
        tag="board_research_online",
    )
    text = (completion.text or "").strip()
    try:
        start, end = text.find("["), text.rfind("]")
        parsed = json.loads(text[start : end + 1] if start >= 0 and end > start else text)
    except json.JSONDecodeError as exc:
        raise ResearchError("OpenRouter online search returned unparseable results") from exc
    if not isinstance(parsed, list):
        raise ResearchError("OpenRouter online search returned no results list")
    out: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "title": str(item.get("title") or "")[:200],
                "url": str(item.get("url") or "")[:500],
                "snippet": str(item.get("snippet") or "")[:400],
            }
        )
        if len(out) >= count:
            break
    return out


def _live_search(table: Any, query: str, *, count: int) -> tuple[list[dict[str, Any]], str]:
    if _brave_key():
        results = _brave_search(query, count=count), "brave"
    elif (os.environ.get("OPENROUTER_API_KEY") or "").strip() or (
        os.environ.get("OPENROUTER_API_KEY_SECRET_ARN") or ""
    ).strip():
        results = _openrouter_online(table, query, count=count), "openrouter_online"
    else:
        results = None
    if results is not None:
        # Cache misses are the only calls that cost quota; the owner sees the count in settings.
        try:
            board_store.add_external_usage_day(table, "searchCalls")
        except Exception as exc:  # pragma: no cover - accounting must not break the search
            _log_event("warning", tag="board_research_usage_failed", error=str(exc)[:200])
        return results
    raise ResearchError(
        "Web search is not configured. Put a Brave Search key in "
        "lxsoftware-admin-siutindei-board-search-api-key or rely on the existing OpenRouter key."
    )


def _run_search(ctx: Any, query: str, *, kind: str, count: int | None = None) -> dict[str, Any]:
    q = _clamp_query(query)
    limit = max(1, min(int(count or BOARD_RESEARCH_MAX_RESULTS), BOARD_RESEARCH_MAX_RESULTS))
    name = _cache_name(kind, q)
    cached = _from_cache(ctx.table, name)
    if cached:
        return cached
    results, source = _live_search(ctx.table, q, count=limit)
    payload = {"kind": kind, "query": q, "source": source, "results": results}
    stored = _store(ctx.table, name, payload)
    _log_event("info", tag="board_research", kind=kind, source=source, n=len(results))
    return stored


def op_search(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    return _run_search(ctx, args.get("query"), kind="web", count=args.get("limit"))


def op_hk_news(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    topic = _clamp_query(args.get("query") or "Hong Kong children's activities market")
    return _run_search(
        ctx,
        f"{topic} Hong Kong (site:news.gov.hk OR site:scmp.com OR site:thestandard.com.hk)",
        kind="hk_news",
        count=args.get("limit"),
    )


def op_edb_holidays(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    year = str(args.get("year") or "").strip() or "this school year"
    return _run_search(
        ctx,
        f"Hong Kong Education Bureau school holiday calendar {year} site:edb.gov.hk",
        kind="edb",
        count=args.get("limit"),
    )


def op_venues(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    district = " ".join(str(args.get("district") or "").lower().split())
    if district and district not in HK_DISTRICTS:
        raise ResearchError(f"Unknown Hong Kong district '{district}'. Use one of: {', '.join(HK_DISTRICTS)}.")
    kind_of = str(args.get("kind") or "children's activity venue").strip()[:80]
    where = f" in {district}" if district else " Hong Kong"
    return _run_search(ctx, f"{kind_of} listing{where}", kind="venues", count=args.get("limit"))
