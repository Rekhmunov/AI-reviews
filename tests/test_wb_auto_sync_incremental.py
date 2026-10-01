"""WB auto-sync must not dual-pass full history (starves other cabinets)."""

from __future__ import annotations

import unittest
from unittest import mock

from review_processor.service import ReviewAutomationService, WildberriesMarketplaceClient


class _RecordingWbClient(WildberriesMarketplaceClient):
    def __init__(self) -> None:
        super().__init__(
            api_url="https://feedbacks-api.wildberries.ru/api/v1/feedbacks",
            api_key="token-1",
            page_size=100,
            max_pages=5,
            questions_path="/api/v1/questions",
        )
        self.review_passes: list[str] = []
        self.question_passes: list[str] = []

    def _request_json(self, *, skip: int, take: int, since_date: str | None = None) -> dict[str, object]:
        _ = skip, take, since_date
        self.review_passes.append(str(self.unanswered_value))
        return {
            "data": {
                "feedbacks": [
                    {
                        "id": f"w-{self.unanswered_value}-{skip}",
                        "text": "ok",
                        "productValuation": 5,
                    }
                ]
            }
        }

    def _fetch_conversation_endpoint(self, **kwargs: object) -> list[dict[str, object]]:
        _ = kwargs
        self.question_passes.append(str(self.unanswered_value))
        return [
            {
                "external_id": f"q-{self.unanswered_value}",
                "customer_name": "Клиент",
                "message_text": "Вопрос",
                "created_at": "2026-09-01T12:00:00Z",
                "metadata": {"raw": {}},
            }
        ]


def _service_with_mock_repo() -> ReviewAutomationService:
    repo = mock.Mock()
    repo.get_pending_retry_reviews.return_value = []
    repo.get_ai_settings.return_value = {}
    repo.get_contradiction_rules.return_value = []
    repo.get_existing_classifications.return_value = {}
    repo.upsert_review.return_value = {"review_uid": "u1", "is_new": True}
    repo.list_processing_rules.return_value = []
    repo.get_user_sync_settings.return_value = {}
    return ReviewAutomationService(repository=repo)


class WbAutoSyncIncrementalTests(unittest.TestCase):
    def test_fetch_reviews_iter_skips_answered_pass_when_requested(self) -> None:
        client = _RecordingWbClient()
        with mock.patch("review_processor.service.time.sleep", return_value=None):
            reviews = list(client.fetch_reviews_iter(include_answered=False))
        self.assertEqual(client.review_passes, ["false"])
        self.assertEqual(len(reviews), 1)

    def test_fetch_reviews_iter_dual_pass_by_default(self) -> None:
        client = _RecordingWbClient()
        with mock.patch("review_processor.service.time.sleep", return_value=None):
            reviews = list(client.fetch_reviews_iter())
        self.assertEqual(client.review_passes, ["false", "true"])
        self.assertEqual(len(reviews), 2)

    def test_fetch_questions_skips_answered_pass_when_include_answered_false(self) -> None:
        client = _RecordingWbClient()
        rows = client.fetch_questions(include_answered=False)
        self.assertEqual(client.question_passes, ["false"])
        self.assertEqual(len(rows), 1)

    def test_auto_sync_reviews_passes_include_answered_false(self) -> None:
        service = _service_with_mock_repo()
        service._list_group_subgroups_for_review_classification = mock.Mock(return_value=[])  # type: ignore[method-assign]
        client = _RecordingWbClient()
        seen: dict[str, object] = {}

        def _iter(**kwargs: object):
            seen.update(kwargs)
            return
            yield  # pragma: no cover

        client.fetch_reviews_iter = _iter  # type: ignore[method-assign]
        loaded = service.sync_reviews(
            user_id=1,
            source="wb",
            account_id=29,
            client=client,
            since_date="2026-01-01",
            apply_date_filter=False,
        )
        self.assertEqual(loaded, 0)
        self.assertEqual(seen.get("include_answered"), False)

    def test_manual_sync_reviews_keeps_answered_pass(self) -> None:
        service = _service_with_mock_repo()
        service._list_group_subgroups_for_review_classification = mock.Mock(return_value=[])  # type: ignore[method-assign]
        client = _RecordingWbClient()
        seen: dict[str, object] = {}

        def _iter(**kwargs: object):
            seen.update(kwargs)
            return
            yield  # pragma: no cover

        client.fetch_reviews_iter = _iter  # type: ignore[method-assign]
        loaded = service.sync_reviews(
            user_id=1,
            source="wb",
            account_id=29,
            client=client,
            since_date="2026-01-01",
            apply_date_filter=True,
        )
        self.assertEqual(loaded, 0)
        self.assertNotIn("include_answered", seen)


if __name__ == "__main__":
    unittest.main()
