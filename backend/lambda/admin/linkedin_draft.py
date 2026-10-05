"""Draft LinkedIn posts for a personal presence, not a company page.

Settings voice controls tone. The tone defaults (first person, short lines, a
closing question) apply only where that voice is blank or silent. Substance
rules (one real situation, named system, concrete figures, no buzzwords) and
safety rules (hook length, no employer, no availability, no pitch, forbidden
phrases) always apply. With no owner idea, ``linkedin_seeds`` supplies a real
situation. Each draft in a batch is given its own shape (opening, closing,
length) and the openings and closings of the example, recent posts, and the
batch so far. A draft that uses a slop phrase or an emoji, or that opens,
closes, or phrases itself like one of those posts, gets the rewrite pass.
Deterministic checks in ``linkedin_store`` still run after the model returns.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any

import linkedin_image
import linkedin_seeds
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
# 0.7 made four drafts from one voice and one example converge on one template.
DRAFT_TEMPERATURE = 0.9


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

# Words and phrases that mark a generic post. A draft that uses one gets the
# rewrite pass; the stored guardrails are unchanged.
SLOP_PHRASES: tuple[str, ...] = (
    # The first twelve are quoted in the system prompt.
    "game-changer",
    "humbled",
    "here's the thing",
    "let that sink in",
    "in today's fast-paced",
    "thought leader",
    "unlock",
    "delve",
    "synergy",
    "leverage",
    "journey",
    "mindset",
    "game changer",
    "honored to",
    "honoured to",
    "in today's world",
    "thought leadership",
    "stakeholders",
    "move the needle",
    "double down",
    "at the end of the day",
    "it's not about",
    "the truth is",
    "hot take",
    "agree?",
    "thoughts?",
    "excited to",
    "thrilled to",
    "proud to announce",
    "mind-blowing",
    "incredible",
    "amazing",
    "insane",
    "massive",
)
# One "we" is a real conversation ("a former colleague and I ... we wondered").
# More than that is company voice. "us" and "ourselves" ride along with a "we"
# and are not counted again.
_WE = re.compile(r"(?<![\w])(we|we're|we've|we'll|we'd|our|ours)(?![\w])", re.I)
WE_ALLOWANCE = 1
# Pictographs, dingbats (✅ ❌ ➡), arrows, stars, and the emoji variation selector.
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2190-\u21FF\u2B00-\u2BFF\uFE0F]"
)


def slop_findings(body: str) -> list[dict[str, str]]:
    """Draft-time checks for generic writing. Same shape as ``guardrails`` findings."""
    findings: list[dict[str, str]] = []
    text = body or ""
    if _EMOJI.search(text):
        findings.append(
            {"code": "slop", "severity": "error", "detail": "Remove every emoji, arrow, and symbol."}
        )
    lowered = text.lower()
    for phrase in SLOP_PHRASES:
        if linkedin_store.contains_term(lowered, phrase):
            findings.append(
                {"code": "slop", "severity": "error", "detail": f"Remove “{phrase}”; say the specific thing instead."}
            )
    plural = len(_WE.findall(text))
    if plural > WE_ALLOWANCE:
        findings.append(
            {
                "code": "slop",
                "severity": "error",
                "detail": (
                    f"Write as I, not we. The post says we/our/us {plural} times; "
                    "one is fine for a real conversation."
                ),
            }
        )
    return findings


def _style_example(settings: dict[str, Any]) -> str:
    return str(settings.get("styleExample") or "").strip()


def style_example_hook(settings: dict[str, Any]) -> str:
    """First line of the example, so a draft does not reuse its opening."""
    return linkedin_store.hook_text(_style_example(settings))[:180]


# Each draft in a batch gets its own way in, way out, and length, so four posts
# written from the same voice and the same example do not share one template.
# The list lengths are coprime, so index i walks through different pairs, and
# the batch offset moves successive weeks onto different pairs again.
OPENINGS: tuple[str, ...] = (
    "one plain sentence that says what this post is about, in words specific to this story",
    "the moment it broke, mid-story, before any background",
    "the figure or the limit itself, then how I ran into it",
    "the decision I made, then back up to what led to it",
    "what the system does today, then how it got there",
    "the question a colleague asked me, quoted, then my answer",
    "the small detail I noticed first, before I knew it mattered",
)
CLOSINGS: tuple[str, ...] = (
    "the obvious objection, named and answered honestly",
    "what is still unfinished, stated flatly, and stop",
    "the one thing I would do differently, in a line",
    "the current state or figure, with no comment on it",
    "the next thing I have to fix",
    "the trade-off I accepted, without defending it",
)
LENGTHS: tuple[str, ...] = ("about 200 words", "about 300 words", "about 400 words", "about 250 words", "about 350 words")


def shape_for(index: int, offset: int = 0) -> dict[str, str]:
    """Opening, closing and length for draft ``index`` in a batch that starts at ``offset``."""
    at = max(0, int(index)) + max(0, int(offset))
    return {
        "open": OPENINGS[at % len(OPENINGS)],
        "close": CLOSINGS[at % len(CLOSINGS)],
        "length": LENGTHS[at % len(LENGTHS)],
    }


_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
REPEAT_NGRAM = 7
OPENING_WORDS = 3
CLOSING_WORDS = 4


def _words(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def _ngrams(words: list[str], size: int) -> set[tuple[str, ...]]:
    return {tuple(words[i : i + size]) for i in range(0, max(0, len(words) - size + 1))}


def repeat_findings(body: str, others: list[str]) -> list[dict[str, str]]:
    """A draft that opens, closes, or phrases itself like another post gets the rewrite pass.

    ``others`` are the example post, recent posts, and the drafts already written
    in this batch. The first opening match, the first closing match, and the first
    shared phrase are reported; the rewrite needs the reason, not a census.
    """
    findings: list[dict[str, str]] = []
    opening = _words(linkedin_store.hook_text(body))[:OPENING_WORDS]
    closing = _words(linkedin_store.closing_text(body))[:CLOSING_WORDS]
    grams = _ngrams(_words(body), REPEAT_NGRAM)
    seen_open = seen_close = seen_phrase = False
    for other in others:
        if not other or not other.strip():
            continue
        if not seen_open and len(opening) == OPENING_WORDS:
            if _words(linkedin_store.hook_text(other))[:OPENING_WORDS] == opening:
                seen_open = True
                findings.append(
                    {
                        "code": "repeat",
                        "severity": "error",
                        "detail": (
                            f"Opens the same way as another post (“{' '.join(opening)}…”). "
                            "Start somewhere else in the story."
                        ),
                    }
                )
        if not seen_close and len(closing) == CLOSING_WORDS:
            if _words(linkedin_store.closing_text(other))[:CLOSING_WORDS] == closing:
                seen_close = True
                findings.append(
                    {
                        "code": "repeat",
                        "severity": "error",
                        "detail": (
                            f"Ends the same way as another post (“{' '.join(closing)}…”). "
                            "End on something only this story has."
                        ),
                    }
                )
        if not seen_phrase:
            shared = grams & _ngrams(_words(other), REPEAT_NGRAM)
            if shared:
                phrase = " ".join(sorted(shared)[0])
                seen_phrase = True
                findings.append(
                    {
                        "code": "repeat",
                        "severity": "error",
                        "detail": f"Shares the phrase “{phrase}” with another post. Say it differently.",
                    }
                )
        if seen_open and seen_close and seen_phrase:
            break
    return findings


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
            "It does not override the substance or safety rules.\n"
            f"{voice}"
        )
    else:
        voice_block = "Voice: none. Use the tone defaults."
    example = _style_example(settings)
    example_block = ""
    if example:
        example_block = (
            "Example of the register, written by the author. Take from it only how plain "
            "the sentences are, how much is admitted, and how little is sold. Do not copy "
            "its structure, its opening formula, its closing move, its transitions, or any "
            "phrase from it. Each post you write must have a different way in and a "
            "different way out. A post that reads like a rewrite of this example is wrong.\n"
            f"---\n{example}\n---"
        )
    return "\n\n".join(
        block
        for block in [
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
                "Substance rules always apply. The voice cannot override them. "
                "Write as I, never as a company 'we'; 'we' is allowed once for a real "
                "conversation with a named person. Write about one real situation: name the "
                "system or technology, the constraint or limit, a concrete figure where there is "
                "one, what was tried, and what happened, in the order it happened. Do not open "
                "with the moral or a claim. A reader should learn something they could check. "
                "Do not generalise into advice about mindset, leadership, or 'the industry'. "
                "No sensationalism, no wow. No emojis, arrows, or symbols anywhere. No buzzwords "
                f"or filler: {', '.join(SLOP_PHRASES[:12])}. "
                "Do not open with a question or a one-word line. Do not end with 'Agree?' or "
                "'Thoughts?'. Each post has its own opening and its own ending; do not carry "
                "a formula, a transition, or a phrase from one post to the next."
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
            example_block,
            _picture_block(settings),
            _reply_block(settings),
        ]
        if block
    )


def _picture_block(settings: dict[str, Any]) -> str:
    if not settings.get("imagesEnabled"):
        return ""
    return (
        "Picture. Also return imageScene and imageCaption. imageScene is one sentence, "
        "third person: the author physically dealing with this post's problem, at a comic "
        "scale, in a detailed room. No second recognisable person, no logos, no brand names. "
        "At most one two-word label; screens are unreadable scribbles. imageCaption is the "
        "spoken line under the picture: first person, dry, 8 to 20 words, the understated "
        "reading of the situation. Not a description of the picture and not a summary of the "
        "post. Do not reuse this example or its words: 'The only list I've been on that also "
        "includes a member of the Executive Council.'"
    )


def _reply_block(settings: dict[str, Any]) -> str:
    fields = "firstComment (string), hashtags (array of strings without #), and pillar"
    if settings.get("imagesEnabled"):
        fields = (
            "firstComment (string), hashtags (array of strings without #), pillar, "
            "imageScene (string), and imageCaption (string)"
        )
    return (
        "Reply with one JSON object. body is required and must be the full post, "
        "never an empty string. Also include "
        f"{fields}. This JSON is the shape only; do not copy its wording.\n"
        f"{_SCHEMA_EXAMPLE}"
    )


def _shape_lines(shape: dict[str, str] | None) -> list[str]:
    if not shape:
        return []
    return [
        "Shape for this post, different from the other posts this week: "
        f"open with {shape['open']}. End with {shape['close']}. Length {shape['length']}. "
        "Do not use an opening or a closing that appears in the lists below."
    ]


def _user_prompt(
    *,
    pillar: str,
    idea: str,
    voice: str,
    avoid: list[str],
    avoid_closings: list[str] | None = None,
    shape: dict[str, str] | None = None,
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
        lines.append(
            "Write about this situation. Keep its specifics: the technology, the constraint, "
            "the figures, what was tried, what happened. Do not generalise it or swap in a "
            f"different example.\nSituation: {idea}"
        )
    lines.extend(_shape_lines(shape))
    if avoid:
        lines.append("Do not reuse these openings:")
        lines.extend(f"- {hook}" for hook in avoid[:8])
    if avoid_closings:
        lines.append("Do not reuse these closing lines:")
        lines.extend(f"- {line}" for line in avoid_closings[:8])
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
    scene = _field_text(parsed.get("imageScene"))[: linkedin_store.IMAGE_SCENE_MAX]
    caption = _field_text(parsed.get("imageCaption")).strip("'\"“”‘’")
    caption = caption[: linkedin_store.IMAGE_CAPTION_MAX]
    return {
        "body": body,
        "firstComment": _field_text(parsed.get("firstComment")),
        "hashtags": _usable_hashtags(parsed.get("hashtags")),
        "pillar": _field_text(parsed.get("pillar")),
        "imageScene": scene,
        "imageCaption": caption,
    }


def caption_findings(
    caption: str,
    settings: dict[str, Any],
    others: list[str],
) -> list[dict[str, str]]:
    """The spoken line under the picture, checked like a post and against recent captions."""
    text = str(caption or "").strip()
    if not text:
        return []
    findings = [
        row
        for row in linkedin_store.guardrails(text, "", [], settings)
        if row.get("code") != "hook"
    ]
    findings.extend(slop_findings(text))
    findings.extend(repeat_findings(text, others))
    return findings


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
            temperature=DRAFT_TEMPERATURE,
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


def _messages(
    settings: dict[str, Any],
    pillar: str,
    idea: str,
    avoid: list[str],
    *,
    avoid_closings: list[str] | None = None,
    shape: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _system_prompt(settings)},
        {
            "role": "user",
            "content": _user_prompt(
                pillar=pillar,
                idea=idea,
                voice=_voice_notes(settings),
                avoid=avoid,
                avoid_closings=avoid_closings,
                shape=shape,
            ),
        },
    ]


def _critic_messages(
    settings: dict[str, Any],
    draft: dict[str, Any],
    findings: list[dict[str, str]],
    *,
    shape: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    problems = "; ".join(row["detail"] for row in findings if row.get("severity") == "error")
    voice = _voice_notes(settings)
    voice_line = ""
    if voice:
        voice_line = (
            f"Keep this voice exactly: {voice}\n"
            "The voice still overrides the tone defaults. Safety rules still apply.\n"
        )
    shape_line = "".join(f"{line}\n" for line in _shape_lines(shape))
    picture = ""
    scene = str(draft.get("imageScene") or "")
    caption = str(draft.get("imageCaption") or "")
    if settings.get("imagesEnabled") and (scene or caption):
        picture = (
            f"Picture scene: {scene}\n"
            f"Picture caption: {caption}\n"
            "Return imageScene and imageCaption with the post. Change the caption when a check names it.\n"
        )
    return [
        {"role": "system", "content": _system_prompt(settings)},
        {
            "role": "user",
            "content": (
                "Rewrite this post so it passes the checks. Keep the same idea.\n"
                f"{voice_line}"
                f"{shape_line}"
                f"{picture}"
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
    existing = linkedin_store.list_posts(table, limit=400)
    existing.sort(key=lambda doc: str(doc.get("createdAt") or ""), reverse=True)
    recent = [str(row.get("pillar") or "") for row in existing[:2]]
    used_seeds = {str(row.get("seedId") or "") for row in existing if row.get("seedId")}
    topics: list[dict[str, Any]] = []
    for idea in ideas:
        if len(topics) >= count:
            break
        chosen = str(idea.get("pillar") or "") or (pillar or _next_pillar(pillars, recent))
        if chosen not in linkedin_store.pillar_ids():
            chosen = _next_pillar(pillars, recent)
        topics.append({"pillar": chosen, "idea": idea})
        recent.append(chosen)
    # With no owner idea left, a seed supplies the real situation so the model
    # does not invent a generic one.
    offset = 0
    while len(topics) < count:
        chosen = pillar if pillar in linkedin_store.pillar_ids() else _next_pillar(pillars, recent)
        seed = linkedin_seeds.pick_seed(pillar=chosen, used=used_seeds, offset=offset)
        offset += 1
        if seed is None:
            topics.append({"pillar": chosen, "idea": None})
        else:
            used_seeds.add(str(seed["id"]))
            seed_pillar = str(seed["pillar"])
            if seed_pillar in linkedin_store.pillar_ids() and not pillar:
                chosen = seed_pillar
            topics.append({"pillar": chosen, "idea": {"text": seed["text"], "seedId": seed["id"]}})
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
    others: list[str] | None = None,
    shape: dict[str, str] | None = None,
    captions: list[str] | None = None,
) -> tuple[dict[str, Any], float]:
    """One draft, with the single rewrite pass when a check fails.

    ``others`` are posts this draft must not resemble: the example, recent posts,
    and the batch so far. ``shape`` is the opening/closing/length for this draft.
    """
    siblings = [text for text in (others or []) if text and text.strip()]
    closings = [linkedin_store.closing_text(text)[:180] for text in siblings]
    closings = [line for line in closings if line]
    parsed, cost = complete(
        _messages(settings, pillar, idea, avoid, avoid_closings=closings, shape=shape)
    )
    if pillar in linkedin_store.pillar_ids():
        parsed["pillar"] = pillar
    findings = linkedin_store.guardrails(
        parsed["body"],
        parsed["firstComment"],
        parsed["hashtags"],
        settings,
    )
    findings.extend(slop_findings(parsed["body"]))
    findings.extend(repeat_findings(parsed["body"], siblings))
    if settings.get("imagesEnabled"):
        findings.extend(caption_findings(str(parsed.get("imageCaption") or ""), settings, captions or []))
    if linkedin_store.errors_block(findings):
        revised, extra = complete(_critic_messages(settings, parsed, findings, shape=shape))
        cost += extra
        if pillar in linkedin_store.pillar_ids():
            revised["pillar"] = pillar
        if not revised.get("imageScene"):
            revised["imageScene"] = parsed.get("imageScene") or ""
        if not revised.get("imageCaption"):
            revised["imageCaption"] = parsed.get("imageCaption") or ""
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
    # Posts this batch must not resemble: the example first, then recent posts,
    # then each draft as it is written. Openings and closings are quoted to the
    # model; the full text feeds repeat_findings.
    others: list[str] = []
    example = _style_example(settings)
    if example:
        others.append(example)
    recent = linkedin_store.recent_bodies(table)
    others.extend(recent)
    captions = linkedin_store.recent_captions(table)
    # Shapes rotate from where the last batch left off, so week two does not
    # open and close its four posts the way week one did.
    shape_offset = len(linkedin_store.list_posts(table, limit=400))
    created: list[dict[str, Any]] = []
    spent = 0.0
    errors: list[str] = []
    for index, topic in enumerate(topics):
        if linkedin_store.month_spend(table) + spent >= float(settings["maxUsdPerMonth"]):
            errors.append("Stopped because the monthly draft budget is used up.")
            break
        idea = topic.get("idea") or {}
        avoid = [linkedin_store.hook_text(text)[:180] for text in others]
        try:
            parsed, cost = draft_one(
                settings=settings,
                pillar=str(topic["pillar"]),
                idea=str(idea.get("text") or ""),
                avoid=[hook for hook in avoid if hook],
                complete=caller,
                others=others,
                shape=shape_for(index, shape_offset),
                captions=captions,
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
            others.append(str(parsed.get("body") or ""))
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
                    "seedId": str(idea.get("seedId") or ""),
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
        if settings.get("imagesEnabled"):
            try:
                doc = linkedin_image.queue_for_post(
                    table,
                    str(doc["postId"]),
                    scene=str(parsed.get("imageScene") or ""),
                    caption=str(parsed.get("imageCaption") or ""),
                    force=True,
                )
            except LinkedInError as exc:
                errors.append(str(exc))
            except Exception as exc:  # noqa: BLE001 — the draft is saved even when the picture cannot be queued
                _log_event("warning", tag="linkedin_image_enqueue_failed", error=str(exc)[:300])
                errors.append("The picture could not be queued.")
            else:
                caption = str((doc.get("image") or {}).get("caption") or "")
                if caption:
                    captions.append(caption)
        created.append(linkedin_store.public_post(doc))
        others.append(str(doc["body"]))
    if not created and errors:
        raise LinkedInError(errors[0])
    return {"posts": created, "errors": errors, "spendUsd": round(spent, 6)}
