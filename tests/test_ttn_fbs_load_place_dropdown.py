"""TTN FBS load place must use shipper LE warehouse (dropdown), not LE card address."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARGO = (ROOT / "review_processor" / "ttn_fbs_cargo.py").read_text(encoding="utf-8")
OZ = (ROOT / "review_processor" / "ozon_fbs_supplies.py").read_text(encoding="utf-8")
WB = (ROOT / "review_processor" / "wb_fbs.py").read_text(encoding="utf-8")
JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_resolve_shipper_load_place_helper() -> None:
    assert "def resolve_shipper_load_place" in CARGO
    assert "legal_entity_id" in CARGO
    assert "exclude_warehouse_id" in CARGO

    class _Repo:
        def list_supply_warehouses(self, *, user_id: int):
            assert user_id == 1
            return [
                {"id": 10, "legal_entity_id": 5, "warehouse_name": "B", "address": "addr-b"},
                {"id": 7, "legal_entity_id": 5, "warehouse_name": "A", "address": "addr-a"},
                {"id": 9, "legal_entity_id": 5, "warehouse_name": "SC", "address": "sc"},
                {"id": 3, "legal_entity_id": 99, "warehouse_name": "Other", "address": "x"},
            ]

        def warehouse_address_line(self, wh):
            return str(wh.get("address") or "")

    from review_processor.ttn_fbs_cargo import resolve_shipper_load_place

    wid, addr = resolve_shipper_load_place(
        _Repo(), user_id=1, legal_entity_id=5, exclude_warehouse_id=9
    )
    # Prefer non-excluded; sort by name → A before B.
    assert wid == 7
    assert addr == "addr-a"

    wid2, addr2 = resolve_shipper_load_place(
        _Repo(), user_id=1, legal_entity_id=5, exclude_warehouse_id=0
    )
    assert wid2 == 7
    assert addr2 == "addr-a"

    empty_id, empty_addr = resolve_shipper_load_place(
        _Repo(), user_id=1, legal_entity_id=404, exclude_warehouse_id=0
    )
    assert empty_id == 0
    assert empty_addr == ""


def test_ozon_and_wb_prefill_use_load_warehouse() -> None:
    for src, label in ((OZ, "ozon"), (WB, "wb")):
        block = src.split("def build_ttn_prefill", 1)[1].split("\ndef ", 1)[0]
        assert "resolve_shipper_load_place" in block, label
        assert '"load_warehouse_id": load_warehouse_id' in block, label
        # Must not only use LE card address for load.
        assert "shipper.get(\"address\")" in block, label


def test_open_ttn_modal_prefers_load_warehouse_key() -> None:
    assert "load_warehouse_id" in JS
    assert "w:${Number(record.load_warehouse_id)}" in JS
    assert "_ttnWarehousesForLegalEntity" in JS
    # Unload already prefers warehouse_id — keep both.
    assert "w:${Number(record.warehouse_id)}" in JS
    # Legacy recovery: sole LE warehouse when LE card address was stored.
    assert 'startsWith("le:")' in JS
    assert "_ttnWarehousesForLegalEntity" in JS


def test_cache_bump() -> None:
    html = HTML if "app.js?v=669" in HTML else (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
    assert "app.js?v=669" in html
