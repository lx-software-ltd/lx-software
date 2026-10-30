"""Turn an uploaded resume into a paragraph map and a role layout."""

from __future__ import annotations

import base64
import re
from typing import Any

import boto3
import openrouter_client
import openrouter_usage
import resume_docx
import resume_spend
import resume_store
from openrouter_client import parse_json_object_text
from resume_store import ResumeError

_SECTIONS = {
    "summary": "summary",
    "profile": "summary",
    "about": "summary",
    "個人簡介": "summary",
    "experience": "experience",
    "work experience": "experience",
    "employment": "experience",
    "工作經驗": "experience",
    "skills": "skills",
    "technical skills": "skills",
    "技能": "skills",
    "education": "education",
    "學歷": "education",
    "certifications": "certification",
    "certification": "certification",
    "證照": "certification",
}
_ROLES = {
    "name",
    "contact",
    "headline",
    "summary",
    "section_heading",
    "role_header",
    "role_meta",
    "bullet",
    "skills",
    "education",
    "certification",
    "other",
}
_DATE = re.compile(r"(19|20)\d{2}|present|至今", re.IGNORECASE)
_CONTACT = re.compile(r"@|\+?\d[\d\s().-]{6,}")


def heuristic(paragraphs: list[dict[str, Any]]) -> dict[str, Any]:
    labeled: list[dict[str, str]] = []
    groups: list[dict[str, Any]] = []
    section = ""
    header_id = ""
    for index, paragraph in enumerate(paragraphs):
        text = str(paragraph.get("text") or "").strip()
        folded = text.casefold()
        role = "other"
        if not text:
            role = "other"
        elif index == 0 and len(text) < 80:
            role = "name"
        elif _is_heading(paragraph, folded, text):
            role = "section_heading"
            section = _SECTIONS.get(folded, section)
            header_id = ""
        elif _CONTACT.search(text) and len(text) < 160 and section == "":
            role = "contact"
        elif paragraph.get("numbered") or text.startswith(("•", "-", "–", "*")):
            role = "bullet" if section in {"", "experience"} else _body_role(section)
            if role == "bullet" and groups:
                groups[-1]["bulletIds"].append(paragraph["id"])
        elif section == "experience" and _DATE.search(text) and len(text) < 140:
            role = "role_header"
            header_id = str(paragraph["id"])
            groups.append({"headerId": header_id, "bulletIds": []})
        elif section == "experience" and header_id and len(text) < 100:
            role = "role_meta"
        else:
            role = _body_role(section) if section else "other"
            if role == "bullet" and groups:
                groups[-1]["bulletIds"].append(paragraph["id"])
        labeled.append({"id": str(paragraph["id"]), "role": role})
    return {"paragraphs": labeled, "roles": groups, "overrides": {}}


def _is_heading(paragraph: dict[str, Any], folded: str, text: str) -> bool:
    style = str(paragraph.get("style") or "").casefold()
    if "heading" in style or style.startswith("title"):
        return True
    if folded in _SECTIONS and len(text) < 40:
        return True
    return text.isupper() and 2 < len(text) < 40


def _body_role(section: str) -> str:
    return {
        "summary": "summary",
        "skills": "skills",
        "education": "education",
        "certification": "certification",
        "experience": "bullet",
    }.get(section, "other")


def paragraphs_from_text(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        style = ""
        numbered = False
        if line.startswith("#"):
            style = "Heading1"
            line = line.lstrip("#").strip()
        elif line.startswith(("- ", "* ", "• ")):
            numbered = True
            line = line[2:].strip()
        rows.append(
            {
                "id": f"p{len(rows)}",
                "text": line,
                "style": style,
                "numbered": numbered,
                "inTable": False,
                "inTextBox": False,
                "runs": 1 if line else 0,
                "chars": len(line),
            }
        )
    return rows


def _merge(layout: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    current = {str(item["id"]): str(item["role"]) for item in layout.get("paragraphs") or []}
    for item in model.get("paragraphs") or []:
        paragraph_id = str(item.get("id") or "")
        role = str(item.get("role") or "")
        if paragraph_id in current and role in _ROLES:
            current[paragraph_id] = role
    groups = []
    known_bullets = set(current)
    for group in model.get("roles") or []:
        header = str(group.get("headerId") or "")
        bullets = [str(item) for item in group.get("bulletIds") or [] if str(item) in known_bullets]
        if header in current:
            groups.append({"headerId": header, "bulletIds": bullets})
    if not groups:
        groups = list(layout.get("roles") or [])
    return {
        "paragraphs": [{"id": key, "role": value} for key, value in current.items()],
        "roles": groups,
        "overrides": dict(layout.get("overrides") or {}),
    }


def _book(table: Any, job: dict[str, Any] | None, result: Any) -> None:
    openrouter_usage.add_usage_day(table, service="resume", owner="extract", usage=result.usage, calls=1)
    if job is not None:
        resume_spend.add_usage(table, job, result.usage)


def _timeout(job: dict[str, Any] | None, preferred: int) -> int:
    started = str((job or {}).get("startedAt") or "") or None
    return resume_spend.bounded_timeout(started, preferred)


def classify(
    table: Any,
    paragraphs: list[dict[str, Any]],
    layout: dict[str, Any],
    settings: dict[str, Any],
    job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model = resume_store.model_name(settings)
    if not model:
        raise ResumeError("No model is configured.")
    hints = [
        {"id": item["id"], "text": item.get("text") or "", "hint": role["role"]}
        for item, role in zip(paragraphs, layout["paragraphs"], strict=False)
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "Label resume paragraphs. Return JSON "
                '{"paragraphs":[{"id":"p0","role":"name"}],"roles":[{"headerId":"p3","bulletIds":["p4"]}]}. '
                "Roles: name, contact, headline, summary, section_heading, role_header, role_meta, "
                "bullet, skills, education, certification, other. Group experience bullets under their role header. "
                "Do not rewrite the text."
            ),
        },
        {"role": "user", "content": str(hints)},
    ]
    result = openrouter_client.chat_completion(
        messages=messages,
        model=model,
        secrets_client=boto3.client("secretsmanager"),
        timeout=_timeout(job, 60),
        json_mode=True,
        temperature=0,
        max_tokens=4000,
        service="resume",
        owner="extract",
        reasoning={"enabled": False, "exclude": True},
    )
    _book(table, job, result)
    parsed = parse_json_object_text(result.text)
    if not isinstance(parsed, dict):
        raise ResumeError("The model did not return a paragraph map.")
    return _merge(layout, parsed)


def pdf_text(table: Any, data: bytes, settings: dict[str, Any], job: dict[str, Any] | None = None) -> str:
    model = resume_store.model_name(settings)
    if not model:
        raise ResumeError("No model is configured.")
    encoded = base64.b64encode(data).decode("ascii")
    text = _pdf_engine(table, model, encoded, "pdf-text", job)
    if len(text.strip()) < 200:
        text = _pdf_engine(table, model, encoded, "mistral-ocr", job)
    return text


def _pdf_engine(table: Any, model: str, encoded: str, engine: str, job: dict[str, Any] | None) -> str:
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": 'Extract the resume text. Return JSON {"text":"..."} with one paragraph per line. Do not summarize.',
                },
                {
                    "type": "file",
                    "file": {"filename": "resume.pdf", "file_data": f"data:application/pdf;base64,{encoded}"},
                },
            ],
        }
    ]
    result = openrouter_client.chat_completion(
        messages=messages,
        model=model,
        secrets_client=boto3.client("secretsmanager"),
        timeout=_timeout(job, 90),
        json_mode=True,
        temperature=0,
        max_tokens=6000,
        plugins=[{"id": "file-parser", "pdf": {"engine": engine}}],
        service="resume",
        owner="extract",
        reasoning={"enabled": False, "exclude": True},
    )
    _book(table, job, result)
    parsed = parse_json_object_text(result.text)
    if not isinstance(parsed, dict):
        return ""
    return str(parsed.get("text") or "")


def _needs_text(paragraphs: list[dict[str, Any]]) -> bool:
    return any(str(item.get("text") or "").strip() for item in paragraphs)


def run(table: Any, resume_id: str, job: dict[str, Any] | None = None) -> None:
    meter = job if job is not None else {}
    doc = resume_store.get_resume(table, resume_id)
    if not doc:
        raise ResumeError("Resume not found.", 404)
    loaded = resume_store.load_bytes(str((doc.get("file") or {}).get("key") or ""))
    if not loaded:
        raise ResumeError("The uploaded file is missing.")
    _content_type, data = loaded
    settings = resume_store.load_settings(table)
    cap = float(settings.get("maxUsdPerMonth") or 0)
    fmt = str(doc.get("format") or "")
    reserved = False
    try:
        if fmt == "docx":
            paragraphs = resume_docx.paragraph_map(data)
            layout = heuristic(paragraphs)
            if _needs_text(paragraphs):
                resume_spend.reserve_job(table, meter, cap)
                reserved = True
                layout = classify(table, paragraphs, layout, settings, meter)
        else:
            if fmt == "pdf":
                resume_spend.reserve_job(table, meter, cap)
                reserved = True
                text = pdf_text(table, data, settings, meter)
            else:
                text = data.decode("utf-8", errors="replace")
            paragraphs = paragraphs_from_text(text)
            layout = heuristic(paragraphs)
            if fmt == "pdf" and _needs_text(paragraphs):
                layout = classify(table, paragraphs, layout, settings, meter)
        doc["paragraphs"] = paragraphs
        doc["layout"] = layout
        doc["extract"] = {"status": "ready", "error": ""}
        make_template = bool(doc.pop("makeTemplate", False))
        resume_store.save_resume(table, doc)
        if make_template:
            resume_store.set_template(table, resume_id)
    finally:
        if reserved:
            resume_spend.settle_job(table, meter)
