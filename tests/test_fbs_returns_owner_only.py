"""WB/Ozon FBS toolbar «Возвраты» — только главному пользователю."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
OZON_JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")


def test_returns_buttons_hidden_by_default() -> None:
    wb = HTML[HTML.find('id="wbFbsKizRestoreBtn"') : HTML.find('id="wbFbsKizRestoreBtn"') + 280]
    oz = HTML[HTML.find('id="ozonFbsKizRestoreBtn"') : HTML.find('id="ozonFbsKizRestoreBtn"') + 160]
    assert "Возвраты" in wb and "hidden" in wb
    assert "Возвраты" in oz and "hidden" in oz


def test_wb_owner_only_returns_sync() -> None:
    assert "function _wbFbsSyncOwnerOnlyReturnsBtn(" in APP_JS
    assert "_wbFbsSyncOwnerOnlyReturnsBtn()" in APP_JS
    chunk = APP_JS.split("function _wbFbsSyncOwnerOnlyReturnsBtn", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "wbFbsKizRestoreBtn" in chunk
    assert "_wbFbsCanViewOwnerTabs" in chunk
    open_fn = APP_JS.split("function openWbFbsKizRestoreModal", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "isTenantOwner" in open_fn


def test_ozon_owner_only_returns_sync() -> None:
    assert "function _ozonFbsSyncOwnerOnlyReturnsBtn(" in OZON_JS
    assert "_ozonFbsSyncOwnerOnlyReturnsBtn()" in OZON_JS
    chunk = OZON_JS.split("function _ozonFbsSyncOwnerOnlyReturnsBtn", 1)[1].split(
        "\n  async function initSection", 1
    )[0]
    assert "ozonFbsKizRestoreBtn" in chunk
    assert "isTenantOwner" in chunk


def test_cache_bump() -> None:
    assert "app.js?v=697" in HTML
    assert "ozon_fbs.js?v=197" in HTML
