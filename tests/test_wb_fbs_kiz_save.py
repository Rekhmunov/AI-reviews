"""Unit tests for КИЗ save scoping and clear semantics."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from review_processor.wb_fbs_detail import save_kiz_marking


def _client_mock() -> MagicMock:
    client = MagicMock()
    client.set_order_sgtin = MagicMock()
    client.delete_order_meta = MagicMock()
    return client


@patch("review_processor.wb_fbs_detail.time.sleep", return_value=None)
@patch("review_processor.wb_fbs_detail.wb.WbFbsClient")
def test_save_skips_empty_unbound(mock_cls: Any, _sleep: Any) -> None:
    client = _client_mock()
    mock_cls.return_value = client
    result = save_kiz_marking(
        api_key="k",
        items=[
            {"order_id": 1, "kiz_codes": []},
            {"order_id": 2, "kiz_codes": ["", "  "]},
        ],
        allowed_order_ids={1, 2},
    )
    assert result["saved"] == 0
    assert result["skipped"] == 2
    assert result["failed"] == 0
    client.set_order_sgtin.assert_not_called()
    client.delete_order_meta.assert_not_called()


@patch("review_processor.wb_fbs_detail.time.sleep", return_value=None)
@patch("review_processor.wb_fbs_detail.wb.WbFbsClient")
def test_save_clear_deletes_only_when_flagged(mock_cls: Any, _sleep: Any) -> None:
    client = _client_mock()
    mock_cls.return_value = client
    result = save_kiz_marking(
        api_key="k",
        items=[
            {"order_id": 1, "kiz_codes": [], "clear": True},
            {"order_id": 2, "kiz_codes": []},
        ],
        allowed_order_ids={1, 2},
    )
    assert result["saved"] == 1
    assert result["skipped"] == 1
    client.delete_order_meta.assert_called_once_with(1, "sgtin")
    client.set_order_sgtin.assert_not_called()


@patch("review_processor.wb_fbs_detail.time.sleep", return_value=None)
@patch("review_processor.wb_fbs_detail.wb.WbFbsClient")
def test_save_rejects_orders_outside_supply(mock_cls: Any, _sleep: Any) -> None:
    client = _client_mock()
    mock_cls.return_value = client
    result = save_kiz_marking(
        api_key="k",
        items=[
            {"order_id": 99, "kiz_codes": ["010460..."]},
            {"order_id": 1, "kiz_codes": ["010461..."]},
        ],
        allowed_order_ids={1},
    )
    assert result["saved"] == 1
    assert result["failed"] == 1
    assert result["ok"] is False
    client.set_order_sgtin.assert_called_once_with(1, ["010461..."])
    err = next(r for r in result["results"] if r["order_id"] == 99)
    assert "поставку" in err["error"].lower() or "поставк" in err["error"].lower()


@patch("review_processor.wb_fbs_detail.time.sleep", return_value=None)
@patch("review_processor.wb_fbs_detail.wb.WbFbsClient")
def test_save_sets_sgtin(mock_cls: Any, _sleep: Any) -> None:
    client = _client_mock()
    mock_cls.return_value = client
    result = save_kiz_marking(
        api_key="k",
        items=[{"order_id": 5, "kiz_codes": ["AAA", "AAA", "BBB"]}],
        allowed_order_ids={5},
    )
    assert result["ok"] is True
    assert result["saved"] == 1
    client.set_order_sgtin.assert_called_once_with(5, ["AAA", "BBB"])
