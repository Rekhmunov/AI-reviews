"""WB FBS supply-detail «Отмененные заказы» — только главному пользователю."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web_static" / "app.js"
HTML = ROOT / "web_templates" / "app.html"
WEB = ROOT / "review_processor" / "web.py"


def test_cancelled_orders_btn_owner_only() -> None:
    js = JS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")

    assert 'id="wbFbsSupplyDetailCancelledBtn"' in html
    assert "openWbFbsCancelledOrdersModal()" in html
    assert "app.js?v=624" in html

    assert "function _wbFbsSyncOwnerOnlyCancelledBtn" in js
    assert "_wbFbsSyncOwnerOnlyCancelledBtn()" in js

    sync_fn = js[
        js.find("function _wbFbsSyncOwnerOnlyCancelledBtn") : js.find(
            "async function initWbFbsSection"
        )
    ]
    assert "_wbFbsCanViewOwnerTabs" in sync_fn
    assert "btn.hidden = !can" in sync_fn

    open_fn = js[
        js.find("function openWbFbsCancelledOrdersModal") : js.find(
            "function closeWbFbsCancelledOrdersModal"
        )
    ]
    assert "_wbFbsCanViewOwnerTabs" in open_fn
    assert "только главному пользователю" in open_fn

    refresh_fn = js[
        js.find("async function refreshWbFbsCancelledOrders") : js.find(
            "function openWbFbsCancelledOrdersModal"
        )
    ]
    assert "_wbFbsCanViewOwnerTabs" in refresh_fn

    route = web[
        web.find('@app.get("/api/wb-fbs/supplies/{supply_id}/cancelled")') : web.find(
            '@app.put("/api/wb-fbs/supplies/{supply_id}/kiz")'
        )
    ]
    assert "_can_view_wb_fbs" in route
    assert "_is_wb_fbs_tenant_owner" in route
    assert "Отмененные заказы доступны только главному пользователю" in route
