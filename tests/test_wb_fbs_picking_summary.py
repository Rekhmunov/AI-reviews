"""Picking list starts with a one-column summary page."""

import re

from review_processor.wb_fbs_detail import render_picking_list_html


def test_picking_list_summary_page_has_only_sobrano():
    payload = {
        "detail": {"supply_id": "S1", "created_date": "2026-08-07", "order_count": 3},
        "groups": [
            {
                "product_name": "Товар A",
                "qty": 2,
                "orders": [
                    {"order_id": 1, "sticker_part_a": "a", "sticker_part_b": "11"},
                    {"order_id": 2, "sticker_part_a": "b", "sticker_part_b": "22"},
                ],
                "barcodes": ["111"],
            },
            {
                "product_name": "Товар A",
                "qty": 1,
                "orders": [
                    {"order_id": 3, "sticker_part_a": "c", "sticker_part_b": "33"},
                ],
                "barcodes": ["222"],
            },
            {
                "product_name": "Товар B",
                "qty": 1,
                "orders": [
                    {"order_id": 4, "sticker_part_a": "d", "sticker_part_b": "44"},
                ],
                "barcodes": [],
            },
        ],
    }
    html = render_picking_list_html(payload)
    assert "summary-page" in html
    assert "detail-page" in html
    assert "Товар A — 3 шт." in html
    assert "Товар B — 1 шт." in html

    summary = re.search(r'class="summary-page".*?</section>', html, re.S).group(0)
    assert "Всего 3 заказа" in summary
    assert "Собрано" in summary
    assert "Упаковано" not in summary

    detail = re.search(r'class="detail-page".*?</section>', html, re.S).group(0)
    assert "Собрано" in detail
    assert "Упаковано" in detail
