"""Ozon FBS «Доставляются»: KIZ/pick tones; owner may open modals."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OZON_JS = ROOT / "web_static" / "ozon_fbs.js"
APP_HTML = ROOT / "web_templates" / "app.html"
STYLE_CSS = ROOT / "web_static" / "style.css"


def _slice_fn(src: str, start_marker: str, end_marker: str) -> str:
    start = src.find(start_marker)
    assert start >= 0, f"missing {start_marker}"
    end = src.find(end_marker, start + len(start_marker))
    assert end > start, f"missing end {end_marker} after {start_marker}"
    return src[start:end]


def test_ozon_delivering_banner_no_local_edit_hint() -> None:
    js = OZON_JS.read_text(encoding="utf-8")
    sync_fn = _slice_fn(
        js,
        "function syncSupplyDetailReadOnlyMode(",
        "function colspan(",
    )
    assert "Состав поставки изменению не подлежит — отправления уже в доставке." in sync_fn
    assert "можно заносить локально" not in sync_fn
    assert "_ozonFbsSyncSupplyDetailToneOnlySplits(_ozonFbsKizPickLockedAsToneOnly())" in sync_fn
    assert 'info.classList.add("is-warn")' in sync_fn
    assert "actions.hidden = false" in sync_fn


def test_ozon_delivering_kiz_pick_tone_only_no_modal() -> None:
    js = OZON_JS.read_text(encoding="utf-8")
    html = APP_HTML.read_text(encoding="utf-8")
    css = STYLE_CSS.read_text(encoding="utf-8")

    assert "function _ozonFbsSyncSupplyDetailToneOnlySplits(" in js
    assert "function _ozonFbsCanOpenKizPickWhileReadOnly(" in js
    assert "function _ozonFbsKizPickLockedAsToneOnly(" in js
    assert "is-tone-only" in js
    assert "is-tone-only" in css

    kiz_fn = _slice_fn(js, "async function openOzonFbsKizModal(", "window.openOzonFbsKizModal")
    pick_fn = _slice_fn(
        js,
        "async function openOzonFbsPickVerifyModal(",
        "window.openOzonFbsPickVerifyModal",
    )
    # Managers stay blocked; tenant owner may open for view/edit on delivering.
    assert "if (isSupplyDetailReadOnly() && !_ozonFbsCanOpenKizPickWhileReadOnly()) return;" in kiz_fn
    assert "if (isSupplyDetailReadOnly() && !_ozonFbsCanOpenKizPickWhileReadOnly()) return;" in pick_fn
    assert "if (isSupplyDetailReadOnly()) return;" not in kiz_fn
    assert "if (isSupplyDetailReadOnly()) return;" not in pick_fn
    assert "_ozonFbsIsTenantOwner()" in js
    assert "return _ozonFbsIsTenantOwner();" in js

    ready_fn = _slice_fn(
        js,
        "function _ozonFbsSupplyDetailSetActionsReady(",
        "function onSupplyDetailCheckboxChange(",
    )
    assert "_ozonFbsSyncSupplyDetailToneOnlySplits(_ozonFbsKizPickLockedAsToneOnly())" in ready_fn

    # Buttons still present in markup; refresh remains for tone updates.
    assert 'id="ozonFbsSupplyDetailKizBtn"' in html
    assert 'id="ozonFbsSupplyDetailPickVerifyBtn"' in html
    assert 'id="ozonFbsSupplyDetailKizRefreshBtn"' in html
    assert 'id="ozonFbsSupplyDetailPickRefreshBtn"' in html
    assert "ozon_fbs.js?v=140" in html


def test_ozon_delivering_auto_tones_still_run() -> None:
    js = OZON_JS.read_text(encoding="utf-8")
    assert "function _ozonFbsAutoRefreshSplitTones(" in js
    assert "refreshOzonFbsMarkingStatus(null, { silent: true })" in js or \
           "refreshOzonFbsKizStatus(null, { silent: true })" in js
    assert "refreshOzonFbsPickVerifyStatus(null, { silent: true })" in js
