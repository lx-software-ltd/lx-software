"""Job posts and applications for the Resume tab."""

from __future__ import annotations

from typing import Any

from resume_store import (
    AD_TEXT_MAX,
    APPLICATION_STATUSES,
    PK_PREFIX,
    TITLE_MAX,
    ResumeError,
    _get,
    _new_id,
    _now,
    _put,
    _query,
    get_resume,
)


def get_posting(table: Any, posting_id: str) -> dict[str, Any] | None:
    return _get(table, f"{PK_PREFIX}posting#{posting_id}", "RESUME")


def list_postings(table: Any) -> list[dict[str, Any]]:
    return _query(table, f"{PK_PREFIX}postings")


def create_posting(table: Any, body: dict[str, Any]) -> dict[str, Any]:
    title = str(body.get("title") or "").strip()
    company = str(body.get("company") or "").strip()
    ad_text = str(body.get("adText") or "").strip()
    if not title or not company or not ad_text:
        raise ResumeError("Title, company, and the job post are required.")
    if len(ad_text) > AD_TEXT_MAX:
        raise ResumeError(f"The job post is over {AD_TEXT_MAX} characters.")
    if len(title) > TITLE_MAX or len(company) > TITLE_MAX:
        raise ResumeError(f"Title and company must be under {TITLE_MAX} characters.")
    posting_id = _new_id()
    now = _now()
    doc = {
        "postingId": posting_id,
        "title": title,
        "company": company,
        "url": str(body.get("url") or "").strip()[:500],
        "location": str(body.get("location") or "").strip()[:200],
        "adText": ad_text,
        "analysis": None,
        "createdAt": now,
        "gsi1pk": f"{PK_PREFIX}postings",
        "gsi1sk": f"{now}#{posting_id}",
    }
    _put(table, {"pk": f"{PK_PREFIX}posting#{posting_id}", "sk": "RESUME", **doc})
    return doc


def save_posting(table: Any, doc: dict[str, Any]) -> dict[str, Any]:
    posting_id = str(doc["postingId"])
    _put(table, {"pk": f"{PK_PREFIX}posting#{posting_id}", "sk": "RESUME", **doc})
    return doc


def public_posting(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc.get("postingId"),
        "title": doc.get("title") or "",
        "company": doc.get("company") or "",
        "url": doc.get("url") or "",
        "location": doc.get("location") or "",
        "adText": doc.get("adText") or "",
        "analysis": doc.get("analysis"),
        "createdAt": doc.get("createdAt") or "",
    }


def list_applications(table: Any) -> list[dict[str, Any]]:
    return _query(table, f"{PK_PREFIX}applications")


def get_application(table: Any, application_id: str) -> dict[str, Any] | None:
    return _get(table, f"{PK_PREFIX}application#{application_id}", "RESUME")


def _recruiter(body: dict[str, Any], current: dict[str, Any], *, partial: bool) -> dict[str, str]:
    source = body.get("recruiter") if isinstance(body.get("recruiter"), dict) else None
    if source is None and partial:
        source = current.get("recruiter") if isinstance(current.get("recruiter"), dict) else {}
    source = source or {}
    email = str(source.get("email") or "").strip()
    if email and "@" not in email:
        raise ResumeError("Recruiter email must contain @.")
    return {
        "name": str(source.get("name") or "").strip()[:200],
        "email": email[:200],
        "phone": str(source.get("phone") or "").strip()[:80],
    }


def _fields(table: Any, body: dict[str, Any], *, partial: bool, current: dict[str, Any]) -> dict[str, Any]:
    def take(name: str, default: str = "") -> str:
        if name not in body and partial:
            return str(current.get(name) or default)
        return str(body.get(name) or default).strip()

    company = take("company")
    position = take("position")
    if not company or not position:
        raise ResumeError("Company and position are required.")
    if len(company) > TITLE_MAX or len(position) > TITLE_MAX:
        raise ResumeError(f"Company and position must be under {TITLE_MAX} characters.")
    status = take("status", "saved")
    if status not in APPLICATION_STATUSES:
        raise ResumeError("Status is not valid.")
    resume_id = take("resumeId")
    if resume_id and not get_resume(table, resume_id):
        raise ResumeError("Resume not found.", 404)
    posting_id = take("postingId")
    if posting_id and not get_posting(table, posting_id):
        raise ResumeError("Job post not found.", 404)
    return {
        "company": company,
        "position": position,
        "status": status,
        "resumeId": resume_id,
        "postingId": posting_id,
        "appliedAt": take("appliedAt"),
        "nextStepAt": take("nextStepAt"),
        "notes": take("notes")[:4000],
        "recruiter": _recruiter(body, current, partial=partial),
    }


def create_application(table: Any, body: dict[str, Any]) -> dict[str, Any]:
    fields = _fields(table, body, partial=False, current={})
    application_id = _new_id()
    now = _now()
    doc = {
        "applicationId": application_id,
        **fields,
        "history": [{"at": now, "status": fields["status"]}],
        "createdAt": now,
        "updatedAt": now,
        "gsi1pk": f"{PK_PREFIX}applications",
        "gsi1sk": f"{now}#{application_id}",
    }
    _put(table, {"pk": f"{PK_PREFIX}application#{application_id}", "sk": "RESUME", **doc})
    return doc


def patch_application(table: Any, application_id: str, body: dict[str, Any]) -> dict[str, Any]:
    doc = get_application(table, application_id)
    if not doc:
        raise ResumeError("Application not found.", 404)
    fields = _fields(table, body, partial=True, current=doc)
    if fields["status"] != doc.get("status"):
        history = list(doc.get("history") or [])
        history.append({"at": _now(), "status": fields["status"]})
        doc["history"] = history[-50:]
    doc.update(fields)
    now = _now()
    doc["updatedAt"] = now
    doc["gsi1sk"] = f"{now}#{application_id}"
    _put(table, {"pk": f"{PK_PREFIX}application#{application_id}", "sk": "RESUME", **doc})
    return doc


def delete_application(table: Any, application_id: str) -> None:
    if not get_application(table, application_id):
        raise ResumeError("Application not found.", 404)
    table.delete_item(Key={"pk": f"{PK_PREFIX}application#{application_id}", "sk": "RESUME"})


def public_application(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc.get("applicationId"),
        "resumeId": doc.get("resumeId") or "",
        "postingId": doc.get("postingId") or "",
        "company": doc.get("company") or "",
        "position": doc.get("position") or "",
        "recruiter": doc.get("recruiter") or {"name": "", "email": "", "phone": ""},
        "status": doc.get("status") or "saved",
        "appliedAt": doc.get("appliedAt") or "",
        "nextStepAt": doc.get("nextStepAt") or "",
        "notes": doc.get("notes") or "",
        "history": list(doc.get("history") or []),
        "createdAt": doc.get("createdAt") or "",
        "updatedAt": doc.get("updatedAt") or "",
    }
