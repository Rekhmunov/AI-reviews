"""Ozon FBS toolbar: «ТСД» and «Для водителя» — только главному пользователю."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
WEB = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")


def test_tsd_and_driver_buttons_hidden_by_default() -> None:
    assert 'id="ozonFbsTsdBtn"' in HTML
    assert 'id="ozonFbsDriverPageBtn"' in HTML
    tsd_i = HTML.find('id="ozonFbsTsdBtn"')
    driver_i = HTML.find('id="ozonFbsDriverPageBtn"')
    tsd = HTML[tsd_i : driver_i]
    driver = HTML[driver_i : driver_i + 350]
    assert "hidden" in tsd
    assert "hidden" in driver
    assert "ТСД" in tsd
    assert "Для водителя" in driver


def test_sync_owner_only_hides_both_buttons() -> None:
    assert "function _ozonFbsSyncOwnerOnlyTsdDriverBtns" in JS
    start = JS.find("function _ozonFbsSyncOwnerOnlyTsdDriverBtns")
    end = JS.find("async function initSection", start)
    sync = JS[start:end]
    assert "isTenantOwner" in sync
    assert "ozonFbsTsdBtn" in sync
    assert "ozonFbsDriverPageBtn" in sync
    assert "btn.hidden = !can" in sync
    assert "can_view_wb_fbs_tsd" not in sync


def test_init_section_calls_owner_sync() -> None:
    start = JS.find("async function initSection")
    end = JS.find("function _ozonFbsSyncOwnerOnlyGear", start)
    init = JS[start:end]
    assert "_ozonFbsSyncOwnerOnlyTsdDriverBtns()" in init
    assert "can_view_wb_fbs_tsd" not in init


def test_driver_page_and_apis_owner_only() -> None:
    page = WEB[
        WEB.find("def ozon_fbs_driver_page") : WEB.find("def admin_page")
    ]
    assert "_is_wb_fbs_tenant_owner" in page
    assert "только главному пользователю" in page

    vehicles = WEB[
        WEB.find("def ozon_fbs_driver_page_vehicles") : WEB.find(
            "def ozon_fbs_driver_page_cargo_places"
        )
    ]
    assert "_is_wb_fbs_tenant_owner" in vehicles

    cargo_start = WEB.find("def ozon_fbs_driver_page_cargo_places")
    cargo = WEB[cargo_start : cargo_start + 1200]
    assert "_is_wb_fbs_tenant_owner" in cargo


def test_cache_bump() -> None:
    assert "ozon_fbs.js?v=174" in HTML
