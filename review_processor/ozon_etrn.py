"""Ozon FBO eTrN (эТрН) draft XML for Kontur.Logistics upload.

Builds formal title-1 XML (КНД 1110339, ON_TRNACLGROT, ВерсФорм 5.01)
from FeedPilot supply / legal-entity / driver / cargo data. Intended as a
draft the user uploads into Kontur.Logistics and completes/signs there.

Schema references:
- FNS order ЕД-7-26/1065@ (format 5.01)
- Diadoc GenerateTitleXml sample (АдресРФ vs АдрРФ, Подписант)
- Kontur.Logistics InfPol keys (ORDERS / Значение)
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

# Best-effort region codes for common city/region names (OKATO/КЛАДР first digits).
_REGION_BY_NAME: tuple[tuple[str, str], ...] = (
    ("москва", "77"),
    ("санкт-петербург", "78"),
    ("петербург", "78"),
    ("ленинград", "47"),
    ("московск", "50"),
    ("новосибирск", "54"),
    ("екатеринбург", "66"),
    ("свердловск", "66"),
    ("казань", "16"),
    ("татарстан", "16"),
    ("нижегород", "52"),
    ("нижегородская", "52"),
    ("краснодар", "23"),
    ("ростов", "61"),
    ("самар", "63"),
    ("челябинск", "74"),
    ("омск", "55"),
    ("воронеж", "36"),
    ("перм", "59"),
    ("волгоград", "34"),
    ("красноярск", "24"),
    ("саратов", "64"),
    ("тюмен", "72"),
    ("уфа", "02"),
    ("башкортостан", "02"),
    ("тула", "71"),
    ("калининград", "39"),
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


def _region_code_from_text(address: str, index: str = "") -> str:
    low = str(address or "").lower()
    for needle, code in _REGION_BY_NAME:
        if needle in low:
            return code
    # Postal index first two digits are only a rough fallback (not always OKATO).
    idx = re.sub(r"\D", "", str(index or ""))
    if len(idx) >= 2:
        return idx[:2]
    return ""


def _extract_address_from_requisites(requisites: str) -> str:
    """Pull legal address text from supply legal-entity requisites field only."""
    raw = str(requisites or "").strip()
    if not raw:
        return ""
    m = re.search(
        r"(?:юр\.?\s*адрес|юридический\s*адрес|фактический\s*адрес|адрес)\s*[:=]?\s*(.+)",
        raw,
        flags=re.I | re.S,
    )
    if m:
        candidate = m.group(1).strip()
        candidate = re.split(
            r"\n|(?:р/?с|к/?с|расчетн|бик|банк)\b",
            candidate,
            maxsplit=1,
            flags=re.I,
        )[0].strip(" .;,")
        if candidate:
            return candidate[:500]

    cleaned = raw
    cleaned = re.sub(r"ИНН\s*[:=]?\s*\d{10,12}", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"КПП\s*[:=]?\s*\d{9}", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"ОГРН\s*[:=]?\s*\d+", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"(?:р/?с|к/?с|бик|банк)[^\n]*", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.;")
    if not cleaned:
        return ""
    idx_m = re.search(r"\b\d{6}\b.{5,300}", cleaned)
    if idx_m:
        return idx_m.group(0).strip(" ,.;")[:500]
    if re.search(
        r"(?:г\.|город|ул\.|улица|д\.|дом|обл|край|район|пос|деревн|стр\.|строение)",
        cleaned,
        flags=re.I,
    ):
        return cleaned[:500]
    return cleaned[:500]


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
    out["КодРегион"] = _region_code_from_text(raw, out["Индекс"])

    # Word-bounded street markers only (bare «ш»/«д» must not match inside words).
    street_m = re.search(
        r"(?<![А-Яа-яA-Za-z])"
        r"(?:ул\.|улица|пр-кт|проспект|пер\.|переулок|ш\.|шоссе|б-р|бульвар)"
        r"\s*([^,]+?)(?=,|\s+(?:д\.|дом)\s*\d|$)",
        raw,
        flags=re.I,
    )
    if street_m:
        out["Улица"] = street_m.group(0).strip().rstrip(",")

    # House: «д.» / «дом» / «стр.» / «строение» — never bare «д» (деревня).
    house_m = re.search(
        r"(?:^|[\s,])(?:д\.|дом|стр\.|строение)\s*([0-9A-Za-zА-Яа-я/-]+)",
        raw,
        flags=re.I,
    )
    if house_m:
        out["Дом"] = house_m.group(1)

    city_m = re.search(r"(?<![А-Яа-яA-Za-z])(?:г\.|город)\s*([^,]+)", raw, flags=re.I)
    if city_m:
        out["Город"] = city_m.group(1).strip()
    # Village / settlement name (деревня X / пос. X).
    sett_m = re.search(
        r"(?<![А-Яа-яA-Za-z])(?:деревня|село|посёлок|поселок|пос\.)\s*([^,]+)",
        raw,
        flags=re.I,
    )
    if sett_m:
        out["НаселПункт"] = sett_m.group(1).strip()
    district_m = re.search(
        r"([^,]+?)\s+(?:р-н|район)\b",
        raw,
        flags=re.I,
    )
    if district_m:
        out["Район"] = district_m.group(1).strip() + " р-н"
    return out


def _parse_driver_license(documents: str) -> dict[str, str]:
    """Extract VU series/number/date or INNFL from free-text driver documents."""
    raw = str(documents or "")
    out = {"СерВУ": "", "НомВУ": "", "ДатаВыдВУ": "", "ИННФЛ": ""}
    if not raw:
        return out
    inn_m = re.search(r"ИНН\s*[:=]?\s*(\d{12})", raw, flags=re.I)
    if inn_m:
        out["ИННФЛ"] = inn_m.group(1)
    date_m = re.search(
        r"(?:выд|выдач|от)\s*[.:]?\s*(\d{2}\.\d{2}\.\d{4})",
        raw,
        flags=re.I,
    )
    if date_m:
        out["ДатаВыдВУ"] = date_m.group(1)
    # «ВУ 99 00 123456» / «серия 99 00 номер 123456»
    vu_m = re.search(
        r"(?:ву|в/у|водительск\w*\s*уд\w*)\s*[:.]?\s*"
        r"(\d{2})\s*(\d{2})\s+(\d{6})",
        raw,
        flags=re.I,
    )
    if vu_m:
        out["СерВУ"] = f"{vu_m.group(1)}{vu_m.group(2)}"
        out["НомВУ"] = vu_m.group(3)
        return out
    ser_m = re.search(r"сери[яи]\s*[:=]?\s*(\d{2})\s*(\d{2})", raw, flags=re.I)
    num_m = re.search(r"(?:номер|№)\s*[:=]?\s*(\d{6})", raw, flags=re.I)
    if ser_m and num_m:
        out["СерВУ"] = f"{ser_m.group(1)}{ser_m.group(2)}"
        out["НомВУ"] = num_m.group(1)
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
    # Required by schema: never emit empty place/mass fields.
    if total_places <= 0:
        total_places = 1
        places_label = places_label or "1 место (уточнить)"
        cargo_name = "Текстиль (количество мест уточнить)"
    if kg <= 0:
        kg = 1
    return {
        "pallets": pallets,
        "boxes": boxes,
        "other": other,
        "total_places": total_places,
        "tons": tons,
        "kg": kg,
        "places_label": places_label or "Отсутствует",
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
        parts = str(fallback_line).strip().split()
        if parts:
            maybe_plate = parts[-1]
            if re.search(r"\d", maybe_plate):
                number = maybe_plate
                model = " ".join(parts[:-1]).strip()
            else:
                model = str(fallback_line).strip()
    # РегНомер is T(1-9) in schema — keep first 9 chars if longer.
    if len(number) > 9:
        number = number[:9]
    return model, number


def _el(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    clean_attrs = {k: str(v) for k, v in attrs.items() if v is not None and str(v) != ""}
    node = ET.SubElement(parent, tag, clean_attrs)
    if text is not None:
        node.text = str(text)
    return node


def _add_phone(parent: ET.Element, tag: str, phone: str) -> None:
    phone = str(phone or "").strip()
    if phone:
        _el(parent, tag, phone)


def _add_contact(parent: ET.Element, phone: str) -> None:
    phone = str(phone or "").strip()
    if not phone:
        return
    contact = _el(parent, "Контакт")
    _el(contact, "Тлф", phone)


def _add_adr_rf(parent: ET.Element, tag: str, addr: dict[str, str]) -> None:
    """Always emit АдрРФ / АдресРФ (never АдрИнф — Kontur shows that as foreign)."""
    raw = str(addr.get("raw") or "").strip()
    attrs = {
        k: addr[k]
        for k in ("Индекс", "КодРегион", "Район", "Город", "НаселПункт", "Улица", "Дом", "Корпус", "Кварт")
        if addr.get(k)
    }
    if not attrs.get("КодРегион"):
        code = _region_code_from_text(raw, attrs.get("Индекс", ""))
        if code:
            attrs["КодРегион"] = code
    # Keep Russian address type; if structured parse is weak, prefer full raw in Улица.
    if raw and not attrs.get("Улица") and not attrs.get("Индекс"):
        attrs["Улица"] = raw[:255]
    elif raw and not attrs.get("Улица") and not any(
        attrs.get(k) for k in ("Город", "НаселПункт", "Дом")
    ):
        attrs["Улица"] = raw[:255]
    if not attrs and not raw:
        return
    if not attrs:
        attrs = {"Улица": raw[:255]}
    _el(parent, tag, **attrs)


def build_ozon_etrn_xml(
    *,
    item: dict[str, Any],
    le: dict[str, Any] | None = None,
    driver_name: str = "",
    driver_phone: str = "",
    driver_documents: str = "",
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
    # Shipper legal address from Поставки → Настройки → Юр.лица.
    # Prefer dedicated `address` column; fall back to parsing requisites for old data.
    # Never substitute production/warehouse (load/delivery) addresses here.
    legal_addr_raw = str(le.get("address") or "").strip() or _extract_address_from_requisites(org_req)
    shipper_addr = _parse_ru_address(legal_addr_raw)

    cargo = _cargo_stats(cargoes_json if cargoes_json is not None else item.get("cargoes_json"))
    fam, imya, otch = _split_fio(driver_name)
    if not fam:
        fam, imya = "Не", "указан"
    v_model, v_number = _vehicle_parts(
        vehicle_json if vehicle_json is not None else item.get("vehicle_json"),
        fallback_line=vehicle_line,
    )
    carrier_name, carrier_inn, carrier_kpp = _parse_carrier(carrier_text)
    if not carrier_name:
        carrier_name = "Перевозчик (уточнить)"
    vu = _parse_driver_license(driver_documents)

    signer_src = str(le.get("signatories") or le.get("in_person") or "").strip()
    s_fam, s_imya, s_otch = _split_fio(signer_src)
    if not s_fam:
        s_fam, s_imya = "Не", "указан"

    contact_phone = str(driver_phone or "").strip()
    if not contact_phone:
        phone_m = re.search(r"(?:\+7|8)\s*[\d\-()\s]{9,}", org_req)
        if phone_m:
            contact_phone = re.sub(r"\s+", "", phone_m.group(0))

    date_ru = now.strftime("%d.%m.%Y")
    time_ru = now.strftime("%H:%M:%S")
    date_file = now.strftime("%Y%m%d")
    file_guid = str(uuid.uuid4())

    # A=carrier FNS id (unknown for draft), E=Ozon GUID, O=shipper draft id.
    # Kontur rewrites ИдФайл on import when needed.
    shipper_edo = f"2BM-{inn}-{kpp or '000000000'}-DRAFT" if inn else "2BM-DRAFT-SHIPPER"
    id_file = (
        f"ON_TRNACLGROT_"
        f"_"  # carrier FNSId unknown in FeedPilot
        f"{OZON_CONSIGNEE_EDO_GUID}_"
        f"{shipper_edo}_"
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
        НомерТрН=supply_num or "Без номера",
        ДатаТрН=date_ru,
        НомЗак=supply_num or "Без номера",
        ДатаЗак=date_ru,
    )

    # --- СвГО ---
    sv_go = _el(sod, "СвГО", ГОЭксп="0")
    rek_go = _el(sv_go, "РекИдентГО")
    id_go = _el(rek_go, "ИдСв")
    go_attrs = {"НаимОрг": org_full or "Грузоотправитель"}
    if inn:
        go_attrs["ИННЮЛ"] = inn
    if kpp:
        go_attrs["КПП"] = kpp
    _el(id_go, "СвЮЛУч", **go_attrs)
    if shipper_addr.get("raw") or shipper_addr.get("Индекс"):
        adr_go = _el(rek_go, "Адрес")
        _add_adr_rf(adr_go, "АдрРФ", shipper_addr)
    _add_contact(rek_go, contact_phone)

    # --- СвГП (Ozon) ---
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
    adr_dost = _el(sv_gp, "АдресДостГр")
    if not dest_addr.get("raw"):
        dest_addr = {
            **dest_addr,
            "raw": str(item.get("warehouse_name") or item.get("transit_warehouse_name") or "Склад Ozon"),
        }
    _add_adr_rf(adr_dost, "АдресРФ", dest_addr)

    # --- СвГруз ---
    sv_gruz = _el(sod, "СвГруз")
    op = _el(
        sv_gruz,
        "ОпГруз",
        НаимГруз=cargo["cargo_name"],
        СостГруз="Без повреждений",
        СпУпак=cargo["places_label"],
        ВидТар="00",
        КолМестГр=str(cargo["total_places"]),
        УчГосСист="0",
    )
    _el(op, "Марк", "Отсутствует")
    _el(op, "ПлМасГруз", МасБрутЗнач=str(cargo["kg"]))

    # --- УказГО ---
    ukaz = _el(sod, "УказГО", УкНормПрвз="Отсутствуют", ЗапрПерегруз="0")
    sv_pa = _el(
        ukaz,
        "СвПА",
        СпосПерУкПА="Электронное уведомление перевозчика о переадресовке",
        ЛицоПА="Грузоотправитель",
    )
    kont_pa = _el(sv_pa, "КонтПА")
    _el(kont_pa, "Тлф", contact_phone or "не указан")

    # --- СвПер ---
    sv_per = _el(sod, "СвПер")
    id_per = _el(sv_per, "ИдСв")
    per_attrs = {"НаимОрг": carrier_name}
    if carrier_inn:
        per_attrs["ИННЮЛ"] = carrier_inn
    if carrier_kpp:
        per_attrs["КПП"] = carrier_kpp
    _el(id_per, "СвЮЛУч", **per_attrs)
    _add_contact(sv_per, contact_phone)

    # --- СвВодит ---
    vod_attrs: dict[str, str] = {}
    if vu.get("ИННФЛ"):
        vod_attrs["ИННФЛ"] = vu["ИННФЛ"]
    else:
        if vu.get("НомВУ"):
            vod_attrs["НомВУ"] = vu["НомВУ"]
        if vu.get("СерВУ"):
            vod_attrs["СерВУ"] = vu["СерВУ"]
        if vu.get("ДатаВыдВУ"):
            vod_attrs["ДатаВыдВУ"] = vu["ДатаВыдВУ"]
        # Schema: VU trio OR ИННФЛ required — draft placeholders when unknown.
        if not (vod_attrs.get("НомВУ") and vod_attrs.get("СерВУ") and vod_attrs.get("ДатаВыдВУ")):
            vod_attrs.setdefault("СерВУ", "0000")
            vod_attrs.setdefault("НомВУ", "000000")
            vod_attrs.setdefault("ДатаВыдВУ", "01.01.2000")
    sv_vod = _el(sod, "СвВодит", **vod_attrs)
    _el(sv_vod, "Тлф", contact_phone or "не указан")
    fio_attrs = {"Фамилия": fam, "Имя": imya or "не указано"}
    if otch:
        fio_attrs["Отчество"] = otch
    _el(sv_vod, "ФИО", **fio_attrs)

    # --- СвТС ---
    sv_ts = _el(sod, "СвТС")
    ts = _el(
        sv_ts,
        "ТС",
        РегНомер=v_number or "А000АА00",
        ТипВлад="1",  # 1 = собственность (draft default)
    )
    _el(
        ts,
        "ПарТС",
        Тип="грузовой автомобиль",
        Марка=v_model or "не указана",
        Грузопод="20",
        Вместим="20",
    )

    # --- СвПогруз ---
    sv_pogr = _el(
        sod,
        "СвПогруз",
        ЗаявПогр=f"{date_ru}T00:00:00+03:00",
        НалКоорТочВрЗаяв="1",
        ФДатВрПриб=f"{date_ru}T00:00:00+03:00",
        НалКоорТочВрФПогр="1",
        ФДатВрУбыт=f"{date_ru}T00:00:00+03:00",
        НалКоорТочВрФУбыт="1",
        МасБрутОтгр=str(cargo["kg"]),
        МетОпрМасс="03",
        КолМестПрием=str(cargo["total_places"]),
    )
    f_adr = _el(sv_pogr, "ФАдресПогр")
    if not load_addr.get("raw"):
        load_addr = {**load_addr, "raw": "Адрес погрузки уточнить"}
    _add_adr_rf(f_adr, "АдресРФ", load_addr)

    lich = _el(sv_pogr, "СвЛицПогрГр", СовпГОП="1")
    ident = _el(lich, "ИдентРекГО")
    if inn:
        _el(ident, "ИННЮЛ", inn)
    vlad = _el(sv_pogr, "ВладИнфр", СовпГОВ="1")
    ident2 = _el(vlad, "ИдентРекГО")
    if inn:
        _el(ident2, "ИННЮЛ", inn)

    # ИнфПол must be last in СодИнфГО sequence (table 5.3).
    # Ozon matches supply by Orders; Kontur EDI convention uses ORDERS.
    if supply_num:
        inf = _el(sod, "ИнфПол")
        _el(inf, "ТекстИнф", Идентиф="Orders", Значение=supply_num)
        _el(inf, "ТекстИнф", Идентиф="ORDERS", Значение=supply_num)

    # Подписант is required under Документ (table 5.2).
    signer = _el(doc, "Подписант", СтатПодп="1", Должн="Уполномоченное лицо")
    signer_fio = {"Фамилия": s_fam, "Имя": s_imya or "не указано"}
    if s_otch:
        signer_fio["Отчество"] = s_otch
    _el(signer, "ФИО", **signer_fio)

    rough = ET.tostring(root, encoding="utf-8")
    try:
        return minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")
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
    driver_documents = str((driver_row or {}).get("documents") or "")

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
        "driver_documents": driver_documents,
        "vehicle_line": vehicle_line,
    }
