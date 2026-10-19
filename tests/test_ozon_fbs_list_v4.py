"""FBS posting list uses Ozon ``/v4/posting/fbs/list`` and cursor pages."""

from datetime import UTC, datetime, timedelta

from review_processor.ozon_fbs import OzonFbsClient, unpack_posting_list_page


def test_list_postings_page_calls_v4_with_cursor() -> None:
    captured: dict = {}

    class _Client(OzonFbsClient):
        def post_json(self, path, body):  # type: ignore[override]
            captured["path"] = path
            captured["body"] = body
            return {
                "postings": [{"posting_number": "P-1", "status": "delivering"}],
                "has_next": True,
                "cursor": "next-1",
            }

    now = datetime.now(UTC)
    rows, has_next, cursor = _Client("664575", "key").list_postings_page(
        status="delivering",
        since=now - timedelta(days=1),
        to=now,
        limit=50,
        cursor="prev-1",
        with_extras=False,
    )
    assert captured["path"] == "/v4/posting/fbs/list"
    assert captured["body"]["cursor"] == "prev-1"
    assert "offset" not in captured["body"]
    assert captured["body"]["with"]["financial_data"] is False
    assert captured["body"]["filter"]["status"] == "delivering"
    assert rows == [{"posting_number": "P-1", "status": "delivering"}]
    assert has_next is True
    assert cursor == "next-1"


def test_list_postings_page_omits_empty_cursor_and_clears_it_without_next() -> None:
    captured: dict = {}

    class _Client(OzonFbsClient):
        def post_json(self, path, body):  # type: ignore[override]
            captured["body"] = body
            return {"postings": [], "has_next": False, "cursor": "ignored"}

    now = datetime.now(UTC)
    rows, has_next, cursor = _Client("1", "k").list_postings_page(
        status="cancelled",
        since=now - timedelta(hours=1),
        to=now,
        cursor="",
    )
    assert "cursor" not in captured["body"]
    assert rows == []
    assert has_next is False
    assert cursor == ""


def test_unpack_posting_list_page_accepts_legacy_pair() -> None:
    rows, has_next, cursor = unpack_posting_list_page(
        ([{"posting_number": "P"}], False)
    )
    assert rows == [{"posting_number": "P"}]
    assert has_next is False
    assert cursor == ""
