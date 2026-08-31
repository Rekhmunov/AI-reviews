"""Ozon FBS full sync uses a moderate list page size (not client default)."""

from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz


def test_sync_list_page_limit_constant_is_moderate() -> None:
    assert oz.SYNC_LIST_PAGE_LIMIT == 200
    assert 50 < oz.SYNC_LIST_PAGE_LIMIT <= 1000


def test_sync_ozon_fbs_source_requests_sync_page_limit() -> None:
    repo = MagicMock()
    client = MagicMock()
    seen_limits: list[int] = []

    def _page(**kw):
        seen_limits.append(int(kw.get("limit") or 0))
        return [], False

    client.list_postings_page.side_effect = _page

    with (
        patch("review_processor.ozon_fbs.OzonFbsClient", return_value=client),
        patch("review_processor.ozon_fbs.ensure_ozon_fbs_tables"),
        patch("review_processor.ozon_fbs.time.sleep"),
    ):
        oz.sync_ozon_fbs_source(
            repo,
            user_id=1,
            source_id=2,
            client_id="cid",
            api_key="key",
            lookback_days=3,
        )

    assert seen_limits
    assert all(limit == oz.SYNC_LIST_PAGE_LIMIT for limit in seen_limits)
    assert len(seen_limits) == len(oz.SYNC_STATUSES)
