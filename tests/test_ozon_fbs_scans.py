"""Tests for Ozon FBS scan journal."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs_scans as scans


class OzonFbsScanJournalTests(unittest.TestCase):
    @patch("review_processor.ozon_fbs_scans.ensure_ozon_fbs_scan_tables")
    def test_insert_posting_scan(self, _ensure: MagicMock) -> None:
        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        repo._insert_and_get_id.return_value = 42
        conn.execute.return_value.fetchone.return_value = {
            "id": 42,
            "scan_type": scans.SCAN_LOOKUP,
            "scan_raw": "!qr",
            "posting_number": "PN-1",
            "matched_posting_numbers_json": "[]",
        }
        repo._row_to_dict = lambda r: dict(r)
        item = scans.insert_posting_scan(
            repo,
            user_id=1,
            source_id=2,
            payload={
                "scan_type": scans.SCAN_LOOKUP,
                "scan_raw": "!qr",
                "posting_number": "PN-1",
            },
        )
        self.assertEqual(item.get("posting_number"), "PN-1")
        repo._insert_and_get_id.assert_called_once()

    @patch("review_processor.ozon_fbs_scans.ensure_ozon_fbs_scan_tables")
    def test_list_posting_scans(self, _ensure: MagicMock) -> None:
        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        conn.execute.return_value.fetchall.return_value = [
            {
                "id": 1,
                "scan_type": scans.SCAN_ASSEMBLY,
                "scan_raw": "QR1",
                "posting_number": "PN-1",
                "matched_posting_numbers_json": "[]",
            }
        ]
        repo._row_to_dict = lambda r: dict(r)
        out = scans.list_posting_scans(repo, user_id=1, source_id=2, limit=10)
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["items"][0]["scan_type"], scans.SCAN_ASSEMBLY)


if __name__ == "__main__":
    unittest.main()
