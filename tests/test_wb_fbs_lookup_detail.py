"""WB FBS order lookup detail card (parity with Ozon FBS search card)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from review_processor.wb_fbs import build_order_lookup_details

ROOT = Path(__file__).resolve().parents[1]


def test_build_order_lookup_details_includes_status_sticker_kiz_pick() -> None:
    repo = MagicMock()
    repo._connect.return_value.__enter__ = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))))
    repo._connect.return_value.__exit__ = MagicMock(return_value=False)
    repo._sql = lambda q: q
    repo._row_to_dict = lambda r: dict(r)

    details = build_order_lookup_details(
        repo,
        user_id=1,
        source_id=2,
        row={
            "order_id": 13833711,
            "tab": "assembly",
            "supplier_status": "confirm",
            "wb_status": "waiting",
            "article": "SKU-1",
            "nm_id": "111",
            "product_name": "Футболка",
            "supply_id": "WB-GI-9",
            "sticker_part_a": "1234",
            "sticker_part_b": "567890",
            "kiz_codes_json": '["010460000000000021"]',
            "pick_verified": True,
            "pick_barcode": "4600000000000",
            "created_at_wb": "2026-09-01T10:00:00+00:00",
            "warehouse_label": "Коледино",
            "cargo_type": 1,
            "barcodes": ["4600000000000"],
            "price_display": "990 ₽",
        },
    )
    assert details["order_id"] == 13833711
    assert details["tab_label"] == "На сборке"
    assert details["status_label"] == "На сборке"
    assert details["supply_id"] == "WB-GI-9"
    assert details["sticker_label"] == "1234 567890"
    assert details["kiz_codes"] == ["010460000000000021"]
    assert details["pick_verified"] is True
    assert details["pick_barcode"] == "4600000000000"
    assert details["warehouse_label"] == "Коледино"
    assert details["cargo_label"] == "МГТ"
    assert details["created_at_wb"]
    assert details["barcodes"] == ["4600000000000"]


def test_wb_fbs_lookup_detail_ui_markup() -> None:
    html = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
    js = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")

    assert 'id="wbFbsLookupDetail"' in html
    assert "wb-fbs-lookup-detail" in html
    assert "function _wbFbsRenderLookupDetail" in js
    assert "function _wbFbsLookupDetailRows" in js
    assert "Детали заказа" in js
    assert "Короба TRBX" in js
    assert "Проверка ШК" in js
    assert "data.details" in js
    assert ".wb-fbs-lookup-detail" in css
    assert "style.css?v=291" in html
    assert "app.js?v=535" in html
