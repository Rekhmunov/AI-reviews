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
    assert "Водитель" in thead
    assert "Водитель / перевозчик" not in thead
    assert "ttn-sortable" in thead
    assert "toggleTtnSort('driver')" in thead
    assert "ttn-sort-icon" in thead
    # Overlay click must not close create modal.
    overlay_line = html.split('id="createTtnModal"', 1)[1].split(">", 1)[0]
    assert "closeCreateTtnModal" not in overlay_line
    assert "app.js?v=702" in html
    assert "style.css?v=418" in html


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
    assert "пустое оставляем пустым" in route_fn
    assert "_ttnPartyPhone" in route_fn or "function _ttnPartyPhone" in js
    assert "if (phone) lines.push(phone)" in route_fn
    assert "${places} мест" in route_fn or "`${places} мест`" in route_fn
    route_btn = html.split('id="ttnRouteBtn"', 1)[1].split("</button>", 1)[0]
    assert "disabled" not in route_btn
    assert "openTtnRouteModal()" in route_btn


def test_route_includes_party_phone() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "function _ttnPartyPhone" in js
    phone_fn = js.split("function _ttnPartyPhone", 1)[1].split("\nfunction ", 1)[0]
    assert 'e?.phone' in phone_fn or "e.phone" in phone_fn
    assert "c?.phone" in phone_fn or "c.phone" in phone_fn
    assert "_supplyLegalEntitiesCache" in phone_fn
    assert "_supplyContractorsCache" in phone_fn


def test_multi_ttn_css_tabs() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert "ttn-tabs" in css
    assert "#createTtnModal .ttn-tabs-bar" in css
    assert "#createTtnModal .ttn-tab" in css
    assert "#createTtnModal .ttn-tab.is-active" in css
    assert "#createTtnModal .ttn-tab-num" in css
    assert "#createTtnModal .ttn-add-tab-btn" in css
    js = JS.read_text(encoding="utf-8")
    assert 'class="ttn-tab-num"' in js


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
    """Grouped TN rows stay adjacent: newest ttn_date first, within group by id ASC."""
    from review_processor.repository import cluster_supply_ttn_records_by_group

    rows = [
        {"id": 1, "group_id": "", "doc_number": "1", "ttn_date": "01.09.2026"},
        {"id": 3, "group_id": "g1", "doc_number": "3", "ttn_date": "02.09.2026"},
        {"id": 2, "group_id": "g1", "doc_number": "2", "ttn_date": "02.09.2026"},
        {"id": 4, "group_id": "", "doc_number": "4", "ttn_date": "03.09.2026"},
        {"id": 6, "group_id": "g2", "doc_number": "6", "ttn_date": "04.09.2026"},
        {"id": 5, "group_id": "g2", "doc_number": "5", "ttn_date": "04.09.2026"},
    ]
    out = cluster_supply_ttn_records_by_group(rows)
    assert [r["id"] for r in out] == [5, 6, 4, 2, 3, 1]
    # Members of each group are contiguous.
    g2 = [i for i, r in enumerate(out) if r["group_id"] == "g2"]
    g1 = [i for i, r in enumerate(out) if r["group_id"] == "g1"]
    assert g2 == [0, 1]
    assert g1 == [3, 4]


def test_ttn_list_clusters_prefers_date_over_doc_number() -> None:
    from review_processor.repository import cluster_supply_ttn_records_by_group

    rows = [
        {"id": 10, "group_id": "", "doc_number": "99", "ttn_date": "01.09.2026"},
        {"id": 11, "group_id": "", "doc_number": "1", "ttn_date": "10.09.2026"},
        {"id": 12, "group_id": "g", "doc_number": "3", "ttn_date": "05.09.2026"},
        {"id": 13, "group_id": "g", "doc_number": "4", "ttn_date": "05.09.2026"},
    ]
    out = cluster_supply_ttn_records_by_group(rows)
    assert [r["id"] for r in out] == [11, 12, 13, 10]


def test_ttn_ui_reclusters_after_filters() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "function _ttnClusterRowsByGroup" in js
    assert "function _ttnDocNumberValue" in js
    assert "function toggleTtnSort" in js
    assert 'TTN_SORT_KEY = "ttn_table_sort_v1"' in js
    assert 'col: "ttn_date", dir: "desc"' in js
    assert "localStorage.setItem(TTN_SORT_KEY" in js
    render = js.split("function renderTtnTable", 1)[1].split("\nfunction ", 1)[0]
    assert "_ttnFilteredRows()" in render or "_ttnPageSlice" in render
    assert "_updateTtnSortIcons()" in render
    assert "_ttnPageSlice" in render
    assert "ttn-row-checkbox" in render
    assert "toggleTtnRowSelected" in js
    assert "function toggleTtnSelectAll" in js
    assert "function printSelectedTtnRecords" in js
    assert "/api/supply-ttn-records/print-html" in js
    assert "TTN_PAGE_SIZE = 50" in js
    assert "function ttnChangePage" in js
    assert "function _ttnOnFilterChange" in js
    html = HTML.read_text(encoding="utf-8")
    assert 'id="ttnSelectAll"' in html
    assert 'id="ttnPrintSelectedBtn"' in html
    assert 'id="ttnPrevBtn"' in html
    assert 'id="ttnNextBtn"' in html
    assert 'id="ttnPageInfo"' in html
    assert 'id="ttnInfo"' in html
    assert "ttnChangePage(-1)" in html
    assert 'class="ttn-sortable"' in html or "ttn-sortable" in html
    assert "toggleTtnSort('ttn_date')" in html
    assert "toggleTtnSort('doc_number')" in html
    assert "app.js?v=702" in html
    assert "style.css?v=418" in html
    css = CSS.read_text(encoding="utf-8")
    assert "#ttnTable th.ttn-sortable" in css
    assert ".ttn-sort-icon" in css
    web = WEB.read_text(encoding="utf-8")
    assert '"/api/supply-ttn-records/print-html"' in web
    assert "allocate_next_supply_ttn_doc_number" in web
    assert "peek_next_supply_ttn_doc_number" in web
    repo = REPO.read_text(encoding="utf-8")
    assert "def peek_next_supply_ttn_doc_number" in repo
    assert "def allocate_next_supply_ttn_doc_number" in repo
    assert "pg_advisory_lock" in repo
    assert "Newest transport notes" in repo


def test_ttn_select_all_uses_current_page_of_filtered() -> None:
    js = JS.read_text(encoding="utf-8")
    select_all = js.split("function toggleTtnSelectAll", 1)[1].split("\nfunction ", 1)[0]
    assert "_ttnPageSlice(_ttnFilteredRows())" in select_all
    assert "TTN_PAGE_SIZE" in js
    # Filter change resets to page 1.
    assert "_ttnPage = 1" in js.split("function _ttnOnFilterChange", 1)[1].split(
        "\nfunction ", 1
    )[0]

def test_supply_ttn_doc_number_gap_fill() -> None:
    """Lowest free positive integer is reused after a gap (delete semantics)."""
    used = {1, 2, 4, 5}

    def _next(used_set: set[int]) -> int:
        n = 1
        while n in used_set:
            n += 1
        return n

    assert _next(used) == 3
    assert _next({1, 2, 3}) == 4
    assert _next(set()) == 1
    repo = REPO.read_text(encoding="utf-8")
    assert "while n in used" in repo.split("def peek_next_supply_ttn_doc_number", 1)[1][:400]
    assert "while n in used" in repo.split("def allocate_next_supply_ttn_doc_number", 1)[1][:800]