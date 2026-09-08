"""UI assertions for Остатки → Возврат → Восстановить данные."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")


def _receipt_block() -> str:
    start = APP_HTML.find('id="supplyStockReceiptModal"')
    end = APP_HTML.find('id="supplyStockReturnRestoreModal"')
    assert start > 0 and end > start
    return APP_HTML[start:end]


def _restore_block() -> str:
    start = APP_HTML.find('id="supplyStockReturnRestoreModal"')
    end = APP_HTML.find('id="supplyStockAdjustmentModal"')
    assert start > 0 and end > start
    return APP_HTML[start:end]


def test_restore_button_inside_receipt_modal() -> None:
    block = _receipt_block()
    assert 'id="supplyStockReceiptRestoreBtn"' in block
    assert "Восстановить данные" in block
    assert "openSupplyStockReturnRestoreModal()" in block
    assert 'hidden' in block[block.find("supplyStockReceiptRestoreBtn") :][:200]


def test_restore_modal_markup() -> None:
    block = _restore_block()
    assert 'id="supplyStockReturnRestoreModal"' in block
    assert 'id="supplyStockReturnRestoreScan"' in block
    assert 'id="supplyStockReturnRestoreResult"' in block
    assert 'id="supplyStockReturnRestoreCacheInfo"' in block
    assert 'id="supplyStockReturnRestoreTable"' in block
    assert 'id="supplyStockReturnRestoreTbody"' in block
    assert "Сканируйте стикер возврата WB или КИЗ для печати" in block
    assert "sb-sheet-modal" in block
    assert "sb-adj-modal" in block
    assert "wb-fbs-sd-table" in block
    assert ">Заказ<" in block
    assert ">Товар<" in block


def test_restore_js_wiring_no_sync() -> None:
    assert "function openSupplyStockReturnRestoreModal" in APP_JS
    assert "function closeSupplyStockReturnRestoreModal" in APP_JS
    assert "function processSupplyStockReturnRestoreScan" in APP_JS
    assert "function printStockReturnRestoreKiz" in APP_JS
    assert "function printStockReturnRestoreBarcode" in APP_JS
    assert "function _stockReturnRestoreRenderTable" in APP_JS
    assert "function onSupplyStockReceiptKindChange" in APP_JS
    assert "function _sbSyncReceiptRestoreBtn" in APP_JS
    assert "/api/wb-fbs/returns/restore/scan" in APP_JS
    assert "/api/wb-fbs/returns/restore/cache-info" in APP_JS
    assert "Распечатать ШК" in APP_JS
    assert "const canPrintBarcode = barcodes.length > 0" in APP_JS
    assert "_stockReturnRestoreBarcodes(item)" in APP_JS
    assert "Распечатать КИЗ" in APP_JS
    assert "_wbFbsReturnsPrintHtml" in APP_JS
    assert "_wbFbsReturnsDoBarcodePrint" in APP_JS
    # Restore must not trigger WB sync.
    restore_fn = APP_JS[
        APP_JS.find("function openSupplyStockReturnRestoreModal") : APP_JS.find(
            "function closeSupplyStockReturnRestoreModal"
        )
    ]
    assert "/returns/sync" not in restore_fn
    scan_fn = APP_JS[
        APP_JS.find("async function processSupplyStockReturnRestoreScan") : APP_JS.find(
            "async function printStockReturnRestoreKiz"
        )
    ]
    assert "/returns/sync" not in scan_fn
    # Failed scan must not wipe previously scanned rows.
    assert "_stockReturnRestoreClearResult()" not in scan_fn


def test_close_restore_keeps_receipt_open() -> None:
    close_fn = APP_JS[
        APP_JS.find("function closeSupplyStockReturnRestoreModal") : APP_JS.find(
            "function onSupplyStockReturnRestoreScanKey"
        )
    ]
    assert "closeSupplyStockReceiptModal" not in close_fn
    assert "supplyStockReceiptScan" in close_fn


def test_restore_styles_layering() -> None:
    assert "#supplyStockReturnRestoreModal" in STYLE
    assert "z-index: 1250" in STYLE
    assert "#wbFbsReturnsBarcodeModal" in STYLE
    assert "z-index: 1350" in STYLE
    assert ".sb-return-restore-table-wrap" in STYLE
    assert "#supplyStockReturnRestoreModal > .sb-return-restore-modal" in STYLE
    assert "height: calc(100vh - 40px)" in STYLE
    assert "#supplyStockReturnRestoreModal" in STYLE.split("Остатки modals: full-bleed sheets")[1][:2500]


def test_asset_versions_bumped() -> None:
    assert "app.js?v=571" in APP_HTML
    assert "style.css?v=323" in APP_HTML
