"""Ozon FBS supply driver assignment (catalog + vehicle plates)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from review_processor.ozon_fbs_supplies import (
    driver_vehicle_plates,
    empty_supply_driver,
    get_supply_driver,
    get_supply_driver_payload,
    list_supply_driver_options,
    set_supply_driver,
)


def test_driver_vehicle_plates_uses_reg_number() -> None:
    plates = driver_vehicle_plates(
        [
            {"model": "MAN", "number": "В849ВО37", "line": "MAN В849ВО37"},
            {"model": "GAZelle", "number": "А123ВС777", "line": "GAZelle А123ВС777"},
            {"model": "MAN", "number": "в849во37", "line": "dup"},
        ]
    )
    assert [p["number"] for p in plates] == ["В849ВО37", "А123ВС777"]


def test_driver_vehicle_plates_from_line_string() -> None:
    plates = driver_vehicle_plates(["КАМАЗ К456КК199", "безномера"])
    assert plates[0]["number"] == "К456КК199"
    assert all(p["number"] for p in plates)


def test_list_supply_driver_options_skips_empty() -> None:
    repo = MagicMock()
    repo.list_supply_drivers.return_value = [
        {
            "id": 4,
            "full_name": "Иванов Иван",
            "vehicles_json": '[{"model":"MAN","number":"В849ВО37"}]',
        },
        {"id": 0, "full_name": "Skip"},
        {"id": 5, "full_name": ""},
    ]
    opts = list_supply_driver_options(repo, user_id=1)
    assert len(opts) == 1
    assert opts[0]["id"] == 4
    assert opts[0]["vehicles"][0]["number"] == "В849ВО37"


def test_set_supply_driver_requires_catalog_driver(monkeypatch) -> None:
    monkeypatch.setattr(
        "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema",
        lambda repo: None,
    )
    repo = MagicMock()
    repo.list_supply_drivers.return_value = []
    with pytest.raises(ValueError, match="Выберите водителя"):
        set_supply_driver(
            repo, user_id=1, source_id=2, supply_id="OZ-1", driver_id=0
        )
    with pytest.raises(ValueError, match="не найден"):
        set_supply_driver(
            repo, user_id=1, source_id=2, supply_id="OZ-1", driver_id=9
        )


def test_set_supply_driver_requires_plate_when_several(monkeypatch) -> None:
    monkeypatch.setattr(
        "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema",
        lambda repo: None,
    )
    repo = MagicMock()
    repo.list_supply_drivers.return_value = [
        {
            "id": 4,
            "full_name": "Иванов Иван",
            "vehicles_json": (
                '[{"number":"В849ВО37"},{"number":"А123ВС777"}]'
            ),
        }
    ]
    with pytest.raises(ValueError, match="гос. номер"):
        set_supply_driver(
            repo, user_id=1, source_id=2, supply_id="OZ-1", driver_id=4
        )


def test_set_supply_driver_upserts_and_autofills_single_plate(monkeypatch) -> None:
    monkeypatch.setattr(
        "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema",
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
            if "INSERT INTO ozon_fbs_supply_driver" in text:
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
        repo, user_id=1, source_id=2, supply_id="OZ-1", driver_id=4
    )
    assert out["has_driver"] is True
    assert out["driver_id"] == 4
    assert out["driver_name"] == "Иванов Иван"
    assert out["vehicle_number"] == "В849ВО37"
    assert stored["row"]["vehicle_number"] == "В849ВО37"


def test_get_supply_driver_empty_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema",
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
        repo, user_id=1, source_id=2, supply_id="OZ-1"
    ) == empty_supply_driver()


def test_get_supply_driver_payload_includes_catalog(monkeypatch) -> None:
    monkeypatch.setattr(
        "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema",
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
        repo, user_id=1, source_id=2, supply_id="OZ-1"
    )
    assert payload["has_driver"] is True
    assert payload["drivers"][0]["vehicles"][0]["number"] == "В849ВО37"
