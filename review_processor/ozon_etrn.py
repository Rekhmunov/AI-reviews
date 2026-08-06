"""Ozon FBO eTrN (эТрН) draft XML for Kontur.Logistics upload.

Builds formal title-1 XML (КНД 1110339, ON_TRNACLGROT, ВерсФорм 5.01)
from FeedPilot supply / legal-entity / driver / cargo data. Intended as a
draft the user uploads into Kontur.Logistics and completes/signs there.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any
from xml.dom import minidom

_log = logging.getLogger(__name__)

OZON_CONSIGNEE_NAME = 'Общество с ограниченной ответственностью "Интернет Решения"'
OZON_CONSIGNEE_INN = "7704217370"
OZON_CONSIGNEE_KPP = "997750001"
OZON_CONSIGNEE_EDO_GUID = "2BM-7704217370-774301001-201407110916237240124"

_CARGO_WEIGHT_TONS = {"PALLET": 0.2, "BOX": 0.0125}


def _xml_escape_attr(value: object) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _parse_inn_kpp(text: str) -> tuple[str, str]:
    raw = str(text or "")
    inn_m = re.search(r"ИНН\s*[:=]?\s*(\d{10}|\d{12})", raw, flags=re.I)
    kpp_m = re.search(r"КПП\s*[:=]?\s*(\d{9})", raw, flags=re.I)
    inn = inn_m.group(1) if inn_m else ""
    kpp = kpp_m.group(1) if kpp_m else ""
    if not inn:
        bare = re.search(r"\b(\d{10}|\d{12})\b", raw)
        if bare:
            inn = bare.group(1)
    if not kpp and inn:
        bare_kpp = re.search(r"\b(\d{9})\b", raw)
        if bare_kpp and bare_kpp.group(1) != inn[:9]:
            kpp = bare_kpp.group(1)
    return inn, kpp


def _parse_carrier(text: str) -> tuple[str, str, str]:
    """Return (name, inn, kpp) from free-text carrier field."""
    raw = str(text or "").strip()
    if not raw:
        return "", "", ""
    inn, kpp = _parse_inn_kpp(raw)
    name = raw
    name = re.sub(r"ИНН\s*[:=]?\s*\d{10,12}", "", name, flags=re.I)
    name = re.sub(r"КПП\s*[:=]?\s*\d{9}", "", name, flags=re.I)
    name = re.sub(r"[,/|;]+", " ", name).strip(" -")
    name = re.sub(r"\s{2,}", " ", name)
    return name, inn, kpp


def _split_fio(full_name: str) -> tuple[str, str, str]:
    parts = [p for p in str(full_name or "").strip().split() if p]
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return parts[0], parts[1], " ".join(parts[2:])


def _region_code_from_index(index: str) -> str:
    idx = re.sub(r"\D", "", str(index or ""))
    if len(idx) >= 2:
        return idx[:2]
    return ""


def _parse_ru_address(address: str) -> dict[str, str]:
    """Best-effort split of a free-form Russian address into template fields."""
    raw = str(address or "").strip()
    out = {
        "Индекс": "",
        "КодРегион": "",
        "Район": "",
        "Город": "",
        "НаселПункт": "",
        "Улица": "",
        "Дом": "",
        "Корпус": "",
        "Кварт": "",
        "raw": raw,
    }
    if not raw:
        return out
    idx_m = re.search(r"\b(\d{6})\b", raw)
    if idx_m:
        out["Индекс"] = idx_m.group(1)
        out["КодРегион"] = _region_code_from_index(idx_m.group(1))
    # street + house
    street_m = re.search(
        r"(?:ул\.?|улица|пр-кт|проспект|пер\.?|переулок|ш\.?|шоссе|б-р|бульвар)\s*"
        r"([^,]+?)(?:,|\s+д\.?\s*|\s+дом\s*|$)",
        raw,
        flags=re.I,
    )
    if street_m:
        out["Улица"] = street_m.group(0).strip().rstrip(",")
    house_m = re.search(r"(?:д\.?|дом)\s*([0-9A-Za-zА-Яа-я/-]+)", raw, flags=re.I)
    if house_m:
        out["Дом"] = house_m.group(1)
    # settlement / city leftovers
    if "г." in raw.lower() or "город" in raw.lower():
        city_m = re.search(r"(?:г\.|город)\s*([^,]+)", raw, flags=re.I)
        if city_m:
            out["Город"] = city_m.group(1).strip()
    if "с." in raw.lower() or "село" in raw.lower() or "п." in raw.lower():
        sett_m = re.search(r"(?:с\.|село|п\.|поселок|посёлок)\s*([^,]+)", raw, flags=re.I)
        if sett_m:
            out["НаселПункт"] = sett_m.group(1).strip()
    district_m = re.search(r"(?:р-н|район)\s*([^,]+)", raw, flags=re.I)
    if district_m:
        out["Район"] = ("р-н " + district_m.group(1).strip()).strip()
    return out


def _cargo_stats(cargoes_json: object) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    if isinstance(cargoes_json, list):
        groups = [g for g in cargoes_json if isinstance(g, dict)]
    elif isinstance(cargoes_json, str) and cargoes_json.strip():
        try:
            parsed = json.loads(cargoes_json)
            if isinstance(parsed, list):
                groups = [g for g in parsed if isinstance(g, dict)]
        except Exception:
            groups = []
    pallets = 0
    boxes = 0
    other = 0
    tons = 0.0
    for g in groups:
        typ = str(g.get("type") or "").upper()
        count = int(g.get("count") or 0)
        tons += float(_CARGO_WEIGHT_TONS.get(typ, 0.0)) * count
        if typ == "PALLET":
            pallets += count
        elif typ == "BOX":
            boxes += count
        else:
            other += count
    total_places = pallets + boxes + other
    parts: list[str] = []
    if pallets:
        parts.append(f"{pallets} палет")
    if boxes:
        parts.append(f"{boxes} коробок")
    if other:
        parts.append(f"{other} мест")
    places_label = ", ".join(parts) if parts else ""
    cargo_name = "Текстиль"
    if places_label:
        cargo_name = f"Текстиль. {places_label}"
    kg = int(round(tons * 1000)) if tons > 0 else 0
    return {
        "pallets": pallets,
        "boxes": boxes,
        "other": other,
        "total_places": total_places,
        "tons": tons,
        "kg": kg,
        "places_label": places_label,
        "cargo_name": cargo_name,
    }


def _find_legal_entity(entities: list[dict[str, Any]], supplier_name: str) -> dict[str, Any]:
    supplier = str(supplier_name or "").strip().lower()
    if supplier:
        for e in entities:
            short = str(e.get("short_name") or "").strip().lower()
            full = str(e.get("full_name") or "").strip().lower()
            if supplier and (supplier == short or supplier == full or supplier in short or supplier in full):
                return e
    for e in entities:
        if "ООО" in str(e.get("short_name") or ""):
            return e
    return entities[0] if entities else {}


def _find_driver(drivers: list[dict[str, Any]], driver_name: str) -> dict[str, Any]:
    target = str(driver_name or "").strip().lower()
    if not target:
        return {}
    for d in drivers:
        name = str(d.get("full_name") or "").strip().lower()
        if name == target:
            return d
    # fuzzy: all tokens present
    tokens = [t for t in target.split() if t]
    for d in drivers:
        name = str(d.get("full_name") or "").strip().lower()
        if tokens and all(t in name for t in tokens):
            return d
    return {}


def _vehicle_parts(vehicle_json: object, fallback_line: str = "") -> tuple[str, str]:
    model, number = "", ""
    data: dict[str, Any] = {}
    if isinstance(vehicle_json, dict):
        data = vehicle_json
    elif isinstance(vehicle_json, str) and vehicle_json.strip() and vehicle_json.strip() != "{}":
        try:
            parsed = json.loads(vehicle_json)
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = {}
    model = str(data.get("vehicle_model") or "").strip()
    number = str(data.get("vehicle_number") or "").strip()
    if not model and not number and fallback_line:
        # "MODEL A123BC77" — last token often plate
        parts = str(fallback_line).strip().split()
        if parts:
            maybe_plate = parts[-1]
            if re.search(r"\d", maybe_plate):
                number = maybe_plate
                model = " ".join(parts[:-1]).strip()
            else:
                model = str(fallback_line).strip()
    return model, number


def _el(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    clean_attrs = {k: str(v) for k, v in attrs.items() if v is not None and str(v) != ""}
    node = ET.SubElement(parent, tag, clean_attrs)
    if text is not None:
        node.text = str(text)
    return node


def build_ozon_etrn_xml(
    *,
    item: dict[str, Any],
    le: dict[str, Any] | None = None,
    driver_name: str = "",
    driver_phone: str = "",
    vehicle_line: str = "",
    vehicle_json: object = None,
    cargoes_json: object = None,
    load_address: str = "",
    delivery_address: str = "",
    carrier_text: str = "",
    now: datetime | None = None,
) -> bytes:
    """Build formal eTrN title-1 XML draft bytes (UTF-8)."""
    now = now or datetime.now()
    le = le or {}
    supply_num = str(item.get("supply_order_number") or item.get("supply_order_id") or "").strip()
    org_full = str(le.get("full_name") or le.get("short_name") or item.get("supplier_name") or "").strip()
    org_req = str(le.get("requisites") or "")
    inn, kpp = _parse_inn_kpp(org_req)
    if not inn:
        inn, kpp2 = _parse_inn_kpp(org_full)
        kpp = kpp or kpp2

    load_addr = _parse_ru_address(load_address)
    dest_addr = _parse_ru_address(delivery_address)
    # Prefer structured production address for shipper legal address if requisites lack one
    shipper_addr = load_addr if load_addr.get("raw") else dest_addr

    cargo = _cargo_stats(cargoes_json if cargoes_json is not None else item.get("cargoes_json"))
    fam, imya, otch = _split_fio(driver_name)
    v_model, v_number = _vehicle_parts(
        vehicle_json if vehicle_json is not None else item.get("vehicle_json"),
        fallback_line=vehicle_line,
    )
    carrier_name, carrier_inn, carrier_kpp = _parse_carrier(carrier_text)

    date_ru = now.strftime("%d.%m.%Y")
    time_ru = now.strftime("%H:%M:%S")
    date_file = now.strftime("%Y%m%d")
    file_guid = str(uuid.uuid4())

    shipper_edo = ""
    if inn:
        shipper_edo = f"2BM-{inn}-{kpp or '000000000'}-DRAFT"
    # A=carrier empty, E=Ozon GUID, O=shipper draft id (Kontur may rewrite on import)
    id_file = (
        f"ON_TRNACLGROT_"
        f"_"
        f"{OZON_CONSIGNEE_EDO_GUID}_"
        f"{shipper_edo or 'DRAFT'}_"
        f"0_"
        f"{date_file}_"
        f"{file_guid}"
    )

    root = ET.Element(
        "Файл",
        {
            "ИдФайл": id_file,
            "ВерсФорм": "5.01",
            "ВерсПрог": "FeedPilot 1.0",
        },
    )
    doc = _el(
        root,
        "Документ",
        КНД="1110339",
        ПоФактХЖ="Транспортная накладная, информация грузоотправителя",
        ДатИнфГО=date_ru,
        ВрИнфГО=time_ru,
    )
    sod = _el(
        doc,
        "СодИнфГО",
        СодОпер=(
            "Лицом, осуществляющим погрузку груза, при указанных обстоятельствах "
            "передан водителю груз с указанными характеристиками"
        ),
        НомерТрН=supply_num,
        ДатаТрН=date_ru,
        НомЗак=supply_num or "Без номера",
        ДатаЗак=date_ru,
    )

    # Ozon-required supply number
    if supply_num:
        inf = _el(sod, "ИнфПол")
        _el(inf, "ТекстИнф", Идентиф="Orders", Значен=supply_num)

    # Shipper
    sv_go = _el(sod, "СвГО", ГОЭксп="0")
    rek_go = _el(sv_go, "РекИдентГО")
    id_go = _el(rek_go, "ИдСв")
    go_attrs = {"НаимОрг": org_full}
    if inn:
        go_attrs["ИННЮЛ"] = inn
    if kpp:
        go_attrs["КПП"] = kpp
    _el(id_go, "СвЮЛУч", **go_attrs)
    adr_go = _el(rek_go, "Адрес")
    adr_rf_attrs = {
        k: shipper_addr[k]
        for k in ("Индекс", "КодРегион", "Район", "Город", "НаселПункт", "Улица", "Дом")
        if shipper_addr.get(k)
    }
    if adr_rf_attrs:
        _el(adr_go, "АдрРФ", **adr_rf_attrs)
    elif shipper_addr.get("raw"):
        # Keep raw address visible for manual fix in Kontur
        _el(adr_go, "АдрРФ", Улица=shipper_addr["raw"][:255])
    contact_go = _el(rek_go, "Контакт")
    _el(contact_go, "Тлф")

    # Consignee — Ozon
    sv_gp = _el(sod, "СвГП")
    rek_gp = _el(sv_gp, "РекИдентГП")
    id_gp = _el(rek_gp, "ИдСв")
    _el(
        id_gp,
        "СвЮЛУч",
        НаимОрг=OZON_CONSIGNEE_NAME,
        ИННЮЛ=OZON_CONSIGNEE_INN,
        КПП=OZON_CONSIGNEE_KPP,
    )
    contact_gp = _el(rek_gp, "Контакт")
    _el(contact_gp, "Тлф")
    adr_dost = _el(sv_gp, "АдресДостГр")
    dest_attrs = {
        k: dest_addr[k]
        for k in ("Индекс", "КодРегион", "Район", "Город", "НаселПункт", "Улица", "Дом")
        if dest_addr.get(k)
    }
    if dest_attrs:
        _el(adr_dost, "АдрРФ", **dest_attrs)
    elif dest_addr.get("raw"):
        _el(adr_dost, "АдрРФ", Улица=dest_addr["raw"][:255])
    else:
        _el(adr_dost, "КодГАР")

    # Cargo
    sv_gruz = _el(sod, "СвГруз")
    op_attrs = {
        "НаимГруз": cargo["cargo_name"],
        "СостГруз": "Исправное",
        "СпУпак": cargo["places_label"] or "Отсутствует",
        "ВидТар": "00",
        "УчГосСист": "0",
    }
    if cargo["total_places"]:
        op_attrs["КолМестГр"] = str(cargo["total_places"])
    op = _el(sv_gruz, "ОпГруз", **op_attrs)
    _el(op, "Марк", "Отсутствует")
    mass_attrs = {}
    if cargo["kg"]:
        mass_attrs["МасБрутЗнач"] = str(cargo["kg"])
    _el(op, "ПлМасГруз", **mass_attrs)

    # Instructions
    ukaz = _el(sod, "УказГО", УкНормПрвз="Отсутствует", ЗапрПерегруз="0")
    sv_pa = _el(
        ukaz,
        "СвПА",
        СпосПерУкПА="Электронное уведомление перевозчика о переадресовке",
        ЛицоПА="Грузоотправитель",
    )
    kont_pa = _el(sv_pa, "КонтПА")
    _el(kont_pa, "Тлф")

    # Carrier
    sv_per = _el(sod, "СвПер")
    id_per = _el(sv_per, "ИдСв")
    per_attrs = {"НаимОрг": carrier_name}
    if carrier_inn:
        per_attrs["ИННЮЛ"] = carrier_inn
    if carrier_kpp:
        per_attrs["КПП"] = carrier_kpp
    _el(id_per, "СвЮЛУч", **per_attrs)
    contact_per = _el(sv_per, "Контакт")
    _el(contact_per, "Тлф")

    # Driver
    sv_vod = _el(sod, "СвВодит")
    if driver_phone:
        _el(sv_vod, "Тлф", driver_phone)
    else:
        _el(sv_vod, "Тлф")
    fio_attrs = {"Фамилия": fam, "Имя": imya}
    if otch:
        fio_attrs["Отчество"] = otch
    _el(sv_vod, "ФИО", **fio_attrs)

    # Vehicle
    sv_ts = _el(sod, "СвТС")
    ts_attrs = {}
    if v_number:
        ts_attrs["РегНомер"] = v_number
    ts_attrs["ТипВлад"] = ts_attrs.get("ТипВлад") or ""
    ts = _el(sv_ts, "ТС", **{k: v for k, v in ts_attrs.items() if v != "" or k == "ТипВлад"})
    # Ensure РегНомер/ТипВлад exist like template even if empty
    if "РегНомер" not in ts.attrib:
        ts.set("РегНомер", v_number)
    if "ТипВлад" not in ts.attrib:
        ts.set("ТипВлад", "")
    part_attrs = {"Тип": "", "Марка": v_model, "Грузопод": "", "Вместим": ""}
    _el(ts, "ПарТС", **part_attrs)

    # Loading
    load_attrs = {
        "ЗаявПогр": f"{date_ru}T00:00:00+03:00",
        "НалКоорТочВрЗаяв": "1",
        "ФДатВрПриб": f"{date_ru}T00:00:00+03:00",
        "НалКоорТочВрФПогр": "1",
        "ФДатВрУбыт": f"{date_ru}T00:00:00+03:00",
        "НалКоорТочВрФУбыт": "1",
        "МетОпрМасс": "01",
    }
    if cargo["kg"]:
        load_attrs["МасБрутОтгр"] = str(cargo["kg"])
    if cargo["total_places"]:
        load_attrs["КолМестПрием"] = str(cargo["total_places"])
    sv_pogr = _el(sod, "СвПогруз", **load_attrs)
    f_adr = _el(sv_pogr, "ФАдресПогр")
    load_rf = {
        k: load_addr[k]
        for k in ("Индекс", "КодРегион", "Район", "Город", "НаселПункт", "Улица", "Дом")
        if load_addr.get(k)
    }
    if load_rf:
        _el(f_adr, "АдрРФ", **load_rf)
    elif load_addr.get("raw"):
        _el(f_adr, "АдрРФ", Улица=load_addr["raw"][:255])
    else:
        _el(f_adr, "КодГАР")

    lich = _el(sv_pogr, "СвЛицПогрГр", СовпГОП="1")
    ident = _el(lich, "ИдентРекГО")
    if inn:
        _el(ident, "ИННЮЛ", inn)
    vlad = _el(sv_pogr, "ВладИнфр", СовпГОВ="1")
    ident2 = _el(vlad, "ИдентРекГО")
    if inn:
        _el(ident2, "ИННЮЛ", inn)

    rough = ET.tostring(root, encoding="utf-8")
    try:
        pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")
        # minidom adds XML declaration; ensure no extra blank first line issues
        return pretty
    except Exception:
        _log.exception("ozon_etrn: pretty print failed")
        return b'<?xml version="1.0" encoding="utf-8"?>\n' + rough


def collect_ozon_etrn_context(
    *,
    repository: Any,
    owner_id: int,
    item: dict[str, Any],
    driver_name: str = "",
    driver_phone: str = "",
    vehicle_line: str = "",
) -> dict[str, Any]:
    """Resolve addresses / LE / carrier extras for XML build."""
    entities = repository.list_supply_legal_entities(user_id=owner_id)
    le = _find_legal_entity(entities, str(item.get("supplier_name") or ""))
    drivers = repository.list_supply_drivers(user_id=owner_id)
    driver_row = _find_driver(drivers, driver_name)
    carrier_text = str((driver_row or {}).get("carrier") or "")

    production_name = str(item.get("production") or "").strip()
    load_address = ""
    if production_name:
        for p in repository.list_supply_productions(user_id=owner_id):
            if str(p.get("name") or "").strip() == production_name:
                load_address = str(p.get("address") or "").strip()
                break

    dest_wh = str(item.get("warehouse_name") or "").strip()
    transit_wh = str(item.get("transit_warehouse_name") or "").strip()
    pickup_wh = transit_wh or dest_wh
    delivery_address = ""
    if pickup_wh:
        for w in repository.list_supply_warehouses(user_id=owner_id):
            if str(w.get("warehouse_name") or "").strip() == pickup_wh:
                delivery_address = str(w.get("address") or "").strip()
                break
    if not delivery_address:
        delivery_address = pickup_wh

    return {
        "le": le,
        "carrier_text": carrier_text,
        "load_address": load_address,
        "delivery_address": delivery_address,
        "driver_name": driver_name,
        "driver_phone": driver_phone,
        "vehicle_line": vehicle_line,
    }
