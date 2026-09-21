"""Ozon FBS phone cards keep the TTN badge and do not restyle the desktop table."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def _slice(src: str, start: str, end: str) -> str:
    i = src.find(start)
    assert i >= 0, start
    j = src.find(end, i + len(start))
    assert j > i, end
    return src[i:j]


def test_cache_versions() -> None:
    assert "ozon_fbs.js?v=191" in HTML
    assert "style.css?v=411" in HTML


def test_supply_cells_keep_ttn_badge_logic() -> None:
    fn = _slice(JS, "function renderSuppliesTable", "function productCompositionHtml")
    assert "wb-fbs-td-status" in fn
    assert "_ozonFbsSupplyStageCell(s)" in fn
    assert "isDeliveringSuppliesTab()\n        ? String(s.row_tone" in fn
    stage = _slice(JS, "function _ozonFbsSupplyStageCell", "function renderSuppliesTable")
    assert "if (!isDeliveringSuppliesTab()) return stage;" in stage
    assert '"Сформирована"' in stage
    assert '"Несформирована"' in stage


def test_phone_cards_are_inside_mobile_media_only() -> None:
    mobile = _slice(CSS, "/* ── OZON FBS: mobile layout", "/* ════════════════════════════════")
    assert "wb-fbs-table--supplies.fbs-col-wrap" in mobile
    assert "wb-fbs-table--supplies:not(.fbs-col-wrap)" in mobile
    assert "wb-fbs-td-status" in mobile
    assert "fbs-supply-row-warn" in mobile
    assert "fbs-supply-row-ok" in mobile
    assert "#section-supplies-ozon-fbs .wb-fbs-sync-info" in mobile
    desktop = CSS.split("@media (max-width: 720px) {", 1)[0]
    assert "wb-fbs-table--supplies.fbs-col-wrap" not in desktop
    assert "wb-fbs-td-status { grid-area: status" not in desktop
