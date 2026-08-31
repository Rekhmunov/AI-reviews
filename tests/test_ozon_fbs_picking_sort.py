"""Ozon FBS picking-list groups sort by catalog product_name (same as WB)."""

from review_processor.ozon_fbs_supplies import (
    _group_postings_by_article,
    _sort_groups_by_product_name,
    render_picking_list_html,
)
from review_processor.wb_fbs_detail import _portal_title_sort_key


def test_product_name_key_matches_wb_portal_title_key():
    titles = [
        "Наматрасник 180х200 см на резинке, толстый",
        "Наматрасник 160х200 см на резинке, толстый",
        "Наматрасник 180х200 на резинке с бортами, толстый",
    ]
    ordered = sorted(titles, key=_portal_title_sort_key)
    assert ordered == [
        "Наматрасник 160х200 см на резинке, толстый",
        "Наматрасник 180х200 на резинке с бортами, толстый",
        "Наматрасник 180х200 см на резинке, толстый",
    ]


def test_group_postings_sort_by_product_name_not_posting_order():
    # Encounter / posting_number order would keep Z then A then M.
    orders = [
        {
            "posting_number": "001",
            "offer_id": "art-z",
            "sku": "9",
            "product_name": "Наматрасник 180х200 см на резинке, толстый",
        },
        {
            "posting_number": "002",
            "offer_id": "art-a",
            "sku": "1",
            "product_name": "Наматрасник 160х200 см на резинке, толстый",
        },
        {
            "posting_number": "003",
            "offer_id": "art-m",
            "sku": "2",
            "product_name": "Наматрасник 180х200 на резинке с бортами, толстый",
        },
        {
            "posting_number": "010",
            "offer_id": "art-a",
            "sku": "1",
            "product_name": "Наматрасник 160х200 см на резинке, толстый",
        },
    ]
    groups = _group_postings_by_article(orders)
    assert [g["article"] for g in groups] == ["art-a", "art-m", "art-z"]
    assert [g["qty"] for g in groups] == [2, 1, 1]
    assert [o["posting_number"] for o in groups[0]["orders"]] == ["002", "010"]


def test_sort_groups_by_product_name_tie_break_article():
    groups = [
        {
            "article": "b-art",
            "product_name": "Одинаковое имя",
            "nm_id": "2",
            "orders": [{"posting_number": "2"}],
        },
        {
            "article": "a-art",
            "product_name": "Одинаковое имя",
            "nm_id": "1",
            "orders": [{"posting_number": "1"}],
        },
    ]
    sorted_groups = _sort_groups_by_product_name(groups)
    assert [g["article"] for g in sorted_groups] == ["a-art", "b-art"]


def test_picking_list_html_rows_follow_product_name_order():
    html = render_picking_list_html(
        {
            "supply_id": "OZ-1",
            "name": "Тест",
            "warehouse_label": "Склад",
            "orders": [
                {
                    "posting_number": "9",
                    "offer_id": "late",
                    "product_name": "Яблоко",
                    "is_cancelled": False,
                },
                {
                    "posting_number": "1",
                    "offer_id": "early",
                    "product_name": "Абрикос",
                    "is_cancelled": False,
                },
            ],
        }
    )
    pos_a = html.find("Абрикос")
    pos_y = html.find("Яблоко")
    assert pos_a != -1 and pos_y != -1
    assert pos_a < pos_y
