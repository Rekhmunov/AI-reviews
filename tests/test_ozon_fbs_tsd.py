"""Unit tests for Ozon FBS ТСД helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from review_processor.ozon_fbs_tsd import (
    build_ozon_tsd_hub_progress,
    list_ozon_tsd_supplies,
    _normalize_tsd_rows,
)


def test_normalize_tsd_rows_adds_sticker_number_and_order_id() -> None:
    rows = _normalize_tsd_rows(
        [{"posting_number": "0101152363-0210-1", "kiz_codes": ["x"]}]
    )
    assert rows[0]["sticker_number"] == "0101152363-0210-1"
    assert rows[0]["order_id"] == "0101152363-0210-1"


def test_list_ozon_tsd_supplies_filters_search() -> None:
    repo = MagicMock()
    payload = {
        "items": [
            {"supply_id": "OZ-1", "name": "Поставка Ozon Shop от 01.01.2026"},
            {"supply_id": "OZ-2", "name": "Другая"},
        ]
    }
    with patch(
        "review_processor.ozon_fbs_tsd.oz_sup.list_awaiting_deliver_supplies",
        return_value=payload,
    ):
        out = list_ozon_tsd_supplies(
            repo, user_id=1, source_id=2, search="ozon shop"
        )
    assert out["total"] == 1
    assert out["items"][0]["supply_id"] == "OZ-1"


def test_build_ozon_tsd_hub_progress_counts() -> None:
    repo = MagicMock()
    kiz_rows = [
        {"posting_number": "A", "kiz_codes": ["c"], "cancelled": False},
        {"posting_number": "B", "kiz_codes": [], "cancelled": False},
    ]
    pick_rows = [
        {"posting_number": "C", "pick_verified": True, "pick_barcode": "460123"},
    ]
    with patch(
        "review_processor.ozon_fbs_tsd.oz_mark.build_marking_payload",
        return_value={"rows": kiz_rows},
    ), patch(
        "review_processor.ozon_fbs_tsd.oz_pick.build_pick_verify_payload",
        return_value={"rows": pick_rows},
    ):
        out = build_ozon_tsd_hub_progress(
            repo,
            user_id=1,
            source_id=2,
            supply_id="OZ-1",
            client_id="c",
            api_key="k",
        )
    assert out["kiz"] == {"total": 2, "done": 1}
    assert out["pick"] == {"total": 1, "done": 1}
    assert out["order_count"] == 3
