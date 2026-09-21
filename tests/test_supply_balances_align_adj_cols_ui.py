"""Поставки → Остатки: left-align qty + resizable modal columns."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def _slice_around(text: str, needle: str, before: int = 0, after: int = 240) -> str:
    idx = text.find(needle)
    assert idx >= 0, needle
    return text[idx + before : idx + after]


def test_balance_qty_columns_left_aligned() -> None:
    block = _slice_around(STYLE, ".supply-balances-table td.sb-col-date,", after=220)
    assert "text-align: left;" in block
    assert "text-align: right;" not in block

    wrap = _slice_around(STYLE, ".supply-balances-table .sb-qty-wrap {", after=160)
    assert "justify-content: flex-start;" in wrap
    assert "justify-content: flex-end;" not in wrap

    mobile = _slice_around(
        STYLE,
        "#section-supplies-balances .supply-balances-table tr.sb-item-row td.sb-col-today {",
        after=200,
    )
    assert "text-align: left;" in mobile
    assert "justify-self: start;" in mobile


def test_adj_modal_columns_resizable_and_persisted() -> None:
    assert APP_HTML.count('class="sb-adj-col-resize"') >= 6
    assert 'data-sb-adj-resize="name"' in APP_HTML
    assert 'data-sb-adj-resize="qty"' in APP_HTML
    assert 'data-sb-adj-resize="comment"' in APP_HTML

    assert "--sb-adj-photo-w:" in STYLE
    assert "--sb-adj-name-w:" in STYLE
    assert (
        "grid-template-columns: 36px var(--sb-adj-photo-w) "
        "minmax(140px, var(--sb-adj-name-w)) var(--sb-adj-qty-w) "
        "minmax(100px, var(--sb-adj-comment-w));"
    ) in STYLE
    assert ".sb-adj-col-resize" in STYLE

    assert 'SB_ADJ_COL_WIDTHS_KEY = "supply_stock_adj_col_widths_v1"' in APP_JS
    assert "function initSupplyStockAdjColumnResizer()" in APP_JS
    assert "localStorage.setItem(SB_ADJ_COL_WIDTHS_KEY" in APP_JS
    assert APP_JS.count("initSupplyStockAdjColumnResizer();") >= 2


def test_adj_modals_have_product_photo_column() -> None:
    assert APP_HTML.count('class="sb-adj-col sb-adj-col-photo"') == 2
    assert "function _sbAdjPhotoHtml(row)" in APP_JS
    assert 'row.photo_url' in APP_JS
    assert '<div class="sb-adj-photo">${_sbAdjPhotoHtml(row)}</div>' in APP_JS
    assert "sb-adj-photo-empty" in APP_JS
    assert ".sb-adj-list .sb-adj-photo .wb-fbs-product-photo" in STYLE


def test_cache_bump_align_adj_cols() -> None:
    assert "style.css?v=406" in APP_HTML
    assert "app.js?v=689" in APP_HTML


def test_balance_as_of_qty_is_inline_adjustment() -> None:
    assert "function _sbBeginInlineQtyEdit(" in APP_JS
    assert "async function _sbSaveInlineStockAdjustment(" in APP_JS
    assert 'mode: "adjustment"' in APP_JS
    assert 'quantity_mode: "absolute"' in APP_JS
    assert 'editable: supplyBalancesState.viewMode === "balance"' in APP_JS
    assert "button.sb-qty-edit" in APP_JS
    assert "if (supplyBalancesState.viewMode !== \"balance\") return;" in APP_JS
    # History columns and sales stay read-only spans; only the selected date is a button.
    assert "canEditAsOf && isAsOf" in APP_JS
    assert "class=\"sb-qty-edit\"" in STYLE or "button.sb-qty-edit" in STYLE
