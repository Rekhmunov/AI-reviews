"""Остатки: сканирование прихода/возврата — qty-модалка, без backdrop-close, confirm при закрытии."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")

BALANCES_MODAL_IDS = (
    "supplyBalancesVisibilityModal",
    "supplyStockReceiptModal",
    "supplyStockReceiptScanQtyModal",
    "supplyStockReturnRestoreModal",
    "supplyStockAdjustmentModal",
    "supplyStockAsOfModal",
    "supplyBalancesOrderModal",
    "supplyStockMovementsModal",
)


def _receipt_block() -> str:
    start = APP_HTML.find('id="supplyStockReceiptModal"')
    end = APP_HTML.find('id="supplyStockReceiptScanQtyModal"')
    assert start > 0 and end > start
    return APP_HTML[start:end]


def _qty_block() -> str:
    start = APP_HTML.find('id="supplyStockReceiptScanQtyModal"')
    end = APP_HTML.find('id="supplyStockReturnRestoreModal"')
    assert start > 0 and end > start
    return APP_HTML[start:end]


def _modal_opening(modal_id: str) -> str:
    start = APP_HTML.find(f'id="{modal_id}"')
    assert start > 0, modal_id
    return APP_HTML[start : start + 420]


def test_receipt_scan_label_removed_for_prihod_and_vozvrat() -> None:
    block = _receipt_block()
    assert "sb-receipt-scan-label" not in block
    assert ">Сканирование<" not in block
    assert 'id="supplyStockReceiptScan"' in block
    assert 'aria-label="Сканирование штрихкода или маркировки"' in block
    assert 'id="supplyStockReceiptKind"' in block
    assert 'value="receipt">Приход<' in block
    assert 'value="return">Возврат<' in block


def test_receipt_scan_qty_modal_markup() -> None:
    block = _qty_block()
    assert 'id="supplyStockReceiptScanQtyModal"' in block
    assert 'id="supplyStockReceiptScanQtyInput"' in block
    assert 'value="1"' in block
    assert "onSupplyStockReceiptScanQtyFocus(event)" in block
    assert "confirmSupplyStockReceiptScanQty()" in block
    assert "closeSupplyStockReceiptScanQtyModal()" in block
    assert ">Добавить<" in block
    assert 'aria-label="Закрыть"' in block
    assert "if(event.target===this)" not in block
    assert "event.target === this" not in block


def test_receipt_scan_qty_js_wiring() -> None:
    assert "function openSupplyStockReceiptScanQtyModal" in APP_JS
    assert "function closeSupplyStockReceiptScanQtyModal" in APP_JS
    assert "function confirmSupplyStockReceiptScanQty" in APP_JS
    assert "function onSupplyStockReceiptScanQtyFocus" in APP_JS
    assert "function _sbAddReceiptProductQty" in APP_JS
    assert "function processSupplyStockReceiptScan" in APP_JS
    assert "openSupplyStockReceiptScanQtyModal(product)" in APP_JS
    assert "_sbIncrementReceiptProductQty" not in APP_JS
    assert 'if (String(input.value) === "1") input.value = ""' in APP_JS
    assert "_sbReceiptScanQtyModalOpen()" in APP_JS
    assert "#supplyStockReceiptScanQtyModal" in STYLE
    assert "z-index: 1300" in STYLE


def test_balances_modals_no_backdrop_close() -> None:
    for mid in BALANCES_MODAL_IDS:
        opening = _modal_opening(mid)
        assert f'id="{mid}"' in opening
        assert "if(event.target===this)" not in opening
        assert "event.target === this" not in opening


def test_receipt_and_adj_confirm_on_dirty_close() -> None:
    assert "function _sbStockDocListHasEnteredQty" in APP_JS
    assert 'confirm("Уверены? Введённые количества будут потеряны.")' in APP_JS
    receipt_close = APP_JS[
        APP_JS.find("function closeSupplyStockReceiptModal") : APP_JS.find(
            "window.closeSupplyStockReceiptModal"
        )
    ]
    assert '_sbStockDocListHasEnteredQty("supplyStockReceiptList")' in receipt_close
    assert "closeSupplyStockReceiptScanQtyModal({ skipFocus: true })" in receipt_close
    adj_close = APP_JS[
        APP_JS.find("function closeSupplyStockAdjustmentModal") : APP_JS.find(
            "window.closeSupplyStockAdjustmentModal"
        )
    ]
    assert '_sbStockDocListHasEnteredQty("supplyStockAdjList")' in adj_close
    assert "closeSupplyStockReceiptModal({ force: true })" in APP_JS
    assert "closeSupplyStockAdjustmentModal({ force: true })" in APP_JS


def test_cache_bump() -> None:
    assert "style.css?v=360" in APP_HTML
    assert "app.js?v=615" in APP_HTML
