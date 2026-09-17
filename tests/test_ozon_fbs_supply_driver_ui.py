"""Ozon FBS supply-detail «Водитель» button and modal contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web_static" / "ozon_fbs.js"
CSS = ROOT / "web_static" / "style.css"
HTML = ROOT / "web_templates" / "app.html"
WEB = ROOT / "review_processor" / "web.py"
SUP = ROOT / "review_processor" / "ozon_fbs_supplies.py"


def test_driver_button_sits_after_containers() -> None:
    html = HTML.read_text(encoding="utf-8")
    # Standalone «ШК поставки» button removed — printer lives on the ID chip.
    assert 'id="ozonFbsSupplyDetailShipmentsBtn"' not in html
    assert ">ШК поставки</button>" not in html
    trbx = html.index('id="ozonFbsSupplyDetailTrbxBtn"')
    driver = html.index('id="ozonFbsSupplyDetailDriverBtn"')
    move = html.index('id="ozonFbsSupplyDetailMoveDeliveringBtn"')
    assert trbx < driver < move
    assert ">Водитель</button>" in html
    assert 'onclick="openOzonFbsDriverModal()"' in html


def test_supply_barcode_printer_on_id_chip_and_containers() -> None:
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    assert "wb-fbs-sd-chip-qr" in js
    assert "wb-fbs-sd-qr-print" in js
    assert "openOzonFbsShipmentsModal()" in js
    assert 'id="ozonFbsContainersPrintSupplyBtn"' in html
    assert "Распечатать ШК поставки" in html
    filters = html.index('class="ozon-fbs-containers-filters"')
    print_btn = html.index('id="ozonFbsContainersPrintSupplyBtn"')
    assert print_btn < filters
    assert '"ozonFbsSupplyDetailShipmentsBtn"' not in js


def test_driver_modal_matches_cargo_places_footprint() -> None:
    html = HTML.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert 'id="ozonFbsDriverModal"' in html
    assert "wb-fbs-create-trbx-modal ozon-fbs-driver-modal" in html
    assert 'id="ozonFbsDriverSelect"' in html
    assert 'id="ozonFbsDriverVehicleSelect"' in html
    assert 'id="ozonFbsDriverSaveBtn"' in html
    assert "onclick=\"closeOzonFbsDriverModal()\"" in html
    assert "Гос. номер" in html
    assert ".ozon-fbs-driver-modal" in css
    assert "min-height: min(70vh, 560px)" in css
    assert "#ozonFbsSupplyDetailDriverBtn.is-ok" in css


def test_driver_js_wires_catalog_vehicles_and_green_btn() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "function openOzonFbsDriverModal" in js
    assert "function closeOzonFbsDriverModal" in js
    assert "function onOzonFbsDriverChange" in js
    assert "function saveOzonFbsDriver" in js
    assert "function _ozonFbsFillDriverVehicles" in js
    assert "function _ozonFbsSyncDriverBtn" in js
    assert '"ozonFbsSupplyDetailDriverBtn"' in js
    assert "/driver?source_id=" in js
    assert 'method: "PUT"' in js
    assert 'classList.toggle("is-ok"' in js
    assert "Нет гос. номеров у водителя" in js


def test_driver_locked_in_delivering_for_non_owner() -> None:
    js = JS.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")
    sup = SUP.read_text(encoding="utf-8")
    assert "function _ozonFbsDriverLockedAsToneOnly" in js
    assert "function _ozonFbsCanOpenDriverWhileReadOnly" in js
    assert "_ozonFbsIsTenantOwner()" in js
    assert "В «Доставляются» водителя может менять только главный пользователь" in js
    tone = js[
        js.index("function _ozonFbsSyncSupplyDetailToneOnlySplits") :
        js.index("function _ozonFbsSyncSupplyDetailToneOnlySplits") + 1800
    ]
    assert "ozonFbsSupplyDetailDriverBtn" in tone
    assert "def supply_is_in_delivering" in sup
    assert "CREATE TABLE IF NOT EXISTS ozon_fbs_supply_driver" in sup
    put = web[
        web.index('@app.put("/api/ozon-fbs/supplies/{supply_id}/driver")') :
        web.index('@app.put("/api/ozon-fbs/supplies/{supply_id}/driver")') + 1600
    ]
    assert "supply_is_in_delivering" in put
    assert "_is_wb_fbs_tenant_owner(user)" in put
    assert "В «Доставляются» водителя может менять только главный пользователь" in put


def test_driver_api_routes_exist() -> None:
    web = WEB.read_text(encoding="utf-8")
    assert '@app.get("/api/ozon-fbs/supplies/{supply_id}/driver")' in web
    assert '@app.put("/api/ozon-fbs/supplies/{supply_id}/driver")' in web


def test_cache_bump_for_driver_modal() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "ozon_fbs.js?v=181" in html
    assert "style.css?v=385" in html
