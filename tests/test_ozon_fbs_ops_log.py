"""Ozon FBS ops log: retention = sync lookback days."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class OzonFbsOpsLogTests(unittest.TestCase):
    def test_actor_label_prefers_full_name(self):
        from review_processor import ozon_fbs_ops_log as ops

        self.assertEqual(
            ops.actor_label({"full_name": "Иван", "email": "a@b.c", "id": 1}),
            "Иван",
        )
        self.assertEqual(ops.actor_label({"email": "a@b.c", "id": 2}), "a@b.c")
        self.assertEqual(ops.actor_label({"id": 9}), "user:9")
        self.assertEqual(ops.actor_label(None), "")

    def test_append_event_never_raises(self):
        from review_processor import ozon_fbs_ops_log as ops

        repo = MagicMock()
        repo._connect.side_effect = RuntimeError("db down")
        out = ops.append_event(
            repo,
            user_id=1,
            action=ops.ACTION_SYNC_START,
            message="test",
        )
        self.assertIsNone(out)

    @patch("review_processor.ozon_fbs_ops_log.cleanup_old_events", return_value=0)
    @patch("review_processor.ozon_fbs_ops_log.ensure_ozon_fbs_ops_log_table")
    def test_append_event_inserts(self, _ensure, _cleanup):
        from review_processor import ozon_fbs_ops_log as ops

        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        repo._connect.return_value.__exit__.return_value = False
        repo._sql = lambda sql: sql
        repo._insert_and_get_id.return_value = 42

        out = ops.append_event(
            repo,
            user_id=7,
            action=ops.ACTION_COLLECT_START,
            message="Сборка запущена",
            actor_name="Оператор",
            source_id=3,
        )
        self.assertEqual(out["id"], 42)
        self.assertEqual(out["message"], "Сборка запущена")
        self.assertEqual(out["actor_name"], "Оператор")
        repo._insert_and_get_id.assert_called_once()

    @patch("review_processor.ozon_fbs_ops_log._lookback_days", return_value=3)
    @patch("review_processor.ozon_fbs_ops_log.cleanup_old_events", return_value=2)
    @patch("review_processor.ozon_fbs_ops_log.ensure_ozon_fbs_ops_log_table")
    def test_list_events_returns_retention(self, _ensure, cleanup, _lb):
        from review_processor import ozon_fbs_ops_log as ops

        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        repo._connect.return_value.__exit__.return_value = False
        repo._sql = lambda sql: sql
        repo._row_to_dict.side_effect = lambda r: r

        class _Row(dict):
            pass

        conn.execute.return_value.fetchall.return_value = [
            _Row(
                id=2,
                actor_user_id=1,
                actor_name="A",
                source_id=1,
                created_at="2026-08-30T10:00:00+00:00",
                action="sync_start",
                level="info",
                message="start",
                posting_number="",
                supply_id="",
                details_json="{}",
            ),
            _Row(
                id=1,
                actor_user_id=1,
                actor_name="A",
                source_id=1,
                created_at="2026-08-30T09:00:00+00:00",
                action="settings",
                level="info",
                message="lookback",
                posting_number="",
                supply_id="",
                details_json="{}",
            ),
        ]

        out = ops.list_events(repo, user_id=1, after_id=0, limit=50)
        self.assertTrue(out["ok"])
        self.assertEqual(out["retention_days"], 3)
        self.assertEqual(out["lookback_days"], 3)
        self.assertEqual(out["count"], 2)
        # DESC fetch is reversed to chronological order
        self.assertEqual([x["id"] for x in out["items"]], [2, 1])
        cleanup.assert_called()
        kwargs = cleanup.call_args.kwargs
        self.assertEqual(kwargs.get("lookback_days"), 3)
        self.assertTrue(kwargs.get("force"))

    def test_cleanup_uses_lookback_interval(self):
        from review_processor import ozon_fbs_ops_log as ops

        # Reset throttle so this call runs
        ops._last_cleanup_at.clear()
        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        repo._connect.return_value.__exit__.return_value = False
        repo._sql = lambda sql: sql
        cur = MagicMock()
        cur.rowcount = 5
        conn.execute.return_value = cur

        with patch.object(ops, "ensure_ozon_fbs_ops_log_table"):
            deleted = ops.cleanup_old_events(
                repo, user_id=11, lookback_days=3, force=True
            )
        self.assertEqual(deleted, 5)
        sql = conn.execute.call_args[0][0]
        self.assertIn("INTERVAL '3 days'", sql)
        self.assertIn("user_id", sql)


if __name__ == "__main__":
    unittest.main()
