"""UI assertions: WB FBS KIZ / pick filter facet counts (parity with Ozon)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")


def _between(src: str, start: str, end: str) -> str:
    a = src.find(start)
    b = src.find(end, a + 1) if a >= 0 else -1
    assert a >= 0 and b > a, f"block not found: {start!r} .. {end!r}"
    return src[a:b]


def test_wb_kiz_filter_count_spans_in_html() -> None:
    block = _between(APP_HTML, 'id="wbFbsKizModal"', 'id="wbFbsPickVerifyModal"')
    for el_id in (
        "wbFbsKizFilterFilledCount",
        "wbFbsKizFilterEmptyCount",
        "wbFbsKizFilterErrorsCount",
        "wbFbsKizFilterCancelledCount",
    ):
        assert f'id="{el_id}"' in block
        assert "wb-fbs-kiz-filter-count" in block[block.find(el_id) - 40 : block.find(el_id) + 80]
    assert "Юр. лица" not in block


def test_wb_pick_filter_count_spans_in_html() -> None:
    block = _between(APP_HTML, 'id="wbFbsPickVerifyModal"', 'id="ozonFbsKizModal"')
    for el_id in (
        "wbFbsPickFilterFilledCount",
        "wbFbsPickFilterEmptyCount",
        "wbFbsPickFilterErrorsCount",
        "wbFbsPickFilterCancelledCount",
    ):
        assert f'id="{el_id}"' in block


def test_wb_filter_count_js_helpers() -> None:
    assert "function _wbFbsSetFilterCount" in APP_JS
    assert "function _wbFbsKizUpdateFilterCounts" in APP_JS
    assert "function _wbFbsPickUpdateFilterCounts" in APP_JS
    assert "function _wbFbsPickRowIsComplete" in APP_JS
    assert "По текущему поиску:" in APP_JS[
        APP_JS.find("function _wbFbsSetFilterCount") : APP_JS.find(
            "function _wbFbsKizUpdateFilterCounts"
        )
    ]
    kiz_update = APP_JS[
        APP_JS.find("function _wbFbsKizUpdateFilterCounts") : APP_JS.find(
            "function _wbFbsPickRowIsComplete"
        )
    ]
    assert "_wbFbsKizRowMatchesSearch" in kiz_update
    assert "_wbFbsKizRowIsEmpty" in kiz_update
    assert "wbFbsKizFilterFilledCount" in kiz_update
    assert "wbFbsKizFilterEmptyCount" in kiz_update
    assert "wbFbsKizFilterErrorsCount" in kiz_update
    assert "wbFbsKizFilterCancelledCount" in kiz_update
    # Facets must ignore other checkboxes (search-scoped only).
    assert "wbFbsKizFilterFilled" not in kiz_update.split("wbFbsKizFilterFilledCount")[0]


def test_wb_render_calls_update_filter_counts() -> None:
    kiz_render = APP_JS[
        APP_JS.find("function renderWbFbsKizTable") : APP_JS.find(
            "function renderWbFbsKizTable"
        )
        + 1800
    ]
    assert "_wbFbsKizUpdateFilterCounts()" in kiz_render
    pick_render = APP_JS[
        APP_JS.find("function renderWbFbsPickVerifyTable") : APP_JS.find(
            "function renderWbFbsPickVerifyTable"
        )
        + 1200
    ]
    assert "_wbFbsPickUpdateFilterCounts()" in pick_render
    assert "_wbFbsPickRowIsComplete(r)" in pick_render


def test_filter_count_css_shared_with_ozon() -> None:
    assert ".wb-fbs-kiz-filter-count" in STYLE
    assert 'class="wb-fbs-kiz-filter-count"' in APP_HTML
    assert "ozonFbsKizFilterFilledCount" in APP_HTML


def test_asset_version_bumped() -> None:
    assert "app.js?v=578" in APP_HTML
