"""Ozon FBS supply detail: filter orders by GM / KIZ / filled in the modal."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_supply_detail_gm_filter_ui_wiring() -> None:
    html = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
    js = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")

    assert 'id="ozonFbsSupplyDetailGmFilterBtn"' in html
    assert 'id="ozonFbsSupplyDetailGmFilterPanel"' in html
    assert 'id="ozonFbsSdGmFilterWith"' in html
    assert 'id="ozonFbsSdGmFilterWithout"' in html
    assert "С ГМ" in html
    assert "Без ГМ" in html
    assert 'id="ozonFbsSdFilterWithKiz"' in html
    assert 'id="ozonFbsSdFilterWithoutKiz"' in html
    assert 'id="ozonFbsSdFilterFilled"' in html
    assert 'id="ozonFbsSdFilterEmpty"' in html
    assert "С КИЗ" in html
    assert "Без КИЗ" in html
    assert "Заполненные" in html
    assert "Незаполненные" in html
    assert "applyOzonFbsSupplyDetailGmFilter()" in html
    assert "resetOzonFbsSupplyDetailGmFilter()" in html

    assert "function toggleOzonFbsSupplyDetailGmFilterPanel" in js
    assert "function applyOzonFbsSupplyDetailGmFilter" in js
    assert "function resetOzonFbsSupplyDetailGmFilter" in js
    assert "function _ozonFbsSupplyDetailRowMatchesGmFilter" in js
    assert "function _ozonFbsSupplyDetailRowIsFilled" in js
    assert "_ozonFbsSupplyDetailRowMatchesGmFilter(o)" in js
    assert "_ozonFbsKizRowFilled(o)" in js
    assert "_ozonFbsPickRowPickOk(o)" in js
    assert "gmFilter" in js
    assert "withKiz" in js
    assert "withoutKiz" in js
    assert "ozon_fbs.js?v=230" in html
    assert "style.css?v=445" in html


def test_supply_detail_filter_panel_sections() -> None:
    html = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
    # Compact panel: three facet sections + side-by-side actions.
    ozon_panel_start = html.find('id="ozonFbsSupplyDetailGmFilterPanel"')
    assert ozon_panel_start > 0
    ozon_panel = html[ozon_panel_start : ozon_panel_start + 2500]
    assert "Грузоместа" in ozon_panel
    assert "Товары" in ozon_panel
    assert "Заполнение" in ozon_panel
    assert "ozon-fbs-sd-filter-section" in ozon_panel
