"""WB FBS «Возвраты ПВЗ»: issue dates in the table, 31-day WB order window."""

from __future__ import annotations

import inspect
import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from review_processor import wb_fbs_pvz_returns as pvz
from review_processor import wb_fbs_returns as returns


ROOT = Path(__file__).resolve().parents[1]


class PvzWindowTests(unittest.TestCase):
    def test_issue_day_queries_31_days_ending_that_day(self):
        start, end = pvz.issue_range("2026-10-19", "2026-10-19")
        self.assertEqual((start, end), (date(2026, 10, 19), date(2026, 10, 19)))
        self.assertEqual(pvz.wb_query_window(end), ("2026-09-19", "2026-10-19"))

    def test_shorter_issue_range_still_queries_31_days_to_the_end(self):
        start, end = pvz.issue_range("2026-10-17", "2026-10-19")
        self.assertEqual(start, date(2026, 10, 17))
        self.assertEqual(end, date(2026, 10, 19))
        self.assertEqual(pvz.wb_query_window(end), ("2026-09-19", "2026-10-19"))

    def test_issue_range_clamps_to_31_days(self):
        start, end = pvz.issue_range("2026-09-01", "2026-10-19")
        self.assertEqual(end, date(2026, 10, 19))
        self.assertEqual((end - start).days + 1, 31)

    def test_default_returns_chunk_splits_31_days_pvz_chunk_does_not(self):
        """Existing «Возвраты» stays on 30-day chunks. PVZ asks for one 31-day call."""
        split = returns.iter_goods_return_windows("2026-09-19", "2026-10-19")
        self.assertGreater(len(split), 1)
        one = returns.iter_goods_return_windows(
            "2026-09-19",
            "2026-10-19",
            chunk_days=returns.GOODS_RETURN_MAX_WINDOW_DAYS,
        )
        self.assertEqual(one, [("2026-09-19", "2026-10-19")])
        sig = inspect.signature(returns.sync_goods_returns)
        self.assertEqual(
            sig.parameters["chunk_days"].default,
            returns.GOODS_RETURN_CHUNK_DAYS,
        )

    def test_issued_filter_keeps_completed_day_only(self):
        start, end = date(2026, 10, 17), date(2026, 10, 19)
        issued = {
            "status": "Выдано",
            "completed_dt": "2026-10-19T14:53:06",
            "order_dt": "2026-09-28T10:00:00",
        }
        in_transit = {
            "status": "В пути в пвз",
            "completed_dt": "",
            "order_dt": "2026-10-19T08:00:00",
        }
        too_early = {
            "status": "Выдано",
            "completed_dt": "2026-10-16T14:53:06",
        }
        self.assertTrue(pvz.row_issued_in_range(issued, start, end))
        self.assertFalse(pvz.row_issued_in_range(in_transit, start, end))
        self.assertFalse(pvz.row_issued_in_range(too_early, start, end))
        self.assertEqual(pvz.format_issued_label(issued["completed_dt"]), "19.10.2026 14:53")


class PvzAssembleTests(unittest.TestCase):
    def test_sort_does_not_merge_same_article(self):
        rows = [
            {
                "id": 2,
                "source_id": 1,
                "wb_order_id": 20,
                "srid": "b",
                "status": "Выдано",
                "completed_dt": "2026-10-19T14:53:06",
                "sticker_id": "",
                "shk_id": "",
                "barcode": "",
                "nm_id": 3,
            },
            {
                "id": 1,
                "source_id": 1,
                "wb_order_id": 10,
                "srid": "a",
                "status": "Выдано",
                "completed_dt": "2026-10-19T09:01:00",
                "sticker_id": "",
                "shk_id": "",
                "barcode": "",
                "nm_id": 1,
            },
            {
                "id": 3,
                "source_id": 1,
                "wb_order_id": 30,
                "srid": "c",
                "status": "В пути в пвз",
                "completed_dt": "2026-10-19T12:00:00",
                "sticker_id": "",
                "shk_id": "",
                "barcode": "",
                "nm_id": 9,
            },
        ]
        orders = {
            (1, 20): {
                "article": "nambambbort180200begbort",
                "nm_id": 3,
                "skus_json": "[]",
                "kiz_codes_json": "[]",
                "sticker_part_a": "1",
                "sticker_part_b": "3640",
            },
            (1, 10): {
                "article": "nambambbort160200begbort",
                "nm_id": 1,
                "skus_json": "[]",
                "kiz_codes_json": '["010460000000000021"]',
                "sticker_part_a": "1",
                "sticker_part_b": "7392",
            },
        }
        products = [
            {
                "id": 5,
                "name": "Наматрасник 180х200 см на резинке, толстый",
                "supplier_article": "nambambbort180200begbort",
                "wb_nmid": "3",
                "barcodes": ["4600000000002"],
                "barcode_label_name": "",
                "photo_path": "a.jpg",
            },
            {
                "id": 4,
                "name": "Наматрасник 160х200 см на резинке, толстый",
                "supplier_article": "nambambbort160200begbort",
                "wb_nmid": "1",
                "barcodes": ["4600000000001"],
                "barcode_label_name": "160",
                "photo_path": "b.jpg",
            },
        ]
        items = pvz.assemble_pvz_items(
            rows,
            orders=orders,
            products=products,
            date_from=date(2026, 10, 19),
            date_to=date(2026, 10, 19),
        )
        self.assertEqual([item["srid"] for item in items], ["a", "b"])
        self.assertEqual([item["qty"] for item in items], [1, 1])
        self.assertTrue(items[0]["has_kiz"])
        self.assertFalse(items[1]["has_kiz"])
        self.assertEqual(items[0]["issued_label"], "19.10.2026 09:01")
        self.assertEqual(items[0]["product_photo"], "/api/products/photo/4")

    def test_dedupe_prefers_row_matched_to_local_order(self):
        rows = [
            {
                "id": 1,
                "source_id": 1,
                "wb_order_id": 0,
                "srid": "same",
                "status": "Выдано",
                "completed_dt": "2026-10-19T14:53:06",
                "sticker_id": "",
                "shk_id": "",
                "barcode": "",
            },
            {
                "id": 2,
                "source_id": 2,
                "wb_order_id": 77,
                "srid": "same",
                "status": "Выдано",
                "completed_dt": "2026-10-19T14:53:06",
                "sticker_id": "",
                "shk_id": "",
                "barcode": "",
            },
        ]
        orders = {
            (2, 77): {
                "article": "art",
                "nm_id": 1,
                "skus_json": "[]",
                "kiz_codes_json": "[]",
                "sticker_part_a": "",
                "sticker_part_b": "10",
            }
        }
        items = pvz.assemble_pvz_items(
            rows,
            orders=orders,
            products=[],
            date_from=date(2026, 10, 19),
            date_to=date(2026, 10, 19),
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source_id"], 2)
        self.assertEqual(items[0]["order_id"], 77)


class PvzSyncTests(unittest.TestCase):
    def tearDown(self):
        pvz._pvz_jobs.clear()

    def test_sync_without_sources_asks_to_pick(self):
        repo = MagicMock()
        with patch.object(pvz, "settings_view", return_value={"sources": [], "source_ids": []}):
            with self.assertRaises(ValueError) as ctx:
                pvz.start_pvz_sync(
                    repo, user_id=1, date_from="2026-10-19", date_to="2026-10-19"
                )
        self.assertEqual(str(ctx.exception), pvz.EMPTY_SOURCES_MESSAGE)

    def test_sync_calls_existing_goods_return_with_31_day_window(self):
        repo = MagicMock()
        repo.get_supply_source_with_key.return_value = {
            "id": 7,
            "name": "Кабинет ФБС",
            "marketplace": "wb",
            "api_key": "mp",
            "analytics_api_key": "an",
        }
        with patch.object(
            pvz,
            "settings_view",
            return_value={
                "sources": [{"id": 7, "name": "Кабинет ФБС", "selected": True}],
                "source_ids": [7],
            },
        ), patch.object(
            pvz, "resolve_goods_return_api_keys", return_value=([("an", "source")], True)
        ), patch.object(
            pvz, "goods_return_rate_limit_status", return_value={"blocked": False}
        ), patch.object(
            pvz, "goods_return_token_cooldown_seconds", return_value=0
        ), patch.object(pvz, "sync_goods_returns", return_value={"ok": True}) as sync, patch(
            "review_processor.wb_kiz_circulation.get_wb_analytics_api_key",
            return_value=None,
        ):
            out = pvz.start_pvz_sync(
                repo, user_id=3, date_from="2026-10-19", date_to="2026-10-19"
            )
            self.assertEqual(out["status"], "running")
            deadline = time.time() + 3
            job = None
            while time.time() < deadline:
                job = pvz.get_pvz_sync_job(user_id=3)
                if job and job.get("status") != "running":
                    break
                time.sleep(0.02)
        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "ok")
        sync.assert_called_once()
        kwargs = sync.call_args.kwargs
        self.assertEqual(kwargs["date_from"], "2026-09-19")
        self.assertEqual(kwargs["date_to"], "2026-10-19")
        self.assertEqual(kwargs["chunk_days"], returns.GOODS_RETURN_MAX_WINDOW_DAYS)
        self.assertEqual(kwargs["source_id"], 7)


class PvzUiContractTests(unittest.TestCase):
    def test_button_is_visible_and_owner_gate_stays_on_returns(self):
        html = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
        restore = html.split('id="wbFbsKizRestoreBtn"', 1)[1].split("</button>", 1)[0]
        self.assertIn("hidden", restore)
        self.assertIn("Возвраты", restore)
        pvz_btn = html.split('id="wbFbsPvzReturnsBtn"', 1)[1].split("</button>", 1)[0]
        self.assertNotIn("hidden", pvz_btn)
        self.assertIn("Возвраты ПВЗ", pvz_btn)
        self.assertLess(html.index('id="wbFbsKizRestoreBtn"'), html.index('id="wbFbsPvzReturnsBtn"'))
        self.assertIn('src="/static/wb_fbs_pvz_returns.js?v=4"', html)
        self.assertIn("Отметьте кабинеты WB.", html)
        self.assertNotIn("Отметьте кабинеты WB FBS.", html)
        js = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
        gate = js.split("function _wbFbsSyncOwnerOnlyReturnsBtn()", 1)[1].split("function ", 1)[0]
        self.assertIn("wbFbsKizRestoreBtn", gate)
        self.assertNotIn("wbFbsPvzReturnsBtn", gate)
        pvz_js = (ROOT / "web_static" / "wb_fbs_pvz_returns.js").read_text(encoding="utf-8")
        self.assertIn("Нет источников WB.", pvz_js)
        self.assertNotIn("Нет источников WB FBS.", pvz_js)
        self.assertIn("Распечатать ШК", pvz_js)
        self.assertIn("Распечатать маркировку", pvz_js)
        self.assertIn("В таблице:", pvz_js)
        self.assertIn("Нет выданных возвратов за этот период", pvz_js)
        syncing = pvz_js.split("function _wbFbsPvzSetSyncing", 1)[1].split("function ", 1)[0]
        self.assertLess(
            syncing.index("toggleWbFbsPvzDatePanel(false)"),
            syncing.index("wbFbsPvzState.syncing = !!on"),
        )

    def test_settings_lists_all_wb_sources_not_only_fbs(self):
        repo = MagicMock()
        repo.list_supply_sources.return_value = [
            {"id": 1, "name": "ВБ основной", "marketplace": "wb"},
            {"id": 2, "name": "ФБС ВБ склад", "marketplace": "wb"},
            {"id": 3, "name": "Озон", "marketplace": "ozon"},
            {"id": 4, "name": "Wildberries FBO", "marketplace": "wildberries"},
        ]
        with patch.object(pvz, "saved_source_ids", return_value=[1, 2]):
            view = pvz.settings_view(repo, user_id=9)
        ids = [s["id"] for s in view["sources"]]
        self.assertEqual(ids, [1, 2, 4])
        self.assertEqual(view["source_ids"], [1, 2])
        selected = {s["id"]: s["selected"] for s in view["sources"]}
        self.assertTrue(selected[1])
        self.assertTrue(selected[2])
        self.assertFalse(selected[4])
