"""Unit tests for Настройки → ГТД → Работа с ЧЗ."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from review_processor import supply_gtd_chz as gtd_chz


def _repo_with_rows(fetch_map: dict[str, list] | None = None) -> MagicMock:
    """Minimal ReviewRepository stub for SQL helpers used by supply_gtd_chz."""
    repo = MagicMock()
    repo._sql = lambda s: s
    repo._row_to_dict = lambda r: dict(r) if isinstance(r, dict) else {}
    repo.list_product_photos.return_value = []

    conn = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = conn
    cm.__exit__.return_value = False
    repo._connect.return_value = cm

    # Default: empty fetches
    conn.execute.return_value.fetchone.return_value = {"n": 0, "id": 1}
    conn.execute.return_value.fetchall.return_value = []
    return repo


class DisplayKindTests(unittest.TestCase):
    def test_empty(self) -> None:
        label, kind = gtd_chz._display_kind(
            status="", owner_inn="", participant_inn="7707083893"
        )
        self.assertEqual(kind, gtd_chz.KIND_EMPTY)

    def test_in_circulation(self) -> None:
        with patch.object(gtd_chz.kiz_circ, "cis_owner_is_foreign", return_value=False), patch.object(
            gtd_chz.kiz_circ, "cis_status_label", return_value="В обороте"
        ), patch.object(
            gtd_chz.kiz_circ, "classify_cis_status", return_value="in_circulation"
        ):
            label, kind = gtd_chz._display_kind(
                status="INTRODUCED",
                owner_inn="7707083893",
                participant_inn="7707083893",
            )
        self.assertEqual(kind, gtd_chz.KIND_IN)
        self.assertEqual(label, "В обороте")

    def test_foreign_owner_is_transferred(self) -> None:
        with patch.object(gtd_chz.kiz_circ, "cis_owner_is_foreign", return_value=True):
            label, kind = gtd_chz._display_kind(
                status="INTRODUCED",
                owner_inn="1234567890",
                participant_inn="7707083893",
            )
        self.assertEqual(kind, gtd_chz.KIND_TRANSFERRED)
        self.assertEqual(label, "Передан")


class PrepareGuardsTests(unittest.TestCase):
    def test_withdraw_requires_in_circulation(self) -> None:
        repo = _repo_with_rows()
        gtd = {"id": 5, "gtd_number": "10323010/250826/5101277", "kiz_count": 1}
        settings = {
            "is_enabled": True,
            "participant_inn": "7707083893",
            "product_group": "lp",
            "kpp": "770701001",
            "fias_id": "00000000-0000-0000-0000-000000000001",
            "return_type": "REMOTE_SALE_RETURN",
            "cert_thumbprint": "ABC",
            "api_base_url": "https://example.test",
        }
        with patch.object(gtd_chz, "_require_gtd", return_value=gtd), patch.object(
            gtd_chz, "_chz_settings_ready", return_value=settings
        ), patch.object(
            gtd_chz,
            "_load_gtd_kiz_codes",
            return_value=["0104670172422564215MpGb)qC19x29"],
        ), patch.object(
            gtd_chz,
            "_states_by_kiz",
            return_value={
                "0104670172422564215MpGb)qC19x29": {
                    "cis_status_kind": gtd_chz.KIND_OUT,
                }
            },
        ):
            with self.assertRaises(ValueError) as ctx:
                gtd_chz.prepare_gtd_chz_documents(
                    repo,
                    user_id=1,
                    gtd_id=5,
                    op="withdraw",
                    kiz_shorts=["0104670172422564215MpGb)qC19x29"],
                )
        self.assertIn("подходящих", str(ctx.exception).lower())

    def test_withdraw_builds_lk_receipt(self) -> None:
        repo = _repo_with_rows()
        kiz = "0104670172422564215MpGb)qC19x29"
        gtd = {"id": 5, "gtd_number": "10323010/250826/5101277", "kiz_count": 1}
        settings = {
            "is_enabled": True,
            "participant_inn": "7707083893",
            "product_group": "lp",
            "kpp": "770701001",
            "fias_id": "00000000-0000-0000-0000-000000000001",
            "return_type": "REMOTE_SALE_RETURN",
            "cert_thumbprint": "ABC",
            "api_base_url": "https://example.test",
        }
        with patch.object(gtd_chz, "_require_gtd", return_value=gtd), patch.object(
            gtd_chz, "_chz_settings_ready", return_value=settings
        ), patch.object(
            gtd_chz, "_load_gtd_kiz_codes", return_value=[kiz]
        ), patch.object(
            gtd_chz,
            "_states_by_kiz",
            return_value={kiz: {"cis_status_kind": gtd_chz.KIND_IN}},
        ), patch.object(
            gtd_chz,
            "build_lk_receipt_document",
            return_value={"inn": "7707083893", "action": "DISTANCE", "products": []},
        ) as build_lk:
            out = gtd_chz.prepare_gtd_chz_documents(
                repo,
                user_id=1,
                gtd_id=5,
                op="withdraw",
                kiz_shorts=[kiz],
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["eligible"], 1)
        self.assertEqual(len(out["documents"]), 1)
        doc = out["documents"][0]
        self.assertEqual(doc["doc_type"], "LK_RECEIPT")
        self.assertIn("sign_payload_b64", doc)
        build_lk.assert_called_once()
        kwargs = build_lk.call_args.kwargs
        self.assertEqual(kwargs["action"], "DISTANCE")
        self.assertEqual(kwargs["primary_document_type"], "OTHER")
        self.assertIn("ГТД", kwargs["primary_document_custom_name"])

    def test_return_builds_lp_return(self) -> None:
        repo = _repo_with_rows()
        kiz = "0104670172422564215MpGb)qC19x29"
        gtd = {"id": 5, "gtd_number": "10323010/250826/5101277", "kiz_count": 1}
        settings = {
            "is_enabled": True,
            "participant_inn": "7707083893",
            "product_group": "lp",
            "kpp": "",
            "fias_id": "",
            "return_type": "REMOTE_SALE_RETURN",
            "cert_thumbprint": "",
            "api_base_url": "https://example.test",
        }
        with patch.object(gtd_chz, "_require_gtd", return_value=gtd), patch.object(
            gtd_chz, "_chz_settings_ready", return_value=settings
        ), patch.object(
            gtd_chz, "_load_gtd_kiz_codes", return_value=[kiz]
        ), patch.object(
            gtd_chz,
            "_states_by_kiz",
            return_value={kiz: {"cis_status_kind": gtd_chz.KIND_OUT}},
        ), patch.object(
            gtd_chz,
            "build_lp_return_document",
            return_value={"trade_participant_inn": "7707083893", "products_list": []},
        ) as build_lp:
            out = gtd_chz.prepare_gtd_chz_documents(
                repo,
                user_id=1,
                gtd_id=5,
                op="return",
                kiz_shorts=[kiz],
            )
        self.assertEqual(out["documents"][0]["doc_type"], "LP_RETURN")
        build_lp.assert_called_once()
        self.assertEqual(build_lp.call_args.kwargs["paid"], False)


class RefreshStatusesTests(unittest.TestCase):
    def test_refresh_maps_api_rows(self) -> None:
        repo = _repo_with_rows()
        kiz = "0104670172422564215MpGb)qC19x29"
        client = MagicMock()
        client.cises_info.return_value = [
            {
                "cisInfo": {
                    "requestedCis": kiz,
                    "cis": kiz,
                    "status": "INTRODUCED",
                    "ownerInn": "7707083893",
                }
            }
        ]
        settings = {
            "is_enabled": True,
            "participant_inn": "7707083893",
            "product_group": "lp",
            "api_base_url": "https://example.test",
        }
        with patch.object(
            gtd_chz, "_require_gtd", return_value={"id": 1, "gtd_number": "1/2/3"}
        ), patch.object(
            gtd_chz, "_chz_settings_ready", return_value=settings
        ), patch.object(
            gtd_chz, "_load_gtd_kiz_codes", return_value=[kiz]
        ), patch.object(
            gtd_chz.kiz_circ, "chz_client_from_settings", return_value=client
        ), patch.object(
            gtd_chz, "_start_run", return_value=9
        ), patch.object(
            gtd_chz, "_finish_run"
        ), patch.object(
            gtd_chz, "_upsert_cis_state"
        ) as upsert:
            out = gtd_chz.refresh_gtd_cis_statuses(
                repo,
                user_id=1,
                gtd_id=1,
                token="tok",
                kiz_shorts=[kiz],
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["found"], 1)
        upsert.assert_called()
        kwargs = upsert.call_args.kwargs
        self.assertEqual(kwargs["cis_status"], "INTRODUCED")

    def test_refresh_background_returns_immediately(self) -> None:
        repo = _repo_with_rows()
        kiz = "0104670172422564215MpGb)qC19x29"
        client = MagicMock()
        client.cises_info.return_value = [
            {
                "cisInfo": {
                    "requestedCis": kiz,
                    "cis": kiz,
                    "status": "INTRODUCED",
                    "ownerInn": "7707083893",
                }
            }
        ]
        settings = {
            "is_enabled": True,
            "participant_inn": "7707083893",
            "product_group": "lp",
            "api_base_url": "https://example.test",
        }
        with patch.object(
            gtd_chz, "_require_gtd", return_value={"id": 1, "gtd_number": "1/2/3"}
        ), patch.object(
            gtd_chz, "_chz_settings_ready", return_value=settings
        ), patch.object(
            gtd_chz, "_load_gtd_kiz_codes", return_value=[kiz]
        ), patch.object(
            gtd_chz.kiz_circ, "chz_client_from_settings", return_value=client
        ), patch.object(
            gtd_chz, "_start_run", return_value=42
        ), patch.object(
            gtd_chz, "_update_run_progress"
        ), patch.object(
            gtd_chz, "_finish_run"
        ), patch.object(
            gtd_chz, "_upsert_cis_state"
        ), patch.object(
            gtd_chz.threading, "Thread"
        ) as thr:
            thr.return_value = MagicMock()
            out = gtd_chz.refresh_gtd_cis_statuses(
                repo,
                user_id=1,
                gtd_id=1,
                token="tok",
                kiz_shorts=[kiz],
                background=True,
            )
        self.assertTrue(out["ok"])
        self.assertTrue(out["async"])
        self.assertEqual(out["run_id"], 42)
        self.assertEqual(out["requested"], 1)
        thr.assert_called_once()
        thr.return_value.start.assert_called_once()



class ResubmitGuardTests(unittest.TestCase):
    def test_skips_already_submitted_same_op(self) -> None:
        repo = _repo_with_rows()
        kiz = "0104670172422564215MpGb)qC19x29"
        gtd = {"id": 5, "gtd_number": "10323010/250826/5101277", "kiz_count": 1}
        settings = {
            "is_enabled": True,
            "participant_inn": "7707083893",
            "product_group": "lp",
            "kpp": "770701001",
            "fias_id": "00000000-0000-0000-0000-000000000001",
            "return_type": "REMOTE_SALE_RETURN",
            "cert_thumbprint": "ABC",
            "api_base_url": "https://example.test",
        }
        with patch.object(gtd_chz, "_require_gtd", return_value=gtd), patch.object(
            gtd_chz, "_chz_settings_ready", return_value=settings
        ), patch.object(
            gtd_chz, "_load_gtd_kiz_codes", return_value=[kiz]
        ), patch.object(
            gtd_chz,
            "_states_by_kiz",
            return_value={
                kiz: {
                    "cis_status_kind": gtd_chz.KIND_IN,
                    "last_op": gtd_chz.OP_WITHDRAW,
                    "last_op_status": "submitted",
                }
            },
        ):
            with self.assertRaises(ValueError) as ctx:
                gtd_chz.prepare_gtd_chz_documents(
                    repo,
                    user_id=1,
                    gtd_id=5,
                    op="withdraw",
                    kiz_shorts=[kiz],
                )
        self.assertIn("подходящих", str(ctx.exception).lower())


class ListGtdKizPaginationTests(unittest.TestCase):
    def test_list_uses_sql_limit_offset(self) -> None:
        repo = _repo_with_rows()
        conn = repo._connect.return_value.__enter__.return_value
        # total, kind_counts, filtered_total, page rows
        conn.execute.return_value.fetchone.side_effect = [
            {"n": 5},
            {"n": 5},
        ]
        conn.execute.return_value.fetchall.side_effect = [
            [{"kind": gtd_chz.KIND_EMPTY, "n": 5}],
            [
                {
                    "kiz_id": 1,
                    "kiz_short": "0104670172422564215MpGb)qC19x29",
                    "gtin": "04670172422564",
                    "cis_status": "",
                    "cis_status_kind": gtd_chz.KIND_EMPTY,
                    "cis_status_label": "",
                    "cis_owner_inn": "",
                    "cis_status_error": "",
                    "cis_checked_at": "",
                    "last_op": "",
                    "last_doc_id": "",
                    "last_doc_type": "",
                    "last_op_status": "",
                    "last_op_error": "",
                }
            ],
        ]
        gtd = {"id": 5, "gtd_number": "10323010/250826/5101277", "kiz_count": 5, "note": ""}
        with patch.object(gtd_chz, "_require_gtd", return_value=gtd), patch.object(
            gtd_chz, "ensure_supply_gtd_chz_tables"
        ):
            out = gtd_chz.list_gtd_kiz_for_chz(
                repo, user_id=1, gtd_id=5, offset=0, limit=1
            )
        self.assertEqual(out["total"], 5)
        self.assertEqual(out["filtered_total"], 5)
        self.assertEqual(len(out["items"]), 1)
        self.assertTrue(out["has_more"])
        # Last execute should be the page query with LIMIT/OFFSET
        last_sql = conn.execute.call_args_list[-1].args[0]
        self.assertIn("LIMIT ?", last_sql)
        self.assertIn("OFFSET ?", last_sql)
        self.assertEqual(conn.execute.call_args_list[-1].args[1][-2:], (1, 0))
        self.assertEqual(out["items"][0].get("product_name"), "")

    def test_list_enriches_product_name_from_catalog_ean13(self) -> None:
        repo = _repo_with_rows()
        repo.list_product_photos.return_value = [
            {"name": "Подушка 50x70", "barcodes": ["4670172422564"]},
        ]
        conn = repo._connect.return_value.__enter__.return_value
        conn.execute.return_value.fetchone.side_effect = [
            {"n": 1},
            {"n": 1},
        ]
        conn.execute.return_value.fetchall.side_effect = [
            [{"kind": gtd_chz.KIND_EMPTY, "n": 1}],
            [
                {
                    "kiz_id": 1,
                    "kiz_short": "0104670172422564215MpGb)qC19x29",
                    "gtin": "04670172422564",
                    "cis_status": "",
                    "cis_status_kind": gtd_chz.KIND_EMPTY,
                    "cis_status_label": "",
                    "cis_owner_inn": "",
                    "cis_status_error": "",
                    "cis_checked_at": "",
                    "last_op": "",
                    "last_doc_id": "",
                    "last_doc_type": "",
                    "last_op_status": "",
                    "last_op_error": "",
                }
            ],
        ]
        gtd = {"id": 5, "gtd_number": "10323010/250826/5101277", "kiz_count": 1, "note": ""}
        with patch.object(gtd_chz, "_require_gtd", return_value=gtd), patch.object(
            gtd_chz, "ensure_supply_gtd_chz_tables"
        ):
            out = gtd_chz.list_gtd_kiz_for_chz(repo, user_id=1, gtd_id=5)
        self.assertEqual(out["items"][0]["product_name"], "Подушка 50x70")
        repo.list_product_photos.assert_called_once_with(user_id=1)


class ProductNameLookupTests(unittest.TestCase):
    def test_ean13_matches_gtin14(self) -> None:
        idx = gtd_chz._build_product_name_by_gtin(
            [{"name": "Товар А", "barcodes": ["4670172422564"]}]
        )
        self.assertEqual(
            gtd_chz._resolve_product_name(idx, gtin="04670172422564"),
            "Товар А",
        )
        self.assertEqual(
            gtd_chz._resolve_product_name(idx, gtin="4670172422564"),
            "Товар А",
        )

    def test_gtin_from_kiz_short_when_column_empty(self) -> None:
        idx = gtd_chz._build_product_name_by_gtin(
            [{"name": "Товар Б", "barcodes": ["04670172422564"]}]
        )
        self.assertEqual(
            gtd_chz._resolve_product_name(
                idx,
                gtin="",
                kiz_short="010467017242256421SERIALXX",
            ),
            "Товар Б",
        )


if __name__ == "__main__":
    unittest.main()
