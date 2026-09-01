"""Local pick-verify status tone for WB FBS supply-detail refresh."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from review_processor.wb_fbs_detail import check_supply_pick_verify_status


class PickVerifyStatusTests(unittest.TestCase):
    def test_all_verified_correct_is_ok(self) -> None:
        detail = {
            "orders": [
                {"order_id": 101, "kiz_required": False},
                {"order_id": 102, "kiz_required": False},
            ]
        }
        local_pick = {
            101: {"verified": True, "barcode": "4670123456789"},
            102: {"verified": True, "barcode": "4600000000000"},
        }
        skus = {
            101: ["4670123456789"],
            102: ["4600000000000"],
        }
        with (
            patch(
                "review_processor.wb_fbs_detail._cache_get_detail",
                return_value=detail,
            ),
            patch(
                "review_processor.wb_fbs_detail.wb.load_order_pick_map",
                return_value=local_pick,
            ),
            patch(
                "review_processor.wb_fbs_detail.wb.load_order_barcodes_map",
                return_value=skus,
            ),
        ):
            out = check_supply_pick_verify_status(
                MagicMock(), user_id=1, source_id=7, supply_id="WB001"
            )
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["required"], 2)
        self.assertEqual(out["done"], 2)
        self.assertEqual(out["empty"], 0)
        self.assertEqual(out["bad"], 0)

    def test_skip_does_not_turn_ok(self) -> None:
        detail = {
            "orders": [
                {"order_id": 101, "kiz_required": False},
                {"order_id": 102, "kiz_required": False},
            ]
        }
        local_pick = {
            101: {"verified": True, "barcode": "4670123456789"},
            102: {"verified": False, "barcode": ""},
        }
        skus = {101: ["4670123456789"], 102: ["4600000000000"]}
        with (
            patch(
                "review_processor.wb_fbs_detail._cache_get_detail",
                return_value=detail,
            ),
            patch(
                "review_processor.wb_fbs_detail.wb.load_order_pick_map",
                return_value=local_pick,
            ),
            patch(
                "review_processor.wb_fbs_detail.wb.load_order_barcodes_map",
                return_value=skus,
            ),
        ):
            out = check_supply_pick_verify_status(
                MagicMock(), user_id=1, source_id=7, supply_id="WB001"
            )
        self.assertEqual(out["status"], "")
        self.assertEqual(out["empty"], 1)

    def test_bad_barcode_does_not_turn_ok(self) -> None:
        detail = {"orders": [{"order_id": 101, "kiz_required": False}]}
        local_pick = {101: {"verified": True, "barcode": "4600000000000"}}
        skus = {101: ["4670123456789"]}
        with (
            patch(
                "review_processor.wb_fbs_detail._cache_get_detail",
                return_value=detail,
            ),
            patch(
                "review_processor.wb_fbs_detail.wb.load_order_pick_map",
                return_value=local_pick,
            ),
            patch(
                "review_processor.wb_fbs_detail.wb.load_order_barcodes_map",
                return_value=skus,
            ),
        ):
            out = check_supply_pick_verify_status(
                MagicMock(), user_id=1, source_id=7, supply_id="WB001"
            )
        self.assertEqual(out["status"], "")
        self.assertEqual(out["bad"], 1)

    def test_kiz_and_cancelled_orders_excluded(self) -> None:
        detail = {
            "orders": [
                {"order_id": 101, "kiz_required": True},
                {
                    "order_id": 102,
                    "kiz_required": False,
                    "cancel_reason_label": "Отменен клиентом",
                },
                {"order_id": 103, "kiz_required": False},
            ]
        }
        local_pick = {103: {"verified": True, "barcode": "4670123456789"}}
        skus = {103: ["4670123456789"]}
        with (
            patch(
                "review_processor.wb_fbs_detail._cache_get_detail",
                return_value=detail,
            ),
            patch(
                "review_processor.wb_fbs_detail.wb.load_order_pick_map",
                return_value=local_pick,
            ),
            patch(
                "review_processor.wb_fbs_detail.wb.load_order_barcodes_map",
                return_value=skus,
            ),
        ):
            out = check_supply_pick_verify_status(
                MagicMock(), user_id=1, source_id=7, supply_id="WB001"
            )
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["required"], 1)


if __name__ == "__main__":
    unittest.main()
