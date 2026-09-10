"""Settings pencil-edit panels for legal entities and contractors."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web_static" / "app.js"
CSS = ROOT / "web_static" / "style.css"
HTML = ROOT / "web_templates" / "app.html"


def test_shared_party_edit_panel_helpers() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "function _sstEditFieldHtml" in js
    assert "function _sstAddrEditFieldsHtml" in js
    assert "function _sstPartyEditPanelHtml" in js
    assert "Основные данные" in js
    assert "Подписание" in js
    assert "поля эТрН" in js
    assert "wfg-span-${span}" in js


def test_legal_and_contractor_edit_use_panel() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "sst-edit-panel-row le-addr-edit-row" in js
    assert "sst-edit-panel-row ctr-addr-edit-row" in js
    assert "sst-editing" in js
    assert '_sstPartyEditPanelHtml(item, "le")' in js
    assert '_sstPartyEditPanelHtml(item, "ctr")' in js
    le = js[js.find("async function startEditLegalEntity") : js.find("async function saveEditLegalEntity")]
    ctr = js[js.find("async function startEditContractor") : js.find("async function saveEditContractor")]
    assert "поля ниже" not in le
    assert "поля ниже" not in ctr
    assert "_sstPartyEditPanelHtml" in le
    assert "_sstPartyEditPanelHtml" in ctr
    assert "sst-inline-edit" in js


def test_edit_panel_styles_present() -> None:
    css = CSS.read_text(encoding="utf-8")
    for token in (
        ".sst-inline-edit",
        ".sst-edit-grid",
        ".sst-edit-section-title",
        ".wfg-span-2",
        ".wfg-span-4",
        "tr.sst-editing",
    ):
        assert token in css


def test_asset_cache_bumped() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "app.js?v=589" in html
    assert "style.css?v=336" in html
