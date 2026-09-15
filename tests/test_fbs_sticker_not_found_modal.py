"""Blocking sticker-not-found modal for WB/Ozon FBS KIZ + pick."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web_templates" / "app.html"
APP_JS = ROOT / "web_static" / "app.js"
OZON_JS = ROOT / "web_static" / "ozon_fbs.js"
CSS = ROOT / "web_static" / "style.css"


def test_modal_markup_and_khorosho_only() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert 'id="fbsStickerNotFoundModal"' in html
    assert ">Хорошо<" in html
    # Generalized dismiss; sticker-not-found remains an alias.
    assert 'onclick="dismissFbsScanAck()"' in html
    # No Esc / overlay dismiss hooks on this modal.
    block = html[html.find("fbsStickerNotFoundModal") : html.find("fbsStickerNotFoundModal") + 900]
    assert "if(event.target===this)" not in block
    assert "keydown" not in block.lower() or "dismiss" not in block.lower()


def test_js_helpers_and_gates() -> None:
    app = APP_JS.read_text(encoding="utf-8")
    oz = OZON_JS.read_text(encoding="utf-8")
    assert "function showFbsStickerNotFound" in app
    assert "function dismissFbsStickerNotFound" in app
    assert "function _fbsStickerNotFoundModalOpen" in app
    assert "function showFbsScanAck" in app
    assert "_fbsScanAckSwallowKeys" in app
    # COM blocked while open (scan-ack / legacy alias)
    assert "_fbsScanAckModalOpen()" in app or "_fbsStickerNotFoundModalOpen()" in app
    assert "_fbsScanAckModalOpen()" in oz or "_fbsStickerNotFoundModalOpen()" in oz
    # All four sticker processors still call the not-found helper
    assert app.count("showFbsStickerNotFound(") >= 2
    assert oz.count("showFbsStickerNotFound(") >= 2
    # Processors bail while modal open
    assert "processWbFbsKizStickerScan" in app
    assert "_fbsScanAckModalOpen()) return" in app or "_fbsStickerNotFoundModalOpen()) return" in app
    assert "_fbsScanAckModalOpen())" in oz or "_fbsStickerNotFoundModalOpen())" in oz


def test_cache_bumps() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "app.js?v=640" in html
    assert "ozon_fbs.js?v=169" in html
    assert "style.css?v=371" in html
    # Same card classes as RU-layout warning (identical size/format).
    assert 'class="modal-card wb-fbs-kiz-ru-layout-modal"' in html
    assert 'id="fbsStickerNotFoundTitle" class="wb-fbs-kiz-ru-layout-title"' in html
    css = CSS.read_text(encoding="utf-8")
    assert ".wb-fbs-kiz-ru-layout-modal" in css
    assert "width: min(420px, calc(100vw - 32px))" in css
    assert "#fbsStickerNotFoundModal" in css
    assert ".fbs-sticker-not-found-modal" not in css
