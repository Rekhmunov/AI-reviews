"""Ozon FBS supply modal: warn when «Ожидают сборки» still has orders."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web_static"
TEMPLATES = ROOT / "web_templates"


def test_ozon_supply_uncollected_warn_parity_with_wb() -> None:
    js = (STATIC / "ozon_fbs.js").read_text(encoding="utf-8")
    html = (TEMPLATES / "app.html").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")

    assert 'id="ozonFbsSupplyDetailNewWarn"' in html
    assert "Не все заказы собраны из «Ожидают сборки»." in html
    assert "Собрать все заказы" in html
    assert 'class="wb-fbs-sd-new-warn"' in html

    assert "function _ozonFbsSupplyDetailUpdateNewWarn" in js
    assert "function _ozonFbsSupplyDetailHideNewWarn" in js
    assert "counts.awaiting_packaging" in js
    assert 'postingTab !== "awaiting_deliver"' in js
    assert "packagingCount <= 0" in js
    assert "_ozonFbsSupplyDetailUpdateNewWarn()" in js
    assert "_ozonFbsSupplyDetailHideNewWarn()" in js

    # Reuse WB alert styling (same visual language).
    assert ".wb-fbs-sd-new-warn" in css
    assert "ozon_fbs.js?v=" in html
