"""WB FBS «Возвраты» — scan journal and goods-return sync."""

from __future__ import annotations

import json
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from review_processor import wb_fbs_returns as returns
from review_processor import wb_fbs as wb


def _fake_wb_jwt(*, uid: int = 1, scopes: int = wb.WB_SCOPE_ANALYTICS | wb.WB_SCOPE_MARKETPLACE) -> str:
    import base64
    import json

    header = base64.urlsafe_b64encode(b'{"alg":"ES256"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"uid": uid, "s": scopes}, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.sig"


class GoodsReturnWindowTests(unittest.TestCase):
    def test_iter_goods_return_windows_splits_90_days(self):
        windows = returns.iter_goods_return_windows("2026-01-01", "2026-03-31")
        self.assertEqual(len(windows), 3)
        self.assertEqual(windows[0][0], "2026-01-01")
        self.assertEqual(windows[-1][1], "2026-03-31")
        for win_from, win_to in windows:
            span = (
                date.fromisoformat(win_to) - date.fromisoformat(win_from)
            ).days + 1
            self.assertLessEqual(span, returns.GOODS_RETURN_MAX_WINDOW_DAYS)

    def test_iter_goods_return_windows_single_month(self):
        windows = returns.iter_goods_return_windows("2026-08-01", "2026-08-20")
        self.assertEqual(windows, [("2026-08-01", "2026-08-20")])

    def test_clamp_goods_return_sync_range_limits_to_90_days(self):
        df, dt, clamped = returns.clamp_goods_return_sync_range(
            "2025-01-01", "2026-08-27"
        )
        self.assertTrue(clamped)
        span = (
            date.fromisoformat(dt) - date.fromisoformat(df)
        ).days + 1
        self.assertLessEqual(span, returns.GOODS_RETURN_DEFAULT_TOTAL_DAYS)


class GoodsReturnUpsertTests(unittest.TestCase):
    def test_upsert_skips_unchanged_srid(self):
        repo = MagicMock()
        repo._sql = lambda sql: sql
        repo._row_to_dict = lambda row: dict(row)

        class _Result:
            def __init__(self, payload):
                self._payload = payload

            def fetchone(self):
                return self._payload[0] if self._payload else None

        raw = json.dumps({"orderId": 1, "srid": "s1", "status": "ok"})
        values = (1, 2, 1, "st", "", "", None, "s1", "ok", "", "", "", "", raw, "now")
        conn = MagicMock()
        conn.execute = MagicMock(return_value=_Result([{"raw_json": raw}]))
        outcome = returns._upsert_goods_return_row(
            conn,
            repo,
            user_id=1,
            source_id=2,
            values=values,
            raw_json=raw,
            srid="s1",
            order_id=1,
            sticker_id="st",
        )
        self.assertEqual(outcome, "unchanged")
        self.assertEqual(conn.execute.call_count, 1)


class GoodsReturnMatchTests(unittest.TestCase):
    def _repo_with_goods_returns(self, rows: list[dict]):
        repo = MagicMock()
        repo._sql = lambda sql: sql
        repo._row_to_dict = lambda row: dict(row)

        class _Result:
            def __init__(self, payload):
                self._payload = payload

            def fetchall(self):
                return self._payload

        conn = MagicMock()
        conn.execute = MagicMock(side_effect=lambda sql, params=None: _Result(rows))
        repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
        repo._connect.return_value.__exit__ = MagicMock(return_value=False)
        return repo

    @patch("review_processor.wb_fbs_returns.wb.ensure_wb_fbs_tables")
    @patch("review_processor.wb_fbs_returns.ensure_wb_fbs_returns_tables")
    def test_find_goods_return_by_sticker_id(self, _ensure_ret, _ensure_wb):
        repo = self._repo_with_goods_returns(
            [
                {
                    "sticker_id": "44556677",
                    "wb_order_id": 900001,
                    "barcode": "",
                    "shk_id": "",
                }
            ]
        )
        hit = returns.find_goods_return_by_scan(
            repo, user_id=1, source_id=2, scan="44556677"
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["wb_order_id"], 900001)

    @patch("review_processor.wb_fbs_returns.wb.ensure_wb_fbs_tables")
    @patch("review_processor.wb_fbs_returns.ensure_wb_fbs_returns_tables")
    def test_find_goods_return_by_barcode(self, _ensure_ret, _ensure_wb):
        repo = self._repo_with_goods_returns(
            [
                {
                    "sticker_id": "",
                    "wb_order_id": 900002,
                    "barcode": "2000000000123",
                    "shk_id": "",
                }
            ]
        )
        hit = returns.find_goods_return_by_scan(
            repo, user_id=1, source_id=2, scan="2000000000123"
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["wb_order_id"], 900002)

    @patch("review_processor.wb_fbs_returns.wb.ensure_wb_fbs_tables")
    @patch("review_processor.wb_fbs_returns.ensure_wb_fbs_returns_tables")
    def test_find_goods_return_by_srid(self, _ensure_ret, _ensure_wb):
        repo = self._repo_with_goods_returns(
            [
                {
                    "sticker_id": "",
                    "srid": "abc123def456",
                    "wb_order_id": 900003,
                    "barcode": "",
                    "shk_id": "",
                }
            ]
        )
        hit = returns.find_goods_return_by_scan(
            repo, user_id=1, source_id=2, scan="abc123def456"
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["wb_order_id"], 900003)


class ReturnScanDuplicateTests(unittest.TestCase):
    @patch("review_processor.wb_fbs_returns._insert_return_scan")
    @patch("review_processor.wb_fbs_returns._kiz_codes_for_order", return_value=[])
    @patch("review_processor.wb_fbs_returns._product_from_order", return_value={})
    @patch("review_processor.wb_fbs_returns._resolve_order_row", return_value=None)
    @patch("review_processor.wb_fbs_returns._return_scan_duplicate")
    def test_return_sticker_duplicate(self, dup, _order, _prod, _kiz, _insert):
        dup.return_value = {
            "id": 11,
            "scan_type": "return_sticker",
            "return_sticker_id": "12345",
            "matched_order_ids_json": "[]",
            "product_barcodes_json": "[]",
        }
        repo = MagicMock()
        result = returns._process_return_sticker_scan(
            repo,
            user_id=1,
            source_id=2,
            api_key="k",
            scan="12345",
            goods_row={"sticker_id": "12345", "wb_order_id": 1},
        )
        _insert.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "duplicate")


class ReturnStickerKizLinkTests(unittest.TestCase):
    @patch("review_processor.wb_fbs_returns._insert_return_scan")
    @patch("review_processor.wb_fbs_returns._kiz_codes_for_order")
    @patch("review_processor.wb_fbs_returns._product_from_order", return_value={"product_name": "Товар"})
    @patch("review_processor.wb_fbs_returns._resolve_order_row")
    @patch("review_processor.wb_fbs_returns._return_scan_duplicate", return_value=None)
    def test_return_sticker_passes_srid_for_kiz_lookup(
        self, _dup, resolve_order, _prod, kiz_lookup, insert
    ):
        resolve_order.return_value = {
            "order_id": 5525061048,
            "sticker_part_a": "1",
            "sticker_part_b": "2345",
            "sticker_barcode": "qr",
        }
        kiz_lookup.return_value = ["010467012345678921CIRC"]
        insert.return_value = {
            "id": 21,
            "scan_type": "return_sticker",
            "order_id": 5525061048,
            "kiz_code": "010467012345678921CIRC",
            "matched_order_ids_json": "[]",
            "product_barcodes_json": "[]",
        }
        repo = MagicMock()
        result = returns._process_return_sticker_scan(
            repo,
            user_id=1,
            source_id=2,
            api_key="k",
            scan="99887766",
            goods_row={
                "sticker_id": "99887766",
                "wb_order_id": 5525061048,
                "srid": "eI.i0a39f75abc.1.0",
            },
        )
        self.assertTrue(result["ok"])
        kiz_lookup.assert_called_once()
        kwargs = kiz_lookup.call_args.kwargs
        self.assertEqual(kwargs["order_id"], 5525061048)
        self.assertEqual(kwargs["srid_hint"], "eI.i0a39f75abc.1.0")
        self.assertEqual(result["item"]["kiz_code"], "010467012345678921CIRC")


class KizScanTests(unittest.TestCase):
    @patch("review_processor.wb_fbs_returns._insert_return_scan")
    @patch("review_processor.wb_fbs_returns._product_from_gtin", return_value={})
    @patch("review_processor.wb_fbs_returns._catalog_barcodes_index", return_value={})
    @patch("review_processor.wb_fbs_returns.kiz_restore.find_kiz_in_local_database")
    @patch("review_processor.wb_fbs_returns.kiz_restore.looks_like_kiz_scan", return_value=True)
    @patch("review_processor.wb_fbs_returns.kiz_restore.normalize_kiz_mark", side_effect=lambda x: x)
    @patch("review_processor.wb_fbs_returns.kiz_restore.extract_gtin14", return_value="04670123456789")
    def test_kiz_scan_gtin_not_in_catalog_warns(
        self,
        _gtin,
        _norm,
        _looks,
        db_hit,
        _catalog,
        _prod,
        insert,
    ):
        db_hit.return_value = {"found": False, "order_ids": []}
        insert.return_value = {"id": 6, "scan_type": "kiz", "kiz_code": "010467012345678921X"}
        repo = MagicMock()
        result = returns.process_return_scan(
            repo,
            user_id=1,
            source_id=2,
            api_key="k",
            scan="010467012345678921X",
        )
        self.assertTrue(result["ok"])
        self.assertIn("GTIN не найден в каталоге товаров", result["item"].get("warning", ""))

    @patch("review_processor.wb_fbs_returns._insert_return_scan")
    @patch("review_processor.wb_fbs_returns._product_from_gtin", return_value={})
    @patch("review_processor.wb_fbs_returns.kiz_restore.find_kiz_in_local_database")
    @patch("review_processor.wb_fbs_returns.kiz_restore.looks_like_kiz_scan", return_value=True)
    @patch("review_processor.wb_fbs_returns.kiz_restore.normalize_kiz_mark", side_effect=lambda x: x)
    @patch("review_processor.wb_fbs_returns.kiz_restore.extract_gtin14", return_value="04670123456789")
    def test_kiz_scan_not_in_local_db_warns(
        self,
        _gtin,
        _norm,
        _looks,
        db_hit,
        _prod,
        insert,
    ):
        db_hit.return_value = {"found": False, "order_ids": []}
        insert.return_value = {"id": 5, "scan_type": "kiz", "kiz_code": "010467012345678921X"}
        repo = MagicMock()
        result = returns.process_return_scan(
            repo,
            user_id=1,
            source_id=2,
            api_key="k",
            scan="010467012345678921X",
        )
        self.assertTrue(result["ok"])
        self.assertIn("warning", result["item"])


class ReturnCatalogFieldsTests(unittest.TestCase):
    def test_catalog_fields_from_product(self):
        out = returns._catalog_fields_from_product(
            {
                "barcodes": ["2038564013653", "4670123456789"],
                "barcode_label_name": "Этикетка",
            }
        )
        self.assertEqual(out["catalog_barcodes"], ["2038564013653", "4670123456789"])
        self.assertEqual(out["barcode_label_name"], "Этикетка")

    def test_enrich_return_scan_catalog_fields_by_article(self):
        repo = MagicMock()
        repo.list_product_photos.return_value = [
            {
                "supplier_article": "art-1",
                "barcodes": ["2038564013653"],
                "barcode_label_name": "Под этикетку",
            }
        ]
        item = returns._enrich_return_scan_catalog_fields(
            repo,
            user_id=1,
            item={"product_article": "art-1"},
        )
        self.assertEqual(item["catalog_barcodes"], ["2038564013653"])
        self.assertEqual(item["barcode_label_name"], "Под этикетку")


class GoodsReturnHttpErrorTests(unittest.TestCase):
    def test_format_retry_hint_seconds(self):
        hint = returns._format_wb_retry_hint("1800")
        self.assertIn("30 мин", hint)

    def test_format_retry_hint_unix_timestamp_msk(self):
        # 2026-08-25 00:47:17 UTC = 03:47 MSK
        hint = returns._format_wb_retry_hint("1787618837")
        self.assertIn("МСК", hint)
        self.assertIn("03:47", hint)

    def test_format_goods_return_http_error_429(self):
        err = returns.format_wb_goods_return_http_error(
            code=429,
            body='{"status":429}',
            retry_after="900",
        )
        self.assertIn("Лимит WB", str(err))
        self.assertIn("15 мин", str(err))


class ListReturnScansTests(unittest.TestCase):
    def test_return_scans_search_sql_empty(self):
        clause, params = returns._return_scans_search_sql("")
        self.assertEqual(clause, "")
        self.assertEqual(params, [])

    def test_return_scans_search_sql_pattern(self):
        clause, params = returns._return_scans_search_sql("5525")
        self.assertIn("ILIKE", clause)
        self.assertEqual(len(params), 10)
        self.assertTrue(all(p == "%5525%" for p in params))

    @patch("review_processor.wb_fbs_returns._enrich_return_scan_catalog_fields", side_effect=lambda _repo, **kwargs: kwargs["item"])
    @patch("review_processor.wb_fbs_returns._catalog_by_article_index", return_value={})
    @patch("review_processor.wb_fbs_returns.ensure_wb_fbs_returns_tables")
    def test_list_return_scans_has_more(self, _ensure, _catalog, _enrich):
        repo = MagicMock()
        row = {
            "id": 1,
            "user_id": 1,
            "source_id": 2,
            "scanned_at": "2025-01-01T00:00:00+00:00",
            "scan_type": "return_sticker",
            "scan_raw": "x",
            "return_sticker_id": "",
            "order_id": 1,
            "assembly_sticker_barcode": "",
            "assembly_sticker_number": "",
            "kiz_code": "",
            "matched_order_ids_json": "[]",
            "product_name": "",
            "product_article": "",
            "product_photo": "",
            "product_barcodes_json": "[]",
            "gtin14": "",
            "duplicate_of_id": None,
        }
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [row, row]
        repo._connect.return_value.__enter__.return_value = conn
        repo._row_to_dict.side_effect = lambda r: dict(r)
        repo._sql.side_effect = lambda q: q

        result = returns.list_return_scans(
            repo,
            user_id=1,
            source_id=2,
            limit=1,
            offset=0,
        )
        self.assertTrue(result["has_more"])
        self.assertEqual(len(result["items"]), 1)


class ReturnOrderPreviewTests(unittest.TestCase):
    @patch("review_processor.wb_fbs_returns._kiz_codes_for_order", return_value=["010467012345678921PREV"])
    @patch("review_processor.wb_fbs_returns._product_from_order", return_value={"product_name": "Товар", "product_article": "art-1"})
    @patch("review_processor.wb_fbs_returns._goods_return_srid_hint", return_value="eI.test.1.0")
    @patch("review_processor.wb_fbs_returns._resolve_order_row")
    def test_build_return_order_preview(self, resolve_order, _srid, _prod, _kiz):
        resolve_order.return_value = {
            "order_id": 5525061048,
            "sticker_part_a": "1",
            "sticker_part_b": "9999",
            "sticker_barcode": "qr1",
        }
        repo = MagicMock()
        out = returns.build_return_order_preview(
            repo,
            user_id=1,
            source_id=2,
            order_id=5525061048,
            api_key="k",
        )
        self.assertTrue(out["found"])
        item = out["item"]
        self.assertTrue(item["preview"])
        self.assertIsNone(item["id"])
        self.assertEqual(item["scan_type"], "lookup")
        self.assertEqual(item["order_id"], 5525061048)
        self.assertEqual(item["kiz_code"], "010467012345678921PREV")

    @patch("review_processor.wb_fbs_returns._resolve_order_row", return_value=None)
    def test_build_return_order_preview_not_found(self, _resolve):
        repo = MagicMock()
        out = returns.build_return_order_preview(
            repo, user_id=1, source_id=2, order_id=999, api_key="k"
        )
        self.assertFalse(out["found"])


class ExportCsvTests(unittest.TestCase):
    def test_export_return_scans_csv_has_bom(self):
        csv_text = returns.export_return_scans_csv(
            [
                {
                    "scanned_at": "2026-01-01T10:00:00+00:00",
                    "scan_type": "return_sticker",
                    "order_id": 1,
                    "return_sticker_id": "99",
                    "assembly_sticker_number": "13640",
                    "kiz_code": "KIZ",
                    "product_name": "Товар",
                    "product_article": "art-1",
                    "product_barcodes": ["123"],
                }
            ]
        )
        self.assertTrue(csv_text.startswith("\ufeff"))
        self.assertIn("Товар", csv_text)

    def test_export_goods_returns_csv_has_bom_and_fields(self):
        csv_text = returns.export_goods_returns_csv(
            [
                {
                    "wb_order_id": 900001,
                    "sticker_id": "54628560521",
                    "barcode": "1680063403480",
                    "shk_id": "23411783472",
                    "srid": "ad3817664d3046c5a8d55054d8be96d6",
                    "nm_id": 12862181,
                    "status": "Готов к выдаче",
                    "reason": "Цвет",
                    "order_dt": "2026-08-20",
                    "ready_to_return_dt": "2026-08-21",
                    "completed_dt": "",
                    "synced_at": "2026-08-27T10:00:00+00:00",
                    "raw_json": json.dumps(
                        {
                            "returnType": "Возврат товара",
                            "brand": "TestBrand",
                            "subjectName": "Рубашки",
                            "dstOfficeAddress": "Москва",
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        )
        self.assertTrue(csv_text.startswith("\ufeff"))
        self.assertIn("54628560521", csv_text)
        self.assertIn("TestBrand", csv_text)
        self.assertIn("stickerId", csv_text)

    @patch("review_processor.wb_fbs_returns.ensure_wb_fbs_returns_tables")
    def test_list_goods_returns_date_filter(self, _ensure):
        repo = MagicMock()
        repo._sql = lambda sql: sql

        class _Result:
            def fetchall(self):
                return [{"wb_order_id": 1, "sticker_id": "99", "raw_json": "{}"}]

        conn = MagicMock()
        conn.execute = MagicMock(return_value=_Result())
        repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
        repo._connect.return_value.__exit__ = MagicMock(return_value=False)
        repo._row_to_dict = lambda row: dict(row)

        rows = returns.list_goods_returns(
            repo,
            user_id=1,
            source_id=2,
            date_from="2026-08-01",
            date_to="2026-08-31",
        )
        self.assertEqual(len(rows), 1)
        sql = conn.execute.call_args[0][0]
        self.assertIn("order_dt", sql)


class GoodsReturnSourceFilterTests(unittest.TestCase):
    def test_goods_return_row_matches_source_by_order_id(self):
        matchers = {"order_ids": {9001}, "nm_ids": {100}}
        self.assertTrue(
            returns._goods_return_row_matches_source(
                order_id=9001,
                srid="",
                nm_id=100,
                matchers=matchers,
                srid_to_order={},
            )
        )
        self.assertFalse(
            returns._goods_return_row_matches_source(
                order_id=9002,
                srid="",
                nm_id=100,
                matchers=matchers,
                srid_to_order={},
            )
        )

    def test_goods_return_row_matches_source_by_srid(self):
        matchers = {"order_ids": {9001}, "nm_ids": set()}
        self.assertTrue(
            returns._goods_return_row_matches_source(
                order_id=0,
                srid="abc.1.0",
                nm_id=None,
                matchers=matchers,
                srid_to_order={"abc.1.0": 9001},
            )
        )

    def test_goods_return_row_matches_source_by_nm_when_no_order(self):
        matchers = {"order_ids": set(), "nm_ids": {555}}
        self.assertTrue(
            returns._goods_return_row_matches_source(
                order_id=0,
                srid="",
                nm_id=555,
                matchers=matchers,
                srid_to_order={},
            )
        )

    def test_goods_return_row_matches_source_by_barcode(self):
        matchers = {"order_ids": set(), "nm_ids": set(), "barcodes": {"2001900289005"}}
        self.assertTrue(
            returns._goods_return_row_matches_source(
                order_id=0,
                srid="",
                nm_id=None,
                barcode="2001900289005",
                matchers=matchers,
                srid_to_order={},
            )
        )

    def test_goods_return_row_matches_confirmed_marketplace_order(self):
        matchers = {"order_ids": set(), "nm_ids": set(), "barcodes": set()}
        self.assertTrue(
            returns._goods_return_row_matches_source(
                order_id=777,
                srid="",
                nm_id=None,
                matchers=matchers,
                srid_to_order={},
                confirmed_order_ids={777},
            )
        )

    def test_goods_return_row_matches_srid_via_confirmed_order(self):
        matchers = {"order_ids": set(), "nm_ids": set(), "barcodes": set()}
        self.assertTrue(
            returns._goods_return_row_matches_source(
                order_id=0,
                srid="abchex",
                nm_id=None,
                matchers=matchers,
                srid_to_order={"abchex": 888},
                confirmed_order_ids={888},
            )
        )

    def test_resolve_goods_return_api_key_prefers_source(self):
        source = _fake_wb_jwt(uid=11, scopes=wb.WB_SCOPE_ANALYTICS | wb.WB_SCOPE_MARKETPLACE)
        fallback = _fake_wb_jwt(uid=22, scopes=wb.WB_SCOPE_ANALYTICS)
        key, src, trust = returns.resolve_goods_return_api_key(
            source_api_key=source,
            fallback_analytics_key=fallback,
        )
        self.assertEqual(key, source)
        self.assertEqual(src, "source")
        self.assertTrue(trust)

    def test_resolve_goods_return_api_key_falls_back_to_settings(self):
        fallback = _fake_wb_jwt(uid=11, scopes=wb.WB_SCOPE_ANALYTICS)
        key, src, trust = returns.resolve_goods_return_api_key(
            source_api_key="",
            fallback_analytics_key=fallback,
        )
        self.assertEqual(key, fallback)
        self.assertEqual(src, "settings")
        self.assertFalse(trust)

    def test_resolve_goods_return_api_key_uses_settings_when_source_marketplace_only(self):
        source = _fake_wb_jwt(uid=11, scopes=wb.WB_SCOPE_MARKETPLACE)
        fallback = _fake_wb_jwt(uid=11, scopes=wb.WB_SCOPE_ANALYTICS)
        key, src, trust = returns.resolve_goods_return_api_key(
            source_api_key=source,
            fallback_analytics_key=fallback,
        )
        self.assertEqual(key, fallback)
        self.assertEqual(src, "settings")
        self.assertTrue(trust)

    def test_resolve_goods_return_api_key_uses_source_analytics_first(self):
        source = _fake_wb_jwt(uid=11, scopes=wb.WB_SCOPE_MARKETPLACE)
        source_analytics = _fake_wb_jwt(uid=11, scopes=wb.WB_SCOPE_ANALYTICS)
        fallback = _fake_wb_jwt(uid=22, scopes=wb.WB_SCOPE_ANALYTICS)
        key, src, trust = returns.resolve_goods_return_api_key(
            source_api_key=source,
            source_analytics_api_key=source_analytics,
            fallback_analytics_key=fallback,
        )
        self.assertEqual(key, source_analytics)
        self.assertEqual(src, "source_analytics")
        self.assertTrue(trust)

    def test_resolve_goods_return_api_key_rejects_mismatched_settings(self):
        source = _fake_wb_jwt(uid=11, scopes=wb.WB_SCOPE_MARKETPLACE)
        fallback = _fake_wb_jwt(uid=22, scopes=wb.WB_SCOPE_ANALYTICS)
        with self.assertRaises(RuntimeError) as ctx:
            returns.resolve_goods_return_api_key(
                source_api_key=source,
                fallback_analytics_key=fallback,
            )
        self.assertIn("другому кабинету", str(ctx.exception))

    def test_goods_return_report_trusted_for_source_key(self):
        self.assertTrue(returns.goods_return_report_trusted("source"))
        self.assertFalse(returns.goods_return_report_trusted("settings"))
        self.assertFalse(returns.goods_return_report_trusted(""))

    def test_goods_return_row_trusted_accepts_without_local_order(self):
        matchers = {"order_ids": set(), "nm_ids": set(), "barcodes": set()}
        self.assertTrue(
            returns._goods_return_row_matches_source(
                order_id=0,
                srid="abchex123",
                nm_id=100,
                matchers=matchers,
                srid_to_order={},
                trust_report=True,
            )
        )

    @patch("review_processor.wb_fbs_returns._purge_foreign_goods_returns_in_range", return_value=0)
    @patch("review_processor.wb_fbs_returns.fetch_goods_return_report")
    @patch("review_processor.wb_fbs_returns.ensure_wb_fbs_returns_tables")
    @patch("review_processor.wb_fbs_returns._load_source_goods_return_matchers")
    def test_sync_goods_returns_trusted_source_stores_unmatched_rows(
        self,
        load_matchers,
        _ensure,
        fetch_report,
        _purge,
    ):
        load_matchers.return_value = {"order_ids": set(), "nm_ids": set(), "barcodes": set()}
        fetch_report.return_value = [
            {"orderId": 0, "nmId": 555, "srid": "hexsrid", "stickerId": "999"},
        ]
        repo = MagicMock()
        repo._sql = lambda sql: sql
        conn = MagicMock()
        repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
        repo._connect.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "review_processor.wb_fbs_returns._upsert_goods_return_row",
            return_value="inserted",
        ) as upsert:
            out = returns.sync_goods_returns(
                repo,
                user_id=1,
                source_id=10,
                api_key="source-key",
                date_from="2026-08-01",
                date_to="2026-08-10",
                api_key_source="source",
                trust_report=True,
                api_key_candidates=[("source-key", "source")],
            )

        self.assertEqual(out["skipped_foreign"], 0)
        self.assertTrue(out["report_trusted"])
        self.assertEqual(upsert.call_count, 1)

    @patch("review_processor.wb_fbs_returns._purge_foreign_goods_returns_in_range", return_value=0)
    @patch("review_processor.wb_fbs_returns.fetch_goods_return_report")
    @patch("review_processor.wb_fbs_returns.ensure_wb_fbs_returns_tables")
    @patch("review_processor.wb_fbs_returns._load_source_goods_return_matchers")
    def test_sync_goods_returns_skips_foreign_rows(
        self,
        load_matchers,
        _ensure,
        fetch_report,
        _purge,
    ):
        load_matchers.return_value = {"order_ids": {9001}, "nm_ids": {100}, "barcodes": set()}
        fetch_report.return_value = [
            {"orderId": 9001, "nmId": 100, "srid": "keep.1.0", "stickerId": "111"},
            {"orderId": 9002, "nmId": 200, "srid": "skip.1.0", "stickerId": "222"},
        ]
        repo = MagicMock()
        repo._sql = lambda sql: sql
        conn = MagicMock()
        repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
        repo._connect.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "review_processor.wb_fbs_returns.wb.order_ids_by_srids",
            return_value={"keep.1.0": 9001, "skip.1.0": 9002},
        ), patch(
            "review_processor.wb_fbs_returns._upsert_goods_return_row",
            return_value="inserted",
        ) as upsert:
            out = returns.sync_goods_returns(
                repo,
                user_id=1,
                source_id=10,
                api_key="k",
                date_from="2026-08-01",
                date_to="2026-08-10",
                trust_report=False,
                api_key_candidates=[("k", "settings")],
            )

        self.assertEqual(out["skipped_foreign"], 1)
        self.assertEqual(upsert.call_count, 1)
        self.assertEqual(upsert.call_args.kwargs["order_id"], 9001)

    @patch("review_processor.wb_fbs_returns._purge_foreign_goods_returns_in_range", return_value=0)
    @patch("review_processor.wb_fbs_returns.fetch_goods_return_report")
    @patch("review_processor.wb_fbs_returns.ensure_wb_fbs_returns_tables")
    @patch("review_processor.wb_fbs_returns._load_source_goods_return_matchers")
    def test_sync_goods_returns_warning_when_settings_key_mismatch(
        self,
        load_matchers,
        _ensure,
        fetch_report,
        _purge,
    ):
        load_matchers.return_value = {"order_ids": set(), "nm_ids": set(), "barcodes": set()}
        fetch_report.return_value = [
            {"orderId": 9001, "nmId": 100, "srid": "x", "stickerId": "111"},
        ]
        repo = MagicMock()
        repo._sql = lambda sql: sql
        conn = MagicMock()
        repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
        repo._connect.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "review_processor.wb_fbs_returns.wb.order_ids_by_srids",
            return_value={},
        ):
            out = returns.sync_goods_returns(
                repo,
                user_id=1,
                source_id=10,
                api_key="settings-key",
                date_from="2026-08-01",
                date_to="2026-08-10",
                api_key_source="settings",
                trust_report=False,
                api_key_candidates=[("settings-key", "settings")],
            )

        self.assertIn("глобальным ключом", out["warning"])
        self.assertEqual(out["api_key_source"], "settings")


if __name__ == "__main__":
    unittest.main()
