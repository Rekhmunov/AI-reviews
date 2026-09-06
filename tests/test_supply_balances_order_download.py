"""Поставки → Остатки: mobile below-min hide + order Excel modal."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


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
    assert '["Товар", "Заказ"]' in APP_JS or "[[\"Товар\", \"Заказ\"]]" in APP_JS
    assert "zakaz_ostatki_" in APP_JS
    assert 'viewMode !== "balance"' in APP_JS
    assert "supplyBalancesOrderDownloadBtn" in APP_JS


def test_cache_bump_order_feature() -> None:
    assert "style.css?v=307" in APP_HTML
    assert "app.js?v=553" in APP_HTML
