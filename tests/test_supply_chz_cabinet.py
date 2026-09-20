"""Cabinet-wide «Работа с ЧЗ» on Настройки → Маркировка и ГТД."""

from __future__ import annotations

from pathlib import Path

import pytest

from review_processor.supply_chz_cabinet import (
    emission_period_bounds,
    initial_search_cursor,
    kiz_from_search_row,
    product_groups_from_settings,
)

ROOT = Path(__file__).resolve().parents[1]
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
WEB = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
API = (ROOT / "review_processor" / "chz_true_api.py").read_text(encoding="utf-8")
CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")


def test_initial_search_cursor_is_day_after_period_end() -> None:
    assert initial_search_cursor("2026-01-05T23:59:59.000Z") == (
        "2026-01-06T00:00:00.000Z",
        "0",
    )


def test_product_groups_split() -> None:
    assert product_groups_from_settings({"product_group": "lp, shoes"}) == ["lp", "shoes"]
    assert product_groups_from_settings({"product_group": "lp"}) == ["lp"]


def test_emission_period_bounds_inclusive_days() -> None:
    assert emission_period_bounds("2026-01-02", "2026-01-05") == (
        "2026-01-02T00:00:00.000Z",
        "2026-01-05T23:59:59.000Z",
    )


def test_emission_period_rejects_bad_range() -> None:
    with pytest.raises(ValueError):
        emission_period_bounds("2026-02-01", "2026-01-01")
    with pytest.raises(ValueError):
        emission_period_bounds("02.01.2026", "05.01.2026")


def test_kiz_from_search_row_keeps_name_when_cis_is_raw() -> None:
    short, gtin, name, emission = kiz_from_search_row(
        {
            "sgtin": "not-a-kiz",
            "gtin": "123",
            "productName": "Шампунь",
            "emissionDate": "2026-03-01T10:00:00.000Z",
        }
    )
    assert short == "not-a-kiz"
    assert gtin == "123"
    assert name == "Шампунь"
    assert emission.startswith("2026-03-01")


def test_cises_search_has_no_status_filter() -> None:
    start = API.find("def cises_search")
    end = API.find("\ndef ", start + 1)
    body = API[start:end]
    assert "emissionDatePeriod" in body
    assert '"states"' not in body
    assert "/cises/search" in body


def test_cabinet_routes_exist() -> None:
    for path in (
        "/api/supply-chz/cabinet/kiz",
        "/api/supply-chz/cabinet/export",
        "/api/supply-chz/cabinet/runs/{run_id}",
        "/api/supply-chz/cabinet/cis-status",
        "/api/supply-chz/cabinet/prepare",
        "/api/supply-chz/cabinet/submit",
    ):
        assert path in WEB


def test_settings_tab_and_header_renamed() -> None:
    assert 'showSuppliesSettingsTab(\'gtd\')">Маркировка и ГТД</button>' in APP_HTML
    assert ">Маркировка и ГТД</h4>" in APP_HTML
    assert "ГТД (таможенные декларации)" not in APP_HTML
    assert "openSupplyChzCabinetModal()\">Работа с ЧЗ</button>" in APP_HTML


def test_cabinet_modal_matches_gtd_chz_size_and_tools() -> None:
    start = APP_HTML.find('id="supplyChzCabinetModal"')
    end = APP_HTML.find('id="editSupplySourceKeyModal"')
    assert start > APP_HTML.find('id="supplyGtdChzLogModal"')
    block = APP_HTML[start:end]
    assert "supply-gtd-chz-modal" in block
    assert 'id="supplyChzCabDateFrom"' in block
    assert 'id="supplyChzCabDateTo"' in block
    assert "Выгрузить коды маркировки" in block
    assert 'id="supplyChzCabLogModal"' in block
    assert "resetSupplyChzCabinetFilters()" in block
    assert 'placeholder="КИЗ, GTIN, название…"' in block
    assert "В обороте" in block and "Выведен" in block
    assert "Не проверен" in block and "Ошибка" in block
    assert "#supplyChzCabinetModal .supply-gtd-chz-modal" in CSS
    assert "min(1120px, calc(100vw - 16px))" in CSS
    assert "function runSupplyChzCabinetExport" in APP_JS
    assert "/api/supply-chz/cabinet/export" in APP_JS
    assert "function resetSupplyChzCabinetFilters" in APP_JS
    assert "Выбрано:" in APP_JS
    assert "def lookup_cabinet_kiz" in (ROOT / "review_processor" / "supply_chz_cabinet.py").read_text(encoding="utf-8")
    assert "cabinet_kiz" in WEB
    assert 'id="supplyGtdCabinetHit"' in APP_HTML
    assert "openSupplyChzCabinetFromSearch" in APP_JS
    assert "Ввести в оборот" in APP_JS
    assert "app.js?v=682" in APP_HTML
    assert "style.css?v=403" in APP_HTML
