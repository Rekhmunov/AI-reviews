"""WB FBS ops log: retention = sync lookback days from gear."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class WbFbsOpsLogTests(unittest.TestCase):
    def test_actor_label(self):
        from review_processor import wb_fbs_ops_log as ops

        self.assertEqual(
            ops.actor_label({"full_name": "Иван", "email": "a@b.c"}),
            "Иван",
        )
        self.assertEqual(ops.actor_label({"email": "a@b.c"}), "a@b.c")
        self.assertEqual(ops.actor_label({"id": 3}), "user:3")

    def test_append_never_raises(self):
        from review_processor import wb_fbs_ops_log as ops

        repo = MagicMock()
        repo._connect.side_effect = RuntimeError("db down")
        self.assertIsNone(
            ops.append_event(repo, user_id=1, action="sync_start", message="x")
        )

    @patch("review_processor.wb_fbs_ops_log.cleanup_old_events", return_value=0)
    @patch("review_processor.wb_fbs_ops_log.ensure_wb_fbs_ops_log_table")
    def test_append_inserts(self, _ensure, _cleanup):
        from review_processor import wb_fbs_ops_log as ops

        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        repo._connect.return_value.__exit__.return_value = False
        repo._sql = lambda sql: sql
        repo._insert_and_get_id.return_value = 11
        out = ops.append_event(
            repo,
            user_id=2,
            action=ops.ACTION_AUTO_COLLECT,
            message="Автосбор МГТ",
            actor_name="авто",
        )
        self.assertEqual(out["id"], 11)
        self.assertEqual(out["action"], ops.ACTION_AUTO_COLLECT)

    @patch("review_processor.wb_fbs_ops_log._lookback_days", return_value=5)
    @patch("review_processor.wb_fbs_ops_log.cleanup_old_events", return_value=1)
    @patch("review_processor.wb_fbs_ops_log.ensure_wb_fbs_ops_log_table")
    def test_list_events_retention(self, _ensure, cleanup, _lb):
        from review_processor import wb_fbs_ops_log as ops

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
                actor_user_id=None,
                actor_name="авто",
                source_id=1,
                created_at="2026-08-30T12:00:00+00:00",
                action="auto_sync",
                level="info",
                message="Автосинхронизация",
                order_id="",
                supply_id="",
                details_json="{}",
            ),
            _Row(
                id=1,
                actor_user_id=1,
                actor_name="A",
                source_id=1,
                created_at="2026-08-30T11:00:00+00:00",
                action="settings",
                level="info",
                message="settings",
                order_id="",
                supply_id="",
                details_json="{}",
            ),
        ]
        out = ops.list_events(repo, user_id=9, after_id=0, limit=50)
        self.assertEqual(out["retention_days"], 5)
        self.assertEqual([x["id"] for x in out["items"]], [1, 2])
        self.assertEqual(cleanup.call_args.kwargs.get("lookback_days"), 5)

    def test_cleanup_sql_uses_lookback(self):
        from review_processor import wb_fbs_ops_log as ops

        ops._last_cleanup_at.clear()
        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        repo._connect.return_value.__exit__.return_value = False
        repo._sql = lambda sql: sql
        cur = MagicMock()
        cur.rowcount = 3
        conn.execute.return_value = cur
        with patch.object(ops, "ensure_wb_fbs_ops_log_table"):
            deleted = ops.cleanup_old_events(
                repo, user_id=4, lookback_days=7, force=True
            )
        self.assertEqual(deleted, 3)
        self.assertIn("INTERVAL '7 days'", conn.execute.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
