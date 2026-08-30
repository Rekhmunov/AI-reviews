"""Tests for Ozon FBS source detection (name-based + legacy marketplace)."""
from __future__ import annotations

import unittest

from review_processor.ozon_fbs import (
    _barcodes_from_posting,
    compute_tab,
    enrich_posting_product_display,
    is_fbs_source_name,
    is_ozon_fbo_source,
    is_ozon_fbs_marketplace,
    is_ozon_fbs_source,
    lookup_posting_by_number,
    parse_posting_number_query,
    resolve_product_barcodes,
    resolve_product_display_name,
    resolve_upsert_status,
    TAB_ARBITRATION,
    TAB_AWAITING_DELIVER,
    TAB_AWAITING_PACKAGING,
    TAB_CANCELLED,
    TAB_DELIVERED,
    TAB_DELIVERING,
)


class OzonFbsMappingTests(unittest.TestCase):
    def test_marketplace_detector_legacy(self) -> None:
        self.assertTrue(is_ozon_fbs_marketplace("ozon_fbs"))
        self.assertTrue(is_ozon_fbs_marketplace("OZON_FBS"))
        self.assertFalse(is_ozon_fbs_marketplace("ozon"))
        self.assertFalse(is_ozon_fbs_marketplace("wb"))

    def test_fbs_source_name(self) -> None:
        self.assertTrue(is_fbs_source_name("ИП Иванов ФБС"))
        self.assertTrue(is_fbs_source_name("Cabinet FBS"))
        self.assertFalse(is_fbs_source_name("ИП Иванов"))
        self.assertFalse(is_fbs_source_name("OZON FBO"))

    def test_ozon_fbs_source_by_name(self) -> None:
        self.assertTrue(is_ozon_fbs_source({"marketplace": "ozon", "name": "Кабинет ФБС"}))
        self.assertTrue(is_ozon_fbs_source({"marketplace": "ozon", "name": "Shop FBS"}))
        self.assertFalse(is_ozon_fbs_source({"marketplace": "ozon", "name": "Кабинет FBO"}))
        self.assertFalse(is_ozon_fbs_source({"marketplace": "wb", "name": "Кабинет ФБС"}))

    def test_ozon_fbs_source_legacy_marketplace(self) -> None:
        self.assertTrue(is_ozon_fbs_source({"marketplace": "ozon_fbs", "name": "Anything"}))
        self.assertTrue(is_ozon_fbs_source({"marketplace": "ozon_fbs", "name": ""}))

    def test_ozon_fbo_source(self) -> None:
        self.assertTrue(is_ozon_fbo_source({"marketplace": "ozon", "name": "Основной"}))
        self.assertFalse(is_ozon_fbo_source({"marketplace": "ozon", "name": "Основной ФБС"}))
        self.assertFalse(is_ozon_fbo_source({"marketplace": "ozon_fbs", "name": "Legacy"}))
        self.assertFalse(is_ozon_fbo_source({"marketplace": "wb", "name": "WB"}))

    def test_compute_tab(self) -> None:
        self.assertEqual(compute_tab("awaiting_packaging"), TAB_AWAITING_PACKAGING)
        self.assertEqual(compute_tab("delivering"), TAB_DELIVERING)
        self.assertEqual(compute_tab("delivered"), TAB_DELIVERED)
        self.assertEqual(compute_tab("cancelled"), TAB_CANCELLED)
        self.assertEqual(compute_tab("arbitration"), TAB_ARBITRATION)
        self.assertEqual(compute_tab("client_arbitration"), TAB_ARBITRATION)

    def test_resolve_upsert_blocks_packaging_after_deliver(self) -> None:
        status, tab = resolve_upsert_status(
            local_status=TAB_AWAITING_DELIVER,
            local_tab=TAB_AWAITING_DELIVER,
            remote_status=TAB_AWAITING_PACKAGING,
        )
        self.assertEqual(status, TAB_AWAITING_DELIVER)
        self.assertEqual(tab, TAB_AWAITING_DELIVER)

    def test_resolve_upsert_allows_deliver_after_packaging(self) -> None:
        status, tab = resolve_upsert_status(
            local_status=TAB_AWAITING_PACKAGING,
            local_tab=TAB_AWAITING_PACKAGING,
            remote_status=TAB_AWAITING_DELIVER,
        )
        self.assertEqual(status, TAB_AWAITING_DELIVER)
        self.assertEqual(tab, TAB_AWAITING_DELIVER)

    def test_resolve_upsert_cancelled_wins(self) -> None:
        status, tab = resolve_upsert_status(
            local_status=TAB_AWAITING_DELIVER,
            local_tab=TAB_AWAITING_DELIVER,
            remote_status=TAB_CANCELLED,
        )
        self.assertEqual(status, TAB_CANCELLED)
        self.assertEqual(tab, TAB_CANCELLED)

    def test_resolve_product_name_from_settings_article(self) -> None:
        name = resolve_product_display_name(
            offer_id="Art-1",
            sku="999",
            name_by_article={"Art-1": "Название из настроек"},
            name_by_ozon_sku={"999": "По SKU"},
        )
        self.assertEqual(name, "Название из настроек")

    def test_resolve_product_name_casefold_article(self) -> None:
        name = resolve_product_display_name(
            offer_id="art-1",
            sku="",
            name_by_article={"art-1": "Имя"},
            name_by_ozon_sku={},
        )
        self.assertEqual(name, "Имя")

    def test_resolve_product_name_by_ozon_sku(self) -> None:
        name = resolve_product_display_name(
            offer_id="unknown",
            sku="770011",
            name_by_article={},
            name_by_ozon_sku={"770011": "Товар SKU"},
        )
        self.assertEqual(name, "Товар SKU")

    def test_resolve_product_name_falls_back_to_offer_not_marketplace_title(self) -> None:
        # Marketplace title must not win when Settings has no match (WB FBS New behaviour).
        name = resolve_product_display_name(
            offer_id="OFFER-9",
            sku="1",
            name_by_article={},
            name_by_ozon_sku={},
        )
        self.assertEqual(name, "OFFER-9")

    def test_enrich_multi_sku_and_qty(self) -> None:
        row = {
            "offer_id": "A1",
            "sku": 10,
            "products_json": (
                '[{"offer_id":"A1","sku":10,"quantity":2},'
                '{"offer_id":"B2","sku":20,"quantity":1}]'
            ),
        }
        enrich_posting_product_display(
            row,
            name_by_article={"A1": "Первый", "B2": "Второй"},
            name_by_ozon_sku={},
        )
        self.assertEqual(row["product_name_display"], "Первый")
        self.assertEqual(row["unit_count"], 3)
        self.assertEqual(row["line_count"], 2)
        self.assertTrue(row["is_multi_unit"])
        self.assertTrue(row["is_multi_sku"])
        self.assertEqual(row["products_brief"][1]["name"], "Второй")
        self.assertEqual(row["products_brief"][0]["quantity"], 2)

    def test_enrich_same_sku_qty_only(self) -> None:
        row = {
            "offer_id": "A1",
            "sku": 10,
            "products_json": '[{"offer_id":"A1","sku":10,"quantity":3}]',
        }
        enrich_posting_product_display(
            row,
            name_by_article={"A1": "Товар"},
            name_by_ozon_sku={},
        )
        self.assertEqual(row["unit_count"], 3)
        self.assertEqual(row["line_count"], 1)
        self.assertTrue(row["is_multi_unit"])
        self.assertFalse(row["is_multi_sku"])

    def test_barcodes_from_posting_skips_offer_and_sku(self) -> None:
        codes = _barcodes_from_posting(
            {"barcodes": {"upper_barcode": "PKG1", "lower_barcode": "PKG2"}},
            [{"offer_id": "ART-1", "sku": 3722013683, "barcode": "4601234567890"}],
        )
        self.assertEqual(codes, ["4601234567890"])

    def test_resolve_product_barcodes_from_settings(self) -> None:
        codes = resolve_product_barcodes(
            offer_id="OOO_Uzori_180x200x30",
            sku="3722013683",
            barcode_map={
                "OOO_Uzori_180x200x30": ["460111", "460222"],
            },
            fallback=["OOO_Uzori_180x200x30", "3722013683"],
        )
        self.assertEqual(codes, ["460111", "460222"])

    def test_resolve_product_barcodes_filters_offer_sku_fallback(self) -> None:
        codes = resolve_product_barcodes(
            offer_id="ART-1",
            sku="999",
            barcode_map={},
            fallback=["ART-1", "999", "460999"],
        )
        self.assertEqual(codes, ["460999"])

    def test_parse_posting_number_query(self) -> None:
        self.assertEqual(
            parse_posting_number_query(" 0124861120-0199-1 "),
            "0124861120-0199-1",
        )
        self.assertEqual(parse_posting_number_query("0124861120-0199-1"), "0124861120-0199-1")
        self.assertEqual(parse_posting_number_query("art-sku"), "")
        self.assertEqual(parse_posting_number_query("0124861120"), "")
        self.assertEqual(parse_posting_number_query("123"), "")

    def test_lookup_posting_by_number_local(self) -> None:
        from unittest.mock import MagicMock, patch

        repo = MagicMock()
        row = {
            "posting_number": "0124861120-0199-1",
            "tab": TAB_AWAITING_DELIVER,
            "status": "awaiting_deliver",
            "offer_id": "ART-1",
            "sku": 1,
            "product_name": "Товар",
            "barcodes_json": "[]",
            "products_json": "[]",
            "warehouse_name": "Склад",
            "price": 100,
        }
        with patch(
            "review_processor.ozon_fbs.get_posting_by_number", return_value=row
        ), patch(
            "review_processor.ozon_fbs._tab_counts",
            return_value={TAB_AWAITING_DELIVER: 1},
        ), patch(
            "review_processor.ozon_fbs.ensure_ozon_fbs_tables"
        ), patch(
            "review_processor.ozon_fbs._enrich_posting_list_item",
            return_value={**row, "warehouse_label": "Склад", "tab_label": "Ожидают отгрузки"},
        ):
            out = lookup_posting_by_number(
                repo,
                user_id=1,
                source_id=2,
                posting_number="0124861120-0199-1",
            )
        self.assertTrue(out["found"])
        self.assertEqual(out["source"], "local")
        self.assertEqual(out["tab"], TAB_AWAITING_DELIVER)
        self.assertEqual(out["item"]["posting_number"], "0124861120-0199-1")

    def test_lookup_posting_by_number_miss(self) -> None:
        from unittest.mock import MagicMock, patch

        repo = MagicMock()
        with patch(
            "review_processor.ozon_fbs.get_posting_by_number", return_value=None
        ), patch(
            "review_processor.ozon_fbs._tab_counts", return_value={}
        ), patch(
            "review_processor.ozon_fbs.ensure_ozon_fbs_tables"
        ):
            out = lookup_posting_by_number(
                repo,
                user_id=1,
                source_id=2,
                posting_number="0124861120-0199-1",
            )
        self.assertFalse(out["found"])
        self.assertIn("не найдено", out["message"])


if __name__ == "__main__":
    unittest.main()
