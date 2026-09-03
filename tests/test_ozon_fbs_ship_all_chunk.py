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


def test_ship_posting_fast_multi_split_skips_get_for_siblings() -> None:
    """Collect ships one package (no split); fast path skips post-ship get."""
    repo = MagicMock()
    client = MagicMock()
    client.ship_posting.return_value = {"result": ["P-1"]}
    row = {
        "posting_number": "P-1",
        "tab": "awaiting_packaging",
        "warehouse_id": 7,
        "warehouse_name": "WH",
        "order_number": "ORD-1",
        "products_json": '[{"sku": 10, "offer_id": "A1", "quantity": 2}]',
        "analytics_data": {"warehouse": "WH", "warehouse_id": 7},
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
    assert out["posting_numbers"] == ["P-1"]
    client.get_posting.assert_not_called()
    force.assert_called_once()
    pkgs = client.ship_posting.call_args.args[1]
    assert len(pkgs) == 1
    assert pkgs[0]["products"][0]["quantity"] == 2


def test_split_posting_persists_siblings_awaiting_packaging() -> None:
    from review_processor.ozon_fbs_detail import split_posting

    repo = MagicMock()
    client = MagicMock()
    client.get_posting.side_effect = [
        {
            "posting_number": "P-1",
            "status": "awaiting_packaging",
            "products": [{"sku": 10, "offer_id": "A", "quantity": 2}],
        },
        {
            "posting_number": "P-1",
            "status": "awaiting_packaging",
            "barcodes": {"upper_barcode": "UP-PARENT", "lower_barcode": "LO-PARENT"},
            "products": [{"sku": 10, "offer_id": "A", "quantity": 1}],
        },
        {
            "posting_number": "P-1-1",
            "status": "awaiting_packaging",
            "barcodes": {"upper_barcode": "UP-CHILD", "lower_barcode": "LO-CHILD"},
            "products": [{"sku": 10, "offer_id": "A", "quantity": 1}],
        },
    ]
    client.split_posting.return_value = {
        "parent_posting": {
            "posting_number": "P-1",
            "products": [{"product_id": 10, "quantity": 1}],
        },
        "postings": [
            {
                "posting_number": "P-1-1",
                "products": [{"product_id": 10, "quantity": 1}],
            }
        ],
    }
    row = {
        "posting_number": "P-1",
        "tab": "awaiting_packaging",
        "products_json": '[{"sku": 10, "offer_id": "A", "quantity": 2}]',
    }
    with (
        patch("review_processor.ozon_fbs_detail.get_posting_row", return_value=row),
        patch("review_processor.ozon_fbs_detail.oz.upsert_posting") as upsert,
        patch("review_processor.ozon_fbs_detail._clear_package_sticker_barcodes") as clear_stickers,
        patch(
            "review_processor.ozon_fbs_detail.oz.persist_posting_stickers_batch",
            return_value=1,
        ) as persist_stickers,
    ):
        out = split_posting(
            repo,
            user_id=1,
            source_id=2,
            posting_number="P-1",
            client_id="c",
            api_key="k",
            client=client,
        )
    assert out["ok"] is True
    assert out["posting_numbers"] == ["P-1", "P-1-1"]
    assert upsert.call_count == 2
    parent_payload = upsert.call_args_list[0].kwargs["posting"]
    sibling_payload = upsert.call_args_list[1].kwargs["posting"]
    assert parent_payload["status"] == "awaiting_packaging"
    assert sibling_payload["status"] == "awaiting_packaging"
    assert parent_payload["products"] == [
        {
            "sku": 10,
            "product_id": 10,
            "quantity": 1,
            "offer_id": "A",
            "name": "",
        }
    ]
    assert sibling_payload["products"][0]["quantity"] == 1
    # Pre-split get + one get per resulting posting for package barcodes.
    assert client.get_posting.call_count == 3
    clear_stickers.assert_called_once()
    assert clear_stickers.call_args.kwargs["posting_numbers"] == ["P-1", "P-1-1"]
    assert persist_stickers.call_count == 2
    first_stickers = persist_stickers.call_args_list[0].kwargs["stickers"]
    second_stickers = persist_stickers.call_args_list[1].kwargs["stickers"]
    assert first_stickers["P-1"]["sticker_barcode"] == "UP-PARENT"
    assert second_stickers["P-1-1"]["sticker_barcode"] == "UP-CHILD"
    assert persist_stickers.call_args_list[0].kwargs["only_if_empty"] is False


def test_refresh_postings_package_stickers_skips_empty_barcodes() -> None:
    from review_processor.ozon_fbs_detail import _refresh_postings_package_stickers_from_ozon

    repo = MagicMock()
    client = MagicMock()
    client.get_posting.return_value = {
        "posting_number": "P-1",
        "status": "awaiting_packaging",
        "products": [{"sku": 1, "quantity": 1}],
    }
    with patch(
        "review_processor.ozon_fbs_detail.oz.persist_posting_stickers_batch"
    ) as persist:
        n = _refresh_postings_package_stickers_from_ozon(
            repo,
            user_id=1,
            source_id=2,
            posting_numbers=["P-1", "P-1", ""],
            client=client,
            overwrite=True,
        )
    assert n == 0
    persist.assert_not_called()
    assert client.get_posting.call_count == 1


def test_enrich_empty_package_stickers_skips_already_bound() -> None:
    from review_processor.ozon_fbs_supplies import _enrich_empty_package_stickers_for_print

    repo = MagicMock()
    client = MagicMock()
    with (
        patch(
            "review_processor.ozon_fbs_supplies.oz.load_posting_sticker_map",
            return_value={
                "P-1": {"sticker_barcode": "UP", "sticker_lower_barcode": ""},
                "P-2": {"sticker_barcode": "", "sticker_lower_barcode": ""},
            },
        ),
        patch(
            "review_processor.ozon_fbs_supplies.oz_detail._refresh_postings_package_stickers_from_ozon",
            return_value=1,
        ) as refresh,
    ):
        n = _enrich_empty_package_stickers_for_print(
            repo,
            user_id=1,
            source_id=2,
            client=client,
            posting_numbers=["P-1", "P-2"],
        )
    assert n == 1
    refresh.assert_called_once()
    assert refresh.call_args.kwargs["posting_numbers"] == ["P-2"]
    assert refresh.call_args.kwargs["overwrite"] is False


def test_parse_split_empty_children_raises() -> None:
    from review_processor.ozon_fbs_detail import _parse_split_response

    plan = [
        {"products": [{"product_id": 1, "quantity": 1}]},
        {"products": [{"product_id": 1, "quantity": 1}]},
    ]
    try:
        _parse_split_response(
            {"parent_posting": {"posting_number": "P-1"}, "postings": []},
            fallback_posting_number="P-1",
            split_plan=plan,
        )
        assert False, "expected error"
    except RuntimeError as exc:
        assert "не вернул номера" in str(exc).lower()


def test_parse_split_unwraps_result_wrapper() -> None:
    from review_processor.ozon_fbs_detail import _parse_split_response

    plan = [
        {"products": [{"product_id": 1, "quantity": 1}]},
        {"products": [{"product_id": 2, "quantity": 1}]},
    ]
    parts = _parse_split_response(
        {
            "result": {
                "parent_posting": {
                    "posting_number": "P-1",
                    "products": [{"product_id": 1, "quantity": 1}],
                },
                "postings": [
                    {
                        "posting_number": "P-1-1",
                        "products": [{"product_id": 2, "quantity": 1}],
                    }
                ],
            }
        },
        fallback_posting_number="P-1",
        split_plan=plan,
    )
    assert [pn for pn, _ in parts] == ["P-1", "P-1-1"]


def test_parse_split_skips_parent_listed_in_postings() -> None:
    """If Ozon lists parent inside postings[], do not shift plan packages."""
    from review_processor.ozon_fbs_detail import _parse_split_response

    plan = [
        {"products": [{"product_id": 10, "quantity": 1}]},
        {"products": [{"product_id": 10, "quantity": 1}]},
    ]
    parts = _parse_split_response(
        {
            "parent_posting": {"posting_number": "P-1"},
            "postings": [
                {"posting_number": "P-1"},
                {"posting_number": "P-1-1"},
            ],
        },
        fallback_posting_number="P-1",
        split_plan=plan,
    )
    assert [pn for pn, _ in parts] == ["P-1", "P-1-1"]
    assert parts[0][1] == plan[0]
    assert parts[1][1] == plan[1]


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
