"""Ozon FBO заказ-заявка (ЭЗЗ) draft XML for Kontur.Logistics upload.

Builds title-1 XML (КНД 1110361, ON_ZAKZVGO, ВерсФорм 5.01)
per FNS order ЕД-7-26/108@ — same data sources as eTrN draft.

Kontur.Logistics rejects the file on import when XSD-required fields are
missing/empty (esp. АдрРФ/Индекс, Конт/Тлф, N(5.2)/N(5.3) numerics).
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any
from xml.dom import minidom
from xml.etree import ElementTree as ET

from .ozon_etrn import (
    OZON_CONSIGNEE_EDO_GUID,
    OZON_CONSIGNEE_INN,
    OZON_CONSIGNEE_NAME,
    _addr_from_carrier_fields,
    _addr_from_production_fields,
    _cargo_stats,
    _carrier_org_from_fields,
    _el,
    _extract_address_from_requisites,
    _format_dt_vz,
    _has_structured_address,
    _ozon_supply_number,
    _parse_carrier,
    _parse_inn_kpp,
    _parse_ru_address,
    _region_code_from_text,
    _region_from_postal_index,
    _split_fio,
    _vehicle_params,
)

_log = logging.getLogger(__name__)

# Fixed Ozon FBO consignee FNSId (same value as eTrN ИдФайл/E).
OZON_FNS_ID = OZON_CONSIGNEE_EDO_GUID

# Representative postal indexes when only КодРегион is known (АдрРФ/Индекс is required).
_DEFAULT_INDEX_BY_REGION: dict[str, str] = {
    "02": "450000",
    "16": "420000",
    "23": "350000",
    "24": "660000",
    "34": "400000",
    "36": "394000",
    "39": "236000",
    "47": "187000",
    "50": "140000",
    "52": "603000",
    "54": "630000",
    "59": "614000",
    "61": "344000",
    "62": "390000",
    "63": "443000",
    "64": "410000",
    "66": "620000",
    "71": "300000",
    "72": "625000",
    "74": "454000",
    "77": "101000",
    "78": "190000",
}


def _fmt_n52(value: object, *, default: str = "1.00") -> str:
    """FNS N(5.2) — e.g. Объем / Грузопод / Вместим."""
    raw = str(value or "").strip().replace(",", ".")
    try:
        return f"{float(raw):.2f}"
    except ValueError:
        return default


def _fmt_n53(value: object, *, default: str = "1.000") -> str:
    """FNS N(5.3) — габариты РазмерГрМест."""
    raw = str(value or "").strip().replace(",", ".")
    try:
        return f"{float(raw):.3f}"
    except ValueError:
        return default


def _fmt_mass(value: object, *, default: str = "1.000") -> str:
    """FNS N(17.3) — МасБрутЗнач."""
    raw = str(value or "").strip().replace(",", ".")
    try:
        return f"{float(raw):.3f}"
    except ValueError:
        return default


def _normalize_phone(phone: str) -> str:
    phone = re.sub(r"[^\d+]", "", str(phone or "").strip())
    # Keep only the first number if several were glued by stripping separators.
    if phone.count("+") > 1:
        phone = "+" + phone.split("+", 2)[1]
    if phone.startswith("8") and len(re.sub(r"\D", "", phone)) == 11:
        phone = "+7" + re.sub(r"\D", "", phone)[1:]
    elif phone.startswith("7") and len(phone) == 11:
        phone = "+" + phone
    elif phone.startswith("+7") and len(re.sub(r"\D", "", phone)) == 11:
        phone = "+7" + re.sub(r"\D", "", phone)[1:]
    return phone


def _phone_from_requisites(requisites: str) -> str:
    """Same fallback as эТрН: pull +7/8 phone from юр.лица requisites text."""
    phone_m = re.search(r"(?:\+7|8)\s*[\d\-()\s]{9,}", str(requisites or ""))
    if not phone_m:
        return ""
    return _normalize_phone(phone_m.group(0))


def _shipper_phone_from_le(le: dict[str, Any] | None) -> str:
    """СвГО/Конт/Тлф ← телефон юр.лица (поле phone, иначе из реквизитов)."""
    le = le or {}
    phone = _normalize_phone(str(le.get("phone") or ""))
    if phone:
        return phone
    return _phone_from_requisites(str(le.get("requisites") or ""))


def _add_kont(parent: ET.Element, phone: str) -> None:
    """ЭЗЗ: Конт is required; Тлф is ОМ T(1-255) — must be non-empty."""
    kont = _el(parent, "Конт")
    phone = _normalize_phone(phone)
    if not phone:
        phone = "+70000000000"
    _el(kont, "Тлф", phone)


def _ensure_adr(addr: dict[str, str] | None, *, fallback_label: str = "Адрес уточнить") -> dict[str, str]:
    """Guarantee АдрРФ required attrs: Индекс (6) + КодРегион (2)."""
    out = dict(addr or {})
    raw = str(out.get("raw") or "").strip()
    idx = re.sub(r"\D", "", str(out.get("Индекс") or ""))
    if len(idx) >= 6:
        out["Индекс"] = idx[:6]
    elif raw:
        m = re.search(r"\b(\d{6})\b", raw)
        if m:
            out["Индекс"] = m.group(1)
            idx = m.group(1)
        else:
            idx = ""
    else:
        idx = ""

    region = str(out.get("КодРегион") or "").strip()
    if not region:
        region = _region_code_from_text(raw, out.get("Индекс", "")) or _region_from_postal_index(
            out.get("Индекс", "")
        )
    if not region:
        region = "77"
    out["КодРегион"] = region.zfill(2)[-2:]

    if not out.get("Индекс") or len(re.sub(r"\D", "", out.get("Индекс", ""))) != 6:
        out["Индекс"] = _DEFAULT_INDEX_BY_REGION.get(out["КодРегион"], "101000")

    if not any(out.get(k) for k in ("Улица", "Город", "НаселПункт", "Дом")):
        label = raw or fallback_label
        out["Улица"] = str(label)[:255]
    return out


def _addr_block(parent: ET.Element, addr: dict[str, str] | None) -> None:
    """Emit participant Адрес/АдрРФ only when we have something real-ish."""
    if not addr:
        return
    if not (addr.get("raw") or addr.get("Индекс") or addr.get("Улица") or addr.get("Город")):
        return
    ensured = _ensure_adr(addr)
    adr = _el(parent, "Адрес")
    attrs = {
        k: ensured[k]
        for k in ("Индекс", "КодРегион", "Район", "Город", "НаселПункт", "Улица", "Дом", "Корпус", "Кварт")
        if ensured.get(k)
    }
    _el(adr, "АдрРФ", **attrs)


def _punkt_address(parent: ET.Element, wrapper_tag: str, addr: dict[str, str] | None, *, label: str) -> None:
    ensured = _ensure_adr(addr, fallback_label=label)
    wrap = _el(parent, wrapper_tag)
    adr = _el(wrap, "Адрес")
    attrs = {
        k: ensured[k]
        for k in ("Индекс", "КодРегион", "Район", "Город", "НаселПункт", "Улица", "Дом", "Корпус", "Кварт")
        if ensured.get(k)
    }
    _el(adr, "АдрРФ", **attrs)


def _fns_participant_id(inn: str, kpp: str = "", *, now: datetime | None = None) -> str:
    inn = str(inn or "").strip()
    kpp = str(kpp or "").strip() or "000000000"
    if not inn:
        return ""
    # Shape close to Diadoc FNSId: 2BM-{INN}-{KPP}-{21 digits}
    stamp = (now or datetime.now()).strftime("%Y%m%d%H%M%S") + "0000000"
    return f"2BM-{inn}-{kpp}-{stamp[:21]}"


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

    # Грузоотправитель: только телефон юр.лица (поле / реквизиты).
    # Водительский номер сюда не подставляем — иначе в Contour у ГО «чужой» телефон.
    contact_phone = _shipper_phone_from_le(le)
    if not contact_phone:
        # Last-resort XSD fill only; Contour still needs non-empty Тлф.
        contact_phone = _normalize_phone(str(driver_phone or ""))
        if not contact_phone and isinstance(driver_fields, dict):
            contact_phone = _normalize_phone(str(driver_fields.get("phone") or ""))

    carrier_addr = _addr_from_carrier_fields(carrier_fields)
    if not _has_structured_address(carrier_addr):
        carrier_addr = _parse_ru_address(_extract_address_from_requisites(carrier_text))
    if not _has_structured_address(carrier_addr):
        carrier_addr = dict(shipper_addr)

    signer_src = str(le.get("signatories") or le.get("in_person") or "").strip()
    s_fam, s_imya, s_otch = _split_fio(signer_src)
    if not s_fam:
        s_fam, s_imya = "Не", "указан"

    date_ru = now.strftime("%d.%m.%Y")
    time_ru = now.strftime("%H:%M:%S")
    file_date = now.strftime("%Y%m%d")
    shipper_edo = _fns_participant_id(inn, kpp, now=now) or "2BM-DRAFT-SHIPPER"
    # Prefer catalog FNSId (Водители → Перевозчик); else draft from ИНН/КПП.
    carrier_edo = ""
    if isinstance(carrier_fields, dict):
        carrier_edo = str(carrier_fields.get("carrier_fns_id") or "").strip()
    if not carrier_edo:
        carrier_edo = _fns_participant_id(carrier_inn, carrier_kpp, now=now)
    # R_T_A_O_W_GGGGMMDD_N — A=carrier (may be empty), O=shipper.
    # Ozon FNSId (грузополучатель FBO) is fixed in eTrN ИдФайл/E = OZON_CONSIGNEE_EDO_GUID.
    file_id = f"ON_ZAKZVGO_{carrier_edo}_{shipper_edo}_0_{file_date}_{uuid.uuid4()}"

    naim_subj = org_full or "Грузоотправитель"
    if inn:
        naim_subj = f"{naim_subj}, ИНН {inn}" + (f", КПП {kpp}" if kpp else "")

    vol_from_fields = str((vehicle_fields or {}).get("volume_m3") or "").strip()
    if vol_from_fields:
        volume = _fmt_n52(vol_from_fields)
    elif cargo["pallets"] > 0:
        volume = _fmt_n52(max(1.0, cargo["pallets"] * 1.5))
    elif cargo["boxes"] > 0:
        volume = _fmt_n52(max(0.1, cargo["boxes"] * 0.08))
    else:
        volume = _fmt_n52(v_params.get("volume_m3") or "20")
    capacity = _fmt_n52(v_params.get("capacity_t") or "20")
    capacity_vol = _fmt_n52(vol_from_fields or v_params.get("volume_m3") or volume)

    places = str(max(1, int(cargo["total_places"] or 1)))
    if cargo["pallets"] > 0:
        dim_h, dim_l, dim_w = "1.800", "1.200", "0.800"
    else:
        dim_h, dim_l, dim_w = "0.400", "0.600", "0.400"

    supply_dt_vz = _format_dt_vz(item.get("supply_date"), fallback=now)
    # ДатаВремяВЗТип is T(=25)
    if len(supply_dt_vz) != 25:
        supply_dt_vz = f"{now.strftime('%d.%m.%Y')}T{now.strftime('%H:%M:%S')}+03:00"

    shipper_addr = _ensure_adr(shipper_addr, fallback_label=org_full or "Адрес грузоотправителя")
    load_for_punkt = _ensure_adr(
        load_addr if (load_addr.get("raw") or load_addr.get("Улица") or load_addr.get("Индекс")) else shipper_addr,
        fallback_label="Пункт погрузки",
    )
    dest_for_punkt = _ensure_adr(
        dest_addr
        if (dest_addr.get("raw") or dest_addr.get("Улица") or dest_addr.get("Индекс"))
        else {
            "Улица": str(item.get("warehouse_name") or "Склад Ozon")[:255],
            "КодРегион": dest_addr.get("КодРегион") or "50",
            "raw": str(delivery_address or item.get("warehouse_name") or ""),
        },
        fallback_label=str(item.get("warehouse_name") or "Склад Ozon"),
    )

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
        # FNS text uses «Отсутствуют»; Contour/Diadoc samples also accept «Отсутствует».
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
    # Carrier phone from catalog; fallback to юр.лица / driver (contact_phone).
    carrier_phone = ""
    if isinstance(carrier_fields, dict):
        carrier_phone = _normalize_phone(str(carrier_fields.get("carrier_phone") or ""))
    if not carrier_phone:
        carrier_phone = contact_phone
    _add_kont(sv_prv, carrier_phone)

    # --- ПунктПод ---
    punkt_pod = _el(
        sod,
        "ПунктПод",
        ДатВрПод=supply_dt_vz,
        НалКоорТочВрПод="1",
    )
    _punkt_address(punkt_pod, "АдрПунктПод", load_for_punkt, label="Пункт подачи ТС")

    # --- АдрПункт Погрузка / Выгрузка ---
    adr_load = _el(
        sod,
        "АдрПункт",
        Опер="Погрузка",
        ПорНомПункт="1",
        ДатВрОпер=supply_dt_vz,
        НалКоорТочВрОпер="1",
    )
    _punkt_address(adr_load, "АдресПункт", load_for_punkt, label="Пункт погрузки")
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
    _punkt_address(adr_unload, "АдресПункт", dest_for_punkt, label="Пункт выгрузки")
    # Ozon FBO consignee (fixed org + FNSId used in eTrN ИдФайл).
    _el(
        adr_unload,
        "ОргВладИнфр",
        НаимВладИнфр=OZON_CONSIGNEE_NAME,
        ИННВладИнфр=OZON_CONSIGNEE_INN,
    )

    # --- ОпГруз ---
    op = _el(
        sod,
        "ОпГруз",
        НаимГруз=cargo["cargo_name"] or "Товар",
        СостГруз="Без повреждений",
        Объем=volume,
        ВидТар="00",
        КолГрМест=places,
        МетОпрМасс="03",
        РаспрГр="0",
        ДелГр="1",
    )
    _el(op, "МасГруз", МасБрутЗнач=_fmt_mass(cargo["kg"] or 1))
    _el(op, "РазмерГрМест", ВысЗнач=dim_h, ДлЗнач=dim_l, ШирЗнач=dim_w)
    _el(op, "Пункт", Погр="1", Выгр="2", КолГрМест=places)

    # --- ПарТСПрвз ---
    _el(
        sod,
        "ПарТСПрвз",
        Тип=v_params.get("type") or "грузовой автомобиль",
        Грузопод=capacity,
        Вместим=capacity_vol,
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
