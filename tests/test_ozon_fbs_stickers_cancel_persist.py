"""Sticker print must persist Ozon-cancelled postings (parity with search)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz
from review_processor.ozon_fbs_supplies import (
    _persist_sticker_cancelled_from_remote,
    _retry_and_diagnose_missing_labels,
    build_stickers_print,
)


def test_persist_sticker_cancelled_from_remote_updates_status() -> None:
    repo = MagicMock()
    remote = {"status": "cancelled", "cancellation": {"cancel_reason_id": 352}}
    with patch.object(oz, "refresh_posting_status_only", return_value={
        "posting_number": "PN-1",
        "status": "cancelled",
        "tab": "cancelled",
    }) as refresh:
        out = _persist_sticker_cancelled_from_remote(
            repo,
            user_id=1,
            source_id=7,
            posting_number="PN-1",
            remote=remote,
        )
    refresh.assert_called_once()
    assert out is not None
    assert out["posting_number"] == "PN-1"
    assert out["cancelled"] is True
    assert out["cancel_reason_label"]


def test_persist_sticker_cancelled_skips_non_cancelled() -> None:
    repo = MagicMock()
    with patch.object(oz, "refresh_posting_status_only") as refresh:
        out = _persist_sticker_cancelled_from_remote(
            repo,
            user_id=1,
            source_id=7,
            posting_number="PN-2",
            remote={"status": "delivering"},
        )
    refresh.assert_not_called()
    assert out is None


def test_retry_and_diagnose_persists_cancelled() -> None:
    repo = MagicMock()
    client = MagicMock()
    client.get_posting.return_value = {
        "status": "cancelled",
        "cancellation": {"cancel_reason_id": 352},
    }
    with patch(
        "review_processor.ozon_fbs_supplies._fetch_label_pages_for_posting",
        return_value=[],
    ), patch(
        "review_processor.ozon_fbs_supplies._persist_sticker_cancelled_from_remote",
        return_value={
            "posting_number": "PN-3",
            "status": "cancelled",
            "tab": "cancelled",
            "cancel_reason_label": "Отменено",
            "cancelled": True,
        },
    ) as persist:
        images, missing, reasons, cancelled = _retry_and_diagnose_missing_labels(
            client,
            repo=repo,
            user_id=1,
            source_id=7,
            images={},
            missing=["PN-3"],
        )
    persist.assert_called_once()
    assert missing == ["PN-3"]
    assert len(reasons) == 1
    assert "отменено" in reasons[0].casefold()
    assert len(cancelled) == 1
    assert cancelled[0]["posting_number"] == "PN-3"


def test_build_stickers_print_returns_cancelled_postings() -> None:
    repo = MagicMock()
    detail = {
        "supply_id": "OZ-1",
        "name": "Test",
        "orders": [
            {
                "posting_number": "PN-4",
                "offer_id": "SKU1",
                "tab": "awaiting_deliver",
            }
        ],
        "order_count": 1,
    }
    cancelled_row = {
        "posting_number": "PN-4",
        "status": "cancelled",
        "tab": "cancelled",
        "cancel_reason_label": "Отменено",
        "cancelled": True,
    }
    with (
        patch(
            "review_processor.ozon_fbs_supplies.get_supply_detail_for_print",
            return_value=detail,
        ),
        patch(
            "review_processor.ozon_fbs_supplies._fetch_label_images",
            return_value={"PN-4": []},
        ),
        patch(
            "review_processor.ozon_fbs_supplies._retry_and_diagnose_missing_labels",
            return_value=({}, ["PN-4"], ["PN-4: отменено"], [cancelled_row]),
        ),
        patch(
            "review_processor.ozon_fbs_supplies.render_stickers_print_html",
            return_value="<html/>",
        ),
    ):
        result = build_stickers_print(
            repo,
            user_id=1,
            source_id=7,
            supply_id="OZ-1",
            client_id="cid",
            api_key="key",
        )
    assert result.cancelled_postings == [cancelled_row]
    assert result.loaded_count == 0
    assert result.missing_posting_numbers == ["PN-4"]


def test_ozon_js_applies_cancelled_after_sticker_print() -> None:
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "web_static" / "ozon_fbs.js").read_text(
        encoding="utf-8"
    )
    html = (Path(__file__).resolve().parents[1] / "web_templates" / "app.html").read_text(
        encoding="utf-8"
    )
    assert "function _ozonFbsApplyStickerCancelledRows" in js
    assert "st.cancelled_postings" in js
    assert "void _ozonFbsRefreshOpenSupplyDetail()" in js
    assert "ozon_fbs.js?v=141" in html
