"""Tailor guardrails reject invented facts and keep locked paragraphs out of scope."""

from __future__ import annotations

import unittest

from test_support import install_aws_stubs

install_aws_stubs()

import resume_guard  # noqa: E402

PARAGRAPHS = [
    {"id": "p0", "text": "Alex Example"},
    {"id": "p1", "text": "Engineer"},
    {"id": "p2", "text": "Built the billing export for Northwind."},
    {"id": "p3", "text": "Python, TypeScript"},
]
LAYOUT = {
    "paragraphs": [
        {"id": "p0", "role": "name"},
        {"id": "p1", "role": "headline"},
        {"id": "p2", "role": "summary"},
        {"id": "p3", "role": "skills"},
    ],
    "roles": [],
    "overrides": {},
}
SETTINGS = {
    "rewriteScope": ["headline", "summary", "bullets", "skills"],
    "bulletPolicy": "keep",
    "allowNewSkills": False,
}


class ResumeGuardTests(unittest.TestCase):
    def test_locked_name_is_not_rewritable(self) -> None:
        allowed = resume_guard.rewritable_ids(PARAGRAPHS, LAYOUT, SETTINGS)
        self.assertNotIn("p0", allowed)
        self.assertIn("p1", allowed)
        self.assertIn("p2", allowed)

    def test_override_locks_a_rewritable_paragraph(self) -> None:
        layout = {**LAYOUT, "overrides": {"p2": "locked"}}
        allowed = resume_guard.rewritable_ids(PARAGRAPHS, layout, SETTINGS)
        self.assertNotIn("p2", allowed)

    def test_new_number_name_and_skill_are_blocking(self) -> None:
        blocking, notes = resume_guard.check(
            paragraphs=PARAGRAPHS,
            layout=LAYOUT,
            settings=SETTINGS,
            output={
                "replacements": [
                    {"id": "p1", "text": "Staff engineer who will unlock 12 platforms"},
                    {"id": "p2", "text": "Built the billing export for Contoso Labs."},
                ],
                "skills": [{"id": "p3", "text": "Python, Rust"}],
            },
        )
        self.assertFalse(notes)
        joined = " ".join(blocking)
        self.assertIn("12", joined)
        self.assertIn("Contoso Labs", joined)
        self.assertIn("unlock", joined)
        self.assertIn("rust", joined)

    def test_same_facts_pass(self) -> None:
        blocking, notes = resume_guard.check(
            paragraphs=PARAGRAPHS,
            layout=LAYOUT,
            settings=SETTINGS,
            output={
                "replacements": [
                    {"id": "p1", "text": "Engineer"},
                    {"id": "p2", "text": "Built the billing export."},
                ],
                "skills": [{"id": "p3", "text": "Python, TypeScript"}],
            },
        )
        self.assertEqual(blocking, [])
        self.assertEqual(notes, [])

    def test_new_skill_is_a_note_when_allowed(self) -> None:
        settings = {**SETTINGS, "allowNewSkills": True}
        blocking, notes = resume_guard.check(
            paragraphs=PARAGRAPHS,
            layout=LAYOUT,
            settings=settings,
            output={"skills": [{"id": "p3", "text": "Python, TypeScript, Go"}]},
        )
        self.assertEqual(blocking, [])
        self.assertTrue(any("go" in note for note in notes))

    def test_bullet_count_stays_unless_flex(self) -> None:
        paragraphs = PARAGRAPHS + [
            {"id": "p4", "text": "Engineer, Northwind 2020"},
            {"id": "p5", "text": "Shipped the billing export"},
        ]
        layout = {
            "paragraphs": LAYOUT["paragraphs"] + [{"id": "p4", "role": "role_header"}, {"id": "p5", "role": "bullet"}],
            "roles": [{"headerId": "p4", "bulletIds": ["p5"]}],
            "overrides": {},
        }
        output = {"roles": [{"headerId": "p4", "bullets": ["Shipped the billing export", "Kept the same tools"]}]}
        blocking, _notes = resume_guard.check(paragraphs=paragraphs, layout=layout, settings=SETTINGS, output=output)
        self.assertTrue(any("bullet count" in row for row in blocking))
        flex = {**SETTINGS, "bulletPolicy": "flex"}
        flex_blocking, _flex_notes = resume_guard.check(
            paragraphs=paragraphs, layout=layout, settings=flex, output=output
        )
        self.assertFalse(any("bullet count" in row for row in flex_blocking))
