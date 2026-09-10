"""Logistics tab: rename Доверенности → Логистика, picker + TTN catalog UI/API wiring."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web_templates" / "app.html"
JS = ROOT / "web_static" / "app.js"
WEB = ROOT / "review_processor" / "web.py"
REPO = ROOT / "review_processor" / "repository.py"


def test_nav_and_section_renamed_to_logistics() -> None:
    html = HTML.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    assert 'id="section-supplies-poa"' in html
    assert 'id="nav-supplies-poa"' in web
    assert "> Логистика</a>" in web or "> Логистика</a>" in web.replace("\n", "")
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
    assert "app.js?v=582" in html
    assert "style.css?v=333" in html


def test_ttn_table_and_modal_fields_present() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert 'id="ttnTbody"' in html
    assert "Грузополучатель" in html
    assert "Водитель / перевозчик" in html
    assert 'id="ttnCreateLegal"' in html
    assert 'id="ttnCreateConsignee"' in html
    assert 'id="ttnCreateDriver"' in html
    assert 'id="ttnCreateVehicle"' in html
    assert 'id="ttnCreateLoadAddress"' in html
    assert 'id="ttnCreateUnloadAddress"' in html
    assert 'id="ttnCreateCargo"' in html
    assert "poaTbody" in html
    assert "openCreatePoAModal()" in html


def test_ttn_backend_crud_and_downloads_wired() -> None:
    web = WEB.read_text(encoding="utf-8")
    repo = REPO.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS supply_ttn_records" in repo
    assert "def list_supply_ttn_records" in repo
    assert "def create_supply_ttn_record" in repo
    assert "def update_supply_ttn_record" in repo
    assert "def delete_supply_ttn_record" in repo
    assert '"/api/supply-ttn-records"' in web
    assert '"/api/supply-ttn-records/{record_id}/pdf"' in web
    assert '"/api/supply-ttn-records/{record_id}/doc"' in web
    assert '"/api/supply-ttn-records/{record_id}/html"' in web
    assert "class CreateTtnRecordRequest" in web
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
