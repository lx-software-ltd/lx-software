"""Daily crawl, public store snapshots, weekly market brief."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import board_actions
import board_async
import board_crawl
import board_hk
import board_staff
import board_store
import board_watch
from contract_constants import BOARD_STAFF_CRAWL_MAX_PAGES_PER_RUN
from http_common import _log_event

PAGES_PER_INVOKE = 40
EMPTY_BODY_MIN_CHARS = 80


def _host(url: str) -> str:
    return (urlparse(url).netloc or "").lower()


def _change_kind(url: str) -> str:
    lower = url.lower()
    if "pric" in lower or "fee" in lower or "tuition" in lower:
        return "pricing"
    if "feature" in lower or "product" in lower:
        return "features"
    if "categor" in lower or "class" in lower or "activit" in lower:
        return "categories"
    return "other"


def _desk_summary(table: Any, settings: dict[str, Any], before: str, after: str) -> str:
    try:
        import board_budget

        completion = board_budget.board_completion(
            table=table,
            messages=[
                {
                    "role": "system",
                    "content": "One line (≤200 chars) describing what changed. JSON: {\"summary\":\"…\"}",
                },
                {"role": "user", "content": json.dumps({"before": before[:1500], "after": after[:1500]})},
            ],
            model=board_budget.model_for("standup", settings),
            timeout=12,
            json_mode=True,
            temperature=0,
            max_tokens=80,
            tag="board_intel_change",
        )
        parsed = json.loads(completion.text or "{}")
        text = str(parsed.get("summary") or "").strip()
        if text:
            return text[:200]
    except Exception as exc:
        _log_event("warning", tag="board_intel_summary_failed", error=str(exc)[:200])
    return "Page content changed."


def daily_crawl(table: Any, settings: dict[str, Any], cursor: dict[str, Any] | None = None) -> dict[str, Any]:
    if not board_staff.enabled(settings):
        return {"ok": True, "skipped": "disabled"}
    watches = board_watch.list_watchlist(table)
    jobs: list[tuple[dict[str, Any], str]] = []
    for watch in watches:
        if watch.get("kind") == "candidate":
            continue
        for url in watch.get("urls") or []:
            jobs.append((watch, str(url)))
    start = int((cursor or {}).get("offset") or 0)
    pages_run = 0
    changes = 0
    today = board_hk.today_hkt()
    for watch, url in jobs[start:]:
        if pages_run >= PAGES_PER_INVOKE:
            board_async.invoke_async(
                {"internal": "board_intel_crawl", "boardKey": "siuTinDei", "cursor": {"offset": start + pages_run}},
                fallback=lambda payload: daily_crawl(table, settings, payload.get("cursor")),
            )
            break
        if pages_run + start >= BOARD_STAFF_CRAWL_MAX_PAGES_PER_RUN:
            break
        host = _host(url)
        if not host or board_crawl.host_backed_off(table, host):
            pages_run += 1
            continue
        if not board_crawl.robots_allows(table, url):
            pages_run += 1
            continue
        board_crawl.pace_host(table, host)
        digest_id = board_crawl.url_digest(url)
        page = board_store.get_watch_page(table, str(watch["watchId"]), digest_id) or {}
        try:
            result = board_crawl.fetch(url)
        except Exception as exc:
            _log_event("warning", tag="board_intel_fetch_failed", url=url[:120], error=str(exc)[:200])
            pages_run += 1
            continue
        if result.status in (403, 429):
            board_crawl.backoff_host(table, host)
            pages_run += 1
            continue
        text = board_crawl.html_to_text(result.text) if "html" in (result.content_type or "").lower() or "<html" in result.text[:200].lower() else result.text
        empty = len(text.strip()) < EMPTY_BODY_MIN_CHARS
        empties = int(page.get("emptyFetches") or 0) + (1 if empty else 0)
        page_doc = {
            "url": url,
            "lastHash": result.hash,
            "lastFetchedAt": board_store.now_iso(),
            "lastDigestKey": page.get("lastDigestKey") or "",
            "emptyFetches": empties,
            "emptyBody": empties >= 2,
            "status": result.status,
        }
        if page.get("emptyBody") or empties >= 2:
            page_doc["emptyBody"] = True
            board_store.put_watch_page(table, str(watch["watchId"]), digest_id, page_doc)
            pages_run += 1
            continue
        prev_key = str(page.get("lastDigestKey") or "")
        before = ""
        if prev_key:
            try:
                before = board_staff._blob_get(prev_key).decode("utf-8", errors="replace")  # noqa: SLF001
            except Exception:
                before = ""
        key = board_crawl.put_digest(str(watch["watchId"]), url, today, text)
        page_doc["lastDigestKey"] = key
        prev_hash = str(page.get("lastHash") or "")
        if prev_hash and prev_hash != result.hash:
            after = board_crawl.digest(text)
            board_store.put_change(
                table,
                {
                    "changeId": board_store.new_id(),
                    "watchId": watch.get("watchId"),
                    "url": url,
                    "kind": _change_kind(url),
                    "beforeKey": prev_key,
                    "afterKey": key,
                    "beforeDigest": board_crawl.digest(before),
                    "afterDigest": after,
                    "summary": _desk_summary(table, settings, before, text),
                },
            )
            changes += 1
        board_store.put_watch_page(table, str(watch["watchId"]), digest_id, page_doc)
        pages_run += 1
    return {"ok": True, "pages": pages_run, "changes": changes, "offset": start}


def public_store_data(app_id: str, platform: str) -> dict[str, Any]:
    if platform == "ios":
        url = f"https://itunes.apple.com/lookup?id={app_id}&country=hk"
        lookup = board_crawl.fetch(url, timeout=10)
        rss = board_crawl.fetch(
            f"https://itunes.apple.com/hk/rss/customerreviews/id={app_id}/sortBy=mostRecent/json",
            timeout=10,
        )
        reviews: list[str] = []
        if rss.status == 404:
            _log_event("info", tag="board_intel_appstore_rss_missing", appId=app_id)
        else:
            try:
                payload = json.loads(rss.text or "{}")
                for entry in (payload.get("feed") or {}).get("entry") or []:
                    title = str((entry.get("title") or {}).get("label") or "")
                    body = str(((entry.get("content") or {}).get("label") or ""))
                    if title or body:
                        reviews.append(f"{title}: {body}"[:400])
                    if len(reviews) >= 40:
                        break
            except Exception:
                reviews = []
        return {"platform": "ios", "lookup": lookup.text[:4000], "reviews": reviews, "status": lookup.status}
    play = board_crawl.fetch(f"https://play.google.com/store/apps/details?id={app_id}&hl=en&gl=hk", timeout=10)
    return {"platform": "android", "text": board_crawl.html_to_text(play.text)[:4000], "status": play.status}


def _changes_this_week(table: Any) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [c for c in board_store.list_changes(table, limit=200) if str(c.get("createdAt") or "") >= cutoff]


def weekly_brief(table: Any, settings: dict[str, Any]) -> dict[str, Any] | None:
    if not board_staff.enabled(settings):
        return None
    changes = _changes_this_week(table)
    reviews: list[str] = []
    for watch in board_watch.list_watchlist(table):
        apps = watch.get("appIds") or {}
        ios = str(apps.get("ios") or "")
        if ios:
            try:
                reviews.extend(public_store_data(ios, "ios").get("reviews") or [])
            except Exception as exc:
                _log_event("warning", tag="board_intel_reviews_failed", error=str(exc)[:200])
        if len(reviews) >= 40:
            break
    catalog = {}
    try:
        import board_product

        catalog = board_product.op_catalog_health(
            type("Ctx", (), {"table": table, "settings": settings})(),
            {},
        )
    except Exception as exc:
        _log_event("warning", tag="board_intel_catalog_failed", error=str(exc)[:200])
    holidays = {}
    try:
        import board_research

        holidays = board_research.op_edb_holidays(
            type("Ctx", (), {"table": table, "settings": settings})(),
            {},
        )
    except Exception:
        holidays = {}
    brief = (
        "Write this week's market brief as Markdown ending with a fenced JSON block "
        '```json {"gaps":[{"category","district","competitorCount"}],'
        '"ideas":[{"title","why","effort"}],"prospects":[{"name","type","url"}]}```.\n\n'
        f"Changes this week ({len(changes)}):\n"
        + "\n".join(f"- {c.get('summary')} ({c.get('url')})" for c in changes[:40])
        + "\n\nCompetitor reviews:\n"
        + "\n".join(f"- {r}" for r in reviews[:40])
        + "\n\nCatalog health:\n"
        + json.dumps(catalog, default=str)[:3000]
        + "\n\nSeasonal calendar:\n"
        + json.dumps(holidays, default=str)[:1500]
    )
    try:
        return board_staff.create_task(
            table,
            settings,
            assignee="market-analyst",
            origin="duty",
            brief=brief[:4000],
            deliverable_type="markdown",
            sla_hours=24,
            event_ref={"kind": "duty", "id": f"market-brief:{board_hk.today_hkt()}"},
            created_by="board_intel",
        )
    except board_staff.StaffError as exc:
        _log_event("info", tag="board_intel_brief_skipped", error=str(exc)[:200])
        return None


_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


def on_brief_delivered(table: Any, task: dict[str, Any]) -> dict[str, Any]:
    text = board_staff.read_deliverable(task) or str(task.get("summary") or "")
    match = _JSON_BLOCK.search(text)
    parsed: dict[str, Any] = {}
    if match:
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            parsed = {}
    gaps = parsed.get("gaps") if isinstance(parsed.get("gaps"), list) else []
    ideas = parsed.get("ideas") if isinstance(parsed.get("ideas"), list) else []
    prospects = parsed.get("prospects") if isinstance(parsed.get("prospects"), list) else []
    board_store.put_cache(table, "intel:gaps", {"gaps": gaps}, ttl_seconds=14 * 86400)
    if prospects:
        try:
            import board_prospects

            for row in prospects:
                if isinstance(row, dict):
                    board_prospects.upsert_prospect(table, {**row, "source": "intel"})
        except ImportError:
            board_store.put_cache(table, "intel:prospects", {"prospects": prospects}, ttl_seconds=14 * 86400)
    created = 0
    open_actions = [a for a in board_store.list_actions(table) if a.get("status") == "open"]
    for idea in ideas:
        if not isinstance(idea, dict):
            continue
        title = str(idea.get("title") or "").strip()
        if not title or board_actions.find_similar_open_action(title, open_actions):
            continue
        action = {
            "actionId": board_store.new_id(),
            "title": title[:200],
            "detail": str(idea.get("why") or "")[:800],
            "persona": "cpo",
            "priority": "later",
            "status": "open",
            "createdAt": board_store.now_iso(),
        }
        board_store.put_action(table, action)
        open_actions.append(action)
        created += 1
    return {"gaps": len(gaps), "ideas": created, "prospects": len(prospects)}


def handle_crawl(event: dict[str, Any]) -> dict[str, Any]:
    if not board_store.event_targets_this_board(event):
        return {"ok": True, "skipped": "other_board"}
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    return daily_crawl(table, settings, event.get("cursor") if isinstance(event.get("cursor"), dict) else None)


def handle_weekly(event: dict[str, Any]) -> dict[str, Any]:
    if not board_store.event_targets_this_board(event):
        return {"ok": True, "skipped": "other_board"}
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    if not board_staff.enabled(settings):
        return {"ok": True, "skipped": "disabled"}
    discovered = board_watch.discover(table, settings)
    task = weekly_brief(table, settings)
    return {"ok": True, "discover": discovered, "taskId": (task or {}).get("taskId")}


def _digest_text(key: str) -> str:
    if not key:
        return ""
    try:
        return board_staff._blob_get(str(key)).decode("utf-8", errors="replace")  # noqa: SLF001
    except Exception:
        return ""


def public_change(doc: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in doc.items() if k not in ("pk", "sk", "gsi1pk", "gsi1sk", "expiresAt")}
    if not out.get("beforeDigest"):
        out["beforeDigest"] = _digest_text(str(doc.get("beforeKey") or ""))
    if not out.get("afterDigest"):
        out["afterDigest"] = _digest_text(str(doc.get("afterKey") or ""))
    return out


def public_watch(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    watch = board_watch.public_watch(doc)
    pages = []
    for page in board_store.list_watch_pages(table, str(doc.get("watchId") or "")):
        pages.append(
            {
                "url": page.get("url"),
                "emptyBody": bool(page.get("emptyBody")),
                "lastFetchedAt": page.get("lastFetchedAt"),
                "status": page.get("status"),
            }
        )
    watch["pages"] = pages
    return watch


def latest_brief(table: Any) -> dict[str, Any] | None:
    prefix = "market-brief:"
    newest: dict[str, Any] | None = None
    for status in ("delivered", "review", "running", "queued"):
        for row in board_store.list_tasks(table, status, limit=80):
            ref = row.get("eventRef") or {}
            if ref.get("kind") != "duty" or not str(ref.get("id") or "").startswith(prefix):
                continue
            if newest is None or str(row.get("createdAt") or "") > str(newest.get("createdAt") or ""):
                newest = row
    if not newest:
        return None
    return {
        "taskId": newest.get("taskId"),
        "status": newest.get("status"),
        "summary": newest.get("summary"),
        "createdAt": newest.get("createdAt"),
        "eventRef": newest.get("eventRef"),
    }


def list_changes(table: Any, days: int = 7) -> list[dict[str, Any]]:
    days = max(1, min(30, int(days)))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [public_change(c) for c in board_store.list_changes(table, limit=200) if str(c.get("createdAt") or "") >= cutoff]


def op_list_watchlist(ctx: Any, _args: dict[str, Any]) -> dict[str, Any]:
    return {"watches": [public_watch(ctx.table, w) for w in board_store.list_watches(ctx.table)]}


def op_get_changes(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    return {"changes": list_changes(ctx.table, int(args.get("days") or 7))}


def _fetch_host_allowed(table: Any, url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    for watch in board_store.list_watches(table):
        for raw in list(watch.get("urls") or []) + [watch.get("url"), watch.get("homepage"), watch.get("domain")]:
            text = str(raw or "").strip()
            if not text:
                continue
            other = urlparse(text if "://" in text else f"https://{text}").hostname or text
            if host == other.lower() or host == text.lower():
                return True
    return False


def op_fetch_page(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url") or "").strip()
    if not _fetch_host_allowed(ctx.table, url):
        return {"error": "host is not on the watchlist"}
    if not board_crawl.robots_allows(ctx.table, url):
        return {"error": "robots.txt disallows this URL"}
    host = _host(url)
    if board_crawl.host_backed_off(ctx.table, host):
        return {"error": "host is in backoff"}
    board_crawl.pace_host(ctx.table, host)
    result = board_crawl.fetch(url)
    text = board_crawl.html_to_text(result.text)
    return {"status": result.status, "finalUrl": result.final_url, "text": text[:4000], "hash": result.hash}


def op_competitor_reviews(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    watch = board_store.get_watch(ctx.table, str(args.get("watchId") or ""))
    if not watch:
        raise ValueError("Watch not found")
    apps = watch.get("appIds") or {}
    out: dict[str, Any] = {}
    if apps.get("ios"):
        out["ios"] = public_store_data(str(apps["ios"]), "ios")
    if apps.get("android"):
        out["android"] = public_store_data(str(apps["android"]), "android")
    return out


def op_search_rank(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    import board_research

    return board_research.op_search(ctx, {"query": args.get("query"), "limit": 8})
