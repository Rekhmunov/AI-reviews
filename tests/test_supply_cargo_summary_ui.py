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
    assert ".wb-fbs-sd-cargo-inline" in style
    assert ".wb-fbs-create-trbx-header-main" in style

    assert "function _wbFbsRenderCargoSummary(" in app_js
    assert 'wbFbsSupplyDetailCargo' in app_js
    assert 'wbFbsCreateTrbxCargo' in app_js
    assert "function _ozonFbsRenderCargoSummary(" in ozon_js
    assert 'ozonFbsSupplyDetailCargo' in ozon_js
    assert 'ozonFbsContainersCargo' in ozon_js


def test_ozon_cargo_summary_inline_with_meta_and_title() -> None:
    """Ozon: pallet line sits on the same row as chips / Грузоместа title."""
    app_html = (TEMPLATES / "app.html").read_text(encoding="utf-8")
    sd_start = app_html.find('id="ozonFbsSupplyDetailModal"')
    sd_end = app_html.find('id="ozonFbsSupplyDetailModal"', sd_start + 1)
    # Modal block until next major modal is enough; use cargo id neighborhood.
    cargo_idx = app_html.find('id="ozonFbsSupplyDetailCargo"')
    assert cargo_idx > 0
    neighborhood = app_html[max(0, cargo_idx - 400) : cargo_idx + 200]
    assert "wb-fbs-sd-meta-row" in neighborhood
    assert "wb-fbs-sd-cargo-inline" in neighborhood
    assert 'id="ozonFbsSupplyDetailMeta"' in neighborhood

    c_idx = app_html.find('id="ozonFbsContainersCargo"')
    assert c_idx > 0
    c_nb = app_html[max(0, c_idx - 350) : c_idx + 180]
    assert "wb-fbs-create-trbx-header-main" in c_nb
    assert "wb-fbs-trbx-cargo-inline" in c_nb
    assert 'id="ozonFbsContainersTitle"' in c_nb
