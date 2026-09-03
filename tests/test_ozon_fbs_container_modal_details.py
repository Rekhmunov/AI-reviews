"""Ozon FBS cargo-place modal: warehouse_date formatting + expand details."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz
from review_processor import ozon_fbs_containers as ct


class FormatWarehouseDateTests(unittest.TestCase):
    def test_date_only(self) -> None:
        self.assertEqual(oz.format_warehouse_date("2026-08-30"), "30.08.2026")

    def test_naive_iso_keeps_local_clock(self) -> None:
        # Must NOT shift warehouse-local 15:30 as if it were UTC.
        self.assertEqual(oz.format_warehouse_date("2026-03-20T15:30:00"), "20.03.2026 15:30")

    def test_space_separated_local(self) -> None:
        self.assertEqual(oz.format_warehouse_date("2026-03-20 09:05:00"), "20.03.2026 09:05")

    def test_empty(self) -> None:
        self.assertEqual(oz.format_warehouse_date(""), "")
        self.assertEqual(oz.format_warehouse_date(None), "")


class ContainerModalDetailsTests(unittest.TestCase):
    def test_timeline_includes_local_move_and_warehouse_date(self) -> None:
        repo = MagicMock()
        with patch.object(
            ct,
            "get_supply_moved_to_delivering_at",
            return_value="2026-03-21T10:00:00+00:00",
        ), patch.object(
            ct,
            "_list_local_container_postings",
            return_value=[
                {
                    "posting_number": "12345-0001",
                    "offer_id": "ART",
                    "product_name": "Товар",
                    "quantity": 1,
                    "has_kiz": True,
                    "kiz_count": 1,
                    "pick_verified": False,
                    "container_barcode": "99",
                    "container_synced": True,
                    "tab": "delivering",
                    "status": "delivering",
                }
            ],
        ):
            out = ct.build_container_modal_details(
                repo,
                user_id=1,
                source_id=2,
                supply_id="sup-1",
                container={
                    "container_id": 99,
                    "container_number": 3,
                    "status": "acceptance_in_progress",
                    "status_label": "Принято на СЦ",
                    "created_at": "2026-03-19T08:00:00Z",
                    "warehouse_date": "2026-03-20T15:30:00",
                },
            )
        keys = [x["key"] for x in out["timeline"]]
        self.assertEqual(
            keys, ["created", "moved_to_delivering", "warehouse_date", "status"]
        )
        self.assertEqual(out["postings_count"], 1)
        self.assertEqual(out["warehouse_date_display"], "20.03.2026 15:30")
        self.assertTrue(out["moved_to_delivering_at_display"])

    def test_enrich_list_attaches_display_fields(self) -> None:
        repo = MagicMock()
        listed = {
            "ok": True,
            "items": [
                {
                    "container_id": 1,
                    "status": "new",
                    "warehouse_date": "2026-03-20T15:30:00",
                    "created_at": "2026-03-19T08:00:00Z",
                }
            ],
        }
        with patch.object(
            ct, "get_supply_moved_to_delivering_at", return_value=""
        ):
            out = ct.enrich_containers_for_supply_modal(
                repo,
                user_id=1,
                source_id=2,
                supply_id="sup-1",
                listed=listed,
            )
        row = out["items"][0]
        self.assertEqual(row["warehouse_date_display"], "20.03.2026 15:30")
        self.assertTrue(row["created_at_display"])
        self.assertEqual(row["moved_to_delivering_at"], "")

    def test_get_details_is_local_only(self) -> None:
        repo = MagicMock()
        with patch.object(ct, "build_container_modal_details") as build:
            build.return_value = {"ok": True, "container_id": 7}
            out = ct.get_container_modal_details(
                repo,
                user_id=1,
                source_id=2,
                supply_id="sup-1",
                container_id=7,
                container={"container_id": 7, "status": "new"},
            )
        self.assertTrue(out["ok"])
        build.assert_called_once()
        kwargs = build.call_args.kwargs
        self.assertEqual(kwargs["container"]["container_id"], 7)


if __name__ == "__main__":
    unittest.main()
