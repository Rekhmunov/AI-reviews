"""Block picking/sticker print when WB order-ids ≠ local assembly links."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from review_processor.wb_fbs_detail import (
    ensure_supply_ready_for_print,
    print_order_ids_mismatch_message,
)


class WbFbsPrintOrderCheckTests(unittest.TestCase):
    def test_mismatch_message_mentions_sync_and_collect(self):
        msg = print_order_ids_mismatch_message(wb_count=186, assembly_count=260)
        self.assertIn("186", msg)
        self.assertIn("260", msg)
        self.assertIn("сборке", msg.lower())
        self.assertIn("синхронизацию", msg.lower())
        self.assertIn("МГТ", msg)

    def test_ensure_passes_when_sets_match(self):
        repo = MagicMock()
        with patch(
            "review_processor.wb_fbs_detail.wb.WbFbsClient"
        ) as client_cls, patch(
            "review_processor.wb_fbs_detail._assembly_order_ids_for_supply",
            return_value=[10, 20, 30],
        ), patch("review_processor.wb_fbs_detail.time.sleep"):
            client_cls.return_value.get_supply_order_ids.return_value = [30, 10, 20]
            out = ensure_supply_ready_for_print(
                repo,
                user_id=1,
                source_id=13,
                api_key="key",
                supply_id="WB-GI-1",
            )
        self.assertEqual(out, [30, 10, 20])

    def test_ensure_blocks_when_wb_lags_behind_assembly(self):
        repo = MagicMock()
        with patch(
            "review_processor.wb_fbs_detail.wb.WbFbsClient"
        ) as client_cls, patch(
            "review_processor.wb_fbs_detail._assembly_order_ids_for_supply",
            return_value=list(range(1, 261)),
        ), patch("review_processor.wb_fbs_detail.time.sleep"):
            client_cls.return_value.get_supply_order_ids.return_value = list(range(1, 187))
            with self.assertRaises(ValueError) as ctx:
                ensure_supply_ready_for_print(
                    repo,
                    user_id=1,
                    source_id=13,
                    api_key="key",
                    supply_id="WB-GI-269260516",
                )
        msg = str(ctx.exception)
        self.assertIn("186", msg)
        self.assertIn("260", msg)
        self.assertIn("Печать заблокирована", msg)

    def test_ensure_blocks_when_wb_unreachable(self):
        repo = MagicMock()
        with patch(
            "review_processor.wb_fbs_detail.wb.WbFbsClient"
        ) as client_cls, patch("review_processor.wb_fbs_detail.time.sleep"):
            client_cls.return_value.get_supply_order_ids.side_effect = RuntimeError("timeout")
            with self.assertRaises(ValueError) as ctx:
                ensure_supply_ready_for_print(
                    repo,
                    user_id=1,
                    source_id=13,
                    api_key="key",
                    supply_id="WB-GI-1",
                )
        self.assertIn("синхронизацию", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
