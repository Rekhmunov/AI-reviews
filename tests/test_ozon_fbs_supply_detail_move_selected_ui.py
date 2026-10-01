"""UI contract: supply-detail selection bar can move postings locally."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OZON_JS = ROOT / "web_static" / "ozon_fbs.js"
APP_HTML = ROOT / "web_templates" / "app.html"


def test_supply_detail_bottom_bar_markup() -> None:
    html = APP_HTML.read_text(encoding="utf-8")
    assert 'id="ozonFbsSupplyDetailBottomBar"' in html
    assert "openOzonFbsSupplyDetailNewSupply()" in html
    assert "openOzonFbsSupplyDetailMoveExisting()" in html
    assert "clearOzonFbsSupplyDetailSelection()" in html
    assert 'id="ozonFbsSupplyDetailNewSupplyModal"' in html


def test_supply_detail_move_selected_js_hooks() -> None:
    text = OZON_JS.read_text(encoding="utf-8")
    assert "function updateSupplyDetailBottomBar" in text
    assert "function openOzonFbsSupplyDetailMoveExisting" in text
    assert "function openOzonFbsSupplyDetailNewSupply" in text
    assert "function confirmOzonFbsSupplyDetailNewSupply" in text
    assert "/api/ozon-fbs/postings/bulk-move-to-supply" in text
    assert "/api/ozon-fbs/postings/bulk-move-to-new-supply" in text
    assert "excludeSupplyId" in text
    # Single-posting move path must remain available.
    assert "/api/ozon-fbs/postings/${encodeURIComponent(nums[0])}/move-to-supply" in text
    assert "window.clearOzonFbsSupplyDetailSelection" in text
    # Empty supply / empty filter must clear or refresh the selection bar.
    assert 'В поставке нет отправлений' in text
    assert "updateSupplyDetailBottomBar();" in text
    empty_idx = text.index('В поставке нет отправлений')
    # The empty-supply branch must call the bar updater (not only the happy path).
    branch = text[empty_idx : empty_idx + 450]
    assert "updateSupplyDetailBottomBar()" in branch
    assert "supplyDetailState.selected = new Set()" in branch
