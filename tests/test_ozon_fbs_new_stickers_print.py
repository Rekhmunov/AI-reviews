"""New Ozon FBS stickers: v3 create + v2 get print path, old print untouched."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz
from review_processor import ozon_fbs_supplies as oz_sup
from review_processor.ozon_fbs_supplies import StickersPrintResult, build_stickers_print

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")


class OzonFbsNewLabelContractTests(unittest.TestCase):
    def test_parse_create_tasks_without_result_wrapper(self) -> None:
        tasks = oz.parse_package_label_create_tasks(
            {
                "tasks": [
                    {"task_id": 11, "task_type": "big_label"},
                    {"task_id": 12, "task_type": "small_label"},
                ]
            }
        )
        self.assertEqual(
            tasks,
            [
                {"task_id": 11, "task_type": "big_label"},
                {"task_id": 12, "task_type": "small_label"},
            ],
        )

    def test_select_prefers_small_label(self) -> None:
        chosen = oz.select_small_label_task(
            [
                {"task_id": 11, "task_type": "big_label"},
                {"task_id": 12, "task_type": "small_label"},
            ]
        )
        self.assertEqual(chosen["task_id"], 12)
        self.assertEqual(chosen["task_type"], "small_label")

    def test_parse_get_file_url_and_unprinted(self) -> None:
        parsed = oz.parse_package_label_get_result(
            {
                "file_url": "https://cdn1.ozon.ru/labels.pdf",
                "status": {
                    "code": "completed",
                    "postings_count": 2,
                    "printed_postings_count": 1,
                    "unprinted_postings": [
                        {"posting_number": "B-2", "message": "not ready"}
                    ],
                },
            }
        )
        self.assertEqual(parsed["file_url"], "https://cdn1.ozon.ru/labels.pdf")
        self.assertEqual(parsed["unprinted_postings"][0]["posting_number"], "B-2")
        self.assertTrue(oz.package_label_task_is_ready(parsed))
        self.assertFalse(oz.package_label_task_is_failed(parsed))

    def test_get_error_without_file_is_failed(self) -> None:
        parsed = oz.parse_package_label_get_result(
            {"error": {"code": "FAILED", "message": "boom"}, "status": {"code": "error"}}
        )
        self.assertTrue(oz.package_label_task_is_failed(parsed))
        self.assertFalse(oz.package_label_task_is_ready(parsed))

    def test_wrapped_result_still_parses(self) -> None:
        tasks = oz.parse_package_label_create_tasks(
            {"result": {"task_id": 77, "taskType": "small_label"}}
        )
        self.assertEqual(tasks, [{"task_id": 77, "task_type": "small_label"}])
        parsed = oz.parse_package_label_get_result(
            {"result": {"fileUrl": "https://cdn1.ozon.ru/a.pdf"}}
        )
        self.assertEqual(parsed["file_url"], "https://cdn1.ozon.ru/a.pdf")


class OzonFbsAsyncLabelClientTests(unittest.TestCase):
    def test_fetch_async_uses_v3_create_and_v2_get(self) -> None:
        client = oz.OzonFbsClient("cid", "key")
        client.post_json = MagicMock(
            side_effect=[
                {
                    "tasks": [
                        {"task_id": 1, "task_type": "big_label"},
                        {"task_id": 2, "task_type": "small_label"},
                    ]
                },
                {"status": {"code": "pending"}},
                {"file_url": "https://cdn1.ozon.ru/n.pdf", "status": {"code": "ok"}},
            ]
        )
        client.download_package_label_file = MagicMock(return_value=b"%PDF-new")
        slept: list[float] = []
        pdf, meta = client.fetch_async_package_label_pdf(
            ["P-1", "P-2"], sleep=slept.append
        )
        self.assertEqual(pdf, b"%PDF-new")
        self.assertEqual(meta["file_url"], "https://cdn1.ozon.ru/n.pdf")
        self.assertTrue(slept)
        create_call, get1, get2 = client.post_json.call_args_list
        self.assertEqual(create_call.args[0], "/v3/posting/fbs/package-label/create")
        self.assertEqual(create_call.args[1], {"posting_numbers": ["P-1", "P-2"]})
        self.assertEqual(get1.args[0], "/v2/posting/fbs/package-label/get")
        self.assertEqual(get1.args[1], {"task_id": 2})
        self.assertEqual(get2.args[1], {"task_id": 2})
        client.download_package_label_file.assert_called_once_with(
            "https://cdn1.ozon.ru/n.pdf"
        )

    def test_sync_package_label_pdf_path_unchanged(self) -> None:
        client = oz.OzonFbsClient("cid", "key")
        client.post_bytes = MagicMock(return_value=b"%PDF-old")
        out = client.package_label_pdf(["P-1"])
        self.assertEqual(out, b"%PDF-old")
        client.post_bytes.assert_called_once_with(
            "/v2/posting/fbs/package-label",
            {"posting_number": ["P-1"]},
        )

    def test_download_rejects_non_ozon_host(self) -> None:
        client = oz.OzonFbsClient("cid", "key")
        with self.assertRaises(RuntimeError) as ctx:
            client.download_package_label_file("https://example.com/x.pdf")
        self.assertIn("хост", str(ctx.exception).lower())

    def test_download_rejects_http(self) -> None:
        client = oz.OzonFbsClient("cid", "key")
        with self.assertRaises(RuntimeError):
            client.download_package_label_file("http://cdn1.ozon.ru/x.pdf")


class OzonFbsNewLabelFetchTests(unittest.TestCase):
    def test_unprinted_pages_map_to_remaining_postings(self) -> None:
        assigned = oz_sup._assign_new_label_pages(
            ["A-1", "B-2", "C-3"],
            ["img-A", "img-C"],
            {
                "unprinted_postings": [
                    {"posting_number": "B-2", "message": "not ready"}
                ]
            },
        )
        self.assertEqual(assigned["A-1"], ["img-A"])
        self.assertEqual(assigned["B-2"], [])
        self.assertEqual(assigned["C-3"], ["img-C"])

    def test_new_fetch_does_not_call_sync_package_label(self) -> None:
        client = MagicMock()
        client.fetch_async_package_label_pdf.return_value = (
            b"%PDF-ab",
            {"unprinted_postings": []},
        )
        with patch.object(
            oz_sup, "_pdf_pages_to_png_b64", return_value=["p1", "p2"]
        ):
            out = oz_sup._fetch_new_label_images(client, ["A-1", "B-2"])
        self.assertEqual(out["A-1"], ["p1"])
        self.assertEqual(out["B-2"], ["p2"])
        client.fetch_async_package_label_pdf.assert_called_once_with(["A-1", "B-2"])
        client.package_label_pdf.assert_not_called()

    def test_new_fetch_mismatch_splits_without_sync_api(self) -> None:
        client = MagicMock()

        def fake_async(nums: list[str]):
            nums = list(nums)
            if len(nums) > 1:
                return b"%PDF-BAD", {"unprinted_postings": []}
            return b"%PDF-" + nums[0].encode(), {"unprinted_postings": []}

        client.fetch_async_package_label_pdf.side_effect = fake_async

        def pages(pdf: bytes) -> list[str]:
            if b"BAD" in pdf:
                return ["only_one"]
            return [pdf.decode()]

        with patch.object(oz_sup, "_pdf_pages_to_png_b64", side_effect=pages):
            out = oz_sup._fetch_new_label_images_for_batch(
                client, ["61801002-0977-1", "64544636-0099-1"]
            )
        self.assertTrue(out["61801002-0977-1"])
        self.assertTrue(out["64544636-0099-1"])
        self.assertNotEqual(out["61801002-0977-1"], out["64544636-0099-1"])
        client.package_label_pdf.assert_not_called()

    def test_old_fetch_still_uses_sync_package_label(self) -> None:
        client = MagicMock()
        client.package_label_pdf.return_value = b"%PDF-old"
        with patch.object(oz_sup, "_pdf_pages_to_png_b64", return_value=["old"]):
            out = oz_sup._fetch_label_images(client, ["A-1"])
        self.assertEqual(out["A-1"], ["old"])
        client.package_label_pdf.assert_called_once_with(["A-1"])
        client.fetch_async_package_label_pdf.assert_not_called()


class OzonFbsBuildStickersNewLabelsTests(unittest.TestCase):
    def _detail(self) -> dict:
        return {
            "supply_id": "OZ-FBS-1",
            "name": "Test",
            "orders": [
                {
                    "posting_number": "A-1",
                    "offer_id": "SKU1",
                    "tab": "awaiting_deliver",
                }
            ],
            "order_count": 1,
        }

    def test_use_new_labels_calls_new_fetch_only(self) -> None:
        repo = MagicMock()
        with patch(
            "review_processor.ozon_fbs_supplies.get_supply_detail_for_print",
            return_value=self._detail(),
        ), patch(
            "review_processor.ozon_fbs_supplies.oz.OzonFbsClient"
        ), patch(
            "review_processor.ozon_fbs_supplies._enrich_empty_package_stickers_for_print"
        ), patch(
            "review_processor.ozon_fbs_supplies._fetch_label_images"
        ) as old_fetch, patch(
            "review_processor.ozon_fbs_supplies._fetch_new_label_images",
            return_value={"A-1": ["img"]},
        ) as new_fetch, patch(
            "review_processor.ozon_fbs_supplies._bind_package_stickers_after_label_print"
        ), patch("review_processor.ozon_fbs_supplies._log"):
            result = build_stickers_print(
                repo,
                user_id=1,
                source_id=13,
                supply_id="OZ-FBS-1",
                client_id="cid",
                api_key="key",
                use_new_labels=True,
            )
        new_fetch.assert_called_once()
        old_fetch.assert_not_called()
        self.assertIsInstance(result, StickersPrintResult)
        self.assertEqual(result.loaded_count, 1)
        self.assertEqual(result.missing_posting_numbers, [])

    def test_default_print_still_uses_old_fetch(self) -> None:
        repo = MagicMock()
        with patch(
            "review_processor.ozon_fbs_supplies.get_supply_detail_for_print",
            return_value=self._detail(),
        ), patch(
            "review_processor.ozon_fbs_supplies.oz.OzonFbsClient"
        ), patch(
            "review_processor.ozon_fbs_supplies._enrich_empty_package_stickers_for_print"
        ), patch(
            "review_processor.ozon_fbs_supplies._fetch_label_images",
            return_value={"A-1": ["old"]},
        ) as old_fetch, patch(
            "review_processor.ozon_fbs_supplies._fetch_new_label_images"
        ) as new_fetch, patch(
            "review_processor.ozon_fbs_supplies._bind_package_stickers_after_label_print"
        ), patch("review_processor.ozon_fbs_supplies._log"):
            result = build_stickers_print(
                repo,
                user_id=1,
                source_id=13,
                supply_id="OZ-FBS-1",
                client_id="cid",
                api_key="key",
            )
        old_fetch.assert_called_once()
        new_fetch.assert_not_called()
        self.assertEqual(result.loaded_count, 1)


class OzonFbsNewStickersUiTests(unittest.TestCase):
    def test_supply_modal_renames_and_opens_v3_to_all(self) -> None:
        self.assertIn('id="ozonFbsSupplyDetailStickersBtn"', HTML)
        self.assertIn('id="ozonFbsSupplyDetailNewStickersBtn"', HTML)
        self.assertIn(">Старые стикеры<", HTML)
        self.assertIn(">Стикеры<", HTML)
        self.assertNotIn(">Новые стикеры<", HTML)
        self.assertIn("ozonFbsOpenNewStickersPrint()", HTML)
        stickers_at = HTML.find('id="ozonFbsSupplyDetailStickersBtn"')
        new_at = HTML.find('id="ozonFbsSupplyDetailNewStickersBtn"')
        trbx_at = HTML.find('id="ozonFbsSupplyDetailTrbxBtn"')
        self.assertLess(stickers_at, new_at)
        self.assertLess(new_at, trbx_at)
        # v3 «Стикеры» visible to all users (split not owner-hidden).
        split_at = HTML.find('id="ozonFbsNewStickersSplit"')
        self.assertGreater(split_at, 0)
        self.assertLess(split_at, new_at)
        chunk = HTML[split_at : split_at + 80]
        self.assertNotIn("hidden", chunk)
        old_btn = HTML[stickers_at : stickers_at + 220]
        self.assertIn("Старые стикеры", old_btn)
        new_btn = HTML[new_at : new_at + 220]
        self.assertIn(">Стикеры<", new_btn)

    def test_new_stickers_has_category_caret_like_old(self) -> None:
        self.assertIn('id="ozonFbsSupplyDetailNewStickersMenuBtn"', HTML)
        self.assertIn('id="ozonFbsNewStickersMenu"', HTML)
        self.assertIn("toggleOzonFbsNewStickersMenu(event)", HTML)
        self.assertIn(
            "openOzonFbsStickersByCategoryModal({ newLabels: true })",
            HTML,
        )
        new_split = HTML[
            HTML.find('id="ozonFbsNewStickersSplit"') : HTML.find(
                'id="ozonFbsSupplyDetailTrbxBtn"'
            )
        ]
        self.assertIn("wb-fbs-picking-caret", new_split)
        self.assertIn("Печать по категориям", new_split)
        self.assertIn(
            "openOzonFbsStickersByCategoryModal({ newLabels: true })",
            new_split,
        )
        # Same caret pattern as ordinary stickers split — still old labels.
        old_split = HTML[
            HTML.find('id="ozonFbsStickersSplit"') : HTML.find(
                'id="ozonFbsNewStickersSplit"'
            )
        ]
        self.assertIn("wb-fbs-picking-caret", old_split)
        self.assertIn("Печать по категориям", old_split)
        self.assertIn("openOzonFbsStickersByCategoryModal()", old_split)
        self.assertNotIn("newLabels: true", old_split)
        self.assertIn("Старые стикеры", old_split)
        self.assertIn("ozonFbsOpenStickersPrint()", old_split)

    def test_js_sends_new_labels_flag_and_keeps_old_default(self) -> None:
        self.assertIn("ozonFbsOpenNewStickersPrint", JS)
        self.assertIn("newLabels: true", JS)
        self.assertIn("new_labels: newLabels", JS)
        self.assertIn(
            'window.ozonFbsOpenStickersPrint = () => openStickersPrint();',
            JS,
        )
        self.assertIn("ozonFbsSupplyDetailNewStickersBtn", JS)
        self.assertIn("function toggleNewStickersMenu", JS)
        self.assertIn("window.toggleOzonFbsNewStickersMenu = toggleNewStickersMenu", JS)
        self.assertIn("stickersCategoryState.newLabels", JS)
        self.assertIn('"Старые стикеры"', JS)
        self.assertIn("const activeBtn = newLabels ? newBtn : oldBtn;", JS)
        self.assertIn('const idleLabel = newLabels ? "Стикеры" : "Старые стикеры";', JS)
        self.assertIn("newBtn.textContent = busy ? (text || waitLabel) : idleLabel;", JS)
        # Progress poll must keep idleLabel/activeBtn (regression: ReferenceError in tab).
        open_print = JS[
            JS.find("function openStickersPrint") : JS.find(
                "function _ozonFbsStickersCategorySetInfo"
            )
        ]
        self.assertIn("${idleLabel}", open_print)
        self.assertIn("activeBtn.textContent = progressText", open_print)
        # No owner gate on v3 print entry.
        open_new = JS[
            JS.find("window.ozonFbsOpenNewStickersPrint") : JS.find(
                "window.toggleOzonFbsStickersMenu"
            )
        ]
        self.assertNotIn("isTenantOwner", open_new)
        print_at = JS.find("function ozonFbsPrintStickersByCategory")
        self.assertGreater(print_at, 0)
        print_fn = JS[print_at : print_at + 900]
        self.assertIn("stickersCategoryState.newLabels", print_fn)
        self.assertIn("includeCoverAndSeparators: true", print_fn)
        self.assertIn("newLabels", print_fn)
        # Row ⋮ «Напечатать стикер» must use v3 like the primary «Стикеры» button.
        one_at = JS.find("function printOnePostingStickerFromDetail")
        self.assertGreater(one_at, 0)
        one_fn = JS[one_at : JS.find("function cancelBadgeHtml", one_at)]
        self.assertIn("openStickersPrint([pn], { newLabels: true })", one_fn)
        self.assertNotIn("openStickersPrint([pn]);", one_fn)
        # While supply modal is open — never fall back to legacy GET stickers.
        self.assertIn("if (supplyDetailReady())", one_fn)
        self.assertLess(
            one_fn.find("openStickersPrint([pn], { newLabels: true })"),
            one_fn.find("_ozonFbsLookupSupplyIdForPosting"),
        )
        # Lookup ⋮ with local supply → async v3 job (supplyId override, no modal).
        self.assertIn("supplyId: lookupSupplyId", one_fn)
        self.assertIn("newLabels: true", one_fn)
        self.assertNotIn("/stickers-print`", one_fn)
        self.assertNotIn("openPrintHtml(url", one_fn)
        # Lookup ⋮ without supply → v3 PDF endpoint.
        self.assertIn("/api/ozon-fbs/postings/stickers-print?", one_fn)
        self.assertIn("openPrintPdf(url", one_fn)
        # openStickersPrint accepts standalone supplyId (lookup without modal).
        open_print = JS[
            JS.find("function openStickersPrint") : JS.find(
                "function _ozonFbsStickersCategorySetInfo"
            )
        ]
        self.assertIn("opts.supplyId", open_print)
        self.assertIn("const standalone = !!opts.supplyId", open_print)
        # Detail card «Этикетка» → same v3 PDF helper (not window.open).
        cur_at = JS.find("function printCurrentSticker")
        self.assertGreater(cur_at, 0)
        cur_fn = JS[cur_at : JS.find("/* ── Selection", cur_at)]
        self.assertIn("/api/ozon-fbs/postings/stickers-print?", cur_fn)
        self.assertIn("openPrintPdf(url", cur_fn)
        self.assertNotIn("window.open(url", cur_fn)
        # КИЗ / без КИЗ ⋮ share the same v3 helper.
        self.assertIn(
            "onclick=\"ozonFbsPrintOnePostingStickerFromDetail(event, '${safePn}')\"",
            JS,
        )
        menu_at = JS.find("function _ozonFbsModalRowMenuItemsHtml")
        self.assertGreater(menu_at, 0)
        menu_fn = JS[menu_at : JS.find("function _ozonFbsSyncRowMenuContent", menu_at)]
        self.assertIn("Напечатать стикер", menu_fn)
        self.assertIn("ozonFbsPrintOnePostingStickerFromDetail", menu_fn)
        # Supply-detail ⋮ uses data-ozon-action → same helper.
        self.assertIn("data-ozon-action=\"print-sticker\"", JS)
        self.assertIn("printOnePostingStickerFromDetail(e, pn)", JS)
        # Category print preserves newLabels from the opener (Стикеры vs Старые).
        cat_print = JS[
            JS.find("function ozonFbsPrintStickersByCategory") : JS.find(
                "document.addEventListener",
                JS.find("function ozonFbsPrintStickersByCategory"),
            )
        ]
        self.assertIn("stickersCategoryState.newLabels", cat_print)
        self.assertIn("newLabels,", cat_print)
        # «Старые стикеры» entry stays without newLabels.
        self.assertIn(
            "window.ozonFbsOpenStickersPrint = () => openStickersPrint();",
            JS,
        )
        open_old = JS[
            JS.find("window.ozonFbsOpenStickersPrint") : JS.find(
                "window.ozonFbsOpenNewStickersPrint"
            )
        ]
        self.assertNotIn("newLabels", open_old)

    def test_v3_stickers_open_to_all_users_ui_and_api(self) -> None:
        sync = JS[
            JS.find("function _ozonFbsSyncOwnerOnlyNewStickersBtn") : JS.find(
                "function _ozonFbsSyncOwnerOnlyAllCancellationsBtn"
            )
        ]
        self.assertIn("ozonFbsNewStickersSplit", sync)
        self.assertIn("split.hidden = false", sync)
        self.assertNotIn("isTenantOwner", sync)
        web = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
        start = web.find('@app.post("/api/ozon-fbs/supplies/{supply_id}/stickers-print/start")')
        self.assertGreater(start, 0)
        chunk = web[start : start + 2200]
        self.assertIn("use_new_labels", chunk)
        self.assertNotIn("Новые стикеры доступны только основному пользователю", chunk)
        self.assertNotIn(
            "use_new_labels and not (\n            user_is_tenant_owner(user)",
            chunk,
        )

    def test_cache_bump(self) -> None:
        self.assertIn("ozon_fbs.js?v=218", HTML)


if __name__ == "__main__":
    unittest.main()
