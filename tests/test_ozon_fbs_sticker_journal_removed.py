"""Ozon FBS: sticker lookup modal replaced; scan journal remains off."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs_scans as scans

ROOT = Path(__file__).resolve().parents[1]


def test_shipment_quality_modal_has_no_scan_journal_ui() -> None:
    html = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
    js = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")

    assert 'id="ozonFbsShipmentQualityModal"' in html
    assert "ozonFbsStickerLookupJournalTbody" not in html
    assert "Журнал сканов" not in html.split('id="ozonFbsShipmentQualityModal"', 1)[1].split(
        'id="ozonFbsOrdersTable"', 1
    )[0]
    assert "loadOzonFbsPostingScansJournal" not in js
    assert "ozon_fbs.js?v=142" in html


def test_record_posting_scan_skips_persistent_journal_keeps_ops_log() -> None:
    repo = MagicMock()
    with (
        patch.object(scans, "insert_posting_scan") as insert_mock,
        patch("review_processor.ozon_fbs_ops_log.log_scan_event") as log_mock,
    ):
        item = scans.record_posting_scan(
            repo,
            user_id=1,
            source_id=2,
            scan_type=scans.SCAN_LOOKUP,
            scan_raw="901963382044000",
            posting_number="PN-1",
        )
    insert_mock.assert_not_called()
    log_mock.assert_called_once()
    assert item is not None
    assert item["posting_number"] == "PN-1"
    assert item["scan_type"] == scans.SCAN_LOOKUP
