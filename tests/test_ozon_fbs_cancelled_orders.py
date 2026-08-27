"""Unit tests for cancelled postings in Ozon FBS local supplies."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from review_processor import ozon_fbs as oz
from review_processor.ozon_fbs_supplies import list_supply_cancelled_postings


def test_cancel_reason_label_from_posting() -> None:
    posting = {
        "status": "cancelled",
        "cancellation": {
            "cancel_reason_id": 352,
            "cancellation_type": "client",
        },
    }
    assert oz.cancel_reason_label_from_posting(posting) == "Товара нет в наличии"


def test_cancel_reason_label_from_row_local() -> None:
    row = {
        "status": "cancelled",
        "tab": "cancelled",
        "raw_json": "{}",
    }
    assert oz.cancel_reason_label_from_row(row) == "Отменено"


def test_list_supply_cancelled_postings_finds_cancelled() -> None:
    repo = MagicMock()
    supply = {
        "supply_id": "OZ-1",
        "posting_numbers": ["A-1", "A-2", "A-3"],
    }
    local_orders = [
        {
            "posting_number": "A-1",
            "offer_id": "ART1",
            "product_name": "Товар 1",
            "product_photo": "",
            "sku": 111,
            "barcodes": ["2001"],
            "created_at_ozon": "2026-08-20T10:00:00+00:00",
            "status": "awaiting_deliver",
            "tab": "awaiting_deliver",
        },
        {
            "posting_number": "A-2",
            "offer_id": "ART2",
            "product_name": "Товар 2",
            "product_photo": "",
            "sku": 222,
            "barcodes": ["2002"],
            "created_at_ozon": "2026-08-21T10:00:00+00:00",
            "status": "cancelled",
            "tab": "cancelled",
            "cancel_reason_label": "Отменено",
        },
        {
            "posting_number": "A-3",
            "offer_id": "ART3",
            "product_name": "Товар 3",
            "product_photo": "",
            "sku": 333,
            "barcodes": [],
            "created_at_ozon": "2026-08-22T10:00:00+00:00",
            "status": "awaiting_deliver",
            "tab": "awaiting_deliver",
        },
    ]

    def _get_posting(pn: str) -> dict:
        if pn == "A-2":
            return {
                "posting_number": pn,
                "status": "cancelled",
                "cancellation": {"cancel_reason_id": 665},
            }
        return {"posting_number": pn, "status": "awaiting_deliver"}

    client = MagicMock()
    client.get_posting.side_effect = _get_posting

    with (
        patch(
            "review_processor.ozon_fbs_supplies.get_supply",
            return_value=supply,
        ),
        patch(
            "review_processor.ozon_fbs_supplies.get_supply_detail",
            return_value={"orders": local_orders, "supply_id": "OZ-1"},
        ),
        patch("review_processor.ozon_fbs_supplies.oz.OzonFbsClient", return_value=client),
        patch("review_processor.ozon_fbs_supplies.oz.upsert_posting"),
        patch("review_processor.ozon_fbs_supplies.time.sleep"),
    ):
        payload = list_supply_cancelled_postings(
            repo,
            user_id=1,
            source_id=2,
            supply_id="OZ-1",
            client_id="c",
            api_key="k",
        )

    assert payload["ok"] is True
    assert payload["posting_count"] == 3
    assert payload["cancelled_count"] == 1
    assert payload["rows"][0]["posting_number"] == "A-2"
    assert payload["rows"][0]["cancel_reason_label"] == "Покупатель не забрал заказ"
    assert payload["done"] is True
    assert payload["remaining"] == 0
    assert client.get_posting.call_count == 3


def test_list_supply_cancelled_postings_chunks_by_offset() -> None:
    repo = MagicMock()
    supply = {
        "supply_id": "OZ-1",
        "posting_numbers": ["A-1", "A-2", "A-3"],
    }
    local_orders = [
        {"posting_number": "A-1", "status": "awaiting_deliver", "tab": "awaiting_deliver"},
        {"posting_number": "A-2", "status": "awaiting_deliver", "tab": "awaiting_deliver"},
        {"posting_number": "A-3", "status": "awaiting_deliver", "tab": "awaiting_deliver"},
    ]

    def _get_posting(pn: str) -> dict:
        if pn == "A-2":
            return {
                "posting_number": pn,
                "status": "cancelled",
                "cancellation": {"cancel_reason_id": 665},
            }
        return {"posting_number": pn, "status": "awaiting_deliver"}

    client = MagicMock()
    client.get_posting.side_effect = _get_posting

    with (
        patch(
            "review_processor.ozon_fbs_supplies.get_supply",
            return_value=supply,
        ),
        patch(
            "review_processor.ozon_fbs_supplies.get_supply_detail",
            return_value={"orders": local_orders, "supply_id": "OZ-1"},
        ),
        patch("review_processor.ozon_fbs_supplies.oz.OzonFbsClient", return_value=client),
        patch("review_processor.ozon_fbs_supplies.oz.upsert_posting"),
    ):
        first = list_supply_cancelled_postings(
            repo,
            user_id=1,
            source_id=2,
            supply_id="OZ-1",
            client_id="c",
            api_key="k",
            check_offset=0,
            check_limit=2,
        )
        second = list_supply_cancelled_postings(
            repo,
            user_id=1,
            source_id=2,
            supply_id="OZ-1",
            client_id="c",
            api_key="k",
            check_offset=first["next_offset"],
            check_limit=2,
        )

    assert first["checked"] == 2
    assert first["remaining"] == 1
    assert first["done"] is False
    assert first["cancelled_count"] == 1
    assert first["rows"][0]["posting_number"] == "A-2"
    assert second["checked"] == 1
    assert second["remaining"] == 0
    assert second["done"] is True
    assert second["cancelled_count"] == 0
    assert client.get_posting.call_count == 3


def test_list_supply_cancelled_postings_empty() -> None:
    repo = MagicMock()
    with patch(
        "review_processor.ozon_fbs_supplies.get_supply",
        return_value={"supply_id": "OZ-1", "posting_numbers": []},
    ):
        payload = list_supply_cancelled_postings(
            repo,
            user_id=1,
            source_id=2,
            supply_id="OZ-1",
            client_id="c",
            api_key="k",
        )
    assert payload["cancelled_count"] == 0
    assert payload["rows"] == []


def test_list_supply_cancelled_postings_raises_when_all_fetch_fail() -> None:
    repo = MagicMock()
    supply = {"supply_id": "OZ-1", "posting_numbers": ["A-1"]}
    client = MagicMock()
    client.get_posting.side_effect = RuntimeError("ozon down")

    with (
        patch(
            "review_processor.ozon_fbs_supplies.get_supply",
            return_value=supply,
        ),
        patch(
            "review_processor.ozon_fbs_supplies.get_supply_detail",
            return_value={"orders": []},
        ),
        patch("review_processor.ozon_fbs_supplies.oz.OzonFbsClient", return_value=client),
        patch("review_processor.ozon_fbs_supplies.time.sleep"),
        pytest.raises(RuntimeError, match="Не удалось проверить статусы"),
    ):
        list_supply_cancelled_postings(
            repo,
            user_id=1,
            source_id=2,
            supply_id="OZ-1",
            client_id="c",
            api_key="k",
        )
