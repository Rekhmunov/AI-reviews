"""Schema-oriented checks for Ozon ЭЗЗ (заказ-заявка) title-1 XML draft."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

from review_processor.ozon_zakaz import build_ozon_zakaz_xml


def _build(**overrides):
    kwargs = dict(
        item={
            "supply_order_id": 120035796,
            "supply_order_number": "2000061286750",
            "supplier_name": 'ООО "Тест"',
            "warehouse_name": "ХОРУГВИНО_РФЦ",
            "supply_date": "2026-08-15T14:30:00",
        },
        le={
            "full_name": 'ООО "Тест Поставщик"',
            "short_name": "Тест",
            "requisites": (
                "ИНН 7701234567 КПП 770101001 "
                "юр. адрес: 101000, г. Москва, ул. Ленина, д. 1"
            ),
            "signatories": "Иванов Иван Иванович",
            "phone": "+79991112233",
            "address": "101000, г. Москва, ул. Ленина, д. 1",
        },
        vehicle_fields={
            "model": "MAN",
            "number": "В849ВО37",
            "type": "грузовой автомобиль",
            "ownership": "1",
            "capacity_t": "20",
            "volume_m3": "20",
        },
        carrier_fields={
            "carrier_name": 'ООО "Перевозчик"',
            "carrier_inn": "5001002003",
            "carrier_kpp": "500101001",
        },
        cargoes_json={
            "version": 2,
            "groups": [{"type": "BOX", "content_type": "MONO", "count": 41}],
            "transport_cargoes": [
                {"type": "PALLET", "transport_cargo_id": "a", "box_count": 11},
                {"type": "PALLET", "transport_cargo_id": "b", "box_count": 30},
            ],
        },
        load_address="141580, Московская обл., г. Химки, ул. Заводская, д. 10",
        delivery_address="143420, Московская обл., г. Истра, ул. Складская, д. 5",
        now=datetime(2026, 8, 10, 9, 31, 11),
    )
    kwargs.update(overrides)
    return build_ozon_zakaz_xml(**kwargs)


def test_zakaz_xml_core_shape():
    root = ET.fromstring(_build())
    assert root.tag == "Файл"
    assert root.attrib["ВерсФорм"] == "5.01"
    assert root.attrib["ИдФайл"].startswith("ON_ZAKZVGO_")
    assert "DRAFT" not in root.attrib["ИдФайл"]

    doc = root.find("Документ")
    assert doc is not None
    assert doc.attrib["КНД"] == "1110361"
    assert doc.attrib["Функция"] == "Заказ"
    assert "7701234567" in doc.attrib.get("НаимЭкСубСост", "")

    sod = doc.find("СодИнфГО")
    assert sod is not None
    assert sod.attrib["НомЗак"] == "2000061286750"
    assert "Предоставление заказа" in sod.attrib.get("СодОпер", "")

    go = sod.find("СвГО/ИдСв/СвЮЛУч")
    assert go is not None
    assert go.attrib["ИННЮЛ"] == "7701234567"
    go_adr = sod.find("СвГО/Адрес/АдрРФ")
    assert go_adr is not None
    assert len(go_adr.attrib.get("Индекс", "")) == 6
    assert go_adr.attrib.get("КодРегион")
    assert sod.find("СвГО/Конт/Тлф") is not None
    assert sod.find("СвГО/Конт/Тлф").text == "+79991112233"

    prv = sod.find("СвПрв/ИдСв/СвЮЛУч")
    assert prv is not None
    assert prv.attrib["ИННЮЛ"] == "5001002003"
    assert sod.find("СвПрв/Конт/Тлф").text  # required non-empty

    assert sod.find("ПунктПод") is not None
    pod_adr = sod.find("ПунктПод/АдрПунктПод/Адрес/АдрРФ")
    assert pod_adr is not None
    assert len(pod_adr.attrib.get("Индекс", "")) == 6

    assert sod.find("АдрПункт[@Опер='Погрузка']") is not None
    assert sod.find("АдрПункт[@Опер='Выгрузка']") is not None
    unload = sod.find("АдрПункт[@Опер='Выгрузка']/АдресПункт/Адрес/АдрРФ")
    assert unload is not None
    assert len(unload.attrib.get("Индекс", "")) == 6

    op = sod.find("ОпГруз")
    assert op is not None
    assert op.attrib["КолГрМест"] == "2"
    assert op.attrib["МетОпрМасс"] == "03"
    assert op.attrib["Объем"] == "20.00"
    assert "." in op.find("МасГруз").attrib.get("МасБрутЗнач", "")
    dims = op.find("РазмерГрМест").attrib
    assert dims["ВысЗнач"] == "1.800"
    assert op.find("Пункт").attrib.get("Погр") == "1"
    assert op.find("Пункт").attrib.get("Выгр") == "2"

    ts = sod.find("ПарТСПрвз")
    assert ts is not None
    assert ts.attrib["Тип"] == "грузовой автомобиль"
    assert ts.attrib["Грузопод"] == "20.00"
    assert ts.attrib["Вместим"] == "20.00"

    podp = doc.find("ПодпИнфГО")
    assert podp is not None
    assert podp.attrib.get("СпосПодтПолном") == "1"
    assert podp.find("ФИО").attrib.get("Фамилия") == "Иванов"


def test_zakaz_uses_supply_number_as_nomzak():
    root = ET.fromstring(
        _build(
            item={
                "supply_order_id": 1,
                "supply_order_number": "020-111",
                "supplier_name": "X",
                "warehouse_name": "W",
                "supply_date": "2026-09-01",
            }
        )
    )
    assert root.find("Документ/СодИнфГО").attrib["НомЗак"] == "020-111"


def test_zakaz_fills_index_when_only_warehouse_name():
    """Unload point without structured address must still get Индекс (АдрРФ required)."""
    root = ET.fromstring(
        _build(
            delivery_address="",
            delivery_addr_fields=None,
            item={
                "supply_order_id": 1,
                "supply_order_number": "1",
                "supplier_name": "X",
                "warehouse_name": "ХОРУГВИНО_РФЦ",
                "supply_date": "2026-08-15",
            },
        )
    )
    unload = root.find("Документ/СодИнфГО/АдрПункт[@Опер='Выгрузка']/АдресПункт/Адрес/АдрРФ")
    assert unload is not None
    assert len(unload.attrib.get("Индекс", "")) == 6
    assert unload.attrib.get("КодРегион")


def test_zakaz_phone_never_empty():
    root = ET.fromstring(_build(le={
        "full_name": 'ООО "Тест"',
        "requisites": "ИНН 7701234567 КПП 770101001",
        "signatories": "Иванов Иван Иванович",
        "phone": "",
        "address": "101000, г. Москва, ул. Ленина, д. 1",
    }, driver_phone=""))
    assert root.find("Документ/СодИнфГО/СвГО/Конт/Тлф").text
    assert root.find("Документ/СодИнфГО/СвПрв/Конт/Тлф").text
