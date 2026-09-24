"""Ozon FBS TTN prefill: «Тип / вместимость» from driver vehicle card."""

from __future__ import annotations

import json

from review_processor.ozon_fbs_supplies import (
    format_ttn_vehicle_type_line,
    resolve_ttn_vehicle_type_from_driver,
)


def test_format_ttn_vehicle_type_line_matches_ui() -> None:
    assert (
        format_ttn_vehicle_type_line(
            {
                "type": "грузовой автомобиль",
                "capacity_t": "1.5",
                "volume_m3": "9",
            }
        )
        == "грузовой автомобиль, 1.5 т, 9 м³"
    )
    assert format_ttn_vehicle_type_line(None) == ""
    assert format_ttn_vehicle_type_line({}) == ""


def test_resolve_ttn_vehicle_type_from_driver_by_plate() -> None:
    driver = {
        "id": 7,
        "full_name": "Петров Пётр",
        "vehicles_json": json.dumps(
            [
                {
                    "model": "Газель",
                    "number": "А123ВС77",
                    "type": "грузовой автомобиль",
                    "ownership": "1",
                    "capacity_t": "1.5",
                    "volume_m3": "9",
                    "line": "Газель А123ВС77",
                },
                {
                    "model": "MAN",
                    "number": "В849ВО37",
                    "type": "седельный тягач",
                    "capacity_t": "18.5",
                    "volume_m3": "86",
                    "line": "MAN В849ВО37",
                },
            ],
            ensure_ascii=False,
        ),
    }
    assert (
        resolve_ttn_vehicle_type_from_driver(driver, vehicle_line="Газель А123ВС77")
        == "грузовой автомобиль, 1.5 т, 9 м³"
    )
    assert (
        resolve_ttn_vehicle_type_from_driver(driver, vehicle_line="А123ВС77")
        == "грузовой автомобиль, 1.5 т, 9 м³"
    )
    assert (
        resolve_ttn_vehicle_type_from_driver(driver, vehicle_line="MAN В849ВО37")
        == "седельный тягач, 18.5 т, 86 м³"
    )
    assert resolve_ttn_vehicle_type_from_driver(None, vehicle_line="X") == ""


def test_ozon_prefill_sets_vehicle_type_in_source() -> None:
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "review_processor" / "ozon_fbs_supplies.py").read_text(
        encoding="utf-8"
    )
    prefill = src.split("def build_ttn_prefill", 1)[1].split(
        "\ndef list_supply_driver_options", 1
    )[0]
    assert "resolve_ttn_vehicle_type_from_driver" in prefill
    assert '"vehicle_type": vehicle_type' in prefill
    # WB prefill must stay untouched (Ozon-only fix).
    wb = (
        Path(__file__).resolve().parents[1] / "review_processor" / "wb_fbs.py"
    ).read_text(encoding="utf-8")
    wb_prefill = wb.split("def build_ttn_prefill", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert "resolve_ttn_vehicle_type_from_driver" not in wb_prefill
