"""Ozon FBS owner-only «Все отмены» journal (delivering supplies, DB-only)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from review_processor import ozon_fbs as oz
from review_processor.ozon_fbs_supplies import list_delivering_supplies_cancellations

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web_static" / "ozon_fbs.js"
HTML = ROOT / "web_templates" / "app.html"
CSS = ROOT / "web_static" / "style.css"
WEB = ROOT / "review_processor" / "web.py"


def test_all_cancellations_ui_wired() -> None:
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")

    assert 'id="ozonFbsAllCancellationsBtn"' in html
    assert "Все отмены" in html
    # Left of shipment quality inside Ozon FBS toolbar-right.
    ozon_block = html.split('id="ozonFbsAllCancellationsBtn"', 1)[1].split(
        'id="ozonFbsSearchFilter"', 1
    )[0]
    assert 'id="ozonFbsShipmentQualityBtn"' in ozon_block
    assert 'id="ozonFbsAllCancellationsModal"' in html
    assert 'id="ozonFbsAllCancellationsSearch"' in html
    assert "ozon_fbs.js?v=188" in html
    assert "style.css?v=405" in html

    assert "function openOzonFbsAllCancellationsModal" in js
    assert "function _ozonFbsSyncOwnerOnlyAllCancellationsBtn" in js
    assert "/api/ozon-fbs/cancellations/delivering" in js
    assert "window.openOzonFbsAllCancellationsModal" in js
    assert "_ozonFbsSyncOwnerOnlyAllCancellationsBtn()" in js
    assert js.count("const shipmentQualityState = {") == 1
    # Double-quoted onclick + JSON.stringify(sid) breaks HTML attributes
    # (onclick="fn("id")" → handler never runs, supplies won't expand).
    assert "onclick='toggleOzonFbsAllCancellationsSupply(${JSON.stringify(sid)})'" in js
    assert 'onclick="toggleOzonFbsAllCancellationsSupply(${JSON.stringify(sid)})"' not in js

    assert ".ozon-fbs-all-cancels-modal" in css
    assert ".ozon-fbs-all-cancels-supply-head" in css

    route = web[
        web.find('@app.get("/api/ozon-fbs/cancellations/delivering")') : web.find(
            '@app.get("/api/ozon-fbs/supplies/{supply_id}/marking")'
        )
    ]
    assert "_is_wb_fbs_tenant_owner" in route
    assert "list_delivering_supplies_cancellations" in route
    assert "только главному пользователю" in route


def test_list_delivering_supplies_cancellations_groups_cancelled(monkeypatch) -> None:
    repo = MagicMock()

    monkeypatch.setattr(
        "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema",
        lambda _repo: None,
    )
    monkeypatch.setattr(
        "review_processor.ozon_fbs_supplies._build_supply_items_for_tab",
        lambda *_a, **_k: [
            {
                "supply_id": "S1",
                "name": "Поставка 1",
                "order_count": 2,
                "warehouse_label": "Склад",
            },
            {
                "supply_id": "S2",
                "name": "Поставка 2",
                "order_count": 1,
                "warehouse_label": "Склад",
            },
        ],
    )
    repo.get_product_name_by_article.return_value = {}
    repo.get_product_name_by_ozon_sku.return_value = {}
    repo.get_product_barcodes_map.return_value = {}
    repo.get_product_photo_map.return_value = {}

    rows = [
        {
            "posting_number": "111-1",
            "supply_id": "S1",
            "status": "cancelled",
            "tab": oz.TAB_CANCELLED,
            "offer_id": "A1",
            "sku": "1",
            "product_name": "Товар 1",
            "barcodes_json": "[]",
            "created_at_ozon": "2026-09-01T10:00:00",
        },
        {
            "posting_number": "111-2",
            "supply_id": "S1",
            "status": "delivering",
            "tab": oz.TAB_DELIVERING,
            "offer_id": "A2",
            "sku": "2",
            "product_name": "Товар 2",
            "barcodes_json": "[]",
            "created_at_ozon": "2026-09-01T11:00:00",
        },
        {
            "posting_number": "222-1",
            "supply_id": "S2",
            "status": "awaiting_deliver",
            "tab": oz.TAB_AWAITING_DELIVER,
            "offer_id": "B1",
            "sku": "3",
            "product_name": "Товар 3",
            "barcodes_json": "[]",
            "created_at_ozon": "2026-09-02T10:00:00",
        },
    ]

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *_a, **_k):
            return self

        def fetchall(self):
            return rows

    repo._connect.return_value = _Conn()
    repo._sql.side_effect = lambda s: s
    repo._row_to_dict.side_effect = lambda r: dict(r)

    payload = list_delivering_supplies_cancellations(
        repo, user_id=1, source_id=10
    )
    assert payload["ok"] is True
    assert payload["cancelled_total"] == 1
    assert len(payload["supplies"]) == 2
    s1 = payload["supplies"][0]
    assert s1["supply_id"] == "S1"
    assert s1["cancelled_count"] == 1
    assert s1["cancelled_orders"][0]["posting_number"] == "111-1"
    assert s1["cancelled_orders"][0]["cancelled"] is True
    s2 = payload["supplies"][1]
    assert s2["cancelled_count"] == 0
    assert s2["cancelled_orders"] == []
