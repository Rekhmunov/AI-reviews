"""TSD hub summary must stay local/DB-only (no WB payload builders)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from review_processor.wb_fbs_detail import build_tsd_hub_progress_from_local


def _row(
    *,
    order_id: int,
    raw: dict,
    kiz_codes: list[str] | None = None,
    pick_verified: bool = False,
    pick_barcode: str = "",
) -> dict:
    return {
        "order_id": order_id,
        "raw_json": json.dumps(raw),
        "kiz_codes_json": json.dumps(kiz_codes or []),
        "pick_verified": pick_verified,
        "pick_barcode": pick_barcode,
    }


class TsdHubProgressLocalTests(unittest.TestCase):
    def test_splits_kiz_and_pick_from_raw_meta(self) -> None:
        repo = MagicMock()
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.__exit__.return_value = False
        repo._connect.return_value = conn
        repo._sql.side_effect = lambda s: s
        conn.execute.return_value.fetchall.return_value = [
            _row(
                order_id=1,
                raw={"requiredMeta": ["sgtin"]},
                kiz_codes=["010460000000000021XXXX"],
            ),
            _row(
                order_id=2,
                raw={"requiredMeta": ["sgtin"]},
                kiz_codes=[],
            ),
            _row(
                order_id=3,
                raw={"requiredMeta": []},
                pick_verified=True,
                pick_barcode="4670123456789",
            ),
            _row(
                order_id=4,
                raw={},
                pick_verified=False,
                pick_barcode="",
            ),
        ]

        out = build_tsd_hub_progress_from_local(
            repo, user_id=10, source_id=7, supply_id="WB-1"
        )
        self.assertEqual(out["kiz"], {"total": 2, "done": 1})
        self.assertEqual(out["pick"], {"total": 2, "done": 1})
        self.assertEqual(out["order_count"], 4)

    def test_optional_meta_sgtin_counts_as_kiz(self) -> None:
        repo = MagicMock()
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.__exit__.return_value = False
        repo._connect.return_value = conn
        repo._sql.side_effect = lambda s: s
        conn.execute.return_value.fetchall.return_value = [
            _row(order_id=9, raw={"optionalMeta": ["sgtin"]}),
        ]
        out = build_tsd_hub_progress_from_local(
            repo, user_id=1, source_id=1, supply_id="S"
        )
        self.assertEqual(out["kiz"]["total"], 1)
        self.assertEqual(out["pick"]["total"], 0)

    def test_empty_supply_id(self) -> None:
        repo = MagicMock()
        out = build_tsd_hub_progress_from_local(
            repo, user_id=1, source_id=1, supply_id="  "
        )
        self.assertEqual(out["order_count"], 0)
        repo._connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
