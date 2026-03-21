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

    def test_conversation_storage_and_user_analytics(self) -> None:
        conv_uid = self.repository.upsert_conversation(
            user_id=self.user_id,
            source="ozon",
            account_id=None,
            external_conversation_id="chat-1",
            kind="chat",
            customer_name="Buyer A",
            message_text="Когда отправите заказ?",
            status="open",
            unread_count=2,
            metadata={"topic": "delivery"},
        )
        self.assertTrue(conv_uid.startswith(f"{self.user_id}:ozon"))

        question_uid = self.repository.upsert_conversation(
            user_id=self.user_id,
            source="wb",
            account_id=None,
            external_conversation_id="q-1",
            kind="question",
            customer_name="Buyer B",
            message_text="Какой состав ткани?",
            status="waiting",
            unread_count=1,
            metadata={"topic": "material"},
        )
        self.assertTrue(question_uid.startswith(f"{self.user_id}:wb"))

        rows = self.repository.list_conversations(user_id=self.user_id)
        self.assertEqual(len(rows), 2)

        closed = self.repository.update_conversation_status(
            user_id=self.user_id,
            conversation_uid=conv_uid,
            status="closed",
        )
        self.assertTrue(closed)
        rows_after = self.repository.list_conversations(user_id=self.user_id, status="closed")
        self.assertEqual(len(rows_after), 1)
        self.assertEqual(rows_after[0]["unread_count"], 0)

        # Add one positive processed review for analytics percentages.
        processed_positive = ProcessedReview(
            review_id="2",
            normalized_text="great quality",
            sentiment_score=4,
            sentiment_label="positive",
            is_spam=False,
            is_toxic=False,
            priority="low",
            tags=["sentiment:positive", "priority:low"],
            recommended_action="auto_close_with_thanks",
        )
        self.repository.upsert_processed_review(
            user_id=self.user_id,
            source="ozon",
            account_id=None,
            review=ReviewInput(review_id="ext-2", text="Отличное качество", rating=5),
            processed=processed_positive,
            category="positive_product",
            processing_mode="auto",
            status="answered_auto",
            auto_reply="Спасибо!",
        )

        analytics = self.repository.get_user_analytics(user_id=self.user_id)
        self.assertEqual(analytics["total_reviews"], 1)
        self.assertEqual(analytics["processed_reviews"], 1)
        self.assertEqual(analytics["positive_count"], 1)
        self.assertEqual(analytics["questions_count"], 1)
        self.assertEqual(analytics["chats_count"], 1)


if __name__ == "__main__":
    unittest.main()
