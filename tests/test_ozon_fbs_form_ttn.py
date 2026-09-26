"""Ozon FBS «Сформировать ТН» on «Доставляются»: local LE/warehouse + delivery menu."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
WEB = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
OZ = (ROOT / "review_processor" / "ozon_fbs_supplies.py").read_text(encoding="utf-8")


def test_delivering_menu_form_and_print_ttn() -> None:
    assert "Сформировать ТН" in JS
    assert "Распечатать ТН" in JS
    assert "function ozonFbsFormTtn" in JS
    assert "/api/ozon-fbs/supplies/" in JS
    assert "/ttn-prefill?source_id=" in JS
    assert "printTtnRecord(" in JS
    menu = JS[JS.find("function _ozonFbsSupplyRowActionsHtml") : JS.find("async function ozonFbsFormTtn")]
    assert "isDeliveringSuppliesTab()" in menu
    assert "Сформировать ТН" in menu
    assert "Распечатать ТН" in menu
    assert "ttnLogisticsXmlMenuItemsHtml" in menu
    assert "Заявка логисту" in APP_JS  # labels come from shared helper in app.js
    assert "Накладная эТрН" in APP_JS
    assert "_ozonFbsSupplyRowActionsHtml(s)" in JS
    # Actions column shown on delivering (not only awaiting rename).
    sync = JS[JS.find("function syncTableMode") : JS.find("function _ozonFbsRenameMenuIconHtml")]
    assert "const showActions = true" in sync
    assert 'return 7;' in JS[JS.find("function colspan") : JS.find("async function loadSources")]
    # Logistics → TN buttons still present (copy into FBS, not move).
    assert "/api/supply-ttn-records/${r.id}/zakaz.xml" in APP_JS
    assert "/api/supply-ttn-records/${r.id}/etrn.xml" in APP_JS
    assert 'span>Заявка логисту</span>' in APP_JS
    assert 'span>Накладная эТрН</span>' in APP_JS


def test_ttn_prefill_is_local_only() -> None:
    assert "def build_ttn_prefill" in OZ
    prefill = OZ.split("def build_ttn_prefill", 1)[1].split("\ndef list_supply_driver_options", 1)[0]
    assert 'platform="ozon"' in prefill
    assert "find_legal_entity_for_fbs_source" in prefill
    assert "find_warehouse_for_fbs_source" in prefill
    assert "resolve_shipper_load_place" in prefill
    assert "load_warehouse_id" in prefill
    assert '"loading_datetime": ttn_date' in prefill
    assert '"unloading_datetime": ttn_date' in prefill
    assert "get_supply_driver" in prefill
    assert "resolve_ttn_vehicle_type_from_driver" in prefill
    assert '"vehicle_type": vehicle_type' in prefill
    assert "find_ttn_record_id_by_fbs" in prefill
    assert "Настройки → Юр. лица" in prefill
    assert "Настройки → Склады" in prefill
    assert "Назначьте водителя" in prefill
    assert 'fbs_platform": "ozon"' in prefill
    assert "local_ozon_places_count" in prefill
    assert "local_ozon_cargo_place_rows" in prefill
    assert "cargo_places_detail" in prefill
    assert '@app.get("/api/ozon-fbs/supplies/{supply_id}/ttn-prefill")' in WEB
    assert "oz_sup.build_ttn_prefill" in WEB
    assert 'platform="ozon"' in OZ.split("def _list_supplies_tab_response", 1)[1].split(
        "def list_awaiting_deliver_supplies", 1
    )[0]
    assert 'it["ttn_id"]' in OZ
    assert "function setTtnOpenedFromFbsTab" in APP_JS
    assert 'setTtnOpenedFromFbsTab("ozon")' in JS
    assert "window.setTtnOpenedFromFbsTab" in APP_JS
    assert "reloadOzonFbsPostings" in JS
    assert "fromFbsTab === \"ozon\"" in APP_JS or "fromFbsTab === 'ozon'" in APP_JS
    assert "function _ttnSetCargoPlacesDetailUi" in APP_JS
    assert "cargo_places_detail_json" in APP_JS
    assert "ttnCargoPlacesDetailField" in HTML
    assert "ttn-gm-detail-list" in HTML
    assert "ttn-cargo-places-cell" in APP_JS
    assert 'data-sort="cargo_places"' in HTML
    assert "Грузоместа" in HTML.split('id="ttnTable"', 1)[1].split("tbody", 1)[0]
    assert "places_block" in WEB
    assert "format_cargo_place_row_label" in WEB


def test_cache_bump_for_ozon_form_ttn() -> None:
    assert "ozon_fbs.js?v=197" in HTML
    assert "app.js?v=702" in HTML
    assert "style.css?v=418" in HTML
    assert "suggest_fbs_ttn_title" in OZ
