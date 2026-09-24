"""Working UI window defaults: 90 days lists, analytics from sync_start."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_list_defaults_use_90_days_not_one_month() -> None:
    assert "from.setDate(from.getDate() - 90)" in APP_JS
    assert APP_JS.count("from.setDate(from.getDate() - 90)") >= 3
    # Old ~1-month defaults must not remain in the three setDefault* helpers.
    assert "monthAgo.setMonth(monthAgo.getMonth() - 1)" not in APP_JS


def test_chats_default_date_range_on_boot() -> None:
    assert "setDefaultChatsDateRange(false)" in APP_JS


def test_analytics_defaults_from_sync_start() -> None:
    assert "ensureAnalyticsDefaultDates" in APP_JS
    assert "/api/user-sync-settings" in APP_JS
    assert "sync_start_date" in APP_JS


def test_app_js_cache_bump() -> None:
    assert "app.js?v=701" in APP_HTML
