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
    req = out.get("requirements") or {}
    assert req.get("marking_is_required_checked") is True
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


def test_enrich_posting_marking_light_skips_exemplar_fallback() -> None:
    posting = {
        "posting_number": "38972162-0286-1",
        "products": [{"sku": 3722013683, "quantity": 1, "offer_id": "ART"}],
    }
    client = MagicMock()
    client.mandatory_mark_is_required.side_effect = RuntimeError("403")
    out = oz.enrich_posting_marking_flags_light(client, posting)
    client.product_exemplar_create_or_get.assert_not_called()
    client.product_exemplar_create_or_get_v5.assert_not_called()
    req = out.get("requirements") or {}
    assert req.get("marking_is_required_checked") is True
    assert oz.posting_requires_marking(
        {"is_mandatory_mark": False, "raw_json": __import__("json").dumps(out)}
    ) is False


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


def test_catalog_requires_kiz_match_offer_then_sku() -> None:
    m = {"white27": True, "752039906": True}
    assert oz.catalog_requires_kiz(offer_id="white27", sku="1", requires_kiz_map=m)
    assert oz.catalog_requires_kiz(offer_id="OTHER", sku="752039906", requires_kiz_map=m)
    assert oz.catalog_requires_kiz(offer_id="WHITE27", sku="", requires_kiz_map=m)
    assert not oz.catalog_requires_kiz(offer_id="x", sku="y", requires_kiz_map=m)
    assert not oz.catalog_requires_kiz(offer_id="white27", sku="1", requires_kiz_map={})


def test_posting_requires_marking_from_catalog_map() -> None:
    row = {
        "offer_id": "white27",
        "sku": "752039906",
        "raw_json": (
            '{"products":[{"sku":752039906,"quantity":2,"offer_id":"white27"},'
            '{"sku":1,"quantity":1,"offer_id":"whitebort"}]}'
        ),
    }
    assert oz.posting_requires_marking(row, requires_kiz_map={"white27": True}) is True
    assert oz.posting_requires_marking(row, requires_kiz_map={}) is False
    row_api = {
        "raw_json": (
            '{"requirements":{"products_requiring_mandatory_mark":["752039906"]},'
            '"products":[{"sku":752039906,"quantity":1,"offer_id":"white27"}]}'
        ),
    }
    assert oz.posting_requires_marking(row_api, requires_kiz_map={}) is False
    assert oz.posting_marking_quantity(row, requires_kiz_map={"white27": True}) == 2
    marked = oz.marked_products_for_posting(
        {
            "products": [
                {"sku": 752039906, "quantity": 2, "offer_id": "white27"},
                {"sku": 1, "quantity": 1, "offer_id": "whitebort"},
            ]
        },
        requires_kiz_map={"white27": True},
    )
    assert len(marked) == 1
    assert marked[0]["product_id"] == 752039906
    assert marked[0]["quantity"] == 2


def test_apply_catalog_marking_flags_sets_requirements() -> None:
    posting = {
        "posting_number": "P-1",
        "products": [
            {"sku": 10, "quantity": 1, "offer_id": "need"},
            {"sku": 20, "quantity": 1, "offer_id": "skip"},
        ],
        "requirements": {"products_requiring_mandatory_mark": ["20"]},
    }
    out = oz.apply_catalog_marking_flags(posting, {"need": True})
    req = out.get("requirements") or {}
    assert req.get("products_requiring_mandatory_mark") == ["10"]
    assert req.get("marking_is_required_checked") is True


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


def test_clean_open_kiz_codes_drops_empty_extras() -> None:
    from review_processor.ozon_fbs_marking import clean_open_kiz_codes

    assert clean_open_kiz_codes(["", ""]) == [""]
    assert clean_open_kiz_codes(["", "", ""]) == [""]
    assert clean_open_kiz_codes(["CODE", ""]) == ["CODE"]
    assert clean_open_kiz_codes(["A", "B"]) == ["A", "B"]
    assert clean_open_kiz_codes(["A", "B", ""]) == ["A", "B"]
    assert clean_open_kiz_codes([]) == [""]


def test_build_marking_payload_no_qty_empty_padding() -> None:
    detail = {
        "supply_id": "OZ-1",
        "orders": [
            {
                "posting_number": "Q-2",
                "kiz_required": True,
                "kiz_quantity": 2,
                "product_name": "x2",
                "offer_id": "ART",
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
            return_value={},
        ),
    ):
        payload = build_marking_payload(
            MagicMock(), user_id=1, source_id=2, supply_id="OZ-1", resolve_kiz=False
        )
    assert payload["rows"][0]["quantity"] == 2
    assert payload["rows"][0]["kiz_codes"] == [""]


def test_build_marking_payload_keeps_filled_codes() -> None:
    detail = {
        "supply_id": "OZ-1",
        "orders": [
            {
                "posting_number": "Q-2",
                "kiz_required": True,
                "kiz_quantity": 2,
                "product_name": "x2",
                "offer_id": "ART",
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
                "Q-2": {
                    "codes": ["AAA", "BBB", ""],
                    "saved_at": "2026-01-01T00:00:00+00:00",
                    "ozon_synced": False,
                }
            },
        ),
    ):
        payload = build_marking_payload(
            MagicMock(), user_id=1, source_id=2, supply_id="OZ-1", resolve_kiz=False
        )
    assert payload["rows"][0]["kiz_codes"] == ["AAA", "BBB"]
