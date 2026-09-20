"""Поставки → Остатки: mobile below-min hide + order Excel modal."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
WEB = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")


def _mobile_balances_block() -> str:
    start = STYLE.find("Edge-to-edge Остатки")
    assert start > 0
    end = STYLE.find("WB FBS → ЧЗ", start)
    assert end > start
    return STYLE[start:end]


def test_mobile_below_min_hides_card_rows() -> None:
    block = _mobile_balances_block()
    assert "tr.sb-item-row.hidden" in block
    assert "tr.sb-item-row[hidden]" in block
    assert "display: none !important" in block
    # Card layout still present (desktop untouched).
    assert "tr.sb-item-row" in block
    assert "display: grid" in block


def test_order_download_button_next_to_below_min() -> None:
    assert 'id="supplyBalancesBelowMinBtn"' in APP_HTML
    assert 'id="supplyBalancesOrderDownloadBtn"' in APP_HTML
    assert "sb-below-min-cluster" in APP_HTML
    assert "openSupplyBalancesOrderModal()" in APP_HTML
    assert ".sb-below-min-cluster" in STYLE
    assert ".sb-order-dl-btn" in STYLE


def test_order_modal_filters_and_table() -> None:
    assert 'id="supplyBalancesOrderModal"' in APP_HTML
    assert 'id="supplyBalancesOrderBelowFilter"' in APP_HTML
    assert 'id="supplyBalancesOrderCategoryFilter"' in APP_HTML
    assert 'id="supplyBalancesOrderTbody"' in APP_HTML
    assert "exportSupplyBalancesOrderXlsx()" in APP_HTML
    assert "function openSupplyBalancesOrderModal(" in APP_JS
    assert "function exportSupplyBalancesOrderXlsx(" in APP_JS
    assert "_sbOrderDefaultQty" in APP_JS
    assert "_sbBuildSimpleXlsxBlob" in APP_JS
    assert '["Товар", "Заказ", "Заказ (короба)"]' in APP_JS
    assert "function _sbOrderBoxesQty(" in APP_JS
    assert "_sbOrderBoxesQty(qty, row.box_qty)" in APP_JS
    assert "zakaz_ostatki_" in APP_JS
    assert 'viewMode !== "balance"' in APP_JS
    assert "supplyBalancesOrderDownloadBtn" in APP_JS
    assert 'id="supplyBalancesOrderTotalQty"' in APP_HTML
    assert "Итого к заказу" in APP_HTML
    assert 'id="supplyBalancesOrderCategoryBtn"' in APP_HTML
    assert 'id="supplyBalancesOrderCategoryPanel"' in APP_HTML
    assert "sb-order-cat-panel" in APP_HTML
    assert "toggleSupplyBalancesOrderCategoryMenu()" in APP_HTML
    assert 'multiple size="6"' in APP_HTML
    assert 'id="supplyBalancesOrderCategoryFilter" multiple' in APP_HTML
    assert "supplyBalancesOrderState.categories = []" in APP_JS
    assert "_sbDataRowMatchesCategoryFilters(row, categories)" in APP_JS
    assert "_sbReadCategoryFiltersFromSelect(catEl)" in APP_JS
    assert "_sbRefreshOrderTotal" in APP_JS
    assert "_sbSelectedCategoryFilters()[0]" not in APP_JS[APP_JS.find("function openSupplyBalancesOrderModal"):APP_JS.find("function closeSupplyBalancesOrderModal")]


def test_order_excel_box_column_uses_product_box_qty() -> None:
    start = WEB.find("def get_supply_balances")
    chunk = WEB[start:start + 12000]
    assert "def _product_box_qty" in chunk
    assert '"box_qty": box_qty' in chunk
    assert "return value if value > 0 else None" in chunk


def test_cache_bump_order_feature() -> None:
    assert "style.css?v=405" in APP_HTML
    assert "app.js?v=684" in APP_HTML
