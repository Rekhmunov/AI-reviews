"""Tests for Ozon FBS stickers: package labels, binding, lookup."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz
from review_processor import ozon_fbs_supplies as oz_sup
from review_processor.ozon_fbs_stickers import find_postings_by_sticker_scan, lookup_posting_by_scan


class OzonFbsClientStructureTests(unittest.TestCase):
    def test_client_exposes_shipments_api_methods(self) -> None:
        client = oz.OzonFbsClient("cid", "key")
        for name in (
            "delivery_method_list",
            "carriage_delivery_list",
            "fbs_act_create",
            "fbs_act_check_status",
            "fbs_act_get_barcode",
            "fbs_act_get_barcode_text",
        ):
            self.assertTrue(hasattr(client, name), name)


class OzonFbsLabelFetchTests(unittest.TestCase):
    def test_batch_ozon_error_falls_back_to_one_by_one(self) -> None:
        client = MagicMock()
        client.package_label_pdf.side_effect = [
            RuntimeError('Ozon HTTP 400: {"code":3,"message":"INVALID_ARGUMENT"}'),
            b"%PDF-one",
            b"%PDF-two",
        ]

        with patch.object(oz_sup, "_pdf_pages_to_png_b64", side_effect=[["p1"], ["p2"]]):
            out = oz_sup._fetch_label_images(client, ["A-1", "B-2"])

        self.assertEqual(out["A-1"], ["p1"])
        self.assertEqual(out["B-2"], ["p2"])
        self.assertEqual(client.package_label_pdf.call_count, 3)

    def test_fetch_merged_batches_over_20(self) -> None:
        client = MagicMock()
        client.package_label_pdf.side_effect = [b"%PDF-1", b"%PDF-2"]

        mock_merged = MagicMock()
        mock_merged.page_count = 1
        mock_merged.tobytes.return_value = b"merged"
        mock_src = MagicMock()

        def fake_open(arg=None, stream=None, filetype=None):
            if stream is not None:
                return mock_src
            return mock_merged

        with patch("pymupdf.open", side_effect=fake_open):
            pdf = oz.fetch_merged_package_label_pdf(client, [f"P-{i}" for i in range(25)])

        self.assertEqual(pdf, b"merged")
        self.assertEqual(client.package_label_pdf.call_count, 2)
        self.assertEqual(len(client.package_label_pdf.call_args_list[0].args[0]), 20)
        self.assertEqual(len(client.package_label_pdf.call_args_list[1].args[0]), 5)


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

    def test_find_by_posting_number_partial(self) -> None:
        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        conn.execute.return_value.fetchall.return_value = [
            {
                "posting_number": "0123604587-1235-1",
                "sticker_barcode": "",
                "sticker_part_a": "0123604587",
                "sticker_part_b": "1235-1",
            }
        ]
        repo._row_to_dict = lambda r: dict(r)
        found = find_postings_by_sticker_scan(
            repo, user_id=1, source_id=2, scan="0123604587-1235-1"
        )
        self.assertEqual(found["row"]["posting_number"], "0123604587-1235-1")

    def test_find_by_sticker_part_b_suffix(self) -> None:
        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        # part_b exact query returns empty; fuzzy via ILIKE tail
        conn.execute.return_value.fetchall.side_effect = [
            [],  # barcode
            [],  # exact pn
            [
                {
                    "posting_number": "0123604587-1235-1",
                    "sticker_barcode": "",
                    "sticker_part_a": "0123604587",
                    "sticker_part_b": "1235-1",
                }
            ],
        ]
        repo._row_to_dict = lambda r: dict(r)
        found = find_postings_by_sticker_scan(
            repo, user_id=1, source_id=2, scan="1235-1"
        )
        self.assertEqual(found["row"]["posting_number"], "0123604587-1235-1")


if __name__ == "__main__":
    unittest.main()
