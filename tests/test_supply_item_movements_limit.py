"""Per-item stock movements journal should keep a deep history window."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
WEB_PY = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
REPO_PY = (ROOT / "review_processor" / "repository.py").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_item_movements_limit_is_deep() -> None:
    # Frontend requests a deep window (not the old 100-row cap).
    assert 'limit: "1000"' in APP_JS
    assert 'limit: "100"' not in APP_JS.split("async function openSupplyStockMovementsModal", 1)[1].split(
        "window.openSupplyStockMovementsModal", 1
    )[0]
    assert "data.truncated" in APP_JS
    assert "Показаны последние" in APP_JS


def test_item_movements_api_allows_deep_limit() -> None:
    assert "limit: int = 1000" in WEB_PY
    assert "lim = max(1, min(lim, 2000))" in WEB_PY
    assert "limit=lim + 1" in WEB_PY
    assert '"truncated": truncated' in WEB_PY
    assert "limit: int = 1000" in REPO_PY
    assert "lim = max(1, min(lim, 2000))" in REPO_PY
    assert "app.js?v=550" in APP_HTML
