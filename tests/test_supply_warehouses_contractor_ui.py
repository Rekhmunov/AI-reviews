"""Поставки → Настройки → Склады: Контрагент/Юр.лицо + API party ids."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web_templates" / "app.html"
JS = ROOT / "web_static" / "app.js"
WEB = ROOT / "review_processor" / "web.py"
REPO = ROOT / "review_processor" / "repository.py"


def test_warehouses_settings_has_party_column_and_select() -> None:
    html = HTML.read_text(encoding="utf-8")
    pane = html.split('id="supplies-settings-pane-warehouses"', 1)[1][:6000]
    thead = pane.split('id="supplyWarehousesThead"', 1)[1][:800]
    assert "Контрагент/Юр.лицо" in thead
    assert 'data-col="contractor"' in thead
    assert 'id="newWarehouseContractor"' in pane
    assert "Контрагент/Юр.лицо" in pane
    # Column order: №, Контрагент/Юр.лицо, Склад, …
    assert thead.find("Контрагент/Юр.лицо") < thead.find("Склад") or thead.find("Название") > thead.find(
        "Контрагент/Юр.лицо"
    )


def test_warehouses_js_party_edit_and_create() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "function _contractorOptionsHtml" in js
    assert "function _warehousePartyRef" in js
    assert "function _parseWarehousePartyRef" in js
    assert "function _ensureSupplyLegalEntitiesLoaded" in js
    assert "newWarehouseContractor" in js
    assert 'optgroup label="Контрагенты"' in js
    assert 'optgroup label="Юр. лица"' in js
    assert 'data-field="party_ref"' in js
    assert "sst_warehouses_v3" in js
    create_payload = js.split("async function saveSupplyWarehouse", 1)[1].split(
        "async function deleteSupplyWarehouse", 1
    )[0]
    assert "contractor_id" in create_payload
    assert "legal_entity_id" in create_payload
    edit_payload = js.split("async function saveEditWarehouse", 1)[1].split(
        "async function toggleAddWarehouseForm", 1
    )[0]
    assert "contractor_id" in edit_payload
    assert "legal_entity_id" in edit_payload
    assert "app.js?v=624" in HTML.read_text(encoding="utf-8")


def test_warehouses_api_and_schema_party_ids() -> None:
    web = WEB.read_text(encoding="utf-8")
    repo = REPO.read_text(encoding="utf-8")
    create_model = web.split("class CreateSupplyWarehouseRequest", 1)[1].split("class ", 1)[0]
    update_model = web.split("class UpdateSupplyWarehouseRequest", 1)[1].split("class ", 1)[0]
    assert "contractor_id: int | None = None" in create_model
    assert "legal_entity_id: int | None = None" in create_model
    assert "contractor_id: int | None = None" in update_model
    assert "legal_entity_id: int | None = None" in update_model
    assert "ALTER TABLE supply_warehouses ADD COLUMN IF NOT EXISTS contractor_id" in repo
    assert "ALTER TABLE supply_warehouses ADD COLUMN IF NOT EXISTS legal_entity_id" in repo
    assert "idx_supply_warehouses_contractor" in repo
    assert "idx_supply_warehouses_legal_entity" in repo
    list_fn = repo.split("def list_supply_warehouses", 1)[1].split("\n    def ", 1)[0]
    assert "contractor_name" in list_fn
    assert "legal_entity_name" in list_fn
    assert "def _resolve_warehouse_party_ids" in repo
    # Deleting contractor / LE clears warehouse links (does not delete warehouses).
    delete_c = repo.split("def delete_supply_contractor", 1)[1].split("\n    def ", 1)[0]
    assert "UPDATE supply_warehouses SET contractor_id = NULL" in delete_c
    delete_le = repo.split("def delete_supply_legal_entity", 1)[1].split("\n    def ", 1)[0]
    assert "UPDATE supply_warehouses SET legal_entity_id = NULL" in delete_le
