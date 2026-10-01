"""UI contract: Reviews AI usage warning banner."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_HTML = ROOT / "web_templates" / "app.html"
APP_JS = ROOT / "web_static" / "app.js"
STYLE_CSS = ROOT / "web_static" / "style.css"


def test_reviews_ai_usage_alert_markup() -> None:
    html = APP_HTML.read_text(encoding="utf-8")
    section = html[html.index('id="section-reviews"') : html.index('id="section-reviews"') + 1200]
    assert 'id="reviewsAiUsageAlert"' in section
    assert 'id="reviewsAiUsageAlertText"' in section
    assert 'id="reviewsAiUsageAlertDismiss"' in section
    assert "dismissReviewsAiUsageAlert()" in section
    # Banner sits under the Reviews heading.
    assert section.index("Отзывы") < section.index("reviewsAiUsageAlert")


def test_reviews_ai_usage_alert_js_hooks() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert "async function loadReviewsAiUsageAlert" in text
    assert "async function dismissReviewsAiUsageAlert" in text
    assert "/api/reviews/ai-usage-alert" in text
    assert "/api/reviews/ai-usage-alert/dismiss" in text
    assert "void loadReviewsAiUsageAlert();" in text
    assert "isTenantOwner()" in text
    # Managers must not dismiss locally without owner check.
    dismiss_idx = text.index("async function dismissReviewsAiUsageAlert")
    branch = text[dismiss_idx : dismiss_idx + 220]
    assert "isTenantOwner()" in branch


def test_reviews_ai_usage_alert_styles() -> None:
    css = STYLE_CSS.read_text(encoding="utf-8")
    assert ".reviews-ai-usage-alert" in css
    assert ".reviews-ai-usage-alert-dismiss" in css
    assert ".reviews-ai-usage-alert-dismiss:focus-visible" in css
