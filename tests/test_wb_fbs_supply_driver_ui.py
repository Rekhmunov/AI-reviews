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
    open_fn = js.split("async function openWbFbsDriverModal", 1)[1].split(
        "\nasync function ", 1
    )[0]
    # Delivery: operators are blocked from opening (owner-only).
    assert 'alert("В «В доставке» водителя может менять только главный пользователь")' in open_fn
    assert "_wbFbsDriverLockedAsToneOnly()" in open_fn.split("alert(", 1)[0]
    assert "Дождитесь загрузки заказов" in open_fn
    assert "def supply_is_in_delivery" in wb
    assert "CREATE TABLE IF NOT EXISTS wb_fbs_supply_driver" in wb
    put = web[
        web.index('@app.put("/api/wb-fbs/supplies/{supply_id}/driver")') :
        web.index('@app.put("/api/wb-fbs/supplies/{supply_id}/driver")') + 2200
    ]
    assert 'posting_tab == "assembly"' in put
    assert "in_delivery = False" in put
    assert "_is_wb_fbs_tenant_owner(user)" in put


def test_driver_assembly_uses_opened_tab_snapshot() -> None:
    """Assembly open must not inherit delivery lock from live list tab / leftover DB rows."""
    js = JS.read_text(encoding="utf-8")
    assert "openedTab" in js
    assert "wbFbsDetailState.openedTab" in js
    is_delivery = js.split("function _wbFbsIsDeliverySuppliesTab", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert 'opened === "delivery"' in is_delivery or 'openedTab' in is_delivery
    open_detail = js.split("async function openWbFbsSupplyDetailModal", 1)[1].split(
        "\nasync function ", 1
    )[0]
    assert "openedTab" in open_detail
    sync = js.split("function _wbFbsSyncDriverBtn", 1)[1].split("\nfunction ", 1)[0]
    assert "is-tone-only" in sync
    assert "_wbFbsDriverLockedAsToneOnly()" in sync
    save = js.split("async function saveWbFbsDriver", 1)[1].split("\nasync function ", 1)[0]
    assert "openedTab" in save


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
    assert "openOzonFbsDriverPage()" in html
    driver_html = DRIVER_HTML.read_text(encoding="utf-8")
    assert "ozon_fbs_driver.js?v=11" in driver_html


def test_wb_driver_modal_lives_in_wb_section_not_ozon() -> None:
    """WB driver overlay must not sit under hidden Ozon section (display:none parent)."""
    html = HTML.read_text(encoding="utf-8")
    wb_s = html.index('id="section-supplies-wb-fbs"')
    wb_e = html.index("</section>", wb_s)
    oz_s = html.index('id="section-supplies-ozon-fbs"')
    oz_e = html.index("</section>", oz_s)
    wb_modal = html.index('id="wbFbsDriverModal"')
    oz_modal = html.index('id="ozonFbsDriverModal"')
    assert wb_s < wb_modal < wb_e
    assert oz_s < oz_modal < oz_e
    assert not (oz_s < wb_modal < oz_e)
    assert html.count('id="wbFbsDriverModal"') == 1
    assert html.count('id="ozonFbsDriverModal"') == 1
    # Shared driver cabinet entry points stay wired.
    assert 'id="wbFbsDriverPageBtn"' in html
    assert 'id="ozonFbsDriverPageBtn"' in html
    assert "openOzonFbsDriverPage()" in html


def test_cache_bump_for_driver_modal() -> None:
    html = HTML.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    assert "app.js?v=683" in html
    assert "style.css?v=405" in html
    assert "#wbFbsDriverModal," in css or "#wbFbsDriverModal" in css
    assert "#wbFbsDriverModal," in css
    assert "z-index: 1450" in css
    assert "#wbFbsDriverModal.modal-overlay.is-opening" in css
    assert "pointer-events: none" in css.split("#wbFbsDriverModal.modal-overlay.is-opening", 1)[1][:200]
    assert "_WB_FBS_DRIVER_OPEN_GUARD_MS" in js
    assert "wbFbsDriverModalState.openedAt" in js
    assert "overlayPointerDown" in js
    assert "function onWbFbsDriverOverlayPointer" in js
    assert 'onmousedown="onWbFbsDriverOverlayPointer(event)"' in html
    assert 'onclick="onWbFbsDriverOverlayPointer(event)"' in html
    assert "is-opening" in js
    close_fn = js.split("function closeWbFbsDriverModal", 1)[1].split(
        "\nwindow.closeWbFbsDriverModal", 1
    )[0]
    assert "_WB_FBS_DRIVER_OPEN_GUARD_MS" in close_fn
    assert "openedAt" in close_fn
