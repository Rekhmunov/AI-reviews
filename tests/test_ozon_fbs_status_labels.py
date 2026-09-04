"""Ozon FBS posting status labels (Seller API → Russian UI)."""

from __future__ import annotations

from review_processor.ozon_fbs import ozon_status_label_ru
from review_processor.ozon_fbs_containers import status_label as container_status_label


def test_ozon_posting_status_labels_cover_fbs_lifecycle() -> None:
    assert ozon_status_label_ru("acceptance_in_progress") == "Идёт приёмка"
    assert ozon_status_label_ru("awaiting_registration") == "Ожидает регистрации"
    assert ozon_status_label_ru("awaiting_approve") == "Ожидает подтверждения"
    assert ozon_status_label_ru("awaiting_packaging") == "Ожидает сборки"
    assert ozon_status_label_ru("awaiting_deliver") == "Ожидает отгрузки"
    assert ozon_status_label_ru("delivering") == "Доставляется"
    assert ozon_status_label_ru("driver_pickup") == "У водителя"
    assert ozon_status_label_ru("delivered") == "Доставлено"
    assert ozon_status_label_ru("cancelled") == "Отменено"
    assert ozon_status_label_ru("arbitration") == "Арбитраж"
    assert ozon_status_label_ru("client_arbitration") == "Клиентский арбитраж"
    assert ozon_status_label_ru("not_accepted") == "Не принято на СЦ"
    assert ozon_status_label_ru("sent_by_seller") == "Отправлено продавцом"
    assert ozon_status_label_ru("cancelled_from_split_pending") == "Отменено (разделение)"
    assert ozon_status_label_ru("") == "неизвестен"
    # Unknown codes stay readable (raw), not blank.
    assert ozon_status_label_ru("some_new_status") == "some_new_status"


def test_posting_acceptance_label_differs_from_container() -> None:
    """Same API token, different domains: posting vs грузоместо."""
    assert ozon_status_label_ru("acceptance_in_progress") == "Идёт приёмка"
    assert container_status_label("acceptance_in_progress") == "Принято на СЦ"
