"""Tests for Ozon FBS marking detection and payload."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz
from review_processor.ozon_fbs_marking import build_marking_payload


def test_posting_requires_marking_from_flag() -> None:
    assert oz.posting_requires_marking({"is_mandatory_mark": True}) is True


def test_posting_requires_marking_from_raw_json() -> None:
    row = {
        "is_mandatory_mark": False,
        "raw_json": (
            '{"requirements":{"products_requiring_mandatory_mark":[1]},'
            '"products":[{"sku":123,"quantity":1,"mandatory_mark":true}]}'
        ),
    }
    assert oz.posting_requires_marking(row) is True


def test_posting_requires_marking_false() -> None:
    row = {
        "is_mandatory_mark": False,
        "raw_json": '{"products":[{"sku":123,"quantity":1}]}',
    }
    assert oz.posting_requires_marking(row) is False


def test_posting_requires_marking_from_optional_possible_mark() -> None:
    row = {
        "is_mandatory_mark": False,
        "raw_json": (
            '{"optional":{"products_with_possible_mandatory_mark":[{"sku":3722013683}]},'
            '"products":[{"sku":3722013683,"quantity":1}]}'
        ),
    }
    assert oz.posting_requires_marking(row) is True


def test_posting_requires_marking_mandatory_mark_list() -> None:
    row = {
        "is_mandatory_mark": False,
        "raw_json": (
            '{"products":[{"sku":123,"quantity":1,"mandatory_mark":["010460..."]}]}'
        ),
    }
    assert oz.posting_requires_marking(row) is True


def test_marking_quantity_from_requirements_sku() -> None:
    row = {
        "is_mandatory_mark": False,
        "quantity": 1,
        "raw_json": (
            '{"requirements":{"products_requiring_mandatory_mark":["123"]},'
            '"products":[{"sku":123,"quantity":2}]}'
        ),
    }
    assert oz.posting_marking_quantity(row) == 2


def test_enrich_posting_marking_from_exemplar() -> None:
    from unittest.mock import MagicMock

    posting = {
        "posting_number": "38972162-0286-1",
        "products": [{"sku": 3722013683, "quantity": 1, "offer_id": "ART"}],
    }
    client = MagicMock()
    client.product_exemplar_create_or_get.return_value = {
        "products": [{"product_id": 3722013683, "is_mandatory_mark_needed": True}]
    }
    out = oz.enrich_posting_marking_flags(client, posting)
    req = out.get("requirements") or {}
    assert "3722013683" in (req.get("products_requiring_mandatory_mark") or [])
    assert oz.posting_requires_marking({"is_mandatory_mark": False, "raw_json": __import__("json").dumps(out)})


def test_marking_quantity_from_products() -> None:
    row = {
        "is_mandatory_mark": False,
        "quantity": 1,
        "raw_json": (
            '{"products":[{"sku":123,"quantity":2,"mandatory_mark":true},'
            '{"sku":124,"quantity":1,"mandatory_mark":true}]}'
        ),
    }
    assert oz.posting_marking_quantity(row) == 3


def test_build_marking_payload_filters_required_only() -> None:
    detail = {
        "supply_id": "OZ-1",
        "orders": [
            {
                "posting_number": "A-1",
                "kiz_required": True,
                "kiz_quantity": 1,
                "product_name": "Бельё",
                "offer_id": "ART1",
                "barcodes": ["2001"],
            },
            {
                "posting_number": "A-2",
                "kiz_required": False,
                "product_name": "Прочее",
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
            return_value={"A-1": {"codes": [], "saved_at": "", "ozon_synced": False}},
        ),
    ):
        payload = build_marking_payload(
            MagicMock(), user_id=1, source_id=2, supply_id="OZ-1"
        )
    assert payload["required_count"] == 1
    assert payload["rows"][0]["posting_number"] == "A-1"
    assert payload["rows"][0]["kiz_codes"] == [""]
