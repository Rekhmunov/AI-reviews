"""Tests for Ozon FBS local-only marking save."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from review_processor.ozon_fbs_marking import save_marking


def test_save_marking_local_only_no_ozon_client() -> None:
    with patch(
        "review_processor.ozon_fbs_marking.update_posting_marking_codes",
        return_value={
            "ok": True,
            "conflict": False,
            "codes": ["010460123456789021ABC"],
            "saved_at": "2026-01-01T00:00:00+00:00",
        },
    ) as upd:
        out = save_marking(
            MagicMock(),
            user_id=1,
            source_id=2,
            items=[
                {
                    "posting_number": "P-1",
                    "kiz_codes": ["010460123456789021ABC"],
                }
            ],
            allowed_posting_numbers={"P-1"},
        )
    assert out["ok"] is True
    assert out["saved"] == 1
    upd.assert_called_once()
    assert upd.call_args.kwargs.get("ozon_synced") is False
