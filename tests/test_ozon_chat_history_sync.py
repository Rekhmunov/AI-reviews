"""Ozon chat history: auto-sync selection and history mapping.

Does not import review_processor.web (fastapi is not installed in this env).
"""

import unittest

from review_processor.service import (
    OzonMarketplaceClient,
    _ozon_chat_timestamp,
    _ozon_user_kind,
    select_ozon_chats_for_history,
)


class OzonUserKindTests(unittest.TestCase):
    def test_cyrillic_es_in_customer_is_buyer(self) -> None:
        self.assertEqual(_ozon_user_kind("Сustomer"), "customer")
        self.assertEqual(_ozon_user_kind("Customer"), "customer")
        self.assertEqual(_ozon_user_kind("Seller"), "seller")

    def test_timestamp_z_matches_offset_form(self) -> None:
        self.assertEqual(
            _ozon_chat_timestamp("2026-09-19T10:00:00Z"),
            "2026-09-19T10:00:00+00:00",
        )


class SelectOzonChatsTests(unittest.TestCase):
    def test_unread_beats_bootstrap_when_capped(self) -> None:
        rows = [
            {"external_id": "old", "unread_count": 0},
            {"external_id": "new", "unread_count": 2},
        ]
        picked = select_ozon_chats_for_history(
            rows,
            {},
            max_calls=1,
            bootstrap_budget=80,
        )
        self.assertEqual([row["external_id"] for row in picked], ["new"])

    def test_stored_timestamp_is_not_bootstrapped(self) -> None:
        rows = [{"external_id": "known", "unread_count": 0}]
        picked = select_ozon_chats_for_history(
            rows,
            {"known": {"last_message_at": "2026-09-01T00:00:00+00:00"}},
        )
        self.assertEqual(picked, [])

    def test_missing_timestamp_is_bootstrapped_once(self) -> None:
        rows = [
            {"external_id": "fresh", "unread_count": 0},
            {"external_id": "stale", "unread_count": 0},
        ]
        picked = select_ozon_chats_for_history(
            rows,
            {},
            known_stale_ids={"stale"},
            bootstrap_budget=10,
        )
        self.assertEqual([row["external_id"] for row in picked], ["fresh"])

    def test_unread_stale_chat_is_still_fetched(self) -> None:
        rows = [{"external_id": "again", "unread_count": 1}]
        picked = select_ozon_chats_for_history(
            rows,
            {"again": {"last_message_at": "2026-01-01T00:00:00+00:00"}},
            known_stale_ids={"again"},
        )
        self.assertEqual([row["external_id"] for row in picked], ["again"])


class _HistoryClient(OzonMarketplaceClient):
    def __init__(self) -> None:
        super().__init__(
            api_url="https://api-seller.ozon.ru",
            client_id="cid",
            api_key="key",
            chats_path="/v3/chat/list",
            chats_history_path="/v3/chat/history",
        )
        self.calls: list[str] = []

    def _request_json(self, *, path: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(path)
        if path.endswith("/history"):
            return {
                "messages": [
                    {
                        "message_id": "m2",
                        "created_at": "2026-09-19T12:00:00Z",
                        "data": ["Где заказ?"],
                        "user": {"id": "55", "type": "Сustomer"},
                        "context": {"order_number": "100-1"},
                    },
                    {
                        "message_id": "m1",
                        "created_at": "2026-09-18T12:00:00Z",
                        "data": ["Здравствуйте"],
                        "user": {"id": "1", "type": "Seller"},
                    },
                ]
            }
        return {
            "chats": [
                {
                    "chat": {
                        "chat_id": "chat-1",
                        "chat_status": "OPENED",
                        "chat_type": "BUYER_SELLER",
                    },
                    "unread_count": 1,
                }
            ],
            "has_next": False,
        }


class OzonHistoryEnrichTests(unittest.TestCase):
    def test_list_only_does_not_call_history(self) -> None:
        client = _HistoryClient()
        rows = client.fetch_chats(enrich_with_events=False)
        self.assertEqual(client.calls, ["/v3/chat/list"])
        self.assertEqual(rows[0]["external_id"], "chat-1")
        self.assertFalse(rows[0].get("last_message_at"))
        self.assertFalse(str(rows[0].get("message_text") or "").strip())

    def test_history_sets_text_time_and_buyer_sender(self) -> None:
        client = _HistoryClient()
        rows = client.fetch_chats(enrich_with_events=True)
        self.assertIn("/v3/chat/history", client.calls)
        chat = rows[0]
        self.assertEqual(chat["last_sender"], "client")
        self.assertEqual(chat["last_message_at"], "2026-09-19T12:00:00+00:00")
        self.assertEqual(chat["message_text"], "Где заказ?")
        self.assertEqual(chat["customer_name"], "Заказ 100-1")
        history = chat["metadata"]["_ozon_history"]
        self.assertEqual(history[0]["direction"], "inbound")
        self.assertEqual(history[0]["created_at"], "2026-09-19T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
