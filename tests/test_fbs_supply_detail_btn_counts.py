"""Supply-detail KIZ/pick buttons show (scanned/total) counts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "web_static" / "app.js"
OZON_JS = ROOT / "web_static" / "ozon_fbs.js"
HTML = ROOT / "web_templates" / "app.html"


def test_wb_supply_detail_btn_count_helpers() -> None:
    js = APP_JS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")

    assert 'id="wbFbsSupplyDetailKizBtn"' in html
    assert 'id="wbFbsSupplyDetailPickVerifyBtn"' in html
    assert "function _wbFbsSyncKizPickBtnLabels" in js
    assert "function _wbFbsComputeKizBtnProgress" in js
    assert "function _wbFbsComputePickBtnProgress" in js
    assert 'btn.textContent = t > 0 ? `${baseLabel} (${d}/${t})` : baseLabel' in js
    assert '_wbFbsSetSupplyActionBtnCount(\n    "wbFbsSupplyDetailKizBtn"' in js or (
        '"wbFbsSupplyDetailKizBtn"' in js
        and "Товары с КИЗ" in js[js.find("function _wbFbsSyncKizPickBtnLabels") :]
    )
    assert "_wbFbsSyncKizPickBtnLabels()" in js
    assert "_wbFbsSyncKizPickBtnLabels({ pick: pickProg })" in js
    # title must stay for wait-orders / tone-only
    sync = js[
        js.find("function _wbFbsSetSupplyActionBtnCount") : js.find(
            "function _wbFbsSyncKizPickBtnLabels"
        )
        + 800
    ]
    assert "title" not in sync or "Keep title untouched" in sync


def test_ozon_supply_detail_btn_count_helpers() -> None:
    js = OZON_JS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")

    assert 'id="ozonFbsSupplyDetailKizBtn"' in html
    assert 'id="ozonFbsSupplyDetailPickVerifyBtn"' in html
    assert "function _ozonFbsSyncKizPickBtnLabels" in js
    assert "function _ozonFbsComputeKizBtnProgress" in js
    assert "function _ozonFbsComputePickBtnProgress" in js
    assert 'btn.textContent = t > 0 ? `${baseLabel} (${d}/${t})` : baseLabel' in js
    assert "_ozonFbsSyncKizPickBtnLabels({ orders: allOrders })" in js
    assert "_ozonFbsSyncKizPickBtnLabels()" in js


def test_cache_bump_for_btn_counts() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "app.js?v=628" in html
    assert "ozon_fbs.js?v=157" in html
