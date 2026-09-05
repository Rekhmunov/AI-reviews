"""Auto green tone for «Товары с/без КИЗ» via existing status endpoints (PC + TSD)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OZON_JS = ROOT / "web_static" / "ozon_fbs.js"
APP_JS = ROOT / "web_static" / "app.js"
TSD_JS = ROOT / "web_static" / "wb_fbs_tsd.js"
APP_HTML = ROOT / "web_templates" / "app.html"
TSD_HTML = ROOT / "web_templates" / "wb_fbs_tsd.html"


def _slice_fn(src: str, start_marker: str, end_marker: str) -> str:
    start = src.find(start_marker)
    assert start >= 0, f"missing {start_marker}"
    end = src.find(end_marker, start + len(start_marker))
    assert end > start, f"missing end {end_marker} after {start_marker}"
    return src[start:end]


def test_ozon_pc_auto_refresh_split_tones() -> None:
    js = OZON_JS.read_text(encoding="utf-8")
    html = APP_HTML.read_text(encoding="utf-8")

    assert "function _ozonFbsAutoRefreshSplitTones" in js
    assert "Promise.all(tasks)" in js
    assert "if (!silent && refreshBtn)" in js
    assert "_ozonFbsStatusCooldownOk" in js
    assert "refreshOzonFbsMarkingStatus(null, { silent: true })" in js
    assert "refreshOzonFbsPickVerifyStatus(null, { silent: true })" in js
    assert "async function refreshOzonFbsMarkingStatus(event, opts)" in js
    assert "async function refreshOzonFbsPickVerifyStatus(event, opts)" in js
    assert "const silent = !!(opts && opts.silent);" in js

    open_fn = _slice_fn(
        js,
        "async function openSupplyDetailModal",
        "function _ozonFbsCancelledSetInfo",
    )
    assert "_ozonFbsAutoRefreshSplitTones()" in open_fn

    close_kiz = _slice_fn(js, "async function closeOzonFbsKizModal", "async function saveOzonFbsKizModal")
    assert "refreshOzonFbsMarkingStatus(null, { silent: true })" in close_kiz

    close_pick = _slice_fn(
        js,
        "function closeOzonFbsPickVerifyModal",
        "async function saveOzonFbsPickVerifyModal",
    )
    assert "refreshOzonFbsPickVerifyStatus(null, { silent: true })" in close_pick

    save_pick = _slice_fn(
        js,
        "async function saveOzonFbsPickVerifyModal",
        "window.initOzonFbsSection",
    )
    assert "refreshOzonFbsPickVerifyStatus(null, { silent: true })" in save_pick
    assert "statusRefreshQueued" in js

    assert "ozon_fbs.js?v=127" in html


def test_wb_pc_auto_refresh_split_tones() -> None:
    js = APP_JS.read_text(encoding="utf-8")
    html = APP_HTML.read_text(encoding="utf-8")

    assert "function _wbFbsAutoRefreshSplitTones" in js
    assert "Promise.all(tasks)" in js
    assert "_wbFbsStatusCooldownOk" in js
    assert "refreshWbFbsKizStatus(null, { silent: true })" in js
    assert "refreshWbFbsPickVerifyStatus(null, { silent: true })" in js
    assert "async function refreshWbFbsKizStatus(event, opts)" in js
    assert "async function refreshWbFbsPickVerifyStatus(event, opts)" in js

    open_fn = _slice_fn(
        js,
        "async function openWbFbsSupplyDetailModal",
        "window.openWbFbsSupplyDetailModal",
    )
    assert "_wbFbsAutoRefreshSplitTones()" in open_fn

    close_kiz = _slice_fn(js, "async function closeWbFbsKizModal", "window.closeWbFbsKizModal")
    assert "refreshWbFbsKizStatus(null, { silent: true })" in close_kiz

    close_pick = _slice_fn(
        js,
        "async function closeWbFbsPickVerifyModal",
        "window.closeWbFbsPickVerifyModal",
    )
    assert "refreshWbFbsPickVerifyStatus(null, { silent: true })" in close_pick

    save_pick = _slice_fn(
        js,
        "async function saveWbFbsPickVerifyModal",
        "window.saveWbFbsPickVerifyModal",
    )
    assert "refreshWbFbsPickVerifyStatus(null, { silent: true })" in save_pick
    assert "statusRefreshQueued" in js

    assert "app.js?v=541" in html


def test_tsd_hub_auto_refresh_tones() -> None:
    js = TSD_JS.read_text(encoding="utf-8")
    html = TSD_HTML.read_text(encoding="utf-8")

    assert "function autoRefreshHubTones" in js
    assert "Promise.all(tasks)" in js
    assert "refreshHubKizStatus(null, { silent: true })" in js
    assert "refreshHubPickStatus(null, { silent: true })" in js
    assert "async function refreshHubKizStatus(event, opts)" in js
    assert "async function refreshHubPickStatus(event, opts)" in js
    assert "autoRefreshHubTones({ kizDisabled, pickDisabled })" in js
    assert "wb_fbs_tsd.js?v=75" in html
