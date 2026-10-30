"""PDF export is a rendered copy of the paragraph map."""

from __future__ import annotations

import unittest

from test_support import install_aws_stubs

install_aws_stubs()

import resume_pdf  # noqa: E402
from resume_store import ResumeError  # noqa: E402


class ResumePdfTests(unittest.TestCase):
    def test_latin_resume_renders_a_pdf(self) -> None:
        data = resume_pdf.render(
            [
                {"id": "p0", "text": "Alex Example"},
                {"id": "p1", "text": "alex.example@example.com"},
                {"id": "p2", "text": "Built the billing export."},
            ],
            {
                "paragraphs": [
                    {"id": "p0", "role": "name"},
                    {"id": "p1", "role": "contact"},
                    {"id": "p2", "role": "summary"},
                ]
            },
            page_size="A4",
        )
        self.assertTrue(data.startswith(b"%PDF"))

    def test_cjk_uses_the_static_font_or_explains_the_limit(self) -> None:
        paragraphs = [{"id": "p0", "text": "個人簡介"}]
        layout = {"paragraphs": [{"id": "p0", "role": "summary"}]}
        if resume_pdf.cjk_supported():
            data = resume_pdf.render(paragraphs, layout)
            self.assertTrue(data.startswith(b"%PDF"))
            return
        with self.assertRaises(ResumeError) as caught:
            resume_pdf.render(paragraphs, layout)
        self.assertIn("Latin-only", str(caught.exception))
