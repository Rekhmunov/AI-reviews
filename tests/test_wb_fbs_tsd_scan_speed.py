"""TSD scan path must not block on network — parity with desktop modal autosave."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TSD_JS = ROOT / "web_static" / "wb_fbs_tsd.js"


def test_tsd_scan_enter_uses_background_autosave_not_await() -> None:
    js = TSD_JS.read_text(encoding="utf-8")
    start = js.find("async function onScanEnter")
    end = js.find("async function onRoute", start)
    assert start > 0 and end > start
    body = js[start:end]
    assert "scheduleKizLocalAutosave" in body
    assert "schedulePickLocalAutosave" in body
    assert "patchScanAfterSuccess" in body
    assert "patchScanAfterStickerMatch" in body
    assert "await saveKizLocal" not in body
    assert "await savePickLocal" not in body


def test_tsd_scan_has_incremental_patch_helpers() -> None:
    js = TSD_JS.read_text(encoding="utf-8")
    for name in (
        "scheduleKizLocalAutosave",
        "schedulePickLocalAutosave",
        "awaitLocalAutosaves",
        "captureScanBaselines",
        "patchScanCard",
        "patchScanAfterSuccess",
        "refreshScanChrome",
        "buildScanCardHtml",
    ):
        assert f"function {name}" in js


def test_tsd_explicit_save_waits_for_autosave_chain() -> None:
    js = TSD_JS.read_text(encoding="utf-8")
    kiz_start = js.find("async function saveKizPushAll")
    kiz_end = js.find("/** Explicit «Сохранить» for pick", kiz_start)
    pick_start = js.find("async function savePickLocalAll")
    pick_end = js.find("function noteSessionScanned", pick_start)
    assert kiz_start > 0 and kiz_end > kiz_start
    assert pick_start > 0 and pick_end > pick_start
    assert "await awaitLocalAutosaves()" in js[kiz_start:kiz_end]
    assert "await awaitLocalAutosaves()" in js[pick_start:pick_end]


def test_tsd_clear_kiz_uses_background_autosave() -> None:
    js = TSD_JS.read_text(encoding="utf-8")
    start = js.find("async function clearKizCodes")
    end = js.find("function syncSourceSelectVisibility", start)
    assert start > 0 and end > start
    body = js[start:end]
    assert "scheduleKizLocalAutosave" in body
    assert "await saveKizLocal" not in body
    assert "refreshScanChrome" in body


def test_tsd_gs_preserve_unchanged_in_wire_scan_input() -> None:
    js = TSD_JS.read_text(encoding="utf-8")
    start = js.find("function wireScanInput")
    end = js.find("function wireScanFooter", start)
    assert start > 0 and end > start
    body = js[start:end]
    assert "isGsKeyEvent" in body
    assert "insertGsIntoInput" in body
    assert "\\u001D" in js
    assert "\\u2194" in js
