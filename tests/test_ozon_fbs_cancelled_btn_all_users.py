"""Ozon FBS «Отмененные заказы» available to all Ozon FBS users (not owner-only)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web_static" / "ozon_fbs.js"
HTML = ROOT / "web_templates" / "app.html"
WEB = ROOT / "review_processor" / "web.py"


def test_cancelled_orders_btn_visible_to_all_ozon_fbs_users() -> None:
    js = JS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")

    assert 'id="ozonFbsSupplyDetailCancelledBtn"' in html
    assert "openOzonFbsCancelledOrdersModal()" in html
    assert "ozon_fbs.js?v=147" in html

    assert "function _ozonFbsSyncCancelledBtn" in js
    assert "_ozonFbsSyncOwnerOnlyCancelledBtn" not in js
    sync_fn = js[
        js.find("function _ozonFbsSyncCancelledBtn") : js.find(
            "function _ozonFbsSyncOwnerOnlyAllCancellationsBtn"
        )
    ]
    assert "isTenantOwner" not in sync_fn
    assert 'btn.hidden = false' in sync_fn

    open_fn = js[
        js.find("function openOzonFbsCancelledOrdersModal") : js.find(
            "function closeOzonFbsCancelledOrdersModal"
        )
    ]
    assert "isTenantOwner" not in open_fn
    assert "только главному пользователю" not in open_fn

    route = web[
        web.find('@app.get("/api/ozon-fbs/supplies/{supply_id}/cancelled")') : web.find(
            '@app.get("/api/ozon-fbs/cancellations/delivering")'
        )
    ]
    assert "_can_view_ozon_fbs" in route
    assert "_is_wb_fbs_tenant_owner" not in route
    assert "только главному пользователю" not in route
