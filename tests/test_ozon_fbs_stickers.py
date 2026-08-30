"""Tests for Ozon FBS stickers: package labels, binding, lookup."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz
from review_processor import ozon_fbs_supplies as oz_sup
from review_processor.ozon_fbs_stickers import find_postings_by_sticker_scan, lookup_posting_by_scan


class OzonFbsClientStructureTests(unittest.TestCase):
    def test_client_exposes_shipments_api_methods(self) -> None:
        client = oz.OzonFbsClient("cid", "key")
        for name in (
            "delivery_method_list",
            "carriage_delivery_list",
            "carriage_get",
            "fbs_act_create",
            "fbs_act_check_status",
            "fbs_act_get_barcode",
            "fbs_act_get_barcode_text",
        ):
            self.assertTrue(hasattr(client, name), name)


class OzonFbsLabelFetchTests(unittest.TestCase):
    def test_batch_ozon_error_falls_back_to_split(self) -> None:
        client = MagicMock()
        # Fail whole batch, then succeed each half (binary split).
        client.package_label_pdf.side_effect = [
            RuntimeError('Ozon HTTP 400: {"code":3,"message":"INVALID_ARGUMENT"}'),
            b"%PDF-one",
            b"%PDF-two",
        ]

        with patch.object(oz_sup, "_pdf_pages_to_png_b64", side_effect=[["p1"], ["p2"]]):
            out = oz_sup._fetch_label_images(client, ["A-1", "B-2"])

        self.assertEqual(out["A-1"], ["p1"])
        self.assertEqual(out["B-2"], ["p2"])
        self.assertEqual(client.package_label_pdf.call_count, 3)

    def test_batch_poison_binary_split_keeps_good_half_batched(self) -> None:
        """One bad posting must not force 20 individual Ozon calls."""
        client = MagicMock()
        good = [f"G-{i}" for i in range(19)]
        bad = "BAD-1"
        batch = good + [bad]

        def side_effect(nums):
            nums = list(nums)
            if bad in nums and len(nums) > 1:
                raise RuntimeError('Ozon HTTP 400: {"code":3,"message":"INVALID_ARGUMENT"}')
            if nums == [bad]:
                raise RuntimeError('Ozon HTTP 400: {"code":3,"message":"INVALID_ARGUMENT"}')
            return b"%PDF-" + ",".join(nums).encode()

        client.package_label_pdf.side_effect = side_effect

        def fake_pages(pdf: bytes):
            raw = pdf.decode("ascii", errors="ignore").removeprefix("%PDF-")
            parts = [p for p in raw.split(",") if p]
            return [f"img-{p}" for p in parts]

        with patch.object(oz_sup, "_pdf_pages_to_png_b64", side_effect=fake_pages):
            out = oz_sup._fetch_label_images(client, batch)

        for pn in good:
            self.assertEqual(out[pn], [f"img-{pn}"])
        self.assertEqual(out[bad], [])
        # Binary split: far fewer than 1 + 20 individual calls.
        self.assertLess(client.package_label_pdf.call_count, 12)

    def test_fetch_merged_batches_over_20(self) -> None:
        client = MagicMock()
        client.package_label_pdf.side_effect = [b"%PDF-1", b"%PDF-2"]

        mock_merged = MagicMock()
        mock_merged.page_count = 1
        mock_merged.tobytes.return_value = b"merged"
        mock_src = MagicMock()

        def fake_open(arg=None, stream=None, filetype=None):
            if stream is not None:
                return mock_src
            return mock_merged

        with patch("pymupdf.open", side_effect=fake_open):
            pdf = oz.fetch_merged_package_label_pdf(client, [f"P-{i}" for i in range(25)])

        self.assertEqual(pdf, b"merged")
        self.assertEqual(client.package_label_pdf.call_count, 2)
        self.assertEqual(len(client.package_label_pdf.call_args_list[0].args[0]), 20)
        self.assertEqual(len(client.package_label_pdf.call_args_list[1].args[0]), 5)

    def test_single_invalid_argument_is_humanized(self) -> None:
        client = MagicMock()
        client.package_label_pdf.side_effect = RuntimeError(
            'Ozon HTTP 400: {"code":3,"message":"INVALID_ARGUMENT"}'
        )
        with self.assertRaises(RuntimeError) as ctx:
            oz.fetch_merged_package_label_pdf(client, ["0124861120-0199-1"])
        msg = str(ctx.exception)
        self.assertNotIn("INVALID_ARGUMENT", msg)
        self.assertIn("Ожидает отгрузки", msg)


class OzonFbsPackageLabelErrorTests(unittest.TestCase):
    def test_format_invalid_argument(self) -> None:
        msg = oz.format_ozon_package_label_error(
            RuntimeError('Ozon HTTP 400: {"code":3,"message":"INVALID_ARGUMENT"}')
        )
        self.assertIn("Ожидает отгрузки", msg)
        self.assertNotIn('"code":3', msg)

    def test_format_not_ready(self) -> None:
        msg = oz.format_ozon_package_label_error(
            RuntimeError("The next postings aren't ready")
        )
        self.assertIn("не готовы", msg.casefold())

    def test_explain_awaiting_packaging(self) -> None:
        msg = oz.explain_package_label_status_block(
            posting_number="0124861120-0199-1",
            status="awaiting_packaging",
        )
        self.assertIn("Ожидает сборки", msg)
        self.assertIn("Сначала соберите", msg)

    def test_explain_delivering(self) -> None:
        msg = oz.explain_package_label_status_block(
            posting_number="0124861120-0199-1",
            status="delivering",
        )
        self.assertIn("Доставляется", msg)
        self.assertIn("повторная печать", msg.casefold())

    def test_ensure_blocks_non_awaiting_deliver(self) -> None:
        client = MagicMock()
        client.get_posting.return_value = {"status": "awaiting_packaging"}
        with self.assertRaises(RuntimeError) as ctx:
            oz.ensure_single_posting_label_printable(client, "0124861120-0199-1")
        self.assertIn("Ожидает сборки", str(ctx.exception))

    def test_ensure_passes_awaiting_deliver(self) -> None:
        client = MagicMock()
        client.get_posting.return_value = {"status": "awaiting_deliver"}
        oz.ensure_single_posting_label_printable(client, "0124861120-0199-1")

    def test_print_package_labels_checks_status(self) -> None:
        from review_processor import ozon_fbs_detail as oz_detail

        with patch.object(oz, "OzonFbsClient") as client_cls:
            client = client_cls.return_value
            client.get_posting.return_value = {"status": "delivering"}
            with self.assertRaises(RuntimeError) as ctx:
                oz_detail.print_package_labels(
                    client_id="cid",
                    api_key="key",
                    posting_numbers=["0124861120-0199-1"],
                )
        self.assertIn("Доставляется", str(ctx.exception))
        client.package_label_pdf.assert_not_called()


class OzonFbsStickerFieldsTests(unittest.TestCase):
    def test_sticker_parts_from_posting_number(self) -> None:
        a, b = oz.sticker_parts_from_posting_number("0123604587-1235-1")
        self.assertEqual(a, "0123604587")
        self.assertEqual(b, "1235-1")

    def test_sticker_fields_from_posting(self) -> None:
        fields = oz.sticker_fields_from_posting(
            {
                "posting_number": "0123604587-1235-1",
                "barcodes": {"upper_barcode": "QR123", "lower_barcode": ""},
            }
        )
        self.assertEqual(fields["sticker_barcode"], "QR123")
        self.assertEqual(fields["sticker_lower_barcode"], "")
        self.assertEqual(fields["sticker_part_a"], "0123604587")
        self.assertEqual(fields["sticker_part_b"], "1235-1")

    def test_sticker_fields_upper_and_lower(self) -> None:
        fields = oz.sticker_fields_from_posting(
            {
                "posting_number": "0123604587-1235-1",
                "barcodes": {"upper_barcode": "UPQR", "lower_barcode": "LOWQR"},
            }
        )
        self.assertEqual(fields["sticker_barcode"], "UPQR")
        self.assertEqual(fields["sticker_lower_barcode"], "LOWQR")

    def test_posting_sticker_payload_falls_back_to_raw_json(self) -> None:
        payload = oz.posting_sticker_payload_from_row(
            {
                "posting_number": "0163799058-0084-1",
                "sticker_barcode": "",
                "sticker_lower_barcode": "",
                "sticker_part_a": "",
                "sticker_part_b": "",
                "raw_json": (
                    '{"posting_number":"0163799058-0084-1",'
                    '"barcodes":{"upper_barcode":"751420599146000",'
                    '"lower_barcode":"751420599146000"}}'
                ),
            }
        )
        self.assertEqual(payload["sticker_barcode"], "751420599146000")
        self.assertEqual(payload["sticker_lower_barcode"], "751420599146000")
        self.assertEqual(payload["sticker_part_a"], "0163799058")
        self.assertEqual(payload["sticker_part_b"], "0084-1")


class OzonFbsStickerPersistTests(unittest.TestCase):
    @patch("review_processor.ozon_fbs.ensure_ozon_fbs_tables")
    def test_persist_posting_stickers_batch_updates_row(self, _ensure: MagicMock) -> None:
        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        cur = MagicMock()
        cur.rowcount = 1
        conn.execute.return_value = cur
        n = oz.persist_posting_stickers_batch(
            repo,
            user_id=1,
            source_id=2,
            stickers={
                "PN-1": {
                    "sticker_barcode": "!scanQR",
                    "sticker_part_a": "0123",
                    "sticker_part_b": "1",
                }
            },
            set_scanned_at=True,
        )
        self.assertEqual(n, 1)
        conn.execute.assert_called_once()


class OzonFbsStickerLookupTests(unittest.TestCase):
    @patch("review_processor.ozon_fbs_stickers.find_postings_by_sticker_scan")
    def test_lookup_posting_by_scan_found(self, mock_find: MagicMock) -> None:
        mock_find.return_value = {
            "row": {
                "posting_number": "PN-1",
                "order_id": 99,
                "order_number": "ORD-99",
                "marking_codes_json": '["010460"]',
                "pick_verified": True,
                "pick_barcode": "4601234567890",
                "pick_verified_at": "2026-08-26T12:00:00+00:00",
                "sticker_barcode": "!qr",
                "sticker_part_a": "0123",
                "sticker_part_b": "1",
            },
            "ambiguous": False,
            "matches": [],
        }
        out = lookup_posting_by_scan(
            MagicMock(), user_id=1, source_id=2, scan="!qr"
        )
        self.assertTrue(out["found"])
        self.assertEqual(out["posting"]["posting_number"], "PN-1")
        self.assertEqual(out["posting"]["kiz_codes"], ["010460"])
        self.assertTrue(out["posting"]["pick_verified"])

    def test_find_by_sticker_barcode(self) -> None:
        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        conn.execute.return_value.fetchall.return_value = [
            {
                "posting_number": "PN-1",
                "sticker_barcode": "!uKEtQZVx",
                "sticker_part_a": "",
                "sticker_part_b": "",
            }
        ]
        repo._row_to_dict = lambda r: dict(r)
        found = find_postings_by_sticker_scan(
            repo, user_id=1, source_id=2, scan="!uKEtQZVx"
        )
        self.assertEqual(found["row"]["posting_number"], "PN-1")

    def test_find_by_sticker_lower_barcode(self) -> None:
        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        conn.execute.return_value.fetchall.side_effect = [
            [],
            [
                {
                    "posting_number": "PN-2",
                    "sticker_barcode": "UPQR",
                    "sticker_lower_barcode": "LOWQR",
                    "sticker_part_a": "",
                    "sticker_part_b": "",
                }
            ],
        ]
        repo._row_to_dict = lambda r: dict(r)
        found = find_postings_by_sticker_scan(
            repo, user_id=1, source_id=2, scan="LOWQR"
        )
        self.assertEqual(found["row"]["posting_number"], "PN-2")

    def test_find_by_posting_number_partial(self) -> None:
        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        conn.execute.return_value.fetchall.return_value = [
            {
                "posting_number": "0123604587-1235-1",
                "sticker_barcode": "",
                "sticker_part_a": "0123604587",
                "sticker_part_b": "1235-1",
            }
        ]
        repo._row_to_dict = lambda r: dict(r)
        found = find_postings_by_sticker_scan(
            repo, user_id=1, source_id=2, scan="0123604587-1235-1"
        )
        self.assertEqual(found["row"]["posting_number"], "0123604587-1235-1")

    def test_find_by_sticker_part_b_suffix(self) -> None:
        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        # part_b exact query returns empty; fuzzy via ILIKE tail
        conn.execute.return_value.fetchall.side_effect = [
            [],  # upper barcode
            [],  # lower barcode
            [],  # exact pn
            [
                {
                    "posting_number": "0123604587-1235-1",
                    "sticker_barcode": "",
                    "sticker_part_a": "0123604587",
                    "sticker_part_b": "1235-1",
                    "raw_json": "",
                }
            ],
        ]
        repo._row_to_dict = lambda r: dict(r)
        found = find_postings_by_sticker_scan(
            repo, user_id=1, source_id=2, scan="1235-1"
        )
        self.assertEqual(found["row"]["posting_number"], "0123604587-1235-1")

    def test_find_by_package_barcode_in_raw_json_only(self) -> None:
        repo = MagicMock()
        conn = MagicMock()
        repo._connect.return_value.__enter__.return_value = conn
        row = {
            "posting_number": "0163799058-0084-1",
            "sticker_barcode": "",
            "sticker_lower_barcode": "",
            "sticker_part_a": "",
            "sticker_part_b": "",
            "raw_json": (
                '{"posting_number":"0163799058-0084-1",'
                '"barcodes":{"upper_barcode":"751420599146000",'
                '"lower_barcode":"751420599146000"}}'
            ),
        }
        conn.execute.return_value.fetchall.side_effect = [
            [],  # upper barcode column
            [],  # lower barcode column
            [],  # exact pn
            [],  # partial pn
            [],  # part_b exact
            [],  # digit tail
            [row],  # raw_json ILIKE
        ]
        repo._row_to_dict = lambda r: dict(r)
        found = find_postings_by_sticker_scan(
            repo, user_id=1, source_id=2, scan="751420599146000"
        )
        self.assertEqual(found["row"]["posting_number"], "0163799058-0084-1")


class OzonFbsStickersPrintHtmlTests(unittest.TestCase):
    def _detail(self) -> dict:
        return {
            "supply_id": "OZ-1",
            "name": "Тест поставка",
            "orders": [
                {
                    "posting_number": "P-1",
                    "offer_id": "ART-1",
                    "product_name": "Товар",
                    "barcodes": ["460"],
                    "sku": 111,
                }
            ],
        }

    def test_full_print_includes_cover_and_separator(self) -> None:
        html = oz_sup.render_stickers_print_html(
            self._detail(),
            source_name="Ozon FBS",
            label_images={"P-1": ["QUJD"]},
            include_cover_and_separators=True,
        )
        self.assertIn('class="label cover"', html)
        self.assertIn('class="label separator"', html)
        self.assertIn('class="label sticker"', html)

    def test_selected_print_is_sticker_only(self) -> None:
        html = oz_sup.render_stickers_print_html(
            self._detail(),
            source_name="Ozon FBS",
            label_images={"P-1": ["QUJD"]},
            order_ids_filter=["P-1"],
            include_cover_and_separators=False,
        )
        self.assertNotIn('class="label cover"', html)
        self.assertNotIn('class="label separator"', html)
        self.assertIn('class="label sticker"', html)
        self.assertEqual(html.count('class="label sticker"'), 1)

    def test_missing_labels_show_screen_only_warn_banner(self) -> None:
        html = oz_sup.render_stickers_print_html(
            self._detail(),
            source_name="Ozon FBS",
            label_images={"P-1": ["QUJD"]},
            missing_posting_numbers=["61801002-0977-1"],
            missing_reasons=["cancelled on Ozon"],
            include_cover_and_separators=True,
        )
        self.assertIn('class="warn-banner"', html)
        self.assertIn("Печать готова.", html)
        self.assertIn("61801002-0977-1", html)
        self.assertIn("cancelled on Ozon", html)
        self.assertIn("screen-status", html)
        self.assertIn(".toolbar, .warn-banner, .screen-status { display: none !important; }", html)
        self.assertIn("window.print()", html)
        self.assertIn("var printed = false", html)
        self.assertIn("if (printed) return", html)

    def test_build_stickers_print_skips_cover_when_filtered(self) -> None:
        detail = {
            "supply_id": "OZ-1",
            "name": "Тест",
            "orders": [
                {
                    "posting_number": "P-1",
                    "offer_id": "A",
                    "product_name": "T",
                    "tab": "awaiting_deliver",
                    "barcodes": [],
                }
            ],
        }
        with (
            patch(
                "review_processor.ozon_fbs_supplies.get_supply_detail_for_print",
                return_value=detail,
            ),
            patch(
                "review_processor.ozon_fbs_supplies._fetch_label_images",
                return_value={"P-1": ["QUJD"]},
            ),
            patch(
                "review_processor.ozon_fbs_supplies.render_stickers_print_html",
                return_value="<html/>",
            ) as render,
        ):
            oz_sup.build_stickers_print(
                MagicMock(),
                user_id=1,
                source_id=2,
                supply_id="OZ-1",
                client_id="c",
                api_key="k",
                posting_numbers_filter=["P-1"],
            )
        self.assertFalse(render.call_args.kwargs.get("include_cover_and_separators"))

    def test_build_stickers_print_category_keeps_cover(self) -> None:
        detail = {
            "supply_id": "OZ-1",
            "name": "Тест",
            "orders": [
                {
                    "posting_number": "P-1",
                    "offer_id": "A",
                    "product_name": "T",
                    "tab": "awaiting_deliver",
                    "barcodes": [],
                },
                {
                    "posting_number": "P-2",
                    "offer_id": "A",
                    "product_name": "T",
                    "tab": "awaiting_deliver",
                    "barcodes": [],
                },
            ],
        }
        with (
            patch(
                "review_processor.ozon_fbs_supplies.get_supply_detail_for_print",
                return_value=detail,
            ),
            patch(
                "review_processor.ozon_fbs_supplies._fetch_label_images",
                return_value={"P-1": ["QUJD"], "P-2": ["QUJD"]},
            ),
            patch(
                "review_processor.ozon_fbs_supplies.render_stickers_print_html",
                return_value="<html/>",
            ) as render,
        ):
            oz_sup.build_stickers_print(
                MagicMock(),
                user_id=1,
                source_id=2,
                supply_id="OZ-1",
                client_id="c",
                api_key="k",
                posting_numbers_filter=["P-1", "P-2"],
                include_cover_and_separators=True,
            )
        self.assertTrue(render.call_args.kwargs.get("include_cover_and_separators"))
        self.assertEqual(
            render.call_args.kwargs.get("order_ids_filter"),
            ["P-1", "P-2"],
        )

    def test_category_filter_html_includes_cover_and_separator(self) -> None:
        detail = {
            "supply_id": "OZ-1",
            "name": "Поставка Кат",
            "orders": [
                {
                    "posting_number": "P-1",
                    "offer_id": "ART-1",
                    "product_name": "Товар",
                    "sku": 11,
                    "tab": "awaiting_deliver",
                    "barcodes": ["460001"],
                }
            ],
        }
        html = oz_sup.render_stickers_print_html(
            detail,
            source_name="Ozon FBS",
            label_images={"P-1": ["QUJD"]},
            order_ids_filter=["P-1"],
            include_cover_and_separators=True,
        )
        self.assertIn('class="label cover"', html)
        self.assertIn("Поставка Кат", html)
        self.assertIn('class="label separator"', html)
        self.assertIn('class="label sticker"', html)


if __name__ == "__main__":
    unittest.main()
