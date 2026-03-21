from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
import time
from urllib.parse import urlencode, urljoin
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import ReviewInput
from .processor import ReviewProcessor
from .repository import ReviewRepository


class MarketplaceClient(Protocol):
    def fetch_reviews(self) -> list[ReviewInput]:
        """Load reviews from marketplace API."""


class MarketplaceSyncError(RuntimeError):
    def __init__(self, source: str, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.source = source
        self.details = details or {}


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
        payload = _request_json(request=request, timeout=self.timeout, source="http")

        if not isinstance(payload, list):
            raise MarketplaceSyncError("http", "Marketplace API response must be a JSON list")

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


@dataclass(slots=True)
class OzonMarketplaceClient:
    api_url: str
    client_id: str
    api_key: str
    list_path: str = "/v1/review/list"
    base_payload: dict[str, object] | None = None
    items_keys: tuple[str, ...] = ("reviews", "feedbacks", "items")
    cursor_keys: tuple[str, ...] = ("last_id", "lastId", "next_last_id", "cursor")
    page_size: int = 50
    max_pages: int = 20
    timeout: int = 20

    def fetch_reviews(self) -> list[ReviewInput]:
        if not self.client_id or not self.api_key:
            raise MarketplaceSyncError("ozon", "Missing Ozon credentials: client_id/api_key")

        last_id: str | None = None
        page = 0
        reviews: list[ReviewInput] = []

        while page < self.max_pages:
            payload: dict[str, object] = dict(self.base_payload or {})
            payload["limit"] = self.page_size
            if last_id:
                payload["last_id"] = last_id
            body = self._request_json(path=self.list_path, payload=payload)
            result = body.get("result") if isinstance(body.get("result"), dict) else body
            _raise_if_error_payload(result, source="ozon")

            page_items = _extract_sequence(result, keys=self.items_keys)
            if not page_items:
                break
            reviews.extend(self._to_review(item) for item in page_items)

            next_last_id = _extract_str(result, keys=self.cursor_keys)
            has_next = bool(result.get("has_next") or result.get("hasNext"))
            page += 1
            if not has_next and len(page_items) < self.page_size:
                break
            if not next_last_id or next_last_id == last_id:
                break
            last_id = next_last_id

        return [review for review in reviews if review.review_id]

    def _request_json(self, *, path: str, payload: dict[str, object]) -> dict[str, object]:
        url = _compose_url(self.api_url, path)
        request = Request(
            url,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Client-Id": self.client_id,
                "Api-Key": self.api_key,
            },
            data=json.dumps(payload).encode("utf-8"),
        )
        payload = _request_json(request=request, timeout=self.timeout, source="ozon")
        if not isinstance(payload, dict):
            raise MarketplaceSyncError("ozon", "Ozon API returned non-object payload")
        return payload

    @staticmethod
    def _to_review(item: dict[str, object]) -> ReviewInput:
        text = str(item.get("text") or item.get("comment") or item.get("content") or "")
        return ReviewInput(
            review_id=str(item.get("id") or item.get("review_id") or item.get("uuid") or ""),
            text=text,
            author=str(item.get("author") or item.get("user_name") or item.get("customer_name") or "")
            or None,
            rating=_to_int(item.get("rating") or item.get("score")),
            metadata={"raw": item, "marketplace": "ozon"},
        )


@dataclass(slots=True)
class WildberriesMarketplaceClient:
    api_url: str
    api_key: str
    list_path: str | None = None
    skip_param: str = "skip"
    take_param: str = "take"
    unanswered_param: str = "isAnswered"
    unanswered_value: str = "false"
    items_keys: tuple[str, ...] = ("feedbacks", "reviews", "items")
    page_size: int = 100
    max_pages: int = 20
    timeout: int = 20

    def fetch_reviews(self) -> list[ReviewInput]:
        if not self.api_key:
            raise MarketplaceSyncError("wb", "Missing Wildberries api_key")

        skip = 0
        page = 0
        reviews: list[ReviewInput] = []

        while page < self.max_pages:
            payload = self._request_json(skip=skip, take=self.page_size)
            _raise_if_error_payload(payload, source="wb")
            items = _extract_sequence(payload, keys=self.items_keys)
            if not items and isinstance(payload.get("data"), dict):
                _raise_if_error_payload(payload["data"], source="wb")
                items = _extract_sequence(payload["data"], keys=self.items_keys)
            if not items:
                break
            reviews.extend(self._to_review(item) for item in items)
            if len(items) < self.page_size:
                break
            skip += self.page_size
            page += 1

        return [review for review in reviews if review.review_id]

    def _request_json(self, *, skip: int, take: int) -> dict[str, object]:
        params = urlencode(
            {
                self.skip_param: skip,
                self.take_param: take,
                self.unanswered_param: self.unanswered_value,
            }
        )
        endpoint = _compose_url(self.api_url, self.list_path)
        url = f"{self.api_url}?{params}" if "?" not in self.api_url else f"{self.api_url}&{params}"
        if self.list_path:
            url = f"{endpoint}?{params}" if "?" not in endpoint else f"{endpoint}&{params}"
        request = Request(
            url,
            method="GET",
            headers={"Authorization": self.api_key},
        )
        payload = _request_json(request=request, timeout=self.timeout, source="wb")
        if not isinstance(payload, dict):
            raise MarketplaceSyncError("wb", "Wildberries API returned non-object payload")
        return payload

    @staticmethod
    def _to_review(item: dict[str, object]) -> ReviewInput:
        text = str(item.get("text") or item.get("pros") or item.get("cons") or "")
        return ReviewInput(
            review_id=str(item.get("id") or item.get("feedbackId") or item.get("review_id") or ""),
            text=text,
            author=str(item.get("userName") or item.get("author") or "") or None,
            rating=_to_int(item.get("productValuation") or item.get("rating")),
            metadata={"raw": item, "marketplace": "wb"},
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
        try:
            reviews = client.fetch_reviews()
        except MarketplaceSyncError as exc:
            self.repository.log_review_action(
                user_id=user_id,
                review_uid=None,
                action_type="sync_error",
                actor="system",
                details={"source": source, "account_id": account_id, "error": str(exc), **exc.details},
            )
            raise
        settings = self.repository.get_ai_settings(include_secrets=True)
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
            review_uid = self.repository.make_review_uid(user_id, source, account_id, review.review_id)
            self.repository.log_review_action(
                user_id=user_id,
                review_uid=review_uid,
                action_type="sync_review",
                actor="system",
                details={"category": category, "status": status, "source": source},
            )
        return len(reviews)

    def sync_all_accounts(self, *, user_id: int) -> dict[str, int]:
        loaded_total = 0
        successful_accounts = 0
        errors: list[dict[str, object]] = []
        accounts = [
            item
            for item in self.repository.list_marketplace_accounts(user_id, include_secrets=True)
            if item["is_active"]
        ]
        for account in accounts:
            account_id = int(account["id"])
            marketplace = str(account["marketplace"])
            try:
                client = self._build_client(account)
                loaded_total += self.sync_reviews(
                    user_id=user_id,
                    source=marketplace,
                    account_id=account_id,
                    client=client,
                )
                successful_accounts += 1
            except MarketplaceSyncError as exc:
                details = {"account_id": account_id, "marketplace": marketplace, "error": str(exc), **exc.details}
                errors.append(details)
            except Exception as exc:
                details = {"account_id": account_id, "marketplace": marketplace, "error": str(exc)}
                errors.append(details)
                self.repository.log_review_action(
                    user_id=user_id,
                    review_uid=None,
                    action_type="sync_error",
                    actor="system",
                    details=details,
                )
        return {
            "accounts": len(accounts),
            "success_accounts": successful_accounts,
            "failed_accounts": len(errors),
            "loaded": loaded_total,
            "errors": errors,
        }

    @staticmethod
    def _build_client(account: dict[str, object]) -> MarketplaceClient:
        marketplace = str(account.get("marketplace") or "")
        extra = account.get("extra") if isinstance(account.get("extra"), dict) else {}
        if marketplace == "mock":
            return MockMarketplaceClient()
        if marketplace == "ozon":
            client_id = str(extra.get("client_id") or "")
            api_key = str(account.get("api_key") or "")
            return OzonMarketplaceClient(
                api_url=str(account.get("api_url") or ""),
                client_id=client_id,
                api_key=api_key,
                list_path=str(extra.get("list_path") or "/v1/review/list"),
                base_payload=extra.get("base_payload") if isinstance(extra.get("base_payload"), dict) else None,
                page_size=_to_positive_int(extra.get("page_size"), default=50),
                max_pages=_to_positive_int(extra.get("max_pages"), default=20),
            )
        if marketplace == "wb":
            api_key = str(account.get("api_key") or "")
            return WildberriesMarketplaceClient(
                api_url=str(account.get("api_url") or ""),
                api_key=api_key,
                list_path=str(extra.get("list_path")) if extra.get("list_path") else None,
                skip_param=str(extra.get("skip_param") or "skip"),
                take_param=str(extra.get("take_param") or "take"),
                unanswered_param=str(extra.get("unanswered_param") or "isAnswered"),
                unanswered_value=str(extra.get("unanswered_value") or "false"),
                page_size=_to_positive_int(extra.get("page_size"), default=100),
                max_pages=_to_positive_int(extra.get("max_pages"), default=20),
            )
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
        updated = self.repository.mark_manual_queue(user_id=user_id, review_uid=review_uid)
        if updated:
            self.repository.log_review_action(
                user_id=user_id,
                review_uid=review_uid,
                action_type="queue_manual",
                actor="operator",
                details={},
            )
        return updated

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
        self.repository.log_review_action(
            user_id=user_id,
            review_uid=review_uid,
            action_type="auto_reply",
            actor="system",
            details={"reply": reply},
        )
        return reply

    def save_manual_reply(self, *, user_id: int, review_uid: str, operator_name: str, response_text: str) -> bool:
        updated = self.repository.mark_manual_replied(
            user_id=user_id,
            review_uid=review_uid,
            operator_name=operator_name,
            response_text=response_text,
        )
        if updated:
            self.repository.log_review_action(
                user_id=user_id,
                review_uid=review_uid,
                action_type="manual_reply",
                actor=operator_name,
                details={"reply": response_text},
            )
        return updated

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
            payload = _request_json(request=request, timeout=20, source="yandex", retries=1)
        except MarketplaceSyncError:
            return None

        text = ""
        result = payload.get("result") if isinstance(payload, Mapping) else None
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


def _extract_sequence(payload: object, *, keys: tuple[str, ...]) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _extract_str(payload: object, *, keys: tuple[str, ...]) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return None


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_positive_int(value: object, *, default: int) -> int:
    parsed = _to_int(value)
    if parsed is None or parsed <= 0:
        return default
    return parsed


def _compose_url(base_url: str, path: str | None) -> str:
    if not path:
        return base_url
    normalized_base = base_url.rstrip("/")
    normalized_path = "/" + path.strip("/")
    if normalized_base.endswith(normalized_path):
        return normalized_base
    return urljoin(normalized_base + "/", path.lstrip("/"))


def _raise_if_error_payload(payload: object, *, source: str) -> None:
    if not isinstance(payload, Mapping):
        return

    explicit_error = payload.get("error")
    if explicit_error:
        raise MarketplaceSyncError(source, f"{source} error: {explicit_error}")

    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        joined = "; ".join(str(item) for item in errors[:5])
        raise MarketplaceSyncError(source, f"{source} errors: {joined}")
    if isinstance(errors, Mapping) and errors:
        joined = "; ".join(f"{k}:{v}" for k, v in list(errors.items())[:5])
        raise MarketplaceSyncError(source, f"{source} errors: {joined}")

    status = payload.get("status")
    if isinstance(status, str) and status.lower() in {"error", "failed", "fail"}:
        message = str(payload.get("message") or payload.get("detail") or "unknown error")
        raise MarketplaceSyncError(source, f"{source} status error: {message}")

    if payload.get("errorText"):
        raise MarketplaceSyncError(source, f"{source} error: {payload.get('errorText')}")


def _request_json(*, request: Request, timeout: int, source: str, retries: int = 2) -> object:
    attempt = 0
    while True:
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            message = f"{source} HTTP error {exc.code}"
            try:
                body_text = exc.read().decode("utf-8")
                if body_text:
                    message = f"{message}: {body_text[:400]}"
            except Exception:
                pass
            raise MarketplaceSyncError(source, message) from exc
        except (URLError, TimeoutError, ValueError) as exc:
            if attempt >= retries:
                raise MarketplaceSyncError(source, f"{source} network/parse error: {exc}") from exc
            time.sleep(0.4 * (2**attempt))
            attempt += 1
