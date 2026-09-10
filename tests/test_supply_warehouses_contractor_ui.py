"""Поставки → Настройки → Склады: колонка Контрагент + API contractor_id."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web_templates" / "app.html"
JS = ROOT / "web_static" / "app.js"
WEB = ROOT / "review_processor" / "web.py"
REPO = ROOT / "review_processor" / "repository.py"


def test_warehouses_settings_has_contractor_column_and_select() -> None:
    html = HTML.read_text(encoding="utf-8")
    pane = html.split('id="supplies-settings-pane-warehouses"', 1)[1][:6000]
    thead = pane.split('id="supplyWarehousesThead"', 1)[1][:800]
    assert "Контрагент" in thead
    assert 'data-col="contractor"' in thead
    assert 'id="newWarehouseContractor"' in pane
    # Column order: №, Контрагент, Склад, …
    assert thead.find("Контрагент") < thead.find("Склад") or thead.find("Название") > thead.find(
        "Контрагент"
    )


def test_warehouses_js_contractor_edit_and_create() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "function _contractorOptionsHtml" in js
    assert "newWarehouseContractor" in js
    assert "data-field=\"contractor_id\"" in js or "data-field='contractor_id'" in js
    assert "sst_warehouses_v3" in js
    create_payload = js.split("async function saveSupplyWarehouse", 1)[1].split(
        "async function deleteSupplyWarehouse", 1
    )[0]
    assert "contractor_id" in create_payload
    edit_payload = js.split("async function saveEditWarehouse", 1)[1].split(
        "async function toggleAddWarehouseForm", 1
    )[0]
    assert "contractor_id" in edit_payload


def test_warehouses_api_and_schema_contractor_id() -> None:
    web = WEB.read_text(encoding="utf-8")
    repo = REPO.read_text(encoding="utf-8")
    assert "contractor_id: int | None = None" in web.split(
        "class CreateSupplyWarehouseRequest", 1
    )[1].split("class ", 1)[0]
    assert "contractor_id: int | None = None" in web.split(
        "class UpdateSupplyWarehouseRequest", 1
    )[1].split("class ", 1)[0]
    assert "ALTER TABLE supply_warehouses ADD COLUMN IF NOT EXISTS contractor_id" in repo
    assert "idx_supply_warehouses_contractor" in repo
    assert "contractor_name" in repo.split("def list_supply_warehouses", 1)[1].split(
        "\n    def ", 1
    )[0]
    # Deleting contractor clears warehouse links (does not delete warehouses).
    delete_fn = repo.split("def delete_supply_contractor", 1)[1].split("\n    def ", 1)[0]
    assert "UPDATE supply_warehouses SET contractor_id = NULL" in delete_fn
