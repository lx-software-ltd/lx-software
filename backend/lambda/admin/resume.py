"""HTTP API and async workers for the LX Software Resume tab."""

from __future__ import annotations

import base64
import os
from typing import Any
from urllib.parse import parse_qs

import board_async
import board_store
import resume_extract
import resume_pdf
import resume_spend
import resume_store
import resume_tailor
import resume_tracker
from http_common import _audit, _json_response, _log_event, _parse_json_body
from resume_store import ResumeError

PREFIX = "/lx-software/resume"


def _table() -> Any:
    return board_store.records_table()


def _require_enabled() -> dict[str, Any] | None:
    if resume_store.feature_enabled():
        return None
    return _json_response(403, {"message": "Resume is turned off.", "reason": "resume_disabled"})


def _parts(path: str) -> list[str]:
    rest = path[len(PREFIX) :] if path.startswith(PREFIX) else path
    return [part for part in rest.split("/") if part]


def _body(event: dict[str, Any]) -> dict[str, Any]:
    return _parse_json_body(event)


def _fail(status: int, exc: ResumeError) -> dict[str, Any]:
    return _json_response(status, {"message": str(exc)})


def _queue(
    event: dict[str, Any], kind: str, internal: str, payload: dict[str, Any], user_sub: str | None
) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    table = _table()
    job = resume_store.new_job(table, kind, payload)
    accepted = board_async.try_invoke_event({"internal": internal, "jobId": job["jobId"]})
    if not accepted:
        job["status"] = "failed"
        job["error"] = "Could not queue the job."
        resume_store.put_job(table, job)
        return _json_response(503, {"message": job["error"], "job": resume_store.public_job(job)})
    _audit(user_sub, f"RESUME_{kind.upper()}", job["jobId"], event)
    return _json_response(202, {"job": resume_store.public_job(job)})


def _filename(title: str, ext: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in title).strip("-")
    return f"{cleaned or 'resume'}.{ext}"


def handle_http(event: dict[str, Any], method: str, path: str, user_sub: str | None) -> dict[str, Any]:
    parts = _parts(path)
    try:
        if parts == ["overview"] and method == "GET":
            return _overview()
        if parts == ["settings"] and method == "GET":
            return _json_response(200, {"settings": resume_store.load_settings(_table())})
        if parts == ["settings"] and method == "PUT":
            return _save_settings(event, user_sub)
        if parts == ["resumes"] and method == "GET":
            return _json_response(
                200,
                {
                    "items": [
                        resume_store.public_resume(row, detail=False) for row in resume_store.list_resumes(_table())
                    ]
                },
            )
        if parts == ["resumes"] and method == "POST":
            return _upload(event, user_sub)
        if len(parts) == 2 and parts[0] == "resumes" and method == "GET":
            return _resume(parts[1])
        if len(parts) == 2 and parts[0] == "resumes" and method == "PATCH":
            return _patch_resume(event, parts[1], user_sub)
        if len(parts) == 2 and parts[0] == "resumes" and method == "DELETE":
            return _delete_resume(event, parts[1], user_sub)
        if len(parts) == 3 and parts[0] == "resumes" and parts[2] == "file" and method == "GET":
            return _file(parts[1])
        if len(parts) == 3 and parts[0] == "resumes" and parts[2] == "pdf" and method == "GET":
            return _pdf(parts[1])
        if parts == ["template"] and method == "PUT":
            return _template(event, user_sub)
        if parts == ["postings"] and method == "GET":
            return _json_response(
                200, {"items": [resume_tracker.public_posting(row) for row in resume_tracker.list_postings(_table())]}
            )
        if parts == ["postings"] and method == "POST":
            return _posting(event, user_sub)
        if parts == ["tailor"] and method == "POST":
            return _tailor(event, user_sub)
        if parts == ["applications"] and method == "GET":
            status = (parse_qs(event.get("rawQueryString") or "").get("status") or [""])[0]
            rows = resume_tracker.list_applications(_table())
            if status:
                rows = [row for row in rows if row.get("status") == status]
            return _json_response(200, {"items": [resume_tracker.public_application(row) for row in rows]})
        if parts == ["applications"] and method == "POST":
            return _application(event, user_sub)
        if len(parts) == 2 and parts[0] == "applications" and method == "PATCH":
            return _patch_application(event, parts[1], user_sub)
        if len(parts) == 2 and parts[0] == "applications" and method == "DELETE":
            return _delete_application(event, parts[1], user_sub)
        if len(parts) == 2 and parts[0] == "jobs" and method == "GET":
            return _job(parts[1])
    except ResumeError as exc:
        return _fail(exc.status, exc)
    return _json_response(404, {"message": "Not found"})


def _overview() -> dict[str, Any]:
    table = _table()
    return _json_response(
        200,
        {
            "enabled": resume_store.feature_enabled(),
            "settings": resume_store.load_settings(table),
            "templateResumeId": resume_store.template_id(table),
            "defaultModel": os.environ.get("OPENROUTER_MODEL") or "",
            "spendUsdMonth": resume_store.month_spend(table),
            "counts": resume_store.counts(table),
            "pdfCjk": resume_pdf.cjk_supported(),
        },
    )


def _save_settings(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    settings = resume_store.save_settings(_table(), _body(event))
    _audit(user_sub, "RESUME_SETTINGS", "state", event)
    return _json_response(200, {"settings": settings})


def _upload(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    body = _body(event)
    try:
        data = base64.b64decode(str(body.get("dataBase64") or ""), validate=True)
    except Exception as exc:
        raise ResumeError("The file is not valid base64.") from exc
    table = _table()
    doc = resume_store.create_resume(
        table,
        title=str(body.get("title") or ""),
        content_type=str(body.get("contentType") or ""),
        data=data,
        make_template=bool(body.get("makeTemplate")),
    )
    job = resume_store.new_job(table, "extract", {"resumeId": doc["resumeId"]})
    accepted = board_async.try_invoke_event({"internal": "resume_extract", "jobId": job["jobId"]})
    if not accepted:
        doc["extract"] = {"status": "failed", "error": "Could not queue the job."}
        resume_store.save_resume(table, doc)
        job["status"] = "failed"
        job["error"] = doc["extract"]["error"]
        resume_store.put_job(table, job)
        return _json_response(
            503,
            {
                "message": job["error"],
                "resume": resume_store.public_resume(doc, detail=False),
                "job": resume_store.public_job(job),
            },
        )
    _audit(user_sub, "RESUME_UPLOAD", doc["resumeId"], event)
    return _json_response(
        202, {"resume": resume_store.public_resume(doc, detail=False), "job": resume_store.public_job(job)}
    )


def _resume(resume_id: str) -> dict[str, Any]:
    doc = resume_store.get_resume(_table(), resume_id)
    if not doc:
        return _json_response(404, {"message": "Resume not found"})
    return _json_response(200, {"item": resume_store.public_resume(doc, detail=True)})


def _patch_resume(event: dict[str, Any], resume_id: str, user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    doc = resume_store.patch_resume(_table(), resume_id, _body(event))
    _audit(user_sub, "RESUME_UPDATE", resume_id, event)
    return _json_response(200, {"item": resume_store.public_resume(doc, detail=True)})


def _delete_resume(event: dict[str, Any], resume_id: str, user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    resume_store.delete_resume(_table(), resume_id)
    _audit(user_sub, "RESUME_DELETE", resume_id, event)
    return _json_response(200, {"deleted": resume_id})


def _file(resume_id: str) -> dict[str, Any]:
    doc = resume_store.get_resume(_table(), resume_id)
    if not doc:
        return _json_response(404, {"message": "Resume not found"})
    loaded = resume_store.load_bytes(str((doc.get("file") or {}).get("key") or ""))
    if not loaded:
        return _json_response(404, {"message": "File not found"})
    content_type, data = loaded
    ext = {"docx": "docx", "pdf": "pdf", "md": "md"}.get(str(doc.get("format")), "bin")
    return _json_response(
        200,
        {
            "contentType": content_type,
            "filename": _filename(str(doc.get("title") or "resume"), ext),
            "dataBase64": base64.b64encode(data).decode("ascii"),
        },
    )


def _pdf(resume_id: str) -> dict[str, Any]:
    table = _table()
    doc = resume_store.get_resume(table, resume_id)
    if not doc:
        return _json_response(404, {"message": "Resume not found"})
    if (doc.get("extract") or {}).get("status") != "ready":
        raise ResumeError("This resume is not ready yet.")
    settings = resume_store.load_settings(table)
    page = str(settings.get("pageSize") or "A4")
    cached = str(doc.get("pdfKey") or "")
    stamp = str(doc.get("pdfPage") or "")
    if cached and stamp == page:
        loaded = resume_store.load_bytes(cached)
        if loaded:
            _content_type, data = loaded
            return _pdf_body(doc, data)
    data = resume_pdf.render(list(doc.get("paragraphs") or []), dict(doc.get("layout") or {}), page_size=page)
    key = f"resume/resumes/{resume_id}/render.pdf"
    resume_store.put_bytes(key, "application/pdf", data)
    doc["pdfKey"] = key
    doc["pdfPage"] = page
    resume_store.save_resume(table, doc)
    return _pdf_body(doc, data)


def _pdf_body(doc: dict[str, Any], data: bytes) -> dict[str, Any]:
    return _json_response(
        200,
        {
            "contentType": "application/pdf",
            "filename": _filename(str(doc.get("title") or "resume"), "pdf"),
            "dataBase64": base64.b64encode(data).decode("ascii"),
        },
    )


def _template(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    resume_id = str(_body(event).get("resumeId") or "")
    resume_store.set_template(_table(), resume_id)
    _audit(user_sub, "RESUME_TEMPLATE", resume_id, event)
    return _json_response(200, {"templateResumeId": resume_id})


def _posting(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    doc = resume_tracker.create_posting(_table(), _body(event))
    _audit(user_sub, "RESUME_POSTING", doc["postingId"], event)
    return _json_response(201, {"item": resume_tracker.public_posting(doc)})


def _ready_template(table: Any, template_id: str) -> None:
    template = resume_store.get_resume(table, template_id) if template_id else None
    ready = (template or {}).get("extract") or {}
    if not template or template.get("format") != "docx" or ready.get("status") != "ready":
        raise ResumeError("Choose a ready Word template.")


def _tailor(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    body = _body(event)
    table = _table()
    template_id = str(body.get("templateId") or "") or resume_store.template_id(table)
    _ready_template(table, template_id)
    posting_id = str(body.get("postingId") or "")
    if posting_id:
        if not resume_tracker.get_posting(table, posting_id):
            raise ResumeError("Job post not found.", 404)
    else:
        posting = body.get("posting") if isinstance(body.get("posting"), dict) else None
        if not posting:
            raise ResumeError("Choose or paste a job post.")
        created = resume_tracker.create_posting(table, posting)
        posting_id = str(created["postingId"])
    return _queue(
        event,
        "tailor",
        "resume_tailor",
        {"templateId": template_id, "postingId": posting_id, "addToTracker": bool(body.get("addToTracker", True))},
        user_sub,
    )


def _application(event: dict[str, Any], user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    doc = resume_tracker.create_application(_table(), _body(event))
    _audit(user_sub, "RESUME_APPLICATION", doc["applicationId"], event)
    return _json_response(201, {"item": resume_tracker.public_application(doc)})


def _patch_application(event: dict[str, Any], application_id: str, user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    doc = resume_tracker.patch_application(_table(), application_id, _body(event))
    _audit(user_sub, "RESUME_APPLICATION_UPDATE", application_id, event)
    return _json_response(200, {"item": resume_tracker.public_application(doc)})


def _delete_application(event: dict[str, Any], application_id: str, user_sub: str | None) -> dict[str, Any]:
    blocked = _require_enabled()
    if blocked:
        return blocked
    resume_tracker.delete_application(_table(), application_id)
    _audit(user_sub, "RESUME_APPLICATION_DELETE", application_id, event)
    return _json_response(200, {"deleted": application_id})


def _job(job_id: str) -> dict[str, Any]:
    table = _table()
    doc = resume_store.get_job(table, job_id)
    if not doc:
        return _json_response(404, {"message": "Job not found"})
    doc = resume_spend.finalize_stale(table, doc)
    return _json_response(200, {"job": resume_store.public_job(doc)})


def _run_worker(event: dict[str, Any], runner: Any) -> dict[str, Any]:
    table = _table()
    job = resume_store.get_job(table, str(event.get("jobId") or ""))
    if not job or job.get("status") not in {"queued", "running"}:
        return {"ok": True}
    if resume_spend.is_stale(job):
        resume_spend.finalize_stale(table, job)
        return {"ok": False}
    if not resume_store.feature_enabled():
        job["status"] = "failed"
        job["error"] = "Resume is turned off."
        resume_store.put_job(table, job)
        return {"ok": False}
    if not job.get("startedAt"):
        job["startedAt"] = resume_store._now()
    job["status"] = "running"
    resume_store.put_job(table, job)
    try:
        runner(table, job)
        fresh = resume_store.get_job(table, str(job["jobId"]))
        if fresh and fresh.get("status") == "failed":
            return {"ok": False}
        job["status"] = "done"
    except Exception as exc:
        resume_spend.settle_job(table, job)
        job["status"] = "failed"
        job["error"] = str(exc)[:500]
        _log_event("warning", tag="resume_job_failed", kind=job.get("kind"), error=job["error"])
    resume_store.put_job(table, job)
    return {"ok": job["status"] == "done"}


def handle_extract(event: dict[str, Any]) -> dict[str, Any]:
    def runner(table: Any, job: dict[str, Any]) -> None:
        resume_id = str((job.get("payload") or {}).get("resumeId") or "")
        try:
            resume_extract.run(table, resume_id, job)
        except Exception as exc:
            doc = resume_store.get_resume(table, resume_id)
            if doc:
                doc["extract"] = {"status": "failed", "error": str(exc)[:500]}
                resume_store.save_resume(table, doc)
            raise
        job["resumeIds"] = [resume_id]

    return _run_worker(event, runner)


def handle_tailor(event: dict[str, Any]) -> dict[str, Any]:
    def runner(table: Any, job: dict[str, Any]) -> None:
        resume_tailor.run(table, job)

    return _run_worker(event, runner)
