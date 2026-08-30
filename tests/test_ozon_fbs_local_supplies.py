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
    list_collect_target_supplies,
    rename_local_supply,
)


class OzonFbsLocalSuppliesTests(unittest.TestCase):
    _SOURCE = "Ozon FBS Shop"

    def test_default_supply_name_msk_date(self) -> None:
        when = datetime(2026, 8, 25, 15, 0, tzinfo=ZoneInfo("Europe/Moscow"))
        self.assertEqual(
            default_supply_name(source_name=self._SOURCE, when=when),
            "Поставка Ozon FBS Shop от 25.08.2026",
        )

    def test_unique_supply_name_suffixes(self) -> None:
        base = "Поставка Ozon FBS Shop от 25.08.2026"
        existing = {base}
        self.assertEqual(
            _unique_supply_name(base, existing),
            f"{base} (2)",
        )
        self.assertEqual(
            _unique_supply_name(base, set()),
            base,
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
        ), patch(
            "review_processor.ozon_fbs_supplies._source_display_name",
            return_value=self._SOURCE,
        ):
            preview = preview_ship_all_collect(repo, user_id=1, source_id=2)

        self.assertEqual(preview["posting_count"], 3)
        self.assertTrue(preview["needs_modal"])
        self.assertEqual(len(preview["groups"]), 2)
        self.assertTrue(all(g["mode"] == "create" for g in preview["groups"]))
        names = [g["suggested_name"] for g in preview["groups"]]
        self.assertNotEqual(names[0], names[1])
        self.assertTrue(all(n.startswith("Поставка ") for n in names))
        self.assertTrue(all(self._SOURCE in n for n in names))
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
        ), patch(
            "review_processor.ozon_fbs_supplies._supply_ids_with_tab",
            side_effect=lambda _repo, *, user_id, source_id, tab: (
                {"OZ-FBS-2-1"} if tab == "awaiting_deliver" else set()
            ),
        ):
            preview = preview_ship_all_collect(repo, user_id=1, source_id=2)

        self.assertFalse(preview["needs_modal"])
        self.assertEqual(preview["groups"][0]["mode"], "add_one")
        self.assertEqual(preview["groups"][0]["default_supply_id"], "OZ-FBS-2-1")

    def test_preview_ignores_delivering_supply_when_one_awaiting(self) -> None:
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
                "supply_id": "OZ-FBS-AD",
                "name": "Поставка от 20.08.2026",
                "warehouse_id": 10,
                "warehouse_name": "Склад А",
                "is_empty": False,
                "order_count": 2,
                "posting_numbers": ["X-1", "X-2"],
            },
            {
                "supply_id": "OZ-FBS-DL",
                "name": "Без локальной поставки",
                "warehouse_id": 10,
                "warehouse_name": "Склад А",
                "is_empty": False,
                "order_count": 1,
                "posting_numbers": ["D-1"],
            },
        ]
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies._load_awaiting_packaging_rows",
            return_value=rows,
        ), patch(
            "review_processor.ozon_fbs_supplies.list_open_supplies",
            return_value=open_supplies,
        ), patch(
            "review_processor.ozon_fbs_supplies._supply_ids_with_tab",
            side_effect=lambda _repo, *, user_id, source_id, tab: (
                {"OZ-FBS-AD"} if tab == "awaiting_deliver" else {"OZ-FBS-DL"}
            ),
        ):
            preview = preview_ship_all_collect(repo, user_id=1, source_id=2)

        self.assertFalse(preview["needs_modal"])
        self.assertEqual(preview["groups"][0]["mode"], "add_one")
        self.assertEqual(preview["groups"][0]["default_supply_id"], "OZ-FBS-AD")

    def test_preview_choose_only_for_two_awaiting_supplies(self) -> None:
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
                "supply_id": "OZ-FBS-1",
                "name": "Поставка 1",
                "warehouse_id": 10,
                "warehouse_name": "Склад А",
                "is_empty": False,
                "order_count": 1,
                "posting_numbers": ["X-1"],
            },
            {
                "supply_id": "OZ-FBS-2",
                "name": "Поставка 2",
                "warehouse_id": 10,
                "warehouse_name": "Склад А",
                "is_empty": False,
                "order_count": 1,
                "posting_numbers": ["X-2"],
            },
        ]
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies._load_awaiting_packaging_rows",
            return_value=rows,
        ), patch(
            "review_processor.ozon_fbs_supplies.list_open_supplies",
            return_value=open_supplies,
        ), patch(
            "review_processor.ozon_fbs_supplies._supply_ids_with_tab",
            side_effect=lambda _repo, *, user_id, source_id, tab: (
                {"OZ-FBS-1", "OZ-FBS-2"} if tab == "awaiting_deliver" else set()
            ),
        ):
            preview = preview_ship_all_collect(repo, user_id=1, source_id=2)

        self.assertTrue(preview["needs_modal"])
        self.assertEqual(preview["groups"][0]["mode"], "choose")
        self.assertEqual(len(preview["groups"][0]["compatible_supplies"]), 2)

    def test_list_collect_target_supplies_excludes_delivering_only(self) -> None:
        repo = MagicMock()
        open_supplies = [
            {
                "supply_id": "AD",
                "name": "Awaiting",
                "is_empty": False,
                "order_count": 1,
            },
            {
                "supply_id": "DL",
                "name": "Delivering",
                "is_empty": False,
                "order_count": 1,
            },
            {
                "supply_id": "EM",
                "name": "Empty",
                "is_empty": True,
                "order_count": 0,
            },
        ]
        with patch(
            "review_processor.ozon_fbs_supplies.list_open_supplies",
            return_value=open_supplies,
        ), patch(
            "review_processor.ozon_fbs_supplies._supply_ids_with_tab",
            side_effect=lambda _repo, *, user_id, source_id, tab: (
                {"AD"} if tab == "awaiting_deliver" else {"DL"}
            ),
        ):
            out = list_collect_target_supplies(repo, user_id=1, source_id=2)
        ids = {s["supply_id"] for s in out}
        self.assertEqual(ids, {"AD", "EM"})

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

    def test_selection_preview_rejects_mixed_warehouses(self) -> None:
        from review_processor.ozon_fbs_supplies import preview_selection_supply

        repo = MagicMock()
        rows = [
            {
                "posting_number": "A-1",
                "tab": "awaiting_packaging",
                "supply_id": "",
                "warehouse_id": 10,
                "warehouse_name": "A",
            },
            {
                "posting_number": "B-1",
                "tab": "awaiting_packaging",
                "supply_id": "",
                "warehouse_id": 20,
                "warehouse_name": "B",
            },
        ]
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies._load_postings_by_numbers",
            return_value=rows,
        ), patch(
            "review_processor.ozon_fbs_supplies.list_open_supplies",
            return_value=[],
        ):
            preview = preview_selection_supply(
                repo, user_id=1, source_id=17, posting_numbers=["A-1", "B-1"]
            )
        self.assertFalse(preview["ok"])
        self.assertTrue(any("склад" in e.lower() for e in preview["errors"]))

    def test_selection_preview_ok_same_warehouse(self) -> None:
        from review_processor.ozon_fbs_supplies import preview_selection_supply

        repo = MagicMock()
        rows = [
            {
                "posting_number": "A-1",
                "tab": "awaiting_packaging",
                "supply_id": "",
                "warehouse_id": 10,
                "warehouse_name": "A",
            },
            {
                "posting_number": "A-2",
                "tab": "awaiting_packaging",
                "supply_id": "",
                "warehouse_id": 10,
                "warehouse_name": "A",
            },
        ]
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies._load_postings_by_numbers",
            return_value=rows,
        ), patch(
            "review_processor.ozon_fbs_supplies.list_open_supplies",
            return_value=[],
        ):
            preview = preview_selection_supply(
                repo, user_id=1, source_id=17, posting_numbers=["A-1", "A-2"]
            )
        self.assertTrue(preview["ok"])
        self.assertEqual(preview["order_count"], 2)
        self.assertEqual(preview["traits"]["warehouse_id"], 10)


class OzonFbsDeliveringSuppliesTests(unittest.TestCase):
    def test_adopt_orphan_delivering_creates_named_supply(self) -> None:
        from review_processor.ozon_fbs_supplies import (
            ORPHAN_DELIVERING_SUPPLY_NAME,
            adopt_orphan_delivering_postings,
        )

        repo = MagicMock()
        orphans = [
            {
                "posting_number": "D-1",
                "warehouse_id": 10,
                "warehouse_name": "Склад А",
            },
        ]
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies._load_orphan_tab_rows",
            return_value=orphans,
        ), patch(
            "review_processor.ozon_fbs_supplies.list_open_supplies",
            return_value=[],
        ), patch(
            "review_processor.ozon_fbs_supplies._find_supply_by_name",
            return_value=None,
        ), patch(
            "review_processor.ozon_fbs_supplies._create_local_supply",
            return_value="OZ-FBS-DEL",
        ) as create:
            out = adopt_orphan_delivering_postings(
                repo, user_id=1, source_id=17
            )
        self.assertEqual(out["adopted"], 1)
        self.assertEqual(out["created_supplies"][0]["supply_id"], "OZ-FBS-DEL")
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["name"], ORPHAN_DELIVERING_SUPPLY_NAME)
        self.assertIsNone(create.call_args.kwargs["force_tab"])

    def test_adopt_orphan_delivering_links_to_existing_supply(self) -> None:
        from review_processor.ozon_fbs_supplies import adopt_orphan_delivering_postings

        repo = MagicMock()
        orphans = [{"posting_number": "D-2", "warehouse_id": 10, "warehouse_name": "A"}]
        existing = {"supply_id": "OZ-EXIST", "name": "Без локальной поставки"}
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies._load_orphan_tab_rows",
            return_value=orphans,
        ), patch(
            "review_processor.ozon_fbs_supplies._find_supply_by_name",
            return_value=existing,
        ), patch(
            "review_processor.ozon_fbs_supplies._link_postings_to_supply_only"
        ) as link, patch(
            "review_processor.ozon_fbs_supplies._create_local_supply"
        ) as create:
            out = adopt_orphan_delivering_postings(
                repo, user_id=1, source_id=17
            )
        self.assertEqual(out["adopted"], 1)
        link.assert_called_once()
        create.assert_not_called()
        self.assertEqual(link.call_args.kwargs["supply_id"], "OZ-EXIST")

    def test_get_supply_detail_delivering_read_only(self) -> None:
        from review_processor import ozon_fbs as oz
        from review_processor.ozon_fbs_supplies import get_supply_detail

        repo = MagicMock()
        repo.get_product_name_by_article.return_value = {}
        repo.get_product_name_by_ozon_sku.return_value = {}
        repo.get_product_barcodes_map.return_value = {}
        repo.get_product_photo_map.return_value = {}
        supply_row = {
            "supply_id": "OZ-1",
            "name": "Без локальной поставки",
            "warehouse_name": "Склад",
            "posting_numbers": ["P-1"],
        }
        posting_row = {
            "posting_number": "P-1",
            "offer_id": "art",
            "sku": "",
            "warehouse_name": "Склад",
            "barcodes_json": "[]",
            "marking_codes_json": "[]",
            "tab": oz.TAB_DELIVERING,
        }
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies.get_supply",
            return_value=supply_row,
        ), patch(
            "review_processor.ozon_fbs_supplies._assembly_posting_numbers_for_supply_tab",
            return_value=["P-1"],
        ), patch.object(repo, "_connect") as conn_ctx:
            conn = MagicMock()
            conn_ctx.return_value.__enter__.return_value = conn
            conn.execute.return_value.fetchall.return_value = [posting_row]
            repo._row_to_dict.side_effect = lambda r: r
            detail = get_supply_detail(
                repo,
                user_id=1,
                source_id=17,
                supply_id="OZ-1",
                posting_tab=oz.TAB_DELIVERING,
            )
        self.assertTrue(detail["read_only"])
        self.assertEqual(detail["posting_tab"], oz.TAB_DELIVERING)
        self.assertEqual(detail["order_count"], 1)

    def test_get_supply_detail_for_print_respects_posting_tab(self) -> None:
        from review_processor.ozon_fbs_supplies import get_supply_detail_for_print

        repo = MagicMock()
        with patch(
            "review_processor.ozon_fbs_supplies.get_supply_detail",
            return_value={
                "supply_id": "OZ-1",
                "order_count": 1,
                "orders": [{"posting_number": "P-await", "tab": "awaiting_deliver"}],
                "posting_tab": "awaiting_deliver",
            },
        ) as get_detail, patch(
            "review_processor.ozon_fbs_supplies.ensure_supply_ready_for_print"
        ) as ensure:
            detail = get_supply_detail_for_print(
                repo,
                user_id=1,
                source_id=2,
                supply_id="OZ-1",
                kind="picking_list",
                posting_tab="awaiting_deliver",
            )
        ensure.assert_not_called()
        get_detail.assert_called_once()
        self.assertEqual(
            get_detail.call_args.kwargs.get("posting_tab"), "awaiting_deliver"
        )
        self.assertEqual(detail["order_count"], 1)

    def test_get_supply_detail_awaiting_tab_excludes_delivering_nums(self) -> None:
        from review_processor import ozon_fbs as oz
        from review_processor.ozon_fbs_supplies import get_supply_detail

        repo = MagicMock()
        repo.get_product_name_by_article.return_value = {}
        repo.get_product_name_by_ozon_sku.return_value = {}
        repo.get_product_barcodes_map.return_value = {}
        repo.get_product_photo_map.return_value = {}
        supply_row = {
            "supply_id": "OZ-MIX",
            "name": "Смешанная",
            "warehouse_name": "WH",
            "posting_numbers": ["P-1", "P-2"],
        }
        posting_row = {
            "posting_number": "P-1",
            "offer_id": "art",
            "sku": "",
            "warehouse_name": "WH",
            "barcodes_json": "[]",
            "marking_codes_json": "[]",
            "tab": oz.TAB_AWAITING_DELIVER,
        }
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies.get_supply",
            return_value=supply_row,
        ), patch(
            "review_processor.ozon_fbs_supplies._assembly_posting_numbers_for_supply_tab",
            return_value=["P-1"],
        ) as tab_nums, patch(
            "review_processor.ozon_fbs_supplies._assembly_posting_numbers_for_supply"
        ) as all_nums, patch.object(repo, "_connect") as conn_ctx:
            conn = MagicMock()
            conn_ctx.return_value.__enter__.return_value = conn
            conn.execute.return_value.fetchall.return_value = [posting_row]
            repo._row_to_dict.side_effect = lambda r: r
            detail = get_supply_detail(
                repo,
                user_id=1,
                source_id=2,
                supply_id="OZ-MIX",
                posting_tab=oz.TAB_AWAITING_DELIVER,
            )
        tab_nums.assert_called_once()
        all_nums.assert_not_called()
        self.assertEqual(detail["order_count"], 1)
        self.assertEqual(detail["orders"][0]["posting_number"], "P-1")

    def test_get_supply_detail_fallback_when_supply_row_missing(self) -> None:
        from review_processor.ozon_fbs_supplies import get_supply_detail

        repo = MagicMock()
        repo.get_product_name_by_article.return_value = {}
        repo.get_product_name_by_ozon_sku.return_value = {}
        repo.get_product_barcodes_map.return_value = {}
        repo.get_product_photo_map.return_value = {}
        posting_row = {
            "posting_number": "P-9",
            "offer_id": "art9",
            "sku": "",
            "warehouse_name": "Склад 9",
            "barcodes_json": "[]",
            "marking_codes_json": "[]",
            "tab": "awaiting_deliver",
        }
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies.get_supply",
            return_value=None,
        ), patch(
            "review_processor.ozon_fbs_supplies._assembly_posting_numbers_for_supply",
            return_value=["P-9"],
        ), patch.object(repo, "_connect") as conn_ctx:
            conn = MagicMock()
            conn_ctx.return_value.__enter__.return_value = conn
            conn.execute.return_value.fetchone.return_value = {
                "warehouse_name": "Склад 9",
                "warehouse_id": 9,
            }
            conn.execute.return_value.fetchall.return_value = [posting_row]
            repo._row_to_dict.side_effect = lambda r: r
            detail = get_supply_detail(
                repo,
                user_id=1,
                source_id=17,
                supply_id="OZ-MISSING",
            )
        self.assertEqual(detail["supply_id"], "OZ-MISSING")
        self.assertEqual(detail["order_count"], 1)
        self.assertEqual(detail["orders"][0]["posting_number"], "P-9")

    def test_get_supply_detail_prefers_assembly_over_empty_json(self) -> None:
        from review_processor.ozon_fbs_supplies import get_supply_detail

        repo = MagicMock()
        repo.get_product_name_by_article.return_value = {}
        repo.get_product_name_by_ozon_sku.return_value = {}
        repo.get_product_barcodes_map.return_value = {}
        repo.get_product_photo_map.return_value = {}
        supply_row = {
            "supply_id": "OZ-2",
            "name": "Поставка",
            "warehouse_name": "Склад",
            "posting_numbers": [],
        }
        posting_row = {
            "posting_number": "P-2",
            "offer_id": "art2",
            "sku": "",
            "warehouse_name": "Склад",
            "barcodes_json": "[]",
            "marking_codes_json": "[]",
            "tab": "awaiting_deliver",
        }
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies.get_supply",
            return_value=supply_row,
        ), patch(
            "review_processor.ozon_fbs_supplies._assembly_posting_numbers_for_supply",
            return_value=["P-2"],
        ), patch.object(repo, "_connect") as conn_ctx:
            conn = MagicMock()
            conn_ctx.return_value.__enter__.return_value = conn
            conn.execute.return_value.fetchall.return_value = [posting_row]
            repo._row_to_dict.side_effect = lambda r: r
            detail = get_supply_detail(
                repo,
                user_id=1,
                source_id=17,
                supply_id="OZ-2",
            )
        self.assertEqual(detail["order_count"], 1)

    def test_rename_local_supply_updates_name(self) -> None:
        repo = MagicMock()
        supply = {
            "supply_id": "OZ-1",
            "name": "Старое имя",
            "done": False,
            "posting_numbers": ["P-1"],
            "order_count": 1,
        }
        renamed = {**supply, "name": "Новое имя"}
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies.get_supply",
            side_effect=[supply, renamed],
        ), patch(
            "review_processor.ozon_fbs_supplies.list_open_supplies",
            return_value=[{"supply_id": "OZ-2", "name": "Другая"}],
        ), patch(
            "review_processor.ozon_fbs_supplies._assembly_posting_numbers_for_supply_tab",
            return_value=[],
        ), patch.object(repo, "_connect") as conn_ctx:
            conn = MagicMock()
            conn_ctx.return_value.__enter__.return_value = conn
            out = rename_local_supply(
                repo,
                user_id=1,
                source_id=2,
                supply_id="OZ-1",
                name="Новое имя",
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["name"], "Новое имя")
        self.assertFalse(out.get("split"))
        conn.execute.assert_called_once()

    def test_rename_local_supply_splits_delivering_keeps_old_name(self) -> None:
        """Mixed supply: awaiting gets new name; delivering keeps old on a fork."""
        repo = MagicMock()
        supply = {
            "supply_id": "OZ-MIX",
            "name": "Старое",
            "done": False,
            "warehouse_id": 10,
            "warehouse_name": "WH",
            "posting_numbers": ["A-1", "D-1"],
            "order_count": 2,
        }
        renamed = {**supply, "name": "Новое", "posting_numbers": ["A-1"]}

        def _tab_nums(**kwargs):
            tab = str(kwargs.get("tab") or "")
            if tab == "delivering":
                return ["D-1"]
            if tab == "awaiting_deliver":
                return ["A-1"]
            return []

        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies.get_supply",
            side_effect=[supply, renamed],
        ), patch(
            "review_processor.ozon_fbs_supplies.list_open_supplies",
            return_value=[],
        ), patch(
            "review_processor.ozon_fbs_supplies._assembly_posting_numbers_for_supply_tab",
            side_effect=lambda *a, **k: _tab_nums(**k),
        ), patch(
            "review_processor.ozon_fbs_supplies._create_local_supply",
            return_value="OZ-FORK",
        ) as create_mock, patch(
            "review_processor.ozon_fbs_supplies._assembly_posting_numbers_for_supply",
            return_value=["A-1"],
        ), patch(
            "review_processor.ozon_fbs_supplies._set_supply_posting_numbers"
        ) as set_nums, patch.object(repo, "_connect") as conn_ctx:
            conn = MagicMock()
            conn_ctx.return_value.__enter__.return_value = conn
            out = rename_local_supply(
                repo,
                user_id=1,
                source_id=2,
                supply_id="OZ-MIX",
                name="Новое",
            )

        self.assertTrue(out["ok"])
        self.assertTrue(out["split"])
        self.assertEqual(out["name"], "Новое")
        self.assertEqual(out["delivering_supply_id"], "OZ-FORK")
        self.assertEqual(out["delivering_name"], "Старое")
        self.assertEqual(out["delivering_count"], 1)
        create_mock.assert_called_once()
        ckwargs = create_mock.call_args.kwargs
        self.assertEqual(ckwargs["name"], "Старое")
        self.assertEqual(ckwargs["posting_numbers"], ["D-1"])
        self.assertIsNone(ckwargs["force_tab"])
        set_nums.assert_called_once()
        self.assertEqual(set_nums.call_args.kwargs["posting_numbers"], ["A-1"])

    def test_rename_local_supply_rejects_duplicate_name(self) -> None:
        repo = MagicMock()
        supply = {
            "supply_id": "OZ-1",
            "name": "Старое",
            "done": False,
            "posting_numbers": [],
            "order_count": 0,
        }
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch(
            "review_processor.ozon_fbs_supplies.get_supply",
            return_value=supply,
        ), patch(
            "review_processor.ozon_fbs_supplies.list_open_supplies",
            return_value=[{"supply_id": "OZ-2", "name": "Занято"}],
        ):
            with self.assertRaises(ValueError):
                rename_local_supply(
                    repo,
                    user_id=1,
                    source_id=2,
                    supply_id="OZ-1",
                    name="Занято",
                )

    def test_build_supply_items_uses_local_name_for_any_tab(self) -> None:
        """Renamed name from ozon_fbs_supplies must show on delivering too."""
        from review_processor.ozon_fbs_supplies import _build_supply_items_for_tab

        repo = MagicMock()
        group = {
            "supply_id": "OZ-1",
            "order_count": 2,
            "warehouse_name": "WH",
            "warehouse_id": 1,
            "last_posting_at": "2026-08-27",
        }
        meta_row = {
            "supply_id": "OZ-1",
            "name": "Переименованная поставка",
            "warehouse_name": "WH",
            "warehouse_id": 1,
            "created_at": "2026-08-27",
        }
        with patch(
            "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
        ), patch.object(repo, "_connect") as conn_ctx:
            conn = MagicMock()
            conn_ctx.return_value.__enter__.return_value = conn
            conn.execute.return_value.fetchall.side_effect = [[group], [meta_row]]
            repo._row_to_dict.side_effect = lambda r: r
            items = _build_supply_items_for_tab(
                repo, user_id=1, source_id=2, tab="delivering"
            )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "Переименованная поставка")

    def test_sort_supply_detail_orders_oldest_first(self) -> None:
        from review_processor.ozon_fbs_supplies import (
            sort_supply_detail_orders_oldest_first,
        )

        rows = [
            {"posting_number": "B", "created_at_ozon": "2026-08-30T12:00:00Z"},
            {"posting_number": "A", "created_at_ozon": "2026-08-29T12:00:00Z"},
            {"posting_number": "C", "in_process_at": "2026-08-28T12:00:00Z"},
            {"posting_number": "Z"},
        ]
        out = sort_supply_detail_orders_oldest_first(rows)
        self.assertEqual([o["posting_number"] for o in out], ["C", "A", "B", "Z"])
        # Helper must not mutate the source list (print paths share dicts).
        self.assertEqual(rows[0]["posting_number"], "B")


if __name__ == "__main__":
    unittest.main()
