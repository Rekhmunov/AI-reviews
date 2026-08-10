"""Unit tests for Contour.Logistics client helpers (no live API)."""
from __future__ import annotations

from review_processor.kontur_logistics import (
    KonturLogisticsClient,
    status_label,
    TRANSPORTATION_STATUS_LABELS,
)
from review_processor.kontur_diadoc import KonturDiadocClient


def test_status_label_known_and_unknown():
    assert status_label("OnTheWay") == TRANSPORTATION_STATUS_LABELS["OnTheWay"]
    assert status_label("CustomX") == "CustomX"
    assert status_label("") == "Нет статуса"


def test_parse_transportation_status():
    payload = {
        "transportationInfo": {
            "id": "tid-1",
            "status": "OnTheWay",
            "statusDescription": "В пути",
            "mintransStatus": {
                "id": "mt-99",
                "status": "Registered",
                "statusDescription": "Зарегистрирован",
                "hasErrors": False,
            },
            "receptionAddress": "A",
            "deliveryAddress": "B",
        }
    }
    parsed = KonturLogisticsClient.parse_transportation_status(payload)
    assert parsed["transportation_id"] == "tid-1"
    assert parsed["status"] == "OnTheWay"
    assert parsed["status_label"] == "В пути"
    assert parsed["mintrans_id"] == "mt-99"


def test_parse_post_message_ids():
    payload = {
        "MessageId": "msg-1",
        "Entities": [
            {"EntityId": "ent-1", "EntityType": "Attachment", "AttachmentTypeNamedId": "LogisticsOrderRequest"},
        ],
    }
    ids = KonturDiadocClient.parse_post_message_ids(payload)
    assert ids["message_id"] == "msg-1"
    assert ids["entity_id"] == "ent-1"


def test_logistics_client_normalizes_url():
    c = KonturLogisticsClient(api_url="https://logist-api.kontur.ru", api_key="k")
    assert c.api_url.endswith("/")
