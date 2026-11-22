"""Ozon FBS supply detail: filter orders by cargo place (GM) in the modal."""

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
    assert "applyOzonFbsSupplyDetailGmFilter()" in html
    assert "resetOzonFbsSupplyDetailGmFilter()" in html

    assert "function toggleOzonFbsSupplyDetailGmFilterPanel" in js
    assert "function applyOzonFbsSupplyDetailGmFilter" in js
    assert "function resetOzonFbsSupplyDetailGmFilter" in js
    assert "function _ozonFbsSupplyDetailRowMatchesGmFilter" in js
    assert "_ozonFbsSupplyDetailRowMatchesGmFilter(o)" in js
    assert "gmFilter" in js
    assert "ozon_fbs.js?v=228" in html
