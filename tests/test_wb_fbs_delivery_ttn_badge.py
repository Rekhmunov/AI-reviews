"""WB FBS «В доставке»: a second status badge shows whether the TTN exists."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
WB = (ROOT / "review_processor" / "wb_fbs.py").read_text(encoding="utf-8")


def _slice(src: str, start: str, end: str) -> str:
    i = src.find(start)
    assert i >= 0, start
    j = src.find(end, i + len(start))
    assert j > i, end
    return src[i:j]


def test_cache_version() -> None:
    assert "app.js?v=691" in HTML


def test_delivery_status_header_unchanged() -> None:
    sync = _slice(JS, "function _wbFbsSyncTableMode()", "function renderWbFbsSuppliesTable")
    assert '<th data-col="2">Статус<span class="col-resize-handle"></span></th>' in sync
    assert "Статус ТН" not in sync


def test_delivery_tab_second_badge_uses_saved_ttn() -> None:
    fn = _slice(JS, "function renderWbFbsSuppliesTable()", "function renderWbFbsOrdersTable")
    assert 'const statusBadge = `<span class="wb-fbs-supply-status ${statusClass}">${_wbFbsEsc(status)}</span>`;' in fn
    assert 'wbFbsState.tab === "delivery"' in fn
    assert "Number(s.ttn_id || 0) > 0" in fn
    assert '"Сформирована"' in fn
    assert '"Несформирована"' in fn
    assert "is-done" in fn
    assert "is-ttn-none" in fn
    assert "fbs-supply-status-stack" in fn
    # Assembly and every other tab keep a single status badge.
    assert ': `<td class="wb-fbs-td-status">${statusBadge}</td>`;' in fn
    # Existing delivery status colour is unchanged.
    assert 'isAssembly\n      ? "is-assembly"\n      : (s.scan_dt ? "is-scanned" : "is-ship")' in fn


def test_ttn_id_only_on_wb_delivery_payload() -> None:
    block = _slice(WB, "if tab_key == TAB_DELIVERY and items:", "return {")
    assert 'it["ttn_id"]' in block
    assert 'platform="wb"' in block


def test_badge_styles_already_shared() -> None:
    assert ".fbs-supply-status-stack" in CSS
    assert ".wb-fbs-supply-status.is-ttn-none" in CSS
    assert ".wb-fbs-supply-status.is-done" in CSS
