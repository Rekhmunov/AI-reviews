"""UI assertions for certificate IK stack + nav alert badge."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
WEB_PY = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")


def test_certs_column_renamed_to_expiry_ik() -> None:
    start = APP_HTML.find('id="section-supplies-certificates"')
    end = APP_HTML.find('id="certModal"', start + 1)
    block = APP_HTML[start:end]
    assert "Дата завершения/ИК" in block
    assert 'data-sort="expiry_date"' in block


def test_certs_ik_modal_present() -> None:
    assert 'id="certIkModal"' in APP_HTML
    assert 'id="certIkDate"' in APP_HTML
    assert "saveCertIkDate()" in APP_HTML
    assert "Дата проведения ИК" in APP_HTML


def test_certs_ik_js_helpers() -> None:
    for name in (
        "function _certsPlannedIkDate",
        "function _certsIkStack",
        "function _certsExpiryIsRed",
        "function _certsRowNeedsAttention",
        "function _updateCertsNavBadge",
        "function openCertIkModal",
        "function saveCertIkDate",
        "function _certsShiftMonths",
    ):
        assert name in APP_JS
    assert "_certsShiftMonths(anniversary, -3)" in APP_JS
    assert "(ИК)" in APP_JS
    assert "navCertsAlertBadge" in APP_JS
    assert "/api/certificates/" in APP_JS and "/ik" in APP_JS


def test_certs_ik_styles_and_nav_badge() -> None:
    assert ".certs-ik-line.is-due" in STYLE
    assert ".nav-certs-alert-badge" in STYLE
    assert "navCertsAlertBadge" in WEB_PY
    assert "nav-certs-alert-badge" in WEB_PY


def test_certs_ik_api_route() -> None:
    assert '"/api/certificates/{cert_id}/ik"' in WEB_PY
    assert "class CertificateIkDateRequest" in WEB_PY
    assert "set_certificate_ik_date" in WEB_PY
