"""Tests for supply source cabinet identity (WB uid / Ozon Client-Id)."""

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


def test_resolve_channel_wb_fbo_fbs() -> None:
    assert ident.resolve_supply_channel(marketplace="wb", name="Основной") == ident.CHANNEL_WB_FBO
    assert ident.resolve_supply_channel(marketplace="wb", name="Склад ФБС") == ident.CHANNEL_WB_FBS
    assert ident.resolve_supply_channel(marketplace="wb", name="FBS north") == ident.CHANNEL_WB_FBS


def test_resolve_channel_ozon() -> None:
    assert ident.resolve_supply_channel(marketplace="ozon", name="Кабинет") == ident.CHANNEL_OZON_FBO
    assert ident.resolve_supply_channel(marketplace="ozon", name="ФБС") == ident.CHANNEL_OZON_FBS
    assert ident.resolve_supply_channel(marketplace="ozon_fbs", name="x") == ident.CHANNEL_OZON_FBS


def test_resolve_external_account_wb_uid() -> None:
    token = _fake_wb_jwt(uid=39682584)
    assert ident.resolve_external_account_id(
        marketplace="wb", api_key=token, client_id=""
    ) == "39682584"


def test_resolve_external_account_ozon_client_id() -> None:
    assert ident.resolve_external_account_id(
        marketplace="ozon", api_key="secret", client_id="  12345  "
    ) == "12345"
    assert (
        ident.resolve_external_account_id(
            marketplace="ozon", api_key="secret", client_id=""
        )
        is None
    )


def test_public_identity_fields_labels() -> None:
    wb = ident.public_identity_fields(
        {
            "marketplace": "wb",
            "name": "ФБС",
            "channel": "wb_fbs",
            "external_account_id": "99",
        }
    )
    assert wb["cabinet_label"] == "uid 99"
    oz = ident.public_identity_fields(
        {
            "marketplace": "ozon",
            "name": "FBO",
            "client_id": "555",
        }
    )
    assert oz["external_account_id"] == "555"
    assert oz["cabinet_label"] == "Client-Id 555"
    assert oz["channel"] == ident.CHANNEL_OZON_FBO


def test_channel_label() -> None:
    assert "ВБ" in ident.channel_label("wb_fbs")
    assert "ОЗОН" in ident.channel_label("ozon_fbo")
