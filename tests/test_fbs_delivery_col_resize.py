"""Column resize memory and text wrap on FBS delivery tables only."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
OZON_JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")


def _slice(src: str, start: str, end: str) -> str:
    i = src.find(start)
    assert i >= 0, start
    j = src.find(end, i + len(start))
    assert j > i, end
    return src[i:j]


def test_cache_versions() -> None:
    assert "app.js?v=697" in HTML
    assert "ozon_fbs.js?v=197" in HTML
    assert "style.css?v=416" in HTML


def test_wb_delivery_wrap_class_keeps_existing_resizer() -> None:
    sync = _slice(APP_JS, "function _wbFbsSyncTableMode", "function _wbFbsClearLookupMode")
    assert 'table.classList.toggle("fbs-col-wrap", wbFbsState.tab === "delivery")' in sync
    delivery = sync.split("} else if (supplies)", 1)[1].split("} else {", 1)[0]
    assert "col-resize-handle" in delivery
    assert "initWbFbsColumnResizer()" in delivery
    assert "wb_fbs_col_widths_v3" in APP_JS
    assert "supplies-delivery" in APP_JS


def test_ozon_delivering_resizer_is_separate_from_orders() -> None:
    sync = _slice(OZON_JS, "function syncTableMode", "function _ozonFbsRenameMenuIconHtml")
    assert 'table.classList.toggle("fbs-col-wrap", isDeliveringSuppliesTab())' in sync
    assert 'const rh = delivering ? \'<span class="col-resize-handle"></span>\' : "";' in sync
    assert "initDeliveringColumnResizer()" in sync
    fn = _slice(OZON_JS, "function initDeliveringColumnResizer", "const COL_WIDTHS_PREFIX")
    assert "if (!table || !isDeliveringSuppliesTab()) return;" in fn
    assert "ozon_fbs_delivering_col_widths_v1" in OZON_JS
    orders = _slice(OZON_JS, "function initColumnResizer", "function createOzonFbsModalColResizer")
    assert "if (!table || isSuppliesTab()) return;" in orders


def test_wrap_css_only_on_fbs_col_wrap() -> None:
    assert ".wb-fbs-table.fbs-col-wrap td" in CSS
    assert "overflow-wrap: anywhere" in CSS
    rule = CSS.split(".wb-fbs-table.fbs-col-wrap .wb-fbs-wh-name", 1)[1].split("}", 1)[0]
    assert "white-space: normal" in rule
