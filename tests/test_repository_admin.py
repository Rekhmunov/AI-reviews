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

    def test_template_flags_and_pagination(self) -> None:
        self.repository.upsert_template(
            user_id=self.user_id,
            category="negative_delivery",
            mode="manual",
            template_text="",
            is_enabled=True,
        )
        tpl = self.repository.get_template(user_id=self.user_id, category="negative_delivery")
        self.assertIsNotNone(tpl)
        assert tpl is not None
        self.assertTrue(tpl["is_enabled"])

        self.repository.upsert_template(
            user_id=self.user_id,
            category="negative_delivery",
            mode="manual",
            template_text="",
            is_enabled=False,
        )
        tpl_disabled = self.repository.get_template(user_id=self.user_id, category="negative_delivery")
        self.assertIsNotNone(tpl_disabled)
        assert tpl_disabled is not None
        self.assertFalse(tpl_disabled["is_enabled"])

        deleted = self.repository.delete_template(user_id=self.user_id, category="negative_delivery")
        self.assertTrue(deleted)
        self.assertIsNone(self.repository.get_template(user_id=self.user_id, category="negative_delivery"))

        processed_negative = ProcessedReview(
            review_id="10",
            normalized_text="bad",
            sentiment_score=-2,
            sentiment_label="negative",
            is_spam=False,
            is_toxic=False,
            priority="high",
            tags=["sentiment:negative"],
            recommended_action="queue_for_manual_review",
        )
        processed_positive = ProcessedReview(
            review_id="11",
            normalized_text="good",
            sentiment_score=3,
            sentiment_label="positive",
            is_spam=False,
            is_toxic=False,
            priority="low",
            tags=["sentiment:positive"],
            recommended_action="auto_close_with_thanks",
        )
        self.repository.upsert_processed_review(
            user_id=self.user_id,
            source="wb",
            account_id=None,
            review=ReviewInput(review_id="ext-p-1", text="Плохо", rating=1),
            processed=processed_negative,
            category="negative_delivery",
            processing_mode="manual",
            status="queued_for_operator",
        )
        self.repository.upsert_processed_review(
            user_id=self.user_id,
            source="wb",
            account_id=None,
            review=ReviewInput(review_id="ext-p-2", text="Хорошо", rating=5),
            processed=processed_positive,
            category="positive_product",
            processing_mode="auto",
            status="answered_auto",
            auto_reply="Спасибо",
        )

        page = self.repository.list_reviews_paginated(user_id=self.user_id, bucket="new", page=1, page_size=10)
        self.assertEqual(page["new_count"], 1)
        self.assertEqual(page["processed_count"], 1)
        self.assertEqual(page["total"], 1)

        deleted_reviews = self.repository.clear_reviews(user_id=self.user_id)
        self.assertEqual(deleted_reviews, 2)

    def test_processing_rules_and_template_variants(self) -> None:
        created = self.repository.add_template_variant(
            user_id=self.user_id,
            group_id="positive",
            subgroup="Вкус",
            template_text="Шаблон 1",
        )
        self.assertEqual(created["group_id"], "positive")
        variants = self.repository.list_template_variants(user_id=self.user_id, group_id="positive", subgroup="Вкус")
        self.assertGreaterEqual(len(variants), 1)

        random_tpl = self.repository.get_random_template_variant(user_id=self.user_id, group_id="positive")
        self.assertIsNotNone(random_tpl)

        self.repository.upsert_processing_rule(
            user_id=self.user_id,
            group_id="positive",
            action_mode="template",
            auto_send=True,
        )
        rule = self.repository.get_processing_rule(user_id=self.user_id, group_id="positive")
        self.assertIsNotNone(rule)
        assert rule is not None
        self.assertEqual(rule["action_mode"], "template")
        self.assertTrue(rule["auto_send"])

        self.repository.replace_processing_rules(
            user_id=self.user_id,
            rules=[{"group_id": "wrong_size", "action_mode": "manual", "auto_send": False}],
        )
        listed = self.repository.list_processing_rules(user_id=self.user_id)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["group_id"], "wrong_size")

    def test_reviews_date_filter_and_sorting(self) -> None:
        processed = ProcessedReview(
            review_id="20",
            normalized_text="ok",
            sentiment_score=1,
            sentiment_label="neutral",
            is_spam=False,
            is_toxic=False,
            priority="medium",
            tags=["sentiment:neutral"],
            recommended_action="queue_for_manual_review",
        )
        self.repository.upsert_processed_review(
            user_id=self.user_id,
            source="wb",
            account_id=None,
            review=ReviewInput(review_id="ext-date-1", text="Отзыв 1", rating=5),
            processed=processed,
            category="positive_product",
            processing_mode="manual",
            status="queued_for_operator",
        )
        self.repository.upsert_processed_review(
            user_id=self.user_id,
            source="wb",
            account_id=None,
            review=ReviewInput(review_id="ext-date-2", text="Отзыв 2", rating=1),
            processed=processed,
            category="negative_delivery",
            processing_mode="manual",
            status="queued_for_operator",
        )
        self.repository.upsert_processed_review(
            user_id=self.user_id,
            source="wb",
            account_id=None,
            review=ReviewInput(review_id="ext-date-3", text="Отзыв 3", rating=3),
            processed=processed,
            category="neutral_other",
            processing_mode="manual",
            status="queued_for_operator",
        )
        with self.repository._connect() as conn:
            conn.execute(
                """
                UPDATE review_items
                SET updated_at = ?
                WHERE user_id = ? AND external_review_id = ?
                """,
                ("2026-03-10T10:00:00+00:00", self.user_id, "ext-date-1"),
            )
            conn.execute(
                """
                UPDATE review_items
                SET updated_at = ?
                WHERE user_id = ? AND external_review_id = ?
                """,
                ("2026-03-11T10:00:00+00:00", self.user_id, "ext-date-2"),
            )
            conn.execute(
                """
                UPDATE review_items
                SET updated_at = ?
                WHERE user_id = ? AND external_review_id = ?
                """,
                ("2026-03-12T10:00:00+00:00", self.user_id, "ext-date-3"),
            )

        date_filtered = self.repository.list_reviews_paginated(
            user_id=self.user_id,
            date_from="2026-03-11",
            date_to="2026-03-12",
            sort="newest",
            page=1,
            page_size=10,
        )
        self.assertEqual(date_filtered["total"], 2)
        self.assertEqual(date_filtered["items"][0]["external_review_id"], "ext-date-3")
        self.assertEqual(date_filtered["items"][1]["external_review_id"], "ext-date-2")

        by_oldest = self.repository.list_reviews_paginated(
            user_id=self.user_id,
            sort="oldest",
            page=1,
            page_size=10,
        )
        self.assertEqual(by_oldest["items"][0]["external_review_id"], "ext-date-1")

        by_low_rating = self.repository.list_reviews_paginated(
            user_id=self.user_id,
            sort="rating_asc",
            page=1,
            page_size=10,
        )
        self.assertEqual(by_low_rating["items"][0]["external_review_id"], "ext-date-2")

        by_high_rating = self.repository.list_reviews_paginated(
            user_id=self.user_id,
            sort="rating_desc",
            page=1,
            page_size=10,
        )
        self.assertEqual(by_high_rating["items"][0]["external_review_id"], "ext-date-1")

        by_category = self.repository.list_reviews_paginated(
            user_id=self.user_id,
            sort="category",
            page=1,
            page_size=10,
        )
        self.assertEqual(by_category["items"][0]["category"], "negative_delivery")

    def test_recommendations_storage_and_random_pick(self) -> None:
        inserted = self.repository.replace_all_recommendations(
            user_id=self.user_id,
            rows=[
                {"source_article": "A-1", "target_articles": ["B-1", "B-2", "B-1"]},
                {"source_article": "A-2", "target_articles": ["C-1"]},
            ],
        )
        self.assertEqual(inserted, 3)

        listed = self.repository.list_recommendations(user_id=self.user_id)
        self.assertEqual(len(listed), 2)
        first = next(item for item in listed if item["source_article"] == "A-1")
        self.assertEqual(first["target_articles"], ["B-1", "B-2"])

        picked = self.repository.get_random_recommendation(user_id=self.user_id, source_article="A-1")
        self.assertIn(picked, {"B-1", "B-2"})


if __name__ == "__main__":
    unittest.main()
