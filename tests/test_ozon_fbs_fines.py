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
    assert "function openOzonFbsFinesModal(" in OZON_JS
    assert "function syncOzonFbsFines(" in OZON_JS
    assert "_ozonFbsSyncOwnerOnlyFinesBtn" in OZON_JS
    assert "openOzonFbsShipmentQualityModal" not in OZON_JS
    assert "_ozonFbsSyncOwnerOnlyShipmentQualityBtn" not in OZON_JS
    assert "is-closed" in OZON_JS
    assert ".ozon-fbs-fines-row.is-closed" in STYLE
    assert ".ozon-fbs-shipment-quality-body" not in STYLE
    assert "ozon_fbs.js?v=191" in APP_HTML
    assert "style.css?v=409" in APP_HTML


def test_api_paths_present_in_web() -> None:
    web = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
    assert "/api/ozon-fbs/fines/settings" in web
    assert "/api/ozon-fbs/fines/sync" in web
    assert "/api/ozon-fbs/fines/units" in web
    assert "_require_ozon_fbs_fines_owner" in web
    assert "/api/ozon-fbs/shipment-quality/" not in web
    assert "ozon_fbs_shipment_quality" not in web
    assert not (ROOT / "review_processor" / "ozon_fbs_shipment_quality.py").exists()


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
