"""Scan/pick/GM counters turn green when filled === total."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "web_static" / "app.js"
OZON_JS = ROOT / "web_static" / "ozon_fbs.js"
GM_JS = ROOT / "web_static" / "ozon_fbs_container_bind.js"
CSS = ROOT / "web_static" / "style.css"
HTML = ROOT / "web_templates" / "app.html"


def test_wb_scan_counters_toggle_complete() -> None:
    js = APP_JS.read_text(encoding="utf-8")
    assert 'el.classList.toggle("is-complete", total > 0 && filled === total)' in js
    kiz = js[js.find("function _wbFbsKizUpdateScanCounter") : js.find("function _wbFbsKizUpdateScanCounter") + 700]
    pick = js[js.find("function _wbFbsPickUpdateScanCounter") : js.find("function _wbFbsPickUpdateScanCounter") + 500]
    assert "is-complete" in kiz and "is-complete" in pick


def test_ozon_scan_counters_toggle_complete() -> None:
    js = OZON_JS.read_text(encoding="utf-8")
    gm = GM_JS.read_text(encoding="utf-8")
    kiz = js[js.find("function _ozonFbsKizUpdateScanCounter") : js.find("function _ozonFbsKizUpdateScanCounter") + 700]
    pick = js[js.find("function _ozonFbsPickUpdateScanCounter") : js.find("function _ozonFbsPickUpdateScanCounter") + 500]
    assert "is-complete" in kiz and "is-complete" in pick
    assert 'el.classList.toggle("is-complete", total > 0 && bound === total)' in gm
    assert 'el.classList.remove("is-complete")' in gm


def test_complete_green_css_and_cache() -> None:
    css = CSS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    assert ".wb-fbs-kiz-scan-count.is-complete" in css
    assert ".ozon-fbs-container-count.is-complete" in css
    assert "color: #15803d" in css
    assert "app.js?v=540" in html
    assert "ozon_fbs.js?v=127" in html
    assert "ozon_fbs_container_bind.js?v=20" in html
    assert "style.css?v=296" in html
