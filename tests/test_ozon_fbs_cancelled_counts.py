"""Ozon FBS: cancelled postings excluded from counts/print, visible in modals."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz
from review_processor.ozon_fbs_marking import build_marking_payload, save_marking
from review_processor.ozon_fbs_pick_verify import build_pick_verify_payload, save_pick_verify
from review_processor.ozon_fbs_supplies import build_stickers_print, render_picking_list_html


def test_tab_counts_exclude_cancelled_on_operational_tabs() -> None:
    repo = MagicMock()
    conn = MagicMock()
    repo._connect.return_value.__enter__ = MagicMock(return_value=conn)
    repo._connect.return_value.__exit__ = MagicMock(return_value=False)
    repo._sql.side_effect = lambda s: s
    conn.execute.return_value.fetchall.return_value = [
        {"tab": oz.TAB_AWAITING_PACKAGING, "n": 4},
        {"tab": oz.TAB_AWAITING_DELIVER, "n": 2},
        {"tab": oz.TAB_CANCELLED, "n": 5},
    ]
    with patch(
        "review_processor.ozon_fbs_detail.count_awaiting_packaging_multi",
        return_value={"multi_posting_count": 3, "extra_postings": 5, "result_posting_count": 9},
    ):
        counts = oz._tab_counts(repo, user_id=1, source_id=2)
    sql_calls = [c[0][0] for c in conn.execute.call_args_list if c[0]]
    count_sql = next(s for s in sql_calls if "GROUP BY tab" in s)
    assert "tab NOT IN" in count_sql
    assert "cancelled_from_split_pending" in count_sql
    assert counts[oz.TAB_AWAITING_PACKAGING] == 4
    assert counts[oz.TAB_CANCELLED] == 5
    assert counts["awaiting_packaging_multi"] == 3
    assert counts["awaiting_packaging_multi_extra"] == 5


def test_picking_list_excludes_cancelled() -> None:
    detail = {
        "supply_id": "OZ-1",
        "name": "Test",
        "warehouse_label": "WH",
        "orders": [
            {
                "posting_number": "A-1",
                "offer_id": "ART1",
                "product_name": "One",
                "cancelled": False,
            },
            {
                "posting_number": "A-2",
                "offer_id": "ART1",
                "product_name": "One",
                "cancelled": True,
                "cancel_reason_label": "Отменено",
            },
        ],
    }
    html = render_picking_list_html(detail)
    assert "Всего 1 отпр." in html
    assert "One — 1 шт." in html


def test_build_marking_payload_excludes_cancelled_with_marking() -> None:
    detail = {
        "supply_id": "OZ-1",
        "orders": [
            {
                "posting_number": "A-1",
                "kiz_required": True,
                "kiz_quantity": 1,
                "product_name": "Active",
                "offer_id": "X",
                "barcodes": [],
                "cancelled": False,
            },
            {
                "posting_number": "A-2",
                "kiz_required": False,
                "kiz_quantity": 1,
                "product_name": "Cancelled",
                "offer_id": "Y",
                "barcodes": [],
                "cancelled": True,
                "cancel_reason_label": "Отмена",
                "is_mandatory_mark": True,
                "raw_json": (
                    '{"requirements":{"products_requiring_mandatory_mark":["1"]},'
                    '"products":[{"sku":1,"quantity":1,"mandatory_mark":true}]}'
                ),
            },
            {
                "posting_number": "A-3",
                "kiz_required": False,
                "product_name": "Plain",
            },
        ],
    }
    with (
        patch(
            "review_processor.ozon_fbs_marking.oz_sup.get_supply_detail",
            return_value=detail,
        ),
        patch(
            "review_processor.ozon_fbs_marking.load_marking_map",
            return_value={
                "A-1": {"codes": [], "saved_at": "", "ozon_synced": False},
                "A-2": {"codes": ["c1"], "saved_at": "t", "ozon_synced": False},
            },
        ),
    ):
        payload = build_marking_payload(
            MagicMock(), user_id=1, source_id=2, supply_id="OZ-1"
        )
    pns = [r["posting_number"] for r in payload["rows"]]
    assert pns == ["A-1"]
    assert payload["required_count"] == 1


def test_build_pick_verify_payload_excludes_cancelled_plain() -> None:
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


def test_save_marking_skips_cancelled_postings() -> None:
    with patch(
        "review_processor.ozon_fbs_marking._load_posting_cancelled_map",
        return_value={"A-1": True},
    ):
        out = save_marking(
            MagicMock(),
            user_id=1,
            source_id=2,
            items=[{"posting_number": "A-1", "kiz_codes": ["x"]}],
            allowed_posting_numbers={"A-1"},
        )
    assert out["skipped"] == 1
    assert out["saved"] == 0


def test_save_pick_verify_skips_cancelled_postings() -> None:
    with patch(
        "review_processor.ozon_fbs_pick_verify._load_posting_cancelled_map",
        return_value={"P-1": True},
    ), patch(
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
                    "pick_barcode": "4601234567890",
                }
            ],
            allowed_posting_numbers={"P-1"},
        )
    assert out["skipped"] == 1
    assert out["saved"] == 0


def test_build_stickers_print_excludes_cancelled() -> None:
    detail = {
        "supply_id": "OZ-1",
        "name": "Test",
        "orders": [
            {
                "posting_number": "A-1",
                "tab": oz.TAB_AWAITING_DELIVER,
                "cancelled": False,
            },
            {
                "posting_number": "A-2",
                "tab": oz.TAB_AWAITING_DELIVER,
                "cancelled": True,
                "cancel_reason_label": "Отменено",
            },
        ],
    }
    repo = MagicMock()
    with (
        patch(
            "review_processor.ozon_fbs_supplies.get_supply_detail_for_print",
            return_value=detail,
        ),
        patch(
            "review_processor.ozon_fbs_supplies._fetch_label_images",
            return_value={"A-1": ["img"]},
        ),
        patch(
            "review_processor.ozon_fbs_supplies.render_stickers_print_html",
            return_value="<html/>",
        ) as render_html,
    ):
        build_stickers_print(
            repo,
            user_id=1,
            source_id=2,
            supply_id="OZ-1",
            client_id="c",
            api_key="k",
        )
    orders = render_html.call_args[0][0].get("orders") or []
    assert [o["posting_number"] for o in orders] == ["A-1"]
