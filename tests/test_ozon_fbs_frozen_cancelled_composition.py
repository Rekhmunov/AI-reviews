"""Frozen Ozon FBS composition: cancelled stay linked until pick-list/stickers reset."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz
from review_processor import ozon_fbs_supplies as oz_sup
from review_processor.ozon_fbs_marking import build_marking_payload
from review_processor.ozon_fbs_pick_verify import build_pick_verify_payload

ROOT = Path(__file__).resolve().parents[1]


def test_marking_payload_includes_cancelled_kiz_rows() -> None:
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
                "kiz_required": True,
                "kiz_quantity": 1,
                "product_name": "Cancelled",
                "offer_id": "Y",
                "barcodes": [],
                "cancelled": True,
                "cancel_reason_label": "Отмена",
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
                "A-2": {"codes": [], "saved_at": "", "ozon_synced": False},
            },
        ),
    ):
        payload = build_marking_payload(
            MagicMock(),
            user_id=1,
            source_id=2,
            supply_id="OZ-1",
            resolve_kiz=False,
        )
    by_pn = {r["posting_number"]: r for r in payload["rows"]}
    assert set(by_pn) == {"A-1", "A-2"}
    assert by_pn["A-2"]["cancelled"] is True
    assert by_pn["A-1"]["cancelled"] is False


def test_pick_verify_payload_includes_cancelled_plain_rows() -> None:
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
                "posting_number": "P-3",
                "kiz_required": False,
                "cancelled": True,
                "cancel_reason_label": "Отмена",
                "product_name": "Cancelled plain",
                "offer_id": "A3",
                "barcodes": [],
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
            return_value={
                "P-1": {
                    "pick_verified": False,
                    "pick_barcode": "",
                    "pick_verified_at": "",
                },
                "P-3": {
                    "pick_verified": False,
                    "pick_barcode": "",
                    "pick_verified_at": "",
                },
            },
        ),
    ):
        payload = build_pick_verify_payload(
            MagicMock(),
            user_id=1,
            source_id=2,
            supply_id="OZ-1",
            resolve_kiz=False,
        )
    by_pn = {r["posting_number"]: r for r in payload["rows"]}
    assert set(by_pn) == {"P-1", "P-3"}
    assert by_pn["P-3"]["cancelled"] is True
    assert payload["plain_count"] == 2


def test_move_to_delivering_ships_stock_for_frozen_cancelled(monkeypatch) -> None:
    awaiting = [
        {
            "posting_number": "P-1",
            "tab": oz.TAB_AWAITING_DELIVER,
            "offer_id": "ART",
            "sku": "1",
            "quantity": 1,
            "products_json": '[{"offer_id":"ART","sku":1,"quantity":1}]',
        }
    ]
    cancelled = [
        {
            "posting_number": "P-CX",
            "tab": oz.TAB_CANCELLED,
            "offer_id": "ART",
            "sku": "1",
            "quantity": 1,
            "products_json": '[{"offer_id":"ART","sku":1,"quantity":1}]',
        }
    ]
    reconcile_calls: list[list[dict]] = []

    class _Repo:
        def _sql(self, q: str) -> str:
            return q

        def _row_to_dict(self, r):
            return dict(r)

        def _connect(self):
            class _Cur:
                def __init__(self, rows=None, n=0):
                    self._rows = rows or []
                    self._n = n

                def fetchall(self):
                    return self._rows

                def fetchone(self):
                    return {"n": self._n}

            class _Conn:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def execute(self, sql, params=()):
                    sql_s = str(sql)
                    if any(
                        x in sql_s
                        for x in ("CREATE TABLE", "ALTER TABLE", "CREATE INDEX")
                    ):
                        return _Cur()
                    if "FROM ozon_fbs_supplies" in sql_s and "SELECT" in sql_s:
                        return _Cur(
                            [
                                {
                                    "supply_id": "OZ-1",
                                    "name": "T",
                                    "posting_numbers_json": "[]",
                                }
                            ]
                        )
                    if "SELECT posting_number, tab" in sql_s:
                        tab = params[-1] if params else ""
                        if tab == oz.TAB_AWAITING_DELIVER:
                            return _Cur(awaiting)
                        if tab == oz.TAB_CANCELLED:
                            return _Cur(cancelled)
                        return _Cur([])
                    if "UPDATE ozon_fbs_postings" in sql_s:
                        return _Cur()
                    if "SELECT COUNT(*)" in sql_s:
                        return _Cur(n=0)
                    return _Cur()

            return _Conn()

    repo = _Repo()
    monkeypatch.setattr(oz_sup, "ensure_ozon_fbs_supply_schema", lambda r: None)
    monkeypatch.setattr(oz, "ensure_ozon_fbs_tables", lambda r: None)
    monkeypatch.setattr(
        oz_sup,
        "get_supply",
        lambda r, **kw: {"supply_id": "OZ-1", "name": "T"},
    )

    def _reconcile(repo, user_id, postings):
        reconcile_calls.append(list(postings))
        return {
            "shipped": len(postings),
            "reversed": 0,
            "skipped": 0,
            "ok": 0,
            "settled": 0,
        }

    monkeypatch.setattr(
        oz_sup, "_reconcile_ozon_fbs_stock_after_local_move", _reconcile
    )

    out = oz_sup.move_supply_to_delivering(
        repo, user_id=1, source_id=5, supply_id="OZ-1"
    )
    assert out["ok"] is True
    assert out["moved"] == 1
    assert out["cancelled_stocked"] == 0
    assert len(reconcile_calls) == 1
    pns = {p["posting_number"] for p in reconcile_calls[0]}
    assert pns == {"P-1"}
    assert all(p["tab"] == oz.TAB_DELIVERING for p in reconcile_calls[0])


def test_status_refresh_ui_keeps_cancelled_in_modals() -> None:
    js = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
    html = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
    close_start = js.find("function closeOzonFbsPostingStatusModal")
    close_fn = js[close_start : close_start + 550]
    assert "_ozonFbsRemovePostingFromOpenModals(" not in close_fn
    assert "function _ozonFbsRefreshOpenModalsAfterCancelFlag" in js
    # Cancelled stay in KIZ/pick modals until pick-list+stickers reset / ⋮ remove.
    assert "будет удалён из модалки" not in js
    assert "function _ozonFbsApplyCancelledQuiet" in js
    assert "ozon_fbs.js?v=193" in html
