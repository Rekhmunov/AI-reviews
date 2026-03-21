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


class ReviewAutomationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = temp.name
        temp.close()
        self.addCleanup(lambda: os.path.exists(self.db_path) and os.unlink(self.db_path))
        self.repository = ReviewRepository(db_path=self.db_path)
        self.service = ReviewAutomationService(repository=self.repository)
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
        self.assertIn("negative_delivery", categories)
        self.assertIn("positive_product", categories)

    def test_queue_manual_and_manual_reply(self) -> None:
        self.service.sync_reviews(
            user_id=int(self.user["id"]),
            source="test-market",
            account_id=None,
            client=_StubClient(),
        )
        review = self.repository.list_reviews(user_id=int(self.user["id"]), category="negative_delivery", limit=1)[0]

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
            category="positive_product",
            mode="auto",
            template_text="Спасибо, {author}! Рады, что товар понравился.",
            is_enabled=True,
        )
        self.service.sync_reviews(
            user_id=int(self.user["id"]),
            source="test-market",
            account_id=None,
            client=_StubClient(),
        )
        positive = self.repository.list_reviews(user_id=int(self.user["id"]), category="positive_product", limit=1)[0]
        self.assertEqual(positive["status"], "answered_auto")
        self.assertIn("Спасибо", positive["auto_reply"] or "")

        reply = self.service.generate_auto_reply(user_id=int(self.user["id"]), review_uid=positive["review_uid"])
        self.assertIn("Спасибо", reply)

    def test_manual_template_routes_negative_to_operator(self) -> None:
        self.repository.upsert_template(
            user_id=int(self.user["id"]),
            category="negative_delivery",
            mode="manual",
            template_text="",
            is_enabled=True,
        )
        self.service.sync_reviews(
            user_id=int(self.user["id"]),
            source="test-market",
            account_id=None,
            client=_StubClient(),
        )
        negative = self.repository.list_reviews(user_id=int(self.user["id"]), category="negative_delivery", limit=1)[0]
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


if __name__ == "__main__":
    unittest.main()
