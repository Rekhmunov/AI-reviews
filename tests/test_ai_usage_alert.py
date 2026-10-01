"""AI usage warning banner: threshold dates + message formatting."""

from __future__ import annotations

import unittest

from review_processor.repository import (
    AI_USAGE_ALERT_THRESHOLD,
    compute_ai_usage_alert_dates,
    format_ai_usage_alert_message,
)


class AiUsageAlertLogicTests(unittest.TestCase):
    def test_threshold_constant(self) -> None:
        self.assertEqual(AI_USAGE_ALERT_THRESHOLD, 500)

    def test_compute_filters_dismissed_and_sorts(self) -> None:
        dates = compute_ai_usage_alert_dates(
            ["2026-10-02", "2026-10-01", "bad", "2026-10-01"],
            dismissed_dates=["2026-10-01"],
        )
        self.assertEqual(dates, ["2026-10-02"])

    def test_message_today_single(self) -> None:
        msg = format_ai_usage_alert_message(
            ["2026-10-01"],
            today="2026-10-01",
        )
        self.assertEqual(
            msg,
            "Внимание, за сегодня израсходовалось более 500 запросов. "
            "Нужно сообщить администратору сервиса.",
        )

    def test_message_past_single(self) -> None:
        msg = format_ai_usage_alert_message(
            ["2026-09-30"],
            today="2026-10-01",
        )
        self.assertIn("30.09.2026", msg)
        self.assertIn("более 500 запросов", msg)
        self.assertIn("администратору сервиса", msg)

    def test_message_multiple_dates(self) -> None:
        msg = format_ai_usage_alert_message(
            ["2026-10-01", "2026-09-30"],
            today="2026-10-01",
        )
        self.assertIn("30.09.2026", msg)
        self.assertIn("01.10.2026", msg)
        self.assertIn("следующие даты", msg)
        self.assertTrue(msg.index("30.09.2026") < msg.index("01.10.2026"))

    def test_empty_message(self) -> None:
        self.assertEqual(format_ai_usage_alert_message([], today="2026-10-01"), "")


if __name__ == "__main__":
    unittest.main()
