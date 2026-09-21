"""Chats section is visible only to the tenant owner."""

from pathlib import Path

from review_processor.config import sync_chats_enabled

ROOT = Path(__file__).resolve().parents[1]


def test_chats_visibility_is_owner_only() -> None:
    web = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
    js = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
    assert "def user_is_tenant_owner(" in web
    assert "can_view_chats = bool(is_tenant_owner)" in web
    assert '"can_view_chats": owner_sees_chats' in web
    assert "Чаты доступны только основному пользователю" in web
    assert "getPermissions().can_view_chats) && isTenantOwner()" in js
    assert "permissions.can_view_chats && isTenantOwner()" in js
    assert 'id="nav-chats"' in html
    assert 'id="section-chats"' in html
    assert "app.js?v=689" in html


def test_chat_sync_defaults_on(monkeypatch) -> None:
    monkeypatch.delenv("FEEDPILOT_SYNC_CHATS_ENABLED", raising=False)
    assert sync_chats_enabled() is True
    monkeypatch.setenv("FEEDPILOT_SYNC_CHATS_ENABLED", "0")
    assert sync_chats_enabled() is False
