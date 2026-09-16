"""WB FBS supply-detail «Водитель» button and modal contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web_static" / "app.js"
CSS = ROOT / "web_static" / "style.css"
HTML = ROOT / "web_templates" / "app.html"
WEB = ROOT / "review_processor" / "web.py"
WB = ROOT / "review_processor" / "wb_fbs.py"
DRIVER_JS = ROOT / "web_static" / "ozon_fbs_driver.js"
DRIVER_HTML = ROOT / "web_templates" / "ozon_fbs_driver.html"


def test_driver_button_sits_before_portal() -> None:
    html = HTML.read_text(encoding="utf-8")
    trbx = html.index('id="wbFbsSupplyDetailTrbxBtn"')
    driver = html.index('id="wbFbsSupplyDetailDriverBtn"')
    portal = html.index('id="wbFbsSupplyDetailPortalBtn"')
    assert trbx < driver < portal
    assert ">Водитель</button>" in html
    assert 'onclick="openWbFbsDriverModal()"' in html


def test_driver_modal_matches_ozon_footprint() -> None:
    html = HTML.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert 'id="wbFbsDriverModal"' in html
    assert "wb-fbs-create-trbx-modal ozon-fbs-driver-modal" in html
    assert 'id="wbFbsDriverSelect"' in html
    assert 'id="wbFbsDriverVehicleSelect"' in html
    assert 'id="wbFbsDriverSaveBtn"' in html
    assert "onclick=\"closeWbFbsDriverModal()\"" in html
    assert "#wbFbsSupplyDetailDriverBtn.is-ok" in css
    assert "#wbFbsDriverModal.modal-overlay" in css


def test_driver_js_wires_catalog_vehicles_and_green_btn() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "function openWbFbsDriverModal" in js
    assert "function closeWbFbsDriverModal" in js
    assert "function onWbFbsDriverChange" in js
    assert "function saveWbFbsDriver" in js
    assert "function _wbFbsFillDriverVehicles" in js
    assert "function _wbFbsSyncDriverBtn" in js
    assert '"wbFbsSupplyDetailDriverBtn"' in js
    assert "/api/wb-fbs/supplies/" in js
    assert "/driver?source_id=" in js
    assert 'method: "PUT"' in js
    assert 'classList.toggle("is-ok"' in js


def test_driver_locked_in_delivery_for_non_owner() -> None:
    js = JS.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")
    wb = WB.read_text(encoding="utf-8")
    assert "function _wbFbsDriverLockedAsToneOnly" in js
    assert "function _wbFbsCanOpenDriverWhileReadOnly" in js
    assert "isTenantOwner()" in js
    assert "В «В доставке» водителя может менять только главный пользователь" in js
    assert "def supply_is_in_delivery" in wb
    assert "CREATE TABLE IF NOT EXISTS wb_fbs_supply_driver" in wb
    put = web[
        web.index('@app.put("/api/wb-fbs/supplies/{supply_id}/driver")') :
        web.index('@app.put("/api/wb-fbs/supplies/{supply_id}/driver")') + 1800
    ]
    assert "supply_is_in_delivery" in put
    assert "_is_wb_fbs_tenant_owner(user)" in put


def test_driver_api_routes_exist() -> None:
    web = WEB.read_text(encoding="utf-8")
    assert '@app.get("/api/wb-fbs/supplies/{supply_id}/driver")' in web
    assert '@app.put("/api/wb-fbs/supplies/{supply_id}/driver")' in web
    assert "_merge_driver_page_cargo_places" in web
    assert "wb_fbs_mod.list_driver_page_cargo_places" in web


def test_shared_driver_cabinet_shows_wb_items() -> None:
    driver_js = DRIVER_JS.read_text(encoding="utf-8")
    assert "Wildberries" in driver_js
    assert "Грузоместо" in driver_js
    assert "TRBX" in driver_js
    html = HTML.read_text(encoding="utf-8")
    assert 'id="wbFbsDriverPageBtn"' in html
    assert "/ozon-fbs/driver" in html
    driver_html = DRIVER_HTML.read_text(encoding="utf-8")
    assert "ozon_fbs_driver.js?v=4" in driver_html


def test_cache_bump_for_driver_modal() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "app.js?v=648" in html
    assert "style.css?v=379" in html
