"""Logistics tab: rename Доверенности → Логистика, picker + TTN catalog UI/API wiring."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web_templates" / "app.html"
JS = ROOT / "web_static" / "app.js"
CSS = ROOT / "web_static" / "style.css"
WEB = ROOT / "review_processor" / "web.py"
REPO = ROOT / "review_processor" / "repository.py"


def test_nav_and_section_renamed_to_logistics() -> None:
    html = HTML.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    assert 'id="section-supplies-poa"' in html
    assert 'id="nav-supplies-poa"' in web
    assert "Логистика</a>" in web
    assert "Доверенности</a>" not in web.split("nav-supplies-poa")[1][:200]
    assert 'managerSupplyPoaHeader">Логистика<' in html
    assert '"supplies-poa": "Поставки — Логистика"' in js
    assert 'supplyParts.push("Логистика")' in js


def test_logistics_title_picker_and_panes() -> None:
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    assert 'id="logisticsTabSelect"' in html
    assert 'option value="poa" selected>Доверенности</option>' in html
    assert 'option value="ttn">ТТН</option>' in html
    assert 'id="logisticsPoaPane"' in html
    assert 'id="logisticsTtnPane"' in html
    assert 'id="createTtnModal"' in html
    assert "openCreateTtnModal()" in html
    assert "function setLogisticsTab" in js
    assert "function initLogisticsSection" in js
    assert 'section === "supplies-poa"' in js and "initLogisticsSection" in js
    assert '"logisticsTab"' in js
    assert "app.js?v=592" in html
    assert "style.css?v=339" in html
    assert "ttn-modal-card" in html
    assert "ttn-form-grid" in html
    assert 'max-width:560px' not in html.split('id="createTtnModal"')[1].split("<!-- ── Планирование")[0]


def test_ttn_table_and_modal_fields_present() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert 'id="ttnTbody"' in html
    assert "Грузополучатель" in html
    assert "Водитель / перевозчик" in html
    assert 'id="ttnCreateShipper"' in html
    assert 'id="ttnCreateShipperWrap"' in html
    assert 'id="ttnCreateConsignee"' in html
    assert 'id="ttnCreateConsigneeWrap"' in html
    assert 'id="ttnCreateDriver"' in html
    assert 'id="ttnCreateDriverWrap"' in html
    assert 'id="ttnCreateVehicle"' in html
    assert 'id="ttnCreateVehicleWrap"' in html
    assert 'id="ttnManualVehicleBtn"' in html
    assert 'id="ttnManualVehicleFields"' in html
    assert 'id="ttnCreateLoadWrap"' in html
    assert 'id="ttnCreateUnloadWrap"' in html
    assert 'id="ttnManualLoadBtn"' in html
    assert 'id="ttnManualUnloadBtn"' in html
    assert 'id="ttnManualLoadFields"' in html
    assert 'id="ttnManualUnloadFields"' in html
    assert 'id="ttnCreateLoadAddress"' in html
    assert 'id="ttnCreateUnloadAddress"' in html
    assert 'id="ttnCreateCargo"' in html
    assert "poaTbody" in html
    assert "openCreatePoAModal()" in html


def test_ttn_default_cargo_description() -> None:
    js = JS.read_text(encoding="utf-8")
    assert 'TTN_DEFAULT_CARGO = "Текстиль (постельное белье/наматрасники)"' in js
    assert 'setVal("ttnCreateCargo", TTN_DEFAULT_CARGO)' in js


def test_ttn_vehicle_manual_via_pencil() -> None:
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    assert "onclick=\"toggleTtnManualVehicle()\"" in html
    assert 'id="ttnManualVehicleFields"' in html
    assert 'display:none' in html.split('id="ttnManualVehicleFields"')[1][:80]
    assert "function toggleTtnManualVehicle" in js
    assert "function _ttnSetVehicleManualUi" in js
    assert "_ttnManualVehicleMode" in js


def test_ss_open_clears_placeholder_text() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "function ssOpen" in js
    assert "function _ssRestoreDisplay" in js
    # Empty selection must not put "— Выберите … —" into input value
    assert 'input.value = (curVal && match) ? match.label : ""' in js
    assert 'input.value = ""' in js.split("function ssOpen")[1].split("function ssFilter")[0]
    assert 'hasValue ? (label || "") : ""' in js


def test_ttn_modal_combined_parties_searchable_and_pencil() -> None:
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert "function _ttnPartyOptions" in js
    assert "le:${e.id}" in js
    assert "c:${c.id}" in js
    assert "Юр. лицо ·" in js
    assert "Контрагент ·" in js
    assert "function toggleTtnManualLoad" in js
    assert "function toggleTtnManualUnload" in js
    assert "onclick=\"toggleTtnManualLoad()\"" in html
    assert "onclick=\"toggleTtnManualUnload()\"" in html
    assert "ttnManualLoadFields" in html and 'display:none' in html.split('id="ttnManualLoadFields"')[1][:80]
    assert "ttnManualUnloadFields" in html and 'display:none' in html.split('id="ttnManualUnloadFields"')[1][:80]
    assert "onfocus=\"ssOpen('ttnCreateShipperWrap')\"" in html
    assert "oninput=\"ssFilter('ttnCreateShipperWrap')\"" in html
    assert "onfocus=\"ssOpen('ttnCreateConsigneeWrap')\"" in html
    assert "onfocus=\"ssOpen('ttnCreateDriverWrap')\"" in html
    assert "onfocus=\"ssOpen('ttnCreateVehicleWrap')\"" in html
    assert "onfocus=\"ssOpen('ttnCreateLoadWrap')\"" in html
    assert "onfocus=\"ssOpen('ttnCreateUnloadWrap')\"" in html
    assert "function _ttnPopulateVehicleOptions" in js
    assert "function _ttnDriverVehicles" in js
    assert "shipper_type" in js and "consignee_type" in js
    assert ".ss-dropdown" in css
    assert "top: 100%;" in css
    modal_css = css.split("#createTtnModal .ss-dropdown")[1][:120]
    assert "margin-top: 0" in modal_css


def test_ttn_backend_crud_and_downloads_wired() -> None:
    web = WEB.read_text(encoding="utf-8")
    repo = REPO.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS supply_ttn_records" in repo
    assert "shipper_type" in repo and "consignee_type" in repo
    assert "def list_supply_ttn_records" in repo
    assert "def create_supply_ttn_record" in repo
    assert "def update_supply_ttn_record" in repo
    assert "def delete_supply_ttn_record" in repo
    assert '"/api/supply-ttn-records"' in web
    assert '"/api/supply-ttn-records/{record_id}/pdf"' in web
    assert '"/api/supply-ttn-records/{record_id}/doc"' in web
    assert '"/api/supply-ttn-records/{record_id}/html"' in web
    assert "class CreateTtnRecordRequest" in web
    assert "shipper_type: str = \"le\"" in web
    assert "consignee_type: str = \"contractor\"" in web
    assert "def _build_ttn_catalog_html" in web
    assert "async function loadTtnRecords" in js
    assert "function renderTtnTable" in js
    assert "async function saveTtnRecord" in js
    assert "downloadTtnPdf" in js
    assert "downloadTtnDoc" in js


def test_poa_api_unchanged() -> None:
    web = WEB.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    assert '"/api/supply-poa-records"' in web
    assert "async function loadPoARecords" in js
    assert "async function savePoARecord" in js
    assert "downloadPoAPdf" in js

def test_ttn_create_modal_matches_supply_size() -> None:
    css = CSS.read_text(encoding="utf-8")
    block = css.split("#createTtnModal .ttn-modal-card")[1].split("@media")[0]
    assert "min(1440px, 100%)" in block
    assert "calc(100vh - 40px)" in block
    assert "flex-direction: column" in block


def test_ttn_load_unload_places_le_contractor_warehouse() -> None:
    js = Path(__file__).resolve().parents[1].joinpath("web_static", "app.js").read_text(encoding="utf-8")
    assert "function _ttnPlacePresetOptions" in js
    helper = js.split("function _ttnPlacePresetOptions", 1)[1].split("\nfunction ", 1)[0]
    assert "Юр. лицо ·" in helper and "Контрагент ·" in helper and "Склад ·" in helper
    assert "Производство ·" not in helper
    assert "c.requisites" not in helper
    assert "contractorAddressLine" in helper


def test_ttn_contractor_shipper_gets_one_line_address() -> None:
    """When shipper is a contractor, PDF/list must get composed address — not an empty string."""
    repo = REPO.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")
    assert "def list_supply_ttn_records" in repo
    block = repo.split("def list_supply_ttn_records", 1)[1].split("\n    def ", 1)[0]
    assert "c_s.address AS c_ship_address" in block
    assert "c_s.phone AS c_ship_phone" in block
    assert "c_s.full_name AS c_ship_full" in block
    assert "contractor_address_line" in block
    # Must not hard-wipe shipper address for contractor party type.
    assert 'd["le_address"] = ""' not in block
    assert "le_address" in web
    assert "Грузоотправитель" in web


def test_ttn_unload_warehouse_picker_for_flagged_contractor() -> None:
    """Unload-only: flagged contractor shows linked warehouse address picker."""
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    assert 'id="ttnUnloadWarehouseBlock"' in html
    assert 'id="ttnUnloadWarehouseWrap"' in html
    assert 'id="ttnUnloadWarehouse"' in html
    assert "function _ttnSyncUnloadWarehousePicker" in js
    assert "function _ttnContractorUsesWarehouseUnload" in js
    assert "function onTtnUnloadWarehouseChange" in js
    assert "ttn_unload_from_warehouses" in js
    sync = js.split("function _ttnSyncUnloadWarehousePicker", 1)[1].split("\nfunction ", 1)[0]
    assert "_ttnManualUnloadMode" in sync
    assert "_ttnWarehousesForContractor" in sync
    # Load presets must not blank contractor address for the flag.
    load_fn = js.split("function onTtnLoadPresetChange", 1)[1].split("\nfunction ", 1)[0]
    assert "UnloadWarehouse" not in load_fn
    save = js.split("async function saveTtnRecord", 1)[1].split("\nwindow.saveTtnRecord", 1)[0]
    assert "Выберите склад / адрес разгрузки контрагента" in save

