"""WB FBS: scan mode toggle (keyboard default / COM) for KIZ + Pick modals."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")


def _block(start_id: str, end_id: str) -> str:
    start = APP_HTML.find(f'id="{start_id}"')
    end = APP_HTML.find(f'id="{end_id}"')
    assert start > 0 and end > start, (start_id, end_id, start, end)
    return APP_HTML[start:end]


def test_kiz_and_pick_scan_bars_have_toggle_not_label() -> None:
    kiz = _block("wbFbsKizModal", "wbFbsKizScanPrompt")
    pick = _block("wbFbsPickVerifyModal", "wbFbsPickScanPrompt")
    for block, toggle_id, status_id, input_id in (
        (kiz, "wbFbsKizScanModeToggle", "wbFbsKizScanModeStatus", "wbFbsKizStickerScan"),
        (pick, "wbFbsPickScanModeToggle", "wbFbsPickScanModeStatus", "wbFbsPickStickerScan"),
    ):
        assert f'id="{toggle_id}"' in block
        assert 'role="switch"' in block
        assert 'aria-checked="false"' in block
        assert "onWbFbsScanModeToggleClick(event)" in block
        assert f'id="{status_id}"' in block
        assert f'id="{input_id}"' in block
        assert ">Сканирование<" not in block
        assert "wb-fbs-kiz-scan-label" not in block
        assert 'onkeydown="onWbFbs' in block  # keyboard Enter path kept


def test_other_scan_labels_untouched() -> None:
    # Restore / Ozon still use the old label — out of scope for this MVP.
    assert 'for="wbFbsKizRestoreScan">Сканирование<' in APP_HTML
    assert 'for="ozonFbsKizStickerScan">Сканирование<' in APP_HTML


def test_process_helpers_preserve_keyboard_enter_wrappers() -> None:
    for process_name, enter_name in (
        ("processWbFbsKizStickerScan", "onWbFbsKizStickerScanKey"),
        ("processWbFbsKizMarkScan", "onWbFbsKizMarkScanKey"),
        ("processWbFbsPickStickerScan", "onWbFbsPickStickerScanKey"),
        ("processWbFbsPickSkuScan", "onWbFbsPickSkuScanKey"),
    ):
        assert f"function {process_name}" in APP_JS
        assert f"function {enter_name}" in APP_JS
        enter = APP_JS[
            APP_JS.find(f"function {enter_name}") : APP_JS.find(f"window.{enter_name}")
        ]
        assert 'event.key !== "Enter"' in enter
        assert f"{process_name}(" in enter
        assert "navigator.serial" not in enter


def test_com_module_optional_and_feeds_process_helpers() -> None:
    assert "function deliverWbFbsComScan" in APP_JS
    assert "function onWbFbsScanModeToggleClick" in APP_JS
    assert "navigator.serial" in APP_JS
    assert "WB_FBS_SCAN_MODE_KEY" in APP_JS
    assert 'localStorage.getItem(WB_FBS_SCAN_MODE_KEY) === "com"' in APP_JS
    assert "processWbFbsKizStickerScan(value, input)" in APP_JS
    assert "processWbFbsKizMarkScan(value, input)" in APP_JS
    assert "processWbFbsPickStickerScan(value, input)" in APP_JS
    assert "processWbFbsPickSkuScan(value, input)" in APP_JS
    assert "_wbFbsScanComOnModalOpened()" in APP_JS
    assert "_wbFbsScanComOnModalClosed()" in APP_JS
    # Default preference is keyboard unless localStorage says com.
    assert '=== "com"' in APP_JS


def test_scan_mode_toggle_css() -> None:
    assert ".wb-fbs-scan-mode-toggle" in STYLE
    assert '.wb-fbs-scan-mode-toggle[aria-checked="true"]' in STYLE
    assert ".wb-fbs-scan-mode-track" in STYLE
    assert "background: #22c55e" in STYLE


def test_cache_bump() -> None:
    assert "style.css?v=360" in APP_HTML
    assert "app.js?v=615" in APP_HTML
