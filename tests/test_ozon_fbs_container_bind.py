"""Tests for Ozon FBS cargo-place binding helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs_containers as ct


class ContainerScanMatchTests(unittest.TestCase):
    def test_normalize_digits(self) -> None:
        self.assertEqual(ct.normalize_container_scan(" 202174459906000 "), "202174459906000")
        self.assertEqual(ct.normalize_container_scan("abc"), "abc")

    def test_match_by_container_id(self) -> None:
        rows = [{"container_id": 202174459906000, "container_number": 1}]
        found = ct.match_container_by_scan(rows, "202174459906000")
        self.assertIsNotNone(found)
        self.assertEqual(found["container_id"], 202174459906000)

    def test_match_miss(self) -> None:
        self.assertIsNone(ct.match_container_by_scan([{"container_id": 1}], "999"))


class ContainerBindLocalTests(unittest.TestCase):
    def test_bind_keeps_local_on_ozon_error(self) -> None:
        repo = MagicMock()
        client = MagicMock()
        client.carriage_container_fill.side_effect = RuntimeError(
            'Ozon HTTP 400: {"message":"FILL_FAILED"}'
        )
        with patch.object(ct, "_set_local_container_bind") as set_local:
            set_local.return_value = {
                "posting_number": "1-1-1",
                "container_id": 202174459906000,
                "container_barcode": "202174459906000",
                "container_synced": False,
                "container_sync_error": "FILL_FAILED",
            }
            out = ct.bind_posting_to_container(
                client,
                repo,
                user_id=1,
                source_id=2,
                posting_number="1-1-1",
                container_id=202174459906000,
                container_barcode="202174459906000",
            )
        self.assertTrue(out["ok"])
        self.assertFalse(out["synced"])
        self.assertIn("FILL_FAILED", out["error"])
        set_local.assert_called_once()
        kwargs = set_local.call_args.kwargs
        self.assertEqual(kwargs["container_id"], 202174459906000)
        self.assertFalse(kwargs["synced"])
        self.assertTrue(kwargs["sync_error"])

    def test_bind_success_marks_synced(self) -> None:
        repo = MagicMock()
        client = MagicMock()
        client.carriage_container_fill.return_value = {"ok": True}
        with patch.object(ct, "_set_local_container_bind") as set_local:
            set_local.return_value = {
                "posting_number": "1-1-1",
                "container_id": 10,
                "container_barcode": "10",
                "container_synced": True,
                "container_sync_error": "",
            }
            out = ct.bind_posting_to_container(
                client,
                repo,
                user_id=1,
                source_id=2,
                posting_number="1-1-1",
                container_id=10,
            )
        self.assertTrue(out["synced"])
        self.assertEqual(out["error"], "")
        self.assertTrue(set_local.call_args.kwargs["synced"])

    def test_unbind_clears_local_even_if_ozon_remove_fails(self) -> None:
        repo = MagicMock()
        client = MagicMock()
        client.carriage_container_remove_postings.side_effect = RuntimeError("gone")
        with (
            patch.object(
                ct,
                "load_container_bind_map",
                return_value={"1-1-1": {"container_id": 10}},
            ),
            patch.object(ct, "_set_local_container_bind") as set_local,
        ):
            set_local.return_value = {
                "posting_number": "1-1-1",
                "container_id": None,
                "container_barcode": "",
                "container_synced": False,
                "container_sync_error": "",
            }
            out = ct.unbind_posting_from_container(
                client,
                repo,
                user_id=1,
                source_id=2,
                posting_number="1-1-1",
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["error"], "")
        self.assertEqual(set_local.call_args.kwargs["sync_error"], "")
        self.assertIsNone(set_local.call_args.kwargs["container_id"])


class MarkingStatusContainerErrorTests(unittest.TestCase):
    def test_status_error_when_container_sync_fails(self) -> None:
        from review_processor import ozon_fbs_marking as marking

        detail = {
            "supply_id": "S1",
            "orders": [
                {
                    "posting_number": "A-1",
                    "kiz_required": True,
                    "kiz_quantity": 1,
                    "cancelled": False,
                }
            ],
        }
        local = {
            "A-1": {
                "codes": ["CODE1"],
                "saved_at": "",
                "ozon_synced": False,
                "gtd_number": "",
                "container_id": 202174459906000,
                "container_barcode": "202174459906000",
                "container_synced": False,
                "container_sync_error": "FILL_FAILED",
            }
        }
        with (
            patch(
                "review_processor.ozon_fbs_marking.oz_sup.get_supply_detail",
                return_value=detail,
            ),
            patch(
                "review_processor.ozon_fbs_marking.load_marking_map",
                return_value=local,
            ),
        ):
            out = marking.check_supply_marking_status(
                MagicMock(), user_id=1, source_id=2, supply_id="S1"
            )
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["container_error_count"], 1)
        self.assertEqual(out["done"], 1)  # KIZ still complete

    def test_status_ignores_non_kiz_container_errors(self) -> None:
        from review_processor import ozon_fbs_marking as marking

        detail = {
            "supply_id": "S1",
            "orders": [
                {
                    "posting_number": "A-1",
                    "kiz_required": True,
                    "kiz_quantity": 1,
                    "cancelled": False,
                },
                {
                    "posting_number": "B-1",
                    "kiz_required": False,
                    "kiz_quantity": 0,
                    "cancelled": False,
                },
            ],
        }
        local = {
            "A-1": {
                "codes": ["CODE1"],
                "saved_at": "",
                "ozon_synced": False,
                "gtd_number": "",
                "container_id": None,
                "container_barcode": "",
                "container_synced": False,
                "container_sync_error": "",
            },
            "B-1": {
                "codes": [],
                "saved_at": "",
                "ozon_synced": False,
                "gtd_number": "",
                "container_id": 99,
                "container_barcode": "99",
                "container_synced": False,
                "container_sync_error": "FILL_FAILED",
            },
        }
        with (
            patch(
                "review_processor.ozon_fbs_marking.oz_sup.get_supply_detail",
                return_value=detail,
            ),
            patch(
                "review_processor.ozon_fbs_marking.load_marking_map",
                return_value=local,
            ),
        ):
            out = marking.check_supply_marking_status(
                MagicMock(), user_id=1, source_id=2, supply_id="S1"
            )
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["container_error_count"], 0)



class PickVerifyStatusContainerTests(unittest.TestCase):
    def test_pick_incomplete_cargo_does_not_force_error(self) -> None:
        """Green/empty tone must follow ШК verify only; unbound cargo is not an error."""
        from review_processor import ozon_fbs_pick_verify as pick

        detail = {
            "supply_id": "S1",
            "orders": [
                {
                    "posting_number": "P-1",
                    "kiz_required": False,
                    "cancelled": False,
                },
                {
                    "posting_number": "P-2",
                    "kiz_required": False,
                    "cancelled": False,
                },
            ],
        }
        local = {
            "P-1": {
                "pick_verified": True,
                "pick_barcode": "4600000000000",
                "pick_verified_at": "2026-01-01T00:00:00Z",
                "container_id": 10,
                "container_barcode": "10",
                "container_synced": True,
                "container_sync_error": "",
            },
            "P-2": {
                "pick_verified": True,
                "pick_barcode": "4600000000001",
                "pick_verified_at": "2026-01-01T00:00:00Z",
                "container_id": None,
                "container_barcode": "",
                "container_synced": False,
                "container_sync_error": "",
            },
        }
        with (
            patch(
                "review_processor.ozon_fbs_pick_verify.oz_sup.get_supply_detail",
                return_value=detail,
            ),
            patch(
                "review_processor.ozon_fbs_pick_verify.load_posting_pick_map",
                return_value=local,
            ),
        ):
            out = pick.check_supply_pick_verify_status(
                MagicMock(), user_id=1, source_id=2, supply_id="S1"
            )
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out.get("container_error_count", 0), 0)

    def test_pick_container_sync_error_makes_error_tone(self) -> None:
        from review_processor import ozon_fbs_pick_verify as pick

        detail = {
            "supply_id": "S1",
            "orders": [
                {
                    "posting_number": "P-1",
                    "kiz_required": False,
                    "cancelled": False,
                }
            ],
        }
        local = {
            "P-1": {
                "pick_verified": True,
                "pick_barcode": "4600000000000",
                "pick_verified_at": "2026-01-01T00:00:00Z",
                "container_id": 10,
                "container_barcode": "10",
                "container_synced": False,
                "container_sync_error": "FILL_FAILED",
            },
        }
        with (
            patch(
                "review_processor.ozon_fbs_pick_verify.oz_sup.get_supply_detail",
                return_value=detail,
            ),
            patch(
                "review_processor.ozon_fbs_pick_verify.load_posting_pick_map",
                return_value=local,
            ),
        ):
            out = pick.check_supply_pick_verify_status(
                MagicMock(), user_id=1, source_id=2, supply_id="S1"
            )
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["container_error_count"], 1)


if __name__ == "__main__":
    unittest.main()
