"""Unit tests for WB FBS → ЧЗ KIZ circulation (new block)."""

from __future__ import annotations

from unittest.mock import patch

from review_processor.chz_true_api import (
    DEMO_BASE,
    PROD_BASE,
    ChzTrueApiClient,
    build_lk_receipt_document,
    build_lp_return_document,
)
from review_processor import wb_kiz_circulation as circ


def test_event_key_stable() -> None:
    a = circ._event_key(
        srid="s1",
        excise_short="01046",
        operation_type=1,
        fiscal_doc_number="123",
        fiscal_dt="2026-08-01",
    )
    b = circ._event_key(
        srid="s1",
        excise_short="01046",
        operation_type=1,
        fiscal_doc_number="123",
        fiscal_dt="2026-08-01",
    )
    c = circ._event_key(
        srid="s1",
        excise_short="01046",
        operation_type=2,
        fiscal_doc_number="123",
        fiscal_dt="2026-08-01",
    )
    assert a == b
    assert a != c
    assert len(a) == 40


def test_normalize_row_withdraw() -> None:
    row = {
        "operation_type_id": 1,
        "excise_short": "0104670172422724215ABC",
        "srid": "srid-1",
        "fiscal_doc_number": "77",
        "fiscal_dt": "2026-08-10T12:00:00",
        "price": 1990.5,
        "nm_id": 123,
    }
    norm = circ._normalize_row(row)
    assert norm is not None
    assert norm["operation_type"] == 1
    assert norm["fiscal_dt"] == "2026-08-10"
    assert norm["price"] == 1990.5
    assert norm["event_key"]


def test_normalize_row_skips_unknown_op() -> None:
    assert circ._normalize_row({"operation_type_id": 9, "excise_short": "x"}) is None
    assert circ._normalize_row({"operation_type_id": 1, "excise_short": ""}) is None


def test_build_lk_receipt_and_return() -> None:
    receipt = build_lk_receipt_document(
        inn="7707083893",
        document_number="100",
        document_date="2026-08-10",
        products=[{"cis": "01046", "product_cost": 100.0}],
        kpp="770701001",
    )
    assert receipt["action"] == "DISTANCE"
    assert receipt["kpp"] == "770701001"
    assert len(receipt["products"]) == 1

    ret = build_lp_return_document(
        inn="7707083893",
        products=[{"cis": "01046"}],
    )
    assert ret["return_type"] == "REMOTE_SALE_RETURN"


def test_chz_client_base_urls() -> None:
    assert ChzTrueApiClient().base == PROD_BASE
    assert ChzTrueApiClient(base_url="demo").base == DEMO_BASE
    assert ChzTrueApiClient(base_url=DEMO_BASE).base == DEMO_BASE


@patch("review_processor.wb_kiz_circulation.list_events")
@patch("review_processor.wb_kiz_circulation.get_chz_settings")
def test_prepare_groups_by_receipt(mock_settings, mock_list) -> None:
    mock_settings.return_value = {
        "is_enabled": True,
        "participant_inn": "7707083893",
        "product_group": "8",
        "kpp": "",
        "fias_id": "",
        "return_type": "REMOTE_SALE_RETURN",
        "cert_thumbprint": "",
        "api_base": "prod",
        "api_base_url": PROD_BASE,
    }
    events = [
        {
            "event_key": "k1",
            "operation_type": 1,
            "excise_short": "cis-a",
            "fiscal_doc_number": "11",
            "fiscal_dt": "2026-08-10",
            "price": 10,
            "status": "pending",
        },
        {
            "event_key": "k2",
            "operation_type": 1,
            "excise_short": "cis-b",
            "fiscal_doc_number": "11",
            "fiscal_dt": "2026-08-10",
            "price": 20,
            "status": "pending",
        },
        {
            "event_key": "k3",
            "operation_type": 2,
            "excise_short": "cis-c",
            "fiscal_doc_number": "12",
            "fiscal_dt": "2026-08-11",
            "status": "pending",
        },
    ]

    def _list(_repo, **kwargs):
        if kwargs.get("status") == "pending":
            return list(events)
        return []

    mock_list.side_effect = _list
    out = circ.prepare_chz_batches(repo=object(), user_id=1, source_id=2)
    assert out["counts"]["documents"] == 2
    assert out["counts"]["withdraw_events"] == 2
    assert out["counts"]["return_events"] == 1
    types = {d["doc_type"] for d in out["documents"]}
    assert types == {"LK_RECEIPT", "LP_RETURN"}
    withdraw = next(d for d in out["documents"] if d["doc_type"] == "LK_RECEIPT")
    assert set(withdraw["event_keys"]) == {"k1", "k2"}
    assert withdraw["sign_payload_b64"]
