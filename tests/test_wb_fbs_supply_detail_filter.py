"""WB FBS supply detail: KIZ / filled filters (no GM), same rules as KIZ+Pick windows."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_wb_supply_detail_filter_ui_wiring() -> None:
    html = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
    js = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")

    assert 'id="wbFbsSupplyDetailFilterBtn"' in html
    assert 'id="wbFbsSupplyDetailFilterPanel"' in html
    assert 'id="wbFbsSdFilterWithKiz"' in html
    assert 'id="wbFbsSdFilterWithoutKiz"' in html
    assert 'id="wbFbsSdFilterFilled"' in html
    assert 'id="wbFbsSdFilterEmpty"' in html
    assert "applyWbFbsSupplyDetailFilter()" in html
    assert "resetWbFbsSupplyDetailFilter()" in html
    # No GM facet on WB supply filter panel.
    wb_panel_start = html.find('id="wbFbsSupplyDetailFilterPanel"')
    assert wb_panel_start > 0
    wb_panel = html[wb_panel_start : wb_panel_start + 2200]
    assert "Грузоместа" not in wb_panel
    assert "С ГМ" not in wb_panel
    assert "Товары" in wb_panel
    assert "Заполнение" in wb_panel

    assert "function toggleWbFbsSupplyDetailFilterPanel" in js
    assert "function applyWbFbsSupplyDetailFilter" in js
    assert "function resetWbFbsSupplyDetailFilter" in js
    assert "function _wbFbsSupplyDetailRowMatchesFilter" in js
    assert "function _wbFbsSupplyDetailRowIsFilled" in js
    assert "_wbFbsSupplyDetailRowMatchesFilter(o)" in js
    assert "!_wbFbsKizRowIsEmpty(o)" in js
    assert "_wbFbsPickRowIsComplete(o)" in js
    assert "rowFilter" in js
    assert "app.js?v=726" in html
    assert "style.css?v=447" in html
    assert ".wb-fbs-sd-filter-panel" in css
    assert ".wb-fbs-sd-filter-btn.is-active" in css
