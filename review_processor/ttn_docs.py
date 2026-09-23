"""Adapters: supply TTN catalog → Ozon Zakaz / eTrN XML builders.

Поставки → Логистика → ТН builds the same ЭЗЗ / эТрН drafts (and EDO flow) as
Поставки → Ozon, using parties / cargo / addresses from the TTN record.
"""
from __future__ import annotations

import re
from typing import Any

from .ozon_etrn import (
    _addr_from_production_fields,
    _addr_from_warehouse_fields,
    _empty_ru_address,
    _has_structured_address,
    _parse_inn_kpp,
    _parse_ru_address,
)
from .ozon_zakaz import _fns_participant_id


def _as_int(value: object, *, default: int = 0) -> int:
    raw = str(value or "").strip().replace(" ", "").replace(",", ".")
    if not raw:
        return default
    try:
        return int(float(raw))
    except ValueError:
        digits = re.sub(r"[^\d.]", "", raw)
        if not digits:
            return default
        try:
            return int(float(digits))
        except ValueError:
            return default


def _as_kg(value: object) -> float | None:
    raw = str(value or "").strip().replace(" ", "").replace(",", ".")
    if not raw:
        return None
    try:
        num = float(re.sub(r"[^\d.]", "", raw) or "")
    except ValueError:
        return None
    return num if num > 0 else None


def _party_kind(value: object, *, default: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"le", "legal", "legal_entity"}:
        return "le"
    if raw in {"contractor", "contragent"}:
        return "contractor"
    return default


def _le_from_contractor(contractor: dict[str, Any], *, address_line: str = "") -> dict[str, Any]:
    name = str(contractor.get("name") or "").strip()
    full = str(contractor.get("full_name") or "").strip() or name
    return {
        "id": contractor.get("id"),
        "short_name": name,
        "full_name": full,
        "requisites": str(contractor.get("requisites") or ""),
        "address": address_line or str(contractor.get("address") or "").strip(),
        "phone": str(contractor.get("phone") or ""),
        "signatories": str(contractor.get("signatories") or ""),
        "in_person": str(contractor.get("in_person") or ""),
        "addr_index": str(contractor.get("addr_index") or ""),
        "addr_region_code": str(contractor.get("addr_region_code") or ""),
        "addr_district": str(contractor.get("addr_district") or ""),
        "addr_city": str(contractor.get("addr_city") or ""),
        "addr_settlement": str(contractor.get("addr_settlement") or ""),
        "addr_street": str(contractor.get("addr_street") or ""),
        "addr_house": str(contractor.get("addr_house") or ""),
        "addr_corpus": str(contractor.get("addr_corpus") or ""),
        "addr_flat": str(contractor.get("addr_flat") or ""),
        "addr_fias": str(contractor.get("addr_fias") or ""),
    }


def _resolve_party(
    repository: Any,
    *,
    owner_id: int,
    party_type: str,
    party_id: int,
) -> dict[str, Any]:
    party_id = int(party_id or 0)
    if party_id <= 0:
        return {}
    if party_type == "le":
        for ent in repository.list_supply_legal_entities(user_id=owner_id) or []:
            if int(ent.get("id") or 0) == party_id:
                return dict(ent)
        return {}
    for row in repository.list_supply_contractors(user_id=owner_id) or []:
        if int(row.get("id") or 0) != party_id:
            continue
        line = ""
        if hasattr(repository, "contractor_address_line"):
            line = str(repository.contractor_address_line(row) or "").strip()
        return _le_from_contractor(row, address_line=line)
    return {}


def _match_address_fields(
    repository: Any,
    *,
    owner_id: int,
    address: str,
) -> tuple[str, dict[str, str], str]:
    raw = str(address or "").strip()
    if not raw:
        return "", _empty_ru_address(), ""

    try:
        productions = repository.list_supply_productions(user_id=owner_id) or []
    except Exception:
        productions = []
    for prod in productions:
        if hasattr(repository, "production_address_line"):
            line = str(repository.production_address_line(prod) or "").strip()
        else:
            line = str(prod.get("address") or "").strip()
        name = str(prod.get("name") or "").strip()
        label = f"{name} | {line}" if name and line else (line or name)
        if raw not in {line, name, label} and not any(
            c and (c in raw or raw in c) for c in (line, name, label) if c
        ):
            continue
        fields = _addr_from_production_fields(prod)
        if not fields.get("raw"):
            fields["raw"] = line or raw
        return line or raw, fields, str(prod.get("head_name") or "").strip()

    try:
        warehouses = repository.list_supply_warehouses(user_id=owner_id) or []
    except Exception:
        warehouses = []
    for wh in warehouses:
        if hasattr(repository, "warehouse_address_line"):
            line = str(repository.warehouse_address_line(wh) or "").strip()
        else:
            line = str(wh.get("address") or "").strip()
        name = str(wh.get("warehouse_name") or wh.get("name") or "").strip()
        label = f"{name} | {line}" if name and line else (line or name)
        if raw not in {line, name, label} and not any(
            c and (c in raw or raw in c) for c in (line, name, label) if c
        ):
            continue
        fields = _addr_from_warehouse_fields(wh)
        if not fields.get("raw"):
            fields["raw"] = line or raw
        return line or raw, fields, ""

    return raw, _parse_ru_address(raw), ""


def build_ttn_cargoes_json(record: dict[str, Any]) -> dict[str, Any]:
    places = max(1, _as_int(record.get("cargo_places"), default=1))
    packing = str(record.get("packing_type") or "").strip().lower()
    if any(token in packing for token in ("короб", "box")) and "палл" not in packing:
        cargo_type = "BOX"
    else:
        cargo_type = "PALLET"
    return {
        "version": 2,
        "groups": [{"type": cargo_type, "count": places}],
        "transport_cargoes": [],
    }


def _consignee_payload(party: dict[str, Any]) -> dict[str, Any]:
    name = str(party.get("full_name") or party.get("short_name") or "").strip() or "Грузополучатель"
    req = str(party.get("requisites") or "")
    inn, kpp = _parse_inn_kpp(req)
    if not inn:
        inn, kpp2 = _parse_inn_kpp(name)
        kpp = kpp or kpp2
    addr_fields = _addr_from_production_fields(party)
    if not _has_structured_address(addr_fields):
        addr_fields = _parse_ru_address(str(party.get("address") or ""))
    edo = _fns_participant_id(inn, kpp) if inn else ""
    return {
        "name": name,
        "inn": inn,
        "kpp": kpp,
        "edo_guid": edo,
        "address": str(party.get("address") or ""),
        "addr_fields": addr_fields,
    }


def collect_ttn_doc_context(
    *,
    repository: Any,
    owner_id: int,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Shared kwargs for Zakaz / eTrN / EDO from one TTN catalog row."""
    shipper_type = _party_kind(record.get("shipper_type"), default="le")
    consignee_type = _party_kind(record.get("consignee_type"), default="contractor")
    shipper_id = int(record.get("legal_entity_id") or 0)
    consignee_id = int(record.get("contractor_id") or 0)

    le = _resolve_party(
        repository, owner_id=owner_id, party_type=shipper_type, party_id=shipper_id
    )
    if not le:
        le = {
            "short_name": str(record.get("le_short") or ""),
            "full_name": str(record.get("le_full") or record.get("le_short") or ""),
            "requisites": str(record.get("le_req") or ""),
            "address": str(record.get("le_address") or ""),
            "phone": str(record.get("le_phone") or ""),
        }

    consignee_party = _resolve_party(
        repository, owner_id=owner_id, party_type=consignee_type, party_id=consignee_id
    )
    if not consignee_party:
        consignee_party = {
            "short_name": str(record.get("c_name") or ""),
            "full_name": str(record.get("c_name") or ""),
            "requisites": str(record.get("c_req") or ""),
            "address": str(record.get("unload_address") or ""),
        }

    driver_id = int(record.get("driver_id") or 0)
    driver_row: dict[str, Any] = {}
    if driver_id > 0:
        for row in repository.list_supply_drivers(user_id=owner_id) or []:
            if int(row.get("id") or 0) == driver_id:
                driver_row = dict(row)
                break

    if driver_row:
        driver_name = str(driver_row.get("full_name") or "").strip()
        driver_phone = str(driver_row.get("phone") or "").strip()
        if hasattr(repository, "driver_documents_line"):
            driver_documents = str(repository.driver_documents_line(driver_row) or "").strip()
        else:
            driver_documents = str(driver_row.get("documents") or record.get("d_docs") or "").strip()
        if hasattr(repository, "carrier_line"):
            carrier_text = str(repository.carrier_line(driver_row) or "").strip()
        else:
            carrier_text = str(driver_row.get("carrier_name") or "").strip()
        carrier_fields = dict(driver_row)
        driver_fields = dict(driver_row)
    else:
        driver_name = str(record.get("driver_manual_name") or "").strip()
        driver_phone = ""
        driver_documents = str(record.get("driver_manual_docs") or "").strip()
        carrier_text = str(record.get("carrier_snapshot") or "").strip()
        carrier_fields = {}
        driver_fields = {}

    if not carrier_text:
        carrier_text = str(record.get("carrier_snapshot") or record.get("d_carrier_name") or "").strip()

    load_address, load_addr_fields, loader_from_catalog = _match_address_fields(
        repository, owner_id=owner_id, address=str(record.get("load_address") or "")
    )
    delivery_address, delivery_addr_fields, _ = _match_address_fields(
        repository, owner_id=owner_id, address=str(record.get("unload_address") or "")
    )
    loader_name = str(record.get("loader_name") or "").strip() or loader_from_catalog

    vehicle_line = str(record.get("vehicle_line") or "").strip()
    vehicle_fields = {
        "line": vehicle_line,
        "type": str(record.get("vehicle_type") or "").strip(),
    }

    doc_number = str(record.get("doc_number") or record.get("id") or "").strip()
    supply_date = (
        str(record.get("loading_datetime") or "").strip()
        or str(record.get("ttn_date") or "").strip()
    )
    item = {
        "supply_order_id": int(record.get("id") or 0),
        "supply_order_number": doc_number or str(record.get("id") or ""),
        "supplier_name": str(le.get("short_name") or le.get("full_name") or ""),
        "warehouse_name": delivery_address
        or str(record.get("unload_address") or "Адрес выгрузки"),
        "supply_date": supply_date,
        "vehicle_json": None,
        "cargoes_json": None,
    }
    # Для ТН из ВБ ФБС номер накладной и ИнфПол-идентификаторы = WB-GI-…
    # (не внутренний номер ТН в каталоге Логистика).
    plat = str(record.get("fbs_platform") or "").strip().lower()
    fbs_sid = str(record.get("fbs_supply_id") or "").strip()
    if fbs_sid and plat in ("wb", "wildberries", "wb_fbs"):
        item["supply_order_number"] = fbs_sid
        item["infpol_orders_value"] = fbs_sid

    return {
        "item": item,
        "le": le,
        "driver_name": driver_name,
        "driver_phone": driver_phone,
        "driver_documents": driver_documents,
        "driver_fields": driver_fields or None,
        "vehicle_line": vehicle_line,
        "vehicle_json": None,
        "vehicle_fields": vehicle_fields,
        "cargoes_json": build_ttn_cargoes_json(record),
        "load_address": load_address or str(record.get("load_address") or ""),
        "load_addr_fields": load_addr_fields if _has_structured_address(load_addr_fields) else None,
        "delivery_address": delivery_address or str(record.get("unload_address") or ""),
        "delivery_addr_fields": (
            delivery_addr_fields if _has_structured_address(delivery_addr_fields) else None
        ),
        "carrier_text": carrier_text,
        "carrier_fields": carrier_fields or None,
        "loader_name": loader_name,
        "shipper_phone": str(le.get("phone") or "").strip(),
        "legal_entities": list(repository.list_supply_legal_entities(user_id=owner_id) or []),
        "consignee": _consignee_payload(consignee_party),
        "cargo_name": str(record.get("cargo_description") or "").strip() or "Груз",
        "cargo_kg": _as_kg(record.get("cargo_weight")),
        "doc_number": doc_number,
        "supplier_short": str(le.get("short_name") or ""),
    }


def build_ttn_zakaz_xml(
    *, repository: Any, owner_id: int, record: dict[str, Any]
) -> tuple[bytes, str]:
    from .ozon_zakaz import build_ozon_zakaz_xml

    ctx = collect_ttn_doc_context(repository=repository, owner_id=owner_id, record=record)
    xml_bytes = build_ozon_zakaz_xml(
        item=ctx["item"],
        le=ctx["le"],
        driver_name=ctx["driver_name"],
        driver_phone=ctx["driver_phone"],
        driver_documents=ctx["driver_documents"],
        driver_fields=ctx["driver_fields"],
        vehicle_line=ctx["vehicle_line"],
        vehicle_json=ctx["vehicle_json"],
        vehicle_fields=ctx["vehicle_fields"],
        cargoes_json=ctx["cargoes_json"],
        load_address=ctx["load_address"],
        load_addr_fields=ctx["load_addr_fields"],
        delivery_address=ctx["delivery_address"],
        delivery_addr_fields=ctx["delivery_addr_fields"],
        carrier_text=ctx["carrier_text"],
        carrier_fields=ctx["carrier_fields"],
        loader_name=ctx["loader_name"],
        shipper_phone=ctx["shipper_phone"],
        legal_entities=ctx["legal_entities"],
        cargo_name=ctx["cargo_name"],
        cargo_kg=ctx["cargo_kg"],
    )
    short = ctx["supplier_short"]
    num = ctx["doc_number"] or record.get("id")
    fname = f"Заявка №{num}{', ' + short if short else ''}.xml"
    return xml_bytes, fname


def build_ttn_etrn_xml(
    *, repository: Any, owner_id: int, record: dict[str, Any]
) -> tuple[bytes, str]:
    from .ozon_etrn import build_ozon_etrn_xml

    ctx = collect_ttn_doc_context(repository=repository, owner_id=owner_id, record=record)
    xml_bytes = build_ozon_etrn_xml(
        item=ctx["item"],
        le=ctx["le"],
        driver_name=ctx["driver_name"],
        driver_phone=ctx["driver_phone"],
        driver_documents=ctx["driver_documents"],
        driver_fields=ctx["driver_fields"],
        vehicle_line=ctx["vehicle_line"],
        vehicle_json=ctx["vehicle_json"],
        vehicle_fields=ctx["vehicle_fields"],
        cargoes_json=ctx["cargoes_json"],
        load_address=ctx["load_address"],
        load_addr_fields=ctx["load_addr_fields"],
        delivery_address=ctx["delivery_address"],
        delivery_addr_fields=ctx["delivery_addr_fields"],
        carrier_text=ctx["carrier_text"],
        carrier_fields=ctx["carrier_fields"],
        loader_name=ctx["loader_name"],
        consignee=ctx["consignee"],
        cargo_name=ctx["cargo_name"],
        cargo_kg=ctx["cargo_kg"],
    )
    short = ctx["supplier_short"]
    num = ctx["doc_number"] or record.get("id")
    fname = f"эТрН №{num}{', ' + short if short else ''}.xml"
    return xml_bytes, fname
