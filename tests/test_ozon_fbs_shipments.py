"""Tests for Ozon FBS «Отгрузки» (carriage / act) helpers."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock

from review_processor.ozon_fbs_shipments import (
    _carriage_status_label,
    _collected_label,
    _departure_iso,
    _normalize_block,
    build_shipments_view,
    pick_default_delivery_method,
)


class OzonFbsShipmentsHelpersTests(unittest.TestCase):
    def test_departure_iso(self) -> None:
        self.assertEqual(_departure_iso(date(2026, 8, 25)), "2026-08-25T00:00:00.000Z")

    def test_status_labels(self) -> None:
        self.assertEqual(_carriage_status_label(""), "Не сформирована")
        self.assertEqual(_carriage_status_label("new"), "Не сформирована")
        self.assertEqual(_carriage_status_label("formed"), "Сформирована")
        self.assertEqual(_carriage_status_label("Не сформирована"), "Не сформирована")
        self.assertEqual(_carriage_status_label("Сформирована"), "Сформирована")

    def test_collected_label(self) -> None:
        self.assertEqual(
            _collected_label(
                {"mandatory_packaged_count": 16, "mandatory_postings_count": 18}
            ),
            "16 из 18",
        )

    def test_pick_self_delivery_method(self) -> None:
        methods = [
            {"id": 1, "name": "Курьер Ozon"},
            {"id": 2, "name": "Доставка на ОЗОН самостоятельно"},
            {"id": 3, "name": "ПВЗ"},
        ]
        picked = pick_default_delivery_method(methods)
        self.assertEqual(picked["id"], 2)

    def test_normalize_empty_carriages_draft(self) -> None:
        block = _normalize_block(
            {
                "warehouse_name": "Кинешма_ВарФабрик_ОЗОН",
                "dropoff_point_type": "sc",
                "dropoff_address": "Ивановская обл...",
                "mandatory_packaged_count": 16,
                "mandatory_postings_count": 18,
                "recommended_time_local": "21:00",
                "warehouse_city": "Кинешма",
                "departure_date": "2026-08-25T00:00:00Z",
                "carriages": [],
            }
        )
        self.assertEqual(block["dropoff_point_type_label"], "В пункт приема")
        self.assertEqual(block["collected_label"], "16 из 18")
        self.assertEqual(block["acceptance_label"], "до 21:00 (Кинешма)")
        self.assertEqual(len(block["carriages"]), 1)
        self.assertEqual(block["carriages"][0]["status_label"], "Не сформирована")
        self.assertTrue(block["carriages"][0]["can_form"])
        self.assertIn("августа", block["day_label"])

    def test_build_shipments_view_prefers_self_delivery(self) -> None:
        client = MagicMock()
        client.delivery_method_list.return_value = {
            "has_next": False,
            "result": [
                {"id": 11, "name": "Другой метод", "status": "ACTIVE", "warehouse_id": 1},
                {
                    "id": 22,
                    "name": "Доставка на ОЗОН самостоятельно",
                    "status": "ACTIVE",
                    "warehouse_id": 1,
                },
            ],
        }
        client.carriage_delivery_list.return_value = {
            "result": [
                {
                    "delivery_method_id": 22,
                    "delivery_method_name": "Доставка на ОЗОН самостоятельно",
                    "warehouse_name": "Склад А",
                    "warehouse_id": 1,
                    "mandatory_packaged_count": 2,
                    "mandatory_postings_count": 2,
                    "carriages": [
                        {"id": "100", "postings_count": 2, "status": "formed"}
                    ],
                }
            ]
        }
        client.fbs_act_get_barcode_text.return_value = {"result": "1020005028015630"}
        client.fbs_act_get_barcode.return_value = {
            "file_content": "aaa",
            "content_type": "image/png",
        }

        view = build_shipments_view(
            client=client,
            warehouse_id=1,
            warehouse_name="Склад А",
            departure=date(2026, 8, 25),
        )
        self.assertTrue(view["ok"])
        self.assertEqual(view["selected_delivery_method_id"], 22)
        self.assertEqual(view["barcode"]["barcode_text"], "1020005028015630")
        client.carriage_delivery_list.assert_called_once()
        args = client.carriage_delivery_list.call_args.kwargs
        self.assertEqual(args["delivery_method_id"], 22)
        self.assertEqual(args["departure_date"], "2026-08-25T00:00:00.000Z")


if __name__ == "__main__":
    unittest.main()
