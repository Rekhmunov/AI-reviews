"""Unit tests for КИЗ save scoping, local-first, and clear semantics."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from review_processor.wb_fbs import _kiz_code_clean
from review_processor.wb_fbs_detail import save_kiz_marking


def test_kiz_code_clean_keeps_group_separator() -> None:
    raw = "01046701724227242150B:\u001d91EE11\u001d92pxuu="
    assert _kiz_code_clean(raw) == raw
    # Default str.strip() would wipe a lone GS; our helper must not.
    assert _kiz_code_clean("\u001d") == "\u001d"
    assert _kiz_code_clean("  " + raw + "\n") == raw


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


@patch("review_processor.wb_fbs_detail.time.sleep", return_value=None)
@patch("review_processor.wb_fbs_detail.wb.update_order_kiz_codes")
@patch("review_processor.wb_fbs_detail.wb.WbFbsClient")
def test_save_local_first_then_wb(
    mock_cls: Any, mock_local: Any, _sleep: Any
) -> None:
    client = _client_mock()
    mock_cls.return_value = client
    mock_local.return_value = True
    repo = MagicMock()
    result = save_kiz_marking(
        api_key="k",
        items=[{"order_id": 7, "kiz_codes": ["CODE1"]}],
        allowed_order_ids={7},
        repo=repo,
        user_id=11,
        source_id=22,
    )
    assert result["ok"] is True
    assert result["saved"] == 1
    assert result["saved_local"] == 1
    client.set_order_sgtin.assert_called_once_with(7, ["CODE1"])
    # Local pending, then local synced after WB ok.
    assert mock_local.call_count == 2
    assert mock_local.call_args_list[0].kwargs["wb_synced"] is False
    assert mock_local.call_args_list[1].kwargs["wb_synced"] is True


@patch("review_processor.wb_fbs_detail.time.sleep", return_value=None)
@patch("review_processor.wb_fbs_detail.wb.update_order_kiz_codes")
@patch("review_processor.wb_fbs_detail.wb.WbFbsClient")
def test_save_keeps_local_when_wb_fails(
    mock_cls: Any, mock_local: Any, _sleep: Any
) -> None:
    client = _client_mock()
    client.set_order_sgtin.side_effect = RuntimeError("WB 409 conflict")
    mock_cls.return_value = client
    mock_local.return_value = True
    repo = MagicMock()
    result = save_kiz_marking(
        api_key="k",
        items=[{"order_id": 8, "kiz_codes": ["CODE2"]}],
        allowed_order_ids={8},
        repo=repo,
        user_id=11,
        source_id=22,
    )
    assert result["ok"] is False
    assert result["saved"] == 0
    assert result["failed"] == 1
    assert result["saved_local"] == 1
    row = result["results"][0]
    assert row["local_ok"] is True
    assert row["wb_ok"] is False
    assert "409" in row["error"]
    assert row["kiz_codes"] == ["CODE2"]
    # Only pending local write — no wb_synced=True update.
    mock_local.assert_called_once()
    assert mock_local.call_args.kwargs["wb_synced"] is False
    assert mock_local.call_args.kwargs["kiz_codes"] == ["CODE2"]
