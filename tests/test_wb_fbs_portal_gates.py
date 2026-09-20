"""WB FBS supply modal: «Портал ВБ» gated by KIZ (if needed) + driver, hover checklist."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_portal_btn_wrapped_with_gate_tip() -> None:
    assert 'id="wbFbsPortalGateWrap"' in HTML
    assert 'id="wbFbsPortalGateTip"' in HTML
    assert 'id="wbFbsSupplyDetailPortalBtn"' in HTML
    wrap = HTML[
        HTML.find('id="wbFbsPortalGateWrap"') : HTML.find('id="wbFbsPortalGateWrap"') + 700
    ]
    assert "wbFbsSupplyDetailPortalBtn" in wrap
    assert "wbFbsPortalGateTip" in wrap


def test_portal_gate_helpers() -> None:
    assert "function _wbFbsNeedsKizForPortal" in JS
    assert "function _wbFbsKizOkForPortal" in JS
    assert "function _wbFbsPortalGateItems" in JS
    assert "function _wbFbsRenderPortalGateTip" in JS
    assert "function _wbFbsCanOpenPortal" in JS
    assert "function _wbFbsSyncPortalBtn" in JS
    assert "Чтобы открыть портал ВБ" in JS
    assert 'label: "Товары с КИЗ"' in JS
    assert 'label: "Водитель"' in JS
    # KIZ optional when supply has no kiz_required orders.
    needs = JS[
        JS.find("function _wbFbsNeedsKizForPortal") : JS.find(
            "function _wbFbsNeedsKizForPortal"
        )
        + 400
    ]
    assert "kiz_required" in needs
    assert "_wbFbsOrderIsCancelled" in needs
    ok = JS[
        JS.find("function _wbFbsKizOkForPortal") : JS.find("function _wbFbsKizOkForPortal")
        + 350
    ]
    assert "if (!_wbFbsNeedsKizForPortal(supply)) return true" in ok
    can = JS[
        JS.find("function _wbFbsCanOpenPortal") : JS.find("function _wbFbsCanOpenPortal")
        + 450
    ]
    assert "_wbFbsDriverHasAssignment(supply)" in can
    assert "_wbFbsKizOkForPortal(supply)" in can


def test_portal_open_respects_gate() -> None:
    open_fn = JS[
        JS.find("function openWbFbsSupplyPortal") : JS.find("function openWbFbsSupplyPortal")
        + 500
    ]
    assert 'aria-disabled") === "true"' in open_fn or "aria-disabled" in open_fn
    assert "_wbFbsCanOpenPortal()" in open_fn


def test_portal_sync_hooked_from_tones() -> None:
    assert "_wbFbsSyncPortalBtn();" in JS
    # Driver + KIZ tone refresh re-evaluate the portal gate.
    assert JS.count("_wbFbsSyncPortalBtn()") >= 3
    driver_sync = JS[
        JS.find("function _wbFbsSyncDriverBtn") : JS.find("function _wbFbsSyncDriverBtn")
        + 350
    ]
    assert "_wbFbsSyncPortalBtn()" in driver_sync
    kiz_tone = JS[
        JS.find("function _wbFbsKizSplitSetTone") : JS.find("function _wbFbsKizSplitSetTone")
        + 600
    ]
    assert "_wbFbsSyncPortalBtn()" in kiz_tone


def test_ozon_gm_still_mandatory_when_binds_exist() -> None:
    """Ozon: cargo-place confirm remains required when GMs are bound."""
    oz = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
    gate = oz[
        oz.find("function _ozonFbsMoveDeliveringGateItems") : oz.find(
            "function _ozonFbsMoveDeliveringGateItems"
        )
        + 900
    ]
    assert "_ozonFbsSupplyHasGmBinds()" in gate
    assert 'label: "Подтверждение грузомест"' in gate
    can = oz[
        oz.find("function _ozonFbsCanMoveToDelivering") : oz.find(
            "function _ozonFbsCanMoveToDelivering"
        )
        + 900
    ]
    assert "_ozonFbsGmConfirmOkForMove()" in can


def test_cache_bumped() -> None:
    assert "app.js?v=683" in HTML
    assert "style.css?v=405" in HTML
    assert ".ozon-fbs-move-gate-tip" in CSS
    assert "button.wb-fbs-sd-portal-btn.is-scan-incomplete" in CSS
