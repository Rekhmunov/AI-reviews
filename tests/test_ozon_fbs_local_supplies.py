"""Tests for Ozon FBS local supplies (collect naming / preview / execute)."""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from review_processor.ozon_fbs_supplies import (
    default_supply_name,
    _unique_supply_name,
    preview_ship_all_collect,
    execute_ship_all_collect,
)


class OzonFbsLocalSuppliesTests(unittest.TestCase):
    def test_default_supply_name_msk_date(self) -> None:
        when = datetime(2026, 8, 25, 15, 0, tzinfo=ZoneInfo("Europe/Moscow"))
        self.assertEqual(default_supply_name(when=when), "Поставка от 25.08.2026")

    def test_unique_supply_name_suffixes(self) -> None:
        existing = {"Поставка от 25.08.2026"}
        self.assertEqual(
            _unique_supply_name("Поставка от 25.08.2026", existing),
            "Поставка от 25.08.2026 (2)",
        )
        self.assertEqual(
            _unique_supply_name("Поставка от 25.08.2026", set()),
            "Поставка от 25.08.2026",
        )

    def test_preview_create_mode_groups_by_warehouse(self) -> None:
        repo = MagicMock()
        rows = [
            {
                "posting_number": "A-1",
                "warehouse_id": 10,
                "warehouse_name": "Склад А",
            },
            {
                "posting_number": "A-2",
                "warehouse_id": 10,
                "warehouse_name": "Склад А",
            },
            {
                "posting_number": "B-1",
                "warehouse_id": 20,
                "warehouse_name": "Склад Б",
            },
        ]
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies._load_awaiting_packaging_rows",
            return_value=rows,
        ), patch(
            "review_processor.ozon_fbs_supplies.list_open_supplies",
            return_value=[],
        ):
            preview = preview_ship_all_collect(repo, user_id=1, source_id=2)

        self.assertEqual(preview["posting_count"], 3)
        self.assertTrue(preview["needs_modal"])
        self.assertEqual(len(preview["groups"]), 2)
        self.assertTrue(all(g["mode"] == "create" for g in preview["groups"]))
        names = [g["suggested_name"] for g in preview["groups"]]
        self.assertNotEqual(names[0], names[1])
        self.assertTrue(all(n.startswith("Поставка от ") for n in names))
        self.assertNotIn("склад", names[0].lower())
        for n in names:
            self.assertNotIn(n, preview["existing_names"])

    def test_preview_add_one_skips_modal(self) -> None:
        repo = MagicMock()
        rows = [
            {
                "posting_number": "A-1",
                "warehouse_id": 10,
                "warehouse_name": "Склад А",
            },
        ]
        open_supplies = [
            {
                "supply_id": "OZ-FBS-2-1",
                "name": "Поставка от 20.08.2026",
                "warehouse_id": 10,
                "warehouse_name": "Склад А",
                "is_empty": False,
                "order_count": 3,
                "posting_numbers": ["X-1", "X-2", "X-3"],
            }
        ]
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies._load_awaiting_packaging_rows",
            return_value=rows,
        ), patch(
            "review_processor.ozon_fbs_supplies.list_open_supplies",
            return_value=open_supplies,
        ):
            preview = preview_ship_all_collect(repo, user_id=1, source_id=2)

        self.assertFalse(preview["needs_modal"])
        self.assertEqual(preview["groups"][0]["mode"], "add_one")
        self.assertEqual(preview["groups"][0]["default_supply_id"], "OZ-FBS-2-1")

    def test_execute_create_calls_ship_and_local_supply(self) -> None:
        repo = MagicMock()
        preview = {
            "ok": True,
            "posting_count": 1,
            "groups": [
                {
                    "group_key": "wh10",
                    "warehouse_id": 10,
                    "warehouse_name": "Склад А",
                    "posting_numbers": ["A-1"],
                    "suggested_name": "Поставка от 25.08.2026",
                    "mode": "create",
                    "default_supply_id": "",
                    "compatible_supplies": [],
                }
            ],
        }
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies.preview_ship_all_collect",
            return_value=preview,
        ), patch(
            "review_processor.ozon_fbs_supplies.list_open_supplies",
            return_value=[],
        ), patch(
            "review_processor.ozon_fbs_supplies.oz.OzonFbsClient"
        ), patch(
            "review_processor.ozon_fbs_supplies.oz_detail.ship_posting"
        ) as ship, patch(
            "review_processor.ozon_fbs_supplies._create_local_supply",
            return_value="OZ-FBS-NEW",
        ) as create:
            out = execute_ship_all_collect(
                repo,
                user_id=1,
                source_id=2,
                client_id="c",
                api_key="k",
                decisions=[{"group_key": "wh10", "action": "create", "name": "Поставка от 25.08.2026"}],
            )
        self.assertEqual(out["shipped"], 1)
        self.assertTrue(out["goto_awaiting_deliver"])
        self.assertEqual(out["created_supplies"][0]["supply_id"], "OZ-FBS-NEW")
        ship.assert_called_once()
        create.assert_called_once()

    def test_adopt_orphans_creates_supply(self) -> None:
        from review_processor.ozon_fbs_supplies import adopt_orphan_awaiting_deliver_postings

        repo = MagicMock()
        orphans = [
            {
                "posting_number": "O-1",
                "warehouse_id": 10,
                "warehouse_name": "Склад А",
            },
            {
                "posting_number": "O-2",
                "warehouse_id": 10,
                "warehouse_name": "Склад А",
            },
        ]
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies._load_orphan_awaiting_deliver_rows",
            return_value=orphans,
        ), patch(
            "review_processor.ozon_fbs_supplies.list_open_supplies",
            return_value=[],
        ), patch(
            "review_processor.ozon_fbs_supplies._create_local_supply",
            return_value="OZ-FBS-ORPHAN",
        ) as create:
            out = adopt_orphan_awaiting_deliver_postings(
                repo, user_id=1, source_id=17
            )
        self.assertEqual(out["adopted"], 2)
        self.assertEqual(out["created_supplies"][0]["supply_id"], "OZ-FBS-ORPHAN")
        create.assert_called_once()
        args = create.call_args
        self.assertEqual(
            sorted(args.kwargs["posting_numbers"]),
            ["O-1", "O-2"],
        )

    def test_adopt_orphans_adds_to_existing_warehouse_supply(self) -> None:
        from review_processor.ozon_fbs_supplies import adopt_orphan_awaiting_deliver_postings

        repo = MagicMock()
        orphans = [
            {
                "posting_number": "O-9",
                "warehouse_id": 10,
                "warehouse_name": "Склад А",
            },
        ]
        open_supplies = [
            {
                "supply_id": "OZ-EXISTING",
                "name": "Поставка от 25.08.2026",
                "warehouse_id": 10,
                "is_empty": False,
                "order_count": 5,
                "posting_numbers": ["X-1"],
            }
        ]
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies._load_orphan_awaiting_deliver_rows",
            return_value=orphans,
        ), patch(
            "review_processor.ozon_fbs_supplies.list_open_supplies",
            return_value=open_supplies,
        ), patch(
            "review_processor.ozon_fbs_supplies._add_postings_to_supply"
        ) as add, patch(
            "review_processor.ozon_fbs_supplies._create_local_supply"
        ) as create:
            out = adopt_orphan_awaiting_deliver_postings(
                repo, user_id=1, source_id=17
            )
        self.assertEqual(out["adopted"], 1)
        add.assert_called_once()
        create.assert_not_called()
        self.assertEqual(add.call_args.kwargs["supply_id"], "OZ-EXISTING")


if __name__ == "__main__":
    unittest.main()
