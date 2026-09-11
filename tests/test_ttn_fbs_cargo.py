"""TN FBS cargo autofill helpers."""

from __future__ import annotations

import unittest

from review_processor.ttn_fbs_cargo import (
    format_places,
    places_from_ozon_containers,
    places_from_wb_trbx,
    product_weight_index,
    sum_weight_for_lines,
    weight_lines_from_ozon_orders,
    weight_lines_from_wb_orders,
)


class TtnFbsCargoTests(unittest.TestCase):
    def test_product_weight_index_keys(self) -> None:
        idx = product_weight_index(
            [
                {
                    "supplier_article": "Art-1",
                    "wb_nmid": "111",
                    "ozon_sku": "222",
                    "weight_kg": 0.5,
                }
            ]
        )
        self.assertEqual(idx["Art-1"], 0.5)
        self.assertEqual(idx["art-1"], 0.5)
        self.assertEqual(idx["111"], 0.5)
        self.assertEqual(idx["222"], 0.5)

    def test_sum_weight_wb_orders(self) -> None:
        idx = product_weight_index(
            [{"supplier_article": "A", "wb_nmid": "9", "weight_kg": 1.25}]
        )
        lines = weight_lines_from_wb_orders(
            [
                {"article": "A", "nm_id": "9"},
                {"article": "A", "nm_id": "9"},
                {"article": "B", "nm_id": "1"},
            ]
        )
        out = sum_weight_for_lines(idx, lines)
        self.assertEqual(out["weight_kg"], 2.5)
        self.assertEqual(out["weight"], "2.5")
        self.assertEqual(out["missing_articles"], ["B"])

    def test_places_wb_and_ozon(self) -> None:
        self.assertEqual(places_from_wb_trbx({"boxes_count": 3, "boxes": []}), 3)
        self.assertEqual(places_from_wb_trbx({"boxes": [{"id": "1"}, {"id": "2"}]}), 2)
        self.assertEqual(
            places_from_ozon_containers(
                {
                    "containers": [
                        {"id": 1, "bound_to_this_supply": True},
                        {"id": 2, "bound_to_this_supply": False},
                        {"id": 3, "supply_id": "S1"},
                    ]
                },
                supply_id="S1",
            ),
            2,
        )
        self.assertEqual(format_places(4), "4")
        self.assertEqual(format_places(None), "")

    def test_ozon_qty_lines(self) -> None:
        lines = weight_lines_from_ozon_orders(
            [
                {"offer_id": "o1", "sku": "s1", "quantity": 3},
                {"offer_id": "o1", "sku": "s1", "quantity": 2},
                {"offer_id": "x", "sku": "y", "cancelled": True, "quantity": 9},
            ]
        )
        self.assertEqual(lines, [(["o1", "s1"], 5)])


if __name__ == "__main__":
    unittest.main()
