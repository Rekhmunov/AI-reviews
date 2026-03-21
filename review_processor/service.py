from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from urllib.request import Request, urlopen

from .models import ReviewInput
from .processor import ReviewProcessor
from .repository import ReviewRepository


class MarketplaceClient(Protocol):
    def fetch_reviews(self) -> list[ReviewInput]:
        """Load reviews from marketplace API."""


@dataclass(slots=True)
class HTTPMarketplaceClient:
    api_url: str
    timeout: int = 15

    def fetch_reviews(self) -> list[ReviewInput]:
        request = Request(self.api_url, method="GET")
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if not isinstance(payload, list):
            raise ValueError("Marketplace API response must be a JSON list")

        return [self._to_review(item) for item in payload]

    @staticmethod
    def _to_review(item: dict[str, object]) -> ReviewInput:
        return ReviewInput(
            review_id=str(item.get("review_id") or item.get("id") or ""),
            text=str(item.get("text") or ""),
            author=str(item["author"]) if item.get("author") is not None else None,
            rating=int(item["rating"]) if item.get("rating") is not None else None,
            metadata={k: v for k, v in item.items() if k not in {"review_id", "id", "text", "author", "rating"}},
        )


class MockMarketplaceClient:
    """Demo client for local startup without real marketplace credentials."""

    def fetch_reviews(self) -> list[ReviewInput]:
        return [
            ReviewInput(
                review_id="mp-1001",
                text="Отличный товар, доставка быстро пришла.",
                author="Покупатель 1",
                rating=5,
                metadata={"marketplace": "mock"},
            ),
            ReviewInput(
                review_id="mp-1002",
                text="Ужасно. Приложение вылетает при оформлении оплаты.",
                author="Покупатель 2",
                rating=1,
                metadata={"marketplace": "mock"},
            ),
            ReviewInput(
                review_id="mp-1003",
                text="Buy now https://spam.example.com",
                author="Bot",
                rating=5,
                metadata={"marketplace": "mock"},
            ),
        ]


class ReviewAutomationService:
    def __init__(self, repository: ReviewRepository, processor: ReviewProcessor | None = None) -> None:
        self.repository = repository
        self.processor = processor or ReviewProcessor()

    def sync_reviews(self, source: str, client: MarketplaceClient) -> int:
        reviews = client.fetch_reviews()
        for review in reviews:
            if not review.review_id:
                continue
            processed = self.processor.process(review)
            self.repository.upsert_processed_review(source, review, processed)
        return len(reviews)

    def list_reviews(self, priority: str | None = None, status: str | None = None) -> list[dict[str, object]]:
        return self.repository.list_reviews(priority=priority, status=status)

    def queue_for_manual_processing(self, review_id: str) -> bool:
        return self.repository.mark_manual_queue(review_id)

    def generate_auto_reply(self, review_id: str) -> str:
        review = self.repository.get_review(review_id)
        if review is None:
            raise KeyError(f"Review {review_id} not found")
        reply = self._build_auto_reply(review)
        updated = self.repository.mark_auto_replied(review_id, reply)
        if not updated:
            raise KeyError(f"Review {review_id} not found")
        return reply

    def save_manual_reply(self, review_id: str, operator_name: str, response_text: str) -> bool:
        return self.repository.mark_manual_replied(review_id, operator_name, response_text)

    @staticmethod
    def _build_auto_reply(review: dict[str, object]) -> str:
        sentiment = str(review.get("sentiment_label"))
        priority = str(review.get("priority"))
        is_spam = bool(review.get("is_spam"))

        if is_spam:
            return "Спасибо за отзыв. Комментарий отмечен системой модерации."
        if priority == "high" or sentiment == "negative":
            return (
                "Спасибо за обратную связь. Нам жаль, что вы столкнулись с проблемой. "
                "Мы уже передали отзыв в поддержку и вернемся с решением."
            )
        if sentiment == "positive":
            return "Спасибо за высокую оценку! Очень рады, что вам понравилось."
        return "Спасибо за отзыв! Мы учтем его в дальнейших улучшениях."
