"""Tests for Ozon FBS «Отгрузки» (carriage / act) helpers."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock

from review_processor.ozon_fbs_shipments import (
    _block_matches_departure,
    _carriage_status_label,
    _carriage_delivery_blocks,
    _carriage_departure_date,
    _collected_label,
    _delivery_method_rows,
    _departure_iso,
    _friendly_ozon_api_error,
    _merge_delivery_methods,
    _normalize_block,
    build_shipments_view,
    pick_default_delivery_method,
    render_shipment_barcode_print_html,
)


class OzonFbsShipmentsHelpersTests(unittest.TestCase):
    def test_departure_iso(self) -> None:
        self.assertEqual(_departure_iso(date(2026, 8, 25)), "2026-08-25T00:00:00.000Z")
        self.assertEqual(_carriage_departure_date(date(2026, 8, 25)), "2026-08-25")

    def test_delivery_method_rows_v2_top_level(self) -> None:
        rows, has_next = _delivery_method_rows(
            {
                "delivery_methods": [
                    {"delivery_method_id": 5, "name": "Метод 5"},
                ],
                "has_next": False,
            }
        )
        self.assertEqual(len(rows), 1)
        self.assertFalse(has_next)

    def test_carriage_blocks_v2_methods(self) -> None:
        blocks = _carriage_delivery_blocks(
            {
                "methods": [
                    {"warehouse_name": "Склад", "carriages": []},
                ]
            }
        )
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["warehouse_name"], "Склад")

    def test_status_labels(self) -> None:
        self.assertEqual(_carriage_status_label(""), "Не сформирована")
        self.assertEqual(_carriage_status_label("new"), "Ожидает подтверждения")
        self.assertEqual(_carriage_status_label("formed"), "Ожидает подтверждения")
        self.assertEqual(_carriage_status_label("Не сформирована"), "Не сформирована")
        self.assertEqual(
            _carriage_status_label("Ожидает подтверждения"), "Ожидает подтверждения"
        )

    def test_delivery_method_rows_v2(self) -> None:
        rows, has_next = _delivery_method_rows(
            {
                "result": {
                    "delivery_methods": [
                        {"delivery_method_id": 5, "name": "Метод 5"},
                    ],
                    "has_next": False,
                }
            }
        )
        self.assertEqual(len(rows), 1)
        self.assertFalse(has_next)

    def test_carriage_blocks_v2_nested(self) -> None:
        blocks = _carriage_delivery_blocks(
            {
                "result": {
                    "delivery_methods": [
                        {"warehouse_name": "Склад", "carriages": []},
                    ]
                }
            }
        )
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["warehouse_name"], "Склад")

    def test_friendly_role_error(self) -> None:
        err = _friendly_ozon_api_error(RuntimeError("Ozon HTTP 403: role missing"))
        self.assertIn("API-ключ Ozon", str(err))

    def test_friendly_incomplete_carriages(self) -> None:
        err = _friendly_ozon_api_error(
            RuntimeError("Ozon HTTP 400: there_are_incomplete_carriages")
        )
        self.assertIn("незакрытые отгрузки", str(err).casefold())

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
            {"id": 2, "name": "Доставка Ozon самостоятельно, Кинешма"},
            {"id": 3, "name": "ПВЗ"},
        ]
        picked = pick_default_delivery_method(methods)
        self.assertEqual(picked["id"], 2)

    def test_merge_delivery_methods_from_posting_fallback(self) -> None:
        methods = _merge_delivery_methods(
            [],
            {"id": 102, "name": "Доставка Ozon самостоятельно, Кинешма"},
        )
        self.assertEqual(len(methods), 1)
        self.assertEqual(methods[0]["id"], 102)

    def test_block_matches_departure_filters_other_days(self) -> None:
        day = date(2026, 8, 26)
        self.assertTrue(
            _block_matches_departure({"departure_date": "2026-08-26T00:00:00Z"}, day)
        )
        self.assertFalse(
            _block_matches_departure({"departure_date": "2026-08-25T00:00:00Z"}, day)
        )

    def test_render_barcode_print_html_58x40(self) -> None:
        html = render_shipment_barcode_print_html(
            supply_name="Поставка 1",
            warehouse_name="Кинешма",
            barcode_text="123",
            barcode_image_base64="abc",
        )
        self.assertIn("58mm 40mm", html)
        self.assertIn("abc", html)

    def test_normalize_empty_carriages_draft(self) -> None:
        block = _normalize_block(
            {
                "warehouse_name": "Кинешма_ВарФабрик_ОЗОН",
                "dropoff_point_type": "SortCenter",
                "first_mile_type": "dropoff",
                "dropoff_address": "Ивановская обл...",
                "mandatory_packaged_count": 16,
                "mandatory_postings_count": 18,
                "timeslot_to": "21:00",
                "recommended_time_local": "20:00",
                "warehouse_city": "Кинешма",
                "departure_date": "2026-08-25T00:00:00Z",
                "carriages": [],
            }
        )
        self.assertEqual(block["dropoff_point_type_label"], "Сортировочный центр")
        self.assertEqual(block["shipment_method_label"], "В пункт приема")
        self.assertEqual(block["collected_label"], "16 из 18")
        self.assertEqual(block["acceptance_label"], "до 21:00 (Кинешма)")
        self.assertEqual(block["hint"], "")
        self.assertIn("журнале регистрации", block["journal_hint"])
        self.assertEqual(len(block["carriages"]), 1)
        self.assertEqual(block["carriages"][0]["status_label"], "Не сформирована")
        self.assertTrue(block["carriages"][0]["can_form"])
        self.assertIn("августа", block["day_label"])

    def test_normalize_open_carriage_new_status(self) -> None:
        client = MagicMock()
        client.carriage_get.return_value = {"status": "formed", "carriage_id": 119882557}
        block = _normalize_block(
            {
                "dropoff_point_type": "SortCenter",
                "first_mile_type": "dropoff",
                "timeslot_to": "21:00",
                "warehouse_city": "Кинешма",
                "carriages": [
                    {"id": 119882557, "status": "new", "postings_count": 261},
                ],
            },
            client=client,
        )
        c = block["carriages"][0]
        self.assertEqual(c["label"], "Отгрузка119882557")
        self.assertEqual(c["status_label"], "Ожидает подтверждения")
        self.assertTrue(c["is_formed"])
        self.assertFalse(c["can_form"])
        client.carriage_get.assert_called_once_with(carriage_id=119882557)

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
                    "departure_date": "2026-08-25",
                    "dropoff_point_type": "SortCenter",
                    "first_mile_type": "dropoff",
                    "timeslot_to": "21:00",
                    "mandatory_packaged_count": 2,
                    "mandatory_postings_count": 2,
                    "carriages": [
                        {"id": "100", "postings_count": 2, "status": "formed"}
                    ],
                }
            ]
        }
        client.carriage_get.return_value = {"status": "formed", "carriage_id": 100}
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
        self.assertEqual(
            view["blocks"][0]["carriages"][0]["status_label"], "Ожидает подтверждения"
        )
        client.carriage_delivery_list.assert_called_once()
        args = client.carriage_delivery_list.call_args.kwargs
        self.assertEqual(args["delivery_method_id"], 22)
        self.assertEqual(args["departure_date"], "2026-08-25")

    def test_build_shipments_view_surfaces_open_carriage_other_day(self) -> None:
        client = MagicMock()
        client.delivery_method_list.return_value = {
            "delivery_methods": [
                {"id": 22, "name": "Доставка на ОЗОН самостоятельно", "status": "ACTIVE"}
            ],
            "has_next": False,
        }
        client.carriage_delivery_list.return_value = {
            "methods": [
                {
                    "delivery_method_id": 22,
                    "departure_date": "2026-08-27",
                    "dropoff_point_type": "SortCenter",
                    "first_mile_type": "dropoff",
                    "timeslot_to": "21:00",
                    "warehouse_city": "Кинешма",
                    "carriages": [
                        {"id": 119882557, "status": "new", "postings_count": 10}
                    ],
                }
            ]
        }
        client.carriage_get.return_value = {"status": "formed"}
        view = build_shipments_view(
            client=client,
            warehouse_id=1,
            warehouse_name="Склад А",
            departure=date(2026, 8, 28),
        )
        self.assertTrue(view["ok"])
        self.assertTrue(view["has_open_carriages_blocking"])
        self.assertIn("незакрытые отгрузки", view["message"].casefold())
        self.assertFalse(view["blocks"][0]["carriages"][0]["can_form"])

    def test_build_shipments_view_uses_fallback_delivery_method(self) -> None:
        client = MagicMock()
        client.delivery_method_list.return_value = {
            "delivery_methods": [],
            "has_next": False,
        }
        client.carriage_delivery_list.return_value = {
            "methods": [
                {
                    "delivery_method_id": 102,
                    "delivery_method_name": "Доставка на ОЗОН самостоятельно",
                    "warehouse_name": "Склад А",
                    "departure_date": "2026-08-25",
                    "carriages": [],
                }
            ]
        }
        view = build_shipments_view(
            client=client,
            warehouse_id=1,
            warehouse_name="Склад А",
            departure=date(2026, 8, 25),
            fallback_delivery_method={
                "id": 102,
                "name": "Доставка Ozon самостоятельно, Кинешма",
            },
        )
        self.assertTrue(view["ok"])
        self.assertEqual(view["selected_delivery_method_id"], 102)
        self.assertEqual(len(view["delivery_methods"]), 1)
        client.carriage_delivery_list.assert_called_once()


if __name__ == "__main__":
    unittest.main()
