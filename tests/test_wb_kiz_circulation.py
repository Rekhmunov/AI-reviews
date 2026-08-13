"""Unit tests for WB FBS → ЧЗ KIZ circulation (new block)."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

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
        "currency_name_short": "RUB",
    }
    norm = circ._normalize_row(row)
    assert norm is not None
    assert norm["operation_type"] == 1
    assert norm["fiscal_dt"] == "2026-08-10"
    assert norm["price"] == 1990.5
    assert norm["currency_name"] == "RUB"
    assert norm["event_key"]


def test_normalize_fiscal_number_int() -> None:
    norm = circ._normalize_row(
        {
            "operationTypeId": 1,
            "exciseShort": "X",
            "srid": "s",
            "fiscalDocNumber": 12345,
            "fiscalDt": "2026-01-02",
        }
    )
    assert norm is not None
    assert norm["fiscal_doc_number"] == "12345"


def test_normalize_row_skips_unknown_op() -> None:
    assert circ._normalize_row({"operation_type_id": 9, "excise_short": "x"}) is None
    assert circ._normalize_row({"operation_type_id": 1, "excise_short": ""}) is None


def test_initial_status_return_without_fiscal_is_pending() -> None:
    ret = circ._normalize_row(
        {"operation_type_id": 2, "excise_short": "Y", "srid": "s2"}
    )
    assert ret is not None
    st, reason = circ._initial_status(ret)
    assert st == circ.STATUS_PENDING
    assert reason == ""


def test_initial_status_withdraw_without_fiscal_is_skipped() -> None:
    w = circ._normalize_row(
        {"operation_type_id": 1, "excise_short": "Y", "srid": "s2"}
    )
    assert w is not None
    st, reason = circ._initial_status(w)
    assert st == circ.STATUS_SKIPPED
    assert "чек" in reason


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


def test_create_document_prefers_signed_b64() -> None:
    client = ChzTrueApiClient()
    signed_doc = build_lk_receipt_document(
        inn="1",
        document_number="11",
        document_date="2026-08-10",
        products=[{"cis": "a", "product_cost": 10.0}],
        kpp="1",
        fias_id="f",
    )
    signed_raw = json.dumps(signed_doc, ensure_ascii=False, separators=(",", ":")).encode()
    signed_b64 = base64.b64encode(signed_raw).decode()

    captured: dict = {}

    def fake_request(method, path, *, params=None, body=None, auth=True):
        captured["body"] = body
        return "doc-1"

    client._request = fake_request  # type: ignore[method-assign]
    # Deliberately different product_document that would break signature if used
    broken = json.loads(json.dumps(signed_doc))
    for p in broken["products"]:
        if isinstance(p.get("product_cost"), float) and p["product_cost"].is_integer():
            p["product_cost"] = int(p["product_cost"])

    doc_id = client.create_document(
        doc_type="LK_RECEIPT",
        product_group="lp",
        product_document=broken,
        product_document_b64=signed_b64,
        signature_b64="SIG",
    )
    assert doc_id == "doc-1"
    assert captured["body"]["product_document"] == signed_b64


def test_classify_chz_doc_status() -> None:
    assert circ.classify_chz_doc_status("CHECKED_OK") == circ.STATUS_ACCEPTED
    assert circ.classify_chz_doc_status("CHECKED_NOT_OK") == circ.STATUS_ERROR
    assert circ.classify_chz_doc_status("IN_PROGRESS") == circ.STATUS_SUBMITTED
    assert circ.classify_chz_doc_status("") == circ.STATUS_SUBMITTED


def test_price_for_chz_skips_foreign_currency() -> None:
    assert circ._price_for_chz({"price": 10, "currency_name": "AMD"}) is None
    assert circ._price_for_chz({"price": 10, "currency_name": "RUB"}) == 10.0
    assert circ._price_for_chz({"price": 10, "currency_name": ""}) == 10.0


@patch("review_processor.wb_kiz_circulation.list_events_for_chz")
@patch(
    "review_processor.wb_kiz_circulation.repair_circulation_queue",
    return_value={"returns_fixed": 0, "withdraw_skipped": 0},
)
@patch("review_processor.wb_kiz_circulation.get_chz_settings")
def test_prepare_groups_by_receipt(mock_settings, _repair, mock_list) -> None:
    mock_settings.return_value = {
        "is_enabled": True,
        "participant_inn": "7707083893",
        "product_group": "lp",
        "kpp": "770701001",
        "fias_id": "fias-1",
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
            "currency_name": "RUB",
            "status": "pending",
        },
        {
            "event_key": "k2",
            "operation_type": 1,
            "excise_short": "cis-b",
            "fiscal_doc_number": "11",
            "fiscal_dt": "2026-08-10",
            "price": 20,
            "currency_name": "RUB",
            "status": "pending",
        },
        {
            "event_key": "k3",
            "operation_type": 2,
            "excise_short": "cis-c",
            "fiscal_doc_number": "",
            "fiscal_dt": "",
            "status": "pending",
        },
    ]
    mock_list.return_value = list(events)
    out = circ.prepare_chz_batches(repo=object(), user_id=1, source_id=2)
    assert out["counts"]["documents"] == 2
    assert out["counts"]["withdraw_events"] == 2
    assert out["counts"]["return_events"] == 1
    types = {d["doc_type"] for d in out["documents"]}
    assert types == {"LK_RECEIPT", "LP_RETURN"}
    withdraw = next(d for d in out["documents"] if d["doc_type"] == "LK_RECEIPT")
    assert set(withdraw["event_keys"]) == {"k1", "k2"}
    assert withdraw["sign_payload_b64"]
    # Signed payload must keep float encoding stable for whole numbers
    raw = base64.b64decode(withdraw["sign_payload_b64"])
    assert b"10.0" in raw or b'"product_cost":10' in raw  # either is stable if server uses b64


@patch("review_processor.wb_kiz_circulation.list_events_for_chz")
@patch(
    "review_processor.wb_kiz_circulation.repair_circulation_queue",
    return_value={"returns_fixed": 0, "withdraw_skipped": 0},
)
@patch("review_processor.wb_kiz_circulation.get_chz_settings")
def test_prepare_soft_skips_withdraw_without_kpp_keeps_returns(
    mock_settings, _repair, mock_list
) -> None:
    mock_settings.return_value = {
        "is_enabled": True,
        "participant_inn": "7707083893",
        "product_group": "lp",
        "kpp": "",
        "fias_id": "",
        "return_type": "REMOTE_SALE_RETURN",
        "cert_thumbprint": "",
        "api_base": "prod",
        "api_base_url": PROD_BASE,
    }
    mock_list.return_value = [
        {
            "event_key": "k1",
            "operation_type": 1,
            "excise_short": "cis-a",
            "fiscal_doc_number": "11",
            "fiscal_dt": "2026-08-10",
            "status": "pending",
        },
        {
            "event_key": "r1",
            "operation_type": 2,
            "excise_short": "cis-r",
            "fiscal_doc_number": "",
            "fiscal_dt": "",
            "status": "pending",
        },
    ]
    out = circ.prepare_chz_batches(repo=object(), user_id=1, source_id=2)
    assert out["counts"]["withdraw_events"] == 0
    assert out["counts"]["return_events"] == 1
    assert any(d["doc_type"] == "LP_RETURN" for d in out["documents"])
    assert out["warnings"]
    assert not any(d["doc_type"] == "LK_RECEIPT" for d in out["documents"])


@patch("review_processor.wb_kiz_circulation.list_events_for_chz")
@patch(
    "review_processor.wb_kiz_circulation.repair_circulation_queue",
    return_value={"returns_fixed": 0, "withdraw_skipped": 0},
)
@patch("review_processor.wb_kiz_circulation.get_chz_settings")
def test_prepare_chunks_returns(mock_settings, _repair, mock_list) -> None:
    mock_settings.return_value = {
        "is_enabled": True,
        "participant_inn": "7707083893",
        "product_group": "lp",
        "kpp": "1",
        "fias_id": "f",
        "return_type": "REMOTE_SALE_RETURN",
        "cert_thumbprint": "",
        "api_base": "prod",
        "api_base_url": PROD_BASE,
    }
    events = [
        {
            "event_key": f"r{i}",
            "operation_type": 2,
            "excise_short": f"cis-{i}",
            "fiscal_doc_number": "",
            "fiscal_dt": "",
            "status": "pending",
        }
        for i in range(circ.CHZ_PRODUCTS_PER_DOC + 5)
    ]
    mock_list.return_value = events
    out = circ.prepare_chz_batches(repo=object(), user_id=1, source_id=2)
    returns = [d for d in out["documents"] if d["doc_type"] == "LP_RETURN"]
    assert len(returns) == 2
    assert sum(len(d["event_keys"]) for d in returns) == len(events)


def test_upsert_rejects_numeric_pg() -> None:
    repo = MagicMock()
    with patch.object(circ, "ensure_kiz_circulation_tables"):
        with pytest.raises(ValueError, match="не число"):
            circ.upsert_chz_settings(
                repo,
                user_id=1,
                product_group="8",
                participant_inn="1",
            )
