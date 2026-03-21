import os
import tempfile
import unittest

from review_processor.models import ProcessedReview, ReviewInput
from review_processor.repository import ReviewRepository


class RepositoryAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = temp.name
        temp.close()
        self.addCleanup(lambda: os.path.exists(self.db_path) and os.unlink(self.db_path))
        self.repository = ReviewRepository(db_path=self.db_path)
        self.user = self.repository.create_user(email="admin@example.com", password_hash="h", role="admin")
        self.user_id = int(self.user["id"])

    def test_account_api_key_is_encrypted_at_rest(self) -> None:
        account = self.repository.create_marketplace_account(
            user_id=self.user_id,
            marketplace="ozon",
            account_name="Ozon main",
            api_url="https://api-seller.ozon.ru",
            api_key="plain-secret-token",
            extra={"client_id": "123"},
        )
        self.assertTrue(account["has_api_key"])
        self.assertNotEqual(account["api_key_preview"], "")

        db_rows = self.repository.raw_fetch(
            "SELECT api_key_encrypted FROM marketplace_accounts WHERE id = ?",
            (int(account["id"]),),
        )
        self.assertEqual(len(db_rows), 1)
        encrypted = str(db_rows[0]["api_key_encrypted"])
        self.assertNotEqual(encrypted, "plain-secret-token")

        with_secret = self.repository.get_marketplace_account(
            user_id=self.user_id,
            account_id=int(account["id"]),
            include_secrets=True,
        )
        self.assertIsNotNone(with_secret)
        self.assertEqual(with_secret["api_key"], "plain-secret-token")

    def test_ai_settings_secret_and_metrics(self) -> None:
        self.repository.update_ai_settings(
            provider="yandex",
            yandex_api_key="yandex-secret",
            yandex_folder_id="folder-1",
            yandex_model_uri="gpt://folder-1/yandexgpt-lite/latest",
        )

        public = self.repository.get_ai_settings()
        self.assertTrue(public["has_yandex_api_key"])
        self.assertNotIn("yandex_api_key", public)

        secret = self.repository.get_ai_settings(include_secrets=True)
        self.assertEqual(secret["yandex_api_key"], "yandex-secret")

        processed = ProcessedReview(
            review_id="1",
            normalized_text="bad delivery",
            sentiment_score=-3,
            sentiment_label="negative",
            is_spam=False,
            is_toxic=False,
            priority="high",
            tags=["sentiment:negative", "priority:high"],
            recommended_action="queue_for_manual_review",
        )
        self.repository.upsert_processed_review(
            user_id=self.user_id,
            source="wb",
            account_id=None,
            review=ReviewInput(review_id="ext-1", text="Плохая доставка", rating=1),
            processed=processed,
            category="negative_delivery",
            processing_mode="manual",
            status="queued_for_operator",
        )
        review_uid = self.repository.make_review_uid(self.user_id, "wb", None, "ext-1")
        self.repository.log_review_action(
            user_id=self.user_id,
            review_uid=review_uid,
            action_type="queue_manual",
            actor="operator",
            details={"reason": "negative_delivery"},
        )

        metrics = self.repository.get_sla_metrics(user_id=self.user_id)
        self.assertEqual(metrics["total_reviews"], 1)
        self.assertEqual(metrics["status_counts"].get("queued_for_operator"), 1)

        actions = self.repository.list_recent_actions(user_id=self.user_id, limit=10)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action_type"], "queue_manual")


if __name__ == "__main__":
    unittest.main()
