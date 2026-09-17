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
    assert "app.js?v=659" in html
    assert "style.css?v=385" in html


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


def test_route_empty_load_address_stays_blank() -> None:
    """Empty п.8 in route text stays blank — no em dash and no button gate."""
    js = JS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    route_fn = js.split("function _ttnBuildRouteText", 1)[1].split("\nfunction ", 1)[0]
    assert 'addr || "—"' not in route_fn
    assert "addr || '—'" not in route_fn
    assert "${addr}" in route_fn
    assert "пустое оставляем пустым" in route_fn
    route_btn = html.split('id="ttnRouteBtn"', 1)[1].split("</button>", 1)[0]
    assert "disabled" not in route_btn
    assert "openTtnRouteModal()" in route_btn


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
    assert "def cluster_supply_ttn_records_by_group" in repo
    assert "cluster_supply_ttn_records_by_group(result)" in repo
    assert "group_id: str = \"\"" in web
    assert 'group_id: str = ""' in web or "group_id: str =" in web
    assert "/api/supply-ttn-records" in web
    assert "list_ttn_records_by_group" in web or "group_id" in web.split(
        "@app.get(\"/api/supply-ttn-records\")", 1
    )[1][:800]


def test_ttn_list_clusters_by_group_id() -> None:
    """Grouped TN rows stay adjacent: newest group first, within group by id ASC."""
    from review_processor.repository import cluster_supply_ttn_records_by_group

    rows = [
        {"id": 1, "group_id": "", "created_at": "2026-09-01T10:00:00"},
        {"id": 3, "group_id": "g1", "created_at": "2026-09-02T10:01:00"},
        {"id": 2, "group_id": "g1", "created_at": "2026-09-02T10:00:00"},
        {"id": 4, "group_id": "", "created_at": "2026-09-03T10:00:00"},
        {"id": 6, "group_id": "g2", "created_at": "2026-09-04T10:00:00"},
        {"id": 5, "group_id": "g2", "created_at": "2026-09-02T12:00:00"},
    ]
    out = cluster_supply_ttn_records_by_group(rows)
    assert [r["id"] for r in out] == [5, 6, 4, 2, 3, 1]
    # Members of each group are contiguous.
    g2 = [i for i, r in enumerate(out) if r["group_id"] == "g2"]
    g1 = [i for i, r in enumerate(out) if r["group_id"] == "g1"]
    assert g2 == [0, 1]
    assert g1 == [3, 4]


def test_ttn_ui_reclusters_after_filters() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "function _ttnClusterRowsByGroup" in js
    render = js.split("function renderTtnTable", 1)[1].split("\nfunction ", 1)[0]
    assert "_ttnClusterRowsByGroup(rows)" in render
