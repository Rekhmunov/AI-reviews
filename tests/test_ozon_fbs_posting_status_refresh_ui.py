"""Per-row Ozon status refresh / copy in KIZ / pick-verify modals."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web_static" / "ozon_fbs.js"
CSS = ROOT / "web_static" / "style.css"
HTML = ROOT / "web_templates" / "app.html"


def test_posting_status_refresh_ui_wired() -> None:
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")

    assert 'id="ozonFbsPostingStatusModal"' in html
    assert "closeOzonFbsPostingStatusModal()" in html
    assert 'id="ozonFbsPostingStatusCloseBtn"' in html
    assert ">Закрыть<" in html[html.find("ozonFbsPostingStatusModal") :]

    assert "function refreshOzonFbsModalPostingStatus" in js
    assert "function copyOzonFbsModalPostingNumber" in js
    assert "function closeOzonFbsPostingStatusModal" in js
    assert "function _ozonFbsRemovePostingFromOpenModals" in js
    assert "ozon-fbs-posting-status-refresh" in js
    assert "ozon-fbs-posting-copy" in js
    assert "refreshOzonFbsModalPostingStatus(" in js
    assert "copyOzonFbsModalPostingNumber(" in js
    assert "lookupPostingByNumber(pn, { refresh: true })" in js
    assert "_ozonFbsCancelledMergeIntoDetail" in js[
        js.find("async function refreshOzonFbsModalPostingStatus") : js.find(
            "function renderOzonFbsCancelledOrdersTable"
        )
    ]
    assert "window.refreshOzonFbsModalPostingStatus = refreshOzonFbsModalPostingStatus" in js
    assert "window.copyOzonFbsModalPostingNumber = copyOzonFbsModalPostingNumber" in js
    assert "window.closeOzonFbsPostingStatusModal = closeOzonFbsPostingStatusModal" in js

    col = js[
        js.find("function _ozonFbsModalPostingColHtml") : js.find("function _ozonFbsKizRowIsEmpty")
    ]
    assert "ozon-fbs-posting-status-refresh" in col
    assert "ozon-fbs-posting-copy" in col
    assert "ozon-fbs-modal-posting-actions" in col
    assert "ozon-fbs-modal-posting-id" in col
    # Copy sits left of refresh in the action cluster.
    assert col.find("ozon-fbs-posting-copy") < col.find("ozon-fbs-posting-status-refresh")

    assert ".ozon-fbs-posting-status-refresh" in css or ".ozon-fbs-posting-icon-btn" in css
    assert ".ozon-fbs-modal-posting-id" in css
    assert ".ozon-fbs-modal-posting-actions" in css
    assert ".ozon-fbs-posting-icon-btn" in css
    assert "#ozonFbsPostingStatusModal.modal-overlay" in css
    # Icon cluster sits next to posting text.
    id_css = css[css.find(".ozon-fbs-modal-posting-id {") : css.find(".ozon-fbs-modal-posting-num {")]
    assert "justify-content: flex-start;" in id_css
    assert "align-items: center;" in id_css
    assert "gap: 6px;" in id_css
    actions_css = css[
        css.find(".ozon-fbs-modal-posting-actions {") : css.find(".ozon-fbs-posting-icon-btn {")
    ]
    assert "gap: 2px;" in actions_css
    # Icon-only control: no button chrome.
    icon_css = css[css.find(".ozon-fbs-posting-icon-btn {") : css.find(
        ".ozon-fbs-posting-icon-btn:hover"
    )]
    assert "border: 0;" in icon_css
    assert "background: transparent;" in icon_css
    assert "ozon_fbs.js?v=144" in html
    assert "style.css?v=331" in html
