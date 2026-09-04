"""Markup for supply / GM cargo summary (WB + Ozon FBS)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web_templates"
STATIC = ROOT / "web_static"


def test_supply_and_gm_cargo_summary_markup() -> None:
    app_html = (TEMPLATES / "app.html").read_text(encoding="utf-8")
    style = (STATIC / "style.css").read_text(encoding="utf-8")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    ozon_js = (STATIC / "ozon_fbs.js").read_text(encoding="utf-8")

    for eid in (
        "wbFbsSupplyDetailCargo",
        "wbFbsCreateTrbxCargo",
        "ozonFbsSupplyDetailCargo",
        "ozonFbsContainersCargo",
    ):
        assert f'id="{eid}"' in app_html

    assert ".wb-fbs-sd-cargo" in style
    assert ".wb-fbs-sd-cargo-label" in style

    assert "function _wbFbsRenderCargoSummary(" in app_js
    assert 'wbFbsSupplyDetailCargo' in app_js
    assert 'wbFbsCreateTrbxCargo' in app_js
    assert "function _ozonFbsRenderCargoSummary(" in ozon_js
    assert 'ozonFbsSupplyDetailCargo' in ozon_js
    assert 'ozonFbsContainersCargo' in ozon_js
