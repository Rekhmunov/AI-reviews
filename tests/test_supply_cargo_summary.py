"""Supply-scoped cargo summary (products / pallets / boxes) for WB + Ozon FBS."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from review_processor.ozon_fbs import compute_ozon_fbs_supply_cargo_summary
from review_processor.wb_fbs import (
    compute_wb_fbs_supply_cargo_summary,
    format_products_ru,
)


class FormatProductsRuTests(unittest.TestCase):
    def test_plurals(self) -> None:
        self.assertEqual(format_products_ru(1), "1 товар")
        self.assertEqual(format_products_ru(2), "2 товара")
        self.assertEqual(format_products_ru(5), "5 товаров")
        self.assertEqual(format_products_ru(11), "11 товаров")
        self.assertEqual(format_products_ru(21), "21 товар")
        self.assertEqual(format_products_ru(22), "22 товара")


class WbSupplyCargoSummaryTests(unittest.TestCase):
    def _repo(self) -> MagicMock:
        repo = MagicMock()
        repo.list_product_photos.return_value = [
            {
                "supplier_article": "ART-1",
                "wb_nmid": "111",
                "box_qty": 10,
                "product_category": "Категория 1",
            }
        ]
        repo.list_product_categories.return_value = [
            {"name": "Категория 1", "boxes_per_pallet": 10}
        ]
        return repo

    def test_full_pallet_from_supply_orders(self) -> None:
        orders = [{"article": "ART-1", "nm_id": "111"} for _ in range(100)]
        summary = compute_wb_fbs_supply_cargo_summary(
            self._repo(), user_id=1, orders=orders
        )
        self.assertEqual(summary["products"], 100)
        self.assertEqual(summary["boxes"], 10.0)
        self.assertEqual(summary["pallets"], 1.0)
        self.assertEqual(
            summary["summary_label"],
            "100 товаров · 1 паллета (10 коробов)",
        )

    def test_skips_cancelled_orders(self) -> None:
        orders = [
            {"article": "ART-1", "nm_id": "111"},
            {"article": "ART-1", "nm_id": "111", "cancel_reason_label": "Отмена"},
        ]
        summary = compute_wb_fbs_supply_cargo_summary(
            self._repo(), user_id=1, orders=orders
        )
        self.assertEqual(summary["products"], 1)
        self.assertEqual(summary["boxes"], 0.1)
        self.assertEqual(summary["pallets"], 0.01)

    def test_empty_orders_hide_summary_label(self) -> None:
        summary = compute_wb_fbs_supply_cargo_summary(
            self._repo(), user_id=1, orders=[]
        )
        self.assertEqual(summary["products"], 0)
        self.assertEqual(summary["summary_label"], "")


class OzonSupplyCargoSummaryTests(unittest.TestCase):
    def _repo(self) -> MagicMock:
        repo = MagicMock()
        repo.list_product_photos.return_value = [
            {
                "supplier_article": "ART-1",
                "ozon_sku": "999",
                "box_qty": 10,
                "product_category": "Категория 1",
            }
        ]
        repo.list_product_categories.return_value = [
            {"name": "Категория 1", "boxes_per_pallet": 10}
        ]
        return repo

    def test_full_pallet_from_supply_postings(self) -> None:
        orders = [
            {"offer_id": "ART-1", "sku": "999", "quantity": 40},
            {"offer_id": "ART-1", "sku": "999", "quantity": 60},
        ]
        summary = compute_ozon_fbs_supply_cargo_summary(
            self._repo(), user_id=1, orders=orders
        )
        self.assertEqual(summary["products"], 100)
        self.assertEqual(summary["boxes"], 10.0)
        self.assertEqual(summary["pallets"], 1.0)
        self.assertEqual(
            summary["summary_label"],
            "100 товаров · 1 паллета (10 коробов)",
        )

    def test_skips_cancelled_postings(self) -> None:
        orders = [
            {"offer_id": "ART-1", "sku": "999", "quantity": 10},
            {"offer_id": "ART-1", "sku": "999", "quantity": 10, "cancelled": True},
        ]
        summary = compute_ozon_fbs_supply_cargo_summary(
            self._repo(), user_id=1, orders=orders
        )
        self.assertEqual(summary["products"], 10)
        self.assertEqual(summary["boxes"], 1.0)
        self.assertEqual(summary["pallets"], 0.1)


if __name__ == "__main__":
    unittest.main()
