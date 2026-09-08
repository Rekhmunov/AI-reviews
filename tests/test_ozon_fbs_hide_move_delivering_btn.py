"""Ozon FBS: «Перенести в доставку» only when KIZ/pick splits are green."""

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


def test_move_delivering_requires_green_kiz_and_pick() -> None:
    js = (STATIC / "ozon_fbs.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    html = (TEMPLATES / "app.html").read_text(encoding="utf-8")

    assert "function _ozonFbsCanMoveToDelivering(" in js
    assert "function _ozonFbsSyncMoveDeliveringEnabled(" in js
    assert "is-scan-incomplete" in js
    assert "is-scan-incomplete" in css
    assert 'classList.contains("is-ok")' in js
    assert "_ozonFbsKizToneFromSupply(supply) !== \"ok\"" in js
    assert "_ozonFbsPickToneFromSupply(supply) !== \"ok\"" in js
    # Wired into tone updates + action ready + click/confirm guards.
    assert "_ozonFbsSyncMoveDeliveringEnabled()" in js
    assert "if (!_ozonFbsCanMoveToDelivering())" in js
    assert "должны быть зелёными" in js
    assert "ozon_fbs.js?v=140" in html
