"""TTL cache + working-window for get_existing_classifications (auto-sync memory)."""

from __future__ import annotations

import time
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from review_processor import repository as repo_mod


class ClassificationsCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        repo_mod._CLASSIFICATIONS_CACHE.clear()

    def tearDown(self) -> None:
        repo_mod._CLASSIFICATIONS_CACHE.clear()

    def test_cache_hit_skips_second_db_query(self) -> None:
        repo = MagicMock(spec=repo_mod.ReviewRepository)
        repo._sql = lambda q: q
        row = {"review_uid": "r1", "grp": "positive", "sub": "ok"}
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchall.return_value = [row]
        repo._connect.return_value = conn
        repo._row_to_dict = lambda r: dict(r)

        with patch.object(repo_mod, "_CLASSIFICATIONS_CACHE_TTL_SEC", 300.0):
            first = repo_mod.ReviewRepository.get_existing_classifications(
                repo, user_id=1, date_from="2026-01-01"
            )
            second = repo_mod.ReviewRepository.get_existing_classifications(
                repo, user_id=1, date_from="2026-01-01"
            )

        self.assertEqual(first, {"r1": ("positive", "ok")})
        self.assertIs(first, second)
        self.assertEqual(conn.execute.call_count, 1)

    def test_ttl_expiry_reloads(self) -> None:
        repo = MagicMock(spec=repo_mod.ReviewRepository)
        repo._sql = lambda q: q
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchall.return_value = [
            {"review_uid": "r1", "grp": "positive", "sub": ""}
        ]
        repo._connect.return_value = conn
        repo._row_to_dict = lambda r: dict(r)

        with patch.object(repo_mod, "_CLASSIFICATIONS_CACHE_TTL_SEC", 0.05):
            repo_mod.ReviewRepository.get_existing_classifications(repo, user_id=7)
            time.sleep(0.07)
            repo_mod.ReviewRepository.get_existing_classifications(repo, user_id=7)

        self.assertEqual(conn.execute.call_count, 2)

    def test_invalidate_clears(self) -> None:
        repo = MagicMock(spec=repo_mod.ReviewRepository)
        repo_mod._CLASSIFICATIONS_CACHE[(3, "2026-01-01")] = (
            time.monotonic(),
            {"a": ("g", "s")},
        )
        repo_mod.ReviewRepository.invalidate_existing_classifications_cache(
            repo, user_id=3
        )
        self.assertNotIn((3, "2026-01-01"), repo_mod._CLASSIFICATIONS_CACHE)

    def test_date_from_passed_in_sql(self) -> None:
        repo = MagicMock(spec=repo_mod.ReviewRepository)
        repo._sql = lambda q: q
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchall.return_value = []
        repo._connect.return_value = conn
        repo._row_to_dict = lambda r: dict(r)

        with patch.object(repo_mod, "_CLASSIFICATIONS_CACHE_TTL_SEC", 0.0):
            repo_mod.ReviewRepository.get_existing_classifications(
                repo, user_id=1, date_from="2026-06-15"
            )

        sql, params = conn.execute.call_args[0]
        self.assertIn(">= ?", sql)
        self.assertEqual(params, (1, "2026-06-15"))

    def test_classifications_window_start_caps_old_sync_start(self) -> None:
        today = datetime.now(UTC).date()
        window = (today - timedelta(days=repo_mod.CLASSIFICATIONS_LOOKBACK_DAYS)).isoformat()
        old = (today - timedelta(days=400)).isoformat()
        self.assertEqual(repo_mod.classifications_window_start(old), window)

    def test_classifications_window_start_keeps_recent_sync_start(self) -> None:
        today = datetime.now(UTC).date()
        recent = (today - timedelta(days=10)).isoformat()
        self.assertEqual(repo_mod.classifications_window_start(recent), recent)


class WorkingWindowSqlTests(unittest.TestCase):
    def test_reviews_list_filters_by_created_date_not_updated_at(self) -> None:
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "review_processor" / "repository.py").read_text(
            encoding="utf-8"
        )
        # Smoke: period filter must use marketplace createdDate, not updated_at::date.
        self.assertIn("createdDate", src)
        self.assertNotIn("updated_at::date >=", src)
        self.assertNotIn("updated_at::date <=", src)


if __name__ == "__main__":
    unittest.main()
