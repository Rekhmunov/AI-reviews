"""Warehouse default packing type → Create TTN preselect."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web_templates" / "app.html"
JS = ROOT / "web_static" / "app.js"
WEB = ROOT / "review_processor" / "web.py"
REPO = ROOT / "review_processor" / "repository.py"
OZ = ROOT / "review_processor" / "ozon_fbs_supplies.py"
WB = ROOT / "review_processor" / "wb_fbs.py"
CARGO = ROOT / "review_processor" / "ttn_fbs_cargo.py"


def test_warehouse_default_packing_schema_and_api() -> None:
    repo = REPO.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")
    assert "default_packing_type TEXT NOT NULL DEFAULT ''" in repo
    assert "default_packing_type" in repo.split("def create_supply_warehouse", 1)[1].split(
        "\n    def ", 1
    )[0]
    assert "default_packing_type" in repo.split("def update_supply_warehouse", 1)[1].split(
        "\n    def ", 1
    )[0]
    create_model = web.split("class CreateSupplyWarehouseRequest", 1)[1].split("class ", 1)[0]
    update_model = web.split("class UpdateSupplyWarehouseRequest", 1)[1].split("class ", 1)[0]
    assert "default_packing_type: str = \"\"" in create_model
    assert "default_packing_type: str = \"\"" in update_model


def test_warehouse_packing_ui() -> None:
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    pane = html.split('id="supplies-settings-pane-warehouses"', 1)[1][:8000]
    assert 'id="newWarehousePacking"' in pane
    assert "Упаковка по умолчанию" in pane
    thead = pane.split('id="supplyWarehousesThead"', 1)[1][:900]
    assert 'data-col="packing"' in thead
    assert "Упаковка" in thead
    assert "sst_warehouses_v4" in js
    assert "default_packing_type" in js.split("async function saveSupplyWarehouse", 1)[1].split(
        "async function deleteSupplyWarehouse", 1
    )[0]
    assert "default_packing_type" in js.split("async function saveEditWarehouse", 1)[1].split(
        "async function toggleAddWarehouseForm", 1
    )[0]
    assert "_warehousePackingOptionsHtml" in js
    assert "colspan=\"7\"" in js.split("async function renderSupplyWarehousesTbody", 1)[1].split(
        "async function startEditWarehouse", 1
    )[0]


def test_ttn_prefill_and_cargo_use_warehouse_packing() -> None:
    oz = OZ.read_text(encoding="utf-8")
    wb = WB.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")
    cargo = CARGO.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    oz_prefill = oz.split("def build_ttn_prefill", 1)[1].split(
        "\ndef list_supply_driver_options", 1
    )[0]
    wb_prefill = wb.split("def build_ttn_prefill", 1)[1].split(
        "\ndef persist_order_stickers_batch", 1
    )[0]
    assert "default_packing_type" in oz_prefill
    assert '"packing_type": packing_type' in oz_prefill
    assert "local_ozon_places_count" in oz_prefill
    assert "default_packing_type" in wb_prefill
    assert '"packing_type": packing_type' in wb_prefill
    cargo_api = web.split("def get_ttn_fbs_cargo", 1)[1].split("\n    @app.", 1)[0]
    assert "include_sc_accepted=True" in cargo_api
    assert "local_ozon_places_count" in cargo_api
    assert '"packing_type": packing_type' in cargo_api
    assert "bound_to_open_supply" in cargo
    assert "def normalize_packing_type" in cargo
    change = js.split("async function onTtnFbsSupplyChange", 1)[1].split(
        "window.onTtnFbsSupplyChange", 1
    )[0]
    assert "packing_type" in change
    assert "_ttnSetPackingValue" in change
    assert "app.js?v=690" in HTML.read_text(encoding="utf-8")
