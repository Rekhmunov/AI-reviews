"""Ozon FBS: green «Грузоместа», move-delivering gates (GM + driver), hover checklist."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
BIND = (ROOT / "web_static" / "ozon_fbs_container_bind.js").read_text(encoding="utf-8")
CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_containers_btn_turns_green_when_all_bound_confirmed() -> None:
    assert "function _ozonFbsContainersAllConfirmed" in JS
    assert "function _ozonFbsContainerCompositionConfirmed" in JS
    assert "function _ozonFbsSyncContainersBtn" in JS
    assert 'btn.classList.toggle("is-ok", _ozonFbsContainersAllConfirmed())' in JS
    assert "can_approve === true" in JS
    assert '"approved"' in JS
    assert "#ozonFbsSupplyDetailTrbxBtn.is-ok" in CSS
    assert "window._ozonFbsOnContainersLoaded = _ozonFbsOnContainersLoaded" in JS
    assert "window._ozonFbsOnContainersLoaded" in BIND


def test_move_delivering_requires_gm_confirm_and_driver() -> None:
    can = JS[
        JS.find("function _ozonFbsCanMoveToDelivering") : JS.find(
            "function _ozonFbsCanMoveToDelivering"
        )
        + 1200
    ]
    assert "_ozonFbsGmConfirmOkForMove()" in can
    assert "_ozonFbsDriverHasAssignment(supply)" in can
    assert "_ozonFbsKizToneFromSupply" in can
    assert "_ozonFbsPickToneFromSupply" in can
    assert "_ozonFbsIsTenantOwner()" in can
    assert "function _ozonFbsGmConfirmOkForMove" in JS
    assert "_ozonFbsSupplyHasGmBinds()" in JS


def test_move_delivering_hover_checklist() -> None:
    assert 'id="ozonFbsMoveDeliveringGateWrap"' in HTML
    assert 'id="ozonFbsMoveDeliveringGateTip"' in HTML
    assert "function _ozonFbsMoveDeliveringGateItems" in JS
    assert "function _ozonFbsRenderMoveDeliveringGateTip" in JS
    assert "Подтверждение грузомест" in JS
    assert "Сканирование товаров с КИЗ" in JS
    assert "Сканирование товаров без КИЗ" in JS
    assert "Водитель выбран" in JS
    assert ".ozon-fbs-move-gate-tip" in CSS
    assert ".ozon-fbs-move-gate-list" in CSS
    # GM checklist row only when binds exist.
    gate = JS[
        JS.find("function _ozonFbsMoveDeliveringGateItems") : JS.find(
            "function _ozonFbsMoveDeliveringGateItems"
        )
        + 900
    ]
    assert "_ozonFbsSupplyHasGmBinds()" in gate
    assert 'label: "Подтверждение грузомест"' in gate
    # Driver save re-evaluates the gate (right after green driver btn sync).
    assert "_ozonFbsSyncDriverBtn();\n      _ozonFbsSyncMoveDeliveringEnabled();" in JS


def test_asset_cache_bumped() -> None:
    assert "ozon_fbs.js?v=186" in HTML
    assert "ozon_fbs_container_bind.js?v=37" in HTML
    assert "style.css?v=401" in HTML
    assert "display: none" in CSS[
        CSS.find(".ozon-fbs-move-gate-tip {") : CSS.find(".ozon-fbs-move-gate-tip {") + 220
    ]
