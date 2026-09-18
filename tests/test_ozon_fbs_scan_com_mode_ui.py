"""Ozon FBS: scan mode toggle (keyboard default / COM) for KIZ + Pick modals.

Keyboard Enter path must stay intact; COM only feeds the same process* helpers.
Ozon specifics (cargo places, local-only marking) live inside process*, not COM.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
OZON_JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")


def _block(start_id: str, end_id: str) -> str:
    start = APP_HTML.find(f'id="{start_id}"')
    end = APP_HTML.find(f'id="{end_id}"')
    assert start > 0 and end > start, (start_id, end_id, start, end)
    return APP_HTML[start:end]


def _extract_fn(src: str, signature: str) -> str:
    i = src.find(signature)
    assert i >= 0, signature
    depth = 0
    started = False
    k = i
    while k < len(src):
        ch = src[k]
        if ch == "{":
            depth += 1
            started = True
        elif ch == "}":
            depth -= 1
            if started and depth == 0:
                return src[i : k + 1]
        k += 1
    raise AssertionError(f"unclosed {signature}")


def test_kiz_and_pick_scan_bars_have_toggle_not_label() -> None:
    kiz = _block("ozonFbsKizModal", "ozonFbsKizScanPrompt")
    pick = _block("ozonFbsPickVerifyModal", "ozonFbsPickScanPrompt")
    for block, toggle_id, status_id, input_id in (
        (kiz, "ozonFbsKizScanModeToggle", "ozonFbsKizScanModeStatus", "ozonFbsKizStickerScan"),
        (pick, "ozonFbsPickScanModeToggle", "ozonFbsPickScanModeStatus", "ozonFbsPickStickerScan"),
    ):
        assert f'id="{toggle_id}"' in block
        assert 'role="switch"' in block
        assert 'aria-checked="false"' in block
        assert "onOzonFbsScanModeToggleClick(event)" in block
        assert f'id="{status_id}"' in block
        assert f'id="{input_id}"' in block
        assert ">Сканирование<" not in block
        assert "wb-fbs-kiz-scan-label" not in block
        assert "onkeydown=" in block and "onOzonFbs" in block
        assert "ContainerScan" in block


def test_import_label_untouched() -> None:
    assert 'for="ozonFbsKizImportText">Сканирование / список стикер + КИЗ<' in APP_HTML
    assert 'for="wbFbsKizRestoreScan">Сканирование<' in APP_HTML


def test_process_helpers_preserve_keyboard_enter_wrappers() -> None:
    for process_name, enter_sig in (
        ("processOzonFbsKizStickerScan", "async function onOzonFbsKizStickerScanKey"),
        ("processOzonFbsKizMarkScan", "function onOzonFbsKizMarkScanKey"),
        ("processOzonFbsPickStickerScan", "async function onOzonFbsPickStickerScanKey"),
        ("processOzonFbsPickSkuScan", "function onOzonFbsPickSkuScanKey"),
    ):
        assert f"function {process_name}" in OZON_JS
        enter = _extract_fn(OZON_JS, enter_sig)
        assert 'event.key !== "Enter"' in enter
        assert f"{process_name}(" in enter
        assert "navigator.serial" not in enter


def test_ozon_specifics_remain_inside_process_helpers() -> None:
    kiz_sticker = _extract_fn(OZON_JS, "async function processOzonFbsKizStickerScan")
    assert "_ozonFbsContainerIsScanMode" in kiz_sticker
    assert "_ozonFbsContainerHandleScan" in kiz_sticker
    kiz_mark = _extract_fn(OZON_JS, "function processOzonFbsKizMarkScan")
    assert "_ozonFbsKizScheduleLocalAutosave" in kiz_mark
    assert "_ozonFbsContainerMaybeBind" in kiz_mark
    pick_sticker = _extract_fn(OZON_JS, "async function processOzonFbsPickStickerScan")
    assert "_ozonFbsContainerIsScanMode" in pick_sticker
    assert "_ozonFbsContainerHandleScan" in pick_sticker


def test_com_module_optional_and_feeds_process_helpers() -> None:
    assert "function deliverOzonFbsComScan" in OZON_JS
    assert "function onOzonFbsScanModeToggleClick" in OZON_JS
    assert "navigator.serial" in OZON_JS
    assert "OZON_FBS_SCAN_MODE_KEY" in OZON_JS
    assert 'localStorage.getItem(OZON_FBS_SCAN_MODE_KEY) === "com"' in OZON_JS
    assert "processOzonFbsKizMarkScan(value, input)" in OZON_JS
    assert "processOzonFbsKizStickerScan(value, input)" in OZON_JS
    assert "processOzonFbsPickSkuScan(value, input)" in OZON_JS
    assert "processOzonFbsPickStickerScan(value, input)" in OZON_JS
    assert "_ozonFbsScanComOnModalOpened()" in OZON_JS
    assert "_ozonFbsScanComOnModalClosed()" in OZON_JS
    assert "function _ozonFbsScanComEmptyPortsHint" in OZON_JS
    assert "YaBrowser" in OZON_JS
    assert "requestPort({ filters: [] })" in OZON_JS
    assert "ozon_fbs_scan_input_mode_v1" in OZON_JS
    assert "wb_fbs_scan_input_mode_v1" not in OZON_JS


def test_com_fills_focused_row_fields_before_sticker_bar() -> None:
    """COM: focused row КИЗ/ШК/грузоместо → that cell; otherwise top sticker scan."""
    assert "function _ozonFbsComTryFillFocusedRowInput" in OZON_JS
    helper = _extract_fn(OZON_JS, "function _ozonFbsComTryFillFocusedRowInput")
    assert 'contains("wb-fbs-kiz-code-input")' in helper
    assert 'contains("ozon-fbs-pick-barcode-input")' in helper
    assert 'contains("ozon-fbs-container-input")' in helper
    assert "onOzonFbsContainerCellBlur" in helper
    assert "_ozonFbsPickCommitBarcode" in helper
    deliver = _extract_fn(OZON_JS, "function deliverOzonFbsComScan")
    assert "_ozonFbsComTryFillFocusedRowInput(value)" in deliver
    # Row fill is attempted inside both KIZ and Pick modal branches, before sticker fields.
    assert deliver.find("_ozonFbsComTryFillFocusedRowInput") < deliver.find("ozonFbsKizStickerScan")
    assert "ozonFbsPickStickerScan" in deliver
    pick_idx = deliver.find("_ozonFbsPickModalIsOpen()")
    assert pick_idx > 0
    pick_branch = deliver[pick_idx:]
    assert "_ozonFbsComTryFillFocusedRowInput(value)" in pick_branch
    assert pick_branch.find("_ozonFbsComTryFillFocusedRowInput") < pick_branch.find("ozonFbsPickStickerScan")


def test_scan_mode_toggle_css_reused() -> None:
    assert ".wb-fbs-scan-mode-toggle" in STYLE
    assert ".ozon-fbs-scan-bar-compact .wb-fbs-scan-mode-toggle" in STYLE


def test_com_auto_reconnect_on_link_loss() -> None:
    assert "OZON_FBS_COM_RECONNECT_MS" in OZON_JS
    assert "_ozonFbsScanComShouldStayConnected" in OZON_JS
    assert "связь потеряна — переподключение" in OZON_JS
    assert "_ozonFbsScanComReleasePort" in OZON_JS
    assert "_ozonFbsScanComBindDisconnect" in OZON_JS



def test_packaging_exemplar_com_and_keyboard_scan_wired() -> None:
    """Юрлица «Маркировка и ГТД»: COM deliver + Enter path + modal COM hooks."""
    assert 'id="ozonFbsPackagingExemplarScanModeToggle"' in APP_HTML
    assert 'id="ozonFbsPackagingExemplarScanModeStatus"' in APP_HTML
    assert "function processOzonFbsPackagingExemplarKizScan" in OZON_JS
    assert "function onOzonFbsPackagingExemplarKizKey" in OZON_JS
    assert "processOzonFbsPackagingExemplarKizScan(value)" in OZON_JS
    assert "_ozonFbsPackagingExemplarModalIsOpen()" in OZON_JS
    assert 'ozonFbsPackagingExemplarScanModeToggle' in OZON_JS
    assert 'ozonFbsPackagingExemplarScanModeStatus' in OZON_JS
    assert "void _ozonFbsScanComOnModalOpened()" in OZON_JS
    assert "onkeydown=\"onOzonFbsPackagingExemplarKizKey(event" in OZON_JS

def test_cache_bump() -> None:
    assert "ozon_fbs.js?v=185" in APP_HTML
    assert "style.css?v=393" in APP_HTML
