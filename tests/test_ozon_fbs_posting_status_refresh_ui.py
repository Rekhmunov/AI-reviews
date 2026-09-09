"""Per-row Ozon status refresh in KIZ / pick-verify modals."""

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
    assert "function closeOzonFbsPostingStatusModal" in js
    assert "function _ozonFbsRemovePostingFromOpenModals" in js
    assert "ozon-fbs-posting-status-refresh" in js
    assert "refreshOzonFbsModalPostingStatus(" in js
    assert "lookupPostingByNumber(pn, { refresh: true })" in js
    assert "_ozonFbsCancelledMergeIntoDetail" in js[
        js.find("async function refreshOzonFbsModalPostingStatus") : js.find(
            "function renderOzonFbsCancelledOrdersTable"
        )
    ]
    assert "window.refreshOzonFbsModalPostingStatus = refreshOzonFbsModalPostingStatus" in js
    assert "window.closeOzonFbsPostingStatusModal = closeOzonFbsPostingStatusModal" in js

    col = js[
        js.find("function _ozonFbsModalPostingColHtml") : js.find("function _ozonFbsKizRowIsEmpty")
    ]
    assert "ozon-fbs-posting-status-refresh" in col
    assert "ozon-fbs-modal-posting-id" in col

    assert ".ozon-fbs-posting-status-refresh" in css
    assert ".ozon-fbs-modal-posting-id" in css
    assert "#ozonFbsPostingStatusModal.modal-overlay" in css
    # Icon-only control: no button chrome.
    refresh_css = css[css.find(".ozon-fbs-posting-status-refresh {") : css.find(
        ".ozon-fbs-posting-status-refresh:hover"
    )]
    assert "border: 0;" in refresh_css
    assert "background: transparent;" in refresh_css
    assert "ozon_fbs.js?v=143" in html
    assert "style.css?v=328" in html
