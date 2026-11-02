"""The shape of a LinkedIn post that gets past the first wave.

LinkedIn shows a new post to a small sample of followers and widens it only
when that sample engages within the first hours. The eight posts published
in October 2026 measured this directly (``docs/architecture/linkedin-reach.md``):
seven engineering posts reached 141 to 475 people each, collected 0 to 7
engagements, and fell to 11 to 45 percent of their day-one impressions on
day two; one personal post collected 110 engagements on day one, held 80
percent on day two, and reached 26,498. The people who saw the engineering
posts reacted at a normal rate (1.25 percent against 0.73 percent for the
personal post). What differed was the first line, the length, the setting,
and the ending. Those are the rules here. They are substance rules: the
voice cannot override them, and ``reach_findings`` sends a draft that breaks
a measurable one to the rewrite pass. The shape rotation lives here too,
because the opening, the closing, and the length are what these rules govern.
"""

from __future__ import annotations

import re

import linkedin_store

# The feed preview on a phone cuts the first line well before the 210-character
# hard cap in linkedin_store. Hooks of 49 to 106 characters drew the largest
# first waves; the two hooks over 150 characters drew among the smallest.
HOOK_PREVIEW_MAX = 110
# The personal post was 206 words. The engineering posts averaged 342 and ran
# to 486. LENGTHS asks for 200 to 260; the check leaves room for the model.
BODY_WORDS_MAX = 300

# Each draft in a batch gets its own way in, way out, and length, so four posts
# written from the same voice and the same example do not share one template.
# The list lengths are coprime, so index i walks through different pairs, and
# the batch offset moves successive weeks onto different pairs again.
OPENINGS: tuple[str, ...] = (
    "one plain sentence about the person this broke for, in words specific to this story",
    "the moment it broke, mid-story, before any background",
    "the figure or the limit itself, then how I ran into it",
    "the decision I made, then back up to what led to it",
    "what the system does for someone today, in one line, then how it got there",
    "the question a colleague asked me, quoted, then my answer",
    "the small detail I noticed first, before I knew it mattered",
)
CLOSINGS: tuple[str, ...] = (
    "the obvious objection, named and answered honestly",
    "what is still unfinished, stated flatly",
    "the one thing I would do differently, in a line",
    "the current state or figure, with no comment on it",
    "the next thing I have to fix",
    "the trade-off I accepted, without defending it",
)
LENGTHS: tuple[str, ...] = (
    "about 200 words",
    "about 250 words",
    "about 220 words",
    "about 260 words",
    "about 240 words",
)


def shape_for(index: int, offset: int = 0) -> dict[str, str]:
    """Opening, closing and length for draft ``index`` in a batch that starts at ``offset``."""
    at = max(0, int(index)) + max(0, int(offset))
    return {
        "open": OPENINGS[at % len(OPENINGS)],
        "close": CLOSINGS[at % len(CLOSINGS)],
        "length": LENGTHS[at % len(LENGTHS)],
    }


def reach_block() -> str:
    """The system-prompt paragraph. Sits after the substance rules and before the safety rules."""
    return (
        "Reach rules always apply. The voice cannot override them. They come from measuring "
        "the published posts: a post is shown to a small first wave and only spreads when that "
        "wave comments, so the first line, the length, and the ending decide its reach. "
        f"The first line fits the feed preview: at most {HOOK_PREVIEW_MAX} characters, and it "
        "carries a figure or a person (a number, a person's question, what broke for whom), "
        "never a system or technology name; posts that opened on a system name drew the "
        "smallest first wave. One line of setting early in the post, so a reader who only "
        "knows the personal posts recognises the author: what I build, for whom, around a "
        "full-time job, without naming a product. The sentence a non-engineer would repeat "
        "goes in the first third of the post, not near the end. Keep the body to 200 to 260 "
        "words. The engineering detail (exact values, names, configuration, the lines of the "
        "fix) goes in firstComment, 60 to 150 words, never empty; the body carries the story. "
        "The last line of the body is one question only a reader who has hit the same thing "
        "could answer in a sentence."
    )


_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def word_count(text: str) -> int:
    return len(_WORD.findall((text or "").lower()))


def reach_findings(body: str) -> list[dict[str, str]]:
    """Draft-time checks for the measurable reach rules. Same shape as ``guardrails`` findings.

    The first comment and the closing question are prompt rules only; see the
    open questions in ``docs/plans/linkedin-reach-rules.md``.
    """
    findings: list[dict[str, str]] = []
    text = body or ""
    hook = linkedin_store.hook_text(text)
    if len(hook) > HOOK_PREVIEW_MAX:
        findings.append(
            {
                "code": "reach",
                "severity": "error",
                "detail": (
                    f"The first line is {len(hook)} characters; the feed preview cuts it. "
                    f"Keep it within {HOOK_PREVIEW_MAX} and open on a figure or a person, "
                    "not a system name."
                ),
            }
        )
    words = word_count(text)
    if words > BODY_WORDS_MAX:
        findings.append(
            {
                "code": "reach",
                "severity": "error",
                "detail": (
                    f"The post is {words} words. Keep the body to 200 to 260 words and move "
                    "the detail into the first comment."
                ),
            }
        )
    return findings
