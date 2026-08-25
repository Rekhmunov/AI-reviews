"""Ozon FBS sync pallet summary (awaiting_packaging + awaiting_deliver)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from review_processor.ozon_fbs import (
    TAB_AWAITING_DELIVER,
    TAB_AWAITING_PACKAGING,
    compute_ozon_fbs_pallet_summary,
)


class ComputeOzonFbsPalletSummaryTests(unittest.TestCase):
    @patch("review_processor.ozon_fbs.ensure_ozon_fbs_tables")
    def test_example_one_full_pallet(self, _ensure):
        # 100 pcs, box_qty=10, boxes_per_pallet=10 → 10 boxes, 1.0 pallet
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
        repo._sql = lambda sql: sql
        repo._row_to_dict = lambda row: dict(row)

        class _Result:
            def fetchall(self):
                return [
                    {
                        "source_id": 7,
                        "offer_id": "ART-1",
                        "sku": 999,
                        "qty": 100,
                    },
                ]

        conn = MagicMock()
        conn.execute.return_value = _Result()
        repo._connect.return_value.__enter__.return_value = conn
        repo._connect.return_value.__exit__.return_value = False

        summary = compute_ozon_fbs_pallet_summary(
            repo,
            user_id=1,
            sources=[{"source_id": 7, "name": "Озон ФБС 1"}],
        )
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["name"], "Озон ФБС 1")
        self.assertEqual(summary[0]["pallets"], 1.0)
        self.assertEqual(summary[0]["boxes"], 10.0)
        self.assertEqual(summary[0]["boxes_label"], "10 коробов")
        self.assertEqual(summary[0]["pallets_label"], "1 паллета (10 коробов)")

        sql = str(conn.execute.call_args[0][0])
        params = conn.execute.call_args[0][1]
        self.assertIn("tab IN", sql)
        self.assertIn(TAB_AWAITING_PACKAGING, params)
        self.assertIn(TAB_AWAITING_DELIVER, params)

    @patch("review_processor.ozon_fbs.ensure_ozon_fbs_tables")
    def test_match_by_ozon_sku(self, _ensure):
        repo = MagicMock()
        repo.list_product_photos.return_value = [
            {
                "supplier_article": "OTHER",
                "ozon_sku": "555",
                "box_qty": 5,
                "product_category": "Кат",
            }
        ]
        repo.list_product_categories.return_value = [
            {"name": "Кат", "boxes_per_pallet": 10}
        ]
        repo._sql = lambda sql: sql
        repo._row_to_dict = lambda row: dict(row)

        class _Result:
            def fetchall(self):
                return [
                    {
                        "source_id": 1,
                        "offer_id": "unknown",
                        "sku": 555,
                        "qty": 25,
                    },
                ]

        conn = MagicMock()
        conn.execute.return_value = _Result()
        repo._connect.return_value.__enter__.return_value = conn
        repo._connect.return_value.__exit__.return_value = False

        summary = compute_ozon_fbs_pallet_summary(
            repo,
            user_id=1,
            sources=[{"source_id": 1, "name": "Кабинет"}],
        )
        self.assertEqual(summary[0]["boxes"], 5.0)
        self.assertEqual(summary[0]["pallets"], 0.5)

    @patch("review_processor.ozon_fbs.ensure_ozon_fbs_tables")
    def test_box_qty_without_category_counts_boxes_only(self, _ensure):
        repo = MagicMock()
        repo.list_product_photos.return_value = [
            {
                "supplier_article": "ART-2",
                "ozon_sku": "",
                "box_qty": 5,
                "product_category": "",
            }
        ]
        repo.list_product_categories.return_value = []
        repo._sql = lambda sql: sql
        repo._row_to_dict = lambda row: dict(row)

        class _Result:
            def fetchall(self):
                return [
                    {
                        "source_id": 3,
                        "offer_id": "ART-2",
                        "sku": None,
                        "qty": 20,
                    },
                ]

        conn = MagicMock()
        conn.execute.return_value = _Result()
        repo._connect.return_value.__enter__.return_value = conn
        repo._connect.return_value.__exit__.return_value = False

        summary = compute_ozon_fbs_pallet_summary(
            repo,
            user_id=1,
            sources=[{"source_id": 3, "name": "ФБС Склад 2"}],
        )
        self.assertEqual(summary[0]["boxes"], 4.0)
        self.assertEqual(summary[0]["pallets"], 0.0)
        self.assertEqual(summary[0]["pallets_label"], "0 паллет (4 короба)")


if __name__ == "__main__":
    unittest.main()
