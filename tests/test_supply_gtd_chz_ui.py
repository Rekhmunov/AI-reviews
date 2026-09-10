"""UI assertions for Настройки → ГТД → Работа с ЧЗ table."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")


def _gtd_chz_block() -> str:
    start = APP_HTML.find('id="supplyGtdChzModal"')
    end = APP_HTML.find('id="supplyGtdChzLogModal"')
    assert start > 0 and end > start
    return APP_HTML[start:end]


def test_gtd_chz_table_has_name_between_kiz_and_gtin() -> None:
    block = _gtd_chz_block()
    assert 'id="supplyGtdChzTable"' in block
    assert 'id="supplyGtdChzColgroup"' in block
    assert 'data-col="name"' in block
    kiz = block.find(">КИЗ<")
    name = block.find(">Наименование<")
    gtin = block.find(">GTIN<")
    assert kiz > 0 and name > kiz and gtin > name


def test_gtd_chz_columns_resizable_markup() -> None:
    block = _gtd_chz_block()
    assert block.count('class="col-resize-handle"') >= 7
    assert 'data-col="check"' in block
    assert 'data-col="kiz"' in block
    assert 'data-col="gtin"' in block
    assert 'data-col="status"' in block
    assert 'data-col="doc"' in block
    assert 'data-col="error"' in block
    assert 'data-col="updated"' in block


def test_gtd_chz_js_col_widths_persist() -> None:
    assert 'SUPPLY_GTD_CHZ_COL_WIDTHS_KEY = "supply_gtd_chz_col_widths_v1"' in APP_JS
    assert "function _supplyGtdChzLoadColWidths" in APP_JS
    assert "function _supplyGtdChzSaveColWidths" in APP_JS
    assert "function _supplyGtdChzApplyColWidths" in APP_JS
    assert "function initSupplyGtdChzColumnResizer" in APP_JS
    assert "localStorage.setItem(SUPPLY_GTD_CHZ_COL_WIDTHS_KEY" in APP_JS
    open_fn = APP_JS[
        APP_JS.find("async function openSupplyGtdChzModal") : APP_JS.find(
            "function closeSupplyGtdChzModal"
        )
    ]
    assert "initSupplyGtdChzColumnResizer()" in open_fn


def test_gtd_chz_js_product_name_from_catalog() -> None:
    assert "function _supplyGtdChzEnsureProductsCache" in APP_JS
    assert "function _supplyGtdChzRebuildProductNameIndex" in APP_JS
    assert "function _supplyGtdChzProductName" in APP_JS
    name_fn = APP_JS[
        APP_JS.find("function _supplyGtdChzProductName") : APP_JS.find(
            "function _supplyGtdChzLoadColWidths"
        )
    ]
    assert "itOrGtin.product_name" in name_fn or "product_name" in name_fn
    assert "_wbFbsKizGtinToProductSkus" in name_fn
    render = APP_JS[
        APP_JS.find("function _supplyGtdChzRenderTable") : APP_JS.find(
            "async function _supplyGtdChzFetch"
        )
    ]
    assert "_supplyGtdChzProductName(it)" in render
    assert 'colspan="8"' in render
    open_fn = APP_JS[
        APP_JS.find("async function openSupplyGtdChzModal") : APP_JS.find(
            "function closeSupplyGtdChzModal"
        )
    ]
    assert "_supplyGtdChzEnsureProductsCache()" in open_fn


def test_gtd_chz_search_covers_name_and_gtin() -> None:
    visible = APP_JS[
        APP_JS.find("function _supplyGtdChzVisibleItems") : APP_JS.find(
            "function _supplyGtdChzRowOpReady"
        )
    ]
    assert "it.gtin" in visible
    assert "_supplyGtdChzProductName(it)" in visible
    assert "КИЗ, GTIN, название…" in _gtd_chz_block()


def test_asset_version_bumped() -> None:
    assert "app.js?v=582" in APP_HTML
