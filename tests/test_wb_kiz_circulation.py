"""Unit tests for WB FBS → ЧЗ KIZ circulation (new block)."""

from __future__ import annotations

import base64
import json
from datetime import date, datetime, timezone
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


def test_initial_status_withdraw_without_fiscal_is_pending_other() -> None:
    w = circ._normalize_row(
        {"operation_type_id": 1, "excise_short": "Y", "srid": "s2"}
    )
    assert w is not None
    st, reason = circ._initial_status(w)
    assert st == circ.STATUS_PENDING
    assert reason == circ.SKIP_NO_FISCAL


def test_is_no_fiscal_reason_accepts_legacy_russian() -> None:
    assert circ._is_no_fiscal_reason("no_fiscal")
    assert circ._is_no_fiscal_reason("нет номера/даты чека")
    assert circ._is_no_fiscal_reason("нет чека")
    assert not circ._is_no_fiscal_reason("other")


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


@patch(
    "review_processor.wb_kiz_circulation._close_deduped_prepare_events",
    return_value=0,
)
@patch(
    "review_processor.wb_kiz_circulation._load_sent_cis_identities",
    return_value=set(),
)
@patch("review_processor.wb_kiz_circulation.list_events_for_chz")
@patch(
    "review_processor.wb_kiz_circulation.repair_circulation_queue",
    return_value={"returns_fixed": 0, "withdraw_skipped": 0},
)
@patch("review_processor.wb_kiz_circulation.get_chz_settings")
def test_prepare_groups_by_receipt(
    mock_settings, _repair, mock_list, _sent, _close
) -> None:
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


@patch(
    "review_processor.wb_kiz_circulation._close_deduped_prepare_events",
    return_value=0,
)
@patch(
    "review_processor.wb_kiz_circulation._load_sent_cis_identities",
    return_value=set(),
)
@patch("review_processor.wb_kiz_circulation.list_events_for_chz")
@patch(
    "review_processor.wb_kiz_circulation.repair_circulation_queue",
    return_value={"returns_fixed": 0, "withdraw_skipped": 0},
)
@patch("review_processor.wb_kiz_circulation.get_chz_settings")
def test_prepare_soft_skips_withdraw_without_kpp_keeps_returns(
    mock_settings, _repair, mock_list, _sent, _close
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
    assert "юр. лица" in out["warnings"][0]
    assert not any(d["doc_type"] == "LK_RECEIPT" for d in out["documents"])


@patch(
    "review_processor.wb_kiz_circulation._close_deduped_prepare_events",
    return_value=0,
)
@patch(
    "review_processor.wb_kiz_circulation._load_sent_cis_identities",
    return_value=set(),
)
@patch("review_processor.wb_kiz_circulation.list_events_for_chz")
@patch(
    "review_processor.wb_kiz_circulation.repair_circulation_queue",
    return_value={"returns_fixed": 0, "withdraw_skipped": 0, "withdraw_requeued": 0},
)
@patch("review_processor.wb_kiz_circulation.get_chz_settings")
def test_prepare_nofiscal_withdraw_uses_other_primary_doc(
    mock_settings, _repair, mock_list, _sent, _close
) -> None:
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
    mock_list.return_value = [
        {
            "event_key": "k-nofiscal",
            "operation_type": 1,
            "excise_short": "cis-nofiscal",
            "fiscal_doc_number": "",
            "fiscal_dt": "",
            "skip_reason": "no_fiscal",
            "status": "pending",
            "price": 15,
            "currency_name": "RUB",
        }
    ]
    out = circ.prepare_chz_batches(repo=object(), user_id=1, source_id=2)
    assert out["counts"]["withdraw_events"] == 1
    assert out["counts"]["skipped"] == 0
    withdraw = next(d for d in out["documents"] if d["doc_type"] == "LK_RECEIPT")
    body = withdraw["product_document"]
    assert body["action"] == "DISTANCE"
    assert body["document_type"] == "OTHER"
    assert body["primary_document_custom_name"] == "Без документа основания"
    assert body["document_number"].startswith("WB-NOFISCAL-")
    assert "OTHER" in withdraw["title"] or "без чека" in withdraw["title"].lower()


def test_build_lk_receipt_other_includes_custom_name() -> None:
    from review_processor.chz_true_api import build_lk_receipt_document

    doc = build_lk_receipt_document(
        inn="7707083893",
        document_number="WB-1",
        document_date="2026-08-14",
        primary_document_type="OTHER",
        primary_document_custom_name="Без документа основания",
        products=[{"cis": "X"}],
        kpp="1",
        fias_id="f",
    )
    assert doc["document_type"] == "OTHER"
    assert doc["primary_document_custom_name"] == "Без документа основания"


@patch(
    "review_processor.wb_kiz_circulation._close_deduped_prepare_events",
    return_value=0,
)
@patch(
    "review_processor.wb_kiz_circulation._load_sent_cis_identities",
    return_value=set(),
)
@patch("review_processor.wb_kiz_circulation.list_events_for_chz")
@patch(
    "review_processor.wb_kiz_circulation.repair_circulation_queue",
    return_value={"returns_fixed": 0, "withdraw_skipped": 0},
)
@patch("review_processor.wb_kiz_circulation.get_chz_settings")
def test_prepare_chunks_returns(mock_settings, _repair, mock_list, _sent, _close) -> None:
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
        with patch.object(
            circ,
            "get_chz_settings",
            return_value={
                "api_base": "prod",
                "kpp": "",
                "fias_id": "",
                "return_type": "REMOTE_SALE_RETURN",
                "cert_thumbprint": "",
            },
        ):
            with pytest.raises(ValueError, match="не число"):
                circ.upsert_chz_settings(
                    repo,
                    user_id=1,
                    product_group="8",
                    participant_inn="1",
                )


def test_resolve_excise_period_uses_exact_dates_no_ceiling() -> None:
    period = circ.resolve_excise_period(
        date_from="2025-01-01", date_to="2026-08-13"
    )
    assert period["date_from"] == "2025-01-01"
    assert period["date_to"] == "2026-08-13"
    assert period["days"] == (date.fromisoformat("2026-08-13") - date.fromisoformat("2025-01-01")).days + 1

    swapped = circ.resolve_excise_period(
        date_from="2026-08-13", date_to="2026-08-01"
    )
    assert swapped["date_from"] == "2026-08-01"
    assert swapped["date_to"] == "2026-08-13"

    with pytest.raises(ValueError, match="Укажите даты"):
        circ.resolve_excise_period(date_from="", date_to="2026-08-13")


def test_format_wb_excise_http_error_429() -> None:
    err = circ.format_wb_excise_http_error(
        code=429, body='{"status":429}', retry_after="1800"
    )
    assert "10 запросов" in str(err)
    assert "30 мин" in str(err)
    err2 = circ.format_wb_excise_http_error(code=403, body="forbidden")
    assert "HTTP 403" in str(err2)
    assert "forbidden" in str(err2)


def test_wb_analytics_key_encrypt_roundtrip_and_mask() -> None:
    from review_processor.security import encrypt_secret, mask_secret

    plain = "eyJhbGciOiJFUzI1NiJ9.analytics-test-token"
    enc = encrypt_secret(plain)
    assert enc and enc != plain
    assert circ._decrypt_wb_analytics_key(
        {"wb_analytics_api_key_encrypted": enc}
    ) == plain
    assert circ._decrypt_wb_analytics_key({"wb_analytics_api_key_encrypted": ""}) == ""
    preview = mask_secret(plain)
    assert preview
    assert plain not in preview


def test_get_wb_analytics_api_key_reads_encrypted() -> None:
    from review_processor.security import encrypt_secret

    plain = "wb-analytics-secret"
    enc = encrypt_secret(plain)
    row = {"wb_analytics_api_key_encrypted": enc}
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    conn.execute.return_value.fetchone.return_value = row
    repo = MagicMock()
    repo._connect.return_value = conn
    repo._sql.side_effect = lambda q: q
    repo._row_to_dict.side_effect = lambda r: r
    with patch.object(circ, "ensure_kiz_circulation_tables"):
        assert circ.get_wb_analytics_api_key(repo, user_id=7) == plain


def test_parse_inn_kpp_from_requisites() -> None:
    inn, kpp = circ._parse_inn_kpp_from_text("ИНН 7707083893 КПП 770701001")
    assert inn == "7707083893"
    assert kpp == "770701001"


def test_resolve_chz_place_from_legal() -> None:
    repo = MagicMock()
    repo.list_supply_legal_entities.return_value = [
        {
            "requisites": "ИНН 7707083893 / КПП 770701001",
            "addr_fias": "0c5b2444-70a0-4932-980c-b4dc0d3f02b5",
            "short_name": "ООО Тест",
        }
    ]
    place = circ.resolve_chz_place_details(
        repo, user_id=1, participant_inn="7707083893"
    )
    assert place["kpp"] == "770701001"
    assert place["fias_id"] == "0c5b2444-70a0-4932-980c-b4dc0d3f02b5"


def test_attach_order_ids_to_events_via_srid() -> None:
    events = [
        {"srid": "eAC.abc.0.0", "rid": ""},
        {"srid": "missing", "rid": ""},
        {"srid": "", "rid": "eAC.abc.0.0"},
    ]
    with patch("review_processor.wb_fbs.order_ids_by_srids") as lookup, patch(
        "review_processor.wb_fbs.load_order_status_map"
    ) as status_map:
        lookup.return_value = {"eAC.abc.0.0": 3291847561}
        status_map.return_value = {
            3291847561: {
                "supplier_status": "complete",
                "wb_status": "sold",
                "cancel_reason_label": "",
                "order_status_label": "Выкуплен",
            }
        }
        circ._attach_order_ids_to_events(
            MagicMock(), user_id=1, source_id=2, events=events
        )
    assert events[0]["order_id"] == 3291847561
    assert events[0]["order_status_label"] == "Выкуплен"
    assert events[0]["order_wb_status"] == "sold"
    assert events[1]["order_id"] is None
    assert events[1]["order_status_label"] == ""
    assert events[2]["order_id"] == 3291847561
    assert events[2]["order_status_label"] == "Выкуплен"
    called_srids = lookup.call_args.kwargs["srids"]
    assert "eAC.abc.0.0" in called_srids
    assert "missing" in called_srids


def test_order_portal_status_label() -> None:
    from review_processor.wb_fbs import order_portal_status_label

    assert order_portal_status_label(wb_status="sold") == "Выкуплен"
    assert order_portal_status_label(wb_status="canceled_by_client") == "Клиент отказался"
    assert order_portal_status_label(supplier_status="confirm") == "На сборке"
    assert order_portal_status_label(supplier_status="complete") == "В доставке"
    assert order_portal_status_label(supplier_status="new") == "Новый"


def test_cis_identity_ignores_fiscal() -> None:
    a = circ._cis_identity(
        srid="s1", rid="", excise_short="CIS", operation_type=1
    )
    b = circ._cis_identity(
        srid="s1", rid="r1", excise_short="CIS", operation_type=1
    )
    # rid is ignored when srid is present
    assert a == b
    assert a != circ._cis_identity(
        srid="s2", rid="", excise_short="CIS", operation_type=1
    )


def test_resolve_sync_upgrade_late_fiscal() -> None:
    nofiscal = {
        "id": 10,
        "event_key": "key-nofiscal",
        "status": circ.STATUS_PENDING,
        "fiscal_doc_number": "",
        "fiscal_dt": "",
        "srid": "s1",
        "excise_short": "CIS",
        "operation_type": 1,
    }
    incoming = {
        "event_key": "key-with-fiscal",
        "fiscal_doc_number": "99",
        "fiscal_dt": "2026-08-01",
        "srid": "s1",
        "excise_short": "CIS",
        "operation_type": 1,
    }
    action, target = circ._resolve_sync_action([nofiscal], norm=incoming)
    assert action == "upgrade"
    assert target is nofiscal


def test_resolve_sync_suppress_when_already_submitted() -> None:
    sent = {
        "id": 11,
        "event_key": "key-nofiscal",
        "status": circ.STATUS_SUBMITTED,
        "fiscal_doc_number": "",
        "fiscal_dt": "",
        "chz_doc_id": "doc-1",
    }
    incoming = {
        "event_key": "key-with-fiscal",
        "fiscal_doc_number": "99",
        "fiscal_dt": "2026-08-01",
    }
    action, target = circ._resolve_sync_action([sent], norm=incoming)
    assert action == "suppress"
    assert target is sent


def test_resolve_sync_suppress_nofiscal_when_fiscal_open() -> None:
    fiscal = {
        "id": 12,
        "event_key": "key-fiscal",
        "status": circ.STATUS_PENDING,
        "fiscal_doc_number": "1",
        "fiscal_dt": "2026-08-01",
    }
    incoming = {
        "event_key": "key-nofiscal",
        "fiscal_doc_number": "",
        "fiscal_dt": "",
    }
    action, _ = circ._resolve_sync_action([fiscal], norm=incoming)
    assert action == "suppress"


def test_resolve_sync_upsert_same_key() -> None:
    row = {
        "id": 1,
        "event_key": "same",
        "status": circ.STATUS_PENDING,
        "fiscal_doc_number": "1",
        "fiscal_dt": "2026-08-01",
    }
    action, target = circ._resolve_sync_action(
        [row], norm={"event_key": "same", "fiscal_doc_number": "1", "fiscal_dt": "2026-08-01"}
    )
    assert action == "upsert"
    assert target is row


def test_dedupe_events_prefers_fiscal_and_skips_already_sent() -> None:
    sent = {("s1", "CIS", 1)}
    nofiscal = {
        "event_key": "a",
        "srid": "s1",
        "rid": "",
        "excise_short": "CIS",
        "operation_type": 1,
        "fiscal_doc_number": "",
        "fiscal_dt": "",
    }
    fiscal = {
        "event_key": "b",
        "srid": "s1",
        "rid": "",
        "excise_short": "CIS",
        "operation_type": 1,
        "fiscal_doc_number": "7",
        "fiscal_dt": "2026-08-01",
    }
    other = {
        "event_key": "c",
        "srid": "s1",
        "rid": "",
        "excise_short": "CIS",
        "operation_type": 1,
        "fiscal_doc_number": "8",
        "fiscal_dt": "2026-08-02",
        "status": "pending",
    }
    kept, skipped = circ._dedupe_events_for_prepare(
        [nofiscal, fiscal], sent_identities=set()
    )
    assert len(kept) == 1
    assert kept[0]["event_key"] == "b"
    assert any(s.get("skip_reason") == "duplicate_nofiscal" for s in skipped)

    kept2, skipped2 = circ._dedupe_events_for_prepare([other], sent_identities=sent)
    assert kept2 == []
    assert skipped2[0]["skip_reason"] == "already_sent"


@patch(
    "review_processor.wb_kiz_circulation._close_deduped_prepare_events",
    return_value=0,
)
@patch(
    "review_processor.wb_kiz_circulation._load_sent_cis_identities",
)
@patch("review_processor.wb_kiz_circulation.list_events_for_chz")
@patch(
    "review_processor.wb_kiz_circulation.repair_circulation_queue",
    return_value={"returns_fixed": 0, "withdraw_skipped": 0},
)
@patch("review_processor.wb_kiz_circulation.get_chz_settings")
def test_prepare_skips_already_sent_identity(
    mock_settings, _repair, mock_list, mock_sent, _close
) -> None:
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
    mock_sent.return_value = {("s1", "cis-a", 1)}
    mock_list.return_value = [
        {
            "event_key": "dup",
            "operation_type": 1,
            "srid": "s1",
            "rid": "",
            "excise_short": "cis-a",
            "fiscal_doc_number": "11",
            "fiscal_dt": "2026-08-10",
            "price": 10,
            "currency_name": "RUB",
            "status": "pending",
        }
    ]
    out = circ.prepare_chz_batches(repo=object(), user_id=1, source_id=2)
    assert out["counts"]["documents"] == 0
    assert out["counts"]["skipped"] == 1
    assert out["skipped"][0]["skip_reason"] == "already_sent"


def test_retention_cutoff_roughly_six_months() -> None:
    assert circ.EVENT_RETENTION_DAYS == 180
    cutoff = circ._retention_cutoff_iso()
    assert cutoff < datetime.now(timezone.utc).isoformat()
    # ~6 months ago (± a few days)
    from datetime import timedelta

    expected = (datetime.now(timezone.utc) - timedelta(days=180)).date()
    assert cutoff[:10] == expected.isoformat()


def test_cis_anchor_prefers_srid() -> None:
    assert circ._cis_anchor(srid="s1", rid="r1") == "s1"
    assert circ._cis_anchor(srid="", rid="r1") == "r1"


def test_upsert_sent_cis_rows_writes_registry() -> None:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    repo = MagicMock()
    repo._connect.return_value = conn
    repo._sql.side_effect = lambda q: q
    with patch.object(circ, "ensure_kiz_circulation_tables"):
        n = circ.upsert_sent_cis_rows(
            repo,
            user_id=1,
            source_id=2,
            rows=[
                {
                    "excise_short": "CIS1",
                    "operation_type": 1,
                    "srid": "s1",
                    "rid": "",
                    "chz_doc_id": "doc-9",
                    "event_key": "ek",
                    "fiscal_doc_number": "1",
                    "fiscal_dt": "2026-01-01",
                }
            ],
            accepted_at="2026-08-14T00:00:00+00:00",
        )
    assert n == 1
    assert conn.execute.called
    sql = conn.execute.call_args.args[0]
    assert "wb_kiz_sent_cis" in sql


def test_load_sent_cis_merges_registry() -> None:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    # First execute → events; second → registry
    ev_rows = [{"srid": "s1", "rid": "", "excise_short": "A", "operation_type": 1}]
    reg_rows = [{"anchor": "s2", "excise_short": "B", "operation_type": 2}]
    ev_result = MagicMock()
    ev_result.fetchall.return_value = ev_rows
    reg_result = MagicMock()
    reg_result.fetchall.return_value = reg_rows
    conn.execute.side_effect = [ev_result, reg_result]
    repo = MagicMock()
    repo._connect.return_value = conn
    repo._sql.side_effect = lambda q: q
    repo._row_to_dict.side_effect = lambda r: r
    with patch.object(circ, "ensure_kiz_circulation_tables"):
        out = circ._load_sent_cis_identities(repo, user_id=1, source_id=2)
    assert ("s1", "A", 1) in out
    assert ("s2", "B", 2) in out


def test_maintain_storage_calls_purge_helpers() -> None:
    repo = MagicMock()
    with patch.object(circ, "clear_accepted_raw_json", return_value=3) as c1, patch.object(
        circ, "purge_old_kiz_circulation_events", return_value=5
    ) as c2, patch.object(
        circ, "purge_old_kiz_runs_and_docs", return_value={"runs": 1, "docs": 2}
    ) as c3, patch.object(
        circ, "_mark_storage_maintained"
    ) as c4, patch.object(
        circ, "get_cursor", return_value={"last_storage_at": ""}
    ):
        out = circ.maintain_kiz_circulation_storage(
            repo, user_id=1, source_id=2, force=True
        )
    assert out == {
        "raw_json_cleared": 3,
        "events_purged": 5,
        "runs_purged": 1,
        "docs_purged": 2,
        "skipped": 0,
    }
    c1.assert_called_once()
    c2.assert_called_once()
    c3.assert_called_once()
    c4.assert_called_once()


def test_maintain_storage_throttles_when_recent() -> None:
    repo = MagicMock()
    recent = datetime.now(timezone.utc).isoformat()
    with patch.object(
        circ, "get_cursor", return_value={"last_storage_at": recent}
    ), patch.object(circ, "clear_accepted_raw_json") as clear:
        out = circ.maintain_kiz_circulation_storage(repo, user_id=1, source_id=2)
    assert out["skipped"] == 1
    clear.assert_not_called()


@patch(
    "review_processor.wb_kiz_circulation._close_deduped_prepare_events",
    return_value=0,
)
@patch(
    "review_processor.wb_kiz_circulation._load_sent_cis_identities",
    return_value=set(),
)
@patch("review_processor.wb_kiz_circulation.list_events_for_chz")
@patch(
    "review_processor.wb_kiz_circulation.repair_circulation_queue",
    return_value={"returns_fixed": 0, "withdraw_skipped": 0},
)
@patch("review_processor.wb_kiz_circulation.get_chz_settings")
def test_prepare_caps_documents_per_round(
    mock_settings, _repair, mock_list, _sent, _close, monkeypatch
) -> None:
    """UKЭP signs one doc at a time — prepare must not return huge batches."""
    monkeypatch.setattr(circ, "CHZ_DOCUMENTS_PER_PREPARE", 3)
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
    mock_list.return_value = [
        {
            "event_key": f"k{i}",
            "operation_type": 1,
            "excise_short": f"cis-{i}",
            "fiscal_doc_number": str(100 + i),
            "fiscal_dt": "2026-08-10",
            "price": 10,
            "currency_name": "RUB",
            "status": "pending",
        }
        for i in range(10)
    ]
    out = circ.prepare_chz_batches(repo=object(), user_id=1, source_id=2)
    assert out["counts"]["documents_built"] == 10
    assert out["counts"]["documents_cap"] == 3
    assert out["counts"]["documents"] == 3
    assert out["counts"]["withdraw_events"] == 3
    assert len(out["documents"]) == 3
    assert out["has_more"] is True
    # Oldest-first: first three receipt numbers from the batch.
    titles = [d["title"] for d in out["documents"]]
    assert "чек 100" in titles[0]
    assert "чек 101" in titles[1]
    assert "чек 102" in titles[2]
