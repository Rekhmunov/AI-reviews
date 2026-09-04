"""Ozon FBS supply modal: hide «Перенести в доставку» on delivering supplies."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web_static"
TEMPLATES = ROOT / "web_templates"


def test_move_delivering_btn_hidden_for_delivering_supplies() -> None:
    js = (STATIC / "ozon_fbs.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    html = (TEMPLATES / "app.html").read_text(encoding="utf-8")

    assert 'id="ozonFbsSupplyDetailMoveDeliveringBtn"' in html
    assert "Перенести в доставку" in html

    assert "ozonFbsSupplyDetailMoveDeliveringBtn" in js
    assert "hideMove" in js
    assert 'postingTab || "").trim() === "delivering"' in js
    assert "isDeliveringSuppliesTab()" in js
    assert "moveBtn.hidden = hideMove" in js

    # display:inline-flex on action buttons must not override [hidden].
    assert ".wb-fbs-sd-actions > button[hidden]" in css
    block_start = css.find(".wb-fbs-sd-actions > button[hidden]")
    assert block_start > 0
    nearby = css[block_start : block_start + 420]
    assert "display: none !important" in nearby
