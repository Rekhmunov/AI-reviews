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


if __name__ == "__main__":
    unittest.main()
