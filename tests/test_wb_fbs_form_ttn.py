"""WB FBS «Сформировать ТН»: local LE/warehouse sources, delivery menu, prefill."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
WEB = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
REPO = (ROOT / "review_processor" / "repository.py").read_text(encoding="utf-8")
WB = (ROOT / "review_processor" / "wb_fbs.py").read_text(encoding="utf-8")


def test_legal_entity_fbs_source_checkboxes() -> None:
    assert 'id="newLegalFbsSources"' in HTML
    assert "Источники FBS" in HTML
    assert "editLegalFbsSources-${item.id}" in JS
    assert "_legalEntityFbsTakenMap" in JS
    assert "takenBy: _legalEntityFbsTakenMap" in JS
    assert "sigPayload.fbs_sources" in JS
    assert 'fbs_sources: _readWarehouseFbsSourcesFromDom(document.getElementById("newLegalFbsSources"))' in JS
    assert "warehouse-fbs-source-taken" in CSS
    assert "def _exclusive_legal_entity_fbs_sources" in REPO
    assert "def find_legal_entity_for_fbs_source" in REPO
    assert "def find_warehouse_for_fbs_source" in REPO
    web_le = WEB.split("class CreateSupplyLegalEntityRequest", 1)[1].split("class UpdateSupplyDriverRequest", 1)[0]
    assert "fbs_sources: list[dict[str, object]] | None = None" in web_le
    patch = WEB.split("def update_supply_legal_entity_endpoint", 1)[1].split("\n    @app.", 1)[0]
    assert "fbs_sources=payload.fbs_sources" in patch


def test_delivery_menu_form_and_print_ttn() -> None:
    assert "Сформировать ТН" in JS
    assert "Распечатать ТН" in JS
    assert "function wbFbsFormTtn" in JS
    assert "/api/wb-fbs/supplies/" in JS
    assert "/ttn-prefill?source_id=" in JS
    assert "printTtnRecord(" in JS
    menu = JS[JS.find("function _wbFbsSupplyRowActionsHtml") : JS.find("async function wbFbsFormTtn")]
    assert "Сформировать ТН" in menu
    assert "Распечатать ТН" in menu
    assert "ttnLogisticsXmlMenuItemsHtml" in menu
    assert "xmlItems" in menu
    assert "Заявка логисту" in JS
    assert "Накладная эТрН" in JS
    assert "/api/supply-ttn-records/${id}/zakaz.xml" in JS
    assert "/api/supply-ttn-records/${id}/etrn.xml" in JS
    assert "Напечатать QR-код поставки" in menu
    assert '_wbFbsSupplyRowActionsHtml(s)' in JS
    assert 'it["ttn_id"]' in WB
    # Shared helper — same endpoints as Логистика → ТН.
    helper = JS.split("function ttnLogisticsXmlMenuItemsHtml", 1)[1].split("\nfunction ", 1)[0]
    assert "/api/supply-ttn-records/${id}/zakaz.xml" in helper
    assert "/api/supply-ttn-records/${id}/etrn.xml" in helper
    assert "Заявка логисту" in helper
    assert "Накладная эТрН" in helper
    # Logistics buttons stay in place (copy into FBS, not move).
    assert "/api/supply-ttn-records/${r.id}/zakaz.xml" in JS
    assert "/api/supply-ttn-records/${r.id}/etrn.xml" in JS
    assert 'span>Заявка логисту</span>' in JS
    assert 'span>Накладная эТрН</span>' in JS


def test_ttn_prefill_is_local_only() -> None:
    assert "def build_ttn_prefill" in WB
    prefill = WB.split("def build_ttn_prefill", 1)[1].split("\ndef persist_order_stickers_batch", 1)[0]
    assert "find_legal_entity_for_fbs_source" in prefill
    assert "find_warehouse_for_fbs_source" in prefill
    assert "resolve_shipper_load_place" in prefill
    assert "load_warehouse_id" in prefill
    assert '"loading_datetime": ttn_date' in prefill
    assert '"unloading_datetime": ttn_date' in prefill
    assert "get_supply_driver" in prefill
    assert "find_ttn_record_id_by_fbs" in prefill
    assert "Юр. лицо для этого источника не выбрано" in prefill
    assert "Назначьте водителя" in prefill
    assert "Настройки → Юр. лица" in prefill
    assert "Настройки → Склады" in prefill
    assert '@app.get("/api/wb-fbs/supplies/{supply_id}/ttn-prefill")' in WEB
    assert "wb_fbs_mod.build_ttn_prefill" in WEB
    assert "def map_ttn_ids_for_fbs_supplies" in REPO
    assert "def get_supply_ttn_record" in REPO
    assert "_ttnOpenedFromWbFbs" in JS
    assert 'wbFbsState.tab === "delivery"' in JS
    assert "existing_ttn_id" in WB
    assert "find_ttn_record_id_by_fbs" in WEB
    create = WEB.split("def create_ttn_record", 1)[1].split("\n    @app.patch", 1)[0]
    assert "find_ttn_record_id_by_fbs" in create
    assert '"updated": True' in create


def test_cache_bump_for_form_ttn() -> None:
    assert "app.js?v=700" in HTML
    assert "style.css?v=418" in HTML
    assert "_ttnParseFbsPreferValue" in JS
    assert "keepMeta: !!preferFbs || !!_ttnOpenedFromFbsTab || !!_ttnOpenedFromWbFbs" in JS
    assert "w:${Number(record.warehouse_id)}" in JS
    assert "suggest_fbs_ttn_title" in WB
