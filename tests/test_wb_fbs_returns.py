"""WB FBS «Возвраты» — scan journal and goods-return sync."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from review_processor import wb_fbs_returns as returns


class GoodsReturnMatchTests(unittest.TestCase):
    def _repo_with_goods_returns(self, rows: list[dict]):
        repo = MagicMock()
        repo._sql = lambda sql: sql
        repo._row_to_dict = lambda row: dict(row)

        class _Result:
            def __init__(self, payload):
                self._payload = payload

            def fetchall(self):
                return self._payload

        conn = MagicMock()
        conn.execute = MagicMock(side_effect=lambda sql, params=None: _Result(rows))
        repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
        repo._connect.return_value.__exit__ = MagicMock(return_value=False)
        return repo

    @patch("review_processor.wb_fbs_returns.wb.ensure_wb_fbs_tables")
    @patch("review_processor.wb_fbs_returns.ensure_wb_fbs_returns_tables")
    def test_find_goods_return_by_sticker_id(self, _ensure_ret, _ensure_wb):
        repo = self._repo_with_goods_returns(
            [
                {
                    "sticker_id": "44556677",
                    "wb_order_id": 900001,
                    "barcode": "",
                    "shk_id": "",
                }
            ]
        )
        hit = returns.find_goods_return_by_scan(
            repo, user_id=1, source_id=2, scan="44556677"
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["wb_order_id"], 900001)

    @patch("review_processor.wb_fbs_returns.wb.ensure_wb_fbs_tables")
    @patch("review_processor.wb_fbs_returns.ensure_wb_fbs_returns_tables")
    def test_find_goods_return_by_barcode(self, _ensure_ret, _ensure_wb):
        repo = self._repo_with_goods_returns(
            [
                {
                    "sticker_id": "",
                    "wb_order_id": 900002,
                    "barcode": "2000000000123",
                    "shk_id": "",
                }
            ]
        )
        hit = returns.find_goods_return_by_scan(
            repo, user_id=1, source_id=2, scan="2000000000123"
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["wb_order_id"], 900002)


class ReturnScanDuplicateTests(unittest.TestCase):
    @patch("review_processor.wb_fbs_returns._insert_return_scan")
    @patch("review_processor.wb_fbs_returns._kiz_codes_for_order", return_value=[])
    @patch("review_processor.wb_fbs_returns._product_from_order", return_value={})
    @patch("review_processor.wb_fbs_returns._resolve_order_row", return_value=None)
    @patch("review_processor.wb_fbs_returns._return_scan_duplicate")
    def test_return_sticker_duplicate(self, dup, _order, _prod, _kiz, _insert):
        dup.return_value = {
            "id": 11,
            "scan_type": "return_sticker",
            "return_sticker_id": "12345",
            "matched_order_ids_json": "[]",
            "product_barcodes_json": "[]",
        }
        repo = MagicMock()
        result = returns._process_return_sticker_scan(
            repo,
            user_id=1,
            source_id=2,
            api_key="k",
            scan="12345",
            goods_row={"sticker_id": "12345", "wb_order_id": 1},
        )
        _insert.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "duplicate")


class ReturnStickerKizLinkTests(unittest.TestCase):
    @patch("review_processor.wb_fbs_returns._insert_return_scan")
    @patch("review_processor.wb_fbs_returns._kiz_codes_for_order")
    @patch("review_processor.wb_fbs_returns._product_from_order", return_value={"product_name": "Товар"})
    @patch("review_processor.wb_fbs_returns._resolve_order_row")
    @patch("review_processor.wb_fbs_returns._return_scan_duplicate", return_value=None)
    def test_return_sticker_passes_srid_for_kiz_lookup(
        self, _dup, resolve_order, _prod, kiz_lookup, insert
    ):
        resolve_order.return_value = {
            "order_id": 5525061048,
            "sticker_part_a": "1",
            "sticker_part_b": "2345",
            "sticker_barcode": "qr",
        }
        kiz_lookup.return_value = ["010467012345678921CIRC"]
        insert.return_value = {
            "id": 21,
            "scan_type": "return_sticker",
            "order_id": 5525061048,
            "kiz_code": "010467012345678921CIRC",
            "matched_order_ids_json": "[]",
            "product_barcodes_json": "[]",
        }
        repo = MagicMock()
        result = returns._process_return_sticker_scan(
            repo,
            user_id=1,
            source_id=2,
            api_key="k",
            scan="99887766",
            goods_row={
                "sticker_id": "99887766",
                "wb_order_id": 5525061048,
                "srid": "eI.i0a39f75abc.1.0",
            },
        )
        self.assertTrue(result["ok"])
        kiz_lookup.assert_called_once()
        kwargs = kiz_lookup.call_args.kwargs
        self.assertEqual(kwargs["order_id"], 5525061048)
        self.assertEqual(kwargs["srid_hint"], "eI.i0a39f75abc.1.0")
        self.assertEqual(result["item"]["kiz_code"], "010467012345678921CIRC")


class KizScanTests(unittest.TestCase):
    @patch("review_processor.wb_fbs_returns._insert_return_scan")
    @patch("review_processor.wb_fbs_returns._product_from_gtin", return_value={})
    @patch("review_processor.wb_fbs_returns._catalog_barcodes_index", return_value={})
    @patch("review_processor.wb_fbs_returns.kiz_restore.find_kiz_in_local_database")
    @patch("review_processor.wb_fbs_returns.kiz_restore.looks_like_kiz_scan", return_value=True)
    @patch("review_processor.wb_fbs_returns.kiz_restore.normalize_kiz_mark", side_effect=lambda x: x)
    @patch("review_processor.wb_fbs_returns.kiz_restore.extract_gtin14", return_value="04670123456789")
    def test_kiz_scan_gtin_not_in_catalog_warns(
        self,
        _gtin,
        _norm,
        _looks,
        db_hit,
        _catalog,
        _prod,
        insert,
    ):
        db_hit.return_value = {"found": False, "order_ids": []}
        insert.return_value = {"id": 6, "scan_type": "kiz", "kiz_code": "010467012345678921X"}
        repo = MagicMock()
        result = returns.process_return_scan(
            repo,
            user_id=1,
            source_id=2,
            api_key="k",
            scan="010467012345678921X",
        )
        self.assertTrue(result["ok"])
        self.assertIn("GTIN не найден в каталоге товаров", result["item"].get("warning", ""))

    @patch("review_processor.wb_fbs_returns._insert_return_scan")
    @patch("review_processor.wb_fbs_returns._product_from_gtin", return_value={})
    @patch("review_processor.wb_fbs_returns.kiz_restore.find_kiz_in_local_database")
    @patch("review_processor.wb_fbs_returns.kiz_restore.looks_like_kiz_scan", return_value=True)
    @patch("review_processor.wb_fbs_returns.kiz_restore.normalize_kiz_mark", side_effect=lambda x: x)
    @patch("review_processor.wb_fbs_returns.kiz_restore.extract_gtin14", return_value="04670123456789")
    def test_kiz_scan_not_in_local_db_warns(
        self,
        _gtin,
        _norm,
        _looks,
        db_hit,
        _prod,
        insert,
    ):
        db_hit.return_value = {"found": False, "order_ids": []}
        insert.return_value = {"id": 5, "scan_type": "kiz", "kiz_code": "010467012345678921X"}
        repo = MagicMock()
        result = returns.process_return_scan(
            repo,
            user_id=1,
            source_id=2,
            api_key="k",
            scan="010467012345678921X",
        )
        self.assertTrue(result["ok"])
        self.assertIn("warning", result["item"])


class ExportCsvTests(unittest.TestCase):
    def test_export_return_scans_csv_has_bom(self):
        csv_text = returns.export_return_scans_csv(
            [
                {
                    "scanned_at": "2026-01-01T10:00:00+00:00",
                    "scan_type": "return_sticker",
                    "order_id": 1,
                    "return_sticker_id": "99",
                    "assembly_sticker_number": "13640",
                    "kiz_code": "KIZ",
                    "product_name": "Товар",
                    "product_article": "art-1",
                    "product_barcodes": ["123"],
                }
            ]
        )
        self.assertTrue(csv_text.startswith("\ufeff"))
        self.assertIn("Товар", csv_text)


if __name__ == "__main__":
    unittest.main()
