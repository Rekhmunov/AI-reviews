"""Unit tests for КИЗ badge status from WB metaDetails.decision."""

from __future__ import annotations

from review_processor.wb_fbs_detail import _kiz_from_meta_row, _kiz_status_from_decision


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
