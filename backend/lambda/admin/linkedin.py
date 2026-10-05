"""HTTP and scheduled workers for the LX Software LinkedIn tab.

Drafting and the assisted share box live here. Posting through the LinkedIn
API waits on ``LINKEDIN_PUBLISH_ENABLED`` and is not implemented yet: the
due worker only reminds the owner to post by hand.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import parse_qs

import board_async
import board_store
import linkedin_draft
import linkedin_store
from http_common import _audit, _json_response, _log_event, _parse_json_body
from linkedin_store import LinkedInError
from openrouter_client import OpenRouterError

PREFIX = "/lx-software/linkedin"

_sesv2: Any = None


def _ses_client() -> Any:
    global _sesv2
    if _sesv2 is None:
        import boto3

        _sesv2 = boto3.client("sesv2")
    return _sesv2


def reset_ses_client_for_tests() -> None:
    global _sesv2
    _sesv2 = None


def notify_from_address() -> str:
    domain = (os.environ.get("INBOUND_MAIL_DOMAIN") or "inbound.lx-software.com").strip()
    return f"linkedin@{domain}"


def send_notice(to_address: str, subject: str, body: str) -> bool:
    address = str(to_address or "").strip()
    if not address:
        return False
    try:
        _ses_client().send_email(
            FromEmailAddress=notify_from_address(),
            Destination={"ToAddresses": [address]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                }
            },
        )
    except Exception as exc:  # noqa: BLE001 — a missed note must not fail the job
        _log_event("warning", tag="linkedin_notice_failed", error=str(exc)[:300])
        return False
    _log_event("info", tag="linkedin_notice_sent", subject=subject[:80])
    return True


def _admin_origin() -> str:
    return (os.environ.get("ADMIN_WEB_ORIGIN") or "https://admin.lx-software.com").rstrip("/")


def _require_enabled():
    if linkedin_store.feature_enabled():
        return None
    return _json_response(403, {"message": "LinkedIn is turned off.", "reason": "linkedin_disabled"})


def _table():
    return board_store.records_table()


def _parts(path: str) -> list[str]:
    rest = path[len(PREFIX) :] if path.startswith(PREFIX) else path
    return [part for part in rest.split("/") if part]


def handle_http(event: dict[str, Any], method: str, path: str, user_sub: str | None) -> dict[str, Any]:
    parts = _parts(path)
    if not parts and method == "GET":
        return _json_response(200, linkedin_store.overview(_table()))
    if parts == ["settings"] and method == "PUT":
        blocked = _require_enabled()
        if blocked:
            return blocked
        try:
            settings = linkedin_store.save_settings(_table(), _parse_json_body(event))
        except LinkedInError as exc:
            return _json_response(400, {"message": str(exc)})
        _audit(user_sub, "LINKEDIN_SETTINGS", "state", event)
        return _json_response(200, {"settings": settings})
    if parts == ["posts"] and method == "GET":
        status = (parse_qs(event.get("rawQueryString") or "").get("status") or [""])[0]
        rows = linkedin_store.list_posts(_table(), status=status or None)
        return _json_response(200, {"items": [linkedin_store.public_post(row) for row in rows]})
    if parts == ["posts"] and method == "POST":
        blocked = _require_enabled()
        if blocked:
            return blocked
        try:
            doc = linkedin_store.create_post(_table(), _parse_json_body(event))
        except LinkedInError as exc:
            return _json_response(400, {"message": str(exc)})
        _audit(user_sub, "LINKEDIN_POST_CREATE", str(doc["postId"]), event)
        return _json_response(201, {"item": linkedin_store.public_post(doc)})
    if len(parts) == 2 and parts[0] == "posts" and method == "PUT":
        blocked = _require_enabled()
        if blocked:
            return blocked
        try:
            doc = linkedin_store.update_post(_table(), parts[1], _parse_json_body(event))
        except LinkedInError as exc:
            status = 404 if str(exc) == "post not found" else 400
            return _json_response(status, {"message": str(exc)})
        _audit(user_sub, "LINKEDIN_POST_UPDATE", parts[1], event)
        return _json_response(200, {"item": linkedin_store.public_post(doc)})
    if len(parts) == 3 and parts[0] == "posts" and method == "POST":
        return _post_action(event, parts[1], parts[2], user_sub)
    if parts == ["ideas"] and method == "GET":
        return _json_response(200, {"items": linkedin_store.list_ideas(_table())})
    if parts == ["ideas"] and method == "POST":
        blocked = _require_enabled()
        if blocked:
            return blocked
        body = _parse_json_body(event)
        try:
            doc = linkedin_store.create_idea(
                _table(),
                str(body.get("text") or ""),
                str(body.get("pillar") or ""),
            )
        except LinkedInError as exc:
            return _json_response(400, {"message": str(exc)})
        _audit(user_sub, "LINKEDIN_IDEA_CREATE", str(doc["ideaId"]), event)
        return _json_response(201, {"item": doc})
    if len(parts) == 2 and parts[0] == "ideas" and method == "DELETE":
        blocked = _require_enabled()
        if blocked:
            return blocked
        linkedin_store.delete_idea(_table(), parts[1])
        _audit(user_sub, "LINKEDIN_IDEA_DELETE", parts[1], event)
        return _json_response(200, {"deleted": parts[1]})
    if parts == ["generate"] and method == "POST":
        return _generate(event, user_sub)
    if len(parts) == 2 and parts[0] == "jobs" and method == "GET":
        doc = linkedin_store.get_job(_table(), parts[1])
        if not doc:
            return _json_response(404, {"message": "Job not found"})
        return _json_response(200, {"job": _public_job(doc)})
    return _json_response(404, {"message": "Not found"})


def _post_action(event: dict[str, Any], post_id: str, action: str, user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    table = _table()
    try:
        if action == "approve":
            doc = linkedin_store.approve_post(table, post_id, user_sub or "")
        elif action == "unapprove":
            doc = linkedin_store.unapprove_post(table, post_id)
        elif action == "archive":
            doc = linkedin_store.archive_post(table, post_id)
        elif action == "mark-posted":
            body = _parse_json_body(event)
            doc = linkedin_store.mark_posted(table, post_id, str(body.get("url") or ""))
        elif action == "regenerate":
            return _regenerate(event, table, post_id, user_sub)
        else:
            return _json_response(404, {"message": "Not found"})
    except LinkedInError as exc:
        status = 404 if str(exc) == "post not found" else 400
        return _json_response(status, {"message": str(exc)})
    _audit(user_sub, f"LINKEDIN_POST_{action.upper()}", post_id, event)
    return _json_response(200, {"item": linkedin_store.public_post(doc)})


def _generate(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    body = _parse_json_body(event)
    payload = {
        "count": body.get("count"),
        "pillar": str(body.get("pillar") or ""),
        "ideaIds": body.get("ideaIds") if isinstance(body.get("ideaIds"), list) else [],
        "postId": "",
    }
    return _queue(event, payload, user_sub)


def _regenerate(event: dict[str, Any], table: Any, post_id: str, user_sub: str | None) -> dict[str, Any]:
    doc = linkedin_store.get_post(table, post_id)
    if not doc:
        return _json_response(404, {"message": "post not found"})
    payload = {
        "count": 1,
        "pillar": str(doc.get("pillar") or ""),
        "ideaIds": [doc["ideaId"]] if doc.get("ideaId") else [],
        "postId": post_id,
    }
    return _queue(event, payload, user_sub)


def _queue(event: dict[str, Any], payload: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    table = _table()
    job = linkedin_store.new_job(table, "generate", payload)
    accepted = board_async.try_invoke_event(
        {"internal": "linkedin_generate", "jobId": job["jobId"]}
    )
    if not accepted:
        job["status"] = "failed"
        job["error"] = "Could not queue generation."
        linkedin_store.put_job(table, job)
        return _json_response(503, {"message": job["error"], "job": _public_job(job)})
    _audit(user_sub, "LINKEDIN_GENERATE", job["jobId"], event)
    return _json_response(202, {"job": _public_job(job)})


def _public_job(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "jobId": doc.get("jobId"),
        "status": doc.get("status"),
        "postIds": list(doc.get("postIds") or []),
        "error": doc.get("error") or "",
    }


def _fail_job(table: Any, job: dict[str, Any] | None, message: str) -> None:
    if not job:
        return
    job["status"] = "failed"
    job["error"] = message
    linkedin_store.put_job(table, job)


def handle_generate(event: dict[str, Any] | None = None) -> dict[str, Any]:
    event = event or {}
    if not linkedin_store.feature_enabled():
        return {"skipped": "disabled"}
    job_id = str(event.get("jobId") or "")
    if not job_id:
        return {"skipped": "missing_job"}
    table = _table()
    job = linkedin_store.get_job(table, job_id)
    if not job:
        return {"ok": False, "error": "job not found"}
    payload = dict(job.get("payload") or {})
    job["status"] = "running"
    linkedin_store.put_job(table, job)
    replacing = str(payload.get("postId") or "")
    try:
        count = payload.get("count")
        result = linkedin_draft.generate_drafts(
            table,
            count=1 if replacing else (int(count) if isinstance(count, int) else None),
            pillar=str(payload.get("pillar") or "") or None,
            idea_ids=[str(item) for item in payload.get("ideaIds") or []],
            job_id=job_id,
            persist=not replacing,
        )
        if replacing and result["posts"]:
            _replace_post(table, replacing, result["posts"][0])
            updated = linkedin_store.get_post(table, replacing) or {}
            result = {**result, "posts": [linkedin_store.public_post(updated)]}
    except (LinkedInError, linkedin_draft.DraftError, OpenRouterError) as exc:
        _fail_job(table, job, str(exc))
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — a worker error must not leave the job running
        _log_event("error", tag="linkedin_generate_failed", error=str(exc)[:300])
        _fail_job(table, job, "Generation failed.")
        return {"ok": False, "error": "Generation failed."}
    job["status"] = "done"
    job["postIds"] = [row["postId"] for row in result["posts"]]
    job["error"] = "; ".join(result["errors"])
    linkedin_store.put_job(table, job)
    _notify_ready(table, len(result["posts"]))
    return {"ok": True, "postIds": [row.get("postId") for row in result["posts"]], "error": job["error"]}


def _replace_post(table: Any, post_id: str, generated: dict[str, Any]) -> None:
    """Regenerate keeps the same id and drops approval."""
    current = linkedin_store.get_post(table, post_id)
    if not current:
        return
    linkedin_store.update_post(
        table,
        post_id,
        {
            "body": generated.get("body") or "",
            "firstComment": generated.get("firstComment") or "",
            "hashtags": generated.get("hashtags") or [],
            "pillar": generated.get("pillar") or current.get("pillar"),
        },
    )


def _notify_ready(table: Any, count: int) -> None:
    if count < 1:
        return
    settings = linkedin_store.load_settings(table)
    address = str(settings.get("notifyEmail") or "")
    if not address:
        return
    origin = _admin_origin()
    send_notice(
        address,
        "LinkedIn drafts are ready",
        (
            f"{count} new draft{'s' if count != 1 else ''} {'are' if count != 1 else 'is'} "
            f"waiting for review.\n\n{origin}/lx-software?tab=linkedin\n"
        ),
    )


def handle_weekly_plan(event: dict[str, Any] | None = None) -> dict[str, Any]:
    del event
    if not linkedin_store.feature_enabled():
        return {"skipped": "disabled"}
    table = _table()
    today = linkedin_store._as_hkt().date().isoformat()
    if linkedin_store.load_plan_date(table) == today:
        return {"skipped": "already_ran"}
    try:
        result = linkedin_draft.generate_drafts(table)
    except (LinkedInError, linkedin_draft.DraftError, OpenRouterError) as exc:
        _log_event("warning", tag="linkedin_weekly_plan_failed", error=str(exc)[:300])
        return {"ok": False, "error": str(exc)}
    linkedin_store.save_plan_date(table, today)
    _notify_ready(table, len(result["posts"]))
    return {"ok": True, "created": len(result["posts"])}


def handle_publish_due(event: dict[str, Any] | None = None) -> dict[str, Any]:
    """Remind the owner when an approved slot has passed.

    Direct publishing stays off until the LinkedIn API step exists. With
    ``LINKEDIN_PUBLISH_ENABLED`` the worker records that it did not post.
    """
    del event
    if not linkedin_store.feature_enabled():
        return {"skipped": "disabled"}
    publish = ""
    if linkedin_store.publish_enabled():
        _log_event("info", tag="linkedin_publish_not_implemented")
        publish = "publish_not_implemented"
    table = _table()
    settings = linkedin_store.load_settings(table)
    address = str(settings.get("notifyEmail") or "")
    reminded = 0
    for row in linkedin_store.due_approved(table):
        post_id = str(row.get("postId") or "")
        if address:
            hook = linkedin_store.hook_text(str(row.get("body") or ""))[:120]
            send_notice(
                address,
                "A LinkedIn post is due",
                (
                    f"This post is due. Open it, use the share box, then mark it posted.\n\n"
                    f"{hook}\n\n{_admin_origin()}/lx-software?tab=linkedin&linkedin-post={post_id}\n"
                ),
            )
        linkedin_store.stamp_due_notified(table, post_id)
        reminded += 1
    result: dict[str, Any] = {"ok": True, "reminded": reminded}
    if publish:
        result["publish"] = publish
    return result
