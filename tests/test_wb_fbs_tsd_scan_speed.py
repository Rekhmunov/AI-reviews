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


def test_tsd_back_arrow_saves_without_confirm() -> None:
    js = TSD_JS.read_text(encoding="utf-8")
    start = js.find("async function leaveScanScreen")
    end = js.find("function scanProgress", start)
    assert start > 0 and end > start
    body = js[start:end]
    assert "confirm(" not in body
    assert "Закрыть без сохранения" not in js
    assert "saveKizPushAll({ silent: true })" in body
    assert "savePickLocalAll({ silent: true })" in body
    assert "hasPendingKizPush()" in body


def test_tsd_autosave_conflict_adopts_server_not_force_overwrite() -> None:
    """Concurrent PC save must not be wiped by TSD autosave force-retry."""
    js = TSD_JS.read_text(encoding="utf-8")
    kiz_start = js.find("async function saveKizLocal")
    kiz_end = js.find("async function savePickLocal", kiz_start)
    assert kiz_start > 0 and kiz_end > kiz_start
    kiz_body = js[kiz_start:kiz_end]
    assert "result.conflict" in kiz_body
    assert "force-overwrite" in kiz_body or "Do NOT force-overwrite" in kiz_body
    assert "if (!retrying) return saveKizLocal" not in kiz_body
    assert "Array.isArray(result.kiz_codes)" in kiz_body
    assert "state.baselineKizByOrder[scanId] = serverCodes.slice()" in kiz_body

    pick_start = kiz_end
    pick_end = js.find("function captureScanBaselines", pick_start)
    assert pick_end > pick_start
    pick_body = js[pick_start:pick_end]
    assert "result.conflict" in pick_body
    assert "if (!retrying) return savePickLocal" not in pick_body
    assert "Adopt server pick" in pick_body or "adopt server" in pick_body.lower()
    assert "delete state.forceSaveByOrder[pickKey]" in pick_body


def test_tsd_bulk_save_is_chunked_against_504() -> None:
    js = TSD_JS.read_text(encoding="utf-8")
    kiz_start = js.find("async function saveKizPushAll")
    kiz_end = js.find("async function savePickLocalAll", kiz_start)
    assert kiz_start > 0 and kiz_end > kiz_start
    kiz_body = js[kiz_start:kiz_end]
    assert "const CHUNK =" in kiz_body
    assert "items.slice(i, i + CHUNK)" in kiz_body
    # Conflict must adopt server + clear force, not arm overwrite of PC.
    assert 'status = "conflict"' in kiz_body
    assert "state.forceSaveByOrder[id] = true" not in kiz_body
    assert "state.baselineKizByOrder[id] = serverCodes.slice()" in kiz_body

    pick_start = kiz_end
    pick_end = js.find("function noteSessionScanned", pick_start)
    assert pick_end > pick_start
    pick_body = js[pick_start:pick_end]
    assert "const CHUNK = 40" in pick_body
    assert "items.slice(i, i + CHUNK)" in pick_body
    assert 'status = "conflict"' in pick_body
    assert "state.forceSaveByOrder[pickKey] = true" not in pick_body


def test_tsd_back_arrow_stays_on_conflict() -> None:
    js = TSD_JS.read_text(encoding="utf-8")
    start = js.find("async function leaveScanScreen")
    end = js.find("function scanProgress", start)
    assert start > 0 and end > start
    body = js[start:end]
    assert 'result.status === "conflict"' in body
    assert 'result.status === "error"' in body
    assert 'result.status === "busy"' in body


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
