"""WB FBS: after move-to-delivery with stock, open seller portal tab."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_portal_url_helper_matches_portal_btn() -> None:
    assert "function _wbFbsSupplyPortalUrl" in JS
    assert "function _wbFbsOpenSupplyPortalTab" in JS
    assert (
        "https://seller.wildberries.ru/marketplace-orders-fbs/supply-detail/packaging"
        in JS
    )
    open_fn = JS[
        JS.find("function openWbFbsSupplyPortal") : JS.find("function openWbFbsSupplyPortal")
        + 700
    ]
    assert "_wbFbsOpenSupplyPortalTab(sid)" in open_fn


def test_confirm_move_opens_portal_only_with_stock() -> None:
    confirm = JS[
        JS.find("async function confirmWbFbsMoveDelivery") : JS.find(
            "window.confirmWbFbsMoveDelivery"
        )
    ]
    assert 'window.open("about:blank", "_blank")' in confirm
    assert "_wbFbsOpenSupplyPortalTab(sid, { win: portalWin })" in confirm
    assert "if (deductStock)" in confirm
    # No-stock path must not open a blank tab up front.
    assert confirm.index("if (deductStock)") < confirm.index(
        'window.open("about:blank", "_blank")'
    )


def test_confirm_copy_mentions_auto_portal_for_stock() -> None:
    open_confirm = JS[
        JS.find("function _wbFbsOpenMoveDeliveryConfirm") : JS.find(
            "function moveWbFbsSupplyToDelivery"
        )
    ]
    assert "Сразу откроется вкладка портала ВБ" in open_confirm
    assert "wantStock" in open_confirm


def test_cache_bump() -> None:
    assert "app.js?v=722" in HTML
