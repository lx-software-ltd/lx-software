"""Rewrite the allowed paragraphs of a template resume for one job post."""

from __future__ import annotations

import hashlib
from typing import Any

import boto3
import openrouter_client
import openrouter_usage
import resume_docx
import resume_extract
import resume_guard
import resume_store
import resume_tracker
from openrouter_client import parse_json_object_text
from resume_store import ResumeError

_LENGTH = {
    "concise": "Prefer shorter bullets. Stay inside the template length.",
    "standard": "Keep each paragraph within about 15% of its current length.",
    "detailed": "You may use the full 15% length budget when the job post needs it.",
}


def _chat(
    table: Any,
    settings: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    owner: str,
    max_tokens: int,
    temperature: float,
) -> Any:
    model = resume_store.model_name(settings)
    if not model:
        raise ResumeError("No model is configured.")
    timeout = resume_store.tailor_timeout()
    result = openrouter_client.chat_completion(
        messages=messages,
        model=model,
        secrets_client=boto3.client("secretsmanager"),
        timeout=timeout,
        json_mode=True,
        temperature=temperature,
        max_tokens=max_tokens,
        service="resume",
        owner=owner,
        reasoning={"enabled": False, "exclude": True},
    )
    if result.finish_reason == "length":
        result = openrouter_client.chat_completion(
            messages=messages,
            model=model,
            secrets_client=boto3.client("secretsmanager"),
            timeout=timeout,
            json_mode=True,
            temperature=temperature,
            max_tokens=max_tokens * 2,
            service="resume",
            owner=owner,
            reasoning={"enabled": False, "exclude": True},
        )
    openrouter_usage.add_usage_day(table, service="resume", owner=owner, usage=result.usage, calls=1)
    return result


def _json(result: Any) -> dict[str, Any]:
    parsed = parse_json_object_text(result.text)
    if not isinstance(parsed, dict):
        raise ResumeError("The model did not return JSON.")
    return parsed


def analyze(table: Any, settings: dict[str, Any], posting: dict[str, Any]) -> dict[str, Any]:
    if isinstance(posting.get("analysis"), dict) and posting["analysis"]:
        return posting["analysis"]
    result = _chat(
        table,
        settings,
        [
            {
                "role": "system",
                "content": (
                    "Read a job post. Return JSON "
                    '{"mustHaves":[""],"niceToHaves":[""],"keywords":[""],"seniority":"","titleHint":""}. '
                    "Use only what the post says."
                ),
            },
            {"role": "user", "content": str(posting.get("adText") or "")},
        ],
        owner="tailor",
        max_tokens=2000,
        temperature=0,
    )
    analysis = _json(result)
    posting["analysis"] = {
        "mustHaves": list(analysis.get("mustHaves") or []),
        "niceToHaves": list(analysis.get("niceToHaves") or []),
        "keywords": list(analysis.get("keywords") or []),
        "seniority": str(analysis.get("seniority") or ""),
        "titleHint": str(analysis.get("titleHint") or ""),
    }
    resume_tracker.save_posting(table, posting)
    return posting["analysis"]


def _prompt(
    paragraphs: list[dict[str, Any]],
    layout: dict[str, Any],
    settings: dict[str, Any],
    analysis: dict[str, Any],
    *,
    findings: list[str],
) -> list[dict[str, str]]:
    allowed = resume_guard.rewritable_ids(paragraphs, layout, settings)
    roles = {str(item.get("id")): str(item.get("role") or "") for item in layout.get("paragraphs") or []}
    editable = [
        {
            "id": item["id"],
            "role": roles.get(str(item["id"]), ""),
            "text": item.get("text") or "",
            "chars": len(str(item.get("text") or "")),
        }
        for item in paragraphs
        if str(item.get("id")) in allowed and str(item.get("text") or "").strip()
    ]
    locked = [
        {"id": item["id"], "role": roles.get(str(item["id"]), ""), "text": item.get("text") or ""}
        for item in paragraphs
        if str(item.get("id")) not in allowed and str(item.get("text") or "").strip()
    ]
    groups = [
        {"headerId": group.get("headerId"), "bulletIds": list(group.get("bulletIds") or [])}
        for group in layout.get("roles") or []
    ]
    system = (
        "Rewrite only the supplied resume paragraphs for this job. Return JSON "
        '{"replacements":[{"id":"p1","text":""}],"roles":[{"headerId":"p3","bullets":[""]}],'
        '"skills":[{"id":"p8","text":""}]}. '
        "Do not invent employers, job titles, dates, degrees, certifications, or numbers. "
        "Every number must already appear in the template. "
        "Keep the same roles and, unless told otherwise, the same number of bullets. "
        + _LENGTH.get(str(settings.get("outputLength") or "standard"), _LENGTH["standard"])
        + " Locked paragraphs are context only. Do not return them."
    )
    if settings.get("instructions"):
        system += " Owner instructions: " + str(settings["instructions"])
    if findings:
        system += " Fix these problems and change nothing else: " + " ".join(findings)
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": str(
                {
                    "job": analysis,
                    "editable": editable,
                    "locked": locked,
                    "roles": groups,
                    "bulletPolicy": settings.get("bulletPolicy") or "keep",
                    "allowNewSkills": bool(settings.get("allowNewSkills")),
                }
            ),
        },
    ]


def _store_tailored(
    table: Any,
    *,
    template: dict[str, Any],
    posting: dict[str, Any],
    data: bytes,
    notes: list[str],
    settings: dict[str, Any],
    model: str,
    usage: dict[str, Any],
    add_to_tracker: bool,
) -> str:
    paragraphs = resume_docx.paragraph_map(data)
    layout = resume_extract.heuristic(paragraphs)
    resume_id = resume_store._new_id()
    key = f"resume/resumes/{resume_id}/tailored.docx"
    resume_store.put_bytes(key, resume_store.DOCX_TYPE, data)
    now = resume_store._now()
    title = f"{posting.get('title') or 'Role'} — {posting.get('company') or 'Company'}"
    doc = {
        "resumeId": resume_id,
        "title": title[: resume_store.TITLE_MAX],
        "kind": "tailored",
        "format": "docx",
        "source": "generated",
        "file": {
            "contentType": resume_store.DOCX_TYPE,
            "size": len(data),
            "key": key,
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        "extract": {"status": "ready", "error": ""},
        "paragraphs": paragraphs,
        "layout": layout,
        "derivedFrom": {"templateId": template.get("resumeId"), "postingId": posting.get("postingId")},
        "generation": {"model": model, "usage": usage, "costUsd": float(usage.get("cost") or 0), "findings": notes},
        "pdfKey": "",
        "createdAt": now,
        "updatedAt": now,
        "gsi1pk": f"{resume_store.PK_PREFIX}resumes",
        "gsi1sk": f"{now}#{resume_id}",
    }
    resume_store.save_resume(table, doc)
    if add_to_tracker:
        resume_tracker.create_application(
            table,
            {
                "company": posting.get("company") or "",
                "position": posting.get("title") or "",
                "status": "saved",
                "resumeId": resume_id,
                "postingId": posting.get("postingId") or "",
                "recruiter": {"name": "", "email": "", "phone": ""},
            },
        )
    del settings
    return resume_id


def run(table: Any, job: dict[str, Any]) -> None:
    payload = job.get("payload") or {}
    template = resume_store.get_resume(table, str(payload.get("templateId") or ""))
    posting = resume_tracker.get_posting(table, str(payload.get("postingId") or ""))
    if not template or template.get("format") != "docx" or (template.get("extract") or {}).get("status") != "ready":
        raise ResumeError("Choose a ready Word template.")
    if not posting:
        raise ResumeError("Job post not found.", 404)
    settings = resume_store.load_settings(table)
    cap = float(settings.get("maxUsdPerMonth") or 0)
    if not resume_store.try_reserve_spend(table, resume_store.ESTIMATE_USD, cap):
        raise ResumeError("This month's resume spend cap has been reached.")
    spent = resume_store.ESTIMATE_USD
    try:
        analysis = analyze(table, settings, posting)
        paragraphs = list(template.get("paragraphs") or [])
        layout = dict(template.get("layout") or {})
        loaded = resume_store.load_bytes(str((template.get("file") or {}).get("key") or ""))
        if not loaded:
            raise ResumeError("The template file is missing.")
        _content_type, source = loaded
        result = _chat(
            table,
            settings,
            _prompt(paragraphs, layout, settings, analysis, findings=[]),
            owner="tailor",
            max_tokens=6000,
            temperature=float(settings.get("temperature") or 0.4),
        )
        output = _json(result)
        blocking, notes = resume_guard.check(paragraphs=paragraphs, layout=layout, settings=settings, output=output)
        usage = dict(result.usage or {})
        if blocking:
            result = _chat(
                table,
                settings,
                _prompt(paragraphs, layout, settings, analysis, findings=blocking),
                owner="tailor",
                max_tokens=6000,
                temperature=float(settings.get("temperature") or 0.4),
            )
            output = _json(result)
            blocking, extra = resume_guard.check(paragraphs=paragraphs, layout=layout, settings=settings, output=output)
            notes.extend(extra)
            for key, value in (result.usage or {}).items():
                if isinstance(value, (int, float)):
                    usage[key] = float(usage.get(key) or 0) + float(value)
        if blocking:
            job["findings"] = blocking
            raise ResumeError(" ".join(blocking))
        tailored, format_notes = resume_docx.apply(source, layout, output)
        notes.extend(format_notes)
        job_resume = _store_tailored(
            table,
            template=template,
            posting=posting,
            data=tailored,
            notes=notes,
            settings=settings,
            model=resume_store.model_name(settings),
            usage=usage,
            add_to_tracker=bool(payload.get("addToTracker", True)),
        )
        job["resumeIds"] = [job_resume]
        job["findings"] = notes
        actual = float(usage.get("cost") or 0)
        resume_store.adjust_spend(table, actual - spent)
    except Exception:
        resume_store.adjust_spend(table, -spent)
        raise
