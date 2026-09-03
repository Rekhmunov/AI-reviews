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


def test_get_era_cache_is_invalidated_for_is_required_rerun() -> None:
    """Postings checked via empty get requirements must re-run is-required."""
    posting = {
        "posting_number": "P-1",
        "products": [{"sku": 1, "quantity": 1}],
        "requirements": {
            "products_requiring_mandatory_mark": [],
            "marking_is_required_checked": True,
            "marking_check_version": 2,
        },
    }
    assert oz.posting_marking_flags_resolved(posting) is False


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


def test_refresh_supply_marking_flags_uses_catalog_requires_kiz() -> None:
    repo = MagicMock()
    conn = MagicMock()
    repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
    repo._connect.return_value.__exit__ = MagicMock(return_value=False)
    repo._sql = lambda s: s
    repo._row_to_dict = lambda row: row
    repo.get_product_requires_kiz_map.return_value = {"ART-1": True, "555": True}
    row = {
        "posting_number": "P-1",
        "is_mandatory_mark": False,
        "raw_json": (
            '{"posting_number":"P-1","products":[{"sku":555,"quantity":1,"offer_id":"ART-1"}]}'
        ),
        "products_json": "[]",
    }
    conn.execute.return_value.fetchall.return_value = [row]

    with patch("review_processor.ozon_fbs_supplies.oz.upsert_posting") as upsert:
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
    saved = upsert.call_args.kwargs.get("posting") or upsert.call_args.args[2]
    req = saved.get("requirements") or {}
    assert "555" in (req.get("products_requiring_mandatory_mark") or [])
    assert req.get("marking_is_required_checked") is True


def test_refresh_supply_marking_flags_chunks_and_advances() -> None:
    """Chunked upserts advance: already-matching rows are skipped next round."""
    repo = MagicMock()
    conn = MagicMock()
    repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
    repo._connect.return_value.__exit__ = MagicMock(return_value=False)
    repo._sql = lambda s: s
    repo._row_to_dict = lambda row: row
    repo.get_product_requires_kiz_map.return_value = {}
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

    with patch("review_processor.ozon_fbs_supplies.oz.upsert_posting") as upsert:
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
    assert upsert.call_count == 2

    # Simulate DB now holding catalog-applied flags for first two.
    saved = []
    for call in upsert.call_args_list:
        posting = call.kwargs.get("posting") or call.args[2]
        saved.append(posting)
    for i, posting in enumerate(saved):
        rows[i]["raw_json"] = __import__("json").dumps(posting)
    conn.execute.return_value.fetchall.return_value = rows

    with patch("review_processor.ozon_fbs_supplies.oz.upsert_posting") as upsert2:
        result2 = refresh_supply_marking_flags_from_ozon(
            repo,
            user_id=1,
            source_id=2,
            posting_numbers=[f"P-{i}" for i in range(5)],
            client_id="cid",
            api_key="key",
            max_postings=2,
        )
    assert result2["checked"] == 2
    assert result2["remaining"] == 1
    assert result2["total_pending"] == 3
    assert upsert2.call_count == 2


def test_refresh_supply_marking_flags_clears_when_catalog_off() -> None:
    """Catalog checkbox off → no KIZ even if posting previously had API requirements."""
    repo = MagicMock()
    conn = MagicMock()
    repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
    repo._connect.return_value.__exit__ = MagicMock(return_value=False)
    repo._sql = lambda s: s
    repo._row_to_dict = lambda row: row
    repo.get_product_requires_kiz_map.return_value = {}
    row = {
        "posting_number": "P-1",
        "is_mandatory_mark": False,
        "raw_json": (
            '{"posting_number":"P-1","products":[{"sku":555,"quantity":1,"offer_id":"X"}],'
            '"requirements":{"products_requiring_mandatory_mark":["555"]}}'
        ),
        "products_json": "[]",
    }
    conn.execute.return_value.fetchall.return_value = [row]

    with patch("review_processor.ozon_fbs_supplies.oz.upsert_posting") as upsert:
        result = refresh_supply_marking_flags_from_ozon(
            repo,
            user_id=1,
            source_id=2,
            posting_numbers=["P-1"],
            client_id="cid",
            api_key="key",
        )

    assert result["checked"] == 1
    assert result["updated"] == 1
    saved = upsert.call_args.kwargs.get("posting") or upsert.call_args.args[2]
    req = saved.get("requirements") or {}
    assert req.get("products_requiring_mandatory_mark") == []
    assert req.get("marking_is_required_checked") is True
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
    assert resolve.call_args.kwargs.get("supply_id") == "OZ-1"
    assert resolve.call_args.kwargs.get("source_id") == 2
    assert resolve.call_args.kwargs.get("posting_tab") == "awaiting_deliver"
    assert get_detail.call_args.kwargs.get("posting_tab") == "awaiting_deliver"
    assert get_detail.call_args.kwargs.get("supply_id") == "OZ-1"
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["posting_number"] == "K-1"
    assert len(payload["order_kiz_flags"]) == 2
    assert payload["marking_resolve"]["remaining"] == 0


def test_refresh_skips_when_sync_already_stamped_catalog_flags() -> None:
    """After sync warm, modal resolve should be remaining=0 (no upserts)."""
    repo = MagicMock()
    conn = MagicMock()
    repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
    repo._connect.return_value.__exit__ = MagicMock(return_value=False)
    repo._sql = lambda s: s
    repo._row_to_dict = lambda row: row
    catalog = {"ART-1": True, "555": True}
    repo.get_product_requires_kiz_map.return_value = catalog
    posting = {
        "posting_number": "P-1",
        "products": [{"sku": 555, "quantity": 1, "offer_id": "ART-1"}],
    }
    stamped = oz.apply_catalog_marking_flags(posting, catalog)
    row = {
        "posting_number": "P-1",
        "is_mandatory_mark": False,
        "raw_json": __import__("json").dumps(stamped),
        "products_json": "[]",
    }
    conn.execute.return_value.fetchall.return_value = [row]

    with patch("review_processor.ozon_fbs_supplies.oz.upsert_posting") as upsert:
        result = refresh_supply_marking_flags_from_ozon(
            repo,
            user_id=1,
            source_id=2,
            posting_numbers=["P-1"],
            client_id="cid",
            api_key="key",
        )

    assert result["updated"] == 0
    assert result["checked"] == 0
    assert result["remaining"] == 0
    assert result["total_pending"] == 0
    upsert.assert_not_called()


def test_invalidate_catalog_marking_flags_clears_checked_only() -> None:
    import json

    repo = MagicMock()
    conn = MagicMock()
    repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
    repo._connect.return_value.__exit__ = MagicMock(return_value=False)
    repo._sql = lambda s: s
    repo._row_to_dict = lambda row: row
    stamped = {
        "posting_number": "P-1",
        "products": [{"sku": 555, "offer_id": "ART-1", "quantity": 1}],
        "requirements": {
            "products_requiring_mandatory_mark": ["555"],
            "marking_is_required_checked": True,
        },
    }
    other = {
        "posting_number": "P-2",
        "products": [{"sku": 777, "offer_id": "OTHER", "quantity": 1}],
        "requirements": {
            "products_requiring_mandatory_mark": [],
            "marking_is_required_checked": True,
        },
    }
    rows = [
        {
            "source_id": 2,
            "posting_number": "P-1",
            "offer_id": "ART-1",
            "sku": 555,
            "products_json": json.dumps(stamped["products"]),
            "raw_json": json.dumps(stamped),
        },
        {
            "source_id": 2,
            "posting_number": "P-2",
            "offer_id": "OTHER",
            "sku": 777,
            "products_json": json.dumps(other["products"]),
            "raw_json": json.dumps(other),
        },
    ]
    conn.execute.return_value.fetchall.return_value = rows

    with patch("review_processor.ozon_fbs.ensure_ozon_fbs_tables"):
        n = oz.invalidate_catalog_marking_flags_for_keys(
            repo, user_id=1, catalog_keys=["ART-1"]
        )

    assert n == 1
    update_calls = [
        c for c in conn.execute.call_args_list if "UPDATE ozon_fbs_postings" in str(c[0][0])
    ]
    assert len(update_calls) == 1
    raw = json.loads(update_calls[0][0][1][0])
    req = raw.get("requirements") or {}
    assert "marking_is_required_checked" not in req
    assert req.get("products_requiring_mandatory_mark") == ["555"]


def test_invalidate_then_refresh_reapplies_catalog() -> None:
    """Toggle path: invalidate → modal residual upserts new mark ids."""
    import json

    repo = MagicMock()
    conn = MagicMock()
    repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
    repo._connect.return_value.__exit__ = MagicMock(return_value=False)
    repo._sql = lambda s: s
    repo._row_to_dict = lambda row: row
    # After invalidate: checked cleared, old mark ids still present.
    posting = {
        "posting_number": "P-1",
        "products": [{"sku": 555, "offer_id": "ART-1", "quantity": 1}],
        "requirements": {"products_requiring_mandatory_mark": []},
    }
    row = {
        "posting_number": "P-1",
        "is_mandatory_mark": False,
        "raw_json": json.dumps(posting),
        "products_json": "[]",
    }
    conn.execute.return_value.fetchall.return_value = [row]
    repo.get_product_requires_kiz_map.return_value = {"ART-1": True, "555": True}

    with patch("review_processor.ozon_fbs_supplies.oz.upsert_posting") as upsert:
        result = refresh_supply_marking_flags_from_ozon(
            repo,
            user_id=1,
            source_id=2,
            posting_numbers=["P-1"],
            client_id="cid",
            api_key="key",
        )
    assert result["updated"] == 1
    saved = upsert.call_args.kwargs["posting"]
    assert (saved.get("requirements") or {}).get("marking_is_required_checked") is True
    assert "555" in (
        (saved.get("requirements") or {}).get("products_requiring_mandatory_mark") or []
    )


def test_sync_does_not_call_marking_enrich() -> None:
    repo = MagicMock()
    repo.get_product_requires_kiz_map.return_value = {"111": True}
    client = MagicMock()
    posting = {
        "posting_number": "P-1",
        "status": "awaiting_deliver",
        "products": [{"sku": 111, "quantity": 1}],
    }
    client.list_postings_page.side_effect = lambda **kw: (
        ([posting], False) if kw.get("status") == "awaiting_deliver" else ([], False)
    )
    saved: list[dict] = []

    def _upsert(*_a, **kw):
        saved.append(kw.get("posting") or {})

    with (
        patch("review_processor.ozon_fbs.OzonFbsClient", return_value=client),
        patch("review_processor.ozon_fbs.ensure_ozon_fbs_tables"),
        patch("review_processor.ozon_fbs.upsert_posting", side_effect=_upsert),
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
    assert saved
    req = saved[0].get("requirements") or {}
    assert req.get("marking_is_required_checked") is True
    assert "111" in (req.get("products_requiring_mandatory_mark") or [])


def test_sync_applies_catalog_kiz_flags_into_upsert() -> None:
    """Sync must stamp catalog flags into raw_json so modal resolve is a no-op."""
    repo = MagicMock()
    repo.get_product_requires_kiz_map.return_value = {
        "ART-KIZ": True,
        "555": True,
    }
    client = MagicMock()
    posting = {
        "posting_number": "P-1",
        "status": "awaiting_packaging",
        "products": [
            {"sku": 555, "offer_id": "ART-KIZ", "quantity": 1},
            {"sku": 777, "offer_id": "ART-PLAIN", "quantity": 1},
        ],
    }
    client.list_postings_page.side_effect = lambda **kw: (
        ([posting], False) if kw.get("status") == "awaiting_packaging" else ([], False)
    )
    saved: list[dict] = []

    def _upsert(*_a, **kw):
        saved.append(dict(kw.get("posting") or {}))

    progress_msgs: list[str] = []

    with (
        patch("review_processor.ozon_fbs.OzonFbsClient", return_value=client),
        patch("review_processor.ozon_fbs.ensure_ozon_fbs_tables"),
        patch("review_processor.ozon_fbs.upsert_posting", side_effect=_upsert),
        patch("review_processor.ozon_fbs.time.sleep"),
    ):
        out = oz.sync_ozon_fbs_source(
            repo,
            user_id=9,
            source_id=3,
            client_id="cid",
            api_key="key",
            lookback_days=3,
            progress=lambda msg, n: progress_msgs.append(msg),
        )

    assert out["postings"] == 1
    assert out["stopped"] is False
    repo.get_product_requires_kiz_map.assert_called_once_with(user_id=9)
    assert any("каталог КИЗ" in m for m in progress_msgs)
    req = saved[0].get("requirements") or {}
    assert req.get("marking_is_required_checked") is True
    assert req.get("products_requiring_mandatory_mark") == ["555"]
    assert req.get("marking_check_version") is None
    # Modal residual skip contract: same apply → already matching.
    again = oz.apply_catalog_marking_flags(saved[0], {"ART-KIZ": True, "555": True})
    assert (again.get("requirements") or {}).get(
        "products_requiring_mandatory_mark"
    ) == ["555"]


def test_sync_skips_catalog_flags_when_map_fails() -> None:
    repo = MagicMock()
    repo.get_product_requires_kiz_map.side_effect = RuntimeError("db down")
    client = MagicMock()
    posting = {
        "posting_number": "P-1",
        "status": "awaiting_deliver",
        "products": [{"sku": 1, "quantity": 1}],
    }
    client.list_postings_page.side_effect = lambda **kw: (
        ([posting], False) if kw.get("status") == "awaiting_deliver" else ([], False)
    )
    saved: list[dict] = []

    def _upsert(*_a, **kw):
        saved.append(kw.get("posting") or {})

    with (
        patch("review_processor.ozon_fbs.OzonFbsClient", return_value=client),
        patch("review_processor.ozon_fbs.ensure_ozon_fbs_tables"),
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

    assert saved[0] is posting or saved[0].get("requirements") is None
    assert "requirements" not in saved[0] or not (
        saved[0].get("requirements") or {}
    ).get("marking_is_required_checked")


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
