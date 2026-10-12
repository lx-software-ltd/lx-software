"""Story tones for LinkedIn drafts.

``RECOMMENDED_VOICE`` is the default and the Over lunch note. The other three
notes are the same register with a different stance. Each stays under the
1000-character voice limit and quotes no catchphrase. Mirrored as
``RECOMMENDED_LINKEDIN_VOICE`` and ``LINKEDIN_STORY_VOICES`` in
``linkedinModel.ts``.
"""

from __future__ import annotations

# Shown in Settings as "Use recommended voice" and used until the owner writes
# their own. Kept under the 1000-character voice limit. Derived from a post the
# owner wrote: a plain opening line, a story told in order, honest hedging, an
# answered objection at the end.
RECOMMENDED_VOICE = (
    "First person singular, always I, never we. Conversational, as if I were telling a "
    "former colleague over lunch what I have been building. No hook: the first line is "
    "plain and specific to this story, not a question, not a claim. Tell it in the order it "
    "happened: what I noticed, what I decided, what I built, where it broke, where it "
    "stands now. Name the real constraint (a full-time job, nights and weekends, a month of "
    "evenings) and real figures when I have them. Plain dashes for a short list. One-line "
    "paragraphs are fine. Dry, understated, a little self-deprecating; an aside now and "
    "then. Admit what is unfinished and what might fail. No sensationalism, no wow, no "
    "lesson headline, no moral, no call to action. Each post has its own shape: a "
    "different way in and a different way out from the last one, no stock opening line, no "
    "stock closing line, no catchphrase carried from post to post. Usually 200 to 450 words."
)

_AT_THE_BREAK_VOICE = (
    "First person singular, always I, never we. Stand at the moment it broke. The first concrete "
    "thing is the figure or the limit, in words specific to this story; background comes after that, "
    "only as much as the reader needs. Short sentences. One-line paragraphs are fine. Name the real "
    "constraint and real figures when I have them. Dry and understated. Admit what is unfinished. "
    "No sensationalism, no wow, no lesson headline, no moral, no call to action. End on the current "
    "state or figure, with no comment on it. The shape for this draft still chooses the way in and "
    "the way out. Each post has its own shape: a different way in and a different way out from the "
    "last one, no stock opening line, no stock closing line, no catchphrase carried from post to "
    "post. Usually 200 to 350 words."
)
_THEY_ASKED_VOICE = (
    "First person singular, always I, never we. This post answers a question a colleague actually "
    "asked. The first line is plain and names the situation, not a claim and not a lesson. Their "
    "question appears in their words. Then how I found the answer: what I looked at, what I tried, "
    "where it broke. Name the real constraint and real figures when I have them. Plain dashes for a "
    "short list. One-line paragraphs are fine. Dry and understated. No sensationalism, no wow, no "
    "lesson headline, no moral, no call to action. End with the answer in one line, including the "
    "trade-off I accepted, without defending it. The shape for this draft still chooses the way in "
    "and the way out. Each post has its own shape: a different way in and a different way out from "
    "the last one, no stock opening line, no stock closing line, no catchphrase carried from post "
    "to post. Usually 200 to 400 words."
)
_WHERE_IT_STANDS_VOICE = (
    "First person singular, always I, never we. Start from what the system does today, in one plain "
    "line specific to this story, not a claim and not a lesson. Then how it got there: what I "
    "noticed, what I decided, what I built, where it broke. Name the real constraint and real "
    "figures when I have them. One-line paragraphs are fine. Dry and understated, a little "
    "self-deprecating. No sensationalism, no wow, no lesson headline, no moral, no call to action. "
    "End by naming what is still unfinished, and stop. The shape for this draft still chooses the "
    "way in and the way out. Each post has its own shape: a different way in and a different way "
    "out from the last one, no stock opening line, no stock closing line, no catchphrase carried "
    "from post to post. Usually 200 to 400 words."
)
STORY_VOICES: tuple[dict[str, str], ...] = (
    {"id": "over-lunch", "label": "Over lunch", "notes": RECOMMENDED_VOICE},
    {"id": "at-the-break", "label": "At the break", "notes": _AT_THE_BREAK_VOICE},
    {"id": "they-asked", "label": "They asked", "notes": _THEY_ASKED_VOICE},
    {"id": "where-it-stands", "label": "Where it stands", "notes": _WHERE_IT_STANDS_VOICE},
)
