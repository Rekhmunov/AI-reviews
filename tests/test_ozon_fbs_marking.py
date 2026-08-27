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


def test_posting_requires_marking_from_requirements_sku() -> None:
    row = {
        "is_mandatory_mark": False,
        "raw_json": (
            '{"requirements":{"products_requiring_mandatory_mark":["555"]},'
            '"products":[{"sku":555,"quantity":1}]}'
        ),
    }
    assert oz.posting_requires_marking(row) is True


def test_enrich_posting_marking_from_is_required() -> None:
    posting = {
        "posting_number": "0123604587-1235-1",
        "products": [{"sku": 3722013683, "quantity": 1, "offer_id": "ART"}],
    }
    client = MagicMock()
    client.mandatory_mark_is_required.return_value = [
        {"sku": 3722013683, "is_required": True}
    ]
    out = oz.enrich_posting_marking_flags(client, posting)
    req = out.get("requirements") or {}
    assert "3722013683" in (req.get("products_requiring_mandatory_mark") or [])
    client.product_exemplar_create_or_get.assert_not_called()
    assert oz.posting_requires_marking(
        {"is_mandatory_mark": False, "raw_json": __import__("json").dumps(out)}
    )


def test_enrich_posting_marking_is_required_false_skips_marking() -> None:
    posting = {
        "posting_number": "0114598183-0259-1",
        "products": [{"sku": 752040595, "quantity": 1}],
    }
    client = MagicMock()
    client.mandatory_mark_is_required.return_value = [
        {"sku": 752040595, "is_required": False}
    ]
    out = oz.enrich_posting_marking_flags(client, posting)
    client.product_exemplar_create_or_get.assert_not_called()
    assert oz.posting_requires_marking(
        {"is_mandatory_mark": False, "raw_json": __import__("json").dumps(out)}
    ) is False


def test_enrich_posting_marking_marketplace_buyout_checks_is_required() -> None:
    posting = {
        "posting_number": "0163799058-0084-1",
        "products": [
            {
                "sku": 3722013683,
                "quantity": 1,
                "offer_id": "OOO_Uzori_180x200x30",
                "is_marketplace_buyout": True,
            }
        ],
    }
    client = MagicMock()
    client.mandatory_mark_is_required.return_value = [
        {"sku": 3722013683, "is_required": True}
    ]
    out = oz.enrich_posting_marking_flags(client, posting)
    client.mandatory_mark_is_required.assert_called_once_with(
        "0163799058-0084-1", [3722013683]
    )
    client.product_exemplar_create_or_get.assert_not_called()
    req = out.get("requirements") or {}
    assert "3722013683" in (req.get("products_requiring_mandatory_mark") or [])
    assert oz.posting_requires_marking(
        {"is_mandatory_mark": False, "raw_json": __import__("json").dumps(out)}
    )


def test_enrich_posting_marking_from_exemplar_fallback() -> None:
    posting = {
        "posting_number": "38972162-0286-1",
        "products": [{"sku": 3722013683, "quantity": 1, "offer_id": "ART"}],
    }
    client = MagicMock()
    client.mandatory_mark_is_required.side_effect = RuntimeError("403")
    client.product_exemplar_create_or_get.return_value = {
        "products": [{"product_id": 3722013683, "is_mandatory_mark_needed": True}]
    }
    out = oz.enrich_posting_marking_flags(client, posting)
    req = out.get("requirements") or {}
    assert "3722013683" in (req.get("products_requiring_mandatory_mark") or [])


def test_posting_requires_marking_mandatory_mark_array() -> None:
    row = {
        "is_mandatory_mark": False,
        "raw_json": (
            '{"products":[{"sku":777,"quantity":1,"mandatory_mark":["010460"]}]}'
        ),
    }
    assert oz.posting_requires_marking(row) is True


def test_posting_requires_marking_from_products_json() -> None:
    row = {
        "is_mandatory_mark": False,
        "raw_json": "{}",
        "products_json": (
            '[{"sku":888,"quantity":1,"mandatory_mark":true}]'
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
                "is_mandatory_mark": True,
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
