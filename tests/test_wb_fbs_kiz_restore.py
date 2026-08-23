"""WB FBS «Восстановление КИЗ» lookup and sticker matching."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from review_processor import wb_fbs_kiz_restore as restore
from review_processor.wb_fbs import persist_order_stickers_batch


class KizRestoreDetectionTests(unittest.TestCase):
    def test_looks_like_kiz_with_gtin(self):
        code = "010467012345678921ABC\u001d91EE06\u001d92ZZ"
        self.assertTrue(restore.looks_like_kiz_scan(code))
        self.assertEqual(restore.extract_gtin14(code), "04670123456789")

    def test_sticker_scan_not_kiz(self):
        self.assertFalse(restore.looks_like_kiz_scan("!uKEtQZVx"))
        self.assertFalse(restore.looks_like_kiz_scan("13640169"))


class StickerMatchTests(unittest.TestCase):
    def _repo_with_orders(self, orders: list[dict]):
        repo = MagicMock()
        repo._sql = lambda sql: sql
        repo._row_to_dict = lambda row: dict(row)

        class _Result:
            def __init__(self, rows):
                self._rows = rows

            def fetchall(self):
                return self._rows

        def _execute(sql, params=None):
            return _Result(orders)

        conn = MagicMock()
        conn.execute = _execute
        repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
        repo._connect.return_value.__exit__ = MagicMock(return_value=False)
        return repo

    @patch("review_processor.wb_fbs_kiz_restore.wb.ensure_wb_fbs_tables")
    def test_find_by_barcode(self, _ensure):
        repo = self._repo_with_orders(
            [
                {
                    "order_id": 100001,
                    "sticker_barcode": "!uKEtQZVx",
                    "sticker_part_a": "1",
                    "sticker_part_b": "3640",
                    "article": "sku-1",
                    "kiz_codes_json": "[]",
                }
            ]
        )
        found = restore.find_orders_by_sticker_scan(
            repo, user_id=1, source_id=2, scan="!uKEtQZVx"
        )
        self.assertFalse(found["ambiguous"])
        self.assertEqual(found["row"]["order_id"], 100001)

    @patch("review_processor.wb_fbs_kiz_restore.wb.ensure_wb_fbs_tables")
    def test_find_by_part_b_digits(self, _ensure):
        repo = self._repo_with_orders(
            [
                {
                    "order_id": 200002,
                    "sticker_barcode": "",
                    "sticker_part_a": "1",
                    "sticker_part_b": "0169",
                    "article": "sku-2",
                    "kiz_codes_json": "[]",
                }
            ]
        )
        found = restore.find_orders_by_sticker_scan(
            repo, user_id=1, source_id=2, scan="10169"
        )
        self.assertEqual(found["row"]["order_id"], 200002)


class KizRestoreLookupTests(unittest.TestCase):
    @patch("review_processor.wb_fbs_kiz_restore.kiz_datamatrix_png_base64", return_value="pngb64")
    def test_direct_kiz_scan(self, _dm):
        repo = MagicMock()
        code = "010467012345678921ABC"
        out = restore.kiz_restore_lookup(
            repo,
            user_id=1,
            source_id=2,
            scan=code,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["mode"], "kiz")
        self.assertEqual(out["kiz_code"], code)
        self.assertEqual(out["datamatrix_png"], "pngb64")

    @patch("review_processor.wb_fbs_kiz_restore.kiz_datamatrix_png_base64", return_value="pngb64")
    @patch("review_processor.wb_fbs_kiz_restore.load_kiz_for_order", return_value=["010467012345678921X"])
    @patch("review_processor.wb_fbs_kiz_restore.find_orders_by_sticker_scan")
    def test_sticker_then_kiz(self, find_mock, load_mock, _dm):
        find_mock.return_value = {
            "row": {
                "order_id": 300003,
                "sticker_part_a": "1",
                "sticker_part_b": "9999",
                "sticker_barcode": "qr1",
                "article": "art",
            },
            "ambiguous": False,
            "matches": [],
        }
        repo = MagicMock()
        out = restore.kiz_restore_lookup(
            repo,
            user_id=1,
            source_id=2,
            scan="qr1",
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["mode"], "sticker")
        self.assertEqual(out["order_id"], 300003)
        load_mock.assert_called_once()

    @patch("review_processor.wb_fbs_kiz_restore.kiz_datamatrix_png_base64", return_value="pngb64")
    @patch("review_processor.wb_fbs_kiz_restore.load_kiz_for_order", return_value=[])
    @patch("review_processor.wb_fbs_kiz_restore.resolve_order_for_restore")
    def test_order_without_kiz(self, resolve_order, _load, _dm):
        resolve_order.return_value = {"order_id": 400004, "kiz_codes_json": "[]"}
        repo = MagicMock()
        out = restore.kiz_restore_lookup(
            repo,
            user_id=1,
            source_id=2,
            order_id=400004,
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "no_kiz")

    @patch("review_processor.wb_fbs_kiz_restore.kiz_datamatrix_png_base64", return_value="pngb64")
    @patch("review_processor.wb_fbs_kiz_restore.load_kiz_for_order", return_value=["010467012345678921REMOTE"])
    @patch("review_processor.wb_fbs_kiz_restore.resolve_order_for_restore")
    def test_remote_order_lookup(self, resolve_order, load_mock, _dm):
        resolve_order.return_value = {
            "order_id": 500005,
            "article": "sku-remote",
            "sticker_part_a": "1",
            "sticker_part_b": "2345",
            "sticker_barcode": "!remote",
        }
        repo = MagicMock()
        out = restore.kiz_restore_lookup(
            repo,
            user_id=1,
            source_id=2,
            order_id=500005,
            api_key="key",
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["mode"], "order")
        self.assertEqual(out["order_id"], 500005)
        resolve_order.assert_called_once()
        load_mock.assert_called_once()


class PersistStickerBatchTests(unittest.TestCase):
    @patch("review_processor.wb_fbs.ensure_wb_fbs_tables")
    def test_persist_updates_existing_row(self, _ensure):
        repo = MagicMock()
        repo._sql = lambda sql: sql
        cur = MagicMock()
        cur.rowcount = 1
        conn = MagicMock()
        conn.execute.return_value = cur
        repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
        repo._connect.return_value.__exit__ = MagicMock(return_value=False)
        n = persist_order_stickers_batch(
            repo,
            user_id=1,
            source_id=2,
            stickers={
                500005: {
                    "sticker_barcode": "!abc",
                    "sticker_part_a": "1",
                    "sticker_part_b": "2345",
                }
            },
        )
        self.assertEqual(n, 1)
        sql = str(conn.execute.call_args[0][0])
        self.assertIn("sticker_barcode", sql)


class DataMatrixRenderTests(unittest.TestCase):
    def test_datamatrix_png_base64(self):
        code = "010467012345678921TEST"
        b64 = restore.kiz_datamatrix_png_base64(code, scale=2)
        self.assertTrue(b64)
        raw = json.loads(json.dumps({"b64": b64}))
        self.assertGreater(len(raw["b64"]), 40)


if __name__ == "__main__":
    unittest.main()
