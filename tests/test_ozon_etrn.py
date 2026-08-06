"""Schema-oriented checks for Ozon eTrN title-1 XML draft."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

from review_processor.ozon_etrn import (
    OZON_CONSIGNEE_EDO_GUID,
    OZON_CONSIGNEE_INN,
    build_ozon_etrn_xml,
)


def _build(**overrides):
    kwargs = dict(
        item={
            "supply_order_id": 123,
            "supply_order_number": "0123456789",
            "supplier_name": 'ООО "Тест"',
            "warehouse_name": "ХОРУГВИНО_РФЦ",
        },
        le={
            "full_name": 'ООО "Тест Поставщик"',
            "short_name": "Тест",
            "requisites": (
                "ИНН 7701234567 КПП 770101001 "
                "юр. адрес: 101000, г. Москва, ул. Ленина, д. 1"
            ),
            "signatories": "Иванов Иван Иванович",
        },
        driver_name="Петров Пётр Петрович",
        driver_phone="+79001234567",
        driver_documents="ВУ 99 00 123456 выд. 01.02.2018",
        vehicle_line="GAZelle A123BC77",
        cargoes_json=[{"type": "PALLET", "content_type": "ITEM", "count": 2}],
        load_address="141580, Московская обл., г. Химки, ул. Заводская, д. 10",
        delivery_address="143420, Московская обл., г. Истра, ул. Складская, д. 5",
        carrier_text="ООО Перевозчик ИНН 5001002003 КПП 500101001",
        now=datetime(2026, 8, 6, 12, 30, 0),
    )
    kwargs.update(overrides)
    return build_ozon_etrn_xml(**kwargs)


def test_etrn_xml_core_schema_shape():
    root = ET.fromstring(_build())
    assert root.tag == "Файл"
    assert root.attrib["ВерсФорм"] == "5.01"
    assert OZON_CONSIGNEE_EDO_GUID in root.attrib["ИдФайл"]

    doc = root.find("Документ")
    assert doc is not None
    assert doc.attrib["КНД"] == "1110339"

    sod = doc.find("СодИнфГО")
    assert sod is not None

    # InfPol is last child of СодИнфГО and uses Значение (not Значен).
    children = list(sod)
    assert children[-1].tag == "ИнфПол"
    texts = children[-1].findall("ТекстИнф")
    assert {t.attrib.get("Идентиф") for t in texts} >= {"Orders", "ORDERS"}
    for t in texts:
        assert t.attrib.get("Значение") == "0123456789"
        assert "Значен" not in t.attrib

    # Delivery / loading use АдресРФ; legal address under Адрес uses АдрРФ.
    # Never emit АдрИнф/АдресИнф — Kontur treats that as foreign address type.
    assert sod.find("СвГП/АдресДостГр/АдресРФ") is not None
    assert sod.find("СвГП/АдресДостГр/АдрРФ") is None
    assert sod.find("СвПогруз/ФАдресПогр/АдресРФ") is not None
    assert sod.find("СвГО/РекИдентГО/Адрес/АдрРФ") is not None
    assert sod.find(".//АдрИнф") is None
    assert sod.find(".//АдресИнф") is None

    # No empty GAR / phone stubs.
    assert sod.find(".//КодГАР") is None
    for phone in sod.findall(".//Тлф"):
        assert (phone.text or "").strip()

    # Required signer under Документ.
    signer = doc.find("Подписант")
    assert signer is not None
    assert signer.attrib.get("СтатПодп") == "1"
    assert signer.find("ФИО") is not None

    # Vehicle ownership + parameters required by schema.
    ts = sod.find("СвТС/ТС")
    assert ts is not None
    assert ts.attrib.get("ТипВлад") == "1"
    part = ts.find("ПарТС")
    assert part is not None
    assert part.attrib.get("Тип")
    assert part.attrib.get("Грузопод")
    assert part.attrib.get("Вместим")

    # Ozon consignee + cargo required fields.
    assert sod.find("СвГП/РекИдентГП/ИдСв/СвЮЛУч").attrib["ИННЮЛ"] == OZON_CONSIGNEE_INN
    op = sod.find("СвГруз/ОпГруз")
    assert op.attrib.get("КолМестГр") == "2"
    assert op.find("ПлМасГруз").attrib.get("МасБрутЗнач")
    assert sod.find("СвПогруз").attrib.get("МетОпрМасс") == "03"
    assert op.attrib.get("СостГруз") == "Без повреждений"


def test_etrn_xml_empty_cargoes_still_has_required_mass_places():
    root = ET.fromstring(_build(cargoes_json=[]))
    op = root.find("Документ/СодИнфГО/СвГруз/ОпГруз")
    assert op is not None
    assert int(op.attrib["КолМестГр"]) >= 1
    assert int(op.find("ПлМасГруз").attrib["МасБрутЗнач"]) >= 1


def test_etrn_xml_incomplete_legal_address_still_adr_rf():
    """Unparseable legal address must stay АдрРФ, not АдрИнф (foreign)."""
    root = ET.fromstring(
        _build(
            le={
                "full_name": 'ООО "Тест"',
                "requisites": "ИНН 7701234567 КПП 770101001 адрес: деревня БезИндекса, участок 7",
                "signatories": "Иванов Иван Иванович",
            },
            load_address="",
            delivery_address="склад без индекса",
        )
    )
    adr = root.find("Документ/СодИнфГО/СвГО/РекИдентГО/Адрес/АдрРФ")
    assert adr is not None
    assert root.find("Документ/СодИнфГО/СвГО/РекИдентГО/Адрес/АдрИнф") is None
    assert root.find(".//АдрИнф") is None
    assert root.find(".//АдресИнф") is None
    assert root.find("Документ/СодИнфГО/СвГП/АдресДостГр/АдресРФ") is not None
    assert root.find("Документ/СодИнфГО/СвПогруз/ФАдресПогр/АдресРФ") is not None


def test_etrn_shipper_address_from_legal_entity_not_load():
    """Грузоотправитель address = юр.лица requisites, not production/warehouse."""
    root = ET.fromstring(
        _build(
            le={
                "full_name": 'ООО "Тест"',
                "requisites": (
                    "ИНН 7701234567 КПП 770101001 "
                    "141200, Московская область, г. Пушкино, ул. Лесная, д. 5"
                ),
                "signatories": "Иванов Иван Иванович",
            },
            load_address=(
                "Московская область, Солнечногорский район, "
                "сельское поселение Пешковское, деревня Хоругвино, строение 32/2"
            ),
        )
    )
    adr = root.find("Документ/СодИнфГО/СвГО/РекИдентГО/Адрес/АдрРФ")
    assert adr is not None
    shipper_xml = ET.tostring(adr, encoding="unicode")
    assert "Хоругвино" not in shipper_xml
    assert "Пушкино" in shipper_xml or "Лесная" in shipper_xml
    # Load address still goes to ФАдресПогр.
    load_xml = ET.tostring(root.find("Документ/СодИнфГО/СвПогруз/ФАдресПогр"), encoding="unicode")
    assert "Хоругвино" in load_xml
