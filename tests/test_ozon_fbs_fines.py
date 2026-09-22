"""Ozon FBS slot fines — extract fees, status aggregation helpers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from review_processor import ozon_fbs_fines as fines

ROOT = Path(__file__).resolve().parents[1]
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
OZON_JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")


def test_extract_slot_fees_from_non_item() -> None:
    amounts = fines.extract_slot_fees(
        {
            "accrual_id": 1,
            "non_item_fee": {
                "type_id": 94,
                "accrued": {"amount": "-34.78", "currency": "RUB"},
            },
            "item_fees": None,
        }
    )
    assert amounts == [Decimal("-34.78")]


def test_extract_slot_fees_ignores_other_types() -> None:
    amounts = fines.extract_slot_fees(
        {
            "non_item_fee": {
                "type_id": 1,
                "accrued": {"amount": "-10", "currency": "RUB"},
            }
        }
    )
    assert amounts == []


def test_status_for_net() -> None:
    assert fines._status_for_net(Decimal("-12.5")) == "open"
    assert fines._status_for_net(Decimal("0")) == "closed"
    assert fines._status_for_net(Decimal("0.005")) == "closed"
    assert fines._status_for_net(Decimal("1.00")) == "over"


def test_ui_replaces_shipment_quality_with_fines() -> None:
    assert 'id="ozonFbsFinesBtn"' in APP_HTML
    assert "Штрафы" in APP_HTML
    assert 'id="ozonFbsFinesModal"' in APP_HTML
    assert 'id="ozonFbsFinesSettingsModal"' in APP_HTML
    assert 'id="ozonFbsFinesEventsModal"' in APP_HTML
    assert "ozonFbsShipmentQualityBtn" not in APP_HTML
    assert "Качество отгрузок" not in APP_HTML
    assert "ozon-fbs-shipment-quality" not in APP_HTML
    assert "wb-fbs-supply-detail-modal ozon-fbs-fines-modal" in APP_HTML
    # Lead text removed from fines modal
    assert "Отгрузка в нерекомендованный слот — списания и сторно" not in APP_HTML
    fines_modal = APP_HTML.split('id="ozonFbsFinesModal"', 1)[1].split(
        'id="ozonFbsFinesSettingsModal"', 1
    )[0]
    assert ">С</span>" not in fines_modal
    assert ">По</span>" not in fines_modal
    assert 'id="ozonFbsFinesFilterBtn"' in APP_HTML
    assert 'id="ozonFbsFinesImportBtn"' in APP_HTML
    assert 'id="ozonFbsFinesImportFile"' in APP_HTML
    assert "function openOzonFbsFinesModal(" in OZON_JS
    assert "function syncOzonFbsFines(" in OZON_JS
    assert "function triggerOzonFbsFinesImport(" in OZON_JS
    assert "function toggleOzonFbsFinesFilterMenu(" in OZON_JS
    assert "_ozonFbsFinesPollUntilIdle" in OZON_JS
    assert "/api/ozon-fbs/fines/sync/status" in OZON_JS
    assert "/api/ozon-fbs/fines/import" in OZON_JS
    assert "_ozonFbsSyncOwnerOnlyFinesBtn" in OZON_JS
    assert "openOzonFbsShipmentQualityModal" not in OZON_JS
    assert "_ozonFbsSyncOwnerOnlyShipmentQualityBtn" not in OZON_JS
    assert "is-closed" in OZON_JS
    assert ".ozon-fbs-fines-row.is-closed" in STYLE
    assert ".ozon-fbs-shipment-quality-body" not in STYLE
    assert "#ozonFbsFinesModal .ozon-fbs-fines-modal" in STYLE
    assert 'grid-template-areas:' in STYLE
    assert '"from to icons"' in STYLE
    assert "ozon-fbs-fines-filter-menu" in STYLE
    assert "ozon_fbs.js?v=193" in APP_HTML
    assert "style.css?v=412" in APP_HTML


def test_api_paths_present_in_web() -> None:
    web = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
    assert "/api/ozon-fbs/fines/settings" in web
    assert "/api/ozon-fbs/fines/sync" in web
    assert "/api/ozon-fbs/fines/sync/status" in web
    assert "/api/ozon-fbs/fines/import" in web
    assert "start_sync_thread" in web
    assert "/api/ozon-fbs/fines/units" in web
    assert "_require_ozon_fbs_fines_owner" in web
    assert "/api/ozon-fbs/shipment-quality/" not in web
    assert "ozon_fbs_shipment_quality" not in web
    assert not (ROOT / "review_processor" / "ozon_fbs_shipment_quality.py").exists()


def test_parse_accruals_report_slot_only() -> None:
    sample = Path(
        "/home/ubuntu/.cursor/projects/workspace/uploads/"
        "_____________________18.09.2026-21.09.2026_acc8.xlsx"
    )
    if not sample.exists():
        return
    rows = fines.parse_accruals_report_rows(sample.read_bytes())
    assert rows
    assert all(r["kind"] in ("fine", "storno") for r in rows)
    assert all(r["unit_number"] for r in rows)
    fines_n = sum(1 for r in rows if r["kind"] == "fine")
    storno_n = sum(1 for r in rows if r["kind"] == "storno")
    assert fines_n > 0 and storno_n > 0
    assert all(r["amount"] < 0 for r in rows if r["kind"] == "fine")
    assert all(r["amount"] > 0 for r in rows if r["kind"] == "storno")


def test_excel_synthetic_id_negative_and_stable() -> None:
    a = fines._excel_synthetic_accrual_id(
        unit_number="58520699-0157-1",
        event_date=date(2026, 9, 18),
        amount=Decimal("36.99"),
        kind="storno",
    )
    b = fines._excel_synthetic_accrual_id(
        unit_number="58520699-0157-1",
        event_date=date(2026, 9, 18),
        amount=Decimal("36.99"),
        kind="storno",
    )
    assert a == b and a < 0
    c = fines._excel_synthetic_accrual_id(
        unit_number="58520699-0157-1",
        event_date=date(2026, 9, 18),
        amount=Decimal("-36.99"),
        kind="fine",
    )
    assert c != a and c < 0


def test_status_closes_when_storno_offsets_fine() -> None:
    """API fine + Excel storno → closed (green) via net sum."""
    assert fines._status_for_net(Decimal("-36.99") + Decimal("36.99")) == "closed"
    assert fines._status_for_net(Decimal("-36.99")) == "open"


def test_fatal_auth_error_detection() -> None:
    assert fines._is_fatal_ozon_auth_error(
        RuntimeError('Ozon HTTP 403: {"code":7,"message":"Api-key is deactivated, use another one"}')
    )
    assert fines._is_fatal_ozon_auth_error(
        RuntimeError('Ozon HTTP 403: Api-Key is missing a required role for a method')
    )
    assert not fines._is_fatal_ozon_auth_error(RuntimeError("Ozon HTTP 429: rate limit"))
    assert not fines._is_fatal_ozon_auth_error(RuntimeError("network error"))


def test_background_sync_helpers_present() -> None:
    src = (ROOT / "review_processor" / "ozon_fbs_fines.py").read_text(encoding="utf-8")
    assert "def start_sync_thread(" in src
    assert "def get_sync_status(" in src
    assert "_is_fatal_ozon_auth_error" in src
    assert "threading.Thread" in src
    assert "pg_type_typname_nsp_index" in src


def test_default_sync_window() -> None:
    d0, d1 = fines.default_sync_dates()
    assert isinstance(d0, date) and isinstance(d1, date)
    assert d1 >= d0
    assert (d1 - d0).days == 14


def test_fetch_day_stops_on_stable_cursor_not_page_size() -> None:
    """Pagination must not assume fixed page size of 1000."""
    src = (ROOT / "review_processor" / "ozon_fbs_fines.py").read_text(encoding="utf-8")
    start = src.find("def _fetch_day_accruals(")
    end = src.find("\ndef sync_range(", start)
    chunk = src[start:end]
    assert "len(chunk) < 1000" not in chunk
    assert "new_count == 0" in chunk
    assert "new_last == last_id" in chunk
