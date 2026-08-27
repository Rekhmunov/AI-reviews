"""Tests for Ozon FBS marking enrich during marking modal and negative cache."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz
from review_processor.ozon_fbs_marking import build_marking_payload
from review_processor.ozon_fbs_supplies import (
    refresh_supply_marking_flags_from_ozon,
    resolve_supply_kiz_flags_from_ozon,
)


def test_enrich_negative_cache_marks_checked() -> None:
    posting = {
        "posting_number": "0114598183-0259-1",
        "products": [{"sku": 752040595, "quantity": 1}],
    }
    client = MagicMock()
    client.mandatory_mark_is_required.return_value = [
        {"sku": 752040595, "is_required": False}
    ]
    out = oz.enrich_posting_marking_flags_light(client, posting)
    req = out.get("requirements") or {}
    assert req.get("marking_is_required_checked") is True
    assert oz.posting_marking_flags_resolved(out) is True
    assert oz.posting_requires_marking({"is_mandatory_mark": False, "raw_json": __import__("json").dumps(out)}) is False


def test_posting_marking_flags_resolved_after_positive_enrich() -> None:
    posting = {
        "posting_number": "0123604587-1235-1",
        "products": [{"sku": 3722013683, "quantity": 1}],
    }
    client = MagicMock()
    client.mandatory_mark_is_required.return_value = [
        {"sku": 3722013683, "is_required": True}
    ]
    out = oz.enrich_posting_marking_flags_light(client, posting)
    assert oz.posting_marking_flags_resolved(out) is True
    assert oz.posting_requires_marking(
        {"is_mandatory_mark": False, "raw_json": __import__("json").dumps(out)}
    )


def test_refresh_supply_marking_flags_uses_is_required_not_get_posting() -> None:
    repo = MagicMock()
    conn = MagicMock()
    repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
    repo._connect.return_value.__exit__ = MagicMock(return_value=False)
    repo._sql = lambda s: s
    repo._row_to_dict = lambda row: row
    row = {
        "posting_number": "P-1",
        "is_mandatory_mark": False,
        "raw_json": (
            '{"posting_number":"P-1","products":[{"sku":555,"quantity":1}]}'
        ),
        "products_json": "[]",
    }
    conn.execute.return_value.fetchall.return_value = [row]
    client = MagicMock()
    client.mandatory_mark_is_required.return_value = [{"sku": 555, "is_required": True}]

    with (
        patch("review_processor.ozon_fbs_supplies.oz.OzonFbsClient", return_value=client),
        patch("review_processor.ozon_fbs_supplies.oz.upsert_posting") as upsert,
        patch("review_processor.ozon_fbs_supplies.time.sleep"),
    ):
        result = refresh_supply_marking_flags_from_ozon(
            repo,
            user_id=1,
            source_id=2,
            posting_numbers=["P-1"],
            client_id="cid",
            api_key="key",
        )

    assert result["updated"] == 1
    assert result["checked"] == 1
    assert result["remaining"] == 0
    client.get_posting.assert_not_called()
    saved = upsert.call_args.kwargs.get("posting") or upsert.call_args.args[2]
    req = saved.get("requirements") or {}
    assert "555" in (req.get("products_requiring_mandatory_mark") or [])


def test_refresh_supply_marking_flags_chunks_and_reports_remaining() -> None:
    repo = MagicMock()
    conn = MagicMock()
    repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
    repo._connect.return_value.__exit__ = MagicMock(return_value=False)
    repo._sql = lambda s: s
    repo._row_to_dict = lambda row: row
    rows = []
    for i in range(5):
        pn = f"P-{i}"
        rows.append(
            {
                "posting_number": pn,
                "is_mandatory_mark": False,
                "raw_json": (
                    f'{{"posting_number":"{pn}","products":[{{"sku":{100 + i},"quantity":1}}]}}'
                ),
                "products_json": "[]",
            }
        )
    conn.execute.return_value.fetchall.return_value = rows
    client = MagicMock()
    client.mandatory_mark_is_required.return_value = [{"sku": 100, "is_required": False}]

    with (
        patch("review_processor.ozon_fbs_supplies.oz.OzonFbsClient", return_value=client),
        patch("review_processor.ozon_fbs_supplies.oz.upsert_posting"),
    ):
        result = refresh_supply_marking_flags_from_ozon(
            repo,
            user_id=1,
            source_id=2,
            posting_numbers=[f"P-{i}" for i in range(5)],
            client_id="cid",
            api_key="key",
            max_postings=2,
        )

    assert result["checked"] == 2
    assert result["remaining"] == 3
    assert result["total_pending"] == 5
    assert result["updated"] == 2
    assert client.mandatory_mark_is_required.call_count == 2


def test_refresh_supply_marking_flags_marks_checked_on_ozon_error() -> None:
    """Failed is-required must still advance the chunk queue (no infinite FE loop)."""
    repo = MagicMock()
    conn = MagicMock()
    repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
    repo._connect.return_value.__exit__ = MagicMock(return_value=False)
    repo._sql = lambda s: s
    repo._row_to_dict = lambda row: row
    row = {
        "posting_number": "P-1",
        "is_mandatory_mark": False,
        "raw_json": '{"posting_number":"P-1","products":[{"sku":555,"quantity":1}]}',
        "products_json": "[]",
    }
    conn.execute.return_value.fetchall.return_value = [row]
    client = MagicMock()
    client.mandatory_mark_is_required.side_effect = RuntimeError("ozon down")

    with (
        patch("review_processor.ozon_fbs_supplies.oz.OzonFbsClient", return_value=client),
        patch("review_processor.ozon_fbs_supplies.oz.upsert_posting") as upsert,
    ):
        result = refresh_supply_marking_flags_from_ozon(
            repo,
            user_id=1,
            source_id=2,
            posting_numbers=["P-1"],
            client_id="cid",
            api_key="key",
        )

    assert result["checked"] == 1
    assert result["remaining"] == 0
    assert result["updated"] == 1
    saved = upsert.call_args.kwargs.get("posting") or upsert.call_args.args[2]
    assert (saved.get("requirements") or {}).get("marking_is_required_checked") is True
    assert oz.posting_marking_flags_resolved(saved) is True


def test_build_marking_payload_resolves_kiz_then_filters_rows() -> None:
    detail = {
        "supply_id": "OZ-1",
        "orders": [
            {
                "posting_number": "K-1",
                "kiz_required": True,
                "kiz_quantity": 1,
                "cancelled": False,
                "offer_id": "A",
            },
            {
                "posting_number": "P-1",
                "kiz_required": False,
                "cancelled": False,
                "offer_id": "B",
            },
        ],
    }
    with (
        patch(
            "review_processor.ozon_fbs_marking.oz_sup.resolve_supply_kiz_flags_from_ozon",
            return_value={"updated": 2, "checked": 2, "remaining": 0, "total_pending": 2},
        ) as resolve,
        patch(
            "review_processor.ozon_fbs_marking.oz_sup.get_supply_detail",
            return_value=detail,
        ) as get_detail,
        patch(
            "review_processor.ozon_fbs_marking.load_marking_map",
            return_value={},
        ),
    ):
        payload = build_marking_payload(
            MagicMock(),
            user_id=1,
            source_id=2,
            supply_id="OZ-1",
            client_id="cid",
            api_key="key",
            resolve_kiz=True,
            posting_tab="awaiting_deliver",
        )
    resolve.assert_called_once()
    assert resolve.call_args.kwargs.get("posting_tab") == "awaiting_deliver"
    assert get_detail.call_args.kwargs.get("posting_tab") == "awaiting_deliver"
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["posting_number"] == "K-1"
    assert len(payload["order_kiz_flags"]) == 2
    assert payload["marking_resolve"]["remaining"] == 0


def test_sync_does_not_call_marking_enrich() -> None:
    repo = MagicMock()
    client = MagicMock()
    posting = {
        "posting_number": "P-1",
        "status": "awaiting_deliver",
        "products": [{"sku": 111, "quantity": 1}],
    }
    client.list_postings_page.side_effect = lambda **kw: (
        ([posting], False) if kw.get("status") == "awaiting_deliver" else ([], False)
    )

    with (
        patch("review_processor.ozon_fbs.OzonFbsClient", return_value=client),
        patch("review_processor.ozon_fbs.ensure_ozon_fbs_tables"),
        patch("review_processor.ozon_fbs.upsert_posting"),
        patch("review_processor.ozon_fbs.enrich_posting_marking_flags_light") as enrich,
        patch("review_processor.ozon_fbs.time.sleep"),
    ):
        oz.sync_ozon_fbs_source(
            repo,
            user_id=1,
            source_id=2,
            client_id="cid",
            api_key="key",
            lookback_days=7,
        )
    enrich.assert_not_called()


def test_resolve_supply_kiz_flags_delegates_to_refresh() -> None:
    with (
        patch(
            "review_processor.ozon_fbs_supplies._assembly_posting_numbers_for_supply",
            return_value=["P-1", "P-2"],
        ),
        patch(
            "review_processor.ozon_fbs_supplies.get_supply_detail",
            return_value={
                "orders": [
                    {"posting_number": "P-1", "cancelled": False},
                    {"posting_number": "P-2", "cancelled": True},
                ]
            },
        ),
        patch(
            "review_processor.ozon_fbs_supplies.refresh_supply_marking_flags_from_ozon",
            return_value={"updated": 1, "checked": 1, "remaining": 0, "total_pending": 1},
        ) as refresh,
    ):
        result = resolve_supply_kiz_flags_from_ozon(
            MagicMock(),
            user_id=1,
            source_id=2,
            supply_id="OZ-1",
            client_id="cid",
            api_key="key",
        )
    assert result["updated"] == 1
    assert refresh.call_args.kwargs.get("posting_numbers") == ["P-1"]
    assert refresh.call_args.kwargs.get("max_postings") is not None
