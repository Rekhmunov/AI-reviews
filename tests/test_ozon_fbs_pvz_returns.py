"""Ozon FBS «Возвраты ПВЗ»: ReceivedBySeller cache + 31-day sync window."""

from __future__ import annotations

import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs_pvz_returns as pvz


ROOT = Path(__file__).resolve().parents[1]


class OzonPvzWindowTests(unittest.TestCase):
    def test_sync_display_range_is_last_31_days(self):
        start, end = pvz.sync_display_range(today=date(2026, 10, 20))
        self.assertEqual(end, date(2026, 10, 20))
        self.assertEqual(start, date(2026, 9, 20))
        self.assertEqual((end - start).days + 1, 31)
        self.assertEqual(pvz.ozon_query_window(end), ("2026-09-20", "2026-10-20"))

    def test_issue_range_clamps_to_31_days(self):
        start, end = pvz.issue_range("2026-09-01", "2026-10-19")
        self.assertEqual(end, date(2026, 10, 19))
        self.assertEqual((end - start).days + 1, 31)

    def test_issued_filter_keeps_received_day_only(self):
        start, end = date(2026, 10, 17), date(2026, 10, 19)
        issued = {
            "visual_status": "ReceivedBySeller",
            "completed_dt": "2026-10-19T14:53:06",
        }
        other = {
            "visual_status": "MovingToSeller",
            "completed_dt": "2026-10-19T14:53:06",
        }
        too_early = {
            "visual_status": "ReceivedBySeller",
            "completed_dt": "2026-10-16T14:53:06",
        }
        self.assertTrue(pvz.row_issued_in_range(issued, start, end))
        self.assertFalse(pvz.row_issued_in_range(other, start, end))
        self.assertFalse(pvz.row_issued_in_range(too_early, start, end))
        self.assertEqual(pvz.format_issued_label(issued["completed_dt"]), "19.10.2026 14:53")

    def test_extract_return_fields_from_api_row(self):
        fields = pvz._extract_return_fields(
            {
                "id": 99,
                "posting_number": "12345-0001-1",
                "order_id": 55,
                "order_number": "12345-0001",
                "visual": {
                    "status": {"sys_name": "ReceivedBySeller", "display_name": "Получен"},
                    "change_moment": "2026-10-19T11:53:06Z",
                },
                "product": {
                    "offer_id": "art-1",
                    "sku": 777,
                    "name": "Товар",
                    "quantity": 2,
                },
                "logistic": {"barcode": "RR123"},
            }
        )
        assert fields is not None
        self.assertEqual(fields["return_id"], 99)
        self.assertEqual(fields["posting_number"], "12345-0001-1")
        self.assertEqual(fields["offer_id"], "art-1")
        self.assertEqual(fields["sku"], "777")
        self.assertEqual(fields["quantity"], 2)
        self.assertEqual(fields["barcode"], "RR123")
        self.assertEqual(fields["visual_status"], "ReceivedBySeller")
        self.assertTrue(fields["completed_dt"].startswith("2026-10-19T"))


class OzonPvzAssembleTests(unittest.TestCase):
    def test_assemble_joins_posting_and_catalog(self):
        rows = [
            {
                "id": 1,
                "source_id": 3,
                "return_id": 10,
                "posting_number": "111-1",
                "order_id": 9,
                "visual_status": "ReceivedBySeller",
                "completed_dt": "2026-10-19T09:01:00",
                "offer_id": "art-a",
                "sku": "100",
                "product_name": "Ozon title",
                "quantity": 1,
                "barcode": "",
            },
            {
                "id": 2,
                "source_id": 3,
                "return_id": 11,
                "posting_number": "222-1",
                "order_id": 8,
                "visual_status": "MovingToSeller",
                "completed_dt": "2026-10-19T12:00:00",
                "offer_id": "art-b",
                "sku": "200",
                "product_name": "Skip",
                "quantity": 1,
                "barcode": "",
            },
        ]
        postings = {
            "111-1": {
                "source_id": 3,
                "posting_number": "111-1",
                "order_id": 9,
                "offer_id": "art-a",
                "sku": "100",
                "barcodes_json": '["4600000000001"]',
                "sticker_scanit": "iiABCDEFGH1234",
                "sticker_part_a": "111",
                "sticker_part_b": "1",
            }
        }
        products = [
            {
                "id": 5,
                "name": "Каталожное имя",
                "supplier_article": "art-a",
                "ozon_sku": "100",
                "barcodes": ["4600000000001"],
                "barcode_label_name": "",
                "photo_path": "/x.jpg",
                "product_category": "Текстиль",
            }
        ]
        items = pvz.assemble_pvz_items(
            rows,
            postings=postings,
            products=products,
            source_names={3: "Ozon FBS"},
            date_from=date(2026, 10, 17),
            date_to=date(2026, 10, 19),
        )
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["product_name"], "Каталожное имя")
        self.assertEqual(item["product_photo"], "/api/products/photo/5")
        self.assertTrue(item["order_linked"])
        self.assertEqual(item["sticker_scanit"], "iiABCDEFGH1234")
        self.assertEqual(item["catalog_barcodes"], ["4600000000001"])
        self.assertEqual(item["product_category"], "Текстиль")


class OzonPvzSettingsTests(unittest.TestCase):
    def test_settings_lists_only_enabled_ozon_fbs(self):
        repo = MagicMock()
        repo.list_supply_sources.return_value = [
            {"id": 1, "name": "Ozon FBS склад", "marketplace": "ozon", "is_enabled": True},
            {"id": 2, "name": "Ozon FBO", "marketplace": "ozon_fbo", "is_enabled": True},
            {"id": 3, "name": "WB", "marketplace": "wb", "is_enabled": True},
            {"id": 4, "name": "Выкл FBS", "marketplace": "ozon_fbs", "is_enabled": False},
            {"id": 5, "name": "Кабинет", "marketplace": "ozon_fbs", "is_enabled": True},
        ]
        with patch.object(pvz, "saved_source_ids", return_value=[1, 5]):
            view = pvz.settings_view(repo, user_id=9)
        ids = [s["id"] for s in view["sources"]]
        self.assertEqual(ids, [1, 5])
        self.assertEqual(view["source_ids"], [1, 5])
        selected = {s["id"]: s["selected"] for s in view["sources"]}
        self.assertTrue(selected[1])
        self.assertTrue(selected[5])


class OzonPvzSyncTests(unittest.TestCase):
    def test_sync_pagination_falls_back_to_max_return_id(self):
        repo = MagicMock()
        client = MagicMock()
        client.post_json.side_effect = [
            {
                "returns": [{"id": 10, "visual": {"status": {"sys_name": "ReceivedBySeller"}, "change_moment": "2026-10-19T12:00:00Z"}, "product": {"quantity": 1}}],
                "has_next": True,
                "last_id": 0,
            },
            {
                "returns": [],
                "has_next": False,
                "last_id": 10,
            },
        ]
        with patch.object(pvz.ozon, "OzonFbsClient", return_value=client), patch.object(
            pvz, "upsert_return_rows", side_effect=[1, 0]
        ) as upsert:
            total = pvz.sync_source_returns(
                repo,
                user_id=1,
                source_id=2,
                client_id="c",
                api_key="k",
                date_from="2026-09-19",
                date_to="2026-10-19",
            )
        self.assertEqual(total, 1)
        self.assertEqual(client.post_json.call_count, 2)
        second_body = client.post_json.call_args_list[1].args[1]
        self.assertEqual(second_body["last_id"], 10)
        self.assertEqual(upsert.call_count, 2)

    def test_start_sync_uses_31_day_window_and_ignores_calendar(self):

        repo = MagicMock()
        with patch.object(
            pvz,
            "settings_view",
            return_value={
                "sources": [{"id": 7, "name": "Ozon FBS", "selected": True}],
                "source_ids": [7],
            },
        ), patch.object(pvz, "sync_display_range", return_value=(date(2026, 9, 19), date(2026, 10, 19))), patch.object(
            pvz, "sync_source_returns", return_value=2
        ) as sync, patch.object(
            repo,
            "get_supply_source_with_key",
            return_value={
                "id": 7,
                "marketplace": "ozon_fbs",
                "client_id": "cid",
                "api_key": "key",
                "name": "Ozon FBS",
            },
        ), patch.object(pvz.ozon, "is_ozon_fbs_source", return_value=True):
            out = pvz.start_pvz_sync(
                repo, user_id=3, date_from="2026-10-01", date_to="2026-10-02"
            )
            self.assertEqual(out["status"], "running")
            self.assertEqual(out["date_from"], "2026-09-19")
            self.assertEqual(out["date_to"], "2026-10-19")
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
        self.assertEqual(kwargs["source_id"], 7)
        self.assertEqual(kwargs["client_id"], "cid")


class OzonPvzUiContractTests(unittest.TestCase):
    def test_button_modal_script_and_qr_giveout(self):
        html = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
        restore = html.split('id="ozonFbsKizRestoreBtn"', 1)[1].split("</button>", 1)[0]
        self.assertIn("hidden", restore)
        pvz_btn = html.split('id="ozonFbsPvzReturnsBtn"', 1)[1].split("</button>", 1)[0]
        self.assertNotIn("hidden", pvz_btn)
        self.assertIn("Возвраты ПВЗ", pvz_btn)
        self.assertLess(
            html.index('id="ozonFbsKizRestoreBtn"'),
            html.index('id="ozonFbsPvzReturnsBtn"'),
        )
        self.assertIn('src="/static/ozon_fbs_pvz_returns.js?v=2"', html)
        self.assertIn('href="/static/style.css?v=437"', html)
        self.assertIn('id="ozonFbsPvzReturnsModal"', html)
        self.assertIn('id="ozonFbsPvzQrBtn"', html)
        # Modals must live in Ozon FBS section — not WB FBS (parent .hidden
        # would hide the overlay while on Ozon tab / show it only on WB).
        ozon_sec = html.split('id="section-supplies-ozon-fbs"', 1)[1].split(
            "<section ", 1
        )[0]
        wb_sec = html.split('id="section-supplies-wb-fbs"', 1)[1].split(
            "<section ", 1
        )[0]
        self.assertIn('id="ozonFbsPvzReturnsModal"', ozon_sec)
        self.assertIn('id="ozonFbsPvzSettingsModal"', ozon_sec)
        self.assertNotIn('id="ozonFbsPvzReturnsModal"', wb_sec)
        self.assertNotIn('id="ozonFbsPvzSettingsModal"', wb_sec)
        self.assertIn("openOzonFbsPvzGiveout()", html)
        self.assertIn("printOzonFbsPvzList('merged')", html)
        toolbar = html.split('id="ozonFbsPvzReturnsModal"', 1)[1].split(
            'class="wb-fbs-pvz-toolbar"', 1
        )[1]
        self.assertLess(toolbar.index("ozonFbsPvzSyncBtn"), toolbar.index("ozonFbsPvzSettingsBtn"))
        self.assertLess(toolbar.index("ozonFbsPvzSettingsBtn"), toolbar.index("ozonFbsPvzPrintBtn"))
        self.assertLess(toolbar.index("ozonFbsPvzPrintBtn"), toolbar.index("ozonFbsPvzQrBtn"))
        self.assertLess(toolbar.index("ozonFbsPvzQrBtn"), toolbar.index("ozonFbsPvzFilterBtn"))
        self.assertLess(toolbar.index("ozonFbsPvzSourceFilter"), toolbar.index("ozonFbsPvzSearchFilter"))
        self.assertIn("Отметьте кабинеты Ozon FBS.", html)
        settings_btn = html.split('id="ozonFbsPvzSettingsBtn"', 1)[1].split("</button>", 1)[0]
        self.assertIn("hidden", settings_btn)

        js = (ROOT / "web_static" / "ozon_fbs_pvz_returns.js").read_text(encoding="utf-8")
        self.assertIn("openOzonReturnsModal", js)
        self.assertIn("openOzonFbsPvzGiveout", js)
        self.assertIn("/api/ozon-fbs/pvz-returns", js)
        self.assertNotIn("/api/wb-fbs/pvz-returns", js)
        self.assertNotIn("Распечатать маркировку", js)
        self.assertNotIn("printOzonFbsPvzKiz", js)
        self.assertIn("Распечатать ШК", js)
        self.assertIn("Дата получения", js)
        self.assertNotIn("Дата выдачи", js)
        self.assertIn('onclick="toggleOzonFbsPvzFilterPanel()"', html)
        self.assertNotIn("toggleOzonFbsPvzFilterPanel(event)", html)
        self.assertIn("_ozonFbsPvzSyncOwnerOnlySettingsBtn", js)
        self.assertIn("isTenantOwner", js)
        self.assertIn("Нет источников Ozon FBS.", js)
        self.assertIn("th.name, td.name { width: 80%; }", js)
        self.assertIn("Брак/утилизация", js)
        self.assertIn("ozonFbsPvzQrBtn", js)

        css = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
        self.assertIn("/* Ozon FBS — Возвраты ПВЗ */", css)
        self.assertIn("#ozonFbsPvzReturnsModal #ozonFbsPvzQrBtn", css)

        web_py = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
        self.assertIn("@app.get(\"/api/ozon-fbs/pvz-returns\")", web_py)
        self.assertIn("@app.post(\"/api/ozon-fbs/pvz-returns/sync\")", web_py)
        save_chunk = web_py.split("async def ozon_fbs_pvz_returns_settings_save", 1)[1].split(
            "@app.post", 1
        )[0]
        self.assertIn("_is_wb_fbs_tenant_owner", save_chunk)
        self.assertIn("только главному пользователю", save_chunk)


if __name__ == "__main__":
    unittest.main()
