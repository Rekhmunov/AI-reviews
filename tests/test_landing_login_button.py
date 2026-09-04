"""Landing page exposes a login CTA to /login."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANDING_HTML = ROOT / "web_templates" / "landing.html"
LANDING_CSS = ROOT / "web_static" / "landing.css"


def test_landing_has_login_button_to_feedpilot() -> None:
    html = LANDING_HTML.read_text(encoding="utf-8")
    css = LANDING_CSS.read_text(encoding="utf-8")
    assert 'href="https://feedpilot.ru/login"' in html
    assert ">Войти<" in html
    assert "fp-landing-login-btn" in html
    assert ".fp-landing-login-btn" in css
    assert "landing.css?v=3" in html
