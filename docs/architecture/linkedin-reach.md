# LinkedIn reach

What the first eight published posts measured, and the rules the draft
generator follows because of it. The rules are code in
`backend/lambda/admin/linkedin_reach.py` and the four story notes in
`linkedin_voices.py`. This page is the evidence behind them. Update the
numbers and the rules together.

## The measurement

Eight posts went out from the scheduler at 08:30 HKT between 8 and 29
October 2026, all with a generated black-and-white cartoon except the last,
which carried a photo. Seven were engineering stories. One was personal.
Numbers are from the LinkedIn creator analytics export on 2 November 2026
(the admin metrics refresh had stored nothing for any of them; see Open
questions). Follower count on that day: 2,104.

| Post (first line topic) | Date | Pillar | Words | First line | Impressions | Engagements | Rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Twenty years since Torino, ten in Hong Kong | 29 Oct | personal | 206 | 86 chars, three numbers, three places | 26,498 | 194 | 0.73% |
| Fourteen percent of generated JSON failed | 8 Oct | ai-practice | 371 | 74 chars, a figure | 475 | 7 | 1.47% |
| The tag key name looked too good to change | 10 Oct | questions | 348 | 49 chars, a mystery | 437 | 7 | 1.60% |
| "Why do I have to hit refresh twice?" my wife asked | 22 Oct | platforms | 486 | 106 chars, a person's question | 258 | 4 | 1.55% |
| Still on the marketing site I talked last time | 27 Oct | architecture | 345 | 150 chars, a system | 239 | 1 | 0.42% |
| The loading spinner kept spinning | 15 Oct | delivery | 293 | 95 chars, a symptom | 190 | 0 | 0% |
| The crawler for the AI staff system just stopped | 13 Oct | architecture | 362 | 152 chars, a system | 178 | 4 | 2.25% |
| Reliability is not a feature you add | 20 Oct | platforms | 187 | 91 chars, an aphorism | 141 | 1 | 0.71% |

Seven engineering posts together: 1,918 impressions, 24 engagements, 1.25%.
The personal post alone, in five days: 26,646 impressions, 194 engagements.

### How each post travelled

| Post | Day 1 | Day 2 | Day 2 as share of day 1 |
| --- | --- | --- | --- |
| Fourteen percent | 284 | 81 | 29% |
| Tag key | 243 | 109 | 45% |
| Crawler | 187 | 33 | 18% |
| Spinner | 150 | 18 | 12% |
| Reliability | 105 | 24 | 23% |
| Refresh twice | 214 | 33 | 15% |
| Marketing site | 133 | 14 | 11% |
| Hong Kong | 10,387 | 8,311 | 80%, then 3,634, 3,369, 945 |

New followers: 35 in the 23 days before the personal post (1.5 a day);
81 in the four days after it (39, 18, 12, 12), about 4% of the whole base.
Members reached in the 28-day window: 18,529, against 2,104 followers, so
roughly 85% of the people who saw the personal post did not follow the
author.

## What it means

LinkedIn shows a new post to a small first wave and widens it only when
that wave engages within the first hours. The engineering posts got a
first wave of 105 to 284 people (5 to 14% of followers), collected 0 to 6
engagements from it, and stopped: every one fell to under half its
day-one impressions on day two. The personal post collected 110
engagements on day one, held 80% on day two, and kept being handed to new
networks for four days.

The engineering posts were not rejected by the people who saw them. Their
engagement rate (1.25% aggregate, up to 2.25%) is higher than the personal
post's 0.73%. The problem is reach, not resonance.

The first wave shrank across consecutive engineering posts: 284, 243, 187,
150, 105. Each low-engagement post made the next sample smaller. The one
with a person's question as its first line bounced to 214; the next, which
opened on a system, fell to 133.

The two first lines that opened on a figure or a mystery (74 and 49
characters) drew the largest engineering first waves. The two that opened
on a system name and ran past 150 characters drew among the smallest. The
one abstract post, with no story, no number and an imperative ending, drew
the smallest of the month.

The personal post differed in four measurable ways: a first line of 86
characters built from numbers and places; 206 words; zero technical
vocabulary with eleven personal anchors; and a photo instead of the
seventh identical cartoon. It ended on a confession (ten years and no
Cantonese), which gave the first wave something to say.

Every one of the eight posts had an empty first comment. The draft prompt's
schema example showed `"firstComment":""`, and the model copied it.

## The rules the drafts follow

Substance rules in the system prompt (`linkedin_reach.reach_block`), which
the voice cannot override:

- The first line fits the feed preview: at most 110 characters
  (`HOOK_PREVIEW_MAX`), and it carries a figure or a person, never a system
  or technology name. The 210-character `HOOK_MAX` in `linkedin_store` stays
  as the hard cap.
- One line of setting early in the post, so a reader who only knows the
  personal posts recognises the author: what I build, for whom, around a
  full-time job, without naming a product.
- The sentence a non-engineer would repeat goes in the first third, not in
  paragraph six.
- The body is 200 to 260 words (`LENGTHS`); the check sends a draft over 300
  words (`BODY_WORDS_MAX`) to the rewrite pass. The engineering detail goes
  in `firstComment`, 60 to 150 words, never empty. The schema example now
  shows a filled first comment.
- The last line of the body is one question only a reader who has hit the
  same thing could answer in a sentence. `Agree?` and `Thoughts?` stay
  blocked.

Deterministic checks (`linkedin_reach.reach_findings`): first line over 110
characters, body over 300 words. Both send the draft to the rewrite pass.
The first comment and the closing question are prompt rules only for now;
see `docs/plans/linkedin-reach-rules.md`.

The four story notes say 200 to 260 words and allow the one closing
question. A saved copy of an earlier note loads as the current one
(`RETIRED_VOICES`).

## What the owner does

These are not in code. They are what the measurement says moves a post
from the first wave to the second.

- Be online for the first hour after 08:30. Post the first comment at once
  if the scheduler has not, and reply to every comment the same hour. A
  reply is an engagement and re-surfaces the post.
- Ask three to five specific people to comment, not react, in that hour.
  People from a different network carry the post out of yours.
- Alternate the pillars: two engineering posts, then one personal or
  in-between post written from the owner's own material. A personal post
  resets the first-wave size the engineering posts erode, and its new
  followers are in the next engineering post's first wave. The scheduler
  does not do this on its own because a personal post needs real material;
  add the idea under Ideas with the `personal` pillar.
- Vary the picture. Seven identical cartoons in a row are a pattern the
  feed learns to skip. A screenshot of the actual fix or a real photo breaks
  it.
- Post the next engineering piece while a personal post's followers are
  fresh; the tail was down to 945 impressions on day five.

## Open questions

- The admin metrics refresh (`linkedin_metrics.py`) stored `impressions:
  null` and `reactions: 0` for every post above, including the one that
  reached 26,498. Until that is fixed the LinkedIn creator export is the
  source of truth, and `GET /public/lx-software/linkedin/posts` returns
  text without numbers.
- One personal post is one data point. The rules above are the measurable
  differences, not a proof. Re-measure after four posts written under them
  and update this page.
