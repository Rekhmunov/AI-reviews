from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
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
    api_key: str | None = None
    timeout: int = 15

    def fetch_reviews(self) -> list[ReviewInput]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.api_url, method="GET", headers=headers)
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

    def sync_reviews(
        self,
        *,
        user_id: int,
        source: str,
        account_id: int | None,
        client: MarketplaceClient,
    ) -> int:
        reviews = client.fetch_reviews()
        settings = self.repository.get_ai_settings()
        for review in reviews:
            if not review.review_id:
                continue
            processed = self.processor.process(review)
            category = self._classify_category(review, processed, settings=settings)
            template = self.repository.get_template(user_id=user_id, category=category)
            mode, template_text = self._resolve_processing_mode(processed, template)

            if mode == "ignore":
                status = "ignored"
                auto_reply = None
            elif mode == "auto":
                status = "answered_auto"
                auto_reply = self._render_template(
                    template_text or self._build_auto_reply(
                        {
                            "sentiment_label": processed.sentiment_label,
                            "priority": processed.priority,
                            "is_spam": processed.is_spam,
                        }
                    ),
                    review=review,
                    category=category,
                    sentiment=processed.sentiment_label,
                )
            else:
                status = "queued_for_operator"
                auto_reply = None

            self.repository.upsert_processed_review(
                user_id=user_id,
                source=source,
                account_id=account_id,
                review=review,
                processed=processed,
                category=category,
                processing_mode=mode,
                status=status,
                auto_reply=auto_reply,
            )
        return len(reviews)

    def sync_all_accounts(self, *, user_id: int) -> dict[str, int]:
        loaded_total = 0
        accounts = [item for item in self.repository.list_marketplace_accounts(user_id) if item["is_active"]]
        for account in accounts:
            client = self._build_client(account)
            loaded_total += self.sync_reviews(
                user_id=user_id,
                source=str(account["marketplace"]),
                account_id=int(account["id"]),
                client=client,
            )
        return {"accounts": len(accounts), "loaded": loaded_total}

    @staticmethod
    def _build_client(account: dict[str, object]) -> MarketplaceClient:
        marketplace = str(account.get("marketplace") or "")
        if marketplace == "mock":
            return MockMarketplaceClient()
        return HTTPMarketplaceClient(
            api_url=str(account.get("api_url") or ""),
            api_key=str(account.get("api_key") or "") or None,
        )

    def list_reviews(
        self,
        *,
        user_id: int,
        priority: str | None = None,
        status: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, object]]:
        return self.repository.list_reviews(user_id=user_id, priority=priority, status=status, category=category)

    def queue_for_manual_processing(self, *, user_id: int, review_uid: str) -> bool:
        return self.repository.mark_manual_queue(user_id=user_id, review_uid=review_uid)

    def generate_auto_reply(self, *, user_id: int, review_uid: str) -> str:
        review = self.repository.get_review(user_id=user_id, review_uid=review_uid)
        if review is None:
            raise KeyError(f"Review {review_uid} not found")
        template = self.repository.get_template(user_id=user_id, category=str(review.get("category")))
        text = str(template["template_text"]) if template else self._build_auto_reply(review)
        reply = self._render_template(
            text,
            review=ReviewInput(
                review_id=str(review.get("external_review_id")),
                text=str(review.get("text")),
                author=str(review.get("author")) if review.get("author") else None,
                rating=int(review["rating"]) if review.get("rating") is not None else None,
            ),
            category=str(review.get("category")),
            sentiment=str(review.get("sentiment_label")),
        )
        updated = self.repository.mark_auto_replied(user_id=user_id, review_uid=review_uid, response_text=reply)
        if not updated:
            raise KeyError(f"Review {review_uid} not found")
        return reply

    def save_manual_reply(self, *, user_id: int, review_uid: str, operator_name: str, response_text: str) -> bool:
        return self.repository.mark_manual_replied(
            user_id=user_id,
            review_uid=review_uid,
            operator_name=operator_name,
            response_text=response_text,
        )

    def _classify_category(
        self,
        review: ReviewInput,
        processed: object,
        *,
        settings: dict[str, object],
    ) -> str:
        provider = str(settings.get("provider") or "rules")
        if provider == "yandex":
            classified = self._classify_with_yandex(review, settings=settings)
            if classified:
                return classified
        sentiment_label = str(getattr(processed, "sentiment_label", "neutral"))
        text = review.text.lower()
        delivery_words = ("доставка", "курьер", "пункт выдачи", "shipment", "delivery")
        product_words = ("товар", "качество", "брак", "слом", "упаковка", "size", "цвет")

        if sentiment_label == "negative":
            if any(word in text for word in delivery_words):
                return "negative_delivery"
            if any(word in text for word in product_words):
                return "negative_product"
            return "negative_other"

        if sentiment_label == "positive":
            if any(word in text for word in product_words):
                return "positive_product"
            return "positive_quality"

        return "neutral_other"

    @staticmethod
    def _normalize_category(text: str) -> str | None:
        categories = {
            "negative_delivery",
            "negative_product",
            "negative_other",
            "positive_quality",
            "positive_product",
            "neutral_other",
        }
        cleaned = text.strip().lower().replace(" ", "_").replace("-", "_")
        if cleaned in categories:
            return cleaned
        for category in categories:
            if category in cleaned:
                return category
        return None

    def _classify_with_yandex(self, review: ReviewInput, *, settings: dict[str, object]) -> str | None:
        api_key = str(settings.get("yandex_api_key") or "")
        folder_id = str(settings.get("yandex_folder_id") or "")
        model_uri = str(settings.get("yandex_model_uri") or "")
        if not api_key or not folder_id:
            return None
        if not model_uri:
            model_uri = f"gpt://{folder_id}/yandexgpt-lite/latest"

        prompt = (
            "Классифицируй отзыв строго одной категорией: "
            "negative_delivery, negative_product, negative_other, positive_quality, "
            "positive_product, neutral_other.\n"
            f"Отзыв: {review.text}\n"
            f"Оценка: {review.rating if review.rating is not None else 'unknown'}\n"
            "Ответ верни только названием категории."
        )

        body = {
            "modelUri": model_uri,
            "completionOptions": {"stream": False, "temperature": 0.0, "maxTokens": 30},
            "messages": [{"role": "user", "text": prompt}],
        }
        request = Request(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            method="POST",
            headers={
                "Authorization": f"Api-Key {api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(body).encode("utf-8"),
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError):
            return None

        text = ""
        result = payload.get("result")
        if isinstance(result, dict):
            alternatives = result.get("alternatives")
            if isinstance(alternatives, list) and alternatives:
                first = alternatives[0]
                if isinstance(first, dict):
                    message = first.get("message")
                    if isinstance(message, dict):
                        text = str(message.get("text") or "")
        return self._normalize_category(text)

    @staticmethod
    def _resolve_processing_mode(processed: object, template: dict[str, object] | None) -> tuple[str, str]:
        if template:
            mode = str(template.get("mode") or "manual")
            text = str(template.get("template_text") or "")
            if mode in {"auto", "manual", "ignore"}:
                return mode, text
        sentiment = str(getattr(processed, "sentiment_label", "neutral"))
        priority = str(getattr(processed, "priority", "low"))
        if sentiment == "negative" or priority == "high":
            return "manual", ""
        return "auto", ""

    @staticmethod
    def _render_template(template: str, *, review: ReviewInput, category: str, sentiment: str) -> str:
        text = template or "Спасибо за отзыв!"
        context = {
            "author": review.author or "клиент",
            "rating": review.rating if review.rating is not None else "без оценки",
            "category": category,
            "sentiment": sentiment,
            "review_id": review.review_id,
        }
        for key, value in context.items():
            text = text.replace(f"{{{key}}}", str(value))
        return text

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
