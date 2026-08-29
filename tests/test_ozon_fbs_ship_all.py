"""Tests for Ozon FBS ship-all (awaiting_packaging → awaiting_deliver)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from review_processor.ozon_fbs_detail import (
    build_ship_packages,
    ship_all_awaiting_packaging,
    ship_posting,
    ship_split_preview,
)


class OzonFbsShipAllTests(unittest.TestCase):
    def test_build_ship_packages_one_unit_per_package(self) -> None:
        packages = build_ship_packages(
            {
                "products_json": '[{"sku": 111, "quantity": 2}, {"sku": 222, "quantity": 1}]'
            }
        )
        self.assertEqual(
            packages,
            [
                {"products": [{"product_id": 111, "quantity": 1}]},
                {"products": [{"product_id": 111, "quantity": 1}]},
                {"products": [{"product_id": 222, "quantity": 1}]},
            ],
        )

    def test_build_ship_packages_requires_products(self) -> None:
        with self.assertRaises(RuntimeError):
            build_ship_packages({"products_json": "[]"})

    def test_ship_split_preview_counts_extra(self) -> None:
        stats = ship_split_preview(
            [
                {"products_json": '[{"sku": 1, "quantity": 2}]'},
                {"products_json": '[{"sku": 2, "quantity": 1}]'},
            ]
        )
        self.assertEqual(stats["multi_posting_count"], 1)
        self.assertEqual(stats["result_posting_count"], 3)
        self.assertEqual(stats["extra_postings"], 1)

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

    def test_ship_posting_forces_awaiting_deliver_on_stale_get(self) -> None:
        """Ozon get may still return awaiting_packaging right after ship."""
        repo = MagicMock()
        client = MagicMock()
        client.get_posting.side_effect = [
            {
                "posting_number": "P-1",
                "status": "awaiting_packaging",
                "products": [{"sku": 1, "quantity": 1}],
            },
            {
                "posting_number": "P-1",
                "status": "awaiting_packaging",
                "products": [{"sku": 1, "quantity": 1}],
            },
        ]
        client.ship_posting.return_value = {"result": True}
        with patch(
            "review_processor.ozon_fbs_detail.get_posting_row",
            return_value={
                "posting_number": "P-1",
                "products_json": '[{"sku": 1, "quantity": 1}]',
            },
        ), patch(
            "review_processor.ozon_fbs_detail.oz.upsert_posting"
        ) as upsert:
            out = ship_posting(
                repo,
                user_id=1,
                source_id=2,
                posting_number="P-1",
                client_id="c",
                api_key="k",
                client=client,
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["posting_numbers"], ["P-1"])
        upsert.assert_called_once()
        kwargs = upsert.call_args.kwargs
        self.assertEqual(kwargs["posting"]["status"], "awaiting_deliver")
        self.assertFalse(kwargs["protect_status_downgrade"])

    def test_ship_posting_multi_package_upserts_siblings(self) -> None:
        repo = MagicMock()
        client = MagicMock()
        client.get_posting.side_effect = [
            {
                "posting_number": "P-1",
                "status": "awaiting_packaging",
                "products": [{"sku": 10, "quantity": 2}],
                "warehouse_id": 5,
            },
            {
                "posting_number": "P-1",
                "status": "awaiting_deliver",
                "products": [{"sku": 10, "quantity": 1}],
            },
            {
                "posting_number": "P-1-1",
                "status": "awaiting_deliver",
                "products": [{"sku": 10, "quantity": 1}],
            },
        ]
        client.ship_posting.return_value = {"result": ["P-1", "P-1-1"]}
        with patch(
            "review_processor.ozon_fbs_detail.get_posting_row",
            return_value={
                "posting_number": "P-1",
                "tab": "awaiting_packaging",
                "products_json": '[{"sku": 10, "quantity": 2}]',
            },
        ), patch(
            "review_processor.ozon_fbs_detail.oz.upsert_posting"
        ) as upsert:
            out = ship_posting(
                repo,
                user_id=1,
                source_id=2,
                posting_number="P-1",
                client_id="c",
                api_key="k",
                client=client,
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["posting_numbers"], ["P-1", "P-1-1"])
        pkgs = client.ship_posting.call_args.args[1]
        self.assertEqual(len(pkgs), 2)
        self.assertEqual(upsert.call_count, 2)


if __name__ == "__main__":
    unittest.main()
