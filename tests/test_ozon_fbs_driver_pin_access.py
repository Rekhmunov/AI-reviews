"""Ozon FBS driver page: PIN uniqueness + public PIN gate."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from review_processor.ozon_fbs_supplies import list_driver_page_vehicle_plates

ROOT = Path(__file__).resolve().parents[1]
WEB = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
REPO = (ROOT / "review_processor" / "repository.py").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
DRIVER_JS = (ROOT / "web_static" / "ozon_fbs_driver.js").read_text(encoding="utf-8")
DRIVER_HTML = (ROOT / "web_templates" / "ozon_fbs_driver.html").read_text(encoding="utf-8")


def test_access_pin_column_and_uniqueness_index() -> None:
    assert "access_pin TEXT NOT NULL DEFAULT ''" in REPO
    assert "uq_supply_drivers_user_access_pin" in REPO
    assert "def normalize_driver_access_pin" in REPO
    assert "def driver_access_pin_taken" in REPO
    assert "def find_supply_driver_by_access_pin" in REPO


def test_public_page_token_and_sessions() -> None:
    assert "ozon_fbs_driver_page_token" in REPO
    assert "ozon_fbs_driver_access_sessions" in REPO
    assert "def ensure_ozon_fbs_driver_page_token" in REPO
    assert "def find_user_id_by_ozon_fbs_driver_page_token" in REPO
    assert "def create_ozon_fbs_driver_access_session" in REPO


def test_web_public_routes_and_pin_on_crud() -> None:
    assert 'access_pin: str = ""' in WEB
    assert "Такой ПИН уже есть у другого водителя" in WEB
    assert "def ozon_fbs_driver_public_page" in WEB
    assert "def ozon_fbs_driver_public_unlock" in WEB
    assert "def ozon_fbs_driver_public_link" in WEB
    assert "X-Driver-Access-Token" in WEB
    assert "PAGE_MODE" in WEB
    assert '"/ozon-fbs/driver/p/{page_token}"' in WEB
    assert '"/api/ozon-fbs/driver/p/{page_token}/unlock"' in WEB
    assert '"/api/ozon-fbs/driver/public-link"' in WEB


def test_settings_ui_has_pin_and_public_link() -> None:
    assert 'id="newDriverAccessPin"' in APP_HTML
    assert "driverPublicLinkBox" in APP_HTML
    assert "copyDriverPublicLink" in APP_HTML
    assert "newDriverAccessPin" in APP_JS
    assert "access_pin: accessPin" in APP_JS
    assert "d.access_pin" in APP_JS
    assert "copyDriverPublicLink" in APP_JS
    assert "/api/ozon-fbs/driver/public-link" in APP_JS


def test_driver_js_pin_gate_and_single_plate() -> None:
    assert "page_mode" in DRIVER_HTML
    assert "PAGE_MODE" in DRIVER_HTML
    assert "isPinMode" in DRIVER_JS
    assert "renderPinForm" in DRIVER_JS
    assert "/unlock" in DRIVER_JS
    assert "maybeAutoloadSinglePlate" in DRIVER_JS
    assert "X-Driver-Access-Token" in DRIVER_JS
    assert 'credentials: isPinMode ? "omit"' in DRIVER_JS


def test_csrf_skips_public_driver_unlock() -> None:
    assert 'path.endswith("/unlock")' in WEB
    assert "/api/ozon-fbs/driver/p/" in WEB


def test_list_plates_can_filter_by_driver_id() -> None:
    repo = MagicMock()
    repo.list_supply_drivers.return_value = [
        {
            "id": 1,
            "full_name": "Иванов",
            "vehicles_json": '[{"number":"А111АА777"},{"number":"В222ВВ777"}]',
        },
        {
            "id": 2,
            "full_name": "Петров",
            "vehicles_json": '[{"number":"С333СС777"}]',
        },
    ]
    all_plates = list_driver_page_vehicle_plates(repo, user_id=10)
    assert len(all_plates) >= 3
    only = list_driver_page_vehicle_plates(repo, user_id=10, driver_id=2)
    nums = {p["number"] for p in only}
    assert nums == {"С333СС777"}


def test_owner_route_redirects_to_pin_not_classic_login() -> None:
    owner_start = WEB.find("def ozon_fbs_driver_page(")
    assert owner_start > 0
    end = WEB.find(chr(10) + "    @app.", owner_start)
    page = WEB[owner_start:end]
    assert "_is_wb_fbs_tenant_owner" in page
    # Short URL must not send drivers to classic /login.
    assert 'RedirectResponse("/login"' not in page
    assert "_ofd_driver_pin_help_html" in WEB
    assert "не использует логин и пароль" in WEB
    assert "/ozon-fbs/driver/p/" in page
    assert "OFD_PAGE_TOKEN_COOKIE" in WEB
    assert "ofd_page_token" in WEB


def test_short_driver_url_never_classic_login() -> None:
    assert "OFD_PAGE_TOKEN_COOKIE" in WEB or 'ofd_page_token' in WEB
    assert "_ofd_driver_pin_help_html" in WEB
    assert "не использует логин и пароль" in WEB
    assert "openOzonFbsDriverPage" in APP_JS
    assert "fetchDriverPublicLinkPath" in APP_JS
    assert "openOzonFbsDriverPage()" in APP_HTML
    assert "без логина и пароля аккаунта" in APP_JS
