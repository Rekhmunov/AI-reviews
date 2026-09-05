"""UI: supply stock movements journal grouped by day (collapsed)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_movements_journal_groups_by_day_collapsed() -> None:
    assert "function _sbGroupMovementsByDay(" in APP_JS
    assert "function _sbRenderMovementsByDay(" in APP_JS
    assert '`<details class="sb-movements-day">' in APP_JS
    assert "sb-movements-day-chevron" in APP_JS
    render_fn = APP_JS.split("function _sbRenderMovementsByDay(", 1)[1].split(
        "async function openSupplyStockMovementsModal(", 1
    )[0]
    assert " open>" not in render_fn
    assert 'open="' not in render_fn
    assert "list.innerHTML = _sbRenderMovementsByDay(items, unit);" in APP_JS


def test_movements_day_group_styles_and_cache() -> None:
    assert ".sb-movements-day-summary" in STYLE_CSS
    assert ".sb-movements-day-chevron" in STYLE_CSS
    assert ".sb-movements-day[open]" in STYLE_CSS
    assert "style.css?v=305" in APP_HTML
    assert "app.js?v=550" in APP_HTML
