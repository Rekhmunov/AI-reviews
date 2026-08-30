"""Block Ozon picking/sticker print when supply JSON ≠ assembly links."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from review_processor.ozon_fbs_supplies import (
    StickersPrintResult,
    build_stickers_print,
    ensure_supply_ready_for_print,
    print_posting_numbers_mismatch_message,
)


class OzonFbsPrintOrderCheckTests(unittest.TestCase):
    def test_mismatch_message_mentions_sync_and_collect(self) -> None:
        msg = print_posting_numbers_mismatch_message(supply_count=10, assembly_count=14)
        self.assertIn("10", msg)
        self.assertIn("14", msg)
        self.assertIn("сборке", msg.lower())
        self.assertIn("синхронизацию", msg.lower())
        self.assertIn("Печать заблокирована", msg)

    def test_ensure_passes_when_sets_match(self) -> None:
        repo = MagicMock()
        with patch(
            "review_processor.ozon_fbs_supplies.get_supply",
            return_value={"posting_numbers": ["P-3", "P-1", "P-2"]},
        ), patch(
            "review_processor.ozon_fbs_supplies._assembly_posting_numbers_for_supply",
            return_value=["P-1", "P-2", "P-3"],
        ), patch("review_processor.ozon_fbs_supplies._log") as log:
            out = ensure_supply_ready_for_print(
                repo,
                user_id=1,
                source_id=13,
                supply_id="OZ-FBS-1",
                kind="picking_list",
            )
        self.assertEqual(out, ["P-3", "P-1", "P-2"])
        log.info.assert_called()

    def test_ensure_blocks_when_assembly_lags(self) -> None:
        repo = MagicMock()
        with patch(
            "review_processor.ozon_fbs_supplies.get_supply",
            return_value={"posting_numbers": [f"P-{i}" for i in range(1, 11)]},
        ), patch(
            "review_processor.ozon_fbs_supplies._assembly_posting_numbers_for_supply",
            return_value=[f"P-{i}" for i in range(1, 15)],
        ), patch("review_processor.ozon_fbs_supplies._log"):
            with self.assertRaises(ValueError) as ctx:
                ensure_supply_ready_for_print(
                    repo,
                    user_id=1,
                    source_id=13,
                    supply_id="OZ-FBS-1",
                    kind="stickers",
                )
        msg = str(ctx.exception)
        self.assertIn("10", msg)
        self.assertIn("14", msg)
        self.assertIn("Печать заблокирована", msg)

    def test_ensure_passes_when_both_empty(self) -> None:
        repo = MagicMock()
        with patch(
            "review_processor.ozon_fbs_supplies.get_supply",
            return_value={"posting_numbers": []},
        ), patch(
            "review_processor.ozon_fbs_supplies._assembly_posting_numbers_for_supply",
            return_value=[],
        ):
            out = ensure_supply_ready_for_print(
                repo,
                user_id=1,
                source_id=13,
                supply_id="OZ-FBS-EMPTY",
            )
        self.assertEqual(out, [])

    def test_build_stickers_print_does_not_fail_when_all_labels_missing(self) -> None:
        repo = MagicMock()
        detail = {
            "supply_id": "OZ-FBS-1",
            "name": "Test",
            "orders": [
                {
                    "posting_number": "A-1",
                    "offer_id": "SKU1",
                    "tab": "awaiting_deliver",
                },
                {
                    "posting_number": "B-2",
                    "offer_id": "SKU2",
                    "tab": "awaiting_deliver",
                },
            ],
            "order_count": 2,
        }
        with patch(
            "review_processor.ozon_fbs_supplies.get_supply_detail_for_print",
            return_value=detail,
        ), patch(
            "review_processor.ozon_fbs_supplies.oz.OzonFbsClient"
        ) as client_cls, patch(
            "review_processor.ozon_fbs_supplies._fetch_label_images",
            return_value={"A-1": [], "B-2": []},
        ), patch(
            "review_processor.ozon_fbs_supplies._retry_and_diagnose_missing_labels",
            return_value=(
                {"A-1": [], "B-2": []},
                ["A-1", "B-2"],
                ["A-1: уже доставляется", "B-2: этикетка не готова"],
            ),
        ), patch("review_processor.ozon_fbs_supplies._log"):
            result = build_stickers_print(
                repo,
                user_id=1,
                source_id=13,
                supply_id="OZ-FBS-1",
                client_id="cid",
                api_key="key",
            )
        client_cls.assert_called_once_with("cid", "key")
        self.assertIsInstance(result, StickersPrintResult)
        self.assertEqual(result.expected_count, 2)
        self.assertEqual(result.loaded_count, 0)
        self.assertEqual(result.missing_posting_numbers, ["A-1", "B-2"])
        self.assertEqual(len(result.missing_reasons or []), 2)
        self.assertIn("Нет этикетки", result.html)
        self.assertIn("Не загружено 2 этик.", result.html)

    def test_batch_page_mismatch_splits_instead_of_misassign(self) -> None:
        from review_processor.ozon_fbs_supplies import _fetch_label_images_for_batch

        client = MagicMock()

        def fake_pdf(nums: list[str]) -> bytes:
            if len(nums) > 1:
                return b"%PDF-BAD"
            return b"%PDF-" + nums[0].encode()

        client.package_label_pdf.side_effect = fake_pdf
        with patch(
            "review_processor.ozon_fbs_supplies._pdf_pages_to_png_b64"
        ) as raster:

            def pages(pdf: bytes) -> list[str]:
                if b"BAD" in pdf:
                    return ["only_one"]
                return [pdf.decode()]

            raster.side_effect = pages
            out = _fetch_label_images_for_batch(client, ["61801002-0977-1", "64544636-0099-1"])
        self.assertTrue(out["61801002-0977-1"])
        self.assertTrue(out["64544636-0099-1"])
        self.assertNotEqual(out["61801002-0977-1"], out["64544636-0099-1"])


if __name__ == "__main__":
    unittest.main()
