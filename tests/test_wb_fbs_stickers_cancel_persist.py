"""Sticker print must diagnose/persist WB-cancelled orders (parity with Ozon)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from review_processor.wb_fbs_detail import (
    _diagnose_missing_sticker_cancellations,
    _orders_excluding_cancelled,
    _sticker_file_present,
    _wb_fbs_order_is_cancelled,
    build_article_groups_for_print,
)


def test_wb_fbs_order_is_cancelled_by_label_and_status() -> None:
    assert _wb_fbs_order_is_cancelled({"cancel_reason_label": "Отказ на ПВЗ"})
    assert _wb_fbs_order_is_cancelled({"supplier_status": "cancel", "wb_status": ""})
    assert not _wb_fbs_order_is_cancelled({"supplier_status": "confirm", "wb_status": ""})


def test_orders_excluding_cancelled_filters_rows() -> None:
    rows = [
        {"order_id": 1, "supplier_status": "confirm"},
        {"order_id": 2, "cancel_reason_label": "Отменен"},
        {"order_id": 3, "supplier_status": "cancel"},
    ]
    out = _orders_excluding_cancelled(rows)
    assert [o["order_id"] for o in out] == [1]


def test_sticker_file_present() -> None:
    assert _sticker_file_present({"file": "abc"})
    assert not _sticker_file_present({"file": ""})
    assert not _sticker_file_present(None)


def test_diagnose_missing_sticker_cancellations_persists() -> None:
    repo = MagicMock()
    client = MagicMock()
    client.get_statuses.return_value = [
        {"id": 101, "supplierStatus": "cancel", "wbStatus": "canceled_by_client"},
        {"id": 102, "supplierStatus": "confirm", "wbStatus": ""},
    ]
    with patch("review_processor.wb_fbs_detail.wb.WbFbsClient", return_value=client), patch(
        "review_processor.wb_fbs_detail.wb.update_order_wb_statuses", return_value=1
    ) as upd, patch(
        "review_processor.wb_fbs_detail.invalidate_supply_detail_cache"
    ) as inv:
        out = _diagnose_missing_sticker_cancellations(
            repo,
            user_id=1,
            source_id=7,
            api_key="key",
            supply_id="WB-1",
            missing_order_ids=[101, 102],
        )
    upd.assert_called_once()
    inv.assert_called_once()
    assert len(out) == 1
    assert out[0]["order_id"] == 101
    assert out[0]["cancelled"] is True
    assert out[0]["cancel_reason_label"]


def test_diagnose_skips_non_cancelled_missing() -> None:
    repo = MagicMock()
    client = MagicMock()
    client.get_statuses.return_value = [
        {"id": 201, "supplierStatus": "confirm", "wbStatus": ""},
    ]
    with patch("review_processor.wb_fbs_detail.wb.WbFbsClient", return_value=client), patch(
        "review_processor.wb_fbs_detail.wb.update_order_wb_statuses"
    ) as upd:
        out = _diagnose_missing_sticker_cancellations(
            repo,
            user_id=1,
            source_id=7,
            api_key="key",
            supply_id="WB-1",
            missing_order_ids=[201],
        )
    upd.assert_not_called()
    assert out == []


def test_build_article_groups_for_print_returns_cancelled_orders() -> None:
    repo = MagicMock()
    detail = {
        "supply_id": "WB-1",
        "name": "Test",
        "orders": [
            {"order_id": 10, "nm_id": 1, "article": "A", "product_name": "P"},
            {"order_id": 11, "nm_id": 2, "article": "B", "product_name": "Q"},
        ],
        "order_count": 2,
    }
    cancelled_row = {
        "order_id": 11,
        "cancelled": True,
        "cancel_reason_label": "Отказ на ПВЗ",
        "supplier_status": "cancel",
        "wb_status": "canceled_by_client",
    }
    stickers = {
        10: {"file": "aaa", "partA": "1", "partB": "2"},
        11: {"file": "", "partA": "", "partB": ""},
    }
    with (
        patch(
            "review_processor.wb_fbs_detail.get_supply_detail_for_print",
            return_value=detail,
        ),
        patch(
            "review_processor.wb_fbs_detail._fetch_stickers_map",
            return_value=stickers,
        ),
        patch(
            "review_processor.wb_fbs_detail._diagnose_missing_sticker_cancellations",
            return_value=[cancelled_row],
        ),
        patch(
            "review_processor.wb_fbs_detail.fetch_card_meta_by_nm",
            return_value={},
        ),
        patch(
            "review_processor.wb_fbs_detail._refresh_product_names",
        ),
    ):
        result = build_article_groups_for_print(
            repo,
            user_id=1,
            source_id=7,
            api_key="key",
            supply_id="WB-1",
            mode="stickers",
        )
    assert result["cancelled_orders"] == [cancelled_row]
    order_ids = [o["order_id"] for o in result["detail"]["orders"]]
    assert 11 not in order_ids
    assert 10 in order_ids


def test_wb_js_applies_cancelled_after_sticker_print() -> None:
    root = Path(__file__).resolve().parents[1]
    js = (root / "web_static" / "app.js").read_text(encoding="utf-8")
    html = (root / "web_templates" / "app.html").read_text(encoding="utf-8")
    assert "function _wbFbsApplyStickerCancelledOrders" in js
    assert "format=json" in js
    assert "data.cancelled_orders" in js
    assert "app.js?v=616" in html
