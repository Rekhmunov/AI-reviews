"""WB FBS supply driver assignment (shared catalog + vehicle plates)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from review_processor.wb_fbs import (
    empty_supply_driver,
    get_supply_driver,
    get_supply_driver_payload,
    list_driver_page_cargo_places,
    list_supplies_for_driver_vehicle,
    set_supply_driver,
)


def test_set_supply_driver_requires_catalog_driver(monkeypatch) -> None:
    monkeypatch.setattr(
        "review_processor.wb_fbs.ensure_wb_fbs_tables",
        lambda repo: None,
    )
    repo = MagicMock()
    repo.list_supply_drivers.return_value = []
    with pytest.raises(ValueError, match="Выберите водителя"):
        set_supply_driver(
            repo, user_id=1, source_id=2, supply_id="WB-1", driver_id=0
        )
    with pytest.raises(ValueError, match="не найден"):
        set_supply_driver(
            repo, user_id=1, source_id=2, supply_id="WB-1", driver_id=9
        )


def test_set_supply_driver_upserts_and_autofills_single_plate(monkeypatch) -> None:
    monkeypatch.setattr(
        "review_processor.wb_fbs.ensure_wb_fbs_tables",
        lambda repo: None,
    )
    stored: dict = {}

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            text = str(sql)
            if "INSERT INTO wb_fbs_supply_driver" in text:
                stored["row"] = {
                    "driver_id": params[3],
                    "driver_name": params[4],
                    "vehicle_number": params[5],
                }
                return self
            if "SELECT driver_id" in text:
                cur = MagicMock()
                cur.fetchone.return_value = stored.get("row")
                return cur
            return self

    repo = MagicMock()
    repo.list_supply_drivers.return_value = [
        {
            "id": 4,
            "full_name": "Иванов Иван",
            "vehicles_json": '[{"model":"MAN","number":"В849ВО37"}]',
        }
    ]
    repo._connect.return_value = _Conn()
    repo._sql.side_effect = lambda q: q
    repo._row_to_dict.side_effect = lambda row: dict(row)

    out = set_supply_driver(
        repo, user_id=1, source_id=2, supply_id="WB-1", driver_id=4
    )
    assert out["has_driver"] is True
    assert out["driver_id"] == 4
    assert out["driver_name"] == "Иванов Иван"
    assert out["vehicle_number"] == "В849ВО37"
    assert stored["row"]["vehicle_number"] == "В849ВО37"


def test_get_supply_driver_empty_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "review_processor.wb_fbs.ensure_wb_fbs_tables",
        lambda repo: None,
    )

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            cur = MagicMock()
            cur.fetchone.return_value = None
            return cur

    repo = MagicMock()
    repo._connect.return_value = _Conn()
    repo._sql.side_effect = lambda q: q
    assert get_supply_driver(
        repo, user_id=1, source_id=2, supply_id="WB-1"
    ) == empty_supply_driver()


def test_get_supply_driver_payload_includes_catalog(monkeypatch) -> None:
    monkeypatch.setattr(
        "review_processor.wb_fbs.ensure_wb_fbs_tables",
        lambda repo: None,
    )

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            cur = MagicMock()
            cur.fetchone.return_value = {
                "driver_id": 4,
                "driver_name": "Иванов Иван",
                "vehicle_number": "В849ВО37",
            }
            return cur

    repo = MagicMock()
    repo._connect.return_value = _Conn()
    repo._sql.side_effect = lambda q: q
    repo._row_to_dict.side_effect = lambda row: dict(row)
    repo.list_supply_drivers.return_value = [
        {
            "id": 4,
            "full_name": "Иванов Иван",
            "vehicles_json": '[{"number":"В849ВО37"}]',
        }
    ]
    payload = get_supply_driver_payload(
        repo, user_id=1, source_id=2, supply_id="WB-1"
    )
    assert payload["has_driver"] is True
    assert len(payload["drivers"]) == 1


def test_list_supplies_for_driver_vehicle_filters_plate(monkeypatch) -> None:
    monkeypatch.setattr(
        "review_processor.wb_fbs.ensure_wb_fbs_tables",
        lambda repo: None,
    )

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *args, **kwargs):
            return self

        def fetchall(self):
            return [
                {
                    "source_id": 10,
                    "supply_id": "WB-1",
                    "driver_id": 1,
                    "driver_name": "Иванов",
                    "vehicle_number": "А123ВС777",
                    "supply_name": "Supply WB-1",
                },
                {
                    "source_id": 10,
                    "supply_id": "WB-2",
                    "driver_id": 1,
                    "driver_name": "Иванов",
                    "vehicle_number": "В849ВО37",
                    "supply_name": "Supply WB-2",
                },
            ]

    repo = MagicMock()
    repo._connect.return_value = _Conn()
    repo._sql.side_effect = lambda s: s
    repo._row_to_dict.side_effect = lambda row: row
    rows = list_supplies_for_driver_vehicle(
        repo, user_id=1, vehicle_number="А123ВС777"
    )
    assert len(rows) == 1
    assert rows[0]["supply_id"] == "WB-1"
    assert rows[0]["marketplace"] == "wb"


def test_list_driver_page_cargo_places_from_local_boxes(monkeypatch) -> None:
    monkeypatch.setattr(
        "review_processor.wb_fbs.list_supplies_for_driver_vehicle",
        lambda repo, **kwargs: [
            {
                "source_id": 3,
                "supply_id": "WB-9",
                "supply_name": "Поставка 9",
                "warehouse_name": "",
                "driver_id": 1,
                "driver_name": "Иванов",
                "vehicle_number": "А123ВС777",
                "marketplace": "wb",
            }
        ],
    )
    monkeypatch.setattr(
        "review_processor.wb_fbs.cached_supply_boxes_by_id",
        lambda repo, user_id, source_id, supply_ids: {
            "WB-9": [{"id": "TRBX001"}, {"id": "TRBX002"}]
        },
    )
    monkeypatch.setattr(
        "review_processor.wb_fbs._local_supply_order_ids",
        lambda repo, user_id, source_id, supply_id: [11, 22, 33],
    )
    out = list_driver_page_cargo_places(
        MagicMock(), user_id=1, vehicle_number="А123ВС777"
    )
    assert out["total"] == 2
    assert out["items"][0]["marketplace"] == "wb"
    assert out["items"][0]["item_kind"] == "trbx"
    assert out["items"][0]["container_id"] == "TRBX001"
    assert out["items"][0]["order_count"] == 3
