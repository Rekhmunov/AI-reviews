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

    def test_bind_rejects_approved_container(self) -> None:
        repo = MagicMock()
        client = MagicMock()
        client.carriage_container_get.return_value = {
            "container": {
                "container_id": 10,
                "container_number": 1,
                "status": "approved",
                "available_actions": ["get_label_container"],
                "count_of_postings": 1,
            }
        }
        with patch.object(ct, "_set_local_container_bind") as set_local:
            with self.assertRaises(ValueError) as ctx:
                ct.bind_posting_to_container(
                    client,
                    repo,
                    user_id=1,
                    source_id=2,
                    posting_number="1-1-1",
                    container_id=10,
                )
        self.assertIn("подтверждено", str(ctx.exception).lower())
        client.carriage_container_fill.assert_not_called()
        set_local.assert_not_called()

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


class ContainerReconcileTests(unittest.TestCase):
    def test_posting_numbers_from_container_payload(self) -> None:
        raw = {
            "posting_numbers": ["A-1", "B-2"],
            "postings": [{"posting_number": "C-3"}],
        }
        nums = ct._posting_numbers_from_container_payload(raw)
        self.assertEqual(nums, ["A-1", "B-2", "C-3"])

    def test_reconcile_adopts_portal_bind(self) -> None:
        repo = MagicMock()
        client = MagicMock()
        supply = {"posting_numbers": ["A-1", "B-1"]}
        with (
            patch.object(ct.oz_sup, "get_supply", return_value=supply),
            patch.object(
                ct,
                "load_container_bind_map",
                side_effect=[
                    {"A-1": {"container_id": 10, "container_barcode": "10", "container_synced": True, "container_sync_error": ""}},
                    {"A-1": {"container_id": 20, "container_barcode": "20", "container_synced": True, "container_sync_error": ""}, "B-1": {}},
                ],
            ),
            patch.object(ct, "resolve_supply_warehouse_id", return_value=(100, "WH")),
            patch.object(
                ct,
                "_list_containers_cached",
                return_value={"items": [{"container_id": 20}, {"container_id": 10}]},
            ),
            patch.object(
                ct,
                "_fetch_container_postings",
                side_effect=lambda _c, container_id: (
                    ({"container_id": 20, "can_fill": True}, ["A-1"], True)
                    if int(container_id) == 20
                    else ({"container_id": 10, "can_fill": True}, [], True)
                ),
            ),
            patch.object(ct, "_set_local_container_bind") as set_local,
        ):
            out = ct.reconcile_supply_container_binds(
                client,
                repo,
                user_id=1,
                source_id=2,
                supply_id="S1",
            )
        self.assertTrue(out["ok"])
        self.assertTrue(out["posting_lists_available"])
        self.assertEqual(len(out["changes"]), 1)
        self.assertEqual(out["changes"][0]["action"], "updated")
        self.assertEqual(out["changes"][0]["posting_number"], "A-1")
        set_local.assert_called_once()
        self.assertEqual(set_local.call_args.kwargs["container_id"], 20)

    def test_reconcile_clears_deleted_container(self) -> None:
        repo = MagicMock()
        client = MagicMock()
        supply = {"posting_numbers": ["A-1"]}
        with (
            patch.object(ct.oz_sup, "get_supply", return_value=supply),
            patch.object(
                ct,
                "load_container_bind_map",
                side_effect=[
                    {"A-1": {"container_id": 99, "container_barcode": "99", "container_synced": True, "container_sync_error": ""}},
                    {"A-1": {"container_id": None, "container_barcode": "", "container_synced": False, "container_sync_error": ""}},
                ],
            ),
            patch.object(ct, "resolve_supply_warehouse_id", return_value=(100, "WH")),
            patch.object(ct, "_list_containers_cached", return_value={"items": []}),
            patch.object(ct, "_fetch_container_postings", return_value=(None, [], False)),
            patch.object(ct, "_set_local_container_bind") as set_local,
        ):
            out = ct.reconcile_supply_container_binds(
                client,
                repo,
                user_id=1,
                source_id=2,
                supply_id="S1",
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["changes"][0]["action"], "cleared")
        set_local.assert_called_once()
        self.assertIsNone(set_local.call_args.kwargs["container_id"])

    def test_reconcile_skips_dirty_posting(self) -> None:
        repo = MagicMock()
        client = MagicMock()
        supply = {"posting_numbers": ["A-1"]}
        with (
            patch.object(ct.oz_sup, "get_supply", return_value=supply),
            patch.object(
                ct,
                "load_container_bind_map",
                return_value={"A-1": {"container_id": 10, "container_barcode": "10", "container_synced": True, "container_sync_error": ""}},
            ),
            patch.object(ct, "resolve_supply_warehouse_id", return_value=(100, "WH")),
            patch.object(ct, "_list_containers_cached", return_value={"items": [{"container_id": 20}]}),
            patch.object(
                ct,
                "_fetch_container_postings",
                return_value=({"container_id": 20}, ["A-1"], True),
            ),
            patch.object(ct, "_set_local_container_bind") as set_local,
        ):
            out = ct.reconcile_supply_container_binds(
                client,
                repo,
                user_id=1,
                source_id=2,
                supply_id="S1",
                skip_postings=["A-1"],
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["changes"], [])
        set_local.assert_not_called()

    def test_reconcile_keeps_unsynced_local_on_portal_empty(self) -> None:
        repo = MagicMock()
        client = MagicMock()
        supply = {"posting_numbers": ["A-1"]}
        with (
            patch.object(ct.oz_sup, "get_supply", return_value=supply),
            patch.object(
                ct,
                "load_container_bind_map",
                return_value={
                    "A-1": {
                        "container_id": 10,
                        "container_barcode": "10",
                        "container_synced": False,
                        "container_sync_error": "FILL_FAILED",
                    }
                },
            ),
            patch.object(ct, "resolve_supply_warehouse_id", return_value=(100, "WH")),
            patch.object(ct, "_list_containers_cached", return_value={"items": [{"container_id": 10}]}),
            patch.object(
                ct,
                "_fetch_container_postings",
                return_value=({"container_id": 10}, [], True),
            ),
            patch.object(ct, "_set_local_container_bind") as set_local,
        ):
            out = ct.reconcile_supply_container_binds(
                client,
                repo,
                user_id=1,
                source_id=2,
                supply_id="S1",
            )
        self.assertTrue(out["ok"])
        self.assertFalse(out["posting_lists_available"])
        self.assertEqual(out["changes"], [])
        set_local.assert_not_called()


if __name__ == "__main__":
    unittest.main()
