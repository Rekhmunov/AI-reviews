"""Tests for Ozon FBS chunked/background ship-all collect."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from review_processor.ozon_fbs_detail import (
    _ship_error_already_assembled,
    ship_posting,
)
from review_processor.ozon_fbs_supplies import (
    execute_ship_all_collect,
    get_ship_all_collect_state,
    start_ship_all_collect_thread,
)


def test_ship_error_already_assembled_detects_ozon_messages() -> None:
    assert _ship_error_already_assembled(RuntimeError("POSTING_ALREADY_SHIPPED"))
    assert _ship_error_already_assembled(RuntimeError("нельзя собрать: awaiting_deliver"))
    assert not _ship_error_already_assembled(RuntimeError("need exemplars"))


def test_ship_posting_fast_uses_local_and_skips_second_get() -> None:
    repo = MagicMock()
    client = MagicMock()
    client.ship_posting.return_value = {"result": ["P-1"]}
    row = {
        "posting_number": "P-1",
        "tab": "awaiting_packaging",
        "products_json": '[{"sku": 111, "quantity": 1}]',
    }
    with (
        patch("review_processor.ozon_fbs_detail.get_posting_row", return_value=row),
        patch("review_processor.ozon_fbs_detail._force_local_awaiting_deliver") as force,
    ):
        out = ship_posting(
            repo,
            user_id=1,
            source_id=2,
            posting_number="P-1",
            client_id="c",
            api_key="k",
            client=client,
            fast=True,
        )
    assert out["ok"] is True
    client.get_posting.assert_not_called()
    client.ship_posting.assert_called_once()
    force.assert_called_once()


def test_ship_posting_fast_treats_already_shipped_as_ok() -> None:
    repo = MagicMock()
    client = MagicMock()
    client.ship_posting.side_effect = RuntimeError("invalid_state awaiting_deliver")
    row = {
        "posting_number": "P-1",
        "tab": "awaiting_packaging",
        "products_json": '[{"sku": 111, "quantity": 1}]',
    }
    with (
        patch("review_processor.ozon_fbs_detail.get_posting_row", return_value=row),
        patch("review_processor.ozon_fbs_detail._force_local_awaiting_deliver") as force,
    ):
        out = ship_posting(
            repo,
            user_id=1,
            source_id=2,
            posting_number="P-1",
            client_id="c",
            api_key="k",
            client=client,
            fast=True,
        )
    assert out["ok"] is True
    force.assert_called_once()


def test_execute_ship_all_collect_progress_and_fast_ship() -> None:
    repo = MagicMock()
    progress_calls: list[tuple] = []

    def _progress(done, total, message):
        progress_calls.append((done, total, message))

    preview = {
        "groups": [
            {
                "group_key": "wh1",
                "mode": "create",
                "suggested_name": "Склад 1",
                "warehouse_id": 1,
                "warehouse_name": "WH",
                "posting_numbers": ["A-1", "A-2"],
            }
        ],
        "posting_count": 2,
    }
    with (
        patch(
            "review_processor.ozon_fbs_supplies.preview_ship_all_collect",
            return_value=preview,
        ),
        patch(
            "review_processor.ozon_fbs_supplies.list_open_supplies",
            return_value=[],
        ),
        patch(
            "review_processor.ozon_fbs_supplies._source_display_name",
            return_value="OZ",
        ),
        patch(
            "review_processor.ozon_fbs_supplies._create_local_supply",
            return_value="OZ-FBS-1",
        ),
        patch("review_processor.ozon_fbs_supplies.oz.OzonFbsClient"),
        patch("review_processor.ozon_fbs_supplies.oz_detail.ship_posting") as ship,
    ):
        ship.return_value = {"ok": True}
        out = execute_ship_all_collect(
            repo,
            user_id=1,
            source_id=2,
            client_id="c",
            api_key="k",
            decisions=[{"group_key": "wh1", "action": "create", "name": "Склад 1"}],
            progress=_progress,
            ship_pause_sec=0,
        )
    assert out["shipped"] == 2
    assert out["failed"] == 0
    assert ship.call_count == 2
    assert ship.call_args.kwargs.get("fast") is True
    assert progress_calls
    assert progress_calls[-1][0] == 2


def test_execute_ship_all_collect_attaches_split_siblings() -> None:
    repo = MagicMock()
    preview = {
        "groups": [
            {
                "group_key": "wh1",
                "mode": "create",
                "suggested_name": "Склад 1",
                "warehouse_id": 1,
                "warehouse_name": "WH",
                "posting_numbers": ["A-1"],
            }
        ],
        "posting_count": 1,
    }
    with (
        patch(
            "review_processor.ozon_fbs_supplies.preview_ship_all_collect",
            return_value=preview,
        ),
        patch(
            "review_processor.ozon_fbs_supplies.list_open_supplies",
            return_value=[],
        ),
        patch(
            "review_processor.ozon_fbs_supplies._source_display_name",
            return_value="OZ",
        ),
        patch(
            "review_processor.ozon_fbs_supplies._create_local_supply",
            return_value="OZ-FBS-1",
        ) as create_supply,
        patch("review_processor.ozon_fbs_supplies.oz.OzonFbsClient"),
        patch("review_processor.ozon_fbs_supplies.oz_detail.ship_posting") as ship,
    ):
        ship.return_value = {
            "ok": True,
            "posting_numbers": ["A-1", "A-1-1", "A-1-2"],
        }
        out = execute_ship_all_collect(
            repo,
            user_id=1,
            source_id=2,
            client_id="c",
            api_key="k",
            decisions=[{"group_key": "wh1", "action": "create", "name": "Склад 1"}],
            ship_pause_sec=0,
        )
    assert out["shipped"] == 1
    assert out["extra_postings"] == 2
    assert out["shipped_numbers"] == ["A-1", "A-1-1", "A-1-2"]
    assert create_supply.call_args.kwargs["posting_numbers"] == [
        "A-1",
        "A-1-1",
        "A-1-2",
    ]


def test_start_ship_all_rejects_second_run() -> None:
    import review_processor.ozon_fbs_supplies as mod

    with mod._collect_lock:
        mod._collect_state["in_progress"] = True
    try:
        ok, msg = start_ship_all_collect_thread(
            repo=MagicMock(),
            user_id=1,
            source_id=2,
            client_id="c",
            api_key="k",
            decisions=[],
        )
        assert ok is False
        assert "уже" in msg.lower()
    finally:
        with mod._collect_lock:
            mod._collect_state["in_progress"] = False


def test_get_ship_all_collect_state_copies_lists() -> None:
    import review_processor.ozon_fbs_supplies as mod

    with mod._collect_lock:
        mod._collect_state["errors"] = [{"posting_number": "X", "error": "e"}]
        mod._collect_state["message"] = "hi"
    st = get_ship_all_collect_state()
    assert st["message"] == "hi"
    assert st["errors"][0]["posting_number"] == "X"
    st["errors"].append({"posting_number": "Y", "error": "z"})
    st2 = get_ship_all_collect_state()
    assert len(st2["errors"]) == 1
