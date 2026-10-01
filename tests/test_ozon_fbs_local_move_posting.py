"""Local Ozon FBS move posting into awaiting_deliver / delivering supply."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz
from review_processor.ozon_fbs_supplies import (
    _sync_supply_composition_from_assembly,
    create_local_supply_from_postings,
    get_supply_detail_for_print,
    list_supplies_for_local_move,
    move_posting_to_local_supply,
    move_postings_to_local_supply,
)


def test_list_supplies_for_local_move_awaiting_only() -> None:
    repo = MagicMock()
    awaiting = [
        {
            "supply_id": "S-A",
            "name": "Awaiting one",
            "order_count": 3,
            "warehouse_label": "WH-A",
        }
    ]
    with patch(
        "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
    ), patch(
        "review_processor.ozon_fbs_supplies._build_supply_items_for_tab",
        return_value=awaiting,
    ), patch(
        "review_processor.ozon_fbs_supplies.list_open_supplies",
        return_value=[
            {
                "supply_id": "S-EMPTY",
                "name": "Empty shell",
                "is_empty": True,
                "warehouse_name": "WH-E",
            },
            {
                "supply_id": "S-D",
                "name": "Delivering-only shell",
                "is_empty": True,
                "warehouse_name": "WH-D",
            },
        ],
    ), patch(
        "review_processor.ozon_fbs_supplies._supply_ids_with_tab",
        side_effect=lambda *_a, tab, **_k: (
            {"S-D"} if tab == oz.TAB_DELIVERING else set()
        ),
    ):
        out = list_supplies_for_local_move(repo, user_id=1, source_id=2)

    assert out["ok"] is True
    assert out["total"] == 2
    assert out["delivering"] == []
    assert [x["supply_id"] for x in out["awaiting_deliver"]] == ["S-A", "S-EMPTY"]
    assert out["awaiting_deliver"][0]["tab"] == oz.TAB_AWAITING_DELIVER
    assert out["awaiting_deliver"][0]["warehouse_name"] == "WH-A"
    assert out["awaiting_deliver"][1]["order_count"] == 0
    assert out["awaiting_deliver"][1]["warehouse_name"] == "WH-E"
    assert [x["supply_id"] for x in out["items"]] == ["S-A", "S-EMPTY"]


def test_sync_supply_composition_from_assembly_keeps_order_and_appends() -> None:
    set_calls: list[dict] = []
    with patch(
        "review_processor.ozon_fbs_supplies._assembly_posting_numbers_for_supply",
        return_value=["PN-NEW", "PN-KEEP", "PN-EXTRA"],
    ), patch(
        "review_processor.ozon_fbs_supplies.get_supply",
        return_value={
            "supply_id": "S-1",
            "posting_numbers": ["PN-KEEP", "PN-STALE", "PN-NEW"],
        },
    ), patch(
        "review_processor.ozon_fbs_supplies._set_supply_posting_numbers",
        side_effect=lambda *_a, **kwargs: set_calls.append(dict(kwargs)),
    ):
        out = _sync_supply_composition_from_assembly(
            MagicMock(), user_id=1, source_id=2, supply_id="S-1"
        )

    assert out == ["PN-KEEP", "PN-NEW", "PN-EXTRA"]
    assert set_calls[0]["posting_numbers"] == ["PN-KEEP", "PN-NEW", "PN-EXTRA"]


def test_move_posting_to_local_supply_syncs_composition_and_clears_container() -> None:
    repo = MagicMock()
    sync_calls: list[str] = []
    updates: list[str] = []

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=()):
            sql_s = str(sql)
            cur = MagicMock()
            if "SELECT posting_number, supply_id, tab, status" in sql_s:
                cur.fetchone.return_value = {
                    "posting_number": "PN-1",
                    "supply_id": "OLD-S",
                    "tab": oz.TAB_DELIVERING,
                    "status": oz.TAB_DELIVERING,
                }
            elif "UPDATE ozon_fbs_postings" in sql_s:
                updates.append(sql_s)
                cur.fetchone.return_value = None
            else:
                cur.fetchone.return_value = None
            return cur

    repo._connect.return_value = _Conn()
    repo._sql.side_effect = lambda q: q
    repo._row_to_dict.side_effect = lambda r: dict(r)

    with patch(
        "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
    ), patch(
        "review_processor.ozon_fbs_supplies.oz.ensure_ozon_fbs_tables"
    ), patch(
        "review_processor.ozon_fbs_supplies.get_supply",
        side_effect=lambda *_a, supply_id, **_k: {
            "supply_id": supply_id,
            "name": f"Name {supply_id}",
            "posting_numbers": (
                ["PN-1", "OTHER"] if supply_id == "OLD-S" else ["KEEP"]
            ),
        },
    ), patch(
        "review_processor.ozon_fbs_supplies._sync_supply_composition_from_assembly",
        side_effect=lambda *_a, supply_id, **_k: sync_calls.append(supply_id) or [],
    ):
        result = move_posting_to_local_supply(
            repo,
            user_id=1,
            source_id=2,
            posting_number="PN-1",
            supply_id="NEW-S",
            target_tab=oz.TAB_AWAITING_DELIVER,
        )

    assert result["ok"] is True
    assert result["unchanged"] is False
    assert result["supply_id"] == "NEW-S"
    assert result["tab"] == oz.TAB_AWAITING_DELIVER
    assert result["from_supply_id"] == "OLD-S"
    assert sync_calls == ["NEW-S", "OLD-S"]
    assert updates
    assert "container_id = NULL" in updates[0]
    assert "container_barcode = ''" in updates[0]


def test_get_supply_detail_for_print_with_tab_uses_assembly_not_json_gate() -> None:
    """Moved orders must print via posting_tab assembly path (no JSON mismatch gate)."""
    with patch(
        "review_processor.ozon_fbs_supplies.detach_cancelled_postings_from_supply"
    ), patch(
        "review_processor.ozon_fbs_supplies.get_supply_detail",
        return_value={
            "supply_id": "NEW-S",
            "orders": [{"posting_number": "PN-MOVED"}, {"posting_number": "PN-KEEP"}],
            "order_count": 2,
        },
    ) as detail_mock, patch(
        "review_processor.ozon_fbs_supplies.ensure_supply_ready_for_print"
    ) as gate_mock:
        out = get_supply_detail_for_print(
            MagicMock(),
            user_id=1,
            source_id=2,
            supply_id="NEW-S",
            kind="picking_list",
            posting_tab=oz.TAB_AWAITING_DELIVER,
        )

    assert [o["posting_number"] for o in out["orders"]] == ["PN-MOVED", "PN-KEEP"]
    gate_mock.assert_not_called()
    assert detail_mock.call_args.kwargs["posting_tab"] == oz.TAB_AWAITING_DELIVER


def test_move_posting_to_local_supply_unchanged_when_same() -> None:
    repo = MagicMock()

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=()):
            cur = MagicMock()
            cur.fetchone.return_value = {
                "posting_number": "PN-1",
                "supply_id": "S-1",
                "tab": oz.TAB_DELIVERING,
                "status": oz.TAB_DELIVERING,
            }
            return cur

    repo._connect.return_value = _Conn()
    repo._sql.side_effect = lambda q: q
    repo._row_to_dict.side_effect = lambda r: dict(r)

    with patch(
        "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
    ), patch(
        "review_processor.ozon_fbs_supplies.oz.ensure_ozon_fbs_tables"
    ), patch(
        "review_processor.ozon_fbs_supplies.get_supply",
        return_value={
            "supply_id": "S-1",
            "name": "Same",
            "posting_numbers": ["PN-1"],
        },
    ), patch(
        "review_processor.ozon_fbs_supplies._sync_supply_composition_from_assembly"
    ) as sync_comp:
        result = move_posting_to_local_supply(
            repo,
            user_id=1,
            source_id=2,
            posting_number="PN-1",
            supply_id="S-1",
            target_tab=oz.TAB_DELIVERING,
        )

    assert result["ok"] is True
    assert result["unchanged"] is True
    sync_comp.assert_not_called()


def test_move_postings_to_local_supply_bulk_syncs_composition() -> None:
    repo = MagicMock()
    sync_calls: list[str] = []
    updates: list[str] = []

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=()):
            sql_s = str(sql)
            cur = MagicMock()
            if "SELECT posting_number, supply_id, tab, status" in sql_s:
                cur.fetchall.return_value = [
                    {
                        "posting_number": "PN-1",
                        "supply_id": "OLD-S",
                        "tab": oz.TAB_AWAITING_DELIVER,
                        "status": oz.TAB_AWAITING_DELIVER,
                        "warehouse_id": 10,
                        "warehouse_name": "WH",
                    },
                    {
                        "posting_number": "PN-2",
                        "supply_id": "OLD-S",
                        "tab": oz.TAB_AWAITING_DELIVER,
                        "status": oz.TAB_AWAITING_DELIVER,
                        "warehouse_id": 10,
                        "warehouse_name": "WH",
                    },
                ]
            elif "UPDATE ozon_fbs_postings" in sql_s:
                updates.append(sql_s)
                cur.fetchall.return_value = []
                cur.fetchone.return_value = None
            else:
                cur.fetchall.return_value = []
                cur.fetchone.return_value = None
            return cur

    repo._connect.return_value = _Conn()
    repo._sql.side_effect = lambda q: q
    repo._row_to_dict.side_effect = lambda r: dict(r)

    with patch(
        "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
    ), patch(
        "review_processor.ozon_fbs_supplies.oz.ensure_ozon_fbs_tables"
    ), patch(
        "review_processor.ozon_fbs_supplies.get_supply",
        side_effect=lambda *_a, supply_id, **_k: {
            "supply_id": supply_id,
            "name": f"Name {supply_id}",
            "posting_numbers": (
                ["PN-1", "PN-2", "KEEP-OLD"]
                if supply_id == "OLD-S"
                else ["KEEP-NEW"]
            ),
        },
    ), patch(
        "review_processor.ozon_fbs_supplies._sync_supply_composition_from_assembly",
        side_effect=lambda *_a, supply_id, **_k: sync_calls.append(supply_id) or [],
    ):
        result = move_postings_to_local_supply(
            repo,
            user_id=1,
            source_id=2,
            posting_numbers=["PN-1", "PN-2", "PN-1"],
            supply_id="NEW-S",
            target_tab=oz.TAB_AWAITING_DELIVER,
        )

    assert result["ok"] is True
    assert result["moved"] == 2
    assert result["unchanged"] == 0
    assert result["missing"] == []
    assert set(result["posting_numbers"]) == {"PN-1", "PN-2"}
    assert result["from_supply_ids"] == ["OLD-S"]
    assert len(updates) == 1
    assert "container_id = NULL" in updates[0]
    assert sync_calls == ["NEW-S", "OLD-S"]


def test_create_local_supply_from_postings_creates_then_moves() -> None:
    repo = MagicMock()

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=()):
            cur = MagicMock()
            cur.fetchall.return_value = [
                {
                    "posting_number": "PN-1",
                    "warehouse_id": 7,
                    "warehouse_name": "Склад А",
                }
            ]
            cur.fetchone.return_value = None
            return cur

    repo._connect.return_value = _Conn()
    repo._sql.side_effect = lambda q: q
    repo._row_to_dict.side_effect = lambda r: dict(r)

    with patch(
        "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
    ), patch(
        "review_processor.ozon_fbs_supplies.oz.ensure_ozon_fbs_tables"
    ), patch(
        "review_processor.ozon_fbs_supplies._build_supply_items_for_tab",
        return_value=[{"name": "Поставка X от 01.01.2026"}],
    ), patch(
        "review_processor.ozon_fbs_supplies._source_display_name",
        return_value="X",
    ), patch(
        "review_processor.ozon_fbs_supplies._create_local_supply",
        return_value="NEW-SID",
    ) as create_mock, patch(
        "review_processor.ozon_fbs_supplies.move_postings_to_local_supply",
        return_value={
            "ok": True,
            "moved": 1,
            "unchanged": 0,
            "posting_numbers": ["PN-1"],
            "from_supply_ids": ["OLD"],
        },
    ) as move_mock:
        result = create_local_supply_from_postings(
            repo,
            user_id=1,
            source_id=2,
            posting_numbers=["PN-1"],
            name="Поставка X от 01.01.2026",
            target_tab=oz.TAB_AWAITING_DELIVER,
        )

    assert result["ok"] is True
    assert result["supply_id"] == "NEW-SID"
    assert result["name"].startswith("Поставка X от 01.01.2026")
    assert result["name"] != "Поставка X от 01.01.2026"  # uniquified
    create_mock.assert_called_once()
    assert create_mock.call_args.kwargs["posting_numbers"] == []
    move_mock.assert_called_once()
    assert move_mock.call_args.kwargs["supply_id"] == "NEW-SID"
    assert move_mock.call_args.kwargs["posting_numbers"] == ["PN-1"]
