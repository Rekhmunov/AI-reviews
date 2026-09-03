"""Tests for Ozon FBS local pick-verify (ШК check without КИЗ)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from review_processor.ozon_fbs_pick_verify import (
    build_pick_verify_payload,
    save_pick_verify,
    update_posting_pick_verify,
)


def test_build_pick_verify_payload_plain_only() -> None:
    detail = {
        "supply_id": "OZ-1",
        "orders": [
            {
                "posting_number": "P-1",
                "kiz_required": False,
                "product_name": "Plain",
                "offer_id": "A1",
                "barcodes": ["4601234567890"],
            },
            {
                "posting_number": "P-2",
                "kiz_required": True,
                "product_name": "Marked",
            },
            {
                "posting_number": "P-3",
                "kiz_required": False,
                "cancelled": True,
                "cancel_reason_label": "Отмена",
            },
        ],
    }
    with (
        patch(
            "review_processor.ozon_fbs_pick_verify.oz_sup.get_supply_detail",
            return_value=detail,
        ),
        patch(
            "review_processor.ozon_fbs_pick_verify.load_posting_pick_map",
            return_value={"P-1": {"pick_verified": False, "pick_barcode": "", "pick_verified_at": ""}},
        ),
    ):
        payload = build_pick_verify_payload(
            MagicMock(), user_id=1, source_id=2, supply_id="OZ-1", resolve_kiz=False
        )
    assert payload["plain_count"] == 1
    pns = {r["posting_number"] for r in payload["rows"]}
    assert pns == {"P-1"}


def test_build_pick_verify_payload_resolves_kiz_then_filters_plain() -> None:
    detail = {
        "supply_id": "OZ-1",
        "orders": [
            {"posting_number": "P-1", "kiz_required": False, "cancelled": False},
            {"posting_number": "K-1", "kiz_required": True, "cancelled": False},
        ],
    }
    with (
        patch(
            "review_processor.ozon_fbs_pick_verify.oz_sup.resolve_supply_kiz_flags_from_ozon",
            return_value={"updated": 1, "checked": 1, "remaining": 0, "total_pending": 1},
        ) as resolve,
        patch(
            "review_processor.ozon_fbs_pick_verify.oz_sup.get_supply_detail",
            return_value=detail,
        ) as get_detail,
        patch(
            "review_processor.ozon_fbs_pick_verify.load_posting_pick_map",
            return_value={},
        ),
    ):
        payload = build_pick_verify_payload(
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
    assert payload["plain_count"] == 1
    assert payload["rows"][0]["posting_number"] == "P-1"
    assert len(payload["order_kiz_flags"]) == 2
    assert payload["marking_resolve"]["remaining"] == 0


def test_build_pick_verify_payload_resolves_without_api_credentials() -> None:
    """Catalog gate does not need Ozon API keys."""
    detail = {
        "supply_id": "OZ-1",
        "orders": [{"posting_number": "P-1", "kiz_required": False, "cancelled": False}],
    }
    with (
        patch(
            "review_processor.ozon_fbs_pick_verify.oz_sup.resolve_supply_kiz_flags_from_ozon",
            return_value={"updated": 0, "checked": 1, "remaining": 0, "total_pending": 1},
        ) as resolve,
        patch(
            "review_processor.ozon_fbs_pick_verify.oz_sup.get_supply_detail",
            return_value=detail,
        ),
        patch(
            "review_processor.ozon_fbs_pick_verify.load_posting_pick_map",
            return_value={},
        ),
    ):
        build_pick_verify_payload(
            MagicMock(),
            user_id=1,
            source_id=2,
            supply_id="OZ-1",
            client_id="",
            api_key="",
            resolve_kiz=True,
        )
    resolve.assert_called_once()


def test_save_pick_verify_validates_barcode() -> None:
    with (
        patch(
            "review_processor.ozon_fbs_pick_verify.load_posting_barcodes_map",
            return_value={"P-1": ["4601234567890"]},
        ),
        patch(
            "review_processor.ozon_fbs_pick_verify.update_posting_pick_verify",
            return_value={
                "ok": True,
                "conflict": False,
                "verified": True,
                "barcode": "4601234567890",
                "verified_at": "2026-01-01T00:00:00+00:00",
            },
        ) as upd,
    ):
        out = save_pick_verify(
            MagicMock(),
            user_id=1,
            source_id=2,
            items=[
                {
                    "posting_number": "P-1",
                    "pick_verified": True,
                    "pick_barcode": "4601234567890",
                }
            ],
            allowed_posting_numbers={"P-1"},
        )
    assert out["ok"] is True
    assert out["saved"] == 1
    upd.assert_called_once()


def test_load_posting_barcodes_map_uses_catalog_when_json_empty() -> None:
    """Parity with UI: empty barcodes_json still validates via product catalog."""
    from review_processor.ozon_fbs_pick_verify import load_posting_barcodes_map

    repo = MagicMock()
    conn = MagicMock()
    repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
    repo._connect.return_value.__exit__ = MagicMock(return_value=False)
    repo._sql.side_effect = lambda s: s
    repo._row_to_dict.return_value = {
        "posting_number": "P-1",
        "offer_id": "whitebort14020025",
        "sku": "123",
        "barcodes_json": "[]",
    }
    conn.execute.return_value.fetchall.return_value = [{"posting_number": "P-1"}]
    repo.get_product_barcodes_map.return_value = {
        "whitebort14020025": ["2000513095126"],
    }
    with patch("review_processor.ozon_fbs_pick_verify.oz.ensure_ozon_fbs_tables"):
        out = load_posting_barcodes_map(
            repo, user_id=1, source_id=2, posting_numbers=["P-1"]
        )
    assert out["P-1"] == ["2000513095126"]


def test_save_pick_verify_accepts_catalog_barcode_when_json_empty() -> None:
    with (
        patch(
            "review_processor.ozon_fbs_pick_verify.load_posting_barcodes_map",
            return_value={"P-1": ["2000513095126"]},
        ),
        patch(
            "review_processor.ozon_fbs_pick_verify.update_posting_pick_verify",
            return_value={
                "ok": True,
                "conflict": False,
                "verified": True,
                "barcode": "2000513095126",
                "verified_at": "2026-01-01T00:00:00+00:00",
            },
        ),
        patch(
            "review_processor.ozon_fbs_pick_verify._load_posting_cancelled_map",
            return_value={},
        ),
    ):
        out = save_pick_verify(
            MagicMock(),
            user_id=1,
            source_id=2,
            items=[
                {
                    "posting_number": "P-1",
                    "pick_verified": True,
                    "pick_barcode": "2000513095126",
                }
            ],
            allowed_posting_numbers={"P-1"},
        )
    assert out["ok"] is True
    assert out["saved"] == 1
    assert out["errors"] == 0


def test_save_pick_verify_rejects_bad_barcode() -> None:
    with patch(
        "review_processor.ozon_fbs_pick_verify.load_posting_barcodes_map",
        return_value={"P-1": ["4601234567890"]},
    ):
        out = save_pick_verify(
            MagicMock(),
            user_id=1,
            source_id=2,
            items=[
                {
                    "posting_number": "P-1",
                    "pick_verified": True,
                    "pick_barcode": "9999999999999",
                }
            ],
            allowed_posting_numbers={"P-1"},
        )
    assert out["ok"] is False
    assert out["errors"] == 1


def test_update_posting_pick_verify_conflict() -> None:
    repo = MagicMock()
    conn = MagicMock()
    repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
    repo._connect.return_value.__exit__ = MagicMock(return_value=False)
    repo._sql.side_effect = lambda s: s
    repo._row_to_dict.return_value = {
        "pick_verified": True,
        "pick_barcode": "4601234567890",
        "pick_verified_at": "2026-01-01T00:00:00+00:00",
    }
    conn.execute.return_value.fetchone.return_value = {"pick_verified": True}
    with patch("review_processor.ozon_fbs_pick_verify.oz.ensure_ozon_fbs_tables"):
        res = update_posting_pick_verify(
            repo,
            user_id=1,
            source_id=2,
            posting_number="P-1",
            verified=True,
            barcode="1111111111111",
            expected_verified_at="2026-01-02T00:00:00+00:00",
        )
    assert res["conflict"] is True


def test_supply_detail_for_pick_verify_local_only() -> None:
    from review_processor.ozon_fbs_pick_verify import _supply_detail_for_pick_verify

    detail = {"supply_id": "OZ-1", "orders": []}
    with patch(
        "review_processor.ozon_fbs_pick_verify.oz_sup.get_supply_detail",
        return_value=detail,
    ) as get_detail:
        out = _supply_detail_for_pick_verify(
            MagicMock(),
            user_id=1,
            source_id=2,
            supply_id="OZ-1",
        )
    assert out["supply_id"] == "OZ-1"
    get_detail.assert_called_once()


def test_allowed_pick_verify_posting_numbers_plain_only() -> None:
    from review_processor.ozon_fbs_pick_verify import allowed_pick_verify_posting_numbers

    detail = {
        "supply_id": "OZ-1",
        "orders": [
            {"posting_number": "P-1", "kiz_required": False},
            {"posting_number": "P-2", "kiz_required": True},
            {"posting_number": "P-3", "kiz_required": False, "cancelled": True},
        ],
    }
    with patch(
        "review_processor.ozon_fbs_pick_verify._supply_detail_for_pick_verify",
        return_value=detail,
    ):
        allowed = allowed_pick_verify_posting_numbers(
            MagicMock(), user_id=1, source_id=2, supply_id="OZ-1"
        )
    assert allowed == {"P-1"}


def test_save_pick_verify_clears_empty_unverify_without_clear_flag() -> None:
    """TSD × clear used to send verified=false + empty barcode without clear.

    Server skipped the item (no results[]), and TSD threw
    «Сервер не вернул результат сохранения ШК».
    """
    with (
        patch(
            "review_processor.ozon_fbs_pick_verify.load_posting_barcodes_map",
            return_value={"P-1": ["4601234567890"]},
        ),
        patch(
            "review_processor.ozon_fbs_pick_verify.update_posting_pick_verify",
            return_value={
                "ok": True,
                "conflict": False,
                "verified": False,
                "barcode": "",
                "verified_at": "",
            },
        ) as upd,
        patch(
            "review_processor.ozon_fbs_pick_verify._load_posting_cancelled_map",
            return_value={},
        ),
    ):
        out = save_pick_verify(
            MagicMock(),
            user_id=1,
            source_id=2,
            items=[
                {
                    "posting_number": "P-1",
                    "pick_verified": False,
                    "pick_barcode": "",
                }
            ],
            allowed_posting_numbers={"P-1"},
        )
    assert out["ok"] is True
    assert out["saved"] == 1
    assert out["skipped"] == 0
    assert len(out["results"]) == 1
    assert out["results"][0]["posting_number"] == "P-1"
    assert out["results"][0]["ok"] is True
    assert out["results"][0]["pick_verified"] is False
    upd.assert_called_once()
    assert upd.call_args.kwargs["verified"] is False
    assert upd.call_args.kwargs["barcode"] == ""


def test_save_pick_verify_clear_flag() -> None:
    with (
        patch(
            "review_processor.ozon_fbs_pick_verify.load_posting_barcodes_map",
            return_value={"P-1": ["4601234567890"]},
        ),
        patch(
            "review_processor.ozon_fbs_pick_verify.update_posting_pick_verify",
            return_value={
                "ok": True,
                "conflict": False,
                "verified": False,
                "barcode": "",
                "verified_at": "",
            },
        ) as upd,
        patch(
            "review_processor.ozon_fbs_pick_verify._load_posting_cancelled_map",
            return_value={},
        ),
    ):
        out = save_pick_verify(
            MagicMock(),
            user_id=1,
            source_id=2,
            items=[
                {
                    "posting_number": "P-1",
                    "pick_verified": False,
                    "pick_barcode": "4601234567890",
                    "clear": True,
                }
            ],
            allowed_posting_numbers={"P-1"},
        )
    assert out["ok"] is True
    assert out["saved"] == 1
    assert out["results"][0]["ok"] is True
    assert upd.call_args.kwargs["verified"] is False
    assert upd.call_args.kwargs["barcode"] == ""
