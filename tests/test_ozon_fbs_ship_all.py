"""Tests for Ozon FBS ship-all (awaiting_packaging → awaiting_deliver)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from review_processor.ozon_fbs_detail import (
    build_ship_packages,
    ship_all_awaiting_packaging,
)


class OzonFbsShipAllTests(unittest.TestCase):
    def test_build_ship_packages_from_products_json(self) -> None:
        packages = build_ship_packages(
            {
                "products_json": '[{"sku": 111, "quantity": 2}, {"sku": 222, "quantity": 1}]'
            }
        )
        self.assertEqual(
            packages,
            [{"products": [{"product_id": 111, "quantity": 2}, {"product_id": 222, "quantity": 1}]}],
        )

    def test_build_ship_packages_requires_products(self) -> None:
        with self.assertRaises(RuntimeError):
            build_ship_packages({"products_json": "[]"})

    def test_ship_all_empty(self) -> None:
        repo = MagicMock()
        with patch(
            "review_processor.ozon_fbs_detail.list_awaiting_packaging_numbers",
            return_value=[],
        ):
            out = ship_all_awaiting_packaging(
                repo,
                user_id=1,
                source_id=2,
                client_id="c",
                api_key="k",
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["total"], 0)
        self.assertEqual(out["shipped"], 0)

    def test_ship_all_calls_ship_for_each(self) -> None:
        repo = MagicMock()
        with patch(
            "review_processor.ozon_fbs_detail.list_awaiting_packaging_numbers",
            return_value=["A-1", "A-2"],
        ), patch(
            "review_processor.ozon_fbs_detail.oz.OzonFbsClient"
        ), patch(
            "review_processor.ozon_fbs_detail.ship_posting"
        ) as ship:
            ship.side_effect = [
                {"ok": True},
                RuntimeError("need exemplars"),
            ]
            out = ship_all_awaiting_packaging(
                repo,
                user_id=1,
                source_id=2,
                client_id="c",
                api_key="k",
            )
        self.assertFalse(out["ok"])
        self.assertEqual(out["total"], 2)
        self.assertEqual(out["shipped"], 1)
        self.assertEqual(out["failed"], 1)
        self.assertEqual(out["shipped_numbers"], ["A-1"])
        self.assertEqual(out["errors"][0]["posting_number"], "A-2")
        self.assertEqual(ship.call_count, 2)


if __name__ == "__main__":
    unittest.main()
