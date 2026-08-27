"""Tests for Ozon FBS source detection (name-based + legacy marketplace)."""
from __future__ import annotations

import unittest

from review_processor.ozon_fbs import (
    _barcodes_from_posting,
    compute_tab,
    is_fbs_source_name,
    is_ozon_fbo_source,
    is_ozon_fbs_marketplace,
    is_ozon_fbs_source,
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


if __name__ == "__main__":
    unittest.main()
