"""Supply boxes: skip WB trbx fetch when local boxes_json is already cached."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from review_processor import wb_fbs


class TestNeedFetchSupplyBoxes(unittest.TestCase):
    def test_fetch_when_empty_or_missing(self) -> None:
        self.assertTrue(wb_fbs.need_fetch_supply_boxes(None))
        self.assertTrue(wb_fbs.need_fetch_supply_boxes([]))
        self.assertTrue(wb_fbs.need_fetch_done_supply_boxes(None))
        self.assertTrue(wb_fbs.need_fetch_done_supply_boxes([]))

    def test_skip_when_cached(self) -> None:
        self.assertFalse(wb_fbs.need_fetch_supply_boxes([{"id": "WB-TRBX-1"}]))
        self.assertFalse(wb_fbs.need_fetch_done_supply_boxes([{"id": "WB-TRBX-1"}]))


class _FakeConn:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def __enter__(self) -> "_FakeConn":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _sql: str, _params: object = None) -> "_FakeConn":
        return self

    def fetchall(self) -> list[dict]:
        return list(self._rows)


class _FakeRepo:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows or []

    def _connect(self) -> _FakeConn:
        return _FakeConn(self._rows)

    def _sql(self, query: str) -> str:
        return query

    def _row_to_dict(self, row: object) -> dict:
        return dict(row)  # type: ignore[arg-type]


class TestCachedSupplyBoxesById(unittest.TestCase):
    def test_loads_non_empty_and_missing(self) -> None:
        repo = _FakeRepo(
            [
                {
                    "supply_id": "WB-GI-CACHED",
                    "boxes_json": '[{"id":"WB-TRBX-1"},{"id":"WB-TRBX-2"}]',
                },
                {"supply_id": "WB-GI-EMPTY", "boxes_json": "[]"},
            ]
        )
        got = wb_fbs.cached_supply_boxes_by_id(
            repo,  # type: ignore[arg-type]
            user_id=1,
            source_id=10,
            supply_ids=["WB-GI-CACHED", "WB-GI-EMPTY", "WB-GI-MISSING"],
        )
        self.assertEqual(len(got["WB-GI-CACHED"]), 2)
        self.assertEqual(got["WB-GI-EMPTY"], [])
        self.assertNotIn("WB-GI-MISSING", got)
        self.assertTrue(wb_fbs.need_fetch_supply_boxes(got.get("WB-GI-EMPTY")))
        self.assertFalse(wb_fbs.need_fetch_supply_boxes(got.get("WB-GI-CACHED")))
        self.assertTrue(wb_fbs.need_fetch_supply_boxes(got.get("WB-GI-MISSING")))

    def test_empty_ids_short_circuit(self) -> None:
        repo = _FakeRepo([{"supply_id": "X", "boxes_json": "[]"}])
        self.assertEqual(
            wb_fbs.cached_supply_boxes_by_id(
                repo,  # type: ignore[arg-type]
                user_id=1,
                source_id=10,
                supply_ids=[],
            ),
            {},
        )


class TestSyncSkipsDoneTrbxWhenCached(unittest.TestCase):
    """sync_wb_fbs_source skips get_supply_boxes when local boxes_json is cached."""

    def test_open_and_uncached_done_fetch_boxes_cached_skips(self) -> None:
        box_calls: list[str] = []
        order_id_calls: list[str] = []
        upserted: list[tuple[str, list]] = []

        class FakeClient:
            def __init__(self, _key: str) -> None:
                pass

            def get_new_orders(self):
                return []

            def get_orders_page(self, **_kwargs):
                return [], None

            def get_statuses(self, _ids):
                return []

            def get_supplies(self, **_kwargs):
                return [
                    {"id": "WB-GI-OPEN", "name": "open", "done": False},
                    {"id": "WB-GI-OPEN-CACHED", "name": "open-cached", "done": False},
                    {"id": "WB-GI-DONE-CACHED", "name": "cached", "done": True},
                    {"id": "WB-GI-DONE-NEW", "name": "new-done", "done": True},
                ], 0

            def get_supply_order_ids(self, sid: str):
                order_id_calls.append(sid)
                return [101] if sid.startswith("WB-GI-OPEN") else []

            def get_supply_boxes(self, sid: str):
                box_calls.append(sid)
                return [{"id": f"BOX-{sid}"}]

        def fake_upsert(_repo, *, user_id, source_id, supply, order_ids=None, boxes=None):
            upserted.append((str(supply.get("id") or ""), list(boxes or [])))

        repo = _FakeRepo([])
        with (
            patch.object(wb_fbs, "WbFbsClient", FakeClient),
            patch.object(wb_fbs, "ensure_wb_fbs_tables"),
            patch.object(wb_fbs, "upsert_supply", side_effect=fake_upsert),
            patch.object(wb_fbs, "upsert_order"),
            patch.object(
                wb_fbs,
                "cached_supply_boxes_by_id",
                return_value={
                    "WB-GI-OPEN-CACHED": [{"id": "WB-TRBX-OPEN"}],
                    "WB-GI-DONE-CACHED": [{"id": "WB-TRBX-9"}],
                },
            ),
            patch.object(wb_fbs.time, "sleep", lambda _s: None),
        ):
            result = wb_fbs.sync_wb_fbs_source(
                repo,  # type: ignore[arg-type]
                user_id=1,
                source_id=10,
                api_key="dummy",
                lookback_days=1,
            )

        self.assertFalse(result.get("scope_error"))
        self.assertEqual(result.get("supplies"), 4)
        # Open without cache + done without cache still fetch boxes.
        self.assertIn("WB-GI-OPEN", box_calls)
        self.assertIn("WB-GI-DONE-NEW", box_calls)
        # Cached open and cached done skip boxes.
        self.assertNotIn("WB-GI-OPEN-CACHED", box_calls)
        self.assertNotIn("WB-GI-DONE-CACHED", box_calls)
        # Open supplies still refresh order-ids even when boxes are cached.
        self.assertIn("WB-GI-OPEN", order_id_calls)
        self.assertIn("WB-GI-OPEN-CACHED", order_id_calls)
        self.assertNotIn("WB-GI-DONE-CACHED", order_id_calls)

        by_id = {sid: boxes for sid, boxes in upserted}
        self.assertEqual(by_id["WB-GI-OPEN"], [{"id": "BOX-WB-GI-OPEN"}])
        self.assertEqual(by_id["WB-GI-DONE-NEW"], [{"id": "BOX-WB-GI-DONE-NEW"}])
        # Empty list → upsert_supply keeps previous non-empty boxes_json.
        self.assertEqual(by_id["WB-GI-OPEN-CACHED"], [])
        self.assertEqual(by_id["WB-GI-DONE-CACHED"], [])


class TestSyncStatusRefreshAgeFilter(unittest.TestCase):
    """Status refresh SQL must pass a 7-day created_at_wb cutoff."""

    def test_status_query_filters_by_created_at_wb(self) -> None:
        executed: list[tuple[str, tuple]] = []

        class _StatusConn:
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return None

            def execute(self, sql: str, params=None):
                executed.append((sql, tuple(params or ())))
                return self

            def fetchall(self):
                return []

        class _StatusRepo(_FakeRepo):
            def _connect(self):
                return _StatusConn()

            def reconcile_wb_fbs_stock_orders(self, **_kwargs):
                return {}

            def list_supply_productions(self, **_kwargs):
                return []

        class FakeClient:
            def __init__(self, _key: str) -> None:
                pass

            def get_new_orders(self):
                return []

            def get_orders_page(self, **_kwargs):
                return [], None

            def get_statuses(self, _ids):
                return []

            def get_supplies(self, **_kwargs):
                return [], 0

            def get_supply_order_ids(self, _sid: str):
                return []

            def get_supply_boxes(self, _sid: str):
                return []

        repo = _StatusRepo()
        before = datetime.now(UTC)
        with (
            patch.object(wb_fbs, "WbFbsClient", FakeClient),
            patch.object(wb_fbs, "ensure_wb_fbs_tables"),
            patch.object(wb_fbs, "upsert_supply"),
            patch.object(wb_fbs, "upsert_order"),
            patch.object(wb_fbs, "cached_supply_boxes_by_id", return_value={}),
            patch.object(wb_fbs.time, "sleep", lambda _s: None),
        ):
            wb_fbs.sync_wb_fbs_source(
                repo,  # type: ignore[arg-type]
                user_id=1,
                source_id=10,
                api_key="dummy",
                lookback_days=2,
            )
        after = datetime.now(UTC)

        status_calls = [
            (sql, params)
            for sql, params in executed
            if "created_at_wb >=" in sql and "tab IN" in sql
        ]
        self.assertEqual(len(status_calls), 1)
        sql, params = status_calls[0]
        self.assertIn("created_at_wb IS NOT NULL", sql)
        self.assertEqual(params[0], 1)
        self.assertEqual(params[1], 10)
        cutoff = datetime.fromisoformat(str(params[2]))
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=UTC)
        expected = before - timedelta(days=wb_fbs.STATUS_REFRESH_MAX_AGE_DAYS)
        self.assertGreaterEqual(cutoff, expected - timedelta(seconds=2))
        self.assertLessEqual(
            cutoff, after - timedelta(days=wb_fbs.STATUS_REFRESH_MAX_AGE_DAYS) + timedelta(seconds=2)
        )


if __name__ == "__main__":
    unittest.main()
