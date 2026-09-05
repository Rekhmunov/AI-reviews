"""WB FBS «В доставке»: open supply detail as view-only with status tones."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "web_static" / "app.js"
APP_HTML = ROOT / "web_templates" / "app.html"
STYLE_CSS = ROOT / "web_static" / "style.css"


def _slice_fn(src: str, start_marker: str, end_marker: str) -> str:
    start = src.find(start_marker)
    assert start >= 0, f"missing {start_marker}"
    end = src.find(end_marker, start + len(start_marker))
    assert end > start, f"missing end {end_marker} after {start_marker}"
    return src[start:end]


def test_wb_delivery_supplies_are_openable() -> None:
    js = APP_JS.read_text(encoding="utf-8")
    table_fn = _slice_fn(
        js,
        "function renderWbFbsSuppliesTable(",
        "function renderWbFbsOrdersTable(",
    )
    assert 'canOpenDetail = isAssembly || wbFbsState.tab === "delivery"' in table_fn
    assert "openWbFbsSupplyDetailModal(" in table_fn
    assert "wb-fbs-supply-name is-link" in table_fn


def test_wb_delivery_detail_readonly_banner_and_ui() -> None:
    js = APP_JS.read_text(encoding="utf-8")
    html = APP_HTML.read_text(encoding="utf-8")
    css = STYLE_CSS.read_text(encoding="utf-8")

    assert "function _wbFbsIsDeliverySuppliesTab(" in js
    assert "function _wbFbsIsSupplyDetailReadOnly(" in js
    assert "function _wbFbsSyncSupplyDetailReadOnlyMode(" in js
    assert "Состав поставки изменению не подлежит — отправления уже в доставке." in js
    assert "wb-fbs-sd--readonly" in js
    assert "is-tone-only" in js
    assert "is-tone-only" in css

    render_fn = _slice_fn(
        js,
        "function renderWbFbsSupplyDetail(",
        "window.renderWbFbsSupplyDetail",
    )
    assert "_wbFbsSyncSupplyDetailReadOnlyMode(readOnly)" in render_fn
    assert "const checkCell = readOnly" in render_fn
    assert "const actCell = readOnly" in render_fn
    assert "detailColspan" in render_fn

    assert 'id="wbFbsSupplyDetailInfo"' in html
    assert "app.js?v=541" in html
    assert "style.css?v=297" in html


def test_wb_delivery_kiz_pick_tone_only_no_modal() -> None:
    js = APP_JS.read_text(encoding="utf-8")

    kiz_fn = _slice_fn(js, "async function openWbFbsKizModal(", "window.openWbFbsKizModal")
    pick_fn = _slice_fn(
        js,
        "async function openWbFbsPickVerifyModal(",
        "window.openWbFbsPickVerifyModal",
    )
    assert "if (_wbFbsIsSupplyDetailReadOnly()) return;" in kiz_fn
    assert "if (_wbFbsIsSupplyDetailReadOnly()) return;" in pick_fn

    ready_fn = _slice_fn(
        js,
        "function _wbFbsSupplyDetailSetActionsReady(",
        "function _wbFbsIsDeliverySuppliesTab(",
    )
    assert "_wbFbsSyncSupplyDetailToneOnlySplits(_wbFbsIsSupplyDetailReadOnly())" in ready_fn

    # Auto tone refresh still available in delivery (same status endpoints).
    assert "function _wbFbsAutoRefreshSplitTones(" in js
    assert "refreshWbFbsKizStatus(null, { silent: true })" in js
    assert "refreshWbFbsPickVerifyStatus(null, { silent: true })" in js


def test_wb_delivery_cargo_locked() -> None:
    js = APP_JS.read_text(encoding="utf-8")
    assert "function _wbFbsIsSupplyDetailCargoLocked(" in js
    assert "_wbFbsIsSupplyDetailCargoLocked()" in js
    create_fn = _slice_fn(
        js,
        "async function submitWbFbsCreateTrbx(",
        "window.submitWbFbsCreateTrbx",
    )
    assert "if (_wbFbsIsSupplyDetailCargoLocked()) return;" in create_fn
