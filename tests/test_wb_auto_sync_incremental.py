"""WB auto-sync must not dual-pass full history (starves other cabinets)."""

from __future__ import annotations

import unittest
from unittest import mock

from review_processor.models import ReviewInput
from review_processor.service import ReviewAutomationService, WildberriesMarketplaceClient


class _RecordingWbClient(WildberriesMarketplaceClient):
    def __init__(self) -> None:
        super().__init__(
            api_url="https://feedbacks-api.wildberries.ru/api/v1/feedbacks",
            api_key="token-1",
            page_size=100,
            max_pages=5,
            questions_path="/api/v1/questions",
        )
        self.review_passes: list[str] = []
        self.question_passes: list[str] = []
        self.request_orders: list[str | None] = []

    def _request_json(
        self,
        *,
        skip: int,
        take: int,
        since_date: str | None = None,
        order: str | None = None,
    ) -> dict[str, object]:
        _ = skip, take, since_date
        self.review_passes.append(str(self.unanswered_value))
        self.request_orders.append(order)
        answered = str(self.unanswered_value) == "true"
        if answered:
            feedbacks = [
                {
                    "id": f"w-textless-{skip}",
                    "text": "",
                    "pros": "",
                    "cons": "",
                    "productValuation": 5,
                    "photoLinks": None,
                    "answer": None,
                },
                {
                    "id": f"w-answered-{skip}",
                    "text": "ok",
                    "productValuation": 5,
                    "answer": {"text": "Спасибо!"},
                },
            ]
        else:
            feedbacks = [
                {
                    "id": f"w-{self.unanswered_value}-{skip}",
                    "text": "ok",
                    "productValuation": 5,
                }
            ]
        return {"data": {"feedbacks": feedbacks}}

    def _fetch_conversation_endpoint(self, **kwargs: object) -> list[dict[str, object]]:
        _ = kwargs
        self.question_passes.append(str(self.unanswered_value))
        return [
            {
                "external_id": f"q-{self.unanswered_value}",
                "customer_name": "Клиент",
                "message_text": "Вопрос",
                "created_at": "2026-09-01T12:00:00Z",
                "metadata": {"raw": {}},
            }
        ]


def _service_with_mock_repo() -> ReviewAutomationService:
    repo = mock.Mock()
    repo.get_pending_retry_reviews.return_value = []
    repo.get_ai_settings.return_value = {}
    repo.get_contradiction_rules.return_value = []
    repo.get_review_contradiction_map.return_value = {}
    repo.get_existing_classifications.return_value = {}
    repo.get_existing_classification_for_uid.return_value = None
    repo.get_review_sync_states_for_account.return_value = {}
    repo.upsert_review.return_value = {"review_uid": "u1", "is_new": True}
    repo.list_processing_rules.return_value = []
    repo.get_user_sync_settings.return_value = {}
    repo.get_ai_usage_requests_for_date.return_value = 0
    repo.list_ai_classification_backlog.return_value = []
    repo.make_review_uid.side_effect = lambda uid, src, acc, rid: f"{uid}:{src}:{acc}:{rid}"
    return ReviewAutomationService(repository=repo)


class WbAutoSyncIncrementalTests(unittest.TestCase):
    def test_fetch_reviews_iter_skips_answered_pass_when_requested(self) -> None:
        client = _RecordingWbClient()
        with mock.patch("review_processor.service.time.sleep", return_value=None):
            reviews = list(client.fetch_reviews_iter(include_answered=False))
        self.assertEqual(client.review_passes, ["false"])
        self.assertEqual(len(reviews), 1)

    def test_fetch_reviews_iter_dual_pass_by_default(self) -> None:
        client = _RecordingWbClient()
        with mock.patch("review_processor.service.time.sleep", return_value=None):
            reviews = list(client.fetch_reviews_iter())
        self.assertEqual(client.review_passes, ["false", "true"])
        self.assertEqual(len(reviews), 3)  # 1 unanswered + 2 from answered pass (unfiltered)

    def test_fetch_reviews_iter_textless_unreplied_bounded_pass(self) -> None:
        client = _RecordingWbClient()
        with mock.patch("review_processor.service.time.sleep", return_value=None):
            reviews = list(
                client.fetch_reviews_iter(
                    include_answered=False,
                    include_textless_unreplied=True,
                    since_date="2020-01-01",
                )
            )
        self.assertEqual(client.review_passes, ["false", "true"])
        self.assertIn("dateDesc", client.request_orders)
        ids = [r.review_id for r in reviews]
        self.assertIn("w-false-0", ids)
        self.assertIn("w-textless-0", ids)
        self.assertNotIn("w-answered-0", ids)
        textless = next(r for r in reviews if r.review_id == "w-textless-0")
        self.assertEqual((textless.text or "").strip(), "")
        self.assertTrue(WildberriesMarketplaceClient._is_textless_unreplied(textless))

    def test_review_has_media_ignores_product_card_images(self) -> None:
        """WB productDetails image URLs must not force Yandex classification."""
        service = ReviewAutomationService(repository=mock.Mock())
        rating_only = ReviewInput(
            review_id="r1",
            text="",
            rating=5,
            metadata={
                "raw": {
                    "text": "",
                    "pros": "",
                    "cons": "",
                    "photoLinks": None,
                    "video": None,
                    "productDetails": {
                        "productName": "Товар",
                        "imgtm": "https://basket.wb.ru/vol1/part1/123/images/big/1.webp",
                    },
                },
                "marketplace": "wb",
            },
        )
        with_buyer_photo = ReviewInput(
            review_id="r2",
            text="",
            rating=4,
            metadata={
                "raw": {
                    "photoLinks": [{"fullSize": "https://feedback/photo.jpg"}],
                    "productDetails": {"imgtm": "https://basket.wb.ru/x.webp"},
                }
            },
        )
        self.assertFalse(service._review_has_media(rating_only))
        self.assertTrue(service._review_has_media(with_buyer_photo))
        category, subgroup = service._classify_category_and_subgroup(
            rating_only,
            type("P", (), {"sentiment_label": "neutral"})(),
            settings={"provider": "rules"},
        )
        self.assertEqual(category, "textless_ratings")
        self.assertEqual(subgroup, "5 звезд")

    def test_is_textless_unreplied_rejects_photos_and_answers(self) -> None:
        with_answer = ReviewInput(
            review_id="a1",
            text="",
            rating=5,
            metadata={"raw": {"answer": {"text": "ok"}, "photoLinks": None}},
        )
        with_photo = ReviewInput(
            review_id="a2",
            text="",
            rating=4,
            metadata={"raw": {"photoLinks": [{"fullSize": "https://img/x.jpg"}]}},
        )
        with_text = ReviewInput(
            review_id="a3",
            text="норм",
            rating=5,
            metadata={"raw": {}},
        )
        plain = ReviewInput(
            review_id="a4",
            text="",
            rating=5,
            metadata={"raw": {"text": "", "pros": "", "cons": "", "answer": None}},
        )
        self.assertFalse(WildberriesMarketplaceClient._is_textless_unreplied(with_answer))
        self.assertFalse(WildberriesMarketplaceClient._is_textless_unreplied(with_photo))
        self.assertFalse(WildberriesMarketplaceClient._is_textless_unreplied(with_text))
        self.assertTrue(WildberriesMarketplaceClient._is_textless_unreplied(plain))

    def test_fetch_questions_skips_answered_pass_when_include_answered_false(self) -> None:
        client = _RecordingWbClient()
        rows = client.fetch_questions(include_answered=False)
        self.assertEqual(client.question_passes, ["false"])
        self.assertEqual(len(rows), 1)

    def test_auto_sync_reviews_passes_include_answered_false(self) -> None:
        service = _service_with_mock_repo()
        service._list_group_subgroups_for_review_classification = mock.Mock(return_value=[])  # type: ignore[method-assign]
        client = _RecordingWbClient()
        seen: dict[str, object] = {}

        def _iter(**kwargs: object):
            seen.update(kwargs)
            return
            yield  # pragma: no cover

        client.fetch_reviews_iter = _iter  # type: ignore[method-assign]
        loaded = service.sync_reviews(
            user_id=1,
            source="wb",
            account_id=29,
            client=client,
            since_date="2026-01-01",
            apply_date_filter=False,
        )
        self.assertEqual(loaded, 0)
        self.assertEqual(seen.get("include_answered"), False)
        self.assertEqual(seen.get("include_textless_unreplied"), True)

    def test_manual_sync_reviews_keeps_answered_pass(self) -> None:
        service = _service_with_mock_repo()
        service._list_group_subgroups_for_review_classification = mock.Mock(return_value=[])  # type: ignore[method-assign]
        client = _RecordingWbClient()
        seen: dict[str, object] = {}

        def _iter(**kwargs: object):
            seen.update(kwargs)
            return
            yield  # pragma: no cover

        client.fetch_reviews_iter = _iter  # type: ignore[method-assign]
        loaded = service.sync_reviews(
            user_id=1,
            source="wb",
            account_id=29,
            client=client,
            since_date="2026-01-01",
            apply_date_filter=True,
        )
        self.assertEqual(loaded, 0)
        self.assertNotIn("include_answered", seen)
        self.assertNotIn("include_textless_unreplied", seen)

    def test_textless_unreplied_since_date_clamps_lookback(self) -> None:
        clamped = WildberriesMarketplaceClient._textless_unreplied_since_date("2020-01-01")
        self.assertIsNotNone(clamped)
        assert clamped is not None
        self.assertGreater(clamped, "2020-01-01")
        recent = WildberriesMarketplaceClient._textless_unreplied_since_date("2099-01-01")
        self.assertEqual(recent, "2099-01-01")

    def test_auto_sync_sends_reply_for_textless_from_answered_pass(self) -> None:
        """Rating-only WB items live in isAnswered=true; auto-sync must still answer them."""
        service = _service_with_mock_repo()
        repo = service.repository
        service._list_group_subgroups_for_review_classification = mock.Mock(return_value=[])  # type: ignore[method-assign]
        service._pick_group_template_text = mock.Mock(return_value="Спасибо за 5 звезд!")  # type: ignore[method-assign]
        repo.get_processing_rule.return_value = {
            "group_id": "textless_ratings",
            "action_mode": "template",
            "auto_send": True,
        }
        repo.get_template.return_value = None
        repo.build_template_variables_context.return_value = {}
        sent: list[tuple[str, str]] = []

        class _Client(_RecordingWbClient):
            def _request_json(
                self,
                *,
                skip: int,
                take: int,
                since_date: str | None = None,
                order: str | None = None,
            ) -> dict[str, object]:
                _ = take, since_date, order
                self.review_passes.append(str(self.unanswered_value))
                if str(self.unanswered_value) == "false":
                    return {"data": {"feedbacks": []}}
                return {
                    "data": {
                        "feedbacks": [
                            {
                                "id": "textless-only-1",
                                "text": "",
                                "pros": "",
                                "cons": "",
                                "productValuation": 5,
                                "userName": "Buyer",
                                "photoLinks": None,
                                "answer": None,
                                "createdDate": "2026-09-20T10:00:00Z",
                            }
                        ]
                    }
                }

            def send_review_reply(self, *, review: ReviewInput, response_text: str) -> bool:
                sent.append((review.review_id, response_text))
                return True

        client = _Client()
        with mock.patch("review_processor.service.time.sleep", return_value=None):
            loaded = service.sync_reviews(
                user_id=1,
                source="wb",
                account_id=30,
                client=client,
                since_date="2026-09-01",
                apply_date_filter=False,
            )
        self.assertEqual(loaded, 1)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], "textless-only-1")
        self.assertIn("5", sent[0][1])
        upsert_calls = [
            c.kwargs for c in repo.upsert_processed_review.call_args_list
        ]
        self.assertTrue(upsert_calls)
        self.assertEqual(upsert_calls[-1].get("status"), "answered_auto")


if __name__ == "__main__":
    unittest.main()
