"""Picking-list group order follows WB supply first-seen articles; orders by partB."""

from review_processor.wb_fbs_detail import _sort_groups_like_wb


def test_groups_keep_first_seen_order_not_article_alphabet():
    groups = [
        {
            "article": "white23",
            "product_name": "Наматрасник",
            "nm_id": 1,
            "orders": [
                {"sticker_part_b": "9833", "sticker_part_a": "1", "order_id": 13},
                {"sticker_part_b": "7671", "sticker_part_a": "1", "order_id": 12},
            ],
        },
        {
            "article": "white25",
            "product_name": "Наматрасник",
            "nm_id": 2,
            "orders": [
                {"sticker_part_b": "9870", "sticker_part_a": "1", "order_id": 5},
                {"sticker_part_b": "0164", "sticker_part_a": "1", "order_id": 1},
            ],
        },
        {
            "article": "nepnam9020025whitebort9020025",
            "product_name": "Наматрасник",
            "nm_id": 4,
            "orders": [
                {"sticker_part_b": "4011", "sticker_part_a": "1", "order_id": 1},
            ],
        },
    ]
    sorted_groups = _sort_groups_like_wb(groups)
    assert [g["article"] for g in sorted_groups] == [
        "white23",
        "white25",
        "nepnam9020025whitebort9020025",
    ]
    assert [o["sticker_part_b"] for o in sorted_groups[0]["orders"]] == ["7671", "9833"]
    assert [o["sticker_part_b"] for o in sorted_groups[1]["orders"]] == ["0164", "9870"]
