"""Full Ozon FBS sync must not re-run schema DDL on every posting upsert.

Keeps list page limit at 50; only skips ensure_ozon_fbs_tables inside the
blue-button sync upsert loop (ensure still runs once at sync start).
"""

from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz


def test_upsert_posting_can_skip_ensure_tables() -> None:
    repo = MagicMock()
    with patch("review_processor.ozon_fbs.ensure_ozon_fbs_tables") as ensure:
        oz.upsert_posting(
            repo,
            user_id=1,
            source_id=2,
            posting={"posting_number": ""},
            ensure_tables=False,
        )
    ensure.assert_not_called()


def test_upsert_posting_ensures_tables_by_default() -> None:
    repo = MagicMock()
    with patch("review_processor.ozon_fbs.ensure_ozon_fbs_tables") as ensure:
        oz.upsert_posting(
            repo,
            user_id=1,
            source_id=2,
            posting={"posting_number": ""},
        )
    ensure.assert_called_once_with(repo)


def test_sync_keeps_limit_50_and_upserts_without_per_row_ensure() -> None:
    repo = MagicMock()
    client = MagicMock()
    posting = {
        "posting_number": "P-1",
        "status": "awaiting_deliver",
        "products": [{"sku": 1, "quantity": 1}],
    }
    seen_limits: list[int] = []

    def _page(**kw):
        seen_limits.append(int(kw.get("limit") or 0))
        if kw.get("status") == "awaiting_deliver":
            return [posting], False
        return [], False

    client.list_postings_page.side_effect = _page
    upsert_kwargs: list[dict] = []

    def _upsert(*_a, **kw):
        upsert_kwargs.append(kw)

    with (
        patch("review_processor.ozon_fbs.OzonFbsClient", return_value=client),
        patch("review_processor.ozon_fbs.ensure_ozon_fbs_tables") as ensure,
        patch("review_processor.ozon_fbs.upsert_posting", side_effect=_upsert),
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

    ensure.assert_called_once_with(repo)
    assert seen_limits
    assert all(limit == 50 for limit in seen_limits)
    assert upsert_kwargs
    assert all(kw.get("ensure_tables") is False for kw in upsert_kwargs)
