"""Local Ozon FBS move posting into awaiting_deliver / delivering supply."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz
from review_processor.ozon_fbs_supplies import (
    list_supplies_for_local_move,
    move_posting_to_local_supply,
)


def test_list_supplies_for_local_move_groups_tabs() -> None:
    repo = MagicMock()
    awaiting = [
        {
            "supply_id": "S-A",
            "name": "Awaiting one",
            "order_count": 3,
            "warehouse_label": "WH-A",
        }
    ]
    delivering = [
        {
            "supply_id": "S-D",
            "name": "Delivering one",
            "order_count": 1,
            "warehouse_name": "WH-D",
        },
        {"supply_id": "", "name": "skip"},
    ]
    with patch(
        "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema"
    ), patch(
        "review_processor.ozon_fbs_supplies._build_supply_items_for_tab",
        side_effect=lambda *_a, tab, **_k: (
            awaiting if tab == oz.TAB_AWAITING_DELIVER else delivering
        ),
    ):
        out = list_supplies_for_local_move(repo, user_id=1, source_id=2)

    assert out["ok"] is True
    assert out["total"] == 2
    assert len(out["awaiting_deliver"]) == 1
    assert out["awaiting_deliver"][0]["supply_id"] == "S-A"
    assert out["awaiting_deliver"][0]["tab"] == oz.TAB_AWAITING_DELIVER
    assert out["awaiting_deliver"][0]["warehouse_name"] == "WH-A"
    assert len(out["delivering"]) == 1
    assert out["delivering"][0]["supply_id"] == "S-D"
    assert out["delivering"][0]["tab"] == oz.TAB_DELIVERING
    assert out["delivering"][0]["warehouse_name"] == "WH-D"
    assert [x["supply_id"] for x in out["items"]] == ["S-A", "S-D"]


def test_move_posting_to_local_supply_updates_membership() -> None:
    repo = MagicMock()
    set_calls: list[dict] = []

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
        "review_processor.ozon_fbs_supplies._set_supply_posting_numbers",
        side_effect=lambda *_a, **kwargs: set_calls.append(dict(kwargs)),
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
    assert len(set_calls) == 2
    old_call = next(c for c in set_calls if c["supply_id"] == "OLD-S")
    new_call = next(c for c in set_calls if c["supply_id"] == "NEW-S")
    assert old_call["posting_numbers"] == ["OTHER"]
    assert new_call["posting_numbers"] == ["KEEP", "PN-1"]


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
        "review_processor.ozon_fbs_supplies._set_supply_posting_numbers"
    ) as set_nums:
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
    set_nums.assert_not_called()
