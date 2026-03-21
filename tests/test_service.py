import os
import tempfile
import unittest

from review_processor.models import ReviewInput
from review_processor.repository import ReviewRepository
from review_processor.service import ReviewAutomationService


class _StubClient:
    def fetch_reviews(self) -> list[ReviewInput]:
        return [
            ReviewInput(
                review_id="ext-1",
                text="Отличный сервис, все супер",
                author="Client A",
                rating=5,
            ),
            ReviewInput(
                review_id="ext-2",
                text="Ужасно, не работает оплата",
                author="Client B",
                rating=1,
            ),
        ]


class ReviewAutomationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = temp.name
        temp.close()
        self.addCleanup(lambda: os.path.exists(self.db_path) and os.unlink(self.db_path))
        self.repository = ReviewRepository(db_path=self.db_path)
        self.service = ReviewAutomationService(repository=self.repository)

    def test_sync_and_list_reviews(self) -> None:
        loaded = self.service.sync_reviews(source="test-market", client=_StubClient())
        self.assertEqual(loaded, 2)

        reviews = self.service.list_reviews()
        self.assertEqual(len(reviews), 2)
        review_ids = {row["review_id"] for row in reviews}
        self.assertEqual(review_ids, {"ext-1", "ext-2"})

    def test_queue_manual_and_manual_reply(self) -> None:
        self.service.sync_reviews(source="test-market", client=_StubClient())

        queued = self.service.queue_for_manual_processing("ext-2")
        self.assertTrue(queued)

        updated = self.service.save_manual_reply("ext-2", "operator-1", "Проблему решили, проверьте заказ.")
        self.assertTrue(updated)

        review = self.repository.get_review("ext-2")
        self.assertIsNotNone(review)
        self.assertEqual(review["status"], "answered_manual")
        self.assertEqual(review["operator_name"], "operator-1")

    def test_auto_reply_marks_review(self) -> None:
        self.service.sync_reviews(source="test-market", client=_StubClient())

        reply = self.service.generate_auto_reply("ext-1")
        self.assertIn("Спасибо", reply)

        review = self.repository.get_review("ext-1")
        self.assertIsNotNone(review)
        self.assertEqual(review["status"], "answered_auto")
        self.assertEqual(review["auto_reply"], reply)


if __name__ == "__main__":
    unittest.main()
