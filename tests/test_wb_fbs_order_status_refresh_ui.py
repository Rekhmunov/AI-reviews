"""WB FBS KIZ/pick modals: copy + status refresh next to order number."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web_static" / "app.js"
CSS = ROOT / "web_static" / "style.css"
HTML = ROOT / "web_templates" / "app.html"
WB = ROOT / "review_processor" / "wb_fbs.py"
WEB = ROOT / "review_processor" / "web.py"


def test_wb_fbs_order_copy_refresh_ui_wired() -> None:
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    wb = WB.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")

    assert 'id="wbFbsOrderStatusModal"' in html
    assert "closeWbFbsOrderStatusModal()" in html
    assert 'id="wbFbsOrderStatusCloseBtn"' in html
    assert ">Закрыть<" in html[html.find("wbFbsOrderStatusModal") :]

    assert "function _wbFbsModalOrderIdHtml" in js
    assert "function copyWbFbsModalOrderNumber" in js
    assert "function refreshWbFbsModalOrderStatus" in js
    assert "function closeWbFbsOrderStatusModal" in js
    assert "function _wbFbsRemoveOrderFromOpenModals" in js
    assert "wb-fbs-order-copy" in js
    assert "wb-fbs-order-status-refresh" in js
    assert "_wbFbsLookupOrderById(oid, { refresh: true })" in js
    assert "window.copyWbFbsModalOrderNumber = copyWbFbsModalOrderNumber" in js
    assert "window.refreshWbFbsModalOrderStatus = refreshWbFbsModalOrderStatus" in js
    assert "window.closeWbFbsOrderStatusModal = closeWbFbsOrderStatusModal" in js

    # Icons sit on the order-number line in both KIZ and pick tables.
    assert js.count("${_wbFbsModalOrderIdHtml(oid)}") >= 2

    helper = js[
        js.find("function _wbFbsModalOrderIdHtml") : js.find("function renderWbFbsKizTable")
    ]
    assert "Скопировать номер заказа" in helper
    assert "Проверить статус на Wildberries" in helper
    assert helper.find("wb-fbs-order-copy") < helper.find("wb-fbs-order-status-refresh")

    assert ".wb-fbs-modal-order-id" in css
    assert ".wb-fbs-modal-order-actions" in css
    assert ".wb-fbs-order-icon-btn" in css
    assert "border: 0;" in css[css.find(".wb-fbs-order-icon-btn {") : css.find(".wb-fbs-order-icon-btn:hover")]
    assert "background: transparent;" in css[
        css.find(".wb-fbs-order-icon-btn {") : css.find(".wb-fbs-order-icon-btn:hover")
    ]
    assert "#wbFbsOrderStatusModal.modal-overlay" in css

    # Live status refresh for local hits.
    assert "refresh: bool = False" in wb[wb.find("def lookup_order_by_id") :]
    assert "refresh_order_statuses_light(" in wb[wb.find("def lookup_order_by_id") :]
    assert "refresh: bool = False" in web[web.find('"/api/wb-fbs/orders/lookup"') :]
    assert "refresh=bool(refresh)" in web[web.find('"/api/wb-fbs/orders/lookup"') :]

    assert "app.js?v=582" in html
    assert "style.css?v=333" in html
