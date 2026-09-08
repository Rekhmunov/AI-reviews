"""UI: Supplies section + modals mobile sheet polish."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_supply_mobile_css_block_exists() -> None:
    assert "Supplies (Поставки): mobile shell + modals" in STYLE
    assert "@media (max-width: 720px)" in STYLE
    assert "100dvh" in STYLE
    assert "env(safe-area-inset-bottom)" in STYLE
    assert "#section-supplies-wb-fbs #wbFbsOrdersTable" in STYLE
    assert "#wbFbsSupplyDetailModal" in STYLE
    assert "#wbFbsCollectMgtModal" in STYLE
    assert "#supplyDetailsModal" in STYLE
    assert "#supplyStockReceiptModal" in STYLE
    assert "min-height: 44px" in STYLE


def test_receipt_scan_autofocus_skips_touch() -> None:
    assert '(hover: hover) and (pointer: fine)' in APP_JS
    assert "setTimeout(() => scanEl?.focus(), 40)" in APP_JS


def test_style_cache_bump() -> None:
    assert "style.css?v=318" in APP_HTML
    assert "app.js?v=562" in APP_HTML


def test_balances_toolbar_filter_panel_layout() -> None:
    """Категория / Вывод / История — под иконкой фильтра слева от поиска."""
    start = APP_HTML.find('id="section-supplies-balances"')
    end = APP_HTML.find("<!-- ── Планирование", start + 1)
    if end < 0:
        end = APP_HTML.find('id="section-supplies-settings"', start)
    assert start > 0 and end > start
    block = APP_HTML[start:end]
    assert 'id="supplyBalancesFilterBtn"' in block
    assert 'id="supplyBalancesFilterPanel"' in block
    assert "hidden" in block[block.find('id="supplyBalancesFilterPanel"') : block.find('id="supplyBalancesFilterPanel"') + 90]
    filter_i = block.find('id="supplyBalancesFilterBtn"')
    search_i = block.find('id="supplyBalancesSearchFilter"')
    below_i = block.find('id="supplyBalancesBelowMinBtn"')
    asof_i = block.find("openSupplyStockAsOfModal()")
    adj_i = block.find("openSupplyStockAdjustmentModal()")
    receipt_i = block.find("openSupplyStockReceiptModal()")
    assert 0 < filter_i < search_i < below_i < asof_i < adj_i < receipt_i
    # Category / visibility / history live inside the filter panel.
    panel = block[block.find('id="supplyBalancesFilterPanel"') : block.find('id="supplyBalancesSearchFilter"')]
    assert "supplyBalancesCategoryFilter" in panel
    assert "openSupplyBalancesVisibilityModal()" in panel
    assert "supplyBalancesHistoryBtn" in panel
    assert "openSupplyBalancesVisibilityModal()" not in block[block.find("sb-toolbar-filters") :]
    assert "toggleSupplyBalancesFilterPanel" in APP_JS
    assert ".sb-balances-filter-panel" in STYLE
    assert ".sb-toolbar-leading" in STYLE

