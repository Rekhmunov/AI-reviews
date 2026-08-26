"""Tests for Ozon FBS sticker binding and lookup."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz
from review_processor.ozon_fbs_stickers import find_postings_by_sticker_scan, lookup_posting_by_scan


class OzonFbsStickerFieldsTests(unittest.TestCase):
    def test_sticker_parts_from_posting_number(self) -> None:
        a, b = oz.sticker_parts_from_posting_number("0123604587-1235-1")
        self.assertEqual(a, "0123604587")
        self.assertEqual(b, "1235-1")

    def test_sticker_fields_from_posting(self) -> None:
        fields = oz.sticker_fields_from_posting(
            {
                "posting_number": "0123604587-1235-1",
                "barcodes": {"upper_barcode": "QR123", "lower_barcode": ""},
            }
        )
        self.assertEqual(fields["sticker_barcode"], "QR123")
        self.assertEqual(fields["sticker_part_a"], "0123604587")
        self.assertEqual(fields["sticker_part_b"], "1235-1")


class OzonFbsStickerPersistTests(unittest.TestCase):
    @patch("review_processor.ozon_fbs.ensure_ozon_fbs_tables")
    def test_persist_posting_stickers_batch_updates_row(self, _ensure: MagicMock) -> None:
        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        cur = MagicMock()
        cur.rowcount = 1
        conn.execute.return_value = cur
        n = oz.persist_posting_stickers_batch(
            repo,
            user_id=1,
            source_id=2,
            stickers={
                "PN-1": {
                    "sticker_barcode": "!scanQR",
                    "sticker_part_a": "0123",
                    "sticker_part_b": "1",
                }
            },
            set_scanned_at=True,
        )
        self.assertEqual(n, 1)
        conn.execute.assert_called_once()


class OzonFbsStickerLookupTests(unittest.TestCase):
    @patch("review_processor.ozon_fbs_stickers.find_postings_by_sticker_scan")
    def test_lookup_posting_by_scan_found(self, mock_find: MagicMock) -> None:
        mock_find.return_value = {
            "row": {
                "posting_number": "PN-1",
                "order_id": 99,
                "order_number": "ORD-99",
                "marking_codes_json": '["010460"]',
                "pick_verified": True,
                "pick_barcode": "4601234567890",
                "pick_verified_at": "2026-08-26T12:00:00+00:00",
                "sticker_barcode": "!qr",
                "sticker_part_a": "0123",
                "sticker_part_b": "1",
            },
            "ambiguous": False,
            "matches": [],
        }
        out = lookup_posting_by_scan(
            MagicMock(), user_id=1, source_id=2, scan="!qr"
        )
        self.assertTrue(out["found"])
        self.assertEqual(out["posting"]["posting_number"], "PN-1")
        self.assertEqual(out["posting"]["kiz_codes"], ["010460"])
        self.assertTrue(out["posting"]["pick_verified"])

    def test_find_by_sticker_barcode(self) -> None:
        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        conn.execute.return_value.fetchall.return_value = [
            {
                "posting_number": "PN-1",
                "sticker_barcode": "!uKEtQZVx",
                "sticker_part_a": "",
                "sticker_part_b": "",
            }
        ]
        repo._row_to_dict = lambda r: dict(r)
        found = find_postings_by_sticker_scan(
            repo, user_id=1, source_id=2, scan="!uKEtQZVx"
        )
        self.assertEqual(found["row"]["posting_number"], "PN-1")


if __name__ == "__main__":
    unittest.main()
