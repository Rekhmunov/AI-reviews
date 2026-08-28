"""Ozon FBS sync lookback settings (gear next to Sync)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class OzonFbsSyncLookbackTests(unittest.TestCase):
    def test_normalize_clamps_to_1_30_default_3(self):
        from review_processor.repository import ReviewRepository

        repo = ReviewRepository.__new__(ReviewRepository)
        self.assertEqual(repo._normalize_ozon_fbs_sync_lookback_days(None), 3)
        self.assertEqual(repo._normalize_ozon_fbs_sync_lookback_days(0), 1)
        self.assertEqual(repo._normalize_ozon_fbs_sync_lookback_days(7), 7)
        self.assertEqual(repo._normalize_ozon_fbs_sync_lookback_days(99), 30)
        self.assertEqual(repo._normalize_ozon_fbs_sync_lookback_days("x"), 3)

    @patch("review_processor.repository.ReviewRepository._connect")
    def test_get_settings(self, connect_mock):
        from review_processor.repository import ReviewRepository

        conn = MagicMock()
        connect_mock.return_value.__enter__.return_value = conn
        connect_mock.return_value.__exit__.return_value = False

        class _Row(dict):
            pass

        conn.execute.return_value.fetchone.return_value = _Row(
            ozon_fbs_sync_lookback_days=5
        )
        repo = ReviewRepository.__new__(ReviewRepository)
        repo._sql = lambda sql: sql
        repo._bool_db = lambda x: x
        out = ReviewRepository.get_ozon_fbs_sync_settings(repo, user_id=1)
        self.assertEqual(out["lookback_days"], 5)
        self.assertEqual(out["lookback_days_min"], 1)
        self.assertEqual(out["lookback_days_max"], 30)

    def test_default_lookback_constant(self):
        from review_processor import ozon_fbs as oz

        self.assertEqual(oz.DEFAULT_LOOKBACK_DAYS, 3)


if __name__ == "__main__":
    unittest.main()
