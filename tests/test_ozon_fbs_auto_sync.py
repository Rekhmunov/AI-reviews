"""Ozon FBS auto-sync settings and manual-sync block (isolated from WB FBS)."""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from review_processor import ozon_fbs as oz


MSK = ZoneInfo("Europe/Moscow")


class OzonFbsAutoSyncHelpersTests(unittest.TestCase):
    def test_msk_window_daytime(self):
        now = datetime(2026, 10, 26, 15, 0, tzinfo=MSK)
        self.assertTrue(
            oz.msk_time_in_active_window(
                now_msk=now, active_from="12:00", active_to="18:00"
            )
        )
        self.assertFalse(
            oz.msk_time_in_active_window(
                now_msk=now, active_from="18:00", active_to="20:00"
            )
        )

    def test_msk_window_overnight(self):
        night = datetime(2026, 10, 26, 23, 30, tzinfo=MSK)
        morning = datetime(2026, 10, 27, 5, 0, tzinfo=MSK)
        midday = datetime(2026, 10, 27, 12, 0, tzinfo=MSK)
        self.assertTrue(
            oz.msk_time_in_active_window(
                now_msk=night, active_from="22:00", active_to="06:00"
            )
        )
        self.assertTrue(
            oz.msk_time_in_active_window(
                now_msk=morning, active_from="22:00", active_to="06:00"
            )
        )
        self.assertFalse(
            oz.msk_time_in_active_window(
                now_msk=midday, active_from="22:00", active_to="06:00"
            )
        )

    def test_manual_sync_block_payload(self):
        now = datetime(2026, 10, 26, 22, 30, tzinfo=MSK)
        settings = {
            "manual_sync_block_enabled": True,
            "manual_sync_block_from": "22:00",
            "manual_sync_block_to": "23:00",
        }
        payload = oz.manual_sync_block_payload(settings, now_msk=now)
        self.assertTrue(payload["manual_sync_blocked"])
        self.assertIn("22:00", payload["manual_sync_block_message"])

        settings["manual_sync_block_enabled"] = False
        payload = oz.manual_sync_block_payload(settings, now_msk=now)
        self.assertFalse(payload["manual_sync_blocked"])

    def test_manual_sync_block_equal_times_not_active(self):
        """Default 00:00–00:00 must not lock Sync when toggle is on by mistake."""
        now = datetime(2026, 10, 26, 12, 0, tzinfo=MSK)
        settings = {
            "manual_sync_block_enabled": True,
            "manual_sync_block_from": "00:00",
            "manual_sync_block_to": "00:00",
        }
        self.assertFalse(oz.manual_sync_blocked_now(settings, now_msk=now))
        payload = oz.manual_sync_block_payload(settings, now_msk=now)
        self.assertFalse(payload["manual_sync_blocked"])

    def test_auto_sync_is_due_without_last(self):
        self.assertTrue(oz.auto_sync_is_due(last_synced_at=None, interval_minutes=30))


class OzonFbsSyncSettingsRepoTests(unittest.TestCase):
    def test_normalize_interval(self):
        from review_processor.repository import ReviewRepository

        repo = ReviewRepository.__new__(ReviewRepository)
        self.assertEqual(repo._normalize_ozon_fbs_auto_sync_interval_minutes(30), 30)
        self.assertEqual(repo._normalize_ozon_fbs_auto_sync_interval_minutes(99), 60)
        self.assertEqual(repo._normalize_ozon_fbs_auto_sync_interval_minutes(None), 60)

    def test_save_rejects_equal_block_window(self):
        from review_processor.repository import ReviewRepository

        repo = ReviewRepository.__new__(ReviewRepository)
        with self.assertRaises(ValueError) as ctx:
            ReviewRepository.save_ozon_fbs_sync_settings(
                repo,
                user_id=1,
                lookback_days=3,
                manual_sync_block_enabled=True,
                manual_sync_block_from="00:00",
                manual_sync_block_to="00:00",
            )
        self.assertIn("интервал", str(ctx.exception).lower())

    @patch("review_processor.repository.ReviewRepository._connect")
    def test_get_settings_includes_auto_fields(self, connect_mock):
        from review_processor.repository import ReviewRepository

        conn = MagicMock()
        connect_mock.return_value.__enter__.return_value = conn
        connect_mock.return_value.__exit__.return_value = False

        class _Row(dict):
            pass

        conn.execute.return_value.fetchone.return_value = _Row(
            ozon_fbs_sync_lookback_days=2,
            ozon_fbs_auto_sync_enabled=True,
            ozon_fbs_auto_sync_interval_minutes=30,
            ozon_fbs_auto_sync_active_from="22:00",
            ozon_fbs_auto_sync_active_to="23:00",
            ozon_fbs_last_synced_at=None,
            ozon_fbs_last_auto_synced_at=None,
            ozon_fbs_manual_sync_block_enabled=True,
            ozon_fbs_manual_sync_block_from="22:00",
            ozon_fbs_manual_sync_block_to="23:00",
        )
        repo = ReviewRepository.__new__(ReviewRepository)
        repo._sql = lambda sql: sql
        repo._bool_db = lambda x: x
        repo._row_to_dict = lambda row: dict(row)
        repo._iso_or_none = lambda v: None
        out = ReviewRepository.get_ozon_fbs_sync_settings(repo, user_id=1)
        self.assertEqual(out["lookback_days"], 2)
        self.assertTrue(out["enabled"])
        self.assertEqual(out["interval_minutes"], 30)
        self.assertEqual(out["active_from"], "22:00")
        self.assertTrue(out["manual_sync_block_enabled"])
        self.assertNotIn("collect_mgt_enabled", out)


class OzonFbsAutoSyncUiContractTests(unittest.TestCase):
    def test_modal_has_auto_sync_and_block_controls(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        html = (root / "web_templates" / "app.html").read_text(encoding="utf-8")
        js = (root / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
        self.assertIn("Автоматическая синхронизация", html)
        self.assertIn('id="ozonFbsAutoSyncEnabled"', html)
        self.assertIn('id="ozonFbsManualSyncBlockEnabled"', html)
        self.assertIn("Блокировать кнопку «Синхронизировать»", html)
        self.assertNotIn("Автосбор МГТ", html.split('id="ozonFbsSyncSettingsModal"', 1)[1].split('id="ozonFbsTabs"', 1)[0])
        self.assertIn("onOzonFbsAutoSyncToggle", js)
        self.assertIn("manual_sync_block_enabled", js)
        self.assertIn("OzonFbsScheduler", (root / "review_processor" / "ozon_fbs.py").read_text(encoding="utf-8"))
        web_py = (root / "review_processor" / "web.py").read_text(encoding="utf-8")
        self.assertIn("ozon_fbs_scheduler.start()", web_py)
        self.assertIn("ozon_fbs_scheduler.stop()", web_py)
        # Isolation: Ozon scheduler must not call WB sync.
        oz_py = (root / "review_processor" / "ozon_fbs.py").read_text(encoding="utf-8")
        self.assertIn("class OzonFbsScheduler", oz_py)
        self.assertNotIn("wb_fbs.start_sync_thread", oz_py)
        self.assertNotIn("WbFbsScheduler", oz_py)


if __name__ == "__main__":
    unittest.main()
