"""Tests for supply source cabinet identity and explicit FBO/FBS channel."""

from __future__ import annotations

import base64
import json

from review_processor import supply_source_identity as ident


def _fake_wb_jwt(*, uid: int = 42) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"uid": uid, "s": 1}).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.sig"


def test_resolve_channel_from_name_legacy() -> None:
    assert ident.resolve_supply_channel(marketplace="wb", name="Основной") == ident.CHANNEL_WB_FBO
    assert ident.resolve_supply_channel(marketplace="wb", name="Склад ФБС") == ident.CHANNEL_WB_FBS
    assert ident.resolve_supply_channel(marketplace="ozon", name="Кабинет") == ident.CHANNEL_OZON_FBO
    assert ident.resolve_supply_channel(marketplace="ozon", name="ФБС") == ident.CHANNEL_OZON_FBS


def test_resolve_channel_explicit_fulfillment_overrides_name() -> None:
    # Name says FBO-ish, but explicit FBS wins.
    assert (
        ident.resolve_supply_channel(
            marketplace="wb", name="Основной", fulfillment="fbs"
        )
        == ident.CHANNEL_WB_FBS
    )
    # Name contains FBS, but explicit FBO wins.
    assert (
        ident.resolve_supply_channel(
            marketplace="wb", name="Склад ФБС", fulfillment="fbo"
        )
        == ident.CHANNEL_WB_FBO
    )
    assert (
        ident.resolve_supply_channel(
            marketplace="ozon", name="x", fulfillment="fbs"
        )
        == ident.CHANNEL_OZON_FBS
    )


def test_resolve_channel_explicit_channel_wins() -> None:
    assert (
        ident.resolve_supply_channel(
            marketplace="wb", name="x", fulfillment="fbo", channel="wb_fbs"
        )
        == ident.CHANNEL_WB_FBS
    )


def test_ensure_name_matches_fulfillment_appends_fbs_marker() -> None:
    assert ident.ensure_name_matches_fulfillment(
        name="Склад", channel="wb_fbs"
    ) == "Склад ФБС"
    assert ident.ensure_name_matches_fulfillment(
        name="Склад ФБС", channel="wb_fbs"
    ) == "Склад ФБС"


def test_ensure_name_matches_fulfillment_rejects_fbs_marker_on_fbo() -> None:
    try:
        ident.ensure_name_matches_fulfillment(name="Склад ФБС", channel="wb_fbo")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "FBO" in str(exc) or "ФБС" in str(exc)


def test_resolve_external_account_wb_prefers_manual_cabinet_id() -> None:
    token = _fake_wb_jwt(uid=39682584)
    assert (
        ident.resolve_external_account_id(
            marketplace="wb", api_key=token, client_id="111"
        )
        == "111"
    )


def test_resolve_external_account_wb_jwt_fallback() -> None:
    token = _fake_wb_jwt(uid=39682584)
    assert ident.resolve_external_account_id(
        marketplace="wb", api_key=token, client_id=""
    ) == "39682584"


def test_source_is_fbs_name_marker_wins_over_channel() -> None:
    # Explicit channel still works when name has no marker.
    assert ident.source_is_fbs(
        {"marketplace": "wb", "name": "Без маркера", "channel": "wb_fbs"}
    )
    # Name marker «ФБС» wins even if a stale channel says FBO.
    assert ident.source_is_fbs(
        {"marketplace": "wb", "name": "Склад ФБС", "channel": "wb_fbo"}
    )
    assert ident.source_is_fbs({"marketplace": "wb", "name": "ФБС склад"})
    assert not ident.source_is_fbs({"marketplace": "wb", "name": "Основной"})
    assert not ident.source_is_fbs(
        {"marketplace": "wb", "name": "Основной", "channel": "wb_fbo"}
    )


def test_sibling_channel() -> None:
    assert ident.sibling_channel("wb_fbo") == "wb_fbs"
    assert ident.sibling_channel("wb_fbs") == "wb_fbo"
    assert ident.sibling_channel("ozon_fbs") == "ozon_fbo"


def test_public_identity_fields_include_fulfillment() -> None:
    wb = ident.public_identity_fields(
        {
            "marketplace": "wb",
            "name": "ФБС",
            "channel": "wb_fbs",
            "external_account_id": "99",
        }
    )
    assert wb["cabinet_label"] == "ID кабинета 99"
    assert wb["fulfillment"] == "fbs"
    oz = ident.public_identity_fields(
        {
            "marketplace": "ozon",
            "name": "FBO",
            "client_id": "555",
        }
    )
    assert oz["external_account_id"] == "555"
    assert oz["channel"] == ident.CHANNEL_OZON_FBO
    assert oz["fulfillment"] == "fbo"


def test_source_is_fbs_follows_renamed_title() -> None:
    """Editing the name to include/remove ФБС must flip FBS detection."""
    assert not ident.source_is_fbs({"marketplace": "wb", "name": "Основной", "channel": "wb_fbo"})
    assert ident.source_is_fbs({"marketplace": "wb", "name": "Основной ФБС", "channel": "wb_fbo"})
    # Channel from name after edit.
    assert (
        ident.resolve_supply_channel(marketplace="wb", name="Основной ФБС")
        == ident.CHANNEL_WB_FBS
    )
