"""TTN catalog → Zakaz / eTrN XML adapters (parity with Ozon supplies)."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from review_processor.ozon_etrn import OZON_CONSIGNEE_NAME
from review_processor.ttn_docs import build_ttn_etrn_xml, build_ttn_zakaz_xml, collect_ttn_doc_context


class _Repo:
    def list_supply_legal_entities(self, user_id=0):
        return []

    def list_supply_contractors(self, user_id=0):
        return []

    def list_supply_drivers(self, user_id=0):
        return []

    def list_supply_productions(self, user_id=0):
        return []

    def list_supply_warehouses(self, user_id=0):
        return []


def _record(**overrides):
    base = {
        "id": 42,
        "doc_number": "TN-42",
        "ttn_date": "2026-03-20",
        "legal_entity_id": 0,
        "contractor_id": 0,
        "shipper_type": "le",
        "consignee_type": "contractor",
        "load_address": "141580, Московская обл., г. Химки, ул. Заводская, д. 10",
        "unload_address": "143420, Московская обл., г. Истра, ул. Складская, д. 5",
        "cargo_description": "Одежда",
        "cargo_places": "3",
        "cargo_weight": "240",
        "packing_type": "Паллеты",
        "vehicle_line": "Газель А123ВС77",
        "le_short": "Тест",
        "le_full": 'ООО "Тест Поставщик"',
        "le_req": "ИНН 7701234567 КПП 770101001",
        "le_address": "101000, г. Москва, ул. Ленина, д. 1",
        "le_phone": "+79991112233",
        "c_name": 'ООО "Получатель"',
        "c_req": "ИНН 5001002003 КПП 500101001",
        "driver_manual_name": "Иванов Иван Иванович",
        "driver_manual_docs": "ВУ 99 00 123456",
        "carrier_snapshot": 'ООО "Перевозчик" ИНН 5001002003',
    }
    base.update(overrides)
    return base


def test_collect_ttn_context_maps_core_fields():
    ctx = collect_ttn_doc_context(repository=_Repo(), owner_id=1, record=_record())
    assert ctx["item"]["supply_order_number"] == "TN-42"
    assert ctx["cargo_name"] == "Одежда"
    assert ctx["cargo_kg"] == 240.0
    assert ctx["consignee"]["name"] == 'ООО "Получатель"'
    assert ctx["consignee"]["inn"] == "5001002003"
    assert ctx["le"]["short_name"] == "Тест"
    assert "Химки" in ctx["load_address"]
    assert "Истра" in ctx["delivery_address"]


def test_ttn_zakaz_xml_download_shape():
    xml_bytes, fname = build_ttn_zakaz_xml(repository=_Repo(), owner_id=1, record=_record())
    assert fname.startswith("Заявка №TN-42")
    root = ET.fromstring(xml_bytes)
    assert root.tag == "Файл"
    assert "Одежда" in xml_bytes.decode("utf-8")


def test_ttn_etrn_uses_ttn_consignee_not_ozon():
    xml_bytes, fname = build_ttn_etrn_xml(repository=_Repo(), owner_id=1, record=_record())
    assert fname.startswith("эТрН №TN-42")
    text = xml_bytes.decode("utf-8")
    assert "Получатель" in text
    assert OZON_CONSIGNEE_NAME not in text
    assert "Одежда" in text
    root = ET.fromstring(xml_bytes)
    assert root.tag == "Файл"
    assert "5001002003" in text


def test_ttn_etrn_wb_fbs_uses_wb_supply_id_as_waybill_number():
    """WB FBS ТН → НомерТрН и ИнфПол Идентиф = WB-GI-…"""
    rec = _record(
        fbs_platform="wb",
        fbs_source_id=7,
        fbs_supply_id="WB-GI-281870610",
        doc_number="15",
    )
    ctx = collect_ttn_doc_context(repository=_Repo(), owner_id=1, record=rec)
    assert ctx["item"]["supply_order_number"] == "WB-GI-281870610"
    assert ctx["item"]["infpol_orders_value"] == "WB-GI-281870610"
    assert ctx["doc_number"] == "15"  # каталожный № ТН не затираем

    xml_bytes, fname = build_ttn_etrn_xml(repository=_Repo(), owner_id=1, record=rec)
    assert fname.startswith("эТрН №15")  # имя файла по номеру ТН
    root = ET.fromstring(xml_bytes)
    sod = root.find("Документ/СодИнфГО")
    assert sod is not None
    assert sod.attrib.get("НомерТрН") == "WB-GI-281870610"
    assert sod.attrib.get("НомЗак") == "WB-GI-281870610"
    texts = sod.findall("ИнфПол/ТекстИнф")
    by_id = {t.attrib.get("Идентиф"): t.attrib.get("Значение") for t in texts}
    assert by_id.get("Orders") == "WB-GI-281870610"
    assert by_id.get("ORDERS") == "WB-GI-281870610"


def test_ttn_etrn_non_wb_keeps_doc_number_in_infpol():
    """Без WB FBS в ИнфПол остаётся номер ТН (как раньше)."""
    xml_bytes, _ = build_ttn_etrn_xml(repository=_Repo(), owner_id=1, record=_record())
    root = ET.fromstring(xml_bytes)
    texts = root.findall("Документ/СодИнфГО/ИнфПол/ТекстИнф")
    by_id = {t.attrib.get("Идентиф"): t.attrib.get("Значение") for t in texts}
    assert by_id.get("Orders") == "TN-42"
    assert by_id.get("ORDERS") == "TN-42"
    assert "shipment_flow_type" not in by_id


def test_ttn_etrn_ozon_fbs_shipment_flow_type_and_cargo_marks():
    """Ozon FBS ТН → InfPol shipment_flow_type=FBS и Марк = ID ГМ поставки."""

    class _RepoWithGm(_Repo):
        def _connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            self._last = (sql, params)
            return self

        def fetchall(self):
            # Distinct container_id for this supply only.
            return [{"cid": 1019563511789384}, {"cid": 1019563511789385}]

        def _sql(self, q):
            return q

        def _row_to_dict(self, row):
            return dict(row) if row else {}

    rec = _record(
        fbs_platform="ozon",
        fbs_source_id=3,
        fbs_supply_id="OZ-FBS-3-20260320-ABC",
        cargo_places="2",
        packing_type="Короба",
        doc_number="9",
    )
    ctx = collect_ttn_doc_context(repository=_RepoWithGm(), owner_id=1, record=rec)
    assert ctx["item"].get("infpol_shipment_flow_type") == "FBS"
    assert ctx["cargo_mark_ids"] == ["1019563511789384", "1019563511789385"]

    xml_bytes, _ = build_ttn_etrn_xml(repository=_RepoWithGm(), owner_id=1, record=rec)
    root = ET.fromstring(xml_bytes)
    sod = root.find("Документ/СодИнфГО")
    assert sod is not None
    texts = sod.findall("ИнфПол/ТекстИнф")
    by_id = {t.attrib.get("Идентиф"): t.attrib.get("Значение") for t in texts}
    assert by_id.get("shipment_flow_type") == "FBS"
    # Номер ТН в Orders сохраняем (не подменяем локальным OZ-FBS id).
    assert by_id.get("Orders") == "9"

    op = sod.find("СвГруз/ОпГруз")
    assert op is not None
    assert op.attrib.get("КолМестГр") == "2"
    marks = [m.text for m in op.findall("Марк")]
    assert marks == ["1019563511789384", "1019563511789385"]
    assert sod.find("СвПогруз").attrib.get("КолМестПрием") == "2"


def test_ttn_etrn_ozon_fbs_without_gm_keeps_absent_mark():
    """Ozon FBS без привязанных ГМ → Марк=Отсутствует, flow type всё равно FBS."""

    class _RepoEmptyGm(_Repo):
        def _connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            return self

        def fetchall(self):
            return []

        def _sql(self, q):
            return q

    rec = _record(
        fbs_platform="ozon",
        fbs_source_id=3,
        fbs_supply_id="OZ-FBS-3-X",
        cargo_places="1",
    )
    xml_bytes, _ = build_ttn_etrn_xml(repository=_RepoEmptyGm(), owner_id=1, record=rec)
    root = ET.fromstring(xml_bytes)
    by_id = {
        t.attrib.get("Идентиф"): t.attrib.get("Значение")
        for t in root.findall("Документ/СодИнфГО/ИнфПол/ТекстИнф")
    }
    assert by_id.get("shipment_flow_type") == "FBS"
    marks = [m.text for m in root.findall("Документ/СодИнфГО/СвГруз/ОпГруз/Марк")]
    assert marks == ["Отсутствует"]


def test_ttn_etrn_vehicle_capacity_from_type_line():
    """Тип / вместимость из ТН → Грузопод / Вместим в эТрН, не дефолт 20/20."""
    rec = _record(
        vehicle_line="Газель А123ВС77",
        vehicle_type="грузовой автомобиль, 1.5 т, 9 м³",
    )
    ctx = collect_ttn_doc_context(repository=_Repo(), owner_id=1, record=rec)
    assert ctx["vehicle_fields"]["capacity_t"] == "1.5"
    assert ctx["vehicle_fields"]["volume_m3"] == "9"
    assert ctx["vehicle_fields"]["type"] == "грузовой автомобиль"

    xml_bytes, _ = build_ttn_etrn_xml(repository=_Repo(), owner_id=1, record=rec)
    root = ET.fromstring(xml_bytes)
    part = root.find("Документ/СодИнфГО/СвТС/ТС/ПарТС")
    assert part is not None
    assert part.attrib.get("Грузопод") == "1.5"
    assert part.attrib.get("Вместим") == "9"
    assert part.attrib.get("Тип") == "грузовой автомобиль"


def test_ttn_etrn_vehicle_capacity_from_driver_catalog():
    """Каталог водителя: capacity/volume с карточки ТС, если в vehicle_type нет цифр."""
    import json

    class _RepoWithDriver(_Repo):
        def list_supply_drivers(self, user_id=0):
            return [
                {
                    "id": 7,
                    "full_name": "Петров Пётр Петрович",
                    "phone": "+79001112233",
                    "documents": "ВУ 11 22 333444",
                    "vehicles_json": json.dumps(
                        [
                            {
                                "model": "MAN",
                                "number": "В849ВО37",
                                "type": "седельный тягач",
                                "ownership": "1",
                                "capacity_t": "18.5",
                                "volume_m3": "86",
                                "line": "MAN В849ВО37",
                            }
                        ],
                        ensure_ascii=False,
                    ),
                }
            ]

    rec = _record(
        driver_id=7,
        driver_manual_name="",
        vehicle_line="MAN В849ВО37",
        vehicle_type="",  # empty snapshot → take from catalog
    )
    ctx = collect_ttn_doc_context(repository=_RepoWithDriver(), owner_id=1, record=rec)
    assert ctx["vehicle_fields"]["capacity_t"] == "18.5"
    assert ctx["vehicle_fields"]["volume_m3"] == "86"
    xml_bytes, _ = build_ttn_etrn_xml(repository=_RepoWithDriver(), owner_id=1, record=rec)
    part = ET.fromstring(xml_bytes).find("Документ/СодИнфГО/СвТС/ТС/ПарТС")
    assert part is not None
    assert part.attrib.get("Грузопод") == "18.5"
    assert part.attrib.get("Вместим") == "86"
