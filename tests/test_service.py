import os
import tempfile
import unittest
from unittest import mock

from review_processor.models import ReviewInput
from review_processor.repository import ReviewRepository
from review_processor.service import MarketplaceSyncError, ReviewAutomationService


class _StubClient:
    def fetch_reviews(self) -> list[ReviewInput]:
        return [
            ReviewInput(
                review_id="ext-1",
                text="Отличный товар, хорошее качество",
                author="Client A",
                rating=5,
            ),
            ReviewInput(
                review_id="ext-2",
                text="Ужасно, задержали доставку и курьер опоздал",
                author="Client B",
                rating=1,
            ),
        ]


class _FailClient:
    def fetch_reviews(self) -> list[ReviewInput]:
        raise MarketplaceSyncError("wb", "invalid token")


class _RecoClient:
    def fetch_reviews(self, *args: object, **kwargs: object) -> list[ReviewInput]:
        _ = args, kwargs
        return [
            ReviewInput(
                review_id="ext-reco-1",
                text="Отличный товар, все понравилось",
                author=None,
                rating=5,
                metadata={"article": "A-1"},
            )
        ]


class _PositiveDeliveryClient:
    def fetch_reviews(self, *args: object, **kwargs: object) -> list[ReviewInput]:
        _ = args, kwargs
        return [
            ReviewInput(
                review_id="ext-delivery-1",
                text="Спасибо, отличная доставка и быстрый курьер",
                author="Client C",
                rating=5,
            )
        ]


def _fake_yandex_category(review: ReviewInput) -> str:
    text = (review.text or "").lower()
    has_negative = any(word in text for word in ("ужас", "плох", "брак", "некачеств", "слом", "задерж", "опозд"))
    if any(word in text for word in ("размер", "маломер", "большемер", "мерит")):
        return "wrong_size"
    if has_negative and any(word in text for word in ("курьер", "достав", "пвз")):
        return "delivery_problems"
    if has_negative:
        return "product_dissatisfaction"
    return "positive"


class ReviewAutomationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = temp.name
        temp.close()
        self.addCleanup(lambda: os.path.exists(self.db_path) and os.unlink(self.db_path))
        self.repository = ReviewRepository(db_path=self.db_path)
        self.service = ReviewAutomationService(repository=self.repository)
        self.service._classify_with_yandex = mock.Mock(
            side_effect=lambda review, settings, strict=False, allowed_groups=None: _fake_yandex_category(review)
        )
        self.user = self.repository.create_user(email="owner@example.com", password_hash="hash", role="admin")

    def test_sync_and_list_reviews(self) -> None:
        loaded = self.service.sync_reviews(
            user_id=int(self.user["id"]),
            source="test-market",
            account_id=None,
            client=_StubClient(),
        )
        self.assertEqual(loaded, 2)

        reviews = self.service.list_reviews(user_id=int(self.user["id"]))
        self.assertEqual(len(reviews), 2)
        categories = {row["category"] for row in reviews}
        self.assertIn("delivery_problems", categories)
        self.assertIn("positive", categories)

    def test_queue_manual_and_manual_reply(self) -> None:
        self.service.sync_reviews(
            user_id=int(self.user["id"]),
            source="test-market",
            account_id=None,
            client=_StubClient(),
        )
        review = self.repository.list_reviews(user_id=int(self.user["id"]), category="delivery_problems", limit=1)[0]

        queued = self.service.queue_for_manual_processing(user_id=int(self.user["id"]), review_uid=review["review_uid"])
        self.assertTrue(queued)

        updated = self.service.save_manual_reply(
            user_id=int(self.user["id"]),
            review_uid=review["review_uid"],
            operator_name="operator-1",
            response_text="Проблему решили, проверьте заказ.",
        )
        self.assertTrue(updated)

        updated_review = self.repository.get_review(user_id=int(self.user["id"]), review_uid=review["review_uid"])
        self.assertIsNotNone(updated_review)
        self.assertEqual(updated_review["status"], "answered_manual")
        self.assertEqual(updated_review["operator_name"], "operator-1")

    def test_auto_reply_marks_review(self) -> None:
        self.repository.upsert_template(
            user_id=int(self.user["id"]),
            category="positive",
            mode="auto",
            template_text="Спасибо, {author}! Рады, что товар понравился.",
            is_enabled=True,
        )
        self.repository.upsert_processing_rule(
            user_id=int(self.user["id"]),
            group_id="positive",
            action_mode="template",
            auto_send=True,
        )
        self.service.sync_reviews(
            user_id=int(self.user["id"]),
            source="test-market",
            account_id=None,
            client=_StubClient(),
        )
        positive = self.repository.list_reviews(user_id=int(self.user["id"]), category="positive", limit=1)[0]
        self.assertEqual(positive["status"], "answered_auto")
        self.assertIn("Спасибо", positive["auto_reply"] or "")

        reply = self.service.generate_auto_reply(user_id=int(self.user["id"]), review_uid=positive["review_uid"])
        self.assertIn("Спасибо", reply)

    def test_manual_template_routes_negative_to_operator(self) -> None:
        self.repository.upsert_template(
            user_id=int(self.user["id"]),
            category="delivery_problems",
            mode="manual",
            template_text="",
            is_enabled=True,
        )
        self.repository.upsert_processing_rule(
            user_id=int(self.user["id"]),
            group_id="delivery_problems",
            action_mode="manual",
            auto_send=False,
        )
        self.service.sync_reviews(
            user_id=int(self.user["id"]),
            source="test-market",
            account_id=None,
            client=_StubClient(),
        )
        negative = self.repository.list_reviews(user_id=int(self.user["id"]), category="delivery_problems", limit=1)[0]
        self.assertEqual(negative["status"], "queued_for_operator")

    def test_sync_all_accounts_collects_errors_and_logs(self) -> None:
        self.repository.create_marketplace_account(
            user_id=int(self.user["id"]),
            marketplace="mock",
            account_name="ok-account",
            api_url="https://example.local/api/reviews",
            api_key=None,
            extra={},
        )
        self.repository.create_marketplace_account(
            user_id=int(self.user["id"]),
            marketplace="wb",
            account_name="bad-account",
            api_url="https://feedbacks-api.wildberries.ru/api/v1/feedbacks",
            api_key="bad-token",
            extra={},
        )

        def _client_for(account: dict[str, object]) -> object:
            if str(account["marketplace"]) == "mock":
                return _StubClient()
            return _FailClient()

        with mock.patch.object(self.service, "_build_client", side_effect=_client_for):
            result = self.service.sync_all_accounts(user_id=int(self.user["id"]))

        self.assertEqual(result["accounts"], 2)
        self.assertEqual(result["success_accounts"], 1)
        self.assertEqual(result["failed_accounts"], 1)
        self.assertEqual(result["loaded"], 2)
        self.assertEqual(len(result["errors"]), 1)

        actions = self.repository.list_recent_actions(user_id=int(self.user["id"]), limit=20)
        self.assertTrue(any(item["action_type"] == "sync_error" for item in actions))

    def test_template_placeholders_user_reco_brand(self) -> None:
        self.repository.replace_all_recommendations(
            user_id=int(self.user["id"]),
            rows=[{"source_article": "A-1", "target_articles": ["R-55"]}],
        )
        self.repository.upsert_template(
            user_id=int(self.user["id"]),
            category="positive",
            mode="auto",
            template_text="%USER%, спасибо за отзыв! Попробуйте %RECO%. С уважением, %BRAND%.",
            is_enabled=True,
        )
        self.repository.upsert_processing_rule(
            user_id=int(self.user["id"]),
            group_id="positive",
            action_mode="template",
            auto_send=True,
        )
        self.service.sync_reviews(
            user_id=int(self.user["id"]),
            source="test-market",
            account_id=None,
            client=_RecoClient(),
        )
        review = self.repository.list_reviews(user_id=int(self.user["id"]), category="positive", limit=1)[0]
        reply = self.service.generate_auto_reply(user_id=int(self.user["id"]), review_uid=review["review_uid"])
        self.assertNotIn("%USER%", reply)
        self.assertNotIn("%RECO%", reply)
        self.assertNotIn("%BRAND%", reply)
        self.assertIn("R-55", reply)
        self.assertIn("VarFabric", reply)
        self.assertFalse(reply.startswith(","))
        self.assertNotIn(",!", reply)

    def test_ignore_rule_requires_auto_send_to_mark_processed(self) -> None:
        self.repository.upsert_processing_rule(
            user_id=int(self.user["id"]),
            group_id="positive",
            action_mode="ignore",
            auto_send=True,
        )
        self.service.sync_reviews(
            user_id=int(self.user["id"]),
            source="test-market",
            account_id=None,
            client=_PositiveDeliveryClient(),
        )
        review = self.repository.list_reviews(user_id=int(self.user["id"]), limit=1)[0]
        self.assertEqual(review["status"], "ignored")

        self.repository.clear_reviews(user_id=int(self.user["id"]))
        self.repository.upsert_processing_rule(
            user_id=int(self.user["id"]),
            group_id="positive",
            action_mode="ignore",
            auto_send=False,
        )
        self.service.sync_reviews(
            user_id=int(self.user["id"]),
            source="test-market",
            account_id=None,
            client=_PositiveDeliveryClient(),
        )
        queued = self.repository.list_reviews(user_id=int(self.user["id"]), limit=1)[0]
        self.assertEqual(queued["status"], "queued_for_operator")

    def test_positive_delivery_uses_delivery_subgroup_template(self) -> None:
        self.repository.upsert_processing_rule(
            user_id=int(self.user["id"]),
            group_id="positive",
            action_mode="template",
            auto_send=True,
        )
        self.repository.replace_subgroup_templates(
            user_id=int(self.user["id"]),
            group_id="positive",
            subgroup="Позитив доставка",
            templates=["ТЕСТ: спасибо за быструю доставку!"],
        )
        self.service.sync_reviews(
            user_id=int(self.user["id"]),
            source="test-market",
            account_id=None,
            client=_PositiveDeliveryClient(),
        )
        review = self.repository.list_reviews(user_id=int(self.user["id"]), limit=1)[0]
        self.assertEqual(review["status"], "answered_auto")
        self.assertIn("быструю доставку", str(review.get("auto_reply") or ""))

    def test_textless_without_tags_routes_to_textless_group(self) -> None:
        review = ReviewInput(review_id="r-empty", text="", rating=5, metadata={})
        processed = self.service.processor.process(review)
        category = self.service._classify_category(review, processed, settings={"provider": "rules"})
        group_id = self.service._resolve_template_group_id(category=category, review=review, sentiment=processed.sentiment_label)
        subgroup = self.service._resolve_template_subgroup(group_id=group_id or "", category=category, review=review)
        self.assertEqual(group_id, "textless_ratings")
        self.assertEqual(subgroup, "5 звезд")

    def test_textless_with_tags_routes_to_tagged_group(self) -> None:
        review = ReviewInput(
            review_id="r-tags",
            text="",
            rating=4,
            metadata={"review_tags": ["Быстрая доставка", "Хорошее качество"]},
        )
        processed = self.service.processor.process(review)
        category = self.service._classify_category(review, processed, settings={"provider": "rules"})
        group_id = self.service._resolve_template_group_id(category=category, review=review, sentiment=processed.sentiment_label)
        subgroup = self.service._resolve_template_subgroup(group_id=group_id or "", category=category, review=review)
        self.assertEqual(group_id, "tagged_reviews")
        self.assertEqual(subgroup, "Общие теги")

    def test_neutral_text_with_size_hint_routes_to_wrong_size(self) -> None:
        review = ReviewInput(
            review_id="r-size",
            text="Классное белье, но плохо застегается молния и мломерит пододеяльник.",
            rating=4,
        )
        processed = self.service.processor.process(review)
        category = self.service._classify_category(review, processed, settings={"provider": "rules"})
        group_id = self.service._resolve_template_group_id(category=category, review=review, sentiment=processed.sentiment_label)
        subgroup = self.service._resolve_template_subgroup(group_id=group_id or "", category=category, review=review)
        self.assertIn(category, {"wrong_size", "delivery_problems", "product_dissatisfaction", "positive"})
        self.assertEqual(group_id, "wrong_size")
        self.assertEqual(subgroup, "Большемерит/маломерит")

    def test_text_review_without_yandex_configuration_raises_error(self) -> None:
        raw_service = ReviewAutomationService(repository=self.repository)
        with self.assertRaises(MarketplaceSyncError):
            raw_service.sync_reviews(
                user_id=int(self.user["id"]),
                source="test-market",
                account_id=None,
                client=_StubClient(),
            )


if __name__ == "__main__":
    unittest.main()
