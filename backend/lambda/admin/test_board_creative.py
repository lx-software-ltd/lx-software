"""Creative card rendering (WP7)."""

from __future__ import annotations

import unittest
from io import BytesIO

from PIL import Image

import board_creative


class CreativeTests(unittest.TestCase):
    def test_every_template_both_languages(self) -> None:
        fields = {"title": "Saturday play in Sha Tin", "body": "Free listing at launch.", "pillar": "activity spotlight"}
        zh = {"title": "沙田週末玩樂", "body": "推出時免費上架。", "pillar": "activity spotlight"}
        for template in board_creative.TEMPLATES:
            card = board_creative.render_card(template, fields, lang="en")
            story = board_creative.render_story(template, fields, lang="en")
            card_zh = board_creative.render_card(template, zh, lang="zh-HK")
            self.assertTrue(card.startswith(b"\x89PNG"))
            self.assertEqual(Image.open(BytesIO(card)).size, (1080, 1080))
            self.assertEqual(Image.open(BytesIO(story)).size, (1080, 1920))
            self.assertEqual(Image.open(BytesIO(card_zh)).size, (1080, 1080))

    def test_wraps_long_chinese(self) -> None:
        text = "沙田" * 100
        font = board_creative._pick_font(lang="zh-HK", bold=False, size=36)
        lines = board_creative.wrap_text(text, font, 800, max_lines=6)
        self.assertLessEqual(len(lines), 6)
        self.assertTrue(any(lines))


if __name__ == "__main__":
    unittest.main()
