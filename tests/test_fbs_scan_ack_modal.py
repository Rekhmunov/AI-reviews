"""Shared blocking scan-ack modal for WB/Ozon FBS KIZ + pick errors."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web_templates" / "app.html"
APP_JS = ROOT / "web_static" / "app.js"
OZON_JS = ROOT / "web_static" / "ozon_fbs.js"


def test_shared_ack_helpers() -> None:
    app = APP_JS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    assert "function showFbsScanAck" in app
    assert "function dismissFbsScanAck" in app
    assert "function _fbsScanAckModalOpen" in app
    assert "_fbsScanAckSwallowKeys" in app
    assert 'onclick="dismissFbsScanAck()"' in html
    assert ">Хорошо<" in html
    # Sticker-not-found remains a thin wrapper with fixed title.
    assert 'title: "Код не найден"' in app
    assert "function showFbsStickerNotFound" in app
    assert "function _fbsStickerNotFoundModalOpen" in app


def test_wb_scan_error_ack_call_sites() -> None:
    app = APP_JS.read_text(encoding="utf-8")
    # Reject-replace + ambiguous + mark mismatch/dup/qty + pick mismatch/already-verified
    assert app.count("showFbsScanAck(") >= 8
    for fn in (
        "processWbFbsKizStickerScan",
        "processWbFbsKizMarkScan",
        "processWbFbsPickStickerScan",
        "processWbFbsPickSkuScan",
    ):
        assert fn in app
        assert "_fbsScanAckModalOpen()) return" in app
    assert "_fbsScanAckModalOpen()" in app  # COM gate


def test_ozon_scan_error_ack_call_sites() -> None:
    oz = OZON_JS.read_text(encoding="utf-8")
    assert oz.count("showFbsScanAck(") >= 8
    assert "_fbsScanAckModalOpen()" in oz
    # Cancelled / ambiguous / mismatch / dup / qty + pick paths
    assert "отменено — КИЗ менять нельзя" in oz
    # TSD/import must not gain this desktop ack family.
    tsd = (ROOT / "web_static" / "wb_fbs_tsd.js").read_text(encoding="utf-8")
    assert "showFbsScanAck" not in tsd
    assert "fbsStickerNotFoundModal" not in tsd


def test_cache_bumps() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "app.js?v=667" in html
    assert "ozon_fbs.js?v=183" in html


def test_ozon_ack_refocuses_sticker_after_closed_prompt() -> None:
    oz = OZON_JS.read_text(encoding="utf-8")
    # Cancelled mark / failed pick SKU close the prompt — ack must not refocus hidden field.
    assert 'getElementById("ozonFbsKizStickerScan")' in oz
    assert 'getElementById("ozonFbsPickStickerScan")' in oz
    assert "showFbsScanAck(msg, sticker || input)" in oz
