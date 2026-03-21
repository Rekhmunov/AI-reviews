from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
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
    def fetch_reviews(
        self,
        *,
        since_date: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[ReviewInput]:
        """Load reviews from marketplace API."""

    def fetch_conversations(
        self,
        *,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[dict[str, object]]:
        """Load questions/chats from marketplace API."""


class MarketplaceSyncError(RuntimeError):
    def __init__(self, source: str, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.source = source
        self.details = details or {}


def _raise_if_stop_requested(stop_requested: Callable[[], bool] | None, *, source: str) -> None:
    if stop_requested and stop_requested():
        raise MarketplaceSyncError(source, "Синхронизация остановлена администратором", details={"cancelled": True})


@dataclass(slots=True)
class HTTPMarketplaceClient:
    api_url: str
    api_key: str | None = None
    timeout: int = 15

    def fetch_reviews(
        self,
        *,
        since_date: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[ReviewInput]:
        _raise_if_stop_requested(stop_requested, source="http")
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.api_url, method="GET", headers=headers)
        payload = _request_json(request=request, timeout=self.timeout, source="http")

        if not isinstance(payload, list):
            raise MarketplaceSyncError("http", "Marketplace API response must be a JSON list")

        return [self._to_review(item) for item in payload]

    def fetch_conversations(self, *, stop_requested: Callable[[], bool] | None = None) -> list[dict[str, object]]:
        _raise_if_stop_requested(stop_requested, source="http")
        return []

    @staticmethod
    def _to_review(item: dict[str, object]) -> ReviewInput:
        review_tags = _extract_review_tags_from_payload(item)
        return ReviewInput(
            review_id=str(item.get("review_id") or item.get("id") or ""),
            text=str(item.get("text") or ""),
            author=str(item["author"]) if item.get("author") is not None else None,
            rating=int(item["rating"]) if item.get("rating") is not None else None,
            metadata={
                **{k: v for k, v in item.items() if k not in {"review_id", "id", "text", "author", "rating"}},
                "review_tags": review_tags,
            },
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
    questions_path: str | None = None
    chats_path: str | None = None
    reply_path: str | None = "/v1/review/comment/create"
    reply_review_id_field: str = "review_id"
    reply_text_field: str = "text"
    reply_payload: dict[str, object] | None = None
    page_size: int = 50
    max_pages: int = 20
    timeout: int = 20

    def fetch_reviews(
        self,
        *,
        since_date: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[ReviewInput]:
        if not self.client_id or not self.api_key:
            raise MarketplaceSyncError("ozon", "Missing Ozon credentials: client_id/api_key")

        last_id: str | None = None
        page = 0
        reviews: list[ReviewInput] = []

        while page < self.max_pages:
            _raise_if_stop_requested(stop_requested, source="ozon")
            payload: dict[str, object] = dict(self.base_payload or {})
            payload["limit"] = self.page_size
            if since_date:
                payload.setdefault("date_from", since_date)
                payload.setdefault("dateFrom", since_date)
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

    def fetch_conversations(self, *, stop_requested: Callable[[], bool] | None = None) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        items.extend(
            self._fetch_conversation_stream(path=self.questions_path, kind="question", stop_requested=stop_requested)
        )
        items.extend(self._fetch_conversation_stream(path=self.chats_path, kind="chat", stop_requested=stop_requested))
        return items

    def _fetch_conversation_stream(
        self,
        *,
        path: str | None,
        kind: str,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[dict[str, object]]:
        if not path:
            return []

        cursor: str | None = None
        page = 0
        result_items: list[dict[str, object]] = []
        while page < self.max_pages:
            _raise_if_stop_requested(stop_requested, source="ozon")
            payload: dict[str, object] = {"limit": self.page_size}
            if cursor:
                payload["last_id"] = cursor
            body = self._request_json(path=path, payload=payload)
            raw = body.get("result") if isinstance(body.get("result"), dict) else body
            _raise_if_error_payload(raw, source="ozon")
            page_items = _extract_sequence(raw, keys=self.items_keys + ("questions", "chats", "dialogs", "messages"))
            if not page_items:
                break
            for item in page_items:
                mapped = self._to_conversation(item, kind=kind)
                if mapped:
                    result_items.append(mapped)
            next_cursor = _extract_str(raw, keys=self.cursor_keys)
            has_next = bool(raw.get("has_next") or raw.get("hasNext"))
            if not has_next and len(page_items) < self.page_size:
                break
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
            page += 1
        return result_items

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

    def send_review_reply(self, *, review: ReviewInput, response_text: str) -> bool:
        if not self.client_id or not self.api_key:
            raise MarketplaceSyncError("ozon", "Missing Ozon credentials: client_id/api_key")
        if not self.reply_path:
            return False
        payload: dict[str, object] = dict(self.reply_payload or {})
        payload[self.reply_review_id_field] = review.review_id
        payload[self.reply_text_field] = response_text
        result = self._request_json(path=self.reply_path, payload=payload)
        raw = result.get("result") if isinstance(result.get("result"), Mapping) else result
        _raise_if_error_payload(raw, source="ozon")
        return True

    @staticmethod
    def _to_review(item: dict[str, object]) -> ReviewInput:
        text = str(item.get("text") or item.get("comment") or item.get("content") or "")
        review_tags = _extract_review_tags_from_payload(item)
        return ReviewInput(
            review_id=str(item.get("id") or item.get("review_id") or item.get("uuid") or ""),
            text=text,
            author=str(item.get("author") or item.get("user_name") or item.get("customer_name") or "")
            or None,
            rating=_to_int(item.get("rating") or item.get("score")),
            metadata={"raw": item, "marketplace": "ozon", "review_tags": review_tags},
        )

    @staticmethod
    def _to_conversation(item: dict[str, object], *, kind: str) -> dict[str, object] | None:
        external_id = str(item.get("id") or item.get("chat_id") or item.get("question_id") or "").strip()
        if not external_id:
            return None
        text = str(item.get("text") or item.get("question") or item.get("message") or item.get("content") or "")
        customer_name = str(item.get("author") or item.get("user_name") or item.get("customer_name") or "") or None
        status = str(item.get("status") or "open").lower()
        unread_count = _to_positive_int(item.get("unread_count") or item.get("unread"), default=0)
        updated_at = str(item.get("updated_at") or item.get("last_message_at") or "")
        return {
            "external_id": external_id,
            "kind": kind,
            "customer_name": customer_name,
            "message_text": text,
            "status": status if status in {"open", "closed", "waiting"} else "open",
            "unread_count": unread_count,
            "last_message_at": updated_at or None,
            "metadata": {"raw": item, "marketplace": "ozon"},
        }


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
    questions_path: str | None = None
    chats_path: str | None = None
    reply_path: str | None = "/api/v1/feedbacks/answer"
    reply_method: str = "POST"
    reply_review_id_field: str = "id"
    reply_text_field: str = "text"
    reply_payload: dict[str, object] | None = None
    page_size: int = 100
    max_pages: int = 20
    timeout: int = 20

    def fetch_reviews(
        self,
        *,
        since_date: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[ReviewInput]:
        if not self.api_key:
            raise MarketplaceSyncError("wb", "Missing Wildberries api_key")

        skip = 0
        page = 0
        reviews: list[ReviewInput] = []

        while page < self.max_pages:
            _raise_if_stop_requested(stop_requested, source="wb")
            try:
                payload = self._request_json(skip=skip, take=self.page_size, since_date=since_date)
            except TypeError:
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

    def fetch_conversations(self, *, stop_requested: Callable[[], bool] | None = None) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        if self.questions_path:
            items.extend(
                self._fetch_conversation_endpoint(path=self.questions_path, kind="question", stop_requested=stop_requested)
            )
        if self.chats_path:
            items.extend(self._fetch_conversation_endpoint(path=self.chats_path, kind="chat", stop_requested=stop_requested))
        return items

    def _fetch_conversation_endpoint(
        self,
        *,
        path: str,
        kind: str,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[dict[str, object]]:
        _raise_if_stop_requested(stop_requested, source="wb")
        endpoint = _compose_url(self.api_url, path)
        request = Request(endpoint, method="GET", headers={"Authorization": self.api_key})
        payload = _request_json(request=request, timeout=self.timeout, source="wb")
        if not isinstance(payload, dict):
            raise MarketplaceSyncError("wb", "Wildberries API returned non-object payload for conversations")
        _raise_if_error_payload(payload, source="wb")
        rows = _extract_sequence(payload, keys=self.items_keys + ("questions", "chats", "dialogs", "messages"))
        if not rows and isinstance(payload.get("data"), Mapping):
            rows = _extract_sequence(
                payload.get("data"),
                keys=self.items_keys + ("questions", "chats", "dialogs", "messages"),
            )
        result: list[dict[str, object]] = []
        for item in rows:
            mapped = self._to_conversation(item, kind=kind)
            if mapped:
                result.append(mapped)
        return result

    def _request_json(self, *, skip: int, take: int, since_date: str | None = None) -> dict[str, object]:
        params_payload: dict[str, object] = {
            self.skip_param: skip,
            self.take_param: take,
            self.unanswered_param: self.unanswered_value,
        }
        if since_date:
            params_payload["dateFrom"] = since_date
            params_payload["date_from"] = since_date
        params = urlencode(params_payload)
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

    def send_review_reply(self, *, review: ReviewInput, response_text: str) -> bool:
        if not self.api_key:
            raise MarketplaceSyncError("wb", "Missing Wildberries api_key")
        if not self.reply_path:
            return False
        payload: dict[str, object] = dict(self.reply_payload or {})
        payload[self.reply_review_id_field] = review.review_id
        payload[self.reply_text_field] = response_text
        method = self.reply_method.strip().upper() if self.reply_method else "POST"
        endpoint = _compose_url(self.api_url, self.reply_path)
        if method == "GET":
            query = urlencode(payload)
            url = f"{endpoint}?{query}" if "?" not in endpoint else f"{endpoint}&{query}"
            request = Request(url, method="GET", headers={"Authorization": self.api_key})
        else:
            request = Request(
                endpoint,
                method="POST",
                headers={"Authorization": self.api_key, "Content-Type": "application/json"},
                data=json.dumps(payload).encode("utf-8"),
            )
        raw = _request_json(request=request, timeout=self.timeout, source="wb", retries=1)
        _raise_if_error_payload(raw, source="wb")
        return True

    @staticmethod
    def _to_review(item: dict[str, object]) -> ReviewInput:
        text = str(item.get("text") or item.get("pros") or item.get("cons") or "")
        review_tags = _extract_review_tags_from_payload(item)
        return ReviewInput(
            review_id=str(item.get("id") or item.get("feedbackId") or item.get("review_id") or ""),
            text=text,
            author=str(item.get("userName") or item.get("author") or "") or None,
            rating=_to_int(item.get("productValuation") or item.get("rating")),
            metadata={"raw": item, "marketplace": "wb", "review_tags": review_tags},
        )

    @staticmethod
    def _to_conversation(item: dict[str, object], *, kind: str) -> dict[str, object] | None:
        external_id = str(item.get("id") or item.get("chatId") or item.get("questionId") or "").strip()
        if not external_id:
            return None
        text = str(item.get("text") or item.get("message") or item.get("question") or "")
        customer_name = str(item.get("userName") or item.get("author") or "") or None
        status = str(item.get("status") or "open").lower()
        return {
            "external_id": external_id,
            "kind": kind,
            "customer_name": customer_name,
            "message_text": text,
            "status": status if status in {"open", "closed", "waiting"} else "open",
            "unread_count": _to_positive_int(item.get("unread_count"), default=0),
            "last_message_at": str(item.get("updatedAt") or item.get("last_message_at") or "") or None,
            "metadata": {"raw": item, "marketplace": "wb"},
        }


class MockMarketplaceClient:
    """Demo client for local startup without real marketplace credentials."""

    def fetch_reviews(
        self,
        *,
        since_date: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[ReviewInput]:
        _raise_if_stop_requested(stop_requested, source="mock")
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

    def fetch_conversations(self, *, stop_requested: Callable[[], bool] | None = None) -> list[dict[str, object]]:
        _raise_if_stop_requested(stop_requested, source="mock")
        return [
            {
                "external_id": "mock-q-1",
                "kind": "question",
                "customer_name": "Покупатель 10",
                "message_text": "Подскажите, ткань не садится после стирки?",
                "status": "open",
                "unread_count": 1,
                "last_message_at": None,
                "metadata": {"marketplace": "mock"},
            },
            {
                "external_id": "mock-c-1",
                "kind": "chat",
                "customer_name": "Покупатель 11",
                "message_text": "Здравствуйте, можете уточнить срок доставки?",
                "status": "waiting",
                "unread_count": 2,
                "last_message_at": None,
                "metadata": {"marketplace": "mock"},
            },
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
        since_date: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> int:
        try:
            try:
                reviews = client.fetch_reviews(since_date=since_date, stop_requested=stop_requested)
            except TypeError:
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
            _raise_if_stop_requested(stop_requested, source=source)
            if not review.review_id:
                continue
            processed = self.processor.process(review)
            category = self._classify_category(review, processed, settings=settings)
            template = self.repository.get_template(user_id=user_id, category=category)
            group_id = self._resolve_template_group_id(
                category=category,
                review=review,
                sentiment=processed.sentiment_label,
            )
            rule = self.repository.get_processing_rule(user_id=user_id, group_id=group_id) if group_id else None
            mode, auto_send, template_text = self._resolve_processing_mode(processed, template, rule)

            if mode == "ignore":
                status = "ignored" if auto_send else "queued_for_operator"
                auto_reply = None
            elif mode in {"auto", "ai"} and auto_send:
                group_template = self._pick_group_template_text(
                    user_id=user_id,
                    category=category,
                    review=review,
                    sentiment=processed.sentiment_label,
                )
                auto_reply = self._render_template(
                    group_template
                    or template_text
                    or self._build_auto_reply(
                        {
                            "sentiment_label": processed.sentiment_label,
                            "priority": processed.priority,
                            "is_spam": processed.is_spam,
                        }
                    ),
                    user_id=user_id,
                    review=review,
                    category=category,
                    sentiment=processed.sentiment_label,
                    default_brand_name=str(settings.get("brand_name") or "VarFabric"),
                )
                sent, send_error = self._send_reply_via_client(
                    client=client,
                    source=source,
                    review=review,
                    response_text=auto_reply,
                )
                if sent:
                    status = "answered_auto"
                else:
                    status = "queued_for_operator"
                    auto_reply = None
                    self.repository.log_review_action(
                        user_id=user_id,
                        review_uid=self.repository.make_review_uid(user_id, source, account_id, review.review_id),
                        action_type="send_reply_error",
                        actor="system",
                        details={"source": source, "error": send_error or "Не удалось отправить ответ"},
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
                details={
                    "category": category,
                    "group_id": group_id,
                    "status": status,
                    "action_mode": mode,
                    "auto_send": auto_send,
                    "source": source,
                },
            )
        return len(reviews)

    def sync_conversations(
        self,
        *,
        user_id: int,
        source: str,
        account_id: int | None,
        client: MarketplaceClient,
        stop_requested: Callable[[], bool] | None = None,
    ) -> int:
        fetch_conversations = getattr(client, "fetch_conversations", None)
        if not callable(fetch_conversations):
            return 0

        try:
            try:
                rows = fetch_conversations(stop_requested=stop_requested)
            except TypeError:
                rows = fetch_conversations()
        except MarketplaceSyncError as exc:
            self.repository.log_review_action(
                user_id=user_id,
                review_uid=None,
                action_type="sync_error",
                actor="system",
                details={"source": source, "account_id": account_id, "error": str(exc), "scope": "conversations"},
            )
            raise

        loaded = 0
        for row in rows:
            _raise_if_stop_requested(stop_requested, source=source)
            external_id = str(row.get("external_id") or "").strip()
            if not external_id:
                continue
            conversation_uid = self.repository.upsert_conversation(
                user_id=user_id,
                source=source,
                account_id=account_id,
                external_conversation_id=external_id,
                kind=str(row.get("kind") or "chat"),
                customer_name=str(row.get("customer_name") or "") or None,
                message_text=str(row.get("message_text") or ""),
                status=str(row.get("status") or "open"),
                unread_count=_to_positive_int(row.get("unread_count"), default=0),
                metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
                last_message_at=str(row.get("last_message_at") or "") or None,
            )
            self.repository.log_review_action(
                user_id=user_id,
                review_uid=conversation_uid,
                action_type="sync_conversation",
                actor="system",
                details={"source": source, "kind": row.get("kind")},
            )
            loaded += 1
        return loaded

    def sync_all_accounts(
        self,
        *,
        user_id: int,
        stop_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        loaded_total = 0
        loaded_conversations = 0
        successful_accounts = 0
        errors: list[dict[str, object]] = []
        was_cancelled = False
        accounts = [
            item
            for item in self.repository.list_marketplace_accounts(user_id, include_secrets=True)
            if item["is_active"]
        ]
        sync_settings = self.repository.get_ai_settings(include_secrets=False)
        use_sync_start_date = bool(sync_settings.get("use_sync_start_date"))
        since_date = str(sync_settings.get("sync_start_date") or "").strip() if use_sync_start_date else ""
        since_value = since_date or None
        for account in accounts:
            if stop_requested and stop_requested():
                was_cancelled = True
                break
            account_id = int(account["id"])
            marketplace = str(account["marketplace"])
            try:
                client = self._build_client(account)
                loaded_total += self.sync_reviews(
                    user_id=user_id,
                    source=marketplace,
                    account_id=account_id,
                    client=client,
                    since_date=since_value,
                    stop_requested=stop_requested,
                )
                loaded_conversations += self.sync_conversations(
                    user_id=user_id,
                    source=marketplace,
                    account_id=account_id,
                    client=client,
                    stop_requested=stop_requested,
                )
                successful_accounts += 1
            except MarketplaceSyncError as exc:
                if bool(exc.details.get("cancelled")):
                    was_cancelled = True
                    break
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
            "loaded_conversations": loaded_conversations,
            "errors": errors,
            "cancelled": was_cancelled,
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
                questions_path=str(extra.get("questions_path")) if extra.get("questions_path") else None,
                chats_path=str(extra.get("chats_path")) if extra.get("chats_path") else None,
                reply_path=str(extra.get("reply_path") or "/v1/review/comment/create"),
                reply_review_id_field=str(extra.get("reply_review_id_field") or "review_id"),
                reply_text_field=str(extra.get("reply_text_field") or "text"),
                reply_payload=extra.get("reply_payload") if isinstance(extra.get("reply_payload"), dict) else None,
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
                questions_path=str(extra.get("questions_path")) if extra.get("questions_path") else None,
                chats_path=str(extra.get("chats_path")) if extra.get("chats_path") else None,
                reply_path=str(extra.get("reply_path") or "/api/v1/feedbacks/answer"),
                reply_method=str(extra.get("reply_method") or "POST"),
                reply_review_id_field=str(extra.get("reply_review_id_field") or "id"),
                reply_text_field=str(extra.get("reply_text_field") or "text"),
                reply_payload=extra.get("reply_payload") if isinstance(extra.get("reply_payload"), dict) else None,
            )
        return HTTPMarketplaceClient(
            api_url=str(account.get("api_url") or ""),
            api_key=str(account.get("api_key") or "") or None,
        )

    def list_reviews(
        self,
        *,
        user_id: int,
        source: str | None = None,
        priority: str | None = None,
        status: str | None = None,
        statuses: list[str] | None = None,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sort: str = "newest",
    ) -> list[dict[str, object]]:
        return self.repository.list_reviews(
            user_id=user_id,
            source=source,
            priority=priority,
            status=status,
            statuses=statuses,
            category=category,
            date_from=date_from,
            date_to=date_to,
            sort=sort,
        )

    def list_reviews_paginated(
        self,
        *,
        user_id: int,
        source: str | None = None,
        priority: str | None = None,
        status: str | None = None,
        statuses: list[str] | None = None,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sort: str = "newest",
        page: int = 1,
        page_size: int = 30,
        bucket: str = "all",
    ) -> dict[str, object]:
        return self.repository.list_reviews_paginated(
            user_id=user_id,
            source=source,
            priority=priority,
            status=status,
            statuses=statuses,
            category=category,
            date_from=date_from,
            date_to=date_to,
            sort=sort,
            page=page,
            page_size=page_size,
            bucket=bucket,
        )

    def list_review_sources(self, *, user_id: int) -> list[str]:
        return self.repository.list_review_sources(user_id=user_id)

    def apply_processing_rules_to_unprocessed(self, *, user_id: int) -> dict[str, int]:
        rows = self.repository.list_unprocessed_reviews(user_id=user_id)
        settings = self.repository.get_ai_settings(include_secrets=False)
        default_brand_name = str(settings.get("brand_name") or "VarFabric")
        updated = 0
        auto_sent = 0
        queued = 0
        ignored = 0
        for row in rows:
            review_uid = str(row.get("review_uid") or "")
            if not review_uid:
                continue
            category = str(row.get("category") or "")
            sentiment = str(row.get("sentiment_label") or "")
            review = ReviewInput(
                review_id=str(row.get("external_review_id") or ""),
                text=str(row.get("text") or ""),
                author=str(row.get("author")) if row.get("author") else None,
                rating=int(row["rating"]) if row.get("rating") is not None else None,
                metadata=dict(row.get("metadata") or {}) if isinstance(row.get("metadata"), dict) else {},
            )
            group_id = self._resolve_template_group_id(
                category=category,
                review=review,
                sentiment=sentiment,
            )
            rule = self.repository.get_processing_rule(user_id=user_id, group_id=group_id) if group_id else None
            mode = str(rule.get("action_mode") or "manual") if rule else "manual"
            auto_send = bool(rule.get("auto_send")) if rule else False

            if mode == "ignore":
                if not auto_send:
                    if self.repository.update_review_processing_result(
                        user_id=user_id,
                        review_uid=review_uid,
                        status="queued_for_operator",
                        auto_reply=None,
                    ):
                        queued += 1
                        updated += 1
                    continue
                if self.repository.update_review_processing_result(
                    user_id=user_id,
                    review_uid=review_uid,
                    status="ignored",
                    auto_reply=None,
                ):
                    ignored += 1
                    updated += 1
                continue

            if mode in {"auto", "template", "ai"} and auto_send:
                group_template = self._pick_group_template_text(
                    user_id=user_id,
                    category=category,
                    review=review,
                    sentiment=sentiment,
                )
                fallback = self._build_auto_reply(
                    {
                        "sentiment_label": sentiment,
                        "priority": str(row.get("priority") or ""),
                        "is_spam": bool(row.get("is_spam")),
                    }
                )
                reply = self._render_template(
                    group_template or fallback,
                    user_id=user_id,
                    review=review,
                    category=category,
                    sentiment=sentiment,
                    default_brand_name=default_brand_name,
                )
                sent = self._send_reply_for_saved_review(
                    user_id=user_id,
                    source=str(row.get("source") or ""),
                    account_id=int(row["account_id"]) if row.get("account_id") is not None else None,
                    review=review,
                    response_text=reply,
                    review_uid=review_uid,
                )
                if not sent:
                    if self.repository.update_review_processing_result(
                        user_id=user_id,
                        review_uid=review_uid,
                        status="queued_for_operator",
                        auto_reply=None,
                    ):
                        queued += 1
                        updated += 1
                    continue
                if self.repository.update_review_processing_result(
                    user_id=user_id,
                    review_uid=review_uid,
                    status="answered_auto",
                    auto_reply=reply,
                ):
                    auto_sent += 1
                    updated += 1
                continue

            if self.repository.update_review_processing_result(
                user_id=user_id,
                review_uid=review_uid,
                status="queued_for_operator",
                auto_reply=None,
            ):
                queued += 1
                updated += 1

        return {
            "updated": updated,
            "auto_sent": auto_sent,
            "queued": queued,
            "ignored": ignored,
        }

    def _send_reply_via_client(
        self,
        *,
        client: object,
        source: str,
        review: ReviewInput,
        response_text: str,
    ) -> tuple[bool, str | None]:
        sender = getattr(client, "send_review_reply", None)
        if not callable(sender):
            # Backward compatibility for test/dummy clients without reply API.
            return True, None
        try:
            try:
                sent = sender(review=review, response_text=response_text)
            except TypeError:
                sent = sender(review, response_text)
        except MarketplaceSyncError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, str(exc)
        if sent is False:
            return False, f"{source}: маркетплейс не подтвердил отправку ответа"
        return True, None

    def _send_reply_for_saved_review(
        self,
        *,
        user_id: int,
        source: str,
        account_id: int | None,
        review: ReviewInput,
        response_text: str,
        review_uid: str,
    ) -> bool:
        if source not in {"wb", "ozon"}:
            return True
        if account_id is None:
            return False
        account = self.repository.get_marketplace_account(
            user_id=user_id,
            account_id=account_id,
            include_secrets=True,
        )
        if account is None:
            return False
        client = self._build_client(account)
        sent, error = self._send_reply_via_client(
            client=client,
            source=source,
            review=review,
            response_text=response_text,
        )
        if sent:
            return True
        self.repository.log_review_action(
            user_id=user_id,
            review_uid=review_uid,
            action_type="send_reply_error",
            actor="system",
            details={"source": source, "account_id": account_id, "error": error or "Не удалось отправить ответ"},
        )
        return False

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
            raise KeyError("Отзыв не найден")
        template = self.repository.get_template(user_id=user_id, category=str(review.get("category")))
        group_template = self._pick_group_template_text(
            user_id=user_id,
            category=str(review.get("category") or ""),
            review=ReviewInput(
                review_id=str(review.get("external_review_id")),
                text=str(review.get("text")),
                author=str(review.get("author")) if review.get("author") else None,
                rating=int(review["rating"]) if review.get("rating") is not None else None,
                metadata=dict(review.get("metadata") or {}) if isinstance(review.get("metadata"), dict) else {},
            ),
            sentiment=str(review.get("sentiment_label") or ""),
        )
        text = group_template or (str(template["template_text"]) if template else self._build_auto_reply(review))
        settings = self.repository.get_ai_settings(include_secrets=False)
        reply = self._render_template(
            text,
            review=ReviewInput(
                review_id=str(review.get("external_review_id")),
                text=str(review.get("text")),
                author=str(review.get("author")) if review.get("author") else None,
                rating=int(review["rating"]) if review.get("rating") is not None else None,
                metadata=dict(review.get("metadata") or {}) if isinstance(review.get("metadata"), dict) else {},
            ),
            user_id=user_id,
            category=str(review.get("category")),
            sentiment=str(review.get("sentiment_label")),
            default_brand_name=str(settings.get("brand_name") or "VarFabric"),
        )
        sent = self._send_reply_for_saved_review(
            user_id=user_id,
            source=str(review.get("source") or ""),
            account_id=int(review["account_id"]) if review.get("account_id") is not None else None,
            review=ReviewInput(
                review_id=str(review.get("external_review_id")),
                text=str(review.get("text")),
                author=str(review.get("author")) if review.get("author") else None,
                rating=int(review["rating"]) if review.get("rating") is not None else None,
                metadata=dict(review.get("metadata") or {}) if isinstance(review.get("metadata"), dict) else {},
            ),
            response_text=reply,
            review_uid=review_uid,
        )
        if not sent:
            raise MarketplaceSyncError("marketplace", "Не удалось отправить ответ на маркетплейс по API")
        updated = self.repository.mark_auto_replied(user_id=user_id, review_uid=review_uid, response_text=reply)
        if not updated:
            raise KeyError("Отзыв не найден")
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

    def _pick_group_template_text(
        self,
        *,
        user_id: int,
        category: str,
        review: ReviewInput,
        sentiment: str,
    ) -> str | None:
        group_id = self._resolve_template_group_id(category=category, review=review, sentiment=sentiment)
        if not group_id:
            return None
        subgroup = self._resolve_template_subgroup(group_id=group_id, category=category, review=review)
        row = self.repository.get_random_template_variant(
            user_id=user_id,
            group_id=group_id,
            subgroup=subgroup,
        )
        if row is None and subgroup:
            row = self.repository.get_random_template_variant(user_id=user_id, group_id=group_id)
        if row is None:
            return None
        text = str(row.get("template_text") or "").strip()
        return text or None

    @staticmethod
    def _resolve_template_subgroup(*, group_id: str, category: str, review: ReviewInput) -> str | None:
        text = (review.text or "").lower()
        if group_id == "positive":
            if any(word in text for word in ("доставк", "курьер", "пвз", "пункт выдачи")):
                return "Позитив доставка"
            if any(word in text for word in ("запах", "аромат")):
                return "Позитив запах"
            if any(word in text for word in ("конструкц", "форма", "сборк")):
                return "Позитив конструкция"
            if any(word in text for word in ("упаковк", "коробк")):
                return "Позитив упаковка"
            if any(word in text for word in ("цвет", "оттенок")):
                return "Позитив цвет"
            if any(word in text for word in ("материал", "ткан", "состав")):
                return "Материал"
            if any(word in text for word in ("вкус", "вкусн")):
                return "Вкус"
            if any(word in text for word in ("эффект", "результат")):
                return "Эффект"
            return "Общий позитив"
        if group_id == "delivery_problems":
            if any(word in text for word in ("долго", "задерж", "опозд")):
                return "Долгая доставка"
            if any(word in text for word in ("испорчен", "мята", "порван", "поврежден", "сломан", "грязн")):
                return "Недостающая упаковка / грязное / поврежденное и сломанное"
            if any(word in text for word in ("наклейк", "этикетк")):
                return "Наклейка"
            if any(word in text for word in ("не тот", "перепут", "другой товар")):
                return "Не тот товар"
            if any(word in text for word in ("некомплект", "не хватает", "нет в комплекте")):
                return "Некомплект"
            if any(word in text for word in ("упаковк", "коробк")):
                return "Испорченная упаковка"
            return "Общие доставка"
        if group_id == "wrong_size":
            if any(word in text for word in ("большемер", "маломер", "мерит")):
                return "Большемерит/маломерит"
            if any(word in text for word in ("замер", "измер")):
                return "Альтернативные измерения"
            return "Не подошел размер"
        if group_id == "textless_ratings":
            rating = review.rating if review.rating is not None else 0
            if rating <= 3:
                return "1-3 звезды"
            if rating == 4:
                return "4 звезды"
            return "5 звезд"
        if group_id == "tagged_reviews":
            return "Общие теги"
        if group_id == "product_dissatisfaction":
            if any(word in text for word in ("подделк", "фейк")):
                return "Подделка"
            if any(word in text for word in ("срок", "годност")):
                return "Срок годности"
            if any(word in text for word in ("запах", "аромат")):
                return "Негатив запах"
            if any(word in text for word in ("конструкц", "сборк", "сломал")):
                return "Негатив конструкция"
            if any(word in text for word in ("цвет", "оттенок")):
                return "Негатив цвет"
            if any(word in text for word in ("брак", "б/у", "бу ")):
                return "Брак и Б/У"
            if any(word in text for word in ("цена", "дорог")):
                return "Высокая цена"
            if any(word in text for word in ("текстур", "консистенц", "материал")):
                return "Текстура, консистенция, материал"
            if any(word in text for word in ("качество", "некачествен")):
                return "Качество"
            if any(word in text for word in ("эффект", "результат")):
                return "Не устраивает эффект"
            if any(word in text for word in ("не подош", "не мое", "лично мне")):
                return "Не подошел лично мне"
            return "Общий негатив"
        return None

    @staticmethod
    def _resolve_template_group_id(*, category: str, review: ReviewInput, sentiment: str) -> str | None:
        normalized = category.strip().lower()
        text = (review.text or "").strip().lower()
        tags = ReviewAutomationService._extract_review_tags(review)
        has_text = bool(text)
        has_tags = bool(tags)

        if not has_text:
            if has_tags:
                return "tagged_reviews"
            return "textless_ratings"

        size_words = ("размер", "маломер", "большемер", "size", "мерит")
        delivery_words = ("доставк", "курьер", "пункт выдачи", "пвз")
        product_words = ("товар", "качество", "брак", "слом", "упаковк", "цвет", "белье", "пододеяльник")

        if normalized in {"positive_quality", "positive_product"}:
            if any(word in text for word in size_words):
                return "wrong_size"
            return "positive"
        if normalized == "negative_delivery":
            return "delivery_problems"
        if normalized in {"neutral_other"}:
            if any(word in text for word in size_words):
                return "wrong_size"
            if any(word in text for word in delivery_words):
                return "delivery_problems"
            if any(word in text for word in product_words):
                return "product_dissatisfaction"
            if sentiment.strip().lower() == "positive":
                return "positive"
            return "product_dissatisfaction"
        if normalized in {"negative_product", "negative_other"}:
            if any(word in text for word in size_words):
                return "wrong_size"
            if any(word in text for word in delivery_words):
                return "delivery_problems"
            return "product_dissatisfaction"
        if sentiment.strip().lower() == "positive":
            if any(word in text for word in size_words):
                return "wrong_size"
            return "positive"
        return None

    @staticmethod
    def _extract_review_tags(review: ReviewInput) -> list[str]:
        metadata = review.metadata if isinstance(review.metadata, dict) else {}
        raw_tags = metadata.get("review_tags")
        result: list[str] = []
        seen: set[str] = set()

        def _push(value: object) -> None:
            text = str(value or "").strip()
            if not text:
                return
            normalized = text.lower()
            if normalized in seen:
                return
            seen.add(normalized)
            result.append(text)

        if isinstance(raw_tags, list):
            for item in raw_tags:
                _push(item)
        elif isinstance(raw_tags, str):
            for part in re.split(r"[,\n;/|]+", raw_tags):
                _push(part)

        # Fallback for unknown provider payload shape.
        if not result:
            raw = metadata.get("raw")
            extracted = _extract_review_tags_from_payload(raw)
            for item in extracted:
                _push(item)
        return result

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
    def _resolve_processing_mode(
        processed: object,
        template: dict[str, object] | None,
        rule: dict[str, object] | None,
    ) -> tuple[str, bool, str]:
        if rule:
            mode = str(rule.get("action_mode") or "manual").strip().lower()
            auto_send = bool(rule.get("auto_send"))
            if mode in {"ai", "auto", "template", "manual", "ignore"}:
                normalized_mode = "auto" if mode == "template" else mode
                return normalized_mode, auto_send, ""
        if template:
            mode = str(template.get("mode") or "manual")
            text = str(template.get("template_text") or "")
            is_enabled = bool(template.get("is_enabled"))
            if is_enabled and mode in {"auto", "manual", "ignore"}:
                return mode, mode == "auto", text
        # По умолчанию система не выполняет автообработку, пока правило не включено.
        return "manual", False, ""

    def _pick_recommendation_for_review(self, *, user_id: int | None, review: ReviewInput) -> str:
        if user_id is None:
            return ""
        source_article = self._extract_product_article(review)
        if not source_article:
            return ""
        recommendation = self.repository.get_random_recommendation(
            user_id=user_id,
            source_article=source_article,
        )
        return str(recommendation or "").strip()

    @staticmethod
    def _extract_product_article(review: ReviewInput) -> str | None:
        def _find_in_mapping(payload: Mapping[str, object]) -> str | None:
            keys = (
                "article",
                "article_id",
                "sku",
                "offer_id",
                "offerId",
                "vendor_code",
                "vendorCode",
                "nmId",
                "nm_id",
                "product_id",
                "productId",
                "item_id",
                "itemId",
            )
            for key in keys:
                if key not in payload:
                    continue
                value = str(payload.get(key) or "").strip()
                if value:
                    return value
            return None

        metadata = review.metadata if isinstance(review.metadata, dict) else {}
        candidates: list[Mapping[str, object]] = []
        if metadata:
            candidates.append(metadata)
        raw = metadata.get("raw")
        if isinstance(raw, Mapping):
            candidates.append(raw)
            nested = raw.get("product")
            if isinstance(nested, Mapping):
                candidates.append(nested)
            nested_item = raw.get("item")
            if isinstance(nested_item, Mapping):
                candidates.append(nested_item)
        for payload in candidates:
            found = _find_in_mapping(payload)
            if found:
                return found
        return None

    @staticmethod
    def _cleanup_rendered_text(text: str) -> str:
        clean = text.strip()
        clean = re.sub(r"\s+([,.;:!?])", r"\1", clean)
        clean = re.sub(r"\s{2,}", " ", clean)
        clean = clean.replace(",!", "!").replace(",?", "?").replace(",.", ".")
        clean = re.sub(r"^[,.;:!?\-\s]+", "", clean)
        clean = clean.replace(" ,", ",").replace(" .", ".").replace(" !", "!").replace(" ?", "?")
        return clean.strip()

    def _render_template(
        self,
        template: str,
        *,
        user_id: int | None,
        review: ReviewInput,
        category: str,
        sentiment: str,
        default_brand_name: str = "VarFabric",
    ) -> str:
        text = template or "Спасибо за отзыв!"
        author_raw = (review.author or "").strip()
        author = author_raw or "клиент"
        rating = review.rating if review.rating is not None else "без оценки"
        category_ru = {
            "negative_delivery": "Негатив: доставка",
            "negative_product": "Негатив: товар",
            "negative_other": "Негатив: прочее",
            "positive_quality": "Позитив: качество",
            "positive_product": "Позитив: товар",
            "neutral_other": "Нейтральный: прочее",
        }.get(category, category)
        sentiment_ru = {
            "negative": "негативная",
            "positive": "позитивная",
            "neutral": "нейтральная",
        }.get(sentiment, sentiment)
        tags_text = ", ".join(self._extract_review_tags(review)) or "без тегов"
        context = {
            "author": author,
            "автор": author,
            "rating": rating,
            "оценка": rating,
            "category": category,
            "категория": category_ru,
            "sentiment": sentiment,
            "тональность": sentiment_ru,
            "tags": tags_text,
            "теги": tags_text,
            "review_id": review.review_id,
            "идентификатор_отзыва": review.review_id,
        }
        for key, value in context.items():
            text = text.replace(f"{{{key}}}", str(value))
        reco = self._pick_recommendation_for_review(user_id=user_id, review=review)
        brand = str((review.metadata or {}).get("brand") or default_brand_name or "VarFabric").strip() or "VarFabric"
        text = text.replace("%USER%", author_raw)
        text = text.replace("%RECO%", reco)
        text = text.replace("%%RECO%%", reco)
        text = text.replace("%BRAND%", brand)
        return self._cleanup_rendered_text(text)

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


def _is_tag_candidate(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if len(text) > 120:
        return False
    if text.isdigit():
        return False
    return any(char.isalpha() for char in text)


def _extract_review_tags_from_payload(payload: object) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    def _push(raw_value: object) -> None:
        if isinstance(raw_value, str):
            parts = re.split(r"[,\n;/|]+", raw_value)
            for part in parts:
                clean = part.strip()
                if not _is_tag_candidate(clean):
                    continue
                key = clean.lower()
                if key in seen:
                    continue
                seen.add(key)
                result.append(clean)
            return
        if isinstance(raw_value, (int, float)):
            return
        if isinstance(raw_value, list):
            for item in raw_value:
                _push(item)
            return
        if isinstance(raw_value, Mapping):
            for key, value in raw_value.items():
                key_text = str(key).lower()
                if key_text in {"name", "title", "value", "text", "label", "tag"}:
                    _push(value)
                    continue
                if any(marker in key_text for marker in ("tag", "label", "mark", "pros", "cons", "advantage", "disadvantage")):
                    _push(value)
                    continue
                if isinstance(value, (list, Mapping)):
                    _push(value)

    if not isinstance(payload, Mapping):
        return result
    for candidate_key in (
        "tags",
        "tag",
        "labels",
        "marks",
        "pros",
        "cons",
        "advantages",
        "disadvantages",
        "pluses",
        "minuses",
        "qualities",
        "quality_tags",
    ):
        if candidate_key in payload:
            _push(payload.get(candidate_key))
    for nested_key in ("raw", "details", "product", "item", "attributes", "options"):
        nested_value = payload.get(nested_key)
        if nested_value is not None:
            _push(nested_value)
    return result


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
