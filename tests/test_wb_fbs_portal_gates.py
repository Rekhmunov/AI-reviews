"""WB FBS supply modal: «Портал ВБ» gated by KIZ/pick (if needed) + driver."""

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
    assert "function _wbFbsNeedsPickForPortal" in JS
    assert "function _wbFbsPickOkForPortal" in JS
    assert "function _wbFbsPortalGateItems" in JS
    assert "function _wbFbsRenderPortalGateTip" in JS
    assert "function _wbFbsCanOpenPortal" in JS
    assert "function _wbFbsSyncPortalBtn" in JS
    assert "Чтобы открыть портал ВБ" in JS
    assert 'label: "Товары с КИЗ"' in JS
    assert 'label: "Товары без КИЗ"' in JS
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
    # Pick optional when supply has no plain (non-KIZ) active orders.
    needs_pick = JS[
        JS.find("function _wbFbsNeedsPickForPortal") : JS.find(
            "function _wbFbsNeedsPickForPortal"
        )
        + 400
    ]
    assert "!o.kiz_required" in needs_pick
    assert "_wbFbsOrderIsCancelled" in needs_pick
    pick_ok = JS[
        JS.find("function _wbFbsPickOkForPortal") : JS.find(
            "function _wbFbsPickOkForPortal"
        )
        + 350
    ]
    assert "if (!_wbFbsNeedsPickForPortal(supply)) return true" in pick_ok
    assert "wbFbsPickSplit" in pick_ok
    items = JS[
        JS.find("function _wbFbsPortalGateItems") : JS.find(
            "function _wbFbsRenderPortalGateTip"
        )
    ]
    assert "_wbFbsNeedsPickForPortal(supply)" in items
    assert 'key: "pick"' in items
    # Checklist order: KIZ → pick → driver.
    assert items.find('key: "kiz"') < items.find('key: "pick"')
    assert items.find('key: "pick"') < items.find('key: "driver"')
    can = JS[
        JS.find("function _wbFbsCanOpenPortal") : JS.find("function _wbFbsCanOpenPortal")
        + 500
    ]
    assert "_wbFbsDriverHasAssignment(supply)" in can
    assert "_wbFbsKizOkForPortal(supply)" in can
    assert "_wbFbsPickOkForPortal(supply)" in can


def test_portal_open_respects_gate() -> None:
    open_fn = JS[
        JS.find("function openWbFbsSupplyPortal") : JS.find("function openWbFbsSupplyPortal")
        + 500
    ]
    assert 'aria-disabled") === "true"' in open_fn or "aria-disabled" in open_fn
    assert "_wbFbsCanOpenPortal()" in open_fn


def test_portal_sync_hooked_from_tones() -> None:
    assert "_wbFbsSyncPortalBtn();" in JS
    # Driver + KIZ + pick tone refresh re-evaluate the portal gate.
    assert JS.count("_wbFbsSyncPortalBtn()") >= 4
    driver_at = JS.find("function _wbFbsSyncDriverBtn")
    driver_sync = JS[driver_at : JS.find("\nfunction ", driver_at + 1)]
    assert "_wbFbsSyncPortalBtn()" in driver_sync
    kiz_at = JS.find("function _wbFbsKizSplitSetTone")
    kiz_tone = JS[kiz_at : JS.find("\nfunction ", kiz_at + 1)]
    assert "_wbFbsSyncPortalBtn()" in kiz_tone
    pick_at = JS.find("function _wbFbsPickSplitSetTone")
    pick_tone = JS[pick_at : JS.find("\nfunction ", pick_at + 1)]
    assert "_wbFbsSyncPortalBtn()" in pick_tone


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
    assert "app.js?v=710" in HTML
    assert "style.css?v=423" in HTML
    assert ".ozon-fbs-move-gate-tip" in CSS
    assert "button.wb-fbs-sd-portal-btn.is-scan-incomplete" in CSS
