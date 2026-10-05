"""Draft LinkedIn posts for a personal presence, not a company page.

Settings voice controls tone. The tone defaults (first person, short lines, a
closing question) apply only where that voice is blank or silent. Safety rules
— hook length, no employer, no availability, no pitch, forbidden phrases —
always apply. Deterministic checks in ``linkedin_store`` still run after the
model returns.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any

import linkedin_store
import openrouter_usage
from http_common import _log_event
from linkedin_store import LinkedInError
from openrouter_client import OpenRouterError, parse_json_object_text

SERVICE = "linkedin"
_BODY_KEYS = ("body", "post", "text", "content", "commentary")
# A post is a few hundred tokens. The first call leaves room for a verbose
# model; the retry after a cut-off answer doubles it.
DRAFT_MAX_TOKENS = 2000
DRAFT_RETRY_MAX_TOKENS = 4000
# Drafts never need chain-of-thought. Hybrid reasoning models otherwise spend
# the whole token budget thinking and the reply is cut before the JSON.
DRAFT_REASONING = {"enabled": False, "exclude": True}


class DraftError(RuntimeError):
    """The model call failed or returned nothing usable.

    ``stop`` marks a failure that will repeat for every topic in this run
    (the model never reaches the JSON), so the batch gives up at once instead
    of spending the same budget on each draft.
    """

    def __init__(self, message: str, *, stop: bool = False) -> None:
        super().__init__(message)
        self.stop = stop


def _voice_notes(settings: dict[str, Any]) -> str:
    return str(settings.get("voiceNotes") or "").strip()


def voice_hash(settings: dict[str, Any]) -> str:
    """Short digest of the voice that produced a draft. Empty voice has its own hash."""
    return hashlib.sha256(_voice_notes(settings).encode("utf-8")).hexdigest()[:16]


# Shape only. A filled body so json_mode does not echo an empty post, and no
# cadence (short lines, a closing question) for the model to imitate.
_SCHEMA_EXAMPLE = (
    '{"body":"The full post goes here.","firstComment":"",'
    '"hashtags":["Topic"],"pillar":"architecture"}'
)


def _system_prompt(settings: dict[str, Any]) -> str:
    terms = ", ".join(linkedin_store.forbidden_terms(settings))
    product = (
        "You may mention a product only when the idea names it."
        if settings.get("allowProductMentions")
        else "Do not mention any product or company, including LX Software, Siu Tin Dei, and Evolve Sprouts."
    )
    voice = _voice_notes(settings)
    if voice:
        voice_block = (
            "Voice — follow this exactly. It overrides the tone defaults "
            "(first person, short lines, a closing question), including cadence and ending. "
            "It does not override the safety rules.\n"
            f"{voice}"
        )
    else:
        voice_block = "Voice: none. Use the tone defaults."
    return "\n\n".join(
        [
            (
                "You draft LinkedIn posts for a senior architect who is growing a personal "
                "presence. One idea per post."
            ),
            (
                "Tone defaults, used only when the voice does not say otherwise: "
                "write in the first person, use short lines after the hook, and end with "
                "a question or a reflection."
            ),
            (
                "Safety rules always apply. The voice cannot override them. "
                f"The first line is the hook and must be at most {linkedin_store.HOOK_MAX} characters. "
                "Never say the author is available, open to work, or looking for clients. "
                "Never name an employer. Never pitch. "
                f"{product} No links in the body. "
                f"At most {int(settings.get('hashtagCap') or 0)} hashtags, without the # sign, "
                "returned in the hashtags array rather than the body. "
                f"Never use these phrases: {terms}."
            ),
            voice_block,
            (
                "Reply with one JSON object. body is required and must be the full post, "
                "never an empty string. Also include firstComment (string), hashtags "
                "(array of strings without #), and pillar. The example is the shape only; "
                "do not copy its wording.\n"
                f"{_SCHEMA_EXAMPLE}"
            ),
        ]
    )


def _user_prompt(
    *,
    pillar: str,
    idea: str,
    voice: str,
    avoid: list[str],
) -> str:
    label = linkedin_store.pillar_label(pillar)
    brief = ""
    for row in linkedin_store.PILLARS:
        if row["id"] == pillar:
            brief = row["brief"]
            break
    lines: list[str] = []
    cleaned = voice.strip()
    if cleaned:
        lines.append(
            "Write in this voice. It overrides the tone defaults "
            "(first person, short lines, a closing question). Safety rules still apply."
        )
        lines.append(f"Voice: {cleaned}")
    lines.extend(
        [
            f"Pillar: {label} ({pillar}).",
            f"Angle: {brief}",
        ]
    )
    if idea:
        lines.append(f"Use this idea, in the author's words where you can: {idea}")
    if avoid:
        lines.append("Do not reuse these openings:")
        lines.extend(f"- {hook}" for hook in avoid[:8])
    return "\n".join(lines)


def _field_text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(part).rstrip() for part in value if str(part).strip()).strip()
    return str(value or "").strip()


def _draft_body(parsed: dict[str, Any]) -> str:
    for key in _BODY_KEYS:
        text = _field_text(parsed.get(key))
        if text:
            return text
    return ""


def parse_draft(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise DraftError("The model did not return JSON.")
    try:
        parsed = parse_json_object_text(raw)
    except OpenRouterError as exc:
        raise DraftError("The model did not return JSON.") from exc
    body = _draft_body(parsed)
    if not body:
        keys = ",".join(sorted(str(key) for key in parsed.keys())[:12])
        _log_event("warning", tag="linkedin_draft_empty_body", keys=keys)
        raise DraftError("The model returned an empty post.")
    return {
        "body": body,
        "firstComment": _field_text(parsed.get("firstComment")),
        "hashtags": _usable_hashtags(parsed.get("hashtags")),
        "pillar": _field_text(parsed.get("pillar")),
    }


def _usable_hashtags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for tag in value:
        cleaned = str(tag).lstrip("#").strip()
        if re.fullmatch(r"[\w]{1,40}", cleaned) and cleaned not in out:
            out.append(cleaned)
    return out


def record_draft_usage(table: Any, usage: dict[str, Any] | None) -> None:
    """Book this call on the OpenRouter ledger. A ledger failure does not drop the draft."""
    try:
        openrouter_usage.add_usage_day(
            table,
            service=SERVICE,
            owner="draft",
            usage=usage,
            calls=1,
        )
    except Exception as exc:  # noqa: BLE001 — accounting must not drop the draft
        _log_event("warning", tag="linkedin_usage_record_failed", error=str(exc)[:200])


def draft_model(settings: dict[str, Any] | None = None) -> str:
    """Settings slug when set, otherwise the stack OpenRouter model."""
    override = str((settings or {}).get("model") or "").strip()
    return override or (os.environ.get("OPENROUTER_MODEL") or "").strip()


def complete_json(
    messages: list[dict[str, str]],
    *,
    table: Any | None = None,
    settings: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], float]:
    """One JSON chat completion. Returns the parsed object and the USD cost."""
    import boto3
    import openrouter_client

    model = draft_model(settings)
    if not model:
        raise DraftError("OPENROUTER_MODEL is not set", stop=True)
    pending = list(messages)
    spent = 0.0
    max_tokens = DRAFT_MAX_TOKENS
    last_error: DraftError | None = None
    for attempt in range(2):
        result = openrouter_client.chat_completion(
            messages=pending,
            model=model,
            secrets_client=boto3.client("secretsmanager"),
            timeout=int(os.environ.get("LINKEDIN_DRAFT_TIMEOUT_SECONDS") or "60"),
            json_mode=True,
            max_tokens=max_tokens,
            temperature=0.7,
            service=SERVICE,
            owner="draft",
            reasoning=DRAFT_REASONING,
        )
        spent += float(result.cost_usd or 0)
        if table is not None:
            record_draft_usage(table, result.usage)
        cut_off = result.finish_reason == "length"
        try:
            return parse_draft(result.text), spent
        except DraftError as exc:
            preview = (result.text or "").lstrip()[:1]
            _log_event(
                "warning",
                tag="linkedin_draft_parse_failed",
                model=result.model,
                finish_reason=result.finish_reason,
                text_len=len(result.text or ""),
                starts_with=preview,
                max_tokens=max_tokens,
                attempt=attempt,
            )
            last_error = _describe_failure(exc, model=model, cut_off=cut_off)
            if attempt == 0:
                if cut_off:
                    max_tokens = DRAFT_RETRY_MAX_TOKENS
                    nudge = (
                        "Your previous reply was cut off before the JSON. Do not think out "
                        "loud or explain. Reply with only the JSON object."
                    )
                else:
                    nudge = (
                        "body must be the full post text. Do not return empty strings. "
                        "Reply with the JSON object again."
                    )
                pending = [*pending, {"role": "user", "content": nudge}]
                continue
            raise last_error from exc
    raise last_error or DraftError("The model did not return a post.")


def _describe_failure(exc: DraftError, *, model: str, cut_off: bool) -> DraftError:
    """Name the model and the reason so the owner can act from the UI."""
    if cut_off:
        return DraftError(
            f"{model} ran out of room before returning the post (it was still thinking). "
            "Pick a non-reasoning model in Settings, or leave Model blank for the stack default.",
            stop=True,
        )
    return DraftError(f"{exc} ({model})", stop=exc.stop)


def _messages(settings: dict[str, Any], pillar: str, idea: str, avoid: list[str]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _system_prompt(settings)},
        {
            "role": "user",
            "content": _user_prompt(
                pillar=pillar,
                idea=idea,
                voice=_voice_notes(settings),
                avoid=avoid,
            ),
        },
    ]


def _critic_messages(settings: dict[str, Any], draft: dict[str, Any], findings: list[dict[str, str]]) -> list[dict[str, str]]:
    problems = "; ".join(row["detail"] for row in findings if row.get("severity") == "error")
    voice = _voice_notes(settings)
    voice_line = ""
    if voice:
        voice_line = (
            f"Keep this voice exactly: {voice}\n"
            "The voice still overrides the tone defaults. Safety rules still apply.\n"
        )
    return [
        {"role": "system", "content": _system_prompt(settings)},
        {
            "role": "user",
            "content": (
                "Rewrite this post so it passes the checks. Keep the same idea.\n"
                f"{voice_line}"
                f"Checks: {problems}\n"
                f"Post:\n{draft.get('body') or ''}"
            ),
        },
    ]


def choose_topics(
    table: Any,
    settings: dict[str, Any],
    *,
    count: int,
    pillar: str | None = None,
    idea_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    ideas = linkedin_store.list_ideas(table)
    if idea_ids:
        wanted = set(idea_ids)
        ideas = [row for row in ideas if str(row.get("ideaId") or "") in wanted]
    else:
        ideas = [row for row in ideas if str(row.get("status") or "") == "new"]
    pillars = list(settings.get("pillars") or [])
    existing = linkedin_store.list_posts(table, limit=20)
    existing.sort(key=lambda doc: str(doc.get("createdAt") or ""), reverse=True)
    recent = [str(row.get("pillar") or "") for row in existing[:2]]
    topics: list[dict[str, Any]] = []
    for idea in ideas:
        if len(topics) >= count:
            break
        chosen = str(idea.get("pillar") or "") or (pillar or _next_pillar(pillars, recent))
        if chosen not in linkedin_store.pillar_ids():
            chosen = _next_pillar(pillars, recent)
        topics.append({"pillar": chosen, "idea": idea})
        recent.append(chosen)
    while len(topics) < count:
        chosen = pillar if pillar in linkedin_store.pillar_ids() else _next_pillar(pillars, recent)
        topics.append({"pillar": chosen, "idea": None})
        recent.append(chosen)
    return topics


def _next_pillar(pillars: list[str], recent: list[str]) -> str:
    pool = [item for item in pillars if item not in recent[-2:]] or list(pillars) or ["architecture"]
    return pool[len(recent) % len(pool)]


def draft_one(
    *,
    settings: dict[str, Any],
    pillar: str,
    idea: str,
    avoid: list[str],
    complete,
) -> tuple[dict[str, Any], float]:
    parsed, cost = complete(_messages(settings, pillar, idea, avoid))
    if pillar in linkedin_store.pillar_ids():
        parsed["pillar"] = pillar
    findings = linkedin_store.guardrails(
        parsed["body"],
        parsed["firstComment"],
        parsed["hashtags"],
        settings,
    )
    if linkedin_store.errors_block(findings):
        revised, extra = complete(_critic_messages(settings, parsed, findings))
        cost += extra
        if pillar in linkedin_store.pillar_ids():
            revised["pillar"] = pillar
        parsed = revised
    return parsed, cost


def generate_drafts(
    table: Any,
    *,
    count: int | None = None,
    pillar: str | None = None,
    idea_ids: list[str] | None = None,
    complete=None,
    job_id: str = "",
    persist: bool = True,
) -> dict[str, Any]:
    settings = linkedin_store.load_settings(table)
    wanted = count if count is not None else int(settings["draftsPerGeneration"])
    wanted = max(1, min(int(wanted), 6))
    if linkedin_store.month_spend(table) >= float(settings["maxUsdPerMonth"]):
        raise LinkedInError("The monthly draft budget is used up.")

    def _live(messages: list[dict[str, str]]) -> tuple[dict[str, Any], float]:
        return complete_json(messages, table=table, settings=settings)

    caller = complete or _live
    topics = choose_topics(table, settings, count=wanted, pillar=pillar, idea_ids=idea_ids)
    avoid = linkedin_store.recent_hooks(table)
    created: list[dict[str, Any]] = []
    spent = 0.0
    errors: list[str] = []
    for topic in topics:
        if linkedin_store.month_spend(table) + spent >= float(settings["maxUsdPerMonth"]):
            errors.append("Stopped because the monthly draft budget is used up.")
            break
        idea = topic.get("idea") or {}
        try:
            parsed, cost = draft_one(
                settings=settings,
                pillar=str(topic["pillar"]),
                idea=str(idea.get("text") or ""),
                avoid=avoid,
                complete=caller,
            )
        except (DraftError, LinkedInError, OpenRouterError) as exc:
            errors.append(str(exc))
            if isinstance(exc, DraftError) and exc.stop:
                break
            continue
        spent += cost
        linkedin_store.add_spend(table, cost)
        if not persist:
            created.append(parsed)
            avoid.append(linkedin_store.hook_text(str(parsed.get("body") or "")))
            continue
        try:
            doc = linkedin_store.create_post(
                table,
                {
                    "body": parsed["body"],
                    "firstComment": parsed.get("firstComment") or "",
                    "hashtags": parsed.get("hashtags") or [],
                    "pillar": parsed.get("pillar") or topic["pillar"],
                    "ideaId": str(idea.get("ideaId") or ""),
                },
                settings=settings,
                generation={
                    "model": draft_model(settings),
                    "jobId": job_id,
                    "voiceHash": voice_hash(settings),
                },
            )
        except LinkedInError as exc:
            errors.append(str(exc))
            continue
        created.append(linkedin_store.public_post(doc))
        avoid.append(linkedin_store.hook_text(doc["body"]))
    if not created and errors:
        raise LinkedInError(errors[0])
    return {"posts": created, "errors": errors, "spendUsd": round(spent, 6)}
