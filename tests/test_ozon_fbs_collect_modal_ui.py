"""Ozon FBS «Собрать все заказы» / «Добавить к существующей» modal UI."""

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
    assert 'id="ozonFbsCollectLead"' in html
    assert "ozon-fbs-collect-lead" in html

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
    assert "style.css?v=" in html
    assert "ozon_fbs.js?v=" in html


def test_collect_modal_title_count_and_aligned_radios() -> None:
    js = (STATIC / "ozon_fbs.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    render = js[
        js.index("function renderCollectModal") : js.index("function collectTargetChanged")
    ]
    assert "Собрать все заказы:" in render
    assert "шт." in render
    assert "ozon-fbs-collect-supply-main" in render
    assert "Отправлений в «Ожидают сборки»" not in render
    # Group warehouse header only when several groups.
    assert "showGroupHead" in render
    assert ".ozon-fbs-collect-supply-main" in css
    assert "align-items: center" in css[css.index(".ozon-fbs-collect-supply-main") :][:200]
    assert "margin: 0 0 0 28px" in css[css.index(".ozon-fbs-collect-supply-meta") :][:120]


def test_selection_add_modal_aligned_radios_no_trait_chips() -> None:
    js = (STATIC / "ozon_fbs.js").read_text(encoding="utf-8")
    chunk = js[
        js.index("function renderSelectionAddModal") : js.index(
            "function selectionSupplyNameInput"
        )
    ]
    assert "selectionTraitsHtml" not in chunk
    assert "wb-fbs-collect-mgt-supply-main" in chunk
    assert 'name="ozonFbsSelectionSupplyPick"' in chunk
    assert "warehouse_name" not in chunk
