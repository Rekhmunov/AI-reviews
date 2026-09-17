"""Logistics multi-TTN UI: tabs, group_id save, route modal, driver column, drafts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web_templates" / "app.html"
JS = ROOT / "web_static" / "app.js"
CSS = ROOT / "web_static" / "style.css"
WEB = ROOT / "review_processor" / "web.py"
REPO = ROOT / "review_processor" / "repository.py"


def test_multi_ttn_html_has_tabs_route_and_driver_column() -> None:
    html = HTML.read_text(encoding="utf-8")
    modal = html.split('id="createTtnModal"', 1)[1].split("<!-- TTN: choose copy source", 1)[0]
    assert 'id="ttnAddTabBtn"' in modal
    assert 'id="ttnTabsBar"' in modal
    assert "Сформировать маршрут" in modal
    assert "openTtnRouteModal()" in modal
    assert 'id="ttnCopySourceModal"' in html
    assert 'id="ttnRouteModal"' in html
    assert 'id="ttnLeaveConfirmModal"' in html
    assert "Точно хотите уйти, не сохраняя?" in html
    thead = html.split('id="ttnTable"', 1)[1].split("</thead>", 1)[0]
    assert ">Водитель<" in thead or ">Водитель<span" in thead
    assert "Водитель / перевозчик" not in thead
    # Overlay click must not close create modal.
    overlay_line = html.split('id="createTtnModal"', 1)[1].split(">", 1)[0]
    assert "closeCreateTtnModal" not in overlay_line
    assert "app.js?v=656" in html
    assert "style.css?v=384" in html


def test_multi_ttn_js_capture_apply_group_route_overlay() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "function _ttnCaptureFormState" in js
    assert "async function _ttnApplyFormState" in js or "function _ttnApplyFormState" in js
    assert "function _ttnBuildPayloadFromState" in js
    assert "group_id" in js.split("function _ttnBuildPayloadFromState", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "crypto.randomUUID" in js
    assert "function openTtnRouteModal" in js
    assert "function ttnAddTab" in js
    assert "function ttnDeleteTab" in js
    assert "TTN_DRAFT_KEY" in js
    assert "localStorage.setItem(TTN_DRAFT_KEY" in js
    assert "_ttnFormDirty" in js
    assert "Точно хотите уйти, не сохраняя?" in js
    driver_cell = js.split("function _ttnDriverCarrierCell", 1)[1].split("\nfunction ", 1)[0]
    assert "carrier_snapshot" not in driver_cell
    assert "d_carrier_name" not in driver_cell
    # Overlay no longer closes on backdrop click (handler removed / noop).
    html = HTML.read_text(encoding="utf-8")
    create_open = html.split('id="createTtnModal"', 1)[1][:400]
    assert "closeCreateTtnModal()" not in create_open.split("ttn-modal-card", 1)[0]


def test_multi_ttn_css_tabs() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert "ttn-tabs" in css
    assert "#createTtnModal .ttn-tabs-bar" in css
    assert "#createTtnModal .ttn-tab" in css
    assert "#createTtnModal .ttn-tab.is-active" in css
    assert "#createTtnModal .ttn-add-tab-btn" in css


def test_multi_ttn_backend_group_id_present() -> None:
    repo = REPO.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")
    assert "group_id" in repo
    assert "ADD COLUMN IF NOT EXISTS group_id" in repo
    assert "list_supply_ttn_records_by_group" in repo
    assert "group_id: str = \"\"" in web
    assert 'group_id: str = ""' in web or "group_id: str =" in web
    assert "/api/supply-ttn-records" in web
    assert "list_ttn_records_by_group" in web or "group_id" in web.split(
        "@app.get(\"/api/supply-ttn-records\")", 1
    )[1][:800]
