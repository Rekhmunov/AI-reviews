"""WB FBS phone layout keeps status badges and does not restyle the desktop table."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def _slice(src: str, start: str, end: str) -> str:
    i = src.find(start)
    assert i >= 0, start
    j = src.find(end, i + len(start))
    assert j > i, end
    return src[i:j]


def test_cache_versions() -> None:
    assert "app.js?v=702" in HTML
    assert "style.css?v=418" in HTML


def test_cell_hooks_do_not_change_status_logic() -> None:
    fn = _slice(JS, "function renderWbFbsSuppliesTable()", "function renderWbFbsOrdersTable")
    assert 'wbFbsState.tab === "delivery"' in fn
    assert "wb-fbs-td-status" in fn
    assert "fbs-supply-status-stack" in fn
    assert '"Сформирована"' in fn
    assert '"Несформирована"' in fn
    assert ': `<td class="wb-fbs-td-status">${statusBadge}</td>`;' in fn
    orders = _slice(JS, "function renderWbFbsOrdersTable()", "function onWbFbsCheckboxChange")
    assert "wb-fbs-td-order" in orders
    assert "wb-fbs-td-product" in orders


def test_phone_cards_are_inside_mobile_media_only() -> None:
    mobile = _slice(CSS, "@media (max-width: 720px) {", "/* WB FBS KIZ circulation modal extras */")
    assert "wb-fbs-table--assembly" in mobile
    assert 'grid-template-areas:\n      "check supply act"' in mobile
    assert "wb-fbs-td-status" in mobile
    assert "wb-fbs-td-scan" in mobile
    assert "fbs-supply-row-warn" in mobile
    assert "fbs-supply-row-ok" in mobile
    assert "#section-supplies-wb-fbs .wb-fbs-sync-info" in mobile
    desktop = CSS.split("@media (max-width: 720px) {", 1)[0]
    assert "wb-fbs-td-status" not in desktop
    assert 'grid-template-areas:\n      "check supply act"' not in desktop
