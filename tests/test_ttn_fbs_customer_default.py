"""FBS «Сформировать ТН»: field 1а defaults to the shipper legal entity."""

from __future__ import annotations

from pathlib import Path

from review_processor.ttn_fbs_cargo import apply_fbs_customer_shipper_default

ROOT = Path(__file__).resolve().parents[1]
WB = (ROOT / "review_processor" / "wb_fbs.py").read_text(encoding="utf-8")
OZ = (ROOT / "review_processor" / "ozon_fbs_supplies.py").read_text(encoding="utf-8")


def _prefill(src: str, end: str) -> str:
    return src.split("def build_ttn_prefill", 1)[1].split(end, 1)[0]


def test_both_fbs_prefills_apply_customer_default_after_saved_fields() -> None:
    for src, end in (
        (WB, "\ndef persist_order_stickers_batch"),
        (OZ, "\ndef list_supply_driver_options"),
    ):
        prefill = _prefill(src, end)
        merge = prefill.split("ttn_cargo.apply_fbs_customer_shipper_default", 1)
        assert len(merge) == 2
        assert '"customer_party_id"' in merge[0]
        assert "existing_record" in merge[0]


def test_new_form_copies_shipper_legal_entity() -> None:
    record = {
        "legal_entity_id": 14,
        "shipper_type": "le",
        "customer_party_type": "",
        "customer_party_id": 0,
        "customer_services": "",
    }
    apply_fbs_customer_shipper_default(record)
    assert record["customer_party_type"] == "le"
    assert record["customer_party_id"] == 14


def test_missing_shipper_leaves_customer_empty() -> None:
    record = {"legal_entity_id": 0, "shipper_type": "le"}
    apply_fbs_customer_shipper_default(record)
    assert "customer_party_id" not in record


def test_saved_customer_is_not_replaced() -> None:
    record = {
        "legal_entity_id": 14,
        "shipper_type": "le",
        "customer_party_type": "le",
        "customer_party_id": 9,
        "customer_services": "",
    }
    apply_fbs_customer_shipper_default(record)
    assert record["customer_party_id"] == 9


def test_saved_free_text_customer_is_not_replaced() -> None:
    record = {
        "legal_entity_id": 14,
        "shipper_type": "le",
        "customer_services": "ООО Ромашка, Москва",
    }
    apply_fbs_customer_shipper_default(record)
    assert "customer_party_type" not in record


def test_contractor_shipper_is_not_copied_into_le_only_field() -> None:
    record = {
        "legal_entity_id": 3,
        "shipper_type": "contractor",
    }
    apply_fbs_customer_shipper_default(record)
    assert "customer_party_id" not in record
