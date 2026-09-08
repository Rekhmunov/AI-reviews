"""UI assertions for Поставки → Сертификаты: spacing + column sort."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")


def _certs_section() -> str:
    start = APP_HTML.find('id="section-supplies-certificates"')
    end = APP_HTML.find('id="certModal"', start + 1)
    assert start > 0 and end > start
    return APP_HTML[start:end]


def test_certs_sortable_headers() -> None:
    block = _certs_section()
    assert 'id="certsTable"' in block
    for col in (
        "legal_entity_short",
        "doc_type",
        "category",
        "number",
        "expiry_date",
    ):
        assert f'data-sort="{col}"' in block
        assert f"toggleCertsSort('{col}')" in block
    assert block.count("certs-sortable") == 5
    assert block.count("certs-sort-icon") == 5
    assert "Действия" in block
    assert 'onclick="toggleCertsSort' not in block.split("Действия")[1][:200]


def test_certs_sort_js_persists() -> None:
    assert 'CERTS_SORT_KEY = "certs_table_sort_v1"' in APP_JS
    assert "function toggleCertsSort" in APP_JS
    assert "function _sortCertsRows" in APP_JS
    assert "function _updateCertsSortIcons" in APP_JS
    assert "localStorage.setItem(CERTS_SORT_KEY" in APP_JS
    assert "localStorage.getItem(CERTS_SORT_KEY" in APP_JS
    assert "rows = _sortCertsRows(rows)" in APP_JS
    assert "_updateCertsSortIcons()" in APP_JS
    assert "window.toggleCertsSort = toggleCertsSort" in APP_JS


def test_certs_spacing_styles() -> None:
    assert "#section-supplies-certificates" in STYLE
    assert "#certsTable.supplies-main-table th" in STYLE
    assert "padding: 10px 12px" in STYLE
    assert "th.certs-sortable" in STYLE
    assert "certs-sort-active" in STYLE


def test_asset_versions_bumped() -> None:
    assert "app.js?v=562" in APP_HTML
    assert "style.css?v=318" in APP_HTML
