"""Ozon «Доставляются»: stage column shows whether the TTN was saved."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")


def _slice(src: str, start: str, end: str) -> str:
    i = src.find(start)
    assert i >= 0, start
    j = src.find(end, i + len(start))
    assert j > i, end
    return src[i:j]


def test_cache_versions() -> None:
    assert "ozon_fbs.js?v=192" in HTML
    assert "style.css?v=411" in HTML


def test_delivering_header_only() -> None:
    sync = _slice(JS, "function syncTableMode", "function _ozonFbsRenameMenuIconHtml")
    assert 'delivering ? "Этап сборки/Статус ТН" : "Этап сборки"' in sync


def test_stage_cell_second_badge_uses_saved_ttn() -> None:
    fn = _slice(JS, "function _ozonFbsSupplyStageCell", "function renderSuppliesTable")
    assert "if (!isDeliveringSuppliesTab()) return stage;" in fn
    assert "Number(supply?.ttn_id || 0) > 0" in fn
    assert '"Сформирована"' in fn
    assert '"Несформирована"' in fn
    assert "is-done" in fn
    assert "is-ttn-none" in fn
    assert "fbs-supply-status-stack" in fn
    render = _slice(JS, "function renderSuppliesTable", "function productCompositionHtml")
    assert "_ozonFbsSupplyStageCell(s)" in render


def test_ttn_badge_styles() -> None:
    assert ".fbs-supply-status-stack" in CSS
    assert ".wb-fbs-supply-status.is-ttn-none" in CSS
    assert ".wb-fbs-supply-status.is-done" in CSS
