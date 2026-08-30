"""Pre-ship КИЗ+ГТД (юрлица) on awaiting_packaging."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz
from review_processor import ozon_fbs_marking as marking


def _gtd_posting(*, sku: int = 111, qty: int = 1) -> dict:
    return {
        "posting_number": "0123-001-1",
        "requirements": {
            "products_requiring_gtd": [sku],
            "products_requiring_mandatory_mark": [sku],
        },
        "products": [{"sku": sku, "quantity": qty, "offer_id": "ART"}],
    }


class PreShipGtdDetectTests(unittest.TestCase):
    def test_requires_gtd_from_requirements(self) -> None:
        row = {"raw_json": json.dumps(_gtd_posting())}
        self.assertTrue(oz.posting_requires_pre_ship_gtd(row))
        self.assertEqual(oz.pre_ship_exemplar_quantity(row), 1)

    def test_mark_only_does_not_require_pre_ship_gtd(self) -> None:
        posting = {
            "requirements": {"products_requiring_mandatory_mark": [1]},
            "products": [{"sku": 1, "quantity": 1}],
        }
        self.assertFalse(oz.posting_requires_pre_ship_gtd(posting))

    def test_qty_uses_exemplar_products(self) -> None:
        row = {"raw_json": json.dumps(_gtd_posting(qty=3)), "quantity": 3}
        self.assertEqual(oz.pre_ship_exemplar_quantity(row), 3)
        products = oz.pre_ship_exemplar_products(_gtd_posting(qty=3))
        self.assertEqual(products[0]["quantity"], 3)

    def test_ready_flag(self) -> None:
        row = {
            "raw_json": json.dumps(_gtd_posting()),
            "marking_ozon_synced": False,
        }
        self.assertFalse(oz.posting_pre_ship_exemplar_ready(row))
        row["marking_ozon_synced"] = True
        self.assertTrue(oz.posting_pre_ship_exemplar_ready(row))
        self.assertTrue(
            oz.posting_pre_ship_exemplar_ready({"raw_json": "{}"})
        )


class PushMarkingGtdTests(unittest.TestCase):
    def test_push_sets_gtd_on_set_and_validate(self) -> None:
        client = MagicMock()
        client.product_exemplar_create_or_get.return_value = {
            "products": [
                {
                    "product_id": 111,
                    "is_gtd_needed": True,
                    "is_mandatory_mark_needed": True,
                    "exemplars": [{"exemplar_id": 9}],
                }
            ]
        }
        client.product_exemplar_status.return_value = {"status": "ship_available"}
        codes = ["0104670172422465215PBRvfYjmynXN"]
        out = marking.push_marking_to_ozon(
            client,
            posting_number="0123-001-1",
            posting=_gtd_posting(),
            codes=codes,
            gtd="10323010/250826/5101277",
            prefer_gtd_products=True,
        )
        self.assertTrue(out.get("ok"))
        products = client.product_exemplar_set.call_args.kwargs["products"]
        ex = products[0]["exemplars"][0]
        self.assertEqual(ex["gtd"], "10323010/250826/5101277")
        self.assertFalse(ex["is_gtd_absent"])
        self.assertEqual(ex["marks"][0]["mark"], codes[0])
        validate_products = client.product_exemplar_validate.call_args[0][1]
        self.assertEqual(
            validate_products[0]["exemplars"][0]["gtd"],
            "10323010/250826/5101277",
        )
        client.product_exemplar_status.assert_called()

    def test_already_defined_is_success(self) -> None:
        client = MagicMock()
        client.product_exemplar_create_or_get.side_effect = RuntimeError(
            'Ozon HTTP 400: {"code":3,"message":"EXEMPLAR_INFO_ALREADY_DEFINED"}'
        )
        out = marking.push_marking_to_ozon(
            client,
            posting_number="0123-001-1",
            posting=_gtd_posting(),
            codes=["0104670172422465215PBRvfYjmynXN"],
            gtd="10323010/250826/5101277",
            prefer_gtd_products=True,
        )
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("already_defined"))
        client.product_exemplar_set.assert_not_called()

    def test_build_set_products_n_codes(self) -> None:
        create = {
            "products": [
                {
                    "product_id": 1,
                    "is_gtd_needed": True,
                    "exemplars": [{"exemplar_id": 10}, {"exemplar_id": 11}],
                }
            ]
        }
        products = marking._build_exemplar_set_products(
            create_result=create,
            codes=["A", "B"],
            gtd="10323010/250826/5101277",
        )
        self.assertEqual(len(products[0]["exemplars"]), 2)
        self.assertEqual(products[0]["exemplars"][0]["marks"][0]["mark"], "A")
        self.assertEqual(products[0]["exemplars"][1]["marks"][0]["mark"], "B")
        self.assertEqual(products[0]["exemplars"][0]["gtd"], "10323010/250826/5101277")


class ShipAllSkipExemplarTests(unittest.TestCase):
    def test_execute_skips_unsynced_gtd_posting(self) -> None:
        from review_processor import ozon_fbs_supplies as oz_sup

        repo = MagicMock()
        row = {
            "posting_number": "P-1",
            "raw_json": json.dumps(_gtd_posting()),
            "marking_ozon_synced": False,
            "warehouse_id": 1,
            "warehouse_name": "WH",
        }

        def _connect():
            conn = MagicMock()
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            conn.execute.return_value.fetchone.return_value = row
            return conn

        repo._connect.side_effect = _connect
        repo._row_to_dict.side_effect = lambda r: r if isinstance(r, dict) else dict(r)
        repo._sql.side_effect = lambda s: s

        preview = {
            "groups": [
                {
                    "group_key": "wh1",
                    "mode": "create",
                    "posting_numbers": ["P-1"],
                    "suggested_name": "Поставка",
                    "warehouse_id": 1,
                    "warehouse_name": "WH",
                }
            ],
            "posting_count": 1,
            "block_collect": False,
        }
        with patch.object(oz_sup, "ensure_ozon_fbs_supply_schema"), patch.object(
            oz_sup, "preview_ship_all_collect", return_value=preview
        ), patch.object(oz_sup, "list_open_supplies", return_value=[]), patch.object(
            oz_sup, "_source_display_name", return_value="OZON"
        ), patch.object(oz_sup.oz, "OzonFbsClient"), patch.object(
            oz_sup.oz_detail, "ship_posting"
        ) as ship:
            out = oz_sup.execute_ship_all_collect(
                repo,
                user_id=1,
                source_id=2,
                client_id="c",
                api_key="k",
                decisions=[{"group_key": "wh1", "action": "create", "name": "Поставка"}],
                ship_pause_sec=0,
            )
        ship.assert_not_called()
        self.assertEqual(out.get("skipped_exemplar"), 1)
        self.assertEqual(out.get("shipped"), 0)
        self.assertTrue(out.get("errors"))
        self.assertEqual(out["errors"][0].get("code"), "PRE_SHIP_EXEMPLAR_REQUIRED")


if __name__ == "__main__":
    unittest.main()
