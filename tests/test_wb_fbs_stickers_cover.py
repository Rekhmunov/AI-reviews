"""Cover sticker is first page when printing supply stickers."""

from __future__ import annotations

import unittest

from review_processor.wb_fbs_detail import (
    _ru_stickers_word,
    render_stickers_print_html,
)


class WbFbsStickersCoverTests(unittest.TestCase):
    def test_ru_stickers_word(self):
        self.assertEqual(_ru_stickers_word(1), "стикер")
        self.assertEqual(_ru_stickers_word(2), "стикера")
        self.assertEqual(_ru_stickers_word(5), "стикеров")
        self.assertEqual(_ru_stickers_word(11), "стикеров")
        self.assertEqual(_ru_stickers_word(21), "стикер")
        self.assertEqual(_ru_stickers_word(22), "стикера")

    def test_cover_is_first_and_excludes_separators_from_count(self):
        payload = {
            "detail": {
                "supply_id": "WB-GI-1",
                "name": "Склад Север / утро",
            },
            "source_name": "ИП Иванов ФБС",
            "groups": [
                {
                    "article": "A1",
                    "qty": 2,
                    "product_name": "Товар 1",
                    "orders": [
                        {"order_id": 101, "sticker_file": ""},
                        {"order_id": 102, "sticker_file": ""},
                    ],
                },
                {
                    "article": "A2",
                    "qty": 1,
                    "product_name": "Товар 2",
                    "orders": [
                        {"order_id": 103, "sticker_file": ""},
                    ],
                },
            ],
        }
        html = render_stickers_print_html(payload)
        cover_pos = html.find('class="label cover"')
        sep_pos = html.find('class="label separator"')
        self.assertGreater(cover_pos, 0)
        self.assertGreater(sep_pos, cover_pos)
        self.assertIn("Склад Север / утро", html)
        self.assertIn("ИП Иванов ФБС", html)
        self.assertIn('class="cover-source"', html)
        # 3 order stickers; 2 article separators are not counted
        self.assertIn("3 стикера", html)
        self.assertEqual(html.count('class="label cover"'), 1)
        self.assertEqual(html.count('class="label separator"'), 2)

    def test_cover_omits_source_line_when_empty(self):
        html = render_stickers_print_html(
            {
                "detail": {"supply_id": "WB-GI-1", "name": "Поставка X"},
                "source_name": "",
                "groups": [
                    {
                        "article": "A",
                        "qty": 1,
                        "orders": [{"order_id": 1, "sticker_file": ""}],
                    }
                ],
            }
        )
        self.assertIn("Поставка X", html)
        self.assertNotIn('class="cover-source"', html)

    def test_no_cover_when_no_groups(self):
        html = render_stickers_print_html(
            {"detail": {"supply_id": "WB-GI-1", "name": "X"}, "groups": []}
        )
        self.assertNotIn('class="label cover"', html)
        self.assertIn("Нет стикеров", html)

    def test_falls_back_to_supply_id_when_name_empty(self):
        html = render_stickers_print_html(
            {
                "detail": {"supply_id": "WB-GI-999", "name": ""},
                "groups": [
                    {
                        "article": "A",
                        "qty": 1,
                        "orders": [{"order_id": 1, "sticker_file": ""}],
                    }
                ],
            }
        )
        self.assertIn("WB-GI-999", html)
        self.assertIn("1 стикер", html)


if __name__ == "__main__":
    unittest.main()
