"""WB FBS cargo-place (trbx) create validation."""

import pytest

from review_processor.wb_fbs import WbFbsClient, _trbx_box_id
from review_processor.wb_fbs_detail import render_trbx_stickers_html


def test_create_supply_boxes_rejects_bad_amount():
    client = WbFbsClient("dummy-key")
    with pytest.raises(ValueError, match="от 1 до 1000"):
        client.create_supply_boxes("WB-GI-1", 0)
    with pytest.raises(ValueError, match="от 1 до 1000"):
        client.create_supply_boxes("WB-GI-1", 1001)
    with pytest.raises(ValueError, match="ID поставки"):
        client.create_supply_boxes("", 1)


def test_ui_remaining_boxes_formula():
    # Mirror front-end: remaining = min(1000, max(1, orders+1) - existing)
    def remaining(orders: int, existing: int) -> int:
        max_total = max(1, orders + 1)
        return max(0, min(1000, max_total - existing))

    assert remaining(5, 0) == 6
    assert remaining(5, 2) == 4
    assert remaining(5, 6) == 0
    assert remaining(0, 0) == 1


def test_trbx_box_id_normalization():
    assert _trbx_box_id({"id": "WB-TRBX-1"}) == "WB-TRBX-1"
    assert _trbx_box_id({"trbxId": "WB-TRBX-2"}) == "WB-TRBX-2"
    assert _trbx_box_id("WB-TRBX-3") == "WB-TRBX-3"
    assert _trbx_box_id({"id": "  "}) == ""


def test_render_trbx_stickers_html():
    # Minimal valid base64 for PNG-ish payload (alphabet only matters for sanitize).
    b64 = "aGVsbG8="
    html_doc = render_trbx_stickers_html(
        supply_id="WB-GI-1",
        stickers=[{"barcode": "WB-TRBX-9", "file": b64}],
    )
    assert "WB-TRBX-9" in html_doc
    assert "data:image/png;base64,aGVsbG8=" in html_doc
    assert "window.print()" in html_doc
    with pytest.raises(ValueError, match="не вернул"):
        render_trbx_stickers_html(supply_id="WB-GI-1", stickers=[])
