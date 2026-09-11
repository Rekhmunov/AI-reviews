"""Поставки → Остатки: заметная сводка продаж + multi category filter."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_sales_status_is_emphasized() -> None:
    block = STYLE[STYLE.find(".sb-status {") : STYLE.find(".sb-status {") + 420]
    assert "color: #0f172a;" in block
    assert "font-weight: 600;" in block
    assert ".sb-status.is-summary" in STYLE
    assert 'classList.toggle("is-summary"' in APP_JS


def test_sales_status_recalculates_on_category_filter() -> None:
    assert "function _sbRefreshSalesPeriodStatus()" in APP_JS
    assert "_sbRefreshSalesPeriodStatus();" in APP_JS
    assert "function applySupplyBalancesSearchFilter()" in APP_JS
    # called from filter apply
    apply = APP_JS.split("function applySupplyBalancesSearchFilter()", 1)[1].split("\nfunction ", 1)[0]
    assert "_sbRefreshSalesPeriodStatus();" in apply
    assert "_sbDataRowMatchesCategoryFilters" in APP_JS


def test_category_filter_multiselect_ctrl_click() -> None:
    assert 'id="supplyBalancesCategoryFilter"' in APP_HTML
    assert "multiple" in APP_HTML.split('id="supplyBalancesCategoryFilter"', 1)[1].split(">", 1)[0]
    assert "sb-category-filter-hint" in APP_HTML
    assert "Ctrl+клик" in APP_HTML
    assert "categoryFilter: []" in APP_JS
    assert "function _sbReadCategoryFiltersFromSelect(" in APP_JS
    assert "sel.multiple" in APP_JS
    assert "select[multiple]" in STYLE


def test_cache_bump_sales_summary_multicat() -> None:
    assert "style.css?v=356" in APP_HTML
    assert "app.js?v=612" in APP_HTML


def test_category_filter_panel_shows_full_names() -> None:
    """Category filter panel is wide enough for long category labels."""
    assert "min(460px, calc(100vw - 32px))" in STYLE
    assert 'title="${esc(o.label)}"' in APP_JS
