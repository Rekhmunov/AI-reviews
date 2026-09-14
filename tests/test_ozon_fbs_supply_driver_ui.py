"""Ozon FBS supply-detail «Водитель» button and modal contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web_static" / "ozon_fbs.js"
CSS = ROOT / "web_static" / "style.css"
HTML = ROOT / "web_templates" / "app.html"


def test_driver_button_sits_after_shipments() -> None:
    html = HTML.read_text(encoding="utf-8")
    ship = html.index('id="ozonFbsSupplyDetailShipmentsBtn"')
    driver = html.index('id="ozonFbsSupplyDetailDriverBtn"')
    move = html.index('id="ozonFbsSupplyDetailMoveDeliveringBtn"')
    assert ship < driver < move
    assert ">Водитель</button>" in html
    assert 'onclick="openOzonFbsDriverModal()"' in html


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
    assert "btn.classList.toggle(\"is-ok\"" in js
    assert "Нет гос. номеров у водителя" in js


def test_driver_api_routes_exist() -> None:
    web = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
    assert '@app.get("/api/ozon-fbs/supplies/{supply_id}/driver")' in web
    assert '@app.put("/api/ozon-fbs/supplies/{supply_id}/driver")' in web


def test_cache_bump_for_driver_modal() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "ozon_fbs.js?v=151" in html
    assert "style.css?v=363" in html
