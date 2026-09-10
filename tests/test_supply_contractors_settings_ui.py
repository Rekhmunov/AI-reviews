"""Поставки → Настройки → Контрагенты: те же поля карточки, что у юр. лиц."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web_templates" / "app.html"
JS = ROOT / "web_static" / "app.js"
WEB = ROOT / "review_processor" / "web.py"
REPO = ROOT / "review_processor" / "repository.py"


def test_contractors_form_mirrors_legal_entity_fields() -> None:
    html = HTML.read_text(encoding="utf-8")
    pane = html.split('id="supplies-settings-pane-contractors"', 1)[1][:8000]
    for field_id in (
        "newContractorName",
        "newContractorFullName",
        "newContractorRequisites",
        "newContractorSignatories",
        "newContractorInPerson",
        "newContractorBasis",
        "newContractorPhone",
        "newContractorAddrIndex",
        "newContractorAddrRegion",
        "newContractorAddrDistrict",
        "newContractorAddrCity",
        "newContractorAddrSettlement",
        "newContractorAddrStreet",
        "newContractorAddrHouse",
        "newContractorAddrCorpus",
        "newContractorAddrFlat",
        "newContractorAddrFias",
    ):
        assert f'id="{field_id}"' in pane
    assert "Короткое наименование" in pane
    assert "Полное наименование" in pane
    assert "Адрес (поля эТрН)" in pane
    assert "newContractorTtnUnloadFromWarehouses" not in pane
    assert "В ТТН адреса разгрузки брать со складов" not in pane


def test_contractors_table_has_le_like_columns() -> None:
    html = HTML.read_text(encoding="utf-8")
    thead = html.split('id="supplyContractorsThead"', 1)[1][:1500]
    for label in (
        "Короткое",
        "Полное наименование",
        "Реквизиты",
        "Подписанты",
        "В лице",
        "Основание",
        "Адрес",
        "Телефон",
    ):
        assert label in thead


def test_contractors_js_edit_and_addr_helpers() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "const _CTR_ADDR_FIELDS" in js
    assert "function contractorAddressLine" in js
    assert "function _readNewContractorAddrFields" in js
    assert "function _clearNewContractorFormFields" in js
    assert "function _contractorAddrEditInputsHtml" in js
    assert "function startEditContractor" in js or "async function startEditContractor" in js
    assert "_sstPartyEditPanelHtml" in js
    assert "sst-inline-edit" in js
    assert "sst-edit-section" in js
    assert "function saveEditContractor" in js
    assert 'data-ctr-addr="' in js
    assert '[data-ctr-addr="' in js
    assert "sst_contractors_v2" in js
    assert "full_name: full" in js
    assert "..._readNewContractorAddrFields()" in js


def test_contractors_addr_fields_match_legal_entities() -> None:
    js = JS.read_text(encoding="utf-8")

    def _fields(const_name: str) -> list[str]:
        block = js.split(f"const {const_name} = [", 1)[1].split("];", 1)[0]
        return [line.split('"')[1] for line in block.splitlines() if '["' in line]

    assert _fields("_CTR_ADDR_FIELDS") == _fields("_LE_ADDR_FIELDS")


def test_contractors_api_models_include_addr_fields() -> None:
    web = WEB.read_text(encoding="utf-8")
    create = web.split("class CreateSupplyContractorRequest", 1)[1].split("class ", 1)[0]
    update = web.split("class UpdateSupplyContractorRequest", 1)[1].split("class ", 1)[0]
    for block in (create, update):
        for field in (
            "full_name",
            "signatories",
            "in_person",
            "basis",
            "phone",
            "addr_index",
            "addr_region_code",
            "addr_fias",
        ):
            assert field in block


def test_contractors_schema_migration_adds_le_columns() -> None:
    repo = REPO.read_text(encoding="utf-8")
    assert "ALTER TABLE supply_contractors ADD COLUMN IF NOT EXISTS" in repo
    for col in (
        "full_name",
        "signatories",
        "in_person",
        "basis",
        "addr_index",
        "addr_region_code",
        "addr_city",
        "addr_street",
        "addr_fias",
    ):
        assert f'("{col}"' in repo
    assert "def contractor_address_line" in repo
    assert "addr_index, addr_region_code, addr_district" in repo


def test_contractors_no_ttn_unload_flag_in_ui() -> None:
    """Warehouses linked to a contractor always appear in TTN place lists — no UI flag."""
    js = JS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    assert "ttn_unload_from_warehouses" not in js
    assert 'data-field="ttn_unload_from_warehouses"' not in js
    assert "newContractorTtnUnloadFromWarehouses" not in html
    assert "ТТН — место разгрузки" not in js


def test_contractor_address_line_assembles_like_legal() -> None:
    from review_processor.repository import ReviewRepository

    line = ReviewRepository.contractor_address_line(
        {
            "addr_index": "101000",
            "addr_city": "Москва",
            "addr_street": "ул. Тверская",
            "addr_house": "1",
            "address": "legacy",
        }
    )
    assert line == "101000, г. Москва, ул. Тверская, д. 1"
    assert (
        ReviewRepository.contractor_address_line(
            {"address": "старый адрес одной строкой", "addr_city": ""}
        )
        == "старый адрес одной строкой"
    )
