"""Daily AI hard stop (1000) + Moscow day boundary helpers."""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from review_processor.repository import (
    AI_USAGE_ALERT_THRESHOLD,
    AI_USAGE_DAILY_LIMIT,
    ai_usage_today,
)
from review_processor.service import MarketplaceSyncError, ReviewAutomationService


class AiUsageDailyLimitTests(unittest.TestCase):
    def test_constants(self) -> None:
        self.assertEqual(AI_USAGE_ALERT_THRESHOLD, 500)
        self.assertEqual(AI_USAGE_DAILY_LIMIT, 1000)
        self.assertLess(AI_USAGE_ALERT_THRESHOLD, AI_USAGE_DAILY_LIMIT)

    def test_ai_usage_today_uses_moscow(self) -> None:
        # 2026-10-01 23:30 UTC == 2026-10-02 02:30 MSK
        utc = datetime(2026, 10, 1, 23, 30, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(ai_usage_today(now=utc), "2026-10-02")
        # Still previous Moscow day just before midnight MSK
        before_msk_midnight = datetime(2026, 10, 1, 20, 59, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(ai_usage_today(now=before_msk_midnight), "2026-10-01")

    def test_classify_blocked_when_daily_limit_reached(self) -> None:
        repo = mock.Mock()
        repo.get_ai_usage_requests_for_date.return_value = AI_USAGE_DAILY_LIMIT
        service = ReviewAutomationService(repository=repo)
        with self.assertRaises(MarketplaceSyncError) as ctx:
            service._classify_with_yandex_target_debug(
                review=mock.Mock(text="ok", rating=5, metadata={}),
                settings={"yandex_api_key": "k", "yandex_folder_id": "f"},
                user_id=1,
                strict=False,
            )
        self.assertTrue(bool(ctx.exception.details.get("daily_limit_reached")))
        self.assertEqual(ctx.exception.details.get("scope"), "classification")
        repo.get_ai_settings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
