"""Ozon FBS supply-detail «Отмененные заказы» — только главному пользователю."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web_static" / "ozon_fbs.js"
HTML = ROOT / "web_templates" / "app.html"
WEB = ROOT / "review_processor" / "web.py"


def test_cancelled_orders_btn_owner_only() -> None:
    js = JS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")

    assert 'id="ozonFbsSupplyDetailCancelledBtn"' in html
    assert "openOzonFbsCancelledOrdersModal()" in html
    assert "ozon_fbs.js?v=166" in html

    assert "function _ozonFbsSyncCancelledBtn" in js
    sync_fn = js[
        js.find("function _ozonFbsSyncCancelledBtn") : js.find(
            "function _ozonFbsSyncOwnerOnlyAllCancellationsBtn"
        )
    ]
    assert "isTenantOwner" in sync_fn
    assert "btn.hidden = !can" in sync_fn

    open_fn = js[
        js.find("function openOzonFbsCancelledOrdersModal") : js.find(
            "function closeOzonFbsCancelledOrdersModal"
        )
    ]
    assert "isTenantOwner" in open_fn
    assert "только главному пользователю" in open_fn

    refresh_fn = js[
        js.find("async function refreshOzonFbsCancelledOrders") : js.find(
            "function openOzonFbsCancelledOrdersModal"
        )
    ]
    assert "isTenantOwner" in refresh_fn

    route = web[
        web.find('@app.get("/api/ozon-fbs/supplies/{supply_id}/cancelled")') : web.find(
            '@app.get("/api/ozon-fbs/cancellations/delivering")'
        )
    ]
    assert "_can_view_ozon_fbs" in route
    assert "_is_wb_fbs_tenant_owner" in route
    assert "Отмененные заказы доступны только главному пользователю" in route
