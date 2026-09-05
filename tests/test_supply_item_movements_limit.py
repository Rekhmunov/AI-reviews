"""Per-item stock movements journal uses a calendar-day window, not row count."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
WEB_PY = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
REPO_PY = (ROOT / "review_processor" / "repository.py").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")

_MODAL_FN = APP_JS.split("async function openSupplyStockMovementsModal", 1)[1].split(
    "window.openSupplyStockMovementsModal", 1
)[0]


def test_item_movements_ui_requests_last_10_days() -> None:
    assert 'days: "10"' in _MODAL_FN
    assert 'limit: "1000"' not in _MODAL_FN
    assert 'limit: "100"' not in _MODAL_FN
    assert "За последние" in _MODAL_FN
    assert "data.date_from" in _MODAL_FN
    assert "data.days" in _MODAL_FN


def test_item_movements_api_uses_day_window() -> None:
    assert "days: int = 10" in WEB_PY
    assert "date_from: str = \"\"" in WEB_PY or 'date_from: str = ""' in WEB_PY
    assert "date_to: str = \"\"" in WEB_PY or 'date_to: str = ""' in WEB_PY
    assert "timedelta(days=days_n - 1)" in WEB_PY
    assert '"date_from": from_s' in WEB_PY
    assert '"date_to": to_s' in WEB_PY
    assert '"days": days_n' in WEB_PY
    assert "date_from=from_s" in WEB_PY
    assert "date_to=to_s" in WEB_PY
    assert "limit=lim + 1" in WEB_PY
    assert '"truncated": truncated' in WEB_PY
    assert "movement_date >=" in REPO_PY
    assert "movement_date <=" in REPO_PY
    assert "date_from: str = \"\"" in REPO_PY or 'date_from: str = ""' in REPO_PY
    assert "app.js?v=551" in APP_HTML
