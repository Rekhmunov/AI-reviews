"""Tests for Ozon FBS marking enrich during sync and supply open."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz
from review_processor.ozon_fbs_supplies import (
    SUPPLY_MARKING_ENRICH_MAX,
    _ensure_supply_marking_flags,
    refresh_supply_marking_flags_from_ozon,
)


def test_sync_enriches_marking_for_active_status_only() -> None:
    repo = MagicMock()
    client = MagicMock()
    posting_plain = {
        "posting_number": "P-PLAIN-1",
        "status": "awaiting_deliver",
        "products": [{"sku": 111, "quantity": 1}],
    }
    posting_marked = {
        "posting_number": "P-KIZ-1",
        "status": "awaiting_deliver",
        "products": [{"sku": 222, "quantity": 1}],
        "requirements": {"products_requiring_mandatory_mark": ["222"]},
    }
    client.list_postings_page.side_effect = lambda **kw: (
        ([posting_plain, posting_marked], False)
        if kw.get("status") == "awaiting_deliver"
        else ([], False)
    )
    client.mandatory_mark_is_required.return_value = [{"sku": 111, "is_required": True}]

    with (
        patch("review_processor.ozon_fbs.OzonFbsClient", return_value=client),
        patch("review_processor.ozon_fbs.ensure_ozon_fbs_tables"),
        patch("review_processor.ozon_fbs.upsert_posting") as upsert,
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

    assert client.mandatory_mark_is_required.call_count == 1
    saved = [c.kwargs.get("posting") for c in upsert.call_args_list]
    saved = [p for p in saved if isinstance(p, dict)]
    plain_saved = next(p for p in saved if p.get("posting_number") == "P-PLAIN-1")
    req = plain_saved.get("requirements") or {}
    assert "111" in (req.get("products_requiring_mandatory_mark") or [])


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
        n = refresh_supply_marking_flags_from_ozon(
            repo,
            user_id=1,
            source_id=2,
            posting_numbers=["P-1"],
            client_id="cid",
            api_key="key",
        )

    assert n == 1
    client.get_posting.assert_not_called()
    client.mandatory_mark_is_required.assert_called_once()
    saved = upsert.call_args.kwargs.get("posting") or upsert.call_args.args[2]
    req = saved.get("requirements") or {}
    assert "555" in (req.get("products_requiring_mandatory_mark") or [])


def test_ensure_supply_marking_flags_caps_batch() -> None:
    repo = MagicMock()
    conn = MagicMock()
    repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
    repo._connect.return_value.__exit__ = MagicMock(return_value=False)
    repo._sql = lambda s: s
    repo._row_to_dict = lambda row: row
    rows = [
        {
            "posting_number": f"P-{i}",
            "is_mandatory_mark": False,
            "raw_json": (
                f'{{"posting_number":"P-{i}","products":[{{"sku":{i},"quantity":1}}]}}'
            ),
            "products_json": "[]",
        }
        for i in range(SUPPLY_MARKING_ENRICH_MAX + 3)
    ]
    conn.execute.return_value.fetchall.return_value = rows

    with patch(
        "review_processor.ozon_fbs_supplies.refresh_supply_marking_flags_from_ozon",
        return_value=SUPPLY_MARKING_ENRICH_MAX,
    ) as refresh:
        note = _ensure_supply_marking_flags(
            repo,
            user_id=1,
            source_id=2,
            posting_numbers=[f"P-{i}" for i in range(SUPPLY_MARKING_ENRICH_MAX + 3)],
            client_id="cid",
            api_key="key",
        )

    refreshed = refresh.call_args.kwargs.get("posting_numbers") or []
    assert len(refreshed) == SUPPLY_MARKING_ENRICH_MAX
    assert "Синхронизировать" in note
