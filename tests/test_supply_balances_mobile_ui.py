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
        "supplyBalancesOrderModal",
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
        "supplyBalancesOrderModal",
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
    assert "style.css?v=311" in APP_HTML
    assert "app.js?v=559" in APP_HTML


def test_receipt_modal_compact_bulk_under_filter() -> None:
    """Добавить на склад: lead gone, date label gone, bulk under filter icon."""
    start = APP_HTML.find('id="supplyStockReceiptModal"')
    end = APP_HTML.find('id="supplyStockAdjustmentModal"')
    assert start > 0 and end > start
    block = APP_HTML[start:end]
    assert "Укажите количество прихода" not in block
    assert ">Дата<" not in block
    assert 'aria-label="Дата"' in block
    assert 'id="supplyStockReceiptFilterBtn"' in block
    assert 'id="supplyStockReceiptBulkPanel" class="sb-bulk-panel" hidden>' in block
    # Filter icon sits left of search in the same search-end cluster.
    filter_i = block.find('id="supplyStockReceiptFilterBtn"')
    search_i = block.find('id="supplyStockReceiptSearch"')
    assert 0 < filter_i < search_i
    assert "toggleSupplyStockReceiptBulkPanel" in APP_JS
    assert "setSupplyStockReceiptBulkPanelOpen" in APP_JS
    assert ".sb-adj-modal .sb-bulk-filter-btn" in STYLE
    assert ".sb-adj-modal .sb-bulk-panel[hidden]" in STYLE
    assert "#supplyStockReceiptModal .sb-sheet-header" in STYLE
    assert "Ко всем" in block
    assert "Обнулить выбранные" in block
    assert "supplyStockReceiptBulkValue" in block


def test_adj_modal_bulk_under_filter() -> None:
    """Корректировка: bulk-панель под иконкой фильтра слева от поиска."""
    start = APP_HTML.find('id="supplyStockAdjustmentModal"')
    end = APP_HTML.find('id="supplyStockAsOfModal"')
    assert start > 0 and end > start
    block = APP_HTML[start:end]
    assert 'id="supplyStockAdjFilterBtn"' in block
    assert 'id="supplyStockAdjBulkPanel" class="sb-bulk-panel" hidden>' in block
    filter_i = block.find('id="supplyStockAdjFilterBtn"')
    search_i = block.find('id="supplyStockAdjSearch"')
    assert 0 < filter_i < search_i
    assert "Ко всем" in block
    assert "Обнулить выбранные" in block
    assert "supplyStockAdjBulkValue" in block
    assert "toggleSupplyStockAdjBulkPanel" in APP_JS
    assert "setSupplyStockAdjBulkPanelOpen" in APP_JS
    assert "setSupplyStockAdjBulkPanelOpen(false)" in APP_JS
    assert "#supplyStockAdjustmentModal .sb-sheet-header" in STYLE


def test_receipt_kind_select_left_of_date() -> None:
    """Тип Приход/Возврат слева от календаря; комментарий получает метку при сохранении."""
    start = APP_HTML.find('id="supplyStockReceiptModal"')
    end = APP_HTML.find('id="supplyStockAdjustmentModal"')
    block = APP_HTML[start:end]
    assert 'id="supplyStockReceiptKind"' in block
    assert 'value="receipt">Приход<' in block
    assert 'value="return">Возврат<' in block
    kind_i = block.find('id="supplyStockReceiptKind"')
    date_i = block.find('id="supplyStockReceiptDate"')
    assert 0 < kind_i < date_i
    assert "function _sbReceiptKindCommentTag" in APP_JS
    assert 'return k === "return" ? "Возврат" : "приход"' in APP_JS
    assert "function _sbMergeReceiptKindComment" in APP_JS
    assert "_sbMergeReceiptKindComment(" in APP_JS
    assert 'id="supplyStockReceiptSaveBtn"' in block
    assert ">Сохранить<" in block
    assert "Сохранить приход" not in block
    assert "Сохранить возврат" not in APP_JS
    # Unit-ish: merge helper behaviour encoded in source order / tags.
    merge = APP_JS[
        APP_JS.find("function _sbMergeReceiptKindComment") : APP_JS.find(
            "async function openSupplyStockReceiptModal"
        )
    ]
    assert "if (!base) return tag;" in merge
    assert "return `${base} · ${tag}`;" in merge
    assert "#supplyStockReceiptModal .sb-doc-field-bare select" in STYLE
