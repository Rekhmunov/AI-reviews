"""Ozon FBS «Собрать все заказы» modal — layout/structure UI regression."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web_static"
TEMPLATES = ROOT / "web_templates"


def test_collect_modal_structure_and_styles() -> None:
    js = (STATIC / "ozon_fbs.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    html = (TEMPLATES / "app.html").read_text(encoding="utf-8")

    assert 'id="ozonFbsCollectModal"' in html
    assert 'id="ozonFbsCollectResultModal"' in html
    assert 'class="modal-card ozon-fbs-collect-modal"' in html
    assert 'class="ozon-fbs-collect-header"' in html
    assert 'class="ozon-fbs-collect-content"' in html
    assert 'class="ozon-fbs-collect-footer"' in html
    assert 'id="ozonFbsCollectConfirmBtn"' in html
    assert "Понятно" in html

    assert "function renderCollectModal" in js
    assert "ozon-fbs-collect-group" in js
    assert "ozon-fbs-collect-supply" in js
    assert "ozon-fbs-collect-field" in js
    assert "ozon-fbs-collect-result-ok" in js
    assert "ozon-fbs-collect-result-err" in js

    assert ".ozon-fbs-collect-modal" in css
    assert ".ozon-fbs-collect-group-head" in css
    assert ".ozon-fbs-collect-supply:has(input:checked)" in css
    assert ".ozon-fbs-collect-footer" in css
    assert "style.css?v=293" in html
    assert "ozon_fbs.js?v=120" in html
