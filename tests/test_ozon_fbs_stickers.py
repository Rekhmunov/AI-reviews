"""Tests for Ozon FBS sticker / package-label fetching."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz
from review_processor import ozon_fbs_supplies as oz_sup


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


if __name__ == "__main__":
    unittest.main()
