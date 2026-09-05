"""UI contract: WB FBS «Добавить к существующей» — no trait chips, aligned radios."""

from __future__ import annotations

from pathlib import Path

_APP_JS = Path(__file__).resolve().parents[1] / "web_static" / "app.js"
_STYLE = Path(__file__).resolve().parents[1] / "web_static" / "style.css"


def test_wb_selection_add_modal_no_trait_chips() -> None:
    text = _APP_JS.read_text(encoding="utf-8")
    start = text.index("function _wbFbsRenderSelectionAddModal")
    end = text.index("function wbFbsSelectionSupplyNameInput")
    chunk = text[start:end]
    assert "_wbFbsSelectionTraitsHtml" not in chunk
    assert "не B2B" not in chunk
    assert "Склад" not in chunk
    assert "кроссбордер" not in chunk.lower()
    assert "cargo_label" not in chunk
    # Radio name aligned on same row as the control.
    assert "wb-fbs-collect-mgt-supply-main" in chunk
    assert 'name="wbFbsSelectionSupplyPick"' in chunk


def test_wb_collect_mgt_supply_main_aligned_in_css() -> None:
    css = _STYLE.read_text(encoding="utf-8")
    assert ".wb-fbs-collect-mgt-supply-main" in css
    assert "align-items: center" in css
    # Collect-MGT title carries the count; group warehouse header is gone.
    js = _APP_JS.read_text(encoding="utf-8")
    render = js[
        js.index("function _wbFbsCollectMgtRenderModal") : js.index(
            "function wbFbsCollectMgtTargetChanged"
        )
    ]
    assert "Собрать все МГТ-заказы:" in render
    assert "шт." in render
    assert "wb-fbs-collect-mgt-group-head" not in render
    assert "Новых МГТ" not in render
