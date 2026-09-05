"""Ozon FBS supply-detail «Товары без КИЗ» button stays green when complete."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web_static" / "ozon_fbs.js"
HTML = ROOT / "web_templates" / "app.html"
SUPPLIES = ROOT / "review_processor" / "ozon_fbs_supplies.py"


def test_pick_button_tone_persists_like_kiz() -> None:
    js = JS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    supplies = SUPPLIES.read_text(encoding="utf-8")

    assert "function _ozonFbsPickToneFromSupply" in js
    assert "function _ozonFbsPickSyncToneFromRows" in js
    assert "_ozonFbsPickSplitSetTone(_ozonFbsPickToneFromSupply(supply))" in js

    open_fn = js[js.find("async function openSupplyDetailModal") : js.find("async function openSupplyDetailModal") + 1200]
    assert '_ozonFbsPickSplitSetTone("")' in open_fn
    assert "ozonFbsPickSplit" in open_fn

    render = js[js.find("if (!needsKiz) _ozonFbsKizSplitSetTone") : js.find("if (!needsKiz) _ozonFbsKizSplitSetTone") + 500]
    assert "needsPick" in render
    assert "_ozonFbsPickToneFromSupply(supply)" in render

    assert 'd["pick_verified"] = pick_ok' in supplies
    assert "Normalize pick-verify fields" in supplies
    assert "ozon_fbs.js?v=" in html
    assert "_ozonFbsAutoRefreshSplitTones()" in js
