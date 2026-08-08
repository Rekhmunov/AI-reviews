"""Unit tests for КИЗ badge status from WB metaDetails.decision."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from review_processor.wb_fbs_detail import (
    _kiz_from_meta_row,
    _kiz_status_from_decision,
    check_supply_kiz_status,
    summarize_kiz_check_status,
)


def test_status_empty_without_codes() -> None:
    assert _kiz_status_from_decision("required", []) == "empty"
    assert _kiz_status_from_decision("", []) == "empty"


def test_status_pending_with_codes() -> None:
    assert _kiz_status_from_decision("required", ["01…"]) == "pending"
    assert _kiz_status_from_decision("optional", ["01…"]) == "pending"
    assert _kiz_status_from_decision("", ["01…"]) == "pending"


def test_status_ok_and_error() -> None:
    assert _kiz_status_from_decision("filled", ["01…"]) == "ok"
    assert _kiz_status_from_decision("invalid", ["01…"]) == "error"
    assert _kiz_status_from_decision("invalid", []) == "error"
    assert _kiz_status_from_decision("FAILED", ["01…"]) == "error"
    assert _kiz_status_from_decision("sgtinInvalid", ["01…"]) == "error"
    # Live WB values from POST /orders/meta:
    assert _kiz_status_from_decision("sgtinNotFound", ["01…"]) == "error"
    assert _kiz_status_from_decision("sgtinIntroduced", ["01…"]) == "ok"
    assert _kiz_status_from_decision("optional", []) == "empty"


def test_meta_row_decision_filled() -> None:
    parsed = _kiz_from_meta_row(
        {
            "id": 1,
            "metaDetails": [
                {"key": "sgtin", "value": ["010467…"], "decision": "filled"}
            ],
        }
    )
    assert parsed["kiz_required"] is True
    assert parsed["kiz_status"] == "ok"
    assert parsed["kiz_bound"] is True


def test_meta_row_decision_invalid() -> None:
    parsed = _kiz_from_meta_row(
        {
            "id": 2,
            "metaDetails": [
                {"key": "sgtin", "value": ["010467…"], "decision": "invalid"}
            ],
        }
    )
    assert parsed["kiz_status"] == "error"


def test_meta_row_pending_required_with_value() -> None:
    parsed = _kiz_from_meta_row(
        {
            "id": 3,
            "metaDetails": [
                {"key": "sgtin", "value": ["010467…"], "decision": "required"}
            ],
        }
    )
    assert parsed["kiz_status"] == "pending"


def test_summarize_kiz_check_status() -> None:
    assert summarize_kiz_check_status([]) == "none"
    # filled / sgtinIntroduced both map to ok → green split control
    assert summarize_kiz_check_status(["ok", "ok"]) == "ok"
    assert summarize_kiz_check_status(["ok", "error"]) == "error"
    assert summarize_kiz_check_status(["error", "pending"]) == "error"
    # Still checking / empty slots → default (not green, not red)
    assert summarize_kiz_check_status(["ok", "pending"]) == "pending"
    assert summarize_kiz_check_status(["empty", "pending"]) == "pending"
    assert summarize_kiz_check_status(["empty"]) == "pending"


def test_check_supply_kiz_status_live_ok_and_not_required() -> None:
    client = MagicMock()
    client.get_supply_order_ids.return_value = [11, 22]
    client.get_statuses.return_value = [
        {"id": 11, "supplierStatus": "confirm", "wbStatus": "waiting"},
        {"id": 22, "supplierStatus": "confirm", "wbStatus": "waiting"},
    ]
    client.get_orders_meta.return_value = [
        {
            "id": 11,
            "metaDetails": [
                {"key": "sgtin", "value": ["010467…"], "decision": "filled"}
            ],
        },
        {"id": 22, "metaDetails": []},
    ]
    with (
        patch("review_processor.wb_fbs_detail.wb.WbFbsClient", return_value=client),
        patch("review_processor.wb_fbs_detail._cache_get_detail", return_value=None),
        patch(
            "review_processor.wb_fbs_detail._local_order_ids_for_supply",
            return_value=[],
        ),
        patch(
            "review_processor.wb_fbs_detail.wb.load_order_status_map",
            return_value={},
        ),
    ):
        payload = check_supply_kiz_status(
            MagicMock(),
            user_id=1,
            source_id=2,
            api_key="key",
            supply_id="S1",
        )
    assert payload["status"] == "ok"
    assert payload["counts"]["required"] == 1
    assert payload["counts"]["ok"] == 1
    by_id = {row["order_id"]: row for row in payload["orders"]}
    assert by_id[11]["kiz_required"] is True
    assert by_id[11]["kiz_status"] == "ok"
    assert by_id[22]["kiz_required"] is False


def test_check_supply_kiz_status_raises_on_meta_failure() -> None:
    client = MagicMock()
    client.get_supply_order_ids.return_value = [11]
    client.get_statuses.return_value = [
        {"id": 11, "supplierStatus": "confirm", "wbStatus": "waiting"},
    ]
    client.get_orders_meta.side_effect = RuntimeError("wb down")
    with (
        patch("review_processor.wb_fbs_detail.wb.WbFbsClient", return_value=client),
        patch("review_processor.wb_fbs_detail._cache_get_detail", return_value=None),
        patch(
            "review_processor.wb_fbs_detail._local_order_ids_for_supply",
            return_value=[],
        ),
        patch(
            "review_processor.wb_fbs_detail.wb.load_order_status_map",
            return_value={},
        ),
        pytest.raises(RuntimeError, match="Не удалось проверить КИЗ"),
    ):
        check_supply_kiz_status(
            MagicMock(),
            user_id=1,
            source_id=2,
            api_key="key",
            supply_id="S1",
        )


def test_check_supply_kiz_status_excludes_cancelled_from_tone() -> None:
    client = MagicMock()
    client.get_supply_order_ids.return_value = [11, 22]
    client.get_statuses.return_value = [
        {"id": 11, "supplierStatus": "confirm", "wbStatus": "waiting"},
        {"id": 22, "supplierStatus": "confirm", "wbStatus": "canceled_by_client"},
    ]
    # Meta is requested only for active order 11.
    client.get_orders_meta.return_value = [
        {
            "id": 11,
            "metaDetails": [
                {"key": "sgtin", "value": ["010467…"], "decision": "filled"}
            ],
        },
    ]
    with (
        patch("review_processor.wb_fbs_detail.wb.WbFbsClient", return_value=client),
        patch("review_processor.wb_fbs_detail._cache_get_detail", return_value=None),
        patch(
            "review_processor.wb_fbs_detail._local_order_ids_for_supply",
            return_value=[],
        ),
        patch(
            "review_processor.wb_fbs_detail.wb.load_order_status_map",
            return_value={},
        ),
        patch(
            "review_processor.wb_fbs_detail.wb.update_order_wb_statuses",
            return_value=1,
        ) as mock_persist,
    ):
        payload = check_supply_kiz_status(
            MagicMock(),
            user_id=1,
            source_id=2,
            api_key="key",
            supply_id="S1",
        )
    # Cancelled order 22 must not paint the control red / block meta.
    assert payload["status"] == "ok"
    assert payload["counts"]["required"] == 1
    assert payload["counts"]["cancelled"] == 1
    by_id = {row["order_id"]: row for row in payload["orders"]}
    assert by_id[22]["cancelled"] is True
    assert by_id[22]["kiz_required"] is False
    client.get_orders_meta.assert_called_once_with([11])
    mock_persist.assert_called_once()
