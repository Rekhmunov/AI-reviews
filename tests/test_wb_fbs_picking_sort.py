"""Picking-list sort must match WB seller-portal order."""

from review_processor.wb_fbs_detail import _natural_sort_key, _sort_groups_like_wb


def test_natural_sort_sizes_like_portal():
    titles = [
        "Наматрасник непромокаемый 90х200 см",
        "Наматрасник непромокаемый 80х160 см",
        "Наматрасник непромокаемый 90х190 см",
        "Наматрасник непромокаемый 80х190 см",
    ]
    ordered = sorted(titles, key=_natural_sort_key)
    assert ordered == [
        "Наматрасник непромокаемый 80х160 см",
        "Наматрасник непромокаемый 80х190 см",
        "Наматрасник непромокаемый 90х190 см",
        "Наматрасник непромокаемый 90х200 см",
    ]


def test_group_sort_uses_wb_title_not_article_alphabet():
    """Article alphabet puts nepnam… before white23; portal uses title sizes."""
    groups = [
        {
            "article": "nepnam9020025whitebort9020025",
            "product_name": "Наматрасник",
            "wb_title": "Наматрасник непромокаемый 90х200 см",
            "nm_id": 4,
            "orders": [
                {"sticker_part_b": "8568", "sticker_part_a": "1", "order_id": 5},
                {"sticker_part_b": "4011", "sticker_part_a": "1", "order_id": 1},
            ],
        },
        {
            "article": "white23",
            "product_name": "Наматрасник",
            "wb_title": "Наматрасник непромокаемый 80х160 см",
            "nm_id": 1,
            "orders": [
                {"sticker_part_b": "9833", "sticker_part_a": "1", "order_id": 13},
                {"sticker_part_b": "7671", "sticker_part_a": "1", "order_id": 12},
            ],
        },
        {
            "article": "white27",
            "product_name": "Наматрасник",
            "wb_title": "Наматрасник непромокаемый 90х190 см",
            "nm_id": 3,
            "orders": [
                {"sticker_part_b": "7387", "sticker_part_a": "1", "order_id": 6},
                {"sticker_part_b": "2658", "sticker_part_a": "1", "order_id": 1},
            ],
        },
        {
            "article": "white25",
            "product_name": "Наматрасник",
            "wb_title": "Наматрасник непромокаемый 80х190 см",
            "nm_id": 2,
            "orders": [
                {"sticker_part_b": "9870", "sticker_part_a": "1", "order_id": 5},
                {"sticker_part_b": "0164", "sticker_part_a": "1", "order_id": 1},
            ],
        },
    ]
    sorted_groups = _sort_groups_like_wb(groups)
    assert [g["article"] for g in sorted_groups] == [
        "white23",
        "white25",
        "white27",
        "nepnam9020025whitebort9020025",
    ]
    assert [o["sticker_part_b"] for o in sorted_groups[1]["orders"]] == ["0164", "9870"]
    assert [o["sticker_part_b"] for o in sorted_groups[2]["orders"]] == ["2658", "7387"]
