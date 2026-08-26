"""Tests for Ozon FBS marking status refresh tone."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from review_processor.ozon_fbs_marking import (
    check_supply_marking_status,
    save_marking,
    update_posting_marking_codes,
)


def test_save_marking_normalizes_arrow_to_gs() -> None:
    arrow = "\u2194"
    gs = "\u001d"
    raw = f"010460123456789021{arrow}93ABC"
    with patch(
        "review_processor.ozon_fbs_marking.update_posting_marking_codes",
        return_value={
            "ok": True,
            "conflict": False,
            "codes": [f"010460123456789021{gs}93ABC"],
            "saved_at": "2026-01-01T00:00:00+00:00",
        },
    ) as upd:
        out = save_marking(
            MagicMock(),
            user_id=1,
            source_id=2,
            items=[{"posting_number": "P-1", "kiz_codes": [raw]}],
            allowed_posting_numbers={"P-1"},
        )
    assert out["ok"] is True
    sent = upd.call_args.kwargs.get("codes") or []
    assert sent == [f"010460123456789021{gs}93ABC"]


def test_update_posting_marking_codes_normalizes_arrow() -> None:
    arrow = "\u2194"
    gs = "\u001d"
    repo = MagicMock()
    conn = MagicMock()
    repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
    repo._connect.return_value.__exit__ = MagicMock(return_value=False)
    repo._sql = lambda s: s
    repo._row_to_dict = lambda row: row
    conn.execute.return_value.fetchone.return_value = {
        "marking_codes_json": "[]",
        "marking_saved_at": "",
    }
    with patch("review_processor.ozon_fbs_marking.oz.ensure_ozon_fbs_tables"):
        res = update_posting_marking_codes(
            repo,
            user_id=1,
            source_id=2,
            posting_number="P-1",
            codes=[f"010460123456789021{arrow}93ABC"],
        )
    assert res["codes"] == [f"010460123456789021{gs}93ABC"]


def test_check_supply_marking_status_ok_when_all_filled() -> None:
    detail = {
        "orders": [
            {
                "posting_number": "A-1",
                "kiz_required": True,
                "kiz_status": "ok",
                "cancelled": False,
            },
            {
                "posting_number": "A-2",
                "kiz_required": True,
                "kiz_status": "ok",
                "cancelled": False,
            },
            {
                "posting_number": "A-3",
                "kiz_required": False,
                "kiz_status": "empty",
                "cancelled": True,
                "cancel_reason_label": "Отменен",
            },
        ],
    }
    with (
        patch(
            "review_processor.ozon_fbs_marking.oz_sup.get_supply_detail",
            return_value=detail,
        ),
        patch(
            "review_processor.ozon_fbs_marking.load_marking_map",
            return_value={
                "A-1": {"codes": ["010460123456789021\u001d93ABC"], "saved_at": "t"},
                "A-2": {"codes": ["010460123456789022\u001d93ABC"], "saved_at": "t"},
            },
        ),
    ):
        out = check_supply_marking_status(
            MagicMock(), user_id=1, source_id=2, supply_id="OZ-1"
        )
    assert out["status"] == "ok"
    assert out["required"] == 2
    assert out["done"] == 2


def test_check_supply_marking_status_default_when_partial() -> None:
    detail = {
        "orders": [
            {
                "posting_number": "A-1",
                "kiz_required": True,
                "kiz_status": "ok",
                "cancelled": False,
            },
            {
                "posting_number": "A-2",
                "kiz_required": True,
                "kiz_status": "empty",
                "cancelled": False,
            },
        ],
    }
    with (
        patch(
            "review_processor.ozon_fbs_marking.oz_sup.get_supply_detail",
            return_value=detail,
        ),
        patch(
            "review_processor.ozon_fbs_marking.load_marking_map",
            return_value={
                "A-1": {"codes": ["010460123456789021\u001d93ABC"], "saved_at": "t"},
            },
        ),
    ):
        out = check_supply_marking_status(
            MagicMock(), user_id=1, source_id=2, supply_id="OZ-1"
        )
    assert out["status"] == ""
    assert out["done"] == 1
    assert out["empty"] == 1
