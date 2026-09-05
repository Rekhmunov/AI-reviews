"""UI: Поставки → Остатки — mobile card layout + full-bleed modals."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def _balances_mobile_block() -> str:
    start = STYLE.find("Edge-to-edge Остатки")
    assert start > 0
    end = STYLE.find("WB FBS → ЧЗ", start)
    assert end > start
    return STYLE[start:end]


def test_balances_section_and_modals_exist() -> None:
    assert 'id="section-supplies-balances"' in APP_HTML
    for mid in (
        "supplyBalancesVisibilityModal",
        "supplyStockReceiptModal",
        "supplyStockAdjustmentModal",
        "supplyStockAsOfModal",
        "supplyStockMovementsModal",
    ):
        assert f'id="{mid}"' in APP_HTML


def test_mobile_balances_card_layout_css() -> None:
    block = _balances_mobile_block()
    assert "#section-supplies-balances .supply-balances-table" in block
    assert "display: flex" in block
    assert "tr.sb-item-row" in block
    assert "grid-template-columns: minmax(0, 1fr) auto" in block
    assert "td.sb-col-today" in block
    assert "border-radius: 12px" in block
    assert ".main:has(#section-supplies-balances:not(.hidden))" in block


def test_mobile_balances_modals_full_bleed() -> None:
    block = _balances_mobile_block()
    for mid in (
        "supplyBalancesVisibilityModal",
        "supplyStockReceiptModal",
        "supplyStockAdjustmentModal",
        "supplyStockAsOfModal",
        "supplyStockMovementsModal",
    ):
        assert f"#{mid}" in block
        assert f"#{mid} > .modal-card" in block or f"#{mid} > .sb-sheet-modal" in block
    assert "height: 100dvh !important" in block
    assert "env(safe-area-inset-bottom)" in block
    assert "flex-direction: column-reverse" in block
    assert "min-height: 44px" in block


def test_js_fluid_table_width_on_compact() -> None:
    assert "function _sbIsCompactViewport(" in APP_JS
    assert 'table.style.width = "100%"' in APP_JS
    assert 'table.style.minWidth = "0"' in APP_JS
    assert 'data-sb-date="${esc(d)}"' in APP_JS


def test_cache_bump() -> None:
    assert "style.css?v=305" in APP_HTML
    assert "app.js?v=549" in APP_HTML
