"""Product weight fill from WB Content / Ozon attributes."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from review_processor.product_weight_fill import (
    build_weight_fill_preview,
    fill_product_weights_from_marketplace,
    weight_kg_from_ozon_item,
    weight_kg_from_wb_card,
)


class ProductWeightParsersTests(unittest.TestCase):
    def test_wb_weight_brutto(self) -> None:
        self.assertEqual(
            weight_kg_from_wb_card({"dimensions": {"weightBrutto": 0.35}}),
            0.35,
        )
        self.assertIsNone(weight_kg_from_wb_card({"dimensions": {"weightBrutto": 0}}))
        self.assertIsNone(weight_kg_from_wb_card(None))

    def test_ozon_weight_units(self) -> None:
        self.assertEqual(
            weight_kg_from_ozon_item({"weight": 350, "weight_unit": "g"}),
            0.35,
        )
        self.assertEqual(
            weight_kg_from_ozon_item({"weight": 0.5, "weight_unit": "kg"}),
            0.5,
        )
        self.assertIsNone(weight_kg_from_ozon_item({"weight": 0, "weight_unit": "g"}))


class ProductWeightFillPreviewTests(unittest.TestCase):
    def test_preview_fills_only_empty_weights(self) -> None:
        repo = MagicMock()
        repo.list_product_photos.return_value = [
            {
                "id": 1,
                "name": "Empty",
                "supplier_article": "A1",
                "wb_nmid": "11",
                "ozon_sku": "",
                "weight_kg": None,
            },
            {
                "id": 2,
                "name": "Filled",
                "supplier_article": "A2",
                "wb_nmid": "",
                "ozon_sku": "22",
                "weight_kg": 1.2,
            },
        ]
        market = {
            1: {
                "weight_kg": 0.4,
                "platform": "wb",
                "source_name": "WB",
                "sources": [{"platform": "wb", "weight_kg": 0.4}],
            },
            2: {
                "weight_kg": 0.9,
                "platform": "ozon",
                "source_name": "OZ",
                "sources": [{"platform": "ozon", "weight_kg": 0.9}],
            },
        }
        with patch(
            "review_processor.product_weight_fill.collect_marketplace_weights",
            return_value=market,
        ):
            items = build_weight_fill_preview(repository=repo, user_id=7)
        by_id = {int(x["id"]): x for x in items}
        self.assertTrue(by_id[1]["has_new"])
        self.assertEqual(by_id[1]["proposed_weight_kg"], 0.4)
        self.assertFalse(by_id[2]["has_new"])
        self.assertIsNone(by_id[2]["proposed_weight_kg"])
        self.assertEqual(by_id[2]["current_weight_kg"], 1.2)

    def test_fill_applies_only_selected_with_new(self) -> None:
        repo = MagicMock()
        repo.set_product_weight_kg.return_value = True
        preview = [
            {
                "id": 1,
                "name": "A",
                "has_new": True,
                "proposed_weight_kg": 0.3,
                "platform": "wb",
            },
            {
                "id": 2,
                "name": "B",
                "has_new": False,
                "proposed_weight_kg": None,
                "platform": "",
            },
        ]
        with patch(
            "review_processor.product_weight_fill.build_weight_fill_preview",
            return_value=preview,
        ):
            result = fill_product_weights_from_marketplace(
                repository=repo, user_id=1, product_ids=[1, 2]
            )
        self.assertEqual(result["updated"], 1)
        repo.set_product_weight_kg.assert_called_once_with(
            user_id=1, product_id=1, weight_kg=0.3
        )


class ProductWeightUiContractTests(unittest.TestCase):
    def test_ui_and_api_contracts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "web_templates" / "app.html").read_text(encoding="utf-8")
        js = (root / "web_static" / "app.js").read_text(encoding="utf-8")
        web = (root / "review_processor" / "web.py").read_text(encoding="utf-8")
        self.assertIn("openProductFillWeightsModal()", html)
        self.assertIn('id="productFillWeightsModal"', html)
        self.assertIn("/api/products/marketplace-weights-preview", js)
        self.assertIn("/api/products/fill-weights-from-marketplace", js)
        self.assertIn("/api/products/marketplace-weights-preview", web)
        self.assertIn("/api/products/fill-weights-from-marketplace", web)
        self.assertIn("def set_product_weight_kg", (root / "review_processor" / "repository.py").read_text(encoding="utf-8"))



if __name__ == "__main__":
    unittest.main()
