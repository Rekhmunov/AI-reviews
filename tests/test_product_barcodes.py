"""Product catalog: multiple barcodes (ШК) per product."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from review_processor.repository import (
    ReviewRepository,
    _catalog_fbs_barcodes_for_product,
    _normalize_product_barcodes,
)


class NormalizeProductBarcodesTests(unittest.TestCase):
    def test_empty_and_none(self):
        self.assertEqual(_normalize_product_barcodes(None), [])
        self.assertEqual(_normalize_product_barcodes(""), [])
        self.assertEqual(_normalize_product_barcodes("[]"), [])

    def test_list_trim_dedupe(self):
        self.assertEqual(
            _normalize_product_barcodes([" 4601 ", "4601", "", "4602"]),
            ["4601", "4602"],
        )

    def test_json_string(self):
        self.assertEqual(
            _normalize_product_barcodes('["4601","4602"]'),
            ["4601", "4602"],
        )

    def test_comma_separated_fallback(self):
        self.assertEqual(
            _normalize_product_barcodes("4601, 4602 ,4601"),
            ["4601", "4602"],
        )


class ProductBarcodesRepositoryTests(unittest.TestCase):
    @patch("review_processor.repository.ReviewRepository._connect")
    def test_add_product_photo_persists_barcodes(self, connect_mock):
        conn = MagicMock()
        connect_mock.return_value.__enter__.return_value = conn
        connect_mock.return_value.__exit__.return_value = False

        repo = ReviewRepository.__new__(ReviewRepository)
        repo._sql = lambda sql: sql
        repo._insert_and_get_id = MagicMock(return_value=11)

        class _Row(dict):
            pass

        conn.execute.return_value.fetchone.return_value = _Row(
            id=11,
            name="Товар",
            skip_kiz_gtin_check=0,
            barcodes_json='["4601234567890","4601234567891"]',
        )

        item = ReviewRepository.add_product_photo(
            repo,
            user_id=1,
            name="Товар",
            supplier_article="A1",
            wb_nmid="1",
            ozon_sku="",
            photo_path=None,
            barcodes=["4601234567890", "4601234567890", "4601234567891"],
        )
        self.assertEqual(item.get("barcodes"), ["4601234567890", "4601234567891"])
        insert_sql = repo._insert_and_get_id.call_args[0][1]
        self.assertIn("barcodes_json", insert_sql)
        params = repo._insert_and_get_id.call_args[0][2]
        self.assertEqual(json.loads(params[9]), ["4601234567890", "4601234567891"])

    @patch("review_processor.repository.ReviewRepository._connect")
    def test_list_product_photos_exposes_barcodes(self, connect_mock):
        conn = MagicMock()
        connect_mock.return_value.__enter__.return_value = conn
        connect_mock.return_value.__exit__.return_value = False

        repo = ReviewRepository.__new__(ReviewRepository)
        repo._sql = lambda sql: sql
        repo._row_to_dict = lambda row: dict(row)

        class _Row(dict):
            pass

        conn.execute.return_value.fetchall.return_value = [
            _Row(id=1, name="A", skip_kiz_gtin_check=0, barcodes_json='["111"]'),
            _Row(id=2, name="B", skip_kiz_gtin_check=0, barcodes_json="[]"),
        ]

        items = ReviewRepository.list_product_photos(repo, user_id=1)
        self.assertEqual(items[0]["barcodes"], ["111"])
        self.assertEqual(items[1]["barcodes"], [])
        self.assertNotIn("barcodes_json", items[0])


class ProductFillBarcodesFromFbsTests(unittest.TestCase):
    def test_catalog_fbs_barcodes_excludes_seller_article(self):
        product = {"supplier_article": "ART-1", "ozon_sku": "OZ-1"}
        got = _catalog_fbs_barcodes_for_product(
            product, ["4601234567890", "ART-1", "4601234567890"]
        )
        self.assertEqual(got, ["4601234567890", "OZ-1"])

    def test_fill_preview_merges_without_duplicates(self):
        repo = ReviewRepository.__new__(ReviewRepository)
        repo.list_product_photos = MagicMock(  # type: ignore[method-assign]
            return_value=[
                {
                    "id": 10,
                    "name": "Товар",
                    "supplier_article": "ART-1",
                    "wb_nmid": "111",
                    "ozon_sku": "",
                    "barcodes": ["460111"],
                }
            ]
        )
        repo.get_wb_fbs_barcodes_by_product_id = MagicMock(  # type: ignore[method-assign]
            return_value={10: ["460222", "ART-1"]}
        )
        preview = ReviewRepository.get_product_fbs_barcode_fill_preview(repo, user_id=1)
        self.assertEqual(len(preview), 1)
        self.assertEqual(preview[0]["current_barcodes"], ["460111"])
        self.assertEqual(preview[0]["new_barcodes"], ["460222"])
        self.assertEqual(preview[0]["merged_barcodes"], ["460111", "460222"])
        self.assertTrue(preview[0]["has_new"])

    def test_fill_applies_only_selected_with_new_codes(self):
        repo = ReviewRepository.__new__(ReviewRepository)
        repo.get_product_fbs_barcode_fill_preview = MagicMock(  # type: ignore[method-assign]
            return_value=[
                {
                    "id": 10,
                    "name": "A",
                    "merged_barcodes": ["460111", "460222"],
                    "new_barcodes": ["460222"],
                    "has_new": True,
                },
                {
                    "id": 11,
                    "name": "B",
                    "merged_barcodes": ["999"],
                    "new_barcodes": [],
                    "has_new": False,
                },
            ]
        )
        repo.set_product_barcodes = MagicMock(return_value=True)  # type: ignore[method-assign]
        result = ReviewRepository.fill_product_barcodes_from_fbs(
            repo, user_id=1, product_ids=[10, 11]
        )
        self.assertEqual(result["updated"], 1)
        repo.set_product_barcodes.assert_called_once_with(
            user_id=1, product_id=10, barcodes=["460111", "460222"]
        )


if __name__ == "__main__":
    unittest.main()
