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
    assert 'option value="ttn">ТН</option>' in html
    assert 'id="logisticsPoaPane"' in html
    assert 'id="logisticsTtnPane"' in html
    assert 'id="createTtnModal"' in html
    assert "openCreateTtnModal()" in html
    assert "+ Создать ТН" in html
    assert "function setLogisticsTab" in js
    assert "function initLogisticsSection" in js
    assert 'section === "supplies-poa"' in js and "initLogisticsSection" in js
    assert '"logisticsTab"' in js
    assert "app.js?v=674" in html
    assert "style.css?v=399" in html
    assert "ttn-modal-card" in html
    assert "ttn-form-grid" in html
    assert 'max-width:560px' not in html.split('id="createTtnModal"')[1].split("<!-- ── Планирование")[0]


def test_ttn_row_actions_print_and_kebab_menu() -> None:
    """Actions column: printer + ⋮ menu with PDF/Word/Edit/Copy/Delete labels."""
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    render = js.split("function renderTtnTable", 1)[1].split("\nfunction ", 1)[0]
    assert "ttn-row-actions" in render
    assert "printTtnRecord" in render
    assert "toggleTtnRowMenu" in render
    assert "ttn-row-menu-btn" in render
    assert "Скачать PDF" in render
    assert "Скачать Word" in render
    assert "Изменить" in render
    assert "Копировать" in render
    assert "Удалить" in render
    # Only print stays outside the menu; PDF/DOC are menu items.
    assert 'title="Печать"' in render
    assert "downloadTtnPdf" in render
    assert "downloadTtnDoc" in render
    assert "openEditTtnModal" in render
    assert "openCopyTtnModal" in render
    assert "deleteTtnRecord" in render
    assert "function toggleTtnRowMenu" in js
    assert "function _ttnCloseRowMenus" in js
    assert ".ttn-row-menu" in css
    assert ".ttn-row-menu-item" in css
    assert ".ttn-row-menu.open" in css


def test_ttn_row_colors_by_fbs_origin() -> None:
    """Ozon FBS → soft blue; WB FBS → soft purple; logistics/copy → default."""
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    render = js.split("function renderTtnTable", 1)[1].split("\nfunction ", 1)[0]
    assert "fbs_platform" in render
    assert "ttn-row-from-ozon" in render
    assert "ttn-row-from-wb" in render
    assert ".ttn-row-from-ozon" in css
    assert ".ttn-row-from-wb" in css
    ozon_rule = css.split("#ttnTable tbody tr.ttn-row-from-ozon td", 1)[1].split("}", 1)[0]
    wb_rule = css.split("#ttnTable tbody tr.ttn-row-from-wb td", 1)[1].split("}", 1)[0]
    ozon_hover = css.split("#ttnTable tbody tr.ttn-row-from-ozon:hover td", 1)[1].split("}", 1)[0]
    wb_hover = css.split("#ttnTable tbody tr.ttn-row-from-wb:hover td", 1)[1].split("}", 1)[0]
    assert "#bfdbfe" in ozon_rule
    assert "#ddd6fe" in wb_rule
    assert "#93c5fd" in ozon_hover
    assert "#c4b5fd" in wb_hover
    open_modal = js.split("async function _openTtnModal", 1)[1].split(
        "async function openCreateTtnModal", 1
    )[0]
    assert 'mode === "copy"' in js
    assert "_ttnSelectedFbsMeta = null" in js
    state_from = js.split("function _ttnStateFromRecord", 1)[1].split("\nfunction ", 1)[0]
    assert 'mode === "copy"' in state_from
    assert "fbsMeta = null" in state_from
    assert "app.js?v=674" in html
    assert "style.css?v=399" in html


def test_ttn_table_columns_resizable_with_persistence() -> None:
    """Logistics → ТН table: drag handles + localStorage column widths."""
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert 'id="ttnTable"' in html
    assert 'id="ttnColgroup"' in html
    assert 'class="col-resize-handle"' in html.split('id="ttnTable"', 1)[1].split("tbody", 1)[0]
    assert "function initTtnColumnResizer" in js
    assert "logistics_ttn_col_widths_v2" in js
    assert "initTtnColumnResizer()" in js.split("function setLogisticsTab", 1)[1].split("\nfunction ", 1)[0]
    assert "#ttnTable th .col-resize-handle" in css
    assert "box-shadow: none !important" in css.split(".ttn-row-menu-item", 1)[1][:500]


def test_ttn_table_and_modal_fields_present() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert 'id="ttnTbody"' in html
    assert "Грузополучатель" in html
    assert "Водитель / перевозчик" in html
    assert 'id="ttnCreateTitle"' in html
    assert "Название" in html.split('id="ttnTable"', 1)[1].split("tbody", 1)[0]
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
    assert 'TTN_DEFAULT_CARGO = "Постельное белье/наматрасник"' in js
    assert "TTN_DEFAULT_CARGO" in js.split("function _ttnApplyFormState", 1)[1].split(
        "\nfunction ", 1
    )[0] or "TTN_DEFAULT_CARGO" in js.split("async function _ttnApplyFormState", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "_ttnSetCargoValue" in js
    assert 'TTN_DEFAULT_DOCS = "УПД/ТОРГ-12/Электронная накладная"' in js
    assert "TTN_DEFAULT_DOCS" in js


def test_ttn_loader_receiver_autofill_from_parties() -> None:
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    assert "function _ttnPartyShortName" in js
    assert "function _ttnSyncLoaderFromShipper" in js
    assert "function _ttnSyncReceiverFromConsignee" in js
    shipper_fn = js.split("function onTtnShipperChange", 1)[1].split("\nfunction ", 1)[0]
    consignee_fn = js.split("function onTtnConsigneeChange", 1)[1].split("\nfunction ", 1)[0]
    assert "_ttnSyncLoaderFromShipper()" in shipper_fn
    assert "_ttnSyncReceiverFromConsignee()" in consignee_fn
    assert "По умолчанию — грузоотправитель" in html
    assert "По умолчанию — грузополучатель" in html
    # Autofill alone must not force-open optional block.
    optional_fn = js.split("function _ttnOptionalFieldsFilled", 1)[1].split("\nfunction ", 1)[0]
    assert "ttnCreateLoaderName" not in optional_fn
    assert "ttnCreateReceiverName" not in optional_fn


def test_ttn_packing_type_select() -> None:
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    packing = html.split('id="ttnCreatePacking"', 1)[1].split("</select>", 1)[0]
    assert 'id="ttnCreatePacking"' in html
    assert "<select" in html.split('for="ttnCreatePacking"', 1)[1][:400]
    assert 'value="Короба">Короба<' in packing
    assert 'value="Паллеты">Паллеты<' in packing
    assert 'value="Рулоны">Рулоны<' in packing
    assert 'TTN_PACKING_OPTIONS = ["Короба", "Паллеты", "Рулоны"]' in js
    assert "function _ttnSetPackingValue" in js
    assert "function toggleTtnManualPacking" in js
    assert "function _ttnPackingTypeValue" in js
    assert 'id="ttnManualPackingFields"' in html
    assert 'id="ttnCreatePackingManual"' in html
    assert "onclick=\"toggleTtnManualPacking()\"" in html
    assert "шаблон не меняется" in html
    assert '_ttnSetPackingValue("")' in js
    assert "packing_type" in js.split("function _ttnStateFromRecord", 1)[1].split("\nfunction ", 1)[0] or \
        "packing" in js.split("function _ttnStateFromRecord", 1)[1].split("\nfunction ", 1)[0]
    assert "packing_type:" in js.split("function _ttnBuildPayloadFromState", 1)[1].split("\nfunction ", 1)[0]
    assert "select.ttn-input" in CSS.read_text(encoding="utf-8")
    assert ".ttn-packing-select-wrap" in CSS.read_text(encoding="utf-8")




def test_ttn_cargo_select_with_manual() -> None:
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    cargo = html.split('id="ttnCreateCargo"', 1)[1].split("</select>", 1)[0]
    assert 'value="Постельное белье/наматрасник"' in cargo
    assert 'value="Стеганное полотно"' in cargo
    assert 'value="Ткань"' in cargo
    assert 'value="Фурнитура"' in cargo
    # Alphabetical order in options list.
    assert 'TTN_CARGO_OPTIONS = [' in js
    assert '"Постельное белье/наматрасник"' in js
    assert '"Стеганное полотно"' in js
    assert '"Ткань"' in js
    assert '"Фурнитура"' in js
    assert "function toggleTtnManualCargo" in js
    assert "function _ttnCargoDescriptionValue" in js
    assert 'id="ttnManualCargoFields"' in html
    assert "onclick=\"toggleTtnManualCargo()\"" in html
    assert "cargo_description:" in js.split("function _ttnBuildPayloadFromState", 1)[1].split("\nfunction ", 1)[0]
    assert ".ttn-cargo-select-wrap" in CSS.read_text(encoding="utf-8")
    # Default cargo is first preset (alphabetically first bedding item).
    assert 'TTN_DEFAULT_CARGO = "Постельное белье/наматрасник"' in js

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
    block = css.split("#createTtnModal .ttn-modal-card")[1].split("#createTtnModal .ttn-modal-header")[0]
    assert "min(1440px, calc(100vw - 40px))" in block
    assert "calc(100vh - 40px)" in block
    assert "flex-direction: column" in block
    assert "!important" in block


def test_ttn_create_modal_form_fills_width() -> None:
    """Form grid and inputs must span the full modal — no left-biased width caps."""
    css = CSS.read_text(encoding="utf-8")
    grid = css.split("#createTtnModal .ttn-form-grid")[1].split("}", 1)[0]
    assert "width: 100%" in grid
    assert "max-width: none" in grid
    assert "max-width: 1100px" not in grid
    assert "max-width: 940px" not in css.split("#createTtnModal.modal-overlay")[1].split("@media (max-width: 900px)")[0]
    inputs = css.split("#createTtnModal .ttn-input,")[1].split("}", 1)[0]
    assert "width: 100% !important" in inputs
    wraps = css.split("#createTtnModal .ss-wrap,")[1].split("}", 1)[0]
    assert "width: 100% !important" in wraps


def test_ttn_load_unload_places_from_party_addresses() -> None:
    """Load/unload dropdowns list addresses of selected shipper/consignee (+ linked warehouses)."""
    js = Path(__file__).resolve().parents[1].joinpath("web_static", "app.js").read_text(encoding="utf-8")
    assert "function _ttnAddressOptionsForParty" in js
    assert "function _ttnRefreshLoadPlaceOptions" in js
    assert "function _ttnRefreshUnloadPlaceOptions" in js
    assert "function onTtnShipperChange" in js
    assert "function onTtnConsigneeChange" in js
    helper = js.split("function _ttnAddressOptionsForParty", 1)[1].split("\nfunction ", 1)[0]
    assert "_ttnWarehousesForContractor" in helper
    assert "_ttnWarehousesForLegalEntity" in helper
    assert "contractorAddressLine" in helper
    assert "warehouseAddressLine" in helper
    # LE party: warehouses only (not LE card address).
    assert "not the LE card address" in helper
    assert "addr:le:" not in helper
    assert "legalEntityAddressLine" not in helper
    # Warehouse dropdown: name first, then address via " | ".
    assert "${wname} | ${waddr}" in helper or "`${wname} | ${waddr}`" in helper
    assert "${waddr} · ${wname}" not in helper
    assert "Юр. лицо ·" not in helper
    assert "Контрагент ·" not in helper
    assert "c.requisites" not in helper
    # Global catalog of all parties/warehouses must not drive place presets anymore.
    assert "function _ttnPlacePresetOptions" not in js
    assert 'ssPopulate("ttnCreateShipperWrap", partyOpts,' in js
    assert "onTtnShipperChange()" in js.split('ssPopulate("ttnCreateShipperWrap"', 1)[1].split(";", 1)[0]
    assert 'ssPopulate("ttnCreateConsigneeWrap", partyOpts,' in js
    assert "onTtnConsigneeChange()" in js.split('ssPopulate("ttnCreateConsigneeWrap"', 1)[1].split(";", 1)[0]



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


def test_ttn_no_secondary_unload_warehouse_picker() -> None:
    """Warehouse addresses belong in the unload place list itself — no second picker / flag."""
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    assert 'id="ttnUnloadWarehouseBlock"' not in html
    assert "function _ttnSyncUnloadWarehousePicker" not in js
    assert "function _ttnContractorUsesWarehouseUnload" not in js
    assert "ttn_unload_from_warehouses" not in js
    assert "newContractorTtnUnloadFromWarehouses" not in html
    assert "Адрес грузоотправителя" in html
    assert "Адрес грузополучателя" in html


def test_ttn_manual_row_has_clear_button() -> None:
    """Manual input rows expose ✕ that clears the row and restores the dropdown."""
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    for fn in (
        "clearTtnManualDriver",
        "clearTtnManualVehicle",
        "clearTtnManualLoad",
        "clearTtnManualUnload",
    ):
        assert f"function {fn}" in js
        assert f"onclick=\"{fn}()\"" in html
    assert "ttn-manual-clear-btn" in html
    assert "ttn-manual-row" in html
    clear_load = js.split("function clearTtnManualLoad", 1)[1].split("\nfunction ", 1)[0]
    assert "_ttnRefreshLoadPlaceOptions" in clear_load
    clear_unload = js.split("function clearTtnManualUnload", 1)[1].split("\nfunction ", 1)[0]
    assert "_ttnRefreshUnloadPlaceOptions" in clear_unload


def test_tn_rename_and_pp2200_fields_additive() -> None:
    """UI renamed to ТН; create modal/print cover ПП РФ № 2200 sections without dropping old fields."""
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")
    repo = REPO.read_text(encoding="utf-8")
    assert "+ Создать ТН" in html
    assert 'id="createTtnModalTitle">Создать ТН<' in html
    assert 'option value="ttn">ТН</option>' in html
    assert "Создать ТН" in js and "Редактировать ТН" in js and "Удалить ТН?" in js
    assert "ТН не найдены" in js
    for field_id in (
        "ttnCreateCustomer",
        "ttnCreateCustomerWrap",
        "ttnCreatePacking",
        "ttnCreateDeclaredValue",
        "ttnCreateVehicleType",
        "ttnCreateLoadingDatetime",
        "ttnCreateLoaderName",
        "ttnCreateUnloadingDatetime",
        "ttnCreateReceiverName",
        "ttnCreateRedirect",
        "ttnCreateMarks",
        "ttnCreateFreightCost",
    ):
        assert f'id="{field_id}"' in html
        assert field_id in js
    assert 'id="ttnOptionalSection"' in html
    assert "Необязательные поля" in html
    assert "function toggleTtnOptionalFields" in js
    assert "function _ttnCustomerPartyOptions" in js
    assert "customer_party_type" in js and "customer_party_id" in js
    # 1а customer picker: legal entities only (no contractors).
    cust_fn = js.split("function _ttnCustomerPartyOptions", 1)[1].split("\nfunction ", 1)[0]
    assert "_supplyLegalEntitiesCache" in cust_fn
    assert "_supplyContractorsCache" not in cust_fn
    assert "Контрагент ·" not in cust_fn
    assert 'label: "— Не указан (как грузоотправитель) —"' in cust_fn
    ref_fn = js.split("function _ttnCustomerRefFromRecord", 1)[1].split("\nfunction ", 1)[0]
    assert 'partyType === "le"' in ref_fn
    assert 'partyType === "contractor"' not in ref_fn
    assert "_supplyContractorsCache" not in ref_fn
    # Vehicle type/capacity comes from driver vehicle card — readonly in TN modal.
    vt = html.split('id="ttnCreateVehicleType"', 1)[1].split(">", 1)[0]
    assert "readonly" in vt
    assert html.count('id="ttnCreateVehicleType"') == 1
    assert "function _ttnFormatVehicleType" in js
    assert "function _ttnSyncVehicleTypeFromSelection" in js
    assert "function onTtnVehicleChange" in js
    assert "skipTypeSync" in js
    assert "(для ТН)" in js
    for col in (
        "customer_services",
        "customer_party_type",
        "customer_party_id",
        "packing_type",
        "declared_value",
        "vehicle_type",
        "loading_datetime",
        "loader_name",
        "unloading_datetime",
        "receiver_name",
        "redirect_info",
        "carrier_marks",
        "freight_cost",
    ):
        assert col in repo and col in web and col in js
    print_html = web.split("def _build_ttn_catalog_html", 1)[1].split("\n    def ", 1)[0]
    assert "Транспортная накладная" in print_html
    # Empty fields stay blank in the printed form (no placeholder dash).
    assert ' or "—"' not in print_html
    for label in ("1.", "1а.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10.", "11.", "12."):
        assert label in print_html
    # Existing core fields still present (no regression).
    for field_id in (
        "ttnCreateShipper",
        "ttnCreateConsignee",
        "ttnCreateDriver",
        "ttnCreateVehicle",
        "ttnCreateCargo",
        "ttnCreatePlaces",
        "ttnCreateWeight",
        "ttnCreateDocs",
        "ttnCreateNotes",
    ):
        assert f'id="{field_id}"' in html
    # Optional fields live inside collapsible block (vehicle type + load/unload datetimes are main).
    optional_block = html.split('id="ttnOptionalSection"', 1)[1].split("ttn-modal-footer", 1)[0]
    assert 'id="ttnCreateVehicleType"' not in optional_block
    assert 'id="ttnCreateLoadingDatetime"' not in optional_block
    assert 'id="ttnCreateUnloadingDatetime"' not in optional_block
    for field_id in (
        "ttnCreateDeclaredValue",
        "ttnCreateLoaderName",
        "ttnCreateReceiverName",
        "ttnCreateNotes",
        "ttnCreateRedirect",
        "ttnCreateMarks",
        "ttnCreateFreightCost",
    ):
        assert f'id="{field_id}"' in optional_block
    vehicle_block = html.split('id="ttnCreateVehicleWrap"', 1)[1].split('id="ttnCreateLoadWrap"', 1)[0]
    assert 'id="ttnCreateVehicleType"' in vehicle_block
    load_block = html.split('id="ttnCreateLoadWrap"', 1)[1].split('id="ttnCreateUnloadWrap"', 1)[0]
    unload_block = html.split('id="ttnCreateUnloadWrap"', 1)[1].split('id="ttnCreateCargo"', 1)[0]
    assert 'id="ttnCreateLoadingDatetime"' in load_block
    assert 'id="ttnCreateUnloadingDatetime"' in unload_block
    assert "Дата погрузки" in load_block
    assert "Дата выдачи" in unload_block
    assert "Дата и время погрузки" not in load_block
    assert "Дата и время выдачи" not in unload_block
    assert 'type="date"' in load_block and 'type="date"' in unload_block
    assert 'type="datetime-local"' not in load_block and 'type="datetime-local"' not in unload_block
    assert "ttn-datetime-cal-btn" in load_block and "ttn-datetime-cal-btn" in unload_block
    assert "function _ttnDatetimeToInputValue" in js
    assert "function _ttnDatetimeFromInputValue" in js
    assert "function openTtnDatetimePicker" in js
    # Stored value is date-only (ДД.ММ.ГГГГ), no time component.
    assert "ДД.ММ.ГГГГ ЧЧ:ММ" not in js
    assert "YYYY-MM-DDTHH:MM" not in js or "legacy" in js.lower()


def test_ttn_fbs_supplies_sorted_newest_first() -> None:
    """FBS supply picker lists newest created_at first (API + client merge)."""
    web = WEB.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    api = web.split("def list_ttn_fbs_supplies", 1)[1].split("\n    @app.", 1)[0]
    assert '"created_at": created_at' in api
    assert "_ttn_fbs_created_ts" in api
    assert "tab_rank" not in api
    assert "created_at: String(it.created_at" in js
    assert "db.localeCompare(da)" in js or "db.localeCompare(da)" in js.replace(" ", "")
    refresh = js.split("async function _ttnRefreshFbsSupplyField", 1)[1].split("\nasync function ", 1)[0]
    assert "created_at" in refresh
    assert "localeCompare" in refresh
