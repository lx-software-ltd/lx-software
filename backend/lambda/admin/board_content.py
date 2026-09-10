"""Content calendar, creatives and publish holds (WP7)."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import board_creative
import board_hk
import board_staff
import board_store
from contract_constants import (
    BOARD_STAFF_CONTENT_CHANNELS,
    BOARD_STAFF_CONTENT_STATUSES,
    BOARD_STAFF_IG_PUBLISHES_PER_DAY,
)
from http_common import _json_response, _log_event

TEMPLATES = board_creative.TEMPLATES
ASSISTED_PREFIX = "assisted_"


class ContentError(ValueError):
    """Invalid content input or state."""


def content_cfg(settings: dict[str, Any]) -> dict[str, Any]:
    return dict(((settings.get("boundaries") or {}).get("content") or {}))


def assisted_channels(settings: dict[str, Any]) -> set[str]:
    raw = content_cfg(settings).get("assistedChannels") or []
    return {str(x) for x in raw}


def iso_week_label(when: datetime | None = None) -> str:
    local = board_hk.as_hkt(when or datetime.now())
    iso = local.isocalendar()
    return f"{iso.year}{iso.week:02d}"


def _utm(channel: str, pillar: str, content_id: str, when: datetime | None = None) -> str:
    return urlencode(
        {
            "utm_source": channel,
            "utm_medium": "social",
            "utm_campaign": f"{pillar}-{iso_week_label(when)}",
            "utm_content": content_id,
        }
    )


def append_utm(link_path: str, channel: str, pillar: str, content_id: str) -> str:
    path = str(link_path or "").strip()
    query = _utm(channel, pillar, content_id)
    if not path:
        return f"https://siutindei.com/?{query}"
    if "://" not in path:
        path = "https://siutindei.com" + (path if path.startswith("/") else "/" + path)
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}{query}"


def presigned_url(key: str, expires: int = 3600) -> str:
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if not bucket:
        return f"https://assets.example/{key}"
    import boto3

    return boto3.client("s3").generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires,
    )


def public_row(doc: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "contentId",
        "status",
        "channel",
        "pillar",
        "slotAt",
        "copyEn",
        "copyZh",
        "hashtags",
        "template",
        "fields",
        "linkPath",
        "linkWithUtm",
        "creativeKeys",
        "holdId",
        "platformPostId",
        "captionHash",
        "performance",
        "createdAt",
        "updatedAt",
    )
    return {k: doc.get(k) for k in keys}


def list_for_api(table: Any, *, status: str | None = None, start: str = "", end: str = "", limit: int = 200) -> list[dict[str, Any]]:
    if status and status not in BOARD_STAFF_CONTENT_STATUSES:
        raise ContentError(f"unknown status {status}")
    rows = board_store.list_content(table, status, limit=max(limit, 400))
    cleaned: list[dict[str, Any]] = []
    for raw in rows:
        row = raw if isinstance(raw, dict) else {}
        slot = str(row.get("slotAt") or "")
        if start and slot < start:
            continue
        if end and slot > end:
            continue
        cleaned.append(public_row(row))
        if len(cleaned) >= limit:
            break
    return cleaned


def _valid_channel(value: str) -> str:
    raw = str(value or "").strip()
    if raw not in BOARD_STAFF_CONTENT_CHANNELS:
        raise ContentError(f"channel must be one of {', '.join(BOARD_STAFF_CONTENT_CHANNELS)}")
    return raw


def upsert_item(table: Any, item: dict[str, Any], *, status: str = "drafted") -> dict[str, Any]:
    now = board_store.now_iso()
    content_id = str(item.get("contentId") or board_store.new_id())
    existing = board_store.get_content(table, content_id) or {}
    channel = _valid_channel(str(item.get("channel") or existing.get("channel") or "facebook"))
    template = str(item.get("template") or existing.get("template") or "spotlight")
    if template not in TEMPLATES:
        template = "spotlight"
    doc = {
        **existing,
        "contentId": content_id,
        "status": status if status in BOARD_STAFF_CONTENT_STATUSES else str(existing.get("status") or "drafted"),
        "channel": channel,
        "pillar": str(item.get("pillar") or existing.get("pillar") or "activity spotlight")[:80],
        "slotAt": str(item.get("slotAt") or existing.get("slotAt") or now),
        "copyEn": str(item.get("copyEn") or existing.get("copyEn") or "")[:2000],
        "copyZh": str(item.get("copyZh") or existing.get("copyZh") or "")[:2000],
        "hashtags": [str(x)[:40] for x in (item.get("hashtags") or existing.get("hashtags") or [])][:20],
        "template": template,
        "fields": item.get("fields") if isinstance(item.get("fields"), dict) else (existing.get("fields") or {}),
        "linkPath": str(item.get("linkPath") or existing.get("linkPath") or "")[:400],
        "createdAt": existing.get("createdAt") or now,
        "updatedAt": now,
    }
    board_store.put_content(table, doc)
    return doc


def render_item(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    channel = str(doc.get("channel") or "facebook")
    fields = dict(doc.get("fields") or {})
    fields.setdefault("title", (doc.get("copyEn") or doc.get("copyZh") or "Siu Tin Dei")[:80])
    fields.setdefault("body", (doc.get("copyZh") if channel.endswith("xiaohongshu") else doc.get("copyEn") or "")[:200])
    fields.setdefault("pillar", doc.get("pillar") or "")
    template = str(doc.get("template") or "spotlight")
    keys: list[str] = []
    cid = str(doc["contentId"])
    if channel == "instagram_story":
        png = board_creative.render_story(template, fields, lang="zh-HK" if doc.get("copyZh") and not doc.get("copyEn") else "en")
        key = f"board/siuTinDei/content/{cid}/0.png"
        board_staff._blob_put(key, png)  # noqa: SLF001
        keys.append(key)
    else:
        en = board_creative.render_card(template, fields, lang="en")
        zh = board_creative.render_card(template, {**fields, "title": fields.get("titleZh") or fields.get("title"), "body": doc.get("copyZh") or fields.get("body")}, lang="zh-HK")
        key0 = f"board/siuTinDei/content/{cid}/0.png"
        key1 = f"board/siuTinDei/content/{cid}/1.png"
        board_staff._blob_put(key0, en)  # noqa: SLF001
        board_staff._blob_put(key1, zh)  # noqa: SLF001
        keys.extend([key0, key1])
    doc["creativeKeys"] = keys
    doc["status"] = "creative"
    doc["updatedAt"] = board_store.now_iso()
    board_store.put_content(table, doc)
    return doc


def caption_for(doc: dict[str, Any], settings: dict[str, Any]) -> str:
    channel = str(doc.get("channel") or "")
    en = str(doc.get("copyEn") or "").strip()
    zh = str(doc.get("copyZh") or "").strip()
    tags = [t if t.startswith("#") else f"#{t}" for t in (doc.get("hashtags") or [])][:20]
    if channel in assisted_channels(settings) and "xiaohongshu" in channel:
        parts = [zh, en]
    elif channel == "instagram":
        parts = [en, zh, " ".join(tags)]
    elif channel == "instagram_story":
        parts = [en or zh]
    else:
        parts = [en, zh]
    return "\n\n".join(p for p in parts if p)


def _plan_context(table: Any, settings: dict[str, Any]) -> str:
    chunks: list[str] = []
    perf: list[dict[str, Any]] = []
    for row in board_store.list_content(table, "published", limit=40):
        if row.get("performance"):
            perf.append(
                {
                    "contentId": row.get("contentId"),
                    "channel": row.get("channel"),
                    "pillar": row.get("pillar"),
                    "performance": row.get("performance"),
                }
            )
    if perf:
        chunks.append("Last week's per-item performance:\n" + json.dumps(perf[:20], default=str)[:1500])
    readout = board_store.get_cache(table, "content:readout")
    if readout and isinstance(readout.get("payload"), dict):
        chunks.append("Last readout:\n" + json.dumps(readout["payload"], default=str)[:800])
    try:
        import board_research

        holidays = board_research.op_edb_holidays(type("Ctx", (), {"table": table, "settings": settings})(), {})
        chunks.append("Upcoming EDB holidays:\n" + json.dumps(holidays, default=str)[:1200])
    except Exception as exc:
        _log_event("info", tag="board_content_holidays_skipped", error=str(exc)[:200])
    try:
        import board_product

        catalog = board_product.op_catalog_health(type("Ctx", (), {"table": table, "settings": settings})(), {})
        chunks.append("Catalog health:\n" + json.dumps(catalog, default=str)[:1500])
    except Exception as exc:
        _log_event("info", tag="board_content_catalog_skipped", error=str(exc)[:200])
    gaps = board_store.get_cache(table, "intel:gaps")
    if gaps and isinstance(gaps.get("payload"), dict):
        chunks.append("Latest market gaps:\n" + json.dumps(gaps["payload"], default=str)[:800])
    return "\n\n".join(chunks)


def plan_week(table: Any, settings: dict[str, Any]) -> dict[str, Any] | None:
    if not board_staff.enabled(settings):
        return None
    today = board_hk.today_hkt()
    from board_triage import find_open_event_task

    if find_open_event_task(table, "duty", f"content-plan:{today}"):
        return None
    cfg = content_cfg(settings)
    context = _plan_context(table, settings)
    brief = (
        "Plan next week's content calendar as JSON {\"items\":[...]} with slotAt, channel, "
        f"pillar, copyEn, copyZh, hashtags, template, fields, linkPath. Pillars: {cfg.get('pillars')}. "
        f"Per week: {cfg.get('perWeek')}. Windows HKT: {cfg.get('windowsHkt')}. "
        "Social week is 21 items (7 facebook, 7 instagram, 7 instagram_story); seo items are extra. "
        "Do not invent photos of children.\n\n"
        + context
    )
    try:
        return board_staff.create_task(
            table,
            settings,
            assignee="content-marketer",
            origin="duty",
            brief=brief[:4000],
            deliverable_type="json",
            sla_hours=12,
            event_ref={"kind": "duty", "id": f"content-plan:{today}"},
            created_by="board_content",
        )
    except board_staff.StaffError as exc:
        _log_event("info", tag="board_content_plan_skipped", error=str(exc)[:200])
        return None


def on_plan_delivered(table: Any, settings: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    text = board_staff.read_deliverable(task, limit=200000) or ""
    parsed: dict[str, Any] = {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                parsed = {}
    items = parsed.get("items") if isinstance(parsed.get("items"), list) else []
    created = 0
    for raw in items:
        if not isinstance(raw, dict):
            continue
        doc = upsert_item(table, raw, status="drafted")
        doc = render_item(table, doc)
        schedule_publish(table, settings, doc)
        created += 1
    return {"items": created}


def schedule_publish(table: Any, settings: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    channel = str(doc.get("channel") or "")
    if channel in assisted_channels(settings) or channel.startswith(ASSISTED_PREFIX):
        doc["status"] = "scheduled"
        doc["updatedAt"] = board_store.now_iso()
        board_store.put_content(table, doc)
        return doc
    import board_tools

    ctx = board_tools.ToolContext(
        table=table,
        settings=settings,
        persona_id="cmo",
        display_name="CMO",
        kind="task",
        actor="persona",
        seat_id="content-marketer",
    )
    outcome = board_tools.execute_call(
        ctx,
        board_tools.REGISTRY["content_publish"],
        {
            "contentId": doc["contentId"],
            "slotAt": doc.get("slotAt") or "",
            "channel": channel,
            "reason": "calendar slot",
        },
    )
    if outcome.status == "held":
        doc["status"] = "scheduled"
        doc["holdId"] = outcome.result.get("holdId")
    elif outcome.status == "ok":
        latest = board_store.get_content(table, str(doc["contentId"])) or doc
        return latest
    else:
        doc["status"] = "scheduled"
        doc["lastError"] = str((outcome.result or {}).get("error") or outcome.status)[:200]
    doc["updatedAt"] = board_store.now_iso()
    board_store.put_content(table, doc)
    return doc


def _ig_count(table: Any) -> int:
    hit = board_store.get_cache(table, f"igpublish:{board_hk.today_hkt()}")
    if hit and isinstance(hit.get("payload"), dict):
        try:
            return int(hit["payload"].get("count") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _bump_ig(table: Any) -> None:
    n = _ig_count(table) + 1
    board_store.put_cache(table, f"igpublish:{board_hk.today_hkt()}", {"count": n}, ttl_seconds=2 * 86400)
    board_store.add_external_usage_day(table, "ig_publish", 1)


def _caption_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _recent_duplicate(table: Any, caption_hash: str) -> str | None:
    cutoff = board_hk.to_iso(board_hk.now_hkt() - timedelta(minutes=10))
    for row in board_store.list_content(table, "published", limit=40):
        if str(row.get("captionHash") or "") == caption_hash and str(row.get("publishedAt") or "") >= cutoff:
            return str(row.get("platformPostId") or "")
    return None


def publish(table: Any, settings: dict[str, Any], content_id: str) -> dict[str, Any]:
    import board_meta

    doc = board_store.get_content(table, content_id)
    if not doc:
        return {"error": "content not found"}
    if doc.get("status") == "vetoed":
        return {"error": "vetoed"}
    if doc.get("platformPostId"):
        return {"ok": True, "platformPostId": doc["platformPostId"], "deduped": True}
    channel = str(doc.get("channel") or "")
    if channel in assisted_channels(settings) or channel.startswith(ASSISTED_PREFIX):
        return {"error": "assisted channel — mark posted from the review page"}
    caption = caption_for(doc, settings)
    digest = _caption_hash(caption)
    existing = _recent_duplicate(table, digest)
    if existing:
        doc["platformPostId"] = existing
        doc["status"] = "published"
        doc["publishedAt"] = board_store.now_iso()
        board_store.put_content(table, doc)
        return {"ok": True, "platformPostId": existing, "deduped": True}
    keys = list(doc.get("creativeKeys") or [])
    if not keys:
        doc = render_item(table, doc)
        keys = list(doc.get("creativeKeys") or [])
    image_url = presigned_url(keys[0]) if keys else ""
    link = append_utm(str(doc.get("linkPath") or ""), channel, str(doc.get("pillar") or "content"), str(doc["contentId"]))
    doc["linkWithUtm"] = link
    try:
        if channel == "facebook":
            pid = board_meta.page_id()
            data = board_meta.graph("POST", f"{pid}/photos", body={"url": image_url, "message": caption + "\n\n" + link})
            post_id = str(data.get("id") or data.get("post_id") or "")
        elif channel == "instagram":
            if _ig_count(table) >= BOARD_STAFF_IG_PUBLISHES_PER_DAY:
                return {"error": "ig daily cap reached"}
            iid = board_meta.ig_user_id()
            created = board_meta.graph("POST", f"{iid}/media", body={"image_url": image_url, "caption": caption})
            creation_id = created.get("id")
            if not creation_id:
                return {"error": "Instagram did not return a creation id"}
            published = board_meta.graph("POST", f"{iid}/media_publish", body={"creation_id": creation_id})
            post_id = str(published.get("id") or "")
            _bump_ig(table)
        elif channel == "instagram_story":
            if _ig_count(table) >= BOARD_STAFF_IG_PUBLISHES_PER_DAY:
                return {"error": "ig daily cap reached"}
            iid = board_meta.ig_user_id()
            created = board_meta.graph(
                "POST", f"{iid}/media", body={"image_url": image_url, "caption": caption, "media_type": "STORIES"}
            )
            creation_id = created.get("id")
            if not creation_id:
                return {"error": "Instagram did not return a creation id"}
            published = board_meta.graph("POST", f"{iid}/media_publish", body={"creation_id": creation_id})
            post_id = str(published.get("id") or "")
            _bump_ig(table)
        else:
            return {"error": f"unsupported publish channel {channel}"}
    except board_meta.MetaError as exc:
        if getattr(exc, "status", None) in {0, None} or "unreachable" in str(exc).lower() or "timeout" in str(exc).lower():
            found = _recent_duplicate(table, digest)
            if found:
                post_id = found
            else:
                return {"error": str(exc)}
        else:
            return {"error": str(exc)}
    if not post_id:
        return {"error": "publish returned no id"}
    doc["platformPostId"] = post_id
    doc["captionHash"] = digest
    doc["status"] = "published"
    doc["publishedAt"] = board_store.now_iso()
    doc["updatedAt"] = doc["publishedAt"]
    board_store.put_content(table, doc)
    return {"ok": True, "platformPostId": post_id, "contentId": doc["contentId"]}


def mark_posted(table: Any, content_id: str) -> dict[str, Any]:
    doc = board_store.get_content(table, content_id)
    if not doc:
        raise ContentError("content not found")
    doc["status"] = "published"
    doc["platformPostId"] = doc.get("platformPostId") or "manual"
    doc["publishedAt"] = board_store.now_iso()
    doc["updatedAt"] = doc["publishedAt"]
    board_store.put_content(table, doc)
    return doc


def owner_put(table: Any, content_id: str, body: dict[str, Any]) -> dict[str, Any]:
    doc = board_store.get_content(table, content_id)
    if not doc:
        raise KeyError("content not found")
    if "copyEn" in body:
        doc["copyEn"] = str(body.get("copyEn") or "")[:2000]
    if "copyZh" in body:
        doc["copyZh"] = str(body.get("copyZh") or "")[:2000]
    if "slotAt" in body:
        doc["slotAt"] = str(body.get("slotAt") or "")
    if "hashtags" in body and isinstance(body.get("hashtags"), list):
        doc["hashtags"] = [str(x)[:40] for x in body["hashtags"]][:20]
    if "status" in body:
        status = str(body.get("status") or "")
        if status not in {"vetoed", "published"}:
            raise ContentError("status may only be set to vetoed or published")
        doc["status"] = status
        if status == "published":
            doc["platformPostId"] = doc.get("platformPostId") or "manual"
            doc["publishedAt"] = board_store.now_iso()
        if status == "vetoed":
            try:
                import board_lessons

                board_lessons.create_from_veto(
                    table,
                    {
                        "summary": f"content {doc.get('contentId')}",
                        "op": "content_publish",
                        "preview": {"channel": doc.get("channel"), "copyEn": doc.get("copyEn")},
                        "vetoReason": str(body.get("reason") or "owner veto"),
                        "seatId": "content-marketer",
                        "classKey": f"publish:{doc.get('channel') or 'content'}",
                        "holdId": doc.get("holdId") or doc.get("contentId"),
                    },
                )
            except Exception as exc:
                _log_event("warning", tag="board_content_lesson_failed", error=str(exc)[:200])
    doc["updatedAt"] = board_store.now_iso()
    board_store.put_content(table, doc)
    return doc


def assisted_due(table: Any, settings: dict[str, Any], *, now_iso: str | None = None) -> list[dict[str, Any]]:
    now = now_iso or board_store.now_iso()
    allowed = assisted_channels(settings)
    out: list[dict[str, Any]] = []
    for row in board_store.list_content(table, "scheduled", limit=200):
        channel = str(row.get("channel") or "")
        if channel not in allowed and not channel.startswith(ASSISTED_PREFIX):
            continue
        if str(row.get("slotAt") or "") <= now:
            out.append(public_row(row))
    return out


def weekly_readout(table: Any, settings: dict[str, Any]) -> dict[str, Any] | None:
    if not board_staff.enabled(settings):
        return None
    today = board_hk.today_hkt()
    from board_triage import find_open_event_task

    if find_open_event_task(table, "duty", f"content-readout:{today}"):
        return None
    brief = (
        "Write last week's content readout in Markdown. End with JSON "
        '{"repeat":[],"adapt":[],"retire":[],"boostContentId":""}. '
        "Pull page and IG insights, post metrics, and web sessions by utm_campaign. "
        "You may boost the best post inside spend caps."
    )
    try:
        return board_staff.create_task(
            table,
            settings,
            assignee="growth-specialist",
            origin="duty",
            brief=brief[:4000],
            deliverable_type="markdown",
            sla_hours=8,
            event_ref={"kind": "duty", "id": f"content-readout:{today}"},
            created_by="board_content",
        )
    except board_staff.StaffError as exc:
        _log_event("info", tag="board_content_readout_skipped", error=str(exc)[:200])
        return None


def write_performance(table: Any, settings: dict[str, Any]) -> dict[str, Any]:
    import board_meta
    import board_tools

    ctx = board_tools.ToolContext(
        table=table,
        settings=settings,
        persona_id="cmo",
        display_name="CMO",
        kind="task",
        actor="persona",
        seat_id="growth-specialist",
    )
    try:
        page = board_meta.op_page_insights(ctx, {})
    except Exception as exc:
        page = {"error": str(exc)[:200]}
        _log_event("warning", tag="board_content_page_insights_failed", error=str(exc)[:200])
    try:
        ig = board_meta.op_ig_insights(ctx, {})
    except Exception as exc:
        ig = {"error": str(exc)[:200]}
        _log_event("warning", tag="board_content_ig_insights_failed", error=str(exc)[:200])
    campaigns: dict[str, Any] = {}
    try:
        import board_web

        wanted: set[str] = set()
        for row in board_store.list_content(table, "published", limit=80):
            when = None
            try:
                if row.get("slotAt"):
                    when = board_hk.parse_iso(str(row.get("slotAt") or ""))
            except ValueError:
                when = None
            wanted.add(f"{str(row.get('pillar') or 'content')}-{iso_week_label(when)}")
        sessions = board_web.op_sessions(ctx, {})
        campaigns = board_web.campaign_sessions(wanted) if wanted else sessions
    except Exception as exc:
        campaigns = {"error": str(exc)[:200]}
        _log_event("warning", tag="board_content_web_sessions_failed", error=str(exc)[:200])
    updated = 0
    best: tuple[float, dict[str, Any]] | None = None
    for row in board_store.list_content(table, "published", limit=80):
        pid = str(row.get("platformPostId") or "")
        if not pid or pid == "manual":
            continue
        channel = str(row.get("channel") or "")
        metrics: dict[str, Any] = {}
        try:
            if channel == "facebook":
                data = board_meta.graph("GET", pid, params={"fields": "insights.metric(post_impressions,post_clicks)"})
                metrics = data.get("insights") or data
            elif channel.startswith("instagram"):
                data = board_meta.graph("GET", f"{pid}/insights", params={"metric": "impressions,reach,saved"})
                metrics = data
        except Exception as exc:
            metrics = {"error": str(exc)[:200]}
        row["performance"] = {"metrics": metrics, "recordedAt": board_store.now_iso()}
        row["updatedAt"] = row["performance"]["recordedAt"]
        board_store.put_content(table, row)
        updated += 1
        score = 0.0
        if isinstance(metrics, dict):
            for key in ("post_impressions", "impressions", "reach"):
                try:
                    score = max(score, float(metrics.get(key) or 0))
                except (TypeError, ValueError):
                    continue
        if best is None or score > best[0]:
            best = (score, row)
    boost = None
    if best and best[1].get("platformPostId") and best[1].get("platformPostId") != "manual":
        try:
            boost = board_tools.execute_call(
                ctx,
                board_tools.REGISTRY["meta_boost_post"],
                {"postId": best[1]["platformPostId"], "reason": "weekly readout best post"},
            )
            boost = {"status": boost.status, "result": boost.result}
        except Exception as exc:
            boost = {"error": str(exc)[:200]}
    return {"page": page, "ig": ig, "web": campaigns, "updated": updated, "boost": boost}


def on_readout_delivered(table: Any, settings: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    perf = write_performance(table, settings)
    text = board_staff.read_deliverable(task) or ""
    board_store.put_cache(table, "content:readout", {"taskId": task.get("taskId"), "text": text[:8000], **perf}, ttl_seconds=21 * 86400)
    return perf


def handle_plan(event: dict[str, Any] | None = None) -> dict[str, Any]:
    if not board_store.event_targets_this_board(event):
        return {"ok": True, "skipped": "other board"}
    if not board_staff.env_enabled():
        return {"ok": True, "skipped": "env"}
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    task = plan_week(table, settings)
    return {"ok": True, "taskId": (task or {}).get("taskId")}


def handle_readout(event: dict[str, Any] | None = None) -> dict[str, Any]:
    if not board_store.event_targets_this_board(event):
        return {"ok": True, "skipped": "other board"}
    if not board_staff.env_enabled():
        return {"ok": True, "skipped": "env"}
    table = board_store.records_table()
    settings = board_store.load_settings(table)
    task = weekly_readout(table, settings)
    return {"ok": True, "taskId": (task or {}).get("taskId")}


def op_list(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    try:
        rows = list_for_api(ctx.table, status=str(args.get("status") or "") or None, limit=min(int(args.get("limit") or 40), 80))
    except ContentError as exc:
        return {"error": str(exc)}
    return {"items": rows}


def op_get(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    row = board_store.get_content(ctx.table, str(args.get("contentId") or args.get("id") or ""))
    if not row:
        return {"error": "content not found"}
    return {"item": public_row(row)}


def op_publish(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    return publish(ctx.table, ctx.settings, str(args.get("contentId") or args.get("id") or ""))
