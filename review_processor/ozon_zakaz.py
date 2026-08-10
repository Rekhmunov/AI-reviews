"""Ozon FBO заказ-заявка (ЭЗЗ) draft XML for Kontur.Logistics upload.

Builds title-1 XML (КНД 1110361, ON_ZAKZVGO, ВерсФорм 5.01)
per FNS order ЕД-7-26/108@ — same data sources as eTrN draft.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any
from xml.dom import minidom
from xml.etree import ElementTree as ET

from .ozon_etrn import (
    _add_adr_rf,
    _addr_from_carrier_fields,
    _addr_from_production_fields,
    _cargo_stats,
    _carrier_org_from_fields,
    _el,
    _format_dt_vz,
    _has_structured_address,
    _ozon_supply_number,
    _parse_carrier,
    _parse_inn_kpp,
    _parse_ru_address,
    _region_code_from_text,
    _split_fio,
    _vehicle_params,
    _extract_address_from_requisites,
)

_log = logging.getLogger(__name__)


def _add_kont(parent: ET.Element, phone: str) -> None:
    """ЭЗЗ uses Конт/Тлф (not Контакт as in эТрН)."""
    kont = _el(parent, "Конт")
    phone = str(phone or "").strip()
    if phone:
        _el(kont, "Тлф", phone)
    else:
        ET.SubElement(kont, "Тлф")


def _addr_block(parent: ET.Element, addr: dict[str, str]) -> None:
    if not (addr.get("raw") or addr.get("Индекс") or addr.get("КодРегион") or addr.get("Улица")):
        return
    adr = _el(parent, "Адрес")
    _add_adr_rf(adr, "АдрРФ", addr)


def _punkt_address(parent: ET.Element, wrapper_tag: str, addr: dict[str, str]) -> None:
    wrap = _el(parent, wrapper_tag)
    adr = _el(wrap, "Адрес")
    _add_adr_rf(adr, "АдрРФ", addr if (addr.get("raw") or addr.get("Индекс") or addr.get("Улица")) else {
        "Улица": "Адрес уточнить",
        "КодРегион": "77",
    })


def build_ozon_zakaz_xml(
    *,
    item: dict[str, Any],
    le: dict[str, Any] | None = None,
    driver_name: str = "",
    driver_phone: str = "",
    driver_documents: str = "",
    driver_fields: dict[str, Any] | None = None,
    vehicle_line: str = "",
    vehicle_json: object = None,
    vehicle_fields: dict[str, Any] | None = None,
    cargoes_json: object = None,
    load_address: str = "",
    load_addr_fields: dict[str, str] | None = None,
    delivery_address: str = "",
    delivery_addr_fields: dict[str, str] | None = None,
    carrier_text: str = "",
    carrier_fields: dict[str, Any] | None = None,
    loader_name: str = "",
    now: datetime | None = None,
) -> bytes:
    """Build ЭЗЗ title-1 (ON_ZAKZVGO) XML draft bytes (UTF-8)."""
    del driver_name, driver_documents, loader_name  # reserved; carrier/vehicle used instead
    now = now or datetime.now()
    le = le or {}
    supply_num = _ozon_supply_number(item) or "Без номера"
    org_full = str(le.get("full_name") or le.get("short_name") or item.get("supplier_name") or "").strip()
    org_req = str(le.get("requisites") or "")
    inn, kpp = _parse_inn_kpp(org_req)
    if not inn:
        inn, kpp2 = _parse_inn_kpp(org_full)
        kpp = kpp or kpp2

    if _has_structured_address(load_addr_fields):
        load_addr = dict(load_addr_fields or {})
        if not load_addr.get("raw"):
            load_addr["raw"] = str(load_address or "").strip()
        if not load_addr.get("КодРегион"):
            load_addr["КодРегион"] = _region_code_from_text(
                str(load_addr.get("raw") or ""),
                str(load_addr.get("Индекс") or ""),
            )
    else:
        load_addr = _parse_ru_address(load_address)

    if _has_structured_address(delivery_addr_fields):
        dest_addr = dict(delivery_addr_fields or {})
        if not dest_addr.get("raw"):
            dest_addr["raw"] = str(delivery_address or "").strip()
        if not dest_addr.get("КодРегион"):
            dest_addr["КодРегион"] = _region_code_from_text(
                str(dest_addr.get("raw") or ""),
                str(dest_addr.get("Индекс") or ""),
            )
    else:
        dest_addr = _parse_ru_address(delivery_address)

    shipper_addr = _addr_from_production_fields(le)
    if not _has_structured_address(shipper_addr):
        legal_addr_raw = str(le.get("address") or "").strip() or _extract_address_from_requisites(org_req)
        shipper_addr = _parse_ru_address(legal_addr_raw)
    elif not shipper_addr.get("КодРегион"):
        shipper_addr["КодРегион"] = _region_code_from_text(
            str(shipper_addr.get("raw") or le.get("address") or ""),
            str(shipper_addr.get("Индекс") or ""),
        )

    cargo = _cargo_stats(cargoes_json if cargoes_json is not None else item.get("cargoes_json"))
    v_params = _vehicle_params(
        vehicle_json=vehicle_json if vehicle_json is not None else item.get("vehicle_json"),
        fallback_line=vehicle_line,
        vehicle_fields=vehicle_fields,
    )
    c_name, c_inn, c_kpp = _carrier_org_from_fields(carrier_fields)
    if c_name or c_inn or c_kpp:
        carrier_name, carrier_inn, carrier_kpp = c_name, c_inn, c_kpp
    else:
        carrier_name, carrier_inn, carrier_kpp = _parse_carrier(carrier_text)

    contact_phone = str(le.get("phone") or "").strip()
    if not contact_phone:
        contact_phone = str(driver_phone or "").strip()
        if not contact_phone and isinstance(driver_fields, dict):
            contact_phone = str(driver_fields.get("phone") or "").strip()

    carrier_addr = _addr_from_carrier_fields(carrier_fields)
    if not _has_structured_address(carrier_addr):
        carrier_addr = _parse_ru_address(_extract_address_from_requisites(carrier_text))

    signer_src = str(le.get("signatories") or le.get("in_person") or "").strip()
    s_fam, s_imya, s_otch = _split_fio(signer_src)
    if not s_fam:
        s_fam, s_imya = "Не", "указан"

    date_ru = now.strftime("%d.%m.%Y")
    time_ru = now.strftime("%H:%M:%S")
    file_date = now.strftime("%Y%m%d")
    shipper_guid = f"2BM-{inn}-{kpp or '000000000'}-DRAFT" if inn else "2BM-DRAFT"
    file_id = (
        f"ON_ZAKZVGO__{shipper_guid}_0_{file_date}_{uuid.uuid4()}"
    )

    naim_subj = org_full or "Грузоотправитель"
    if inn:
        naim_subj = f"{naim_subj}, ИНН {inn}" + (f", КПП {kpp}" if kpp else "")

    # Volume: vehicle m³, else rough estimate from places.
    volume = str(v_params.get("volume_m3") or "").strip()
    if not volume or volume == "20" and not (vehicle_fields or {}).get("volume_m3"):
        if cargo["pallets"] > 0:
            volume = f"{max(1.0, cargo['pallets'] * 1.5):.2f}"
        elif cargo["boxes"] > 0:
            volume = f"{max(0.1, cargo['boxes'] * 0.08):.2f}"
        else:
            volume = "1.00"
    else:
        try:
            volume = f"{float(volume.replace(',', '.')):.2f}"
        except ValueError:
            volume = "1.00"

    places = str(int(cargo["total_places"] or 1))
    # Pallet-ish dimensions when unknown (required by format).
    if cargo["pallets"] > 0:
        dim_h, dim_l, dim_w = "1.80", "1.20", "0.80"
    else:
        dim_h, dim_l, dim_w = "0.40", "0.60", "0.40"

    supply_dt_vz = _format_dt_vz(item.get("supply_date"), fallback=now)

    root = ET.Element(
        "Файл",
        ИдФайл=file_id,
        ВерсПрог="Diadoc 1.0",
        ВерсФорм="5.01",
    )
    doc = _el(
        root,
        "Документ",
        КНД="1110361",
        ДатИнфГО=date_ru,
        ВрИнфГО=time_ru,
        НаимЭкСубСост=naim_subj,
        Функция="Заказ",
    )
    sod = _el(
        doc,
        "СодИнфГО",
        СодОпер="Предоставление заказа и заявки на перевозку груза автомобильным транспортом",
        НомЗак=supply_num,
        ДатаЗак=date_ru,
        УкНормПрвз="Отсутствует",
        ПрвзПищПрод="Отсутствует",
    )

    # --- СвГО ---
    sv_go = _el(sod, "СвГО")
    id_go = _el(sv_go, "ИдСв")
    go_attrs = {"НаимОрг": org_full or "Грузоотправитель"}
    if inn:
        go_attrs["ИННЮЛ"] = inn
    if kpp:
        go_attrs["КПП"] = kpp
    _el(id_go, "СвЮЛУч", **go_attrs)
    _addr_block(sv_go, shipper_addr)
    _add_kont(sv_go, contact_phone)

    # --- СвПрв ---
    sv_prv = _el(sod, "СвПрв")
    id_prv = _el(sv_prv, "ИдСв")
    prv_attrs: dict[str, str] = {}
    if carrier_name:
        prv_attrs["НаимОрг"] = carrier_name
    if carrier_inn:
        prv_attrs["ИННЮЛ"] = carrier_inn
    if carrier_kpp:
        prv_attrs["КПП"] = carrier_kpp
    if prv_attrs:
        _el(id_prv, "СвЮЛУч", **prv_attrs)
    else:
        _el(id_prv, "СвЮЛУч", НаимОрг="Перевозчик (уточнить)")
    _addr_block(sv_prv, carrier_addr)
    _add_kont(sv_prv, contact_phone)

    # --- ПунктПод (подача ТС = адрес погрузки / производство) ---
    punkt_pod = _el(
        sod,
        "ПунктПод",
        ДатВрПод=supply_dt_vz,
        НалКоорТочВрПод="1",
    )
    _punkt_address(punkt_pod, "АдрПунктПод", load_addr if (load_addr.get("raw") or load_addr.get("Улица")) else shipper_addr)

    # --- АдрПункт Погрузка / Выгрузка ---
    load_for_punkt = load_addr if (load_addr.get("raw") or load_addr.get("Улица")) else shipper_addr
    dest_for_punkt = dest_addr if (dest_addr.get("raw") or dest_addr.get("Улица")) else {
        "Улица": str(item.get("warehouse_name") or "Склад Ozon")[:255],
        "КодРегион": dest_addr.get("КодРегион") or "50",
    }

    adr_load = _el(
        sod,
        "АдрПункт",
        Опер="Погрузка",
        ПорНомПункт="1",
        ДатВрОпер=supply_dt_vz,
        НалКоорТочВрОпер="1",
    )
    _punkt_address(adr_load, "АдресПункт", load_for_punkt)
    if org_full and inn:
        _el(adr_load, "ОргВладИнфр", НаимВладИнфр=org_full, ИННВладИнфр=inn)

    adr_unload = _el(
        sod,
        "АдрПункт",
        Опер="Выгрузка",
        ПорНомПункт="2",
        ДатВрОпер=supply_dt_vz,
        НалКоорТочВрОпер="1",
    )
    _punkt_address(adr_unload, "АдресПункт", dest_for_punkt)

    # --- ОпГруз ---
    op = _el(
        sod,
        "ОпГруз",
        НаимГруз=cargo["cargo_name"],
        СостГруз="Без повреждений",
        Объем=volume,
        ВидТар="00",
        КолГрМест=places,
        МетОпрМасс="03",
        РаспрГр="0",
        ДелГр="1",
    )
    _el(op, "МасГруз", МасБрутЗнач=str(cargo["kg"]))
    _el(op, "РазмерГрМест", ВысЗнач=dim_h, ДлЗнач=dim_l, ШирЗнач=dim_w)
    _el(op, "Пункт", Погр="1", Выгр="2", КолГрМест=places)

    # --- ПарТСПрвз ---
    _el(
        sod,
        "ПарТСПрвз",
        Тип=v_params.get("type") or "грузовой автомобиль",
        Грузопод=v_params.get("capacity_t") or "20",
        Вместим=v_params.get("volume_m3") or volume,
    )

    # --- ПодпИнфГО ---
    podp = _el(
        doc,
        "ПодпИнфГО",
        СпосПодтПолном="1",
        Должн="Уполномоченное лицо",
    )
    fio_attrs = {"Фамилия": s_fam, "Имя": s_imya or "не указано"}
    if s_otch:
        fio_attrs["Отчество"] = s_otch
    _el(podp, "ФИО", **fio_attrs)

    rough = ET.tostring(root, encoding="utf-8")
    try:
        return minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")
    except Exception:
        _log.exception("ozon_zakaz: pretty print failed")
        return b'<?xml version="1.0" encoding="utf-8"?>\n' + rough
