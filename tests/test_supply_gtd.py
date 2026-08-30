"""Tests for supply GTD PDF parse / KIZ validation / import (no overwrite)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from review_processor import supply_gtd as gtd


class SupplyGtdParseTests(unittest.TestCase):
    def test_gtin_checksum(self) -> None:
        # Valid GTIN-14 from sample DT codes (04670172422564).
        self.assertTrue(gtd.gtin14_checksum_ok("04670172422564"))
        self.assertFalse(gtd.gtin14_checksum_ok("04670172422565"))
        self.assertFalse(gtd.gtin14_checksum_ok("123"))

    def test_normalize_gtd_number(self) -> None:
        self.assertEqual(
            gtd.normalize_gtd_number("  К ДТ N 10323010/250826/5101277  "),
            "10323010/250826/5101277",
        )
        self.assertEqual(gtd.normalize_gtd_number("bad"), "")

    def test_kiz_short_from_raw_accepts_dt_unit(self) -> None:
        raw = "0104670172422564215MpGb)qC19x29"
        short = gtd.kiz_short_from_raw(raw)
        self.assertEqual(short, raw)
        # With crypto tail — keep short unit only.
        with_crypto = raw + "\u001d" + "91EE06" + "\u001d" + "92abcd"
        self.assertEqual(gtd.kiz_short_from_raw(with_crypto), raw)

    def test_kiz_short_rejects_bad_gtin(self) -> None:
        self.assertEqual(gtd.kiz_short_from_raw("0104670172422565215MpGb)qC19x29"), "")

    def test_kiz_short_rejects_doc_noise(self) -> None:
        self.assertEqual(gtd.kiz_short_from_raw("10323010/250826/5101277"), "")
        self.assertEqual(gtd.kiz_short_from_raw("ЕАЭС RU C-UZ.HK74.B.00021/25"), "")

    def test_parse_gtd_pdf_extracts_codes(self) -> None:
        text = (
            "ДОПОЛНЕНИЕ на 27 Л. К ДТ N 10323010/250826/5101277\n"
            "В ГРАФЕ 31 (Сведения о средствах идентификации). Товар или его потребительская упаковка.\n"
            "0104670172422564215MpGb)qC19x29 0104670172422564215YtrsXQnKjg-j "
            "0104670172422564215Vdmf73KrWZKaZ\n"
            "1650.00 ШТ\n"
            "Лист N 3\n"
        )
        with patch.object(gtd, "_extract_pdf_text", return_value=(text, 1)):
            out = gtd.parse_gtd_pdf(b"%PDF-fake")
        self.assertEqual(out["gtd_number"], "10323010/250826/5101277")
        self.assertEqual(out["kiz_parsed"], 3)
        self.assertIn("0104670172422564215MpGb)qC19x29", out["kiz_list"])
        self.assertEqual(out["qty_hint_sht"], 1650)


class SupplyGtdImportTests(unittest.TestCase):
    def test_import_refuses_duplicate_gtd(self) -> None:
        repo = MagicMock()
        with patch.object(
            gtd,
            "get_gtd_by_number",
            return_value={"id": 9, "gtd_number": "10323010/250826/5101277", "kiz_inserted": 10},
        ), patch.object(
            gtd,
            "parse_gtd_pdf",
            return_value={
                "gtd_number": "10323010/250826/5101277",
                "kiz_list": ["0104670172422564215MpGb)qC19x29"],
                "page_count": 1,
                "kiz_rejected": 0,
                "qty_hint_sht": None,
            },
        ):
            with self.assertRaises(ValueError) as ctx:
                gtd.import_gtd_pdf(
                    repo,
                    user_id=1,
                    pdf_bytes=b"%PDF",
                    gtd_number="10323010/250826/5101277",
                    note="x",
                    filename="a.pdf",
                )
        self.assertIn("уже загружена", str(ctx.exception))

    def test_import_maps_unique_violation_to_value_error(self) -> None:
        from psycopg.errors import UniqueViolation

        repo = MagicMock()
        pre_conn = MagicMock()
        pre_conn.__enter__ = MagicMock(return_value=pre_conn)
        pre_conn.__exit__ = MagicMock(return_value=False)
        empty = MagicMock()
        empty.fetchall.return_value = []
        pre_conn.execute.return_value = empty

        ins_conn = MagicMock()
        ins_conn.__enter__ = MagicMock(return_value=ins_conn)
        ins_conn.__exit__ = MagicMock(return_value=False)
        ins_conn.execute.side_effect = UniqueViolation("duplicate key")

        repo._connect.side_effect = [pre_conn, ins_conn]
        repo._sql.side_effect = lambda q: q

        with patch.object(gtd, "get_gtd_by_number", return_value=None), patch.object(
            gtd,
            "parse_gtd_pdf",
            return_value={
                "gtd_number": "10323010/250826/5101277",
                "kiz_list": ["0104670172422564215MpGb)qC19x29"],
                "page_count": 1,
                "kiz_rejected": 0,
                "qty_hint_sht": None,
            },
        ), patch.object(gtd, "ensure_supply_gtd_tables"):
            with self.assertRaises(ValueError) as ctx:
                gtd.import_gtd_pdf(
                    repo,
                    user_id=1,
                    pdf_bytes=b"%PDF",
                    gtd_number="10323010/250826/5101277",
                    note="",
                    filename="a.pdf",
                )
        self.assertIn("уже загружена", str(ctx.exception))

    def test_import_refuses_empty_kiz(self) -> None:
        repo = MagicMock()
        with patch.object(gtd, "get_gtd_by_number", return_value=None), patch.object(
            gtd,
            "parse_gtd_pdfs",
            return_value={
                "gtd_number": "",
                "kiz_list": [],
                "page_count": 2,
                "kiz_rejected": 0,
                "qty_hint_sht": None,
                "warnings": ["a.pdf: КИЗ не найдены"],
                "source_filenames": ["a.pdf"],
                "kiz_source": "",
            },
        ), patch.object(gtd, "ensure_supply_gtd_tables"):
            with self.assertRaises(ValueError) as ctx:
                gtd.import_gtd_pdfs(
                    repo,
                    user_id=1,
                    files=[("a.pdf", b"%PDF")],
                    gtd_number="10323010/250826/5101277",
                )
        self.assertIn("не найдено", str(ctx.exception).casefold())
        self.assertIn("не создана", str(ctx.exception).casefold())

    def test_parse_sticker_text_pdf(self) -> None:
        text = (
            "Наматрасник 140x200 (серый)\n"
            "0104678434671071215Y%Eveoaz)LTT\n"
            "1\n"
        )
        with patch.object(gtd, "_extract_pdf_text", return_value=(text, 1)), patch.object(
            gtd, "_extract_kiz_via_datamatrix", return_value=({}, 0, "")
        ):
            out = gtd.parse_gtd_pdf(b"%PDF-stickers")
        self.assertEqual(out["kiz_parsed"], 1)
        self.assertEqual(out["kiz_source"], "text")
        self.assertIn("0104678434671071215Y%Eveoaz)LTT", out["kiz_list"])

    def test_parse_falls_back_to_datamatrix(self) -> None:
        with patch.object(gtd, "_extract_pdf_text", return_value=("", 3)), patch.object(
            gtd,
            "_extract_kiz_via_datamatrix",
            return_value=(
                {"0104678434671071215Y%Eveoaz)LTT": "0104678434671071215Y%Eveoaz)LTT"},
                3,
                "",
            ),
        ):
            out = gtd.parse_gtd_pdf(b"%PDF-image-only")
        self.assertEqual(out["kiz_source"], "datamatrix")
        self.assertEqual(out["kiz_parsed"], 1)

    def test_update_rejects_number_clash(self) -> None:
        repo = MagicMock()
        with patch.object(
            gtd,
            "get_gtd_by_id",
            return_value={"id": 1, "gtd_number": "10323010/250826/5101277", "kiz_count": 2},
        ), patch.object(
            gtd,
            "get_gtd_by_number",
            return_value={"id": 2, "gtd_number": "10323010/250826/5109999"},
        ), patch.object(gtd, "ensure_supply_gtd_tables"):
            with self.assertRaises(ValueError) as ctx:
                gtd.update_gtd(
                    repo,
                    user_id=1,
                    gtd_id=1,
                    gtd_number="10323010/250826/5109999",
                    note="",
                )
        self.assertIn("занят", str(ctx.exception).casefold())

    def test_delete_gtd_ok(self) -> None:
        repo = MagicMock()
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        repo._connect.return_value = conn
        repo._sql.side_effect = lambda q: q
        with patch.object(
            gtd,
            "get_gtd_by_id",
            return_value={
                "id": 5,
                "gtd_number": "10323010/250826/5101277",
                "kiz_count": 12,
            },
        ), patch.object(gtd, "ensure_supply_gtd_tables"):
            out = gtd.delete_gtd(repo, user_id=1, gtd_id=5)
        self.assertTrue(out["ok"])
        self.assertEqual(out["kiz_deleted"], 12)
        conn.execute.assert_called()

    def test_classify_same_by_gtd_id_after_rename(self) -> None:
        """Codes already on this doc must count as same even if gtd_number lags."""
        repo = MagicMock()
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        row = MagicMock()
        # Old denormalized number, but gtd_id matches the document being edited.
        conn.execute.return_value.fetchall.return_value = [
            {
                "kiz_short": "0104670172422564215MpGb)qC19x29",
                "gtd_number": "10323010/250826/5101277",
                "gtd_id": 7,
            }
        ]
        repo._connect.return_value = conn
        repo._sql.side_effect = lambda q: q
        repo._row_to_dict.side_effect = lambda r: dict(r)

        same, other, to_ins = gtd._classify_existing_kiz(
            repo,
            user_id=1,
            gtd_number="10323010/250826/5109999",  # new number
            kiz_list=["0104670172422564215MpGb)qC19x29"],
            gtd_id=7,
        )
        self.assertEqual(same, ["0104670172422564215MpGb)qC19x29"])
        self.assertEqual(other, [])
        self.assertEqual(to_ins, [])

    def test_dmtx_page_limit_covers_typical_sticker_sheets(self) -> None:
        # Real sticker PDFs can reach ~10k pages; process in memory-safe chunks.
        self.assertGreaterEqual(gtd._DMTX_MAX_PAGES, 10000)
        self.assertGreaterEqual(gtd._DMTX_CHUNK_PAGES, 20)
        self.assertLess(gtd._DMTX_ASYNC_PAGE_THRESHOLD, 500)

    def test_files_need_async_by_page_threshold(self) -> None:
        with patch.object(gtd, "pdf_page_count", return_value=500):
            need, pages = gtd.files_need_async_import([("a.pdf", b"%PDF")])
        self.assertTrue(need)
        self.assertEqual(pages, 500)
        with patch.object(gtd, "pdf_page_count", return_value=10):
            need2, pages2 = gtd.files_need_async_import([("a.pdf", b"%PDF")])
        self.assertFalse(need2)
        self.assertEqual(pages2, 10)


if __name__ == "__main__":
    unittest.main()
