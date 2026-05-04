from __future__ import annotations

import json
import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
import time
from urllib.parse import urlencode, urljoin, urlparse
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

    def fetch_questions(
        self,
        *,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[dict[str, object]]:
        """Load only questions from marketplace API."""

    def fetch_chats(
        self,
        *,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[dict[str, object]]:
        """Load only chats from marketplace API."""

    def send_conversation_reply(
        self,
        *,
        conversation: dict[str, object],
        response_text: str,
    ) -> bool:
        """Send reply for question/chat to marketplace API."""


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
        return self.fetch_questions(stop_requested=stop_requested) + self.fetch_chats(stop_requested=stop_requested)

    def fetch_questions(self, *, stop_requested: Callable[[], bool] | None = None) -> list[dict[str, object]]:
        _raise_if_stop_requested(stop_requested, source="http")
        return []

    def fetch_chats(self, *, stop_requested: Callable[[], bool] | None = None) -> list[dict[str, object]]:
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
            # Ozon API: general guideline ≤ 10 req/s. Sleep 150 ms between
            # pages to stay comfortably within the limit.
            if page > 0:
                time.sleep(0.15)
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
        return self.fetch_questions(stop_requested=stop_requested) + self.fetch_chats(stop_requested=stop_requested)

    def fetch_questions(
        self,
        *,
        since_date: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[dict[str, object]]:
        return self._fetch_conversation_stream(
            path=self.questions_path,
            kind="question",
            since_date=since_date,
            stop_requested=stop_requested,
        )

    def fetch_chats(
        self,
        *,
        since_date: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[dict[str, object]]:
        return self._fetch_conversation_stream(
            path=self.chats_path,
            kind="chat",
            since_date=since_date,
            stop_requested=stop_requested,
        )

    def _fetch_conversation_stream(
        self,
        *,
        path: str | None,
        kind: str,
        since_date: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[dict[str, object]]:
        if not path:
            return []

        cursor: str | None = None
        page = 0
        result_items: list[dict[str, object]] = []
        while page < self.max_pages:
            _raise_if_stop_requested(stop_requested, source="ozon")
            if page > 0:
                time.sleep(0.15)
            payload: dict[str, object] = {"limit": self.page_size}
            if since_date:
                # Ozon uses date_from / dateFrom for filtering by date
                payload.setdefault("date_from", since_date)
                payload.setdefault("dateFrom", since_date)
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

    def send_conversation_reply(self, *, conversation: dict[str, object], response_text: str) -> bool:
        if not self.client_id or not self.api_key:
            raise MarketplaceSyncError("ozon", "Missing Ozon credentials: client_id/api_key")
        if not self.reply_path:
            return False
        external_id = str(conversation.get("external_conversation_id") or conversation.get("external_id") or "").strip()
        if not external_id:
            raise MarketplaceSyncError("ozon", "Missing external conversation id for reply")
        payload: dict[str, object] = dict(self.reply_payload or {})
        payload[self.reply_review_id_field] = external_id
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
    chats_api_url: str | None = None
    chats_events_path: str | None = "/api/v1/seller/events"
    _resume_events_cursor: str | None = None
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
            # WB Feedbacks API: limit 3 req/s (burst 6). Sleep between pages so
            # we stay well within the 333 ms / request budget.
            if page > 0:
                time.sleep(0.4)
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
        return self.fetch_questions(stop_requested=stop_requested) + self.fetch_chats(stop_requested=stop_requested)

    def fetch_questions(
        self,
        *,
        since_date: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[dict[str, object]]:
        if not self.questions_path:
            return []
        return self._fetch_conversation_endpoint(
            path=self.questions_path,
            kind="question",
            since_date=since_date,
            stop_requested=stop_requested,
        )

    def fetch_chats(
        self,
        *,
        since_date: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
        enrich_with_events: bool = False,
    ) -> list[dict[str, object]]:
        """Fetch the list of seller chats.

        When ``enrich_with_events=True`` (used only during full sync, not during
        capability probes) the events endpoint is also queried to determine the
        last-message sender per chat, which drives the answered/needs-reply
        bucket logic.  This extra step paginates events with a 1.1 s inter-page
        sleep and should NOT be triggered during quick capability checks.
        """
        if not self.chats_path:
            return []
        # WB buyer-chat list returns ALL chats in a single request —
        # no pagination params (skip/take/isAnswered/dateFrom) are supported.
        chats = self._fetch_conversation_endpoint(
            path=self.chats_path,
            kind="chat",
            base_url=self.chats_api_url or self.api_url,
            single_request=True,
            stop_requested=stop_requested,
        )
        if not chats or not enrich_with_events:
            return chats
        # Enrich each chat with last-sender info from the events endpoint.
        # Pass resume_cursor so subsequent syncs only fetch new events.
        try:
            sender_map = self._fetch_last_sender_map(
                since_date=since_date,
                resume_cursor=self._resume_events_cursor,
                stop_requested=stop_requested,
            )
        except MarketplaceSyncError as exc:
            if bool(exc.details.get("cancelled")):
                raise
            sender_map = {}
        except Exception:
            sender_map = {}
        # Extract and store final cursor for next sync.
        cursor_entry = sender_map.pop("_final_cursor", None)
        if isinstance(cursor_entry, dict):
            new_cursor = cursor_entry.get("cursor")
            if new_cursor:
                self._resume_events_cursor = str(new_cursor)
        if sender_map:
            for chat in chats:
                ext_id = str(chat.get("external_id") or "").strip()
                if not ext_id:
                    continue
                sender_info = sender_map.get(ext_id)
                if not sender_info:
                    continue
                meta = chat.get("metadata")
                if isinstance(meta, dict):
                    meta["last_sender"] = sender_info.get("sender")
                    meta["last_sender_ts"] = sender_info.get("ts")
                    # Embed raw events for later storage in sync_chats().
                    meta["_wb_events"] = sender_info.get("events") or []
                if sender_info.get("sender") == "seller":
                    chat["last_sender"] = "seller"
                elif sender_info.get("sender") == "client":
                    chat["last_sender"] = "client"
        return chats

    def _fetch_last_sender_map(
        self,
        *,
        since_date: str | None = None,
        resume_cursor: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> dict[str, dict[str, object]]:
        """Return a map of chatID -> {sender, ts, events, _final_cursor}.

        Paginates through /api/v1/seller/events using the ``next`` cursor.

        ``resume_cursor`` (persisted from last sync): start pagination from
        this position instead of the beginning.  This means subsequent syncs
        only fetch NEW events, not the full history (saves ~90 seconds on the
        first daily re-sync after the initial full load).

        The returned dict includes a special key ``_final_cursor`` with the
        last cursor value so the caller can persist it for next time.

        Events older than ``since_date`` are still skipped client-side.
        """
        if not self.chats_events_path:
            return {}
        base_url = self.chats_api_url or self.api_url
        endpoint = _compose_url(base_url, self.chats_events_path)

        # Convert since_date to a unix-ms cutoff.
        since_ts_ms: int | None = None
        if since_date:
            raw_since = _normalize_timestamp(since_date)
            if raw_since:
                try:
                    dt = datetime.fromisoformat(raw_since.replace("Z", "+00:00"))
                    since_ts_ms = int(dt.timestamp() * 1000)
                except (ValueError, AttributeError):
                    pass

        result: dict[str, dict[str, object]] = {}
        events_by_chat: dict[str, list[dict[str, object]]] = {}
        # Start from resume_cursor if provided (incremental sync), else from start.
        cursor: str | None = resume_cursor or None
        final_cursor: str | None = cursor
        max_pages = 500
        page = 0
        _CHAT_API_BURST = 9
        while page < max_pages:
            _raise_if_stop_requested(stop_requested, source="wb")
            if page > 0 and page % _CHAT_API_BURST == 0:
                time.sleep(10.5)
            url = endpoint if cursor is None else f"{endpoint}?next={cursor}"
            request = Request(url, method="GET", headers={"Authorization": self.api_key})
            try:
                payload = _request_json(request=request, timeout=self.timeout, source="wb")
            except MarketplaceSyncError:
                break
            if not isinstance(payload, dict):
                break
            raw_result = payload.get("result") or {}
            if not isinstance(raw_result, dict):
                break
            events = raw_result.get("events") or []
            if not isinstance(events, list) or not events:
                break
            for event in events:
                if not isinstance(event, dict):
                    continue
                chat_id = str(event.get("chatID") or "").strip()
                sender = str(event.get("sender") or "").strip().lower()
                ts_raw = event.get("addTimestamp")
                try:
                    ts = int(ts_raw) if ts_raw is not None else 0
                except (TypeError, ValueError):
                    ts = 0
                if since_ts_ms is not None and ts > 0 and ts < since_ts_ms:
                    continue
                if not chat_id or not sender:
                    continue
                prev = result.get(chat_id)
                if prev is None or ts > int(prev.get("ts") or 0):
                    result[chat_id] = {"sender": sender, "ts": ts}
                events_by_chat.setdefault(chat_id, []).append(event)
            new_cursor = str(raw_result.get("next") or "").strip() or None
            if new_cursor:
                final_cursor = new_cursor
            cursor = new_cursor
            if not cursor:
                break
            page += 1

        for chat_id, ev_list in events_by_chat.items():
            entry = result.setdefault(chat_id, {})
            entry["events"] = ev_list
        # Store the final cursor so the caller can persist it.
        result["_final_cursor"] = {"cursor": final_cursor}  # type: ignore[assignment]
        return result

    def _fetch_conversation_endpoint(
        self,
        *,
        path: str,
        kind: str,
        base_url: str | None = None,
        since_date: str | None = None,
        single_request: bool = False,
        stop_requested: Callable[[], bool] | None = None,
    ) -> list[dict[str, object]]:
        """Fetch a WB conversation endpoint.

        ``single_request=True``: one GET with no query params (used for the
        WB buyer-chat list which returns all chats in one response and does not
        support skip/take/isAnswered/dateFrom).

        ``single_request=False`` (default): paginated loop with skip/take and
        optional dateFrom — used for the WB questions endpoint.

        Rate limit: WB Feedbacks/Questions API = 3 req/s → sleep 0.4 s between
        pages for paginated mode.
        """
        conversation_keys = self.items_keys + ("questions", "chats", "dialogs", "messages", "result")
        result: list[dict[str, object]] = []

        if single_request:
            # One-shot fetch — no pagination, no extra query params.
            _raise_if_stop_requested(stop_requested, source="wb")
            endpoint = _compose_url(base_url or self.api_url, path)
            request = Request(endpoint, method="GET", headers={"Authorization": self.api_key})
            payload = _request_json(request=request, timeout=self.timeout, source="wb")
            if not isinstance(payload, dict):
                raise MarketplaceSyncError("wb", "Wildberries API returned non-object payload for conversations")
            _raise_if_error_payload(payload, source="wb")
            rows = _extract_sequence(payload, keys=conversation_keys)
            if not rows:
                for nested_key in ("data", "result", "response"):
                    nested_value = payload.get(nested_key)
                    if not isinstance(nested_value, Mapping | list):
                        continue
                    rows = _extract_sequence(nested_value, keys=conversation_keys)
                    if rows:
                        break
            for item in rows:
                mapped = self._to_conversation(item, kind=kind)
                if mapped:
                    result.append(mapped)
            return result

        skip = 0
        page = 0

        # WB Questions supports dateFrom as unix seconds (same as feedbacks).
        wb_date_from = self._to_wb_unix_timestamp(since_date)

        while page < self.max_pages:
            _raise_if_stop_requested(stop_requested, source="wb")
            if page > 0:
                # WB Feedbacks API: 3 req/s limit → 400 ms between requests.
                time.sleep(0.4)
            endpoint = _compose_url(base_url or self.api_url, path)
            params_dict: dict[str, object] = {
                self.skip_param: skip,
                self.take_param: self.page_size,
                self.unanswered_param: self.unanswered_value,
            }
            if wb_date_from is not None:
                params_dict["dateFrom"] = wb_date_from
            params = urlencode(params_dict)
            url = f"{endpoint}?{params}" if "?" not in endpoint else f"{endpoint}&{params}"
            request = Request(url, method="GET", headers={"Authorization": self.api_key})
            payload = _request_json(request=request, timeout=self.timeout, source="wb")
            if not isinstance(payload, dict):
                raise MarketplaceSyncError("wb", "Wildberries API returned non-object payload for conversations")
            _raise_if_error_payload(payload, source="wb")
            rows = _extract_sequence(payload, keys=conversation_keys)
            if not rows:
                for nested_key in ("data", "result", "response"):
                    nested_value = payload.get(nested_key)
                    if not isinstance(nested_value, Mapping | list):
                        continue
                    rows = _extract_sequence(nested_value, keys=conversation_keys)
                    if rows:
                        break
            if not rows:
                break
            for item in rows:
                mapped = self._to_conversation(item, kind=kind)
                if mapped:
                    result.append(mapped)
            if len(rows) < self.page_size:
                break
            skip += self.page_size
            page += 1

        return result

    def _request_json(self, *, skip: int, take: int, since_date: str | None = None) -> dict[str, object]:
        params_payload: dict[str, object] = {
            self.skip_param: skip,
            self.take_param: take,
            self.unanswered_param: self.unanswered_value,
        }
        wb_date_from = self._to_wb_unix_timestamp(since_date)
        if wb_date_from is not None:
            params_payload["dateFrom"] = wb_date_from
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

    @staticmethod
    def _to_wb_unix_timestamp(since_date: str | None) -> int | None:
        raw = str(since_date or "").strip()
        if not raw:
            return None
        if raw.isdigit():
            parsed = int(raw)
            return parsed if parsed > 0 else None
        normalized = raw.replace("Z", "+00:00")
        parsed_dt: datetime | None = None
        try:
            parsed_dt = datetime.fromisoformat(normalized)
        except ValueError:
            # Sync settings keep date in YYYY-MM-DD format.
            date_part = normalized[:10]
            try:
                parsed_dt = datetime.strptime(date_part, "%Y-%m-%d")
            except ValueError:
                return None
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=UTC)
        return int(parsed_dt.astimezone(UTC).timestamp())

    def _fetch_fresh_reply_sign(self, *, chat_id: str) -> str | None:
        """Fetch the current replySign for a specific chat from /seller/chats.

        replySign changes over time.  Calling this before sending ensures
        we use the latest value rather than a potentially stale one from sync.
        """
        if not chat_id or not self.chats_path:
            return None
        try:
            base = self.chats_api_url or self.api_url
            endpoint = _compose_url(base, self.chats_path)
            req = Request(endpoint, method="GET", headers={"Authorization": self.api_key})
            payload = _request_json(request=req, timeout=self.timeout, source="wb")
            if not isinstance(payload, dict):
                return None
            items = _extract_sequence(
                payload,
                keys=self.items_keys + ("questions", "chats", "dialogs", "messages", "result"),
            )
            if not items:
                for nk in ("data", "result", "response"):
                    nv = payload.get(nk)
                    if isinstance(nv, (dict, list)):
                        items = _extract_sequence(nv, keys=self.items_keys + ("chats", "result"))
                        if items:
                            break
            for item in items:
                if str(item.get("chatID") or "") == chat_id:
                    return str(item.get("replySign") or "").strip() or None
        except Exception:
            pass
        return None

    def count_pending(self, *, since_date: str | None = None) -> dict[str, int]:
        """Return approximate counts of items available to sync per channel.

        Uses lightweight count endpoints where available:
        - Reviews: GET /api/v1/feedbacks/count-unanswered → countUnanswered
        - Questions: GET /api/v1/questions/count          → countUnanswered
        - Chats: GET /api/v1/seller/chats (full list), count items returned

        Returns 0 for any channel that errors (access denied, not configured).
        """
        counts: dict[str, int] = {"reviews": 0, "questions": 0, "chats": 0}
        wb_date_from = self._to_wb_unix_timestamp(since_date)

        # Reviews count via /api/v1/feedbacks/count-unanswered
        try:
            review_count_path = "/api/v1/feedbacks/count-unanswered"
            endpoint = _compose_url(self.api_url, review_count_path)
            if wb_date_from is not None:
                endpoint = f"{endpoint}?dateFrom={wb_date_from}"
            req = Request(endpoint, method="GET", headers={"Authorization": self.api_key})
            payload = _request_json(request=req, timeout=self.timeout, source="wb")
            if isinstance(payload, dict):
                data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
                counts["reviews"] = int(data.get("countUnanswered") or 0)
        except Exception:
            counts["reviews"] = 0

        # Questions count via /api/v1/questions/count
        try:
            q_count_path = "/api/v1/questions/count"
            endpoint = _compose_url(self.api_url, q_count_path)
            if wb_date_from is not None:
                endpoint = f"{endpoint}?dateFrom={wb_date_from}"
            req = Request(endpoint, method="GET", headers={"Authorization": self.api_key})
            payload = _request_json(request=req, timeout=self.timeout, source="wb")
            if isinstance(payload, dict):
                data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
                counts["questions"] = int(
                    data.get("countUnanswered")
                    or data.get("count")
                    or data.get("total")
                    or 0
                )
        except Exception:
            counts["questions"] = 0

        # Chats: GET /api/v1/seller/chats returns the full list - just count items
        try:
            if self.chats_path:
                base = self.chats_api_url or self.api_url
                endpoint = _compose_url(base, self.chats_path)
                req = Request(endpoint, method="GET", headers={"Authorization": self.api_key})
                payload = _request_json(request=req, timeout=self.timeout, source="wb")
                if isinstance(payload, dict):
                    items = _extract_sequence(
                        payload,
                        keys=self.items_keys + ("questions", "chats", "dialogs", "messages", "result"),
                    )
                    if not items:
                        for nk in ("data", "result", "response"):
                            nv = payload.get(nk)
                            if isinstance(nv, (dict, list)):
                                items = _extract_sequence(
                                    nv,
                                    keys=self.items_keys + ("questions", "chats", "result"),
                                )
                                if items:
                                    break
                    counts["chats"] = len(items)
        except Exception:
            counts["chats"] = 0

        return counts

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

    def send_conversation_reply(self, *, conversation: dict[str, object], response_text: str) -> bool:
        if not self.api_key:
            raise MarketplaceSyncError("wb", "Missing Wildberries api_key")
        # WB Buyer Chat API uses POST /api/v1/seller/message with replySign.
        # replySign is stored in conversation metadata.raw from the chat list.
        meta = conversation.get("metadata") or {}
        raw_data = meta.get("raw") or {} if isinstance(meta, Mapping) else {}
        reply_sign = str(raw_data.get("replySign") or "").strip() if isinstance(raw_data, Mapping) else ""

        if reply_sign and self.chats_api_url:
            # Chat reply via buyer-chat-api
            base_url = self.chats_api_url
            endpoint = _compose_url(base_url, "/api/v1/seller/message")
            request = Request(
                endpoint,
                method="POST",
                headers={"Authorization": self.api_key, "Content-Type": "application/json"},
                data=json.dumps({"replySign": reply_sign, "text": response_text}).encode("utf-8"),
            )
            raw = _request_json(request=request, timeout=self.timeout, source="wb", retries=1)
            _raise_if_error_payload(raw, source="wb")
            return True

        # Fallback: legacy reply path (feedbacks/questions)
        if not self.reply_path:
            return False
        external_id = str(conversation.get("external_conversation_id") or conversation.get("external_id") or "").strip()
        if not external_id:
            raise MarketplaceSyncError("wb", "Missing external conversation id for reply")
        payload: dict[str, object] = dict(self.reply_payload or {})
        payload[self.reply_review_id_field] = external_id
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
        external_id = str(
            item.get("id")
            or item.get("chatId")
            or item.get("chatID")
            or item.get("chat_id")
            or item.get("questionId")
            or item.get("questionID")
            or item.get("question_id")
            or item.get("dialogId")
            or item.get("dialog_id")
            or item.get("conversationId")
            or item.get("conversation_id")
            or ""
        ).strip()
        if not external_id:
            return None
        last_message = item.get("lastMessage") if isinstance(item.get("lastMessage"), Mapping) else None
        text = str(
            item.get("text")
            or item.get("message")
            or item.get("question")
            or item.get("lastMessageText")
            or item.get("last_message_text")
            or (last_message.get("text") if isinstance(last_message, Mapping) else "")
            or (last_message.get("message") if isinstance(last_message, Mapping) else "")
            or ""
        )
        customer_name = str(item.get("userName") or item.get("author") or item.get("clientName") or "") or None
        status = str(item.get("status") or "open").lower()
        unread_raw = (
            item.get("unread_count")
            if item.get("unread_count") is not None
            else item.get("unreadCount")
            if item.get("unreadCount") is not None
            else item.get("newMessages")
        )
        last_message_at_raw = (
            item.get("updatedAt")
            or item.get("updated_at")
            or item.get("last_message_at")
            or item.get("lastMessageAt")
            or (last_message.get("addTimestamp") if isinstance(last_message, Mapping) else None)
            or (last_message.get("createdAt") if isinstance(last_message, Mapping) else None)
            or (last_message.get("dateTime") if isinstance(last_message, Mapping) else None)
        )
        last_message_at = _normalize_timestamp(last_message_at_raw)
        return {
            "external_id": external_id,
            "kind": kind,
            "customer_name": customer_name,
            "message_text": text,
            "status": status if status in {"open", "closed", "waiting"} else "open",
            "unread_count": _to_positive_int(unread_raw, default=0),
            "last_message_at": last_message_at,
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
        return self.fetch_questions(stop_requested=stop_requested) + self.fetch_chats(stop_requested=stop_requested)

    def fetch_questions(self, *, stop_requested: Callable[[], bool] | None = None) -> list[dict[str, object]]:
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
        ]

    def fetch_chats(self, *, stop_requested: Callable[[], bool] | None = None) -> list[dict[str, object]]:
        _raise_if_stop_requested(stop_requested, source="mock")
        return [
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
    TEXTLESS_GROUP_ID = "textless_ratings"
    TEXTLESS_LOW_SUBGROUP = "1-3 звезды"
    TEXTLESS_HIGH_SUBGROUP = "4-5 звезд"
    GENERAL_SUBGROUP_TITLE = "Общий"
    REVIEW_GROUPS_WITH_GENERAL_SUBGROUP: tuple[str, ...] = (
        "positive",
        "product_dissatisfaction",
        "delivery_problems",
        "wrong_size",
        "tagged_reviews",
    )
    AI_UNCLASSIFIED_CATEGORY = "ai_unclassified"
    AI_UNCLASSIFIED_NOTE = "ИИ не смог корректно определить категорию."
    REVIEW_GROUP_DEFAULT_SUBGROUPS: dict[str, list[str]] = {
        "positive": [
            GENERAL_SUBGROUP_TITLE,
            "Вкус",
            "Материал",
            "Общий позитив",
            "Позитив доставка",
            "Позитив запах",
            "Позитив конструкция",
            "Позитив упаковка",
            "Позитив цвет",
            "Эффект",
        ],
        "product_dissatisfaction": [
            GENERAL_SUBGROUP_TITLE,
            "Брак и Б/У",
            "Высокая цена",
            "Качество",
            "Негатив запах",
            "Негатив конструкция",
            "Негатив цвет",
            "Не подошел лично мне",
            "Не соответствует фото",
            "Не устраивает эффект",
            "Общий негатив",
            "Побочные эффекты",
            "Подделка",
            "Срок годности",
            "Текстура, консистенция, материал",
        ],
        "delivery_problems": [
            GENERAL_SUBGROUP_TITLE,
            "Долгая доставка",
            "Испорченная упаковка",
            "Наклейка",
            "Недостающая упаковка / грязное / поврежденное и сломанное",
            "Некомплект",
            "Не тот товар",
            "Общие доставка",
        ],
        "wrong_size": [
            GENERAL_SUBGROUP_TITLE,
            "Альтернативные измерения",
            "Большемерит/маломерит",
            "Не подошел размер",
        ],
        "tagged_reviews": [
            GENERAL_SUBGROUP_TITLE,
            "Общие теги",
        ],
        TEXTLESS_GROUP_ID: [
            TEXTLESS_LOW_SUBGROUP,
            TEXTLESS_HIGH_SUBGROUP,
        ],
    }
    REVIEW_GROUP_TITLES: dict[str, str] = {
        "positive": "Позитив",
        "product_dissatisfaction": "Недовольство товаром",
        "delivery_problems": "Проблемы при доставке",
        "wrong_size": "Неправильный размер",
        "tagged_reviews": "Отзывы с тегами",
        "textless_ratings": "Оценки без текста",
    }
    GROUP_PROCESSING_DEFAULTS: dict[str, str] = {
        "positive": "yandex",
        "product_dissatisfaction": "yandex",
        "delivery_problems": "yandex",
        "wrong_size": "yandex",
        "tagged_reviews": "program",
        "textless_ratings": "program",
    }

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
            if not self._is_access_error(exc):
                self.repository.log_review_action(
                    user_id=user_id,
                    review_uid=None,
                    action_type="sync_error",
                    actor="system",
                    details={"source": source, "account_id": account_id, "error": str(exc), **exc.details},
                )
            raise
        settings = self.repository.get_ai_settings(include_secrets=True)
        classification_options = self._list_group_subgroups_for_review_classification(
            repository=self.repository,
            user_id=user_id,
        )
        subgroup_lookup_by_group: dict[str, dict[str, str]] = {}
        for item in classification_options:
            group_id = str(item.get("group_id") or "").strip()
            subgroup_items = item.get("subgroup_items")
            if not group_id or not isinstance(subgroup_items, list):
                continue
            subgroup_lookup: dict[str, str] = {}
            for subgroup_item in subgroup_items:
                if not isinstance(subgroup_item, Mapping):
                    continue
                subgroup_title = str(subgroup_item.get("subgroup") or subgroup_item.get("subgroup_title") or "").strip()
                if not subgroup_title:
                    continue
                normalized = self._normalize_subgroup_name(subgroup_title)
                if normalized and normalized not in subgroup_lookup:
                    subgroup_lookup[normalized] = subgroup_title
            if subgroup_lookup:
                subgroup_lookup_by_group[group_id] = subgroup_lookup

        def _resolve_classified_subgroup(group_id: str, subgroup: str | None) -> str | None:
            clean_group = str(group_id or "").strip()
            clean_subgroup = str(subgroup or "").strip()
            if clean_group not in self.REVIEW_GROUPS_WITH_GENERAL_SUBGROUP:
                return clean_subgroup or None
            lookup = subgroup_lookup_by_group.get(clean_group) or {}
            general_subgroup = lookup.get(
                self._normalize_subgroup_name(self.GENERAL_SUBGROUP_TITLE),
                self.GENERAL_SUBGROUP_TITLE,
            )
            if not clean_subgroup:
                return general_subgroup
            normalized = self._normalize_subgroup_name(clean_subgroup)
            if normalized in lookup:
                return lookup[normalized]
            return general_subgroup

        for review in reviews:
            _raise_if_stop_requested(stop_requested, source=source)
            if not review.review_id:
                continue
            processed = self.processor.process(review)
            ai_classification_failed = False
            ai_classification_error = ""
            try:
                category, classified_subgroup = self._classify_category_and_subgroup(
                    review,
                    processed,
                    settings=settings,
                    user_id=user_id,
                )
            except MarketplaceSyncError as exc:
                details = exc.details if isinstance(exc.details, Mapping) else {}
                if str(details.get("scope") or "").strip().lower() == "classification":
                    category = self.AI_UNCLASSIFIED_CATEGORY
                    classified_subgroup = None
                    ai_classification_failed = True
                    ai_classification_error = str(exc)
                else:
                    raise
            if not ai_classification_failed:
                category = str(category or "").strip()
                if not category:
                    ai_classification_failed = True
                    ai_classification_error = "Яндекс-классификатор не вернул корректную группу и подгруппу."
                    category = self.AI_UNCLASSIFIED_CATEGORY
                    classified_subgroup = None
                else:
                    classified_subgroup = _resolve_classified_subgroup(category, classified_subgroup)
            review_metadata = dict(review.metadata) if isinstance(review.metadata, dict) else {}
            if classified_subgroup:
                review_metadata["classified_subgroup"] = classified_subgroup
            review_metadata["classified_group_id"] = category
            if ai_classification_failed:
                review_metadata["ai_classification_status"] = "failed"
                review_metadata["ai_classification_note"] = self.AI_UNCLASSIFIED_NOTE
                review_metadata["ai_classification_error"] = ai_classification_error
            review_for_processing = ReviewInput(
                review_id=review.review_id,
                text=review.text,
                author=review.author,
                rating=review.rating,
                metadata=review_metadata,
            )
            category_for_template = category
            if category_for_template == self.AI_UNCLASSIFIED_CATEGORY:
                category_for_template = "product_dissatisfaction"
            template = self.repository.get_template(user_id=user_id, category=category_for_template)
            group_id = self._resolve_template_group_id(
                category=category,
                review=review_for_processing,
                sentiment=processed.sentiment_label,
            )
            rule = self.repository.get_processing_rule(user_id=user_id, group_id=group_id) if group_id else None
            mode, auto_send, template_text = self._resolve_processing_mode(processed, template, rule)
            if ai_classification_failed:
                mode = "manual"
                auto_send = False
                template_text = ""

            if mode == "template":
                group_template = self._pick_group_template_text(
                    user_id=user_id,
                    category=category_for_template,
                    review=review_for_processing,
                    sentiment=processed.sentiment_label,
                    preferred_subgroup=classified_subgroup,
                )
                selected_template = str(group_template or template_text or "").strip()
                if not selected_template:
                    status = "queued_for_operator"
                    auto_reply = None
                    self.repository.log_review_action(
                        user_id=user_id,
                        review_uid=self.repository.make_review_uid(user_id, source, account_id, review.review_id),
                        action_type="send_reply_error",
                        actor="system",
                        details={"source": source, "error": "Не найден шаблон для автоматического ответа"},
                    )
                    self.repository.upsert_processed_review(
                        user_id=user_id,
                        source=source,
                        account_id=account_id,
                        review=review_for_processing,
                        processed=processed,
                        category=category,
                        processing_mode=mode,
                        status=status,
                        auto_reply=auto_reply,
                    )
                    review_uid = self.repository.make_review_uid(user_id, source, account_id, review_for_processing.review_id)
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
                    continue
                auto_reply = self._render_template(
                    selected_template,
                    user_id=user_id,
                    review=review_for_processing,
                    category=category_for_template,
                    sentiment=processed.sentiment_label,
                )
                sent, send_error = self._send_reply_via_client(
                    client=client,
                    source=source,
                    review=review_for_processing,
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
                review=review_for_processing,
                processed=processed,
                category=category,
                processing_mode=mode,
                status=status,
                auto_reply=auto_reply,
            )
            review_uid = self.repository.make_review_uid(user_id, source, account_id, review_for_processing.review_id)
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
            if ai_classification_failed:
                self.repository.log_review_action(
                    user_id=user_id,
                    review_uid=review_uid,
                    action_type="ai_classification_failed",
                    actor="system",
                    details={
                        "source": source,
                        "error": ai_classification_error,
                        "scope": "classification",
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
        since_date: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> int:
        return self.sync_questions(
            user_id=user_id,
            source=source,
            account_id=account_id,
            client=client,
            since_date=since_date,
            stop_requested=stop_requested,
        ) + self.sync_chats(
            user_id=user_id,
            source=source,
            account_id=account_id,
            client=client,
            since_date=since_date,
            stop_requested=stop_requested,
        )

    def sync_questions(
        self,
        *,
        user_id: int,
        source: str,
        account_id: int | None,
        client: MarketplaceClient,
        since_date: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> int:
        fetch_questions = getattr(client, "fetch_questions", None)
        if not callable(fetch_questions):
            return 0

        try:
            try:
                rows = fetch_questions(since_date=since_date, stop_requested=stop_requested)
            except TypeError:
                rows = fetch_questions()
        except MarketplaceSyncError as exc:
            if not self._is_access_error(exc):
                self.repository.log_review_action(
                    user_id=user_id,
                    review_uid=None,
                    action_type="sync_error",
                    actor="system",
                    details={
                        "source": source,
                        "account_id": account_id,
                        "error": str(exc),
                        "scope": "questions",
                    },
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
                kind="question",
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
                details={"source": source, "kind": "question"},
            )
            loaded += 1
        return loaded

    def sync_chats(
        self,
        *,
        user_id: int,
        source: str,
        account_id: int | None,
        client: MarketplaceClient,
        since_date: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> int:
        fetch_chats = getattr(client, "fetch_chats", None)
        if not callable(fetch_chats):
            return 0

        try:
            try:
                # Step 1: fetch the chat list WITHOUT events — this is a single
                # fast request that returns all chats immediately.
                rows = fetch_chats(
                    since_date=since_date,
                    stop_requested=stop_requested,
                    enrich_with_events=False,
                )
            except TypeError:
                rows = fetch_chats()
        except MarketplaceSyncError as exc:
            if not self._is_access_error(exc):
                self.repository.log_review_action(
                    user_id=user_id,
                    review_uid=None,
                    action_type="sync_error",
                    actor="system",
                    details={
                        "source": source,
                        "account_id": account_id,
                        "error": str(exc),
                        "scope": "chats",
                    },
                )
            raise

        loaded = 0
        for row in rows:
            _raise_if_stop_requested(stop_requested, source=source)
            external_id = str(row.get("external_id") or "").strip()
            if not external_id:
                continue
            last_message_at = str(row.get("last_message_at") or "") or None
            # Determine seller_replied_at from the enriched last_sender field.
            # fetch_chats() adds last_sender="seller" when the most-recent event
            # in /api/v1/seller/events was sent by the seller.  In that case we
            # set seller_replied_at = last_message_at so the conversation moves
            # to the "answered" bucket without requiring a manual reply.
            seller_replied_at: str | None = None
            if str(row.get("last_sender") or "").strip().lower() == "seller":
                seller_replied_at = last_message_at
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            conversation_uid = self.repository.upsert_conversation(
                user_id=user_id,
                source=source,
                account_id=account_id,
                external_conversation_id=external_id,
                kind="chat",
                customer_name=str(row.get("customer_name") or "") or None,
                message_text=str(row.get("message_text") or ""),
                status=str(row.get("status") or "open"),
                unread_count=_to_positive_int(row.get("unread_count"), default=0),
                metadata=meta,
                last_message_at=last_message_at,
                seller_replied_at=seller_replied_at,
            )
            self.repository.log_review_action(
                user_id=user_id,
                review_uid=conversation_uid,
                action_type="sync_conversation",
                actor="system",
                details={"source": source, "kind": "chat"},
            )
            loaded += 1

        # WB /api/v1/seller/chats returns ALL chats with no date filter.
        # Apply since_date client-side: remove chats whose last_message_at
        # is older than the cutoff.
        if since_date and account_id is not None:
            since_iso = _normalize_timestamp(since_date)
            if since_iso:
                try:
                    self.repository.delete_conversations_before_date(
                        user_id=user_id,
                        account_id=int(account_id),
                        kind="chat",
                        before_date=since_iso,
                    )
                except Exception:
                    pass

        # Step 3: enrich chats with events (sender info + history).
        # This is the slow part (~95s first time) so it runs AFTER chats are
        # already saved to DB.  If the user stops sync early, chats are
        # still accessible — they just won't have correct answered/new status
        # until the next full sync completes.
        if loaded > 0 and callable(getattr(client, "fetch_chats", None)):
            try:
                enriched_rows = client.fetch_chats(
                    since_date=since_date,
                    stop_requested=stop_requested,
                    enrich_with_events=True,
                )
                for row in enriched_rows:
                    _raise_if_stop_requested(stop_requested, source=source)
                    ext_id = str(row.get("external_id") or "").strip()
                    if not ext_id:
                        continue
                    conv_uid = self.repository.make_conversation_uid(
                        user_id=user_id, source=source, account_id=account_id,
                        kind="chat", external_conversation_id=ext_id,
                    )
                    last_msg_at = str(row.get("last_message_at") or "") or None
                    last_sender = str(row.get("last_sender") or "").strip().lower()
                    # Only update seller_replied_at when we have explicit sender info.
                    # If sender is unknown (no events returned), leave existing value
                    # so already-answered chats don't lose their status.
                    seller_replied_at: str | None = None
                    if last_sender == "seller":
                        seller_replied_at = last_msg_at
                    elif last_sender == "":
                        # No event data for this chat in this sync pass — skip upsert
                        # to preserve existing answered/new status
                        continue
                    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                    wb_events_enrich: list[dict[str, object]] = []
                    if isinstance(meta, dict):
                        wb_events_enrich = list(meta.pop("_wb_events", None) or [])
                    # Update existing row with sender status.
                    try:
                        self.repository.upsert_conversation(
                            user_id=user_id,
                            source=source,
                            account_id=account_id,
                            external_conversation_id=ext_id,
                            kind="chat",
                            customer_name=str(row.get("customer_name") or "") or None,
                            message_text=str(row.get("message_text") or ""),
                            status=str(row.get("status") or "open"),
                            unread_count=_to_positive_int(row.get("unread_count"), default=0),
                            metadata=meta,
                            last_message_at=last_msg_at,
                            seller_replied_at=seller_replied_at,
                        )
                    except Exception:
                        pass
                    # Save chat history messages.
                    if wb_events_enrich:
                        history: list[dict[str, object]] = []
                        for ev in wb_events_enrich:
                            if not isinstance(ev, dict):
                                continue
                            ev_id = str(ev.get("eventID") or "").strip()
                            ev_sender = str(ev.get("sender") or "").strip().lower()
                            msg = ev.get("message") or {}
                            ev_text = str(msg.get("text") or "").strip()
                            # Handle image attachments: use placeholder text
                            attachments = msg.get("attachments") or {}
                            images = attachments.get("images") or []
                            if not ev_text and images:
                                ev_text = f"[Фото: {len(images)} шт.]"
                            elif not ev_text and attachments.get("goodCard"):
                                card = attachments["goodCard"]
                                ev_text = f"[Товар: {card.get('name', '')}]".strip()
                            ev_ts_raw = ev.get("addTimestamp")
                            ev_ts_ms = int(ev_ts_raw) if ev_ts_raw is not None else 0
                            ev_iso = _normalize_timestamp(ev_ts_ms) or ""
                            client_name = str(ev.get("clientName") or "").strip()
                            if not ev_id or not ev_text:
                                continue
                            history.append({
                                "direction": "inbound" if ev_sender == "client" else "outbound",
                                "message_text": ev_text,
                                "idempotency_key": f"wb-event-{ev_id}",
                                "created_at": ev_iso,
                                "operator_name": client_name if ev_sender == "client" else "Продавец",
                            })
                        if history:
                            try:
                                self.repository.bulk_insert_chat_history_messages(
                                    user_id=user_id,
                                    conversation_uid=conv_uid,
                                    messages=history,
                                )
                            except Exception:
                                pass
            except MarketplaceSyncError as exc:
                if bool(exc.details.get("cancelled")):
                    pass  # Cancelled: chats already saved, statuses will update on next sync
            except Exception:
                pass

            # Persist the final events cursor so the next sync starts from here.
            if account_id is not None and hasattr(client, "_resume_events_cursor"):
                new_cursor = getattr(client, "_resume_events_cursor", None)
                if new_cursor:
                    try:
                        self.repository.update_marketplace_account_extra_field(
                            user_id=user_id,
                            account_id=int(account_id),
                            key="_wb_events_cursor",
                            value=str(new_cursor),
                        )
                    except Exception:
                        pass

        return loaded

    def _is_access_error(self, error: object) -> bool:
        if isinstance(error, MarketplaceSyncError):
            message = str(error).lower()
        else:
            message = str(error or "").lower()
        if " 401" in message or " 403" in message:
            return True
        if "http error 401" in message or "http error 403" in message:
            return True
        if "forbidden" in message or "unauthorized" in message:
            return True
        if "access denied" in message or "permission" in message:
            return True
        if "недостаточно прав" in message or "нет доступа" in message:
            return True
        return False

    def _is_channel_supported(self, *, client: MarketplaceClient, channel: str) -> tuple[bool, str]:
        if channel == "reviews":
            return (callable(getattr(client, "fetch_reviews", None)), "Канал отзывов не поддерживается источником")
        if channel == "questions":
            method = getattr(client, "fetch_questions", None)
            if not callable(method):
                return False, "Канал вопросов не поддерживается источником"
            if hasattr(client, "questions_path") and not bool(getattr(client, "questions_path")):
                return False, "Канал вопросов не настроен для этого источника"
            return True, ""
        if channel == "chats":
            method = getattr(client, "fetch_chats", None)
            if not callable(method):
                return False, "Канал чатов не поддерживается источником"
            if hasattr(client, "chats_path") and not bool(getattr(client, "chats_path")):
                return False, "Канал чатов не настроен для этого источника"
            return True, ""
        return False, f"Неизвестный канал: {channel}"

    def count_pending_for_account(
        self,
        *,
        account: dict[str, object],
        since_date: str | None = None,
    ) -> dict[str, object]:
        """Return a preview of how many items will be synced for this account.

        Calls lightweight count endpoints rather than doing a full sync.
        Returns a dict with account_id, account_name, marketplace and
        channel counts: reviews, questions, chats.
        """
        account_id = int(account.get("id") or 0)
        account_name = str(account.get("account_name") or "")
        marketplace = str(account.get("marketplace") or "")
        client = self._build_client(account)
        counts: dict[str, int] = {"reviews": 0, "questions": 0, "chats": 0}
        if hasattr(client, "count_pending"):
            try:
                counts = client.count_pending(since_date=since_date)  # type: ignore[call-arg]
            except Exception:
                pass
        return {
            "account_id": account_id,
            "account_name": account_name,
            "marketplace": marketplace,
            "reviews": counts.get("reviews", 0),
            "questions": counts.get("questions", 0),
            "chats": counts.get("chats", 0),
            "total": sum(counts.values()),
        }

    def probe_account_channels(
        self,
        *,
        account: dict[str, object],
        since_date: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        account_id = int(account.get("id") or 0)
        marketplace = str(account.get("marketplace") or "")
        account_name = str(account.get("account_name") or "")
        client = self._build_client(account)
        if hasattr(client, "page_size"):
            try:
                setattr(client, "page_size", 1)
            except Exception:
                pass
        if hasattr(client, "max_pages"):
            try:
                setattr(client, "max_pages", 1)
            except Exception:
                pass

        channel_result: dict[str, dict[str, object]] = {}
        available_channels: list[str] = []
        unavailable_channels: list[str] = []
        for channel in ("reviews", "questions", "chats"):
            supported, reason = self._is_channel_supported(client=client, channel=channel)
            if not supported:
                channel_result[channel] = {
                    "available": False,
                    "access_denied": True,
                    "error": reason,
                    "reason": "not_configured",
                }
                unavailable_channels.append(channel)
                continue
            try:
                if channel == "reviews":
                    try:
                        getattr(client, "fetch_reviews")(since_date=since_date, stop_requested=stop_requested)
                    except TypeError:
                        getattr(client, "fetch_reviews")()
                elif channel == "questions":
                    try:
                        getattr(client, "fetch_questions")(stop_requested=stop_requested)
                    except TypeError:
                        getattr(client, "fetch_questions")()
                elif channel == "chats":
                    try:
                        getattr(client, "fetch_chats")(stop_requested=stop_requested)
                    except TypeError:
                        getattr(client, "fetch_chats")()
                channel_result[channel] = {"available": True, "access_denied": False, "error": ""}
                available_channels.append(channel)
            except MarketplaceSyncError as exc:
                if bool(exc.details.get("cancelled")):
                    raise
                access_denied = self._is_access_error(exc)
                channel_result[channel] = {
                    "available": False,
                    "access_denied": bool(access_denied),
                    "error": str(exc),
                    "reason": "access_denied" if access_denied else "temporary_error",
                }
                unavailable_channels.append(channel)
            except Exception as exc:  # pragma: no cover - defensive guard
                channel_result[channel] = {
                    "available": False,
                    "access_denied": False,
                    "error": str(exc),
                    "reason": "temporary_error",
                }
                unavailable_channels.append(channel)
        return {
            "account_id": account_id,
            "marketplace": marketplace,
            "account_name": account_name,
            "channels": channel_result,
            "available_channels": available_channels,
            "unavailable_channels": unavailable_channels,
        }

    def _run_channel_sync(
        self,
        *,
        channel: str,
        user_id: int,
        source: str,
        account_id: int,
        client: MarketplaceClient,
        since_date: str | None,
        stop_requested: Callable[[], bool] | None,
    ) -> dict[str, object]:
        supported, reason = self._is_channel_supported(client=client, channel=channel)
        if not supported:
            return {
                "ok": False,
                "loaded": 0,
                "channel": channel,
                "skipped": True,
                "access_denied": True,
                "error": reason,
            }
        if channel == "reviews":
            loaded = self.sync_reviews(
                user_id=user_id,
                source=source,
                account_id=account_id,
                client=client,
                since_date=since_date,
                stop_requested=stop_requested,
            )
        elif channel == "questions":
            loaded = self.sync_questions(
                user_id=user_id,
                source=source,
                account_id=account_id,
                client=client,
                since_date=since_date,
                stop_requested=stop_requested,
            )
        elif channel == "chats":
            loaded = self.sync_chats(
                user_id=user_id,
                source=source,
                account_id=account_id,
                client=client,
                since_date=since_date,
                stop_requested=stop_requested,
            )
        else:
            raise ValueError(f"Unknown channel: {channel}")
        return {"ok": True, "loaded": int(loaded), "channel": channel}


    def sync_all_accounts(
        self,
        *,
        user_id: int,
        since_date: str | None = None,
        account_ids: list[int] | None = None,
        stop_requested: Callable[[], bool] | None = None,
        progress_callback: Callable[..., None] | None = None,
    ) -> dict[str, object]:
        loaded_total = 0
        loaded_questions = 0
        loaded_chats = 0
        loaded_conversations = 0
        successful_accounts = 0
        errors: list[dict[str, object]] = []
        capability_warnings: list[dict[str, object]] = []
        account_channel_stats: list[dict[str, object]] = []
        was_cancelled = False
        account_ids_filter: set[int] | None = None
        if account_ids is not None:
            normalized_ids: set[int] = set()
            for value in account_ids:
                try:
                    account_id = int(value)
                except (TypeError, ValueError):
                    continue
                if account_id > 0:
                    normalized_ids.add(account_id)
            account_ids_filter = normalized_ids
        accounts = [
            item
            for item in self.repository.list_marketplace_accounts(user_id, include_secrets=True)
            if item["is_active"]
        ]
        if account_ids_filter is not None:
            accounts = [
                item
                for item in accounts
                if int(item.get("id") or 0) in account_ids_filter
            ]
        selected_account_ids = [
            int(item.get("id") or 0)
            for item in accounts
            if int(item.get("id") or 0) > 0
        ]
        requested_account_ids = sorted(account_ids_filter) if account_ids_filter is not None else list(selected_account_ids)
        skipped_accounts = max(len(requested_account_ids) - len(selected_account_ids), 0)
        since_value = str(since_date or "").strip() or None
        total_accounts = len(accounts)
        if progress_callback:
            try:
                progress_callback(
                    step="Начало синхронизации",
                    total_accounts=total_accounts,
                    current_account=0,
                )
            except Exception:
                pass
        for account_idx, account in enumerate(accounts, start=1):
            if stop_requested and stop_requested():
                was_cancelled = True
                break
            account_id = int(account["id"])
            marketplace = str(account["marketplace"])
            current_account = self.repository.get_marketplace_account(
                user_id=user_id,
                account_id=account_id,
                include_secrets=True,
            )
            if current_account is None or not bool(current_account.get("is_active")):
                continue
            account_name = str(current_account.get("account_name") or f"#{account_id}")
            if progress_callback:
                try:
                    progress_callback(
                        step="Синхронизация кабинета",
                        account=f"{account_name} ({marketplace.upper()})",
                        channel="",
                        current_account=account_idx,
                        total_accounts=total_accounts,
                    )
                except Exception:
                    pass
            try:
                client = self._build_client(current_account)
                channel_names = {"reviews": "Отзывы", "questions": "Вопросы", "chats": "Чаты"}
                channel_outcomes: dict[str, dict[str, object]] = {}
                for channel in ("reviews", "questions", "chats"):
                    if stop_requested and stop_requested():
                        was_cancelled = True
                        break
                    if progress_callback:
                        try:
                            progress_callback(
                                step="Загрузка данных",
                                account=f"{account_name} ({marketplace.upper()})",
                                channel=channel_names.get(channel, channel),
                            )
                        except Exception:
                            pass
                    try:
                        ch_result = self._run_channel_sync(
                            channel=channel,
                            user_id=user_id,
                            source=marketplace,
                            account_id=account_id,
                            client=client,
                            since_date=since_value,
                            stop_requested=stop_requested,
                        )
                        channel_outcomes[channel] = ch_result
                        if progress_callback:
                            try:
                                progress_callback(
                                    loaded=int(ch_result.get("loaded") or 0),
                                )
                            except Exception:
                                pass
                    except MarketplaceSyncError as exc:
                        if bool(exc.details.get("cancelled")):
                            was_cancelled = True
                            break
                        is_access_error = self._is_access_error(exc)
                        details = {
                            "account_id": account_id,
                            "marketplace": marketplace,
                            "channel": channel,
                            "scope": channel,
                            "error": str(exc),
                            "access_denied": bool(is_access_error),
                            **exc.details,
                        }
                        errors.append(details)
                        if is_access_error:
                            capability_warnings.append(
                                {
                                    "account_id": account_id,
                                    "marketplace": marketplace,
                                    "channel": channel,
                                    "message": str(exc),
                                }
                            )
                        channel_outcomes[channel] = {
                            "ok": False,
                            "loaded": 0,
                            "error": str(exc),
                            "access_denied": bool(is_access_error),
                        }
                    except Exception as exc:
                        details = {
                            "account_id": account_id,
                            "marketplace": marketplace,
                            "channel": channel,
                            "scope": channel,
                            "error": str(exc),
                        }
                        errors.append(details)
                        self.repository.log_review_action(
                            user_id=user_id,
                            review_uid=None,
                            action_type="sync_error",
                            actor="system",
                            details=details,
                        )
                        channel_outcomes[channel] = {
                            "ok": False,
                            "loaded": 0,
                            "error": str(exc),
                            "access_denied": False,
                        }
                if was_cancelled:
                    break

                account_loaded_reviews = int((channel_outcomes.get("reviews") or {}).get("loaded") or 0)
                account_loaded_questions = int((channel_outcomes.get("questions") or {}).get("loaded") or 0)
                account_loaded_chats = int((channel_outcomes.get("chats") or {}).get("loaded") or 0)
                loaded_total += account_loaded_reviews
                loaded_questions += account_loaded_questions
                loaded_chats += account_loaded_chats
                loaded_conversations = loaded_questions + loaded_chats

                account_success = any(
                    bool((channel_outcomes.get(name) or {}).get("ok")) for name in ("reviews", "questions", "chats")
                )
                if account_success:
                    successful_accounts += 1

                account_channel_stats.append(
                    {
                        "account_id": account_id,
                        "marketplace": marketplace,
                        "reviews": channel_outcomes.get("reviews") or {"ok": False, "loaded": 0},
                        "questions": channel_outcomes.get("questions") or {"ok": False, "loaded": 0},
                        "chats": channel_outcomes.get("chats") or {"ok": False, "loaded": 0},
                    }
                )
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
            "loaded_reviews": loaded_total,
            "loaded_questions": loaded_questions,
            "loaded_chats": loaded_chats,
            "loaded_conversations": loaded_conversations,
            "account_ids": selected_account_ids,
            "skipped_accounts": skipped_accounts,
            "errors": errors,
            "capability_warnings": capability_warnings,
            "account_channel_stats": account_channel_stats,
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
                questions_path=str(extra.get("questions_path") or "/api/v1/questions"),
                chats_path=str(extra.get("chats_path") or "/api/v1/seller/chats"),
                chats_api_url=str(extra.get("chats_api_url") or "https://buyer-chat-api.wildberries.ru"),
                chats_events_path=str(extra.get("chats_events_path") or "/api/v1/seller/events"),
                _resume_events_cursor=str(extra["_wb_events_cursor"]) if extra.get("_wb_events_cursor") else None,
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
        account_ids: list[int] | None = None,
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
            account_ids=account_ids,
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
        account_ids: list[int] | None = None,
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
            account_ids=account_ids,
        )

    def list_review_sources(self, *, user_id: int) -> list[str]:
        return self.repository.list_review_sources(user_id=user_id)

    def apply_processing_rules_to_unprocessed(self, *, user_id: int) -> dict[str, int]:
        rows = self.repository.list_unprocessed_reviews(user_id=user_id)
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
            mode, auto_send, _template_text = self._resolve_processing_mode(processed, None, rule)
            if mode == "template":
                group_template = self._pick_group_template_text(
                    user_id=user_id,
                    category=category,
                    review=review,
                    sentiment=sentiment,
                )
                template = self.repository.get_template(user_id=user_id, category=category)
                template_text = ""
                if template and bool(template.get("is_enabled")):
                    template_text = str(template.get("template_text") or "").strip()
                selected_template = str(group_template or template_text).strip()
                if not selected_template:
                    self.repository.log_review_action(
                        user_id=user_id,
                        review_uid=review_uid,
                        action_type="send_reply_error",
                        actor="system",
                        details={
                            "source": str(row.get("source") or ""),
                            "account_id": int(row["account_id"]) if row.get("account_id") is not None else None,
                            "error": "Не найден шаблон для автоматического ответа",
                        },
                    )
                    if self.repository.update_review_processing_result(
                        user_id=user_id,
                        review_uid=review_uid,
                        status="queued_for_operator",
                        auto_reply=None,
                    ):
                        queued += 1
                        updated += 1
                    continue
                reply = self._render_template(
                    selected_template,
                    user_id=user_id,
                    review=review,
                    category=category,
                    sentiment=sentiment,
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

    def _send_conversation_reply_via_client(
        self,
        *,
        client: object,
        source: str,
        conversation: dict[str, object],
        response_text: str,
    ) -> tuple[bool, str | None]:
        sender = getattr(client, "send_conversation_reply", None)
        if not callable(sender):
            # Backward compatibility: clients without conversation reply API
            # should not break manual workflow.
            return True, None
        try:
            try:
                sent = sender(conversation=conversation, response_text=response_text)
            except TypeError:
                sent = sender(conversation, response_text)
        except MarketplaceSyncError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, str(exc)
        if sent is False:
            return False, f"{source}: маркетплейс не подтвердил отправку ответа в диалог"
        return True, None

    def send_conversation_reply(
        self,
        *,
        user_id: int,
        conversation_uid: str,
        response_text: str,
        operator_name: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        conversation = self.repository.get_conversation(user_id=user_id, conversation_uid=conversation_uid)
        if conversation is None:
            raise KeyError("Диалог не найден")
        source = str(conversation.get("source") or "").strip().lower()
        account_id = conversation.get("account_id")
        clean_text = str(response_text or "").strip()
        if not clean_text:
            raise ValueError("Текст ответа не может быть пустым")
        clean_idempotency = str(idempotency_key or "").strip()
        if not clean_idempotency:
            raise ValueError("idempotency_key обязателен")

        existing = self.repository.get_conversation_message_by_idempotency(
            user_id=user_id,
            conversation_uid=conversation_uid,
            idempotency_key=clean_idempotency,
        )
        if existing is not None and str(existing.get("send_status") or "").strip().lower() == "sent":
            return {"ok": True, "status": "sent", "deduplicated": True}

        self.repository.upsert_conversation_outbound_message(
            user_id=user_id,
            conversation_uid=conversation_uid,
            message_text=clean_text,
            operator_name=operator_name,
            idempotency_key=clean_idempotency,
        )

        account_id_value: int | None = None
        try:
            if account_id is not None:
                account_id_value = int(account_id)
        except (TypeError, ValueError):
            account_id_value = None

        if source not in {"wb", "ozon"} or account_id_value is None:
            self.repository.mark_conversation_message_send_success(
                user_id=user_id,
                conversation_uid=conversation_uid,
                idempotency_key=clean_idempotency,
            )
            self.repository.log_review_action(
                user_id=user_id,
                review_uid=conversation_uid,
                action_type="conversation_send_success",
                actor=operator_name,
                details={"source": source, "idempotency_key": clean_idempotency, "scope": "conversations"},
            )
            return {"ok": True, "status": "sent", "deduplicated": False}

        account = self.repository.get_marketplace_account(
            user_id=user_id,
            account_id=account_id_value,
            include_secrets=True,
        )
        if account is None:
            error_message = "Кабинет маркетплейса для диалога не найден"
            self.repository.mark_conversation_message_send_failure(
                user_id=user_id,
                conversation_uid=conversation_uid,
                idempotency_key=clean_idempotency,
                error_code="account_not_found",
                error_message=error_message,
            )
            self.repository.log_review_action(
                user_id=user_id,
                review_uid=conversation_uid,
                action_type="conversation_send_error",
                actor=operator_name,
                details={
                    "source": source,
                    "error_code": "account_not_found",
                    "error": error_message,
                    "idempotency_key": clean_idempotency,
                    "scope": "conversations",
                },
            )
            return {"ok": False, "status": "failed", "error": error_message}

        client = self._build_client(account)
        # For WB chats: refresh replySign from /seller/chats before sending
        # because replySign changes over time and stale values cause auth errors.
        conversation_with_fresh_sign = dict(conversation)
        if source == "wb" and hasattr(client, "_fetch_fresh_reply_sign"):
            try:
                fresh_sign = client._fetch_fresh_reply_sign(  # type: ignore[attr-defined]
                    chat_id=str(conversation.get("external_conversation_id") or ""),
                )
                if fresh_sign:
                    meta = dict(conversation.get("metadata") or {})
                    raw = dict(meta.get("raw") or {})
                    raw["replySign"] = fresh_sign
                    meta["raw"] = raw
                    conversation_with_fresh_sign["metadata"] = meta
            except Exception:
                pass
        sent, send_error = self._send_conversation_reply_via_client(
            client=client,
            source=source,
            conversation=conversation_with_fresh_sign,
            response_text=clean_text,
        )
        if sent:
            self.repository.mark_conversation_message_send_success(
                user_id=user_id,
                conversation_uid=conversation_uid,
                idempotency_key=clean_idempotency,
            )
            self.repository.log_review_action(
                user_id=user_id,
                review_uid=conversation_uid,
                action_type="conversation_send_success",
                actor=operator_name,
                details={"source": source, "idempotency_key": clean_idempotency, "scope": "conversations"},
            )
            return {"ok": True, "status": "sent", "deduplicated": False}

        error_text = send_error or "Не удалось отправить ответ в диалог"
        self.repository.mark_conversation_message_send_failure(
            user_id=user_id,
            conversation_uid=conversation_uid,
            idempotency_key=clean_idempotency,
            error_code="send_failed",
            error_message=error_text,
        )
        self.repository.log_review_action(
            user_id=user_id,
            review_uid=conversation_uid,
            action_type="conversation_send_error",
            actor=operator_name,
            details={
                "source": source,
                "error_code": "send_failed",
                "error": error_text,
                "idempotency_key": clean_idempotency,
                "scope": "conversations",
            },
        )
        return {"ok": False, "status": "failed", "error": error_text}

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

    def queue_for_manual_processing_with_actor(
        self,
        *,
        actor_email: str,
        owner_user_id: int,
        review_uid: str,
    ) -> bool:
        updated = self.repository.mark_manual_queue(user_id=owner_user_id, review_uid=review_uid)
        if updated:
            self.repository.log_review_action(
                user_id=owner_user_id,
                review_uid=review_uid,
                action_type="queue_manual",
                actor=actor_email,
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

    def save_manual_reply_with_actor(
        self,
        *,
        actor_email: str,
        owner_user_id: int,
        review_uid: str,
        response_text: str,
    ) -> bool:
        updated = self.repository.mark_manual_replied(
            user_id=owner_user_id,
            review_uid=review_uid,
            operator_name=actor_email,
            response_text=response_text,
        )
        if updated:
            self.repository.log_review_action(
                user_id=owner_user_id,
                review_uid=review_uid,
                action_type="manual_reply",
                actor=actor_email,
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
        preferred_subgroup: str | None = None,
    ) -> str | None:
        group_id = self._resolve_template_group_id(category=category, review=review, sentiment=sentiment)
        if not group_id:
            return None
        subgroup = str(preferred_subgroup or "").strip() or self._resolve_template_subgroup(
            group_id=group_id,
            category=category,
            review=review,
        )
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

    @classmethod
    def _resolve_template_subgroup(cls, *, group_id: str, category: str, review: ReviewInput) -> str | None:
        metadata = review.metadata if isinstance(review.metadata, dict) else {}
        classified_subgroup = str(metadata.get("classified_subgroup") or "").strip()
        if classified_subgroup:
            return classified_subgroup
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
                return ReviewAutomationService.TEXTLESS_LOW_SUBGROUP
            return ReviewAutomationService.TEXTLESS_HIGH_SUBGROUP
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
        if normalized in {
            "positive",
            "product_dissatisfaction",
            "delivery_problems",
            "wrong_size",
            "tagged_reviews",
            "textless_ratings",
        }:
            return normalized
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

    @staticmethod
    def _review_has_media(review: ReviewInput) -> bool:
        metadata = review.metadata if isinstance(review.metadata, dict) else {}

        def _has_media(value: object) -> bool:
            if isinstance(value, str):
                text = value.strip().lower()
                if not text:
                    return False
                markers = ("http://", "https://", ".jpg", ".jpeg", ".png", ".webp", ".gif", "photo", "image", "картин")
                return any(marker in text for marker in markers)
            if isinstance(value, list):
                return any(_has_media(item) for item in value)
            if isinstance(value, Mapping):
                for key, nested in value.items():
                    key_text = str(key).lower()
                    if any(marker in key_text for marker in ("photo", "image", "media", "pictures", "gallery", "фото")):
                        if _has_media(nested):
                            return True
                    if _has_media(nested):
                        return True
                return False
            return False

        return _has_media(metadata)

    def _classify_category_and_subgroup(
        self,
        review: ReviewInput,
        processed: object,
        *,
        settings: dict[str, object],
        user_id: int | None = None,
    ) -> tuple[str, str | None]:
        has_text = bool((review.text or "").strip())
        has_media = self._review_has_media(review)

        # Отзывы без текста и без вложений не отправляем в Яндекс:
        # категория и подгруппа определяются только по оценке.
        if not has_text and not has_media:
            rating = review.rating if review.rating is not None else 0
            subgroup = self.TEXTLESS_LOW_SUBGROUP if rating <= 3 else self.TEXTLESS_HIGH_SUBGROUP
            return self.TEXTLESS_GROUP_ID, subgroup

        # Для отзывов с текстом или вложениями обязательно используем Яндекс.
        if user_id is None:
            classified = self._classify_with_yandex(
                review,
                settings=settings,
                strict=True,
                allowed_groups=list(self.REVIEW_GROUP_TITLES.keys()),
            )
            if classified:
                return classified, None
            raise MarketplaceSyncError(
                "yandex",
                "Не удалось определить категорию отзыва через Яндекс. Проверьте настройки и доступность API.",
                details={"scope": "classification", "has_media": has_media, "queue_manual": True},
            )
        return self._classify_with_yandex_target(review=review, settings=settings, user_id=user_id, strict=False)

    def _classify_category(
        self,
        review: ReviewInput,
        processed: object,
        *,
        settings: dict[str, object],
    ) -> str:
        category, _subgroup = self._classify_category_and_subgroup(
            review,
            processed,
            settings=settings,
            user_id=None,
        )
        return category

    @classmethod
    def _is_general_subgroup_for_group(cls, *, group_id: str, subgroup: str) -> bool:
        clean_group = str(group_id or "").strip()
        clean_subgroup = cls._normalize_subgroup_name(subgroup)
        return (
            clean_group in cls.REVIEW_GROUPS_WITH_GENERAL_SUBGROUP
            and clean_subgroup == cls._normalize_subgroup_name(cls.GENERAL_SUBGROUP_TITLE)
        )

    @classmethod
    def _ensure_general_subgroup_first(
        cls,
        *,
        group_id: str,
        subgroup_items: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        clean_group = str(group_id or "").strip()
        if clean_group not in cls.REVIEW_GROUPS_WITH_GENERAL_SUBGROUP:
            return list(subgroup_items)
        result: list[dict[str, str]] = []
        general_row: dict[str, str] | None = None
        for item in subgroup_items:
            subgroup_title = str(item.get("subgroup") or "").strip()
            subgroup_id = str(item.get("subgroup_id") or "").strip()
            if not subgroup_title:
                continue
            resolved_id = subgroup_id or cls._build_subgroup_id(clean_group, subgroup_title)
            normalized_row = {"subgroup_id": resolved_id, "subgroup": subgroup_title}
            if cls._is_general_subgroup_for_group(group_id=clean_group, subgroup=subgroup_title):
                if general_row is None:
                    general_row = normalized_row
                continue
            result.append(normalized_row)
        if general_row is None:
            general_row = {
                "subgroup_id": cls._build_subgroup_id(clean_group, cls.GENERAL_SUBGROUP_TITLE),
                "subgroup": cls.GENERAL_SUBGROUP_TITLE,
            }
        return [general_row, *result]

    @staticmethod
    def _normalize_subgroup_name(value: str) -> str:
        return " ".join(str(value or "").strip().lower().split())

    @classmethod
    def _build_subgroup_id(cls, group_id: str, subgroup: str) -> str:
        clean_group = str(group_id or "").strip().lower().replace(" ", "_").replace("-", "_")
        normalized_subgroup = cls._normalize_subgroup_name(subgroup)
        digest = hashlib.sha1(f"{clean_group}|{normalized_subgroup}".encode("utf-8")).hexdigest()[:12]
        return f"{clean_group}__{digest}"

    @classmethod
    def _list_group_subgroups_for_review_classification(
        cls,
        *,
        repository: ReviewRepository,
        user_id: int,
    ) -> list[dict[str, object]]:
        allowed_group_ids = set(cls.REVIEW_GROUP_TITLES.keys())
        subgroup_items_by_group: dict[str, list[dict[str, str]]] = {group_id: [] for group_id in allowed_group_ids}
        seen_by_group: dict[str, set[str]] = {group_id: set() for group_id in allowed_group_ids}

        def _push(group_id: str, subgroup: str) -> None:
            clean_group = str(group_id or "").strip()
            clean_subgroup = str(subgroup or "").strip()
            if clean_group not in allowed_group_ids or not clean_subgroup:
                return
            normalized = cls._normalize_subgroup_name(clean_subgroup)
            if normalized in seen_by_group[clean_group]:
                return
            seen_by_group[clean_group].add(normalized)
            subgroup_items_by_group[clean_group].append(
                {
                    "subgroup_id": cls._build_subgroup_id(clean_group, clean_subgroup),
                    "subgroup": clean_subgroup,
                }
            )

        default_registry_rows = repository.list_default_template_subgroups()
        has_stored_subgroup_ids = any(str(row.get("subgroup_id") or "").strip() for row in default_registry_rows)
        if default_registry_rows and has_stored_subgroup_ids:
            for row in default_registry_rows:
                clean_group = str(row.get("group_id") or "").strip()
                clean_subgroup = str(row.get("subgroup") or "").strip()
                if clean_group not in allowed_group_ids or not clean_subgroup:
                    continue
                normalized = cls._normalize_subgroup_name(clean_subgroup)
                if normalized in seen_by_group[clean_group]:
                    continue
                seen_by_group[clean_group].add(normalized)
                stored_subgroup_id = str(row.get("subgroup_id") or "").strip()
                subgroup_items_by_group[clean_group].append(
                    {
                        "subgroup_id": stored_subgroup_id or cls._build_subgroup_id(clean_group, clean_subgroup),
                        "subgroup": clean_subgroup,
                    }
                )
        else:
            # Fallback for fresh installations before subgroup registry is initialized.
            for group_id, defaults in cls.REVIEW_GROUP_DEFAULT_SUBGROUPS.items():
                for subgroup in defaults:
                    _push(group_id, subgroup)

        # Закрепленная структура для отзывов без текста.
        subgroup_items_by_group[cls.TEXTLESS_GROUP_ID] = [
            {
                "subgroup_id": cls._build_subgroup_id(cls.TEXTLESS_GROUP_ID, cls.TEXTLESS_LOW_SUBGROUP),
                "subgroup": cls.TEXTLESS_LOW_SUBGROUP,
            },
            {
                "subgroup_id": cls._build_subgroup_id(cls.TEXTLESS_GROUP_ID, cls.TEXTLESS_HIGH_SUBGROUP),
                "subgroup": cls.TEXTLESS_HIGH_SUBGROUP,
            },
        ]

        items: list[dict[str, object]] = []
        ordered_group_ids = [
            "positive",
            "product_dissatisfaction",
            "delivery_problems",
            "wrong_size",
            "tagged_reviews",
            cls.TEXTLESS_GROUP_ID,
        ]
        for group_id in ordered_group_ids:
            subgroup_items = list(subgroup_items_by_group.get(group_id) or [])
            if group_id != cls.TEXTLESS_GROUP_ID and not subgroup_items:
                continue
            subgroup_items = cls._ensure_general_subgroup_first(group_id=group_id, subgroup_items=subgroup_items)
            items.append(
                {
                    "group_id": group_id,
                    "group_title": cls.REVIEW_GROUP_TITLES.get(group_id, group_id),
                    "subgroup_items": subgroup_items,
                    "subgroups": [str(item.get("subgroup") or "") for item in subgroup_items if str(item.get("subgroup") or "")],
                }
            )
        return items

    @classmethod
    def _parse_yandex_target_response(
        cls,
        raw_text: str,
        *,
        options: list[dict[str, object]],
    ) -> dict[str, str] | None:
        response = str(raw_text or "").strip()
        if not response:
            return None
        normalized_response = response.lower()
        group_aliases: dict[str, str] = {}
        subgroup_ids_by_group: dict[str, dict[str, str]] = {}
        subgroup_titles_by_group: dict[str, dict[str, str]] = {}
        for item in options:
            group_id = str(item.get("group_id") or "").strip()
            group_title = str(item.get("group_title") or "").strip()
            if not group_id:
                continue
            group_aliases[group_id.lower()] = group_id
            if group_title:
                group_aliases[group_title.lower()] = group_id
            id_map: dict[str, str] = {}
            title_map: dict[str, str] = {}
            subgroup_items_raw = item.get("subgroup_items")
            subgroup_items: list[dict[str, str]] = []
            if isinstance(subgroup_items_raw, list) and subgroup_items_raw:
                for subgroup_item in subgroup_items_raw:
                    if not isinstance(subgroup_item, Mapping):
                        continue
                    subgroup_id = str(subgroup_item.get("subgroup_id") or "").strip()
                    subgroup_title = str(subgroup_item.get("subgroup") or subgroup_item.get("subgroup_title") or "").strip()
                    if not subgroup_id or not subgroup_title:
                        continue
                    subgroup_items.append({"subgroup_id": subgroup_id, "subgroup": subgroup_title})
            if not subgroup_items:
                for subgroup_title in item.get("subgroups") or []:
                    clean_subgroup = str(subgroup_title or "").strip()
                    if not clean_subgroup:
                        continue
                    subgroup_items.append(
                        {
                            "subgroup_id": cls._build_subgroup_id(group_id, clean_subgroup),
                            "subgroup": clean_subgroup,
                        }
                    )
            for subgroup_item in subgroup_items:
                subgroup_id = str(subgroup_item.get("subgroup_id") or "").strip()
                subgroup_title = str(subgroup_item.get("subgroup") or "").strip()
                if not subgroup_id or not subgroup_title:
                    continue
                id_map[subgroup_id.lower()] = subgroup_title
                title_map[cls._normalize_subgroup_name(subgroup_title)] = subgroup_title
            subgroup_ids_by_group[group_id] = id_map
            subgroup_titles_by_group[group_id] = title_map

        def _detect_group(candidate: str) -> str | None:
            clean = str(candidate or "").strip().lower()
            if not clean:
                return None
            if clean in group_aliases:
                return group_aliases[clean]
            normalized_clean = clean.replace(" ", "_").replace("-", "_")
            if normalized_clean in group_aliases:
                return group_aliases[normalized_clean]
            for alias, group in group_aliases.items():
                if alias and alias in clean:
                    return group
            return None

        def _detect_subgroup(group_id: str, candidate: str) -> tuple[str, str] | None:
            id_map = subgroup_ids_by_group.get(group_id) or {}
            title_map = subgroup_titles_by_group.get(group_id) or {}
            if not id_map and not title_map:
                return None
            raw_candidate = str(candidate or "").strip()
            clean = raw_candidate.lower()
            if clean in id_map:
                subgroup_title = id_map[clean]
                return clean, subgroup_title
            normalized_candidate = clean.replace(" ", "_").replace("-", "_")
            if normalized_candidate in id_map:
                subgroup_title = id_map[normalized_candidate]
                return normalized_candidate, subgroup_title
            normalized_title_candidate = cls._normalize_subgroup_name(raw_candidate)
            if normalized_title_candidate and normalized_title_candidate in title_map:
                subgroup_title = title_map[normalized_title_candidate]
                return cls._build_subgroup_id(group_id, subgroup_title), subgroup_title
            lowered_candidate = str(candidate or "").strip().lower()
            for subgroup_id, subgroup_title in id_map.items():
                if subgroup_id and subgroup_id in lowered_candidate:
                    return cls._build_subgroup_id(group_id, subgroup_title), subgroup_title
            for normalized_title, subgroup_title in title_map.items():
                if normalized_title and normalized_title in cls._normalize_subgroup_name(lowered_candidate):
                    return cls._build_subgroup_id(group_id, subgroup_title), subgroup_title
            return None

        def _to_result(group_id: str, subgroup_id: str, subgroup_title: str) -> dict[str, str]:
            return {
                "group_id": group_id,
                "subgroup_id": subgroup_id,
                "subgroup": subgroup_title,
            }

        parsed_object: dict[str, object] | None = None
        try:
            maybe = json.loads(response)
            if isinstance(maybe, Mapping):
                parsed_object = dict(maybe)
        except Exception:
            pass
        if parsed_object is None:
            json_match = re.search(r"\{.*\}", response, flags=re.DOTALL)
            if json_match:
                try:
                    maybe_nested = json.loads(json_match.group(0))
                    if isinstance(maybe_nested, Mapping):
                        parsed_object = dict(maybe_nested)
                except Exception:
                    parsed_object = None
        if parsed_object is not None:
            group_candidate = str(
                parsed_object.get("group_id")
                or parsed_object.get("group")
                or parsed_object.get("category")
                or ""
            ).strip()
            subgroup_candidate = str(
                parsed_object.get("subgroup_id")
                or parsed_object.get("subgroup")
                or parsed_object.get("subcategory")
                or ""
            ).strip()
            detected_group = _detect_group(group_candidate)
            if detected_group:
                if subgroup_candidate:
                    detected_subgroup = _detect_subgroup(detected_group, subgroup_candidate)
                    if detected_subgroup:
                        return _to_result(detected_group, detected_subgroup[0], detected_subgroup[1])
                    return {"group_id": detected_group, "subgroup_id": "", "subgroup": ""}
                return {"group_id": detected_group, "subgroup_id": "", "subgroup": ""}

        group_match = re.search(r"group[_\s-]*id\s*[:=]\s*([a-z0-9_:-]+)", normalized_response)
        subgroup_match = re.search(r"subgroup[_\s-]*id\s*[:=]\s*([a-z0-9_:-]+)", normalized_response)
        if group_match and subgroup_match:
            detected_group = _detect_group(group_match.group(1))
            if detected_group:
                detected_subgroup = _detect_subgroup(detected_group, subgroup_match.group(1))
                if detected_subgroup:
                    return _to_result(detected_group, detected_subgroup[0], detected_subgroup[1])

        for separator in ("|", "/", ";"):
            if separator not in response:
                continue
            left, right = response.split(separator, 1)
            detected_group = _detect_group(left)
            if detected_group:
                detected_subgroup = _detect_subgroup(detected_group, right)
                if detected_subgroup:
                    return _to_result(detected_group, detected_subgroup[0], detected_subgroup[1])

        best_group: str | None = None
        for alias, group_id in group_aliases.items():
            if alias and alias in normalized_response:
                best_group = group_id
                break
        if not best_group:
            return None
        detected_subgroup = _detect_subgroup(best_group, response)
        if not detected_subgroup:
            return None
        return _to_result(best_group, detected_subgroup[0], detected_subgroup[1])

    def _classify_with_yandex_target(
        self,
        *,
        review: ReviewInput,
        settings: dict[str, object],
        user_id: int,
        strict: bool = False,
    ) -> tuple[str, str | None]:
        result = self._classify_with_yandex_target_debug(
            review=review,
            settings=settings,
            user_id=user_id,
            strict=strict,
        )
        return (
            str(result.get("group_id") or "").strip(),
            str(result.get("subgroup") or "").strip() or None,
        )

    @classmethod
    def _default_subgroup_for_group(cls, group_id: str, options: list[dict[str, object]]) -> dict[str, str] | None:
        clean_group_id = str(group_id or "").strip()
        if not clean_group_id or clean_group_id not in cls.REVIEW_GROUPS_WITH_GENERAL_SUBGROUP:
            return None
        for item in options:
            candidate_group_id = str(item.get("group_id") or "").strip()
            if candidate_group_id != clean_group_id:
                continue
            subgroup_items = item.get("subgroup_items")
            if not isinstance(subgroup_items, list):
                continue
            for subgroup_item in subgroup_items:
                if not isinstance(subgroup_item, Mapping):
                    continue
                subgroup_title = str(subgroup_item.get("subgroup") or subgroup_item.get("subgroup_title") or "").strip()
                subgroup_id = str(subgroup_item.get("subgroup_id") or "").strip()
                if cls._normalize_subgroup_name(subgroup_title) != cls._normalize_subgroup_name(cls.GENERAL_SUBGROUP_TITLE):
                    continue
                if subgroup_id:
                    return {"subgroup_id": subgroup_id, "subgroup": subgroup_title}
                return {
                    "subgroup_id": cls._build_subgroup_id(clean_group_id, subgroup_title),
                    "subgroup": subgroup_title,
                }
        return None

    def _classify_with_yandex_target_debug(
        self,
        *,
        review: ReviewInput,
        settings: dict[str, object],
        user_id: int,
        strict: bool = False,
    ) -> dict[str, object]:
        api_key = str(settings.get("yandex_api_key") or "")
        folder_id = str(settings.get("yandex_folder_id") or "")
        model_uri = str(settings.get("yandex_model_uri") or "")
        if not api_key or not folder_id:
            if strict:
                raise MarketplaceSyncError(
                    "yandex",
                    "Яндекс-классификатор не настроен: укажите ключ API и идентификатор каталога.",
                    details={"scope": "classification"},
                )
            return {"group_id": "", "subgroup_id": "", "subgroup": None, "raw_response": "", "model_uri": model_uri}
        if not model_uri:
            model_uri = f"gpt://{folder_id}/yandexgpt-lite/latest"

        options = self._list_group_subgroups_for_review_classification(repository=self.repository, user_id=user_id)
        options_for_prompt = [item for item in options if str(item.get("group_id") or "") != self.TEXTLESS_GROUP_ID]
        if not options_for_prompt:
            if strict:
                raise MarketplaceSyncError(
                    "yandex",
                    "Не удалось сформировать список групп/подгрупп для классификации.",
                    details={"scope": "classification"},
                )
            return {"group_id": "", "subgroup_id": "", "subgroup": None, "raw_response": "", "model_uri": model_uri}

        options_lines: list[str] = []
        allowed_pairs: list[dict[str, str]] = []
        for item in options_for_prompt:
            group_id = str(item.get("group_id") or "")
            group_title = str(item.get("group_title") or group_id)
            subgroup_items_raw = item.get("subgroup_items")
            subgroup_items: list[dict[str, str]] = []
            if isinstance(subgroup_items_raw, list):
                for subgroup_item in subgroup_items_raw:
                    if not isinstance(subgroup_item, Mapping):
                        continue
                    subgroup_id = str(subgroup_item.get("subgroup_id") or "").strip()
                    subgroup_title = str(subgroup_item.get("subgroup") or subgroup_item.get("subgroup_title") or "").strip()
                    if not subgroup_id or not subgroup_title:
                        continue
                    subgroup_items.append({"subgroup_id": subgroup_id, "subgroup": subgroup_title})
            if not subgroup_items:
                continue
            options_lines.append(f"- {group_id} ({group_title}):")
            for subgroup_item in subgroup_items:
                subgroup_id = str(subgroup_item.get("subgroup_id") or "").strip()
                subgroup_title = str(subgroup_item.get("subgroup") or "").strip()
                if not subgroup_id or not subgroup_title:
                    continue
                allowed_pairs.append(
                    {
                        "group_id": group_id,
                        "group_title": group_title,
                        "subgroup_id": subgroup_id,
                        "subgroup": subgroup_title,
                    }
                )
                options_lines.append(
                    f"  - {subgroup_id}: {subgroup_title}"
                )
        prompt = (
            "Определи одну категорию и одну подгруппу для отзыва.\n"
            f"Отзыв: {review.text or '(без текста)'}\n"
            f"Оценка: {review.rating if review.rating is not None else 'unknown'}\n"
            "Список допустимых вариантов group_id/subgroup_id:\n"
            f"{chr(10).join(options_lines)}\n"
            "Ответ строго в JSON-формате без пояснений: "
            '{"group_id":"<group_id>","subgroup_id":"<subgroup_id>"}.\n'
            "Нельзя возвращать значения, которых нет в списке."
        )

        body = {
            "modelUri": model_uri,
            "completionOptions": {"stream": False, "temperature": 0.0, "maxTokens": 80},
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
        except MarketplaceSyncError as exc:
            if strict:
                raise MarketplaceSyncError(
                    "yandex",
                    f"Ошибка запроса к Яндекс-классификатору: {exc}",
                    details={
                        "scope": "classification",
                        "model_uri": model_uri,
                        "expected_format": '{"group_id":"<group_id>","subgroup_id":"<subgroup_id>"}',
                        "allowed_pairs": allowed_pairs,
                        "prompt_preview": prompt[:8000],
                    },
                ) from exc
            return {"group_id": "", "subgroup_id": "", "subgroup": None, "raw_response": "", "model_uri": model_uri}

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

        raw_response = str(text or "").strip()
        parsed = self._parse_yandex_target_response(text, options=options_for_prompt)
        if parsed:
            group_id = str(parsed.get("group_id") or "").strip()
            subgroup_id = str(parsed.get("subgroup_id") or "").strip()
            subgroup_title = str(parsed.get("subgroup") or "").strip()
            if group_id and subgroup_id and subgroup_title:
                return {
                    "group_id": group_id,
                    "subgroup_id": subgroup_id,
                    "subgroup": subgroup_title,
                    "raw_response": raw_response,
                    "model_uri": model_uri,
                }
            if group_id:
                default_subgroup = self._default_subgroup_for_group(group_id, options_for_prompt)
                if default_subgroup:
                    return {
                        "group_id": group_id,
                        "subgroup_id": str(default_subgroup.get("subgroup_id") or ""),
                        "subgroup": str(default_subgroup.get("subgroup") or ""),
                        "raw_response": raw_response,
                        "model_uri": model_uri,
                        "used_default_subgroup": True,
                        "default_subgroup_reason": "missing_or_invalid_subgroup",
                    }
        if strict:
            raise MarketplaceSyncError(
                "yandex",
                "Яндекс-классификатор вернул ответ без корректной группы/подгруппы.",
                details={
                    "scope": "classification",
                    "raw_response": raw_response,
                    "model_uri": model_uri,
                    "expected_format": '{"group_id":"<group_id>","subgroup_id":"<subgroup_id>"}',
                    "allowed_pairs": allowed_pairs,
                    "prompt_preview": prompt[:8000],
                },
            )
        return {
            "group_id": "",
            "subgroup_id": "",
            "subgroup": None,
            "raw_response": raw_response,
            "model_uri": model_uri,
        }

    @staticmethod
    def _normalize_category(text: str, *, allowed_groups: list[str] | None = None) -> str | None:
        allowed = {str(item).strip().lower() for item in (allowed_groups or []) if str(item).strip()}
        if not allowed:
            allowed = {
                "positive",
                "product_dissatisfaction",
                "delivery_problems",
                "wrong_size",
                "tagged_reviews",
                "textless_ratings",
            }
        aliases = {
            "negative_delivery": "delivery_problems",
            "negative_product": "product_dissatisfaction",
            "negative_other": "product_dissatisfaction",
            "positive_quality": "positive",
            "positive_product": "positive",
            "neutral_other": "product_dissatisfaction",
        }
        cleaned = text.strip().lower().replace(" ", "_").replace("-", "_")
        if cleaned in allowed:
            return cleaned
        if cleaned in aliases and aliases[cleaned] in allowed:
            return aliases[cleaned]
        for alias, mapped in aliases.items():
            if alias in cleaned and mapped in allowed:
                return mapped
        for group_id in allowed:
            if group_id in cleaned:
                return group_id
        return None

    def _classify_with_yandex(
        self,
        review: ReviewInput,
        *,
        settings: dict[str, object],
        strict: bool = False,
        allowed_groups: list[str] | None = None,
    ) -> str | None:
        api_key = str(settings.get("yandex_api_key") or "")
        folder_id = str(settings.get("yandex_folder_id") or "")
        model_uri = str(settings.get("yandex_model_uri") or "")
        if not api_key or not folder_id:
            if strict:
                raise MarketplaceSyncError(
                    "yandex",
                    "Яндекс-классификатор не настроен: укажите ключ API и идентификатор каталога.",
                    details={"scope": "classification"},
                )
            return None
        if not model_uri:
            model_uri = f"gpt://{folder_id}/yandexgpt-lite/latest"

        allowed = [str(item).strip() for item in (allowed_groups or list(self.GROUP_PROCESSING_DEFAULTS.keys())) if str(item).strip()]
        if not allowed:
            if strict:
                raise MarketplaceSyncError(
                    "yandex",
                    "Не заданы группы для Яндекс-классификатора.",
                    details={"scope": "classification"},
                )
            return None

        allowed_list = ", ".join(allowed)

        prompt = (
            "Классифицируй отзыв строго одной группой из списка: "
            f"{allowed_list}.\n"
            f"Отзыв: {review.text}\n"
            f"Оценка: {review.rating if review.rating is not None else 'unknown'}\n"
            "Ответ верни только id группы из списка, без комментариев."
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
        except MarketplaceSyncError as exc:
            if strict:
                raise MarketplaceSyncError(
                    "yandex",
                    f"Ошибка запроса к Яндекс-классификатору: {exc}",
                    details={"scope": "classification"},
                ) from exc
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
        normalized = self._normalize_category(text, allowed_groups=allowed)
        if normalized:
            return normalized
        if strict:
            raise MarketplaceSyncError(
                "yandex",
                "Яндекс-классификатор вернул ответ без корректной категории.",
                details={"scope": "classification", "raw_response": text[:120]},
            )
        return None

    def check_yandex_connection(
        self,
        *,
        api_key: str,
        folder_id: str,
        timeout_seconds: int = 12,
    ) -> dict[str, object]:
        clean_api_key = str(api_key or "").strip()
        clean_folder_id = str(folder_id or "").strip()
        if not clean_api_key:
            raise MarketplaceSyncError("yandex", "Укажите API-ключ Yandex Cloud.")
        if not clean_folder_id:
            raise MarketplaceSyncError("yandex", "Укажите ID каталога (folderId).")
        model_uri = f"gpt://{clean_folder_id}/yandexgpt-lite/latest"
        body = {
            "modelUri": model_uri,
            "completionOptions": {"stream": False, "temperature": 0.0, "maxTokens": 8},
            "messages": [{"role": "user", "text": "Ответь одним словом: OK"}],
        }
        request = Request(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            method="POST",
            headers={
                "Authorization": f"Api-Key {clean_api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(body).encode("utf-8"),
        )
        payload = _request_json(request=request, timeout=max(int(timeout_seconds), 1), source="yandex", retries=0)
        result = payload.get("result") if isinstance(payload, Mapping) else None
        alternatives = result.get("alternatives") if isinstance(result, Mapping) else None
        first = alternatives[0] if isinstance(alternatives, list) and alternatives else {}
        message = first.get("message") if isinstance(first, Mapping) else {}
        text = str(message.get("text") or "").strip() if isinstance(message, Mapping) else ""
        return {
            "ok": True,
            "message": "Подключение к Yandex GPT успешно.",
            "model_uri": model_uri,
            "response_preview": text[:120],
        }

    def classify_test_review_with_yandex(
        self,
        *,
        user_id: int,
        review_text: str,
        review_rating: int | None = None,
        settings: dict[str, object],
    ) -> dict[str, object]:
        clean_text = str(review_text or "").strip()
        if not clean_text:
            raise MarketplaceSyncError("yandex", "Введите текст тестового отзыва.")

        normalized_rating: int | None = None
        if review_rating is not None:
            try:
                normalized_rating = int(review_rating)
            except (TypeError, ValueError) as exc:
                raise MarketplaceSyncError("yandex", "Оценка тестового отзыва должна быть целым числом от 1 до 5.") from exc
            if normalized_rating < 1 or normalized_rating > 5:
                raise MarketplaceSyncError("yandex", "Оценка тестового отзыва должна быть от 1 до 5.")

        options = self._list_group_subgroups_for_review_classification(repository=self.repository, user_id=user_id)
        result = self._classify_with_yandex_target_debug(
            review=ReviewInput(
                review_id="admin-test-review",
                text=clean_text,
                rating=normalized_rating,
                metadata={"source": "admin_test"},
            ),
            settings=settings,
            user_id=user_id,
            strict=True,
        )
        group_id = str(result.get("group_id") or "").strip()
        subgroup_id = str(result.get("subgroup_id") or "").strip()
        subgroup = str(result.get("subgroup") or "").strip()
        if not group_id or not subgroup_id or not subgroup:
            raise MarketplaceSyncError("yandex", "Яндекс-классификатор не вернул корректную группу и подгруппу.")
        return {
            "ok": True,
            "group_id": group_id,
            "group_title": self.REVIEW_GROUP_TITLES.get(group_id, group_id),
            "subgroup_id": subgroup_id,
            "subgroup": subgroup,
            "used_default_subgroup": bool(result.get("used_default_subgroup")),
            "default_subgroup_reason": str(result.get("default_subgroup_reason") or ""),
            "model_uri": str(result.get("model_uri") or ""),
            "raw_response": str(result.get("raw_response") or ""),
            "available_options": options,
        }

    @classmethod
    def _resolve_group_processors(cls, settings: dict[str, object]) -> dict[str, str]:
        modes: dict[str, str] = dict(cls.GROUP_PROCESSING_DEFAULTS)
        raw = settings.get("group_processors")
        if isinstance(raw, Mapping):
            for key, value in raw.items():
                group_id = str(key or "").strip()
                mode = str(value or "").strip().lower()
                if not group_id:
                    continue
                if mode not in {"yandex", "program"}:
                    continue
                modes[group_id] = mode
        return modes

    def _classify_with_program_groups(
        self,
        *,
        review: ReviewInput,
        processed: object,
        allowed_groups: list[str],
    ) -> str | None:
        allowed = {str(item).strip() for item in allowed_groups if str(item).strip()}
        if not allowed:
            return None
        text = (review.text or "").lower()
        size_words = ("размер", "маломер", "большемер", "size", "мерит")
        delivery_words = ("доставк", "курьер", "пункт выдачи", "пвз")
        sentiment = str(getattr(processed, "sentiment_label", "")).strip().lower()

        if "wrong_size" in allowed and any(word in text for word in size_words):
            return "wrong_size"
        if "delivery_problems" in allowed and any(word in text for word in delivery_words):
            return "delivery_problems"
        if sentiment == "positive" and "positive" in allowed:
            return "positive"
        if "product_dissatisfaction" in allowed:
            return "product_dissatisfaction"
        if "positive" in allowed:
            return "positive"
        return next(iter(allowed), None)

    @staticmethod
    def _resolve_processing_mode(
        processed: object,
        template: dict[str, object] | None,
        rule: dict[str, object] | None,
    ) -> tuple[str, bool, str]:
        if rule:
            mode = str(rule.get("action_mode") or "manual").strip().lower()
            if mode in {"ai", "auto", "template", "ignore"}:
                return "template", True, ""
            if mode == "manual":
                return "manual", False, ""
        if template:
            mode = str(template.get("mode") or "manual")
            text = str(template.get("template_text") or "")
            is_enabled = bool(template.get("is_enabled"))
            if is_enabled and mode in {"auto", "template", "ignore"}:
                return "template", True, text
            if is_enabled and mode == "manual":
                return "manual", False, text
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
        variables_context = self.repository.build_template_variables_context(
            user_id=user_id,
            review_author=author_raw,
            review_rating=review.rating,
            review_category=category,
            review_sentiment=sentiment,
            review_tags=self._extract_review_tags(review),
            review_metadata=review.metadata if isinstance(review.metadata, dict) else {},
        )
        text = text.replace("%USER%", author_raw)
        text = text.replace("%RECO%", reco)
        text = text.replace("%%RECO%%", reco)
        for key, value in variables_context.items():
            text = text.replace(str(key), str(value or ""))
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


def _normalize_timestamp(value: object) -> str | None:
    """Convert a timestamp value to an ISO-8601 string.

    WB Buyer Chat API returns ``addTimestamp`` as Unix milliseconds (integer).
    Storing the raw integer as a string would break lexicographic comparisons
    used by the ``processed_by_operator`` SQL clause and date-range filters.
    This helper converts millisecond integers to ISO strings and passes through
    values that are already strings.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ts_sec = float(value)
        # Heuristic: values > 1e10 are milliseconds, not seconds
        if ts_sec > 1e10:
            ts_sec = ts_sec / 1000.0
        try:
            return datetime.fromtimestamp(ts_sec, tz=UTC).isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    raw = str(value).strip()
    if not raw:
        return None
    # If the string is a pure integer it may still be a unix timestamp
    if raw.lstrip("-").isdigit():
        try:
            ts_sec = float(raw)
            if ts_sec > 1e10:
                ts_sec = ts_sec / 1000.0
            return datetime.fromtimestamp(ts_sec, tz=UTC).isoformat()
        except (OSError, OverflowError, ValueError):
            pass
    return raw


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
    normalized_path = "/" + path.strip("/")
    parsed = urlparse(base_url)
    # If path starts with "/" treat it as absolute path from host root,
    # so we always replace the path component rather than appending to it.
    if path.startswith("/"):
        base_root = f"{parsed.scheme}://{parsed.netloc}"
        return base_root + normalized_path
    normalized_base = base_url.rstrip("/")
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
    """Execute an HTTP request and return the parsed JSON response.

    Retryable errors (network, timeout, JSON parse): up to ``retries`` retries
    with exponential backoff starting at 0.4 s.

    HTTP 429 Too Many Requests: retried with a mandatory 60-second wait so we
    respect marketplace rate-limit windows before trying again.  After
    ``retries`` 429 responses the error is re-raised so the caller can handle
    it gracefully (log as access-rate issue, not a hard failure).

    All other HTTP errors (4xx except 429, 5xx) are raised immediately.
    """
    attempt = 0
    rate_limit_attempt = 0
    while True:
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429:
                # Rate-limited: wait and retry up to ``retries`` times.
                rate_limit_attempt += 1
                if rate_limit_attempt > retries:
                    message = f"{source} HTTP error 429: rate limit exceeded"
                    raise MarketplaceSyncError(source, message) from exc
                # Back off: 60 s for the first hit, 120 s for the second.
                wait_sec = 60 * rate_limit_attempt
                time.sleep(wait_sec)
                continue
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
