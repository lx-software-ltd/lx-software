"""Deterministic checks on a tailored resume. No model call."""

from __future__ import annotations

import re
from typing import Any

from linkedin_draft import SLOP_PHRASES

REWRITABLE_ROLES = {
    "headline": "headline",
    "summary": "summary",
    "bullet": "bullets",
    "skills": "skills",
}
_NUMBER = re.compile(r"(?:HK\$|US\$|[$£€¥])?\d[\d,]*(?:\.\d+)?%?")
_CAPITALS = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")
_CJK = re.compile(r"[\u4e00-\u9fff]{2,}")
_DEGREES = (
    "phd",
    "ph.d",
    "msc",
    "m.sc",
    "bsc",
    "b.sc",
    "mba",
    "bachelor",
    "master",
    "doctorate",
)
_SKILL_SPLIT = re.compile(r"[,;/|•·]+")


def rewritable_ids(paragraphs: list[dict[str, Any]], layout: dict[str, Any], settings: dict[str, Any]) -> set[str]:
    roles = {str(item.get("id")): str(item.get("role") or "other") for item in layout.get("paragraphs") or []}
    overrides = layout.get("overrides") or {}
    scope = set(settings.get("rewriteScope") or [])
    allowed: set[str] = set()
    for paragraph in paragraphs:
        paragraph_id = str(paragraph.get("id"))
        override = overrides.get(paragraph_id)
        if override == "locked":
            continue
        if override == "rewritable":
            allowed.add(paragraph_id)
            continue
        needed = REWRITABLE_ROLES.get(roles.get(paragraph_id, ""))
        if needed and needed in scope:
            allowed.add(paragraph_id)
    return allowed


def _texts(paragraphs: list[dict[str, Any]]) -> dict[str, str]:
    return {str(item.get("id")): str(item.get("text") or "") for item in paragraphs}


def _roles(layout: dict[str, Any]) -> dict[str, str]:
    return {str(item.get("id")): str(item.get("role") or "other") for item in layout.get("paragraphs") or []}


def _proposed(
    paragraphs: list[dict[str, Any]],
    layout: dict[str, Any],
    output: dict[str, Any],
) -> dict[str, str]:
    proposed = _texts(paragraphs)
    for item in list(output.get("replacements") or []) + list(output.get("skills") or []):
        proposed[str(item.get("id"))] = str(item.get("text") or "")
    groups = {str(group.get("headerId")): group for group in layout.get("roles") or []}
    for spec in output.get("roles") or []:
        group = groups.get(str(spec.get("headerId")))
        if not group:
            continue
        ids = [str(item) for item in group.get("bulletIds") or []]
        texts = [str(item) for item in spec.get("bullets") or []]
        for bullet_id, text in zip(ids, texts, strict=False):
            proposed[bullet_id] = text
        for index, text in enumerate(texts[len(ids) :]):
            proposed[f"{spec.get('headerId')}:extra:{index}"] = text
    return proposed


def _numbers(text: str) -> set[str]:
    found: set[str] = set()
    for match in _NUMBER.findall(text):
        token = match.replace(",", "")
        if token:
            found.add(token)
    return found


def _skill_tokens(text: str) -> set[str]:
    return {part.strip().casefold() for part in _SKILL_SPLIT.split(text) if part.strip()}


def check(
    *,
    paragraphs: list[dict[str, Any]],
    layout: dict[str, Any],
    settings: dict[str, Any],
    output: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Return blocking findings and notes. Notes are saved; blocking findings reject the draft."""
    blocking: list[str] = []
    notes: list[str] = []
    allowed = rewritable_ids(paragraphs, layout, settings)
    original = _texts(paragraphs)
    roles = _roles(layout)
    template_text = "\n".join(original.values())
    template_fold = template_text.casefold()
    template_numbers = _numbers(template_text.replace(",", ""))
    scope = set(settings.get("rewriteScope") or [])
    changed_ids: set[str] = set()

    for item in list(output.get("replacements") or []) + list(output.get("skills") or []):
        paragraph_id = str(item.get("id") or "")
        changed_ids.add(paragraph_id)
        if paragraph_id not in allowed:
            blocking.append(f"Rewrote locked paragraph {paragraph_id}.")
    if "bullets" in scope:
        template_groups = list(layout.get("roles") or [])
        returned = list(output.get("roles") or [])
        if len(returned) != len(template_groups):
            blocking.append("The number of roles changed.")
        else:
            policy = str(settings.get("bulletPolicy") or "keep")
            for group, spec in zip(template_groups, returned, strict=False):
                header = str(group.get("headerId") or "")
                if str(spec.get("headerId") or "") != header:
                    blocking.append(f"Role {header} was renamed or removed.")
                    continue
                before = len(group.get("bulletIds") or [])
                after = len(spec.get("bullets") or [])
                delta = abs(after - before)
                limit = 0 if policy == "keep" else 1
                if delta > limit:
                    blocking.append(f"Role {header} changed its bullet count.")

    proposed = _proposed(paragraphs, layout, output)
    new_chunks: list[str] = []
    old_total = 0
    new_total = 0
    for paragraph_id in allowed:
        old = original.get(paragraph_id, "")
        new = proposed.get(paragraph_id, old)
        old_total += len(old)
        new_total += len(new)
        if new == old:
            continue
        new_chunks.append(new)
        base = max(len(old), 1)
        if len(new) > int(base * 1.2) + 1:
            blocking.append(f"{paragraph_id} is more than 20% longer than the template.")
    for key, text in proposed.items():
        if ":extra:" in key:
            new_chunks.append(text)
            new_total += len(text)
    if old_total and new_total > int(old_total * 1.1) + 1:
        blocking.append("The resume is more than 10% longer than the template.")

    combined = "\n".join(new_chunks)
    for token in _numbers(combined):
        if token not in template_numbers:
            blocking.append(f"Introduced a number that is not in the template: {token}.")
    for phrase in _CAPITALS.findall(combined):
        if phrase.casefold() not in template_fold:
            blocking.append(f"Introduced a name that is not in the template: {phrase}.")
    for phrase in _CJK.findall(combined):
        if phrase not in template_text:
            blocking.append(f"Introduced wording that is not in the template: {phrase}.")
    folded = combined.casefold()
    for degree in _DEGREES:
        if degree in folded and degree not in template_fold:
            blocking.append(f"Introduced a credential that is not in the template: {degree}.")
    for phrase in SLOP_PHRASES:
        if phrase.casefold() in folded:
            blocking.append(f"Filler wording is not allowed: {phrase}.")

    if "skills" in scope:
        skill_ids = [paragraph_id for paragraph_id, role in roles.items() if role == "skills"]
        template_skills: set[str] = set()
        for paragraph_id in skill_ids:
            template_skills |= _skill_tokens(original.get(paragraph_id, ""))
        proposed_skills: set[str] = set()
        for paragraph_id in skill_ids:
            proposed_skills |= _skill_tokens(proposed.get(paragraph_id, ""))
        added = sorted(proposed_skills - template_skills)
        if added and not settings.get("allowNewSkills"):
            blocking.append("New skills are turned off: " + ", ".join(added) + ".")
        elif added:
            notes.append("New skills to confirm: " + ", ".join(added) + ".")
    return blocking, notes
