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


def test_enrich_posting_marking_from_get_requirements() -> None:
    posting = {
        "posting_number": "0123604587-1235-1",
        "products": [{"sku": 3722013683, "quantity": 1, "offer_id": "ART"}],
    }
    client = MagicMock()
    client.get_posting.return_value = {
        "posting_number": "0123604587-1235-1",
        "products": [{"sku": 3722013683, "quantity": 1, "offer_id": "ART"}],
        "requirements": {"products_requiring_mandatory_mark": [3722013683]},
    }
    out = oz.enrich_posting_marking_flags(client, posting)
    req = out.get("requirements") or {}
    assert 3722013683 in (req.get("products_requiring_mandatory_mark") or []) or (
        "3722013683" in (req.get("products_requiring_mandatory_mark") or [])
    )
    assert req.get("marking_check_version") == oz.MARKING_REQUIREMENT_CHECK_VERSION
    client.mandatory_mark_is_required.assert_not_called()
    assert oz.posting_requires_marking(
        {"is_mandatory_mark": False, "raw_json": __import__("json").dumps(out)}
    )


def test_enrich_ignores_is_required_when_get_requirements_empty() -> None:
    """Catalog is-required:true must not force KIZ if posting card has no marks."""
    posting = {
        "posting_number": "0128881603-0039-1",
        "products": [{"sku": 752499939, "quantity": 1, "offer_id": "white23"}],
    }
    client = MagicMock()
    client.get_posting.return_value = {
        "posting_number": "0128881603-0039-1",
        "products": [{"sku": 752499939, "quantity": 1, "offer_id": "white23"}],
        "requirements": {"products_requiring_mandatory_mark": []},
    }
    client.mandatory_mark_is_required.return_value = [
        {"sku": 752499939, "is_required": True}
    ]
    out = oz.enrich_posting_marking_flags(client, posting)
    client.mandatory_mark_is_required.assert_not_called()
    req = out.get("requirements") or {}
    assert req.get("marking_is_required_checked") is True
    assert not (req.get("products_requiring_mandatory_mark") or [])
    assert oz.posting_requires_marking(
        {"is_mandatory_mark": False, "raw_json": __import__("json").dumps(out)}
    ) is False


def test_enrich_posting_marking_empty_get_skips_marking() -> None:
    posting = {
        "posting_number": "0114598183-0259-1",
        "products": [{"sku": 752040595, "quantity": 1}],
    }
    client = MagicMock()
    client.get_posting.return_value = {
        "posting_number": "0114598183-0259-1",
        "products": [{"sku": 752040595, "quantity": 1}],
        "requirements": {"products_requiring_mandatory_mark": []},
    }
    out = oz.enrich_posting_marking_flags(client, posting)
    req = out.get("requirements") or {}
    assert req.get("marking_is_required_checked") is True
    assert oz.posting_requires_marking(
        {"is_mandatory_mark": False, "raw_json": __import__("json").dumps(out)}
    ) is False


def test_enrich_posting_marking_light_marks_checked_when_get_fails() -> None:
    posting = {
        "posting_number": "38972162-0286-1",
        "products": [{"sku": 3722013683, "quantity": 1, "offer_id": "ART"}],
    }
    client = MagicMock()
    client.get_posting.side_effect = RuntimeError("403")
    out = oz.enrich_posting_marking_flags_light(client, posting)
    client.product_exemplar_create_or_get.assert_not_called()
    client.product_exemplar_create_or_get_v5.assert_not_called()
    req = out.get("requirements") or {}
    assert req.get("marking_is_required_checked") is True
    assert req.get("marking_check_version") == oz.MARKING_REQUIREMENT_CHECK_VERSION


def test_old_is_required_cache_not_resolved() -> None:
    posting = {
        "posting_number": "P-1",
        "requirements": {
            "products_requiring_mandatory_mark": ["752499939"],
            "marking_is_required_checked": True,
        },
        "products": [{"sku": 752499939, "quantity": 1}],
    }
    assert oz.posting_marking_flags_resolved(posting) is False


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
