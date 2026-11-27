"""Supply stock movements journal: load older days in 16-day chunks."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
WEB_PY = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")

_MOVEMENTS_API = WEB_PY.split('@app.get("/api/supply-balances/movements")', 1)[1].split(
    "\n    @app.", 1
)[0]


def test_load_more_ui_wiring() -> None:
    assert "SB_MOVEMENTS_LOAD_MORE_DAYS = 16" in APP_JS
    assert "function loadMoreSupplyStockMovements" in APP_JS
    assert "function _sbRenderSupplyStockMovementsList" in APP_JS
    assert "Подгрузить ещё ${moreDays}" in APP_JS or "Подгрузить ещё ${" in APP_JS
    assert "include_basis: \"0\"" in APP_JS or "include_basis: '0'" in APP_JS
    assert "data.has_more" in APP_JS
    assert "st.hasMore = !!data.has_more" in APP_JS
    assert "sb-movements-load-more" in APP_JS
    assert "onclick=\"loadMoreSupplyStockMovements()\"" in APP_JS
    assert "app.js?v=729" in APP_HTML
    assert "style.css?v=448" in APP_HTML
    assert "подгрузить ещё по 16 дней" in APP_HTML


def test_load_more_styles() -> None:
    assert ".sb-movements-load-more" in STYLE_CSS
    assert ".sb-movements-load-more-btn" in STYLE_CSS
    assert ".sb-movements-list > .sb-movements-day:last-of-type" in STYLE_CSS


def test_movements_api_has_more_and_include_basis() -> None:
    assert "include_basis: int = 1" in _MOVEMENTS_API
    assert '"has_more": has_more' in _MOVEMENTS_API
    assert "want_basis" in _MOVEMENTS_API
    assert "older_probe" in _MOVEMENTS_API
    assert "day_before_from" in _MOVEMENTS_API
