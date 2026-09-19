"""TN autofill: cargo places + weight from WB/Ozon FBS supplies."""

from __future__ import annotations

from typing import Any


def _as_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num < 0:
        return None
    return num


def _as_qty(value: object, default: int = 1) -> int:
    try:
        qty = int(value)
    except (TypeError, ValueError):
        qty = default
    return qty if qty > 0 else 0


def product_weight_index(products: list[dict[str, Any]] | None) -> dict[str, float]:
    """Map article / nmId / ozon sku / offerId (and casefold) → weight_kg."""
    index: dict[str, float] = {}
    for prod in products or []:
        if not isinstance(prod, dict):
            continue
        weight = _as_float(prod.get("weight_kg"))
        if weight is None:
            continue
        for raw in (
            prod.get("supplier_article"),
            prod.get("wb_nmid"),
            prod.get("ozon_sku"),
            prod.get("yandex_offer_id"),
        ):
            key = str(raw or "").strip()
            if not key:
                continue
            index[key] = weight
            index[key.casefold()] = weight
    return index


def sum_weight_for_lines(
    weight_index: dict[str, float],
    lines: list[tuple[list[str], int]],
) -> dict[str, Any]:
    """Sum weight for qty lines. Each line: (lookup_keys, qty)."""
    total = 0.0
    matched_qty = 0
    missing: list[str] = []
    seen_missing: set[str] = set()
    for keys, qty in lines:
        if qty <= 0:
            continue
        weight = None
        label = ""
        for raw in keys:
            key = str(raw or "").strip()
            if not key:
                continue
            if not label:
                label = key
            weight = weight_index.get(key)
            if weight is None:
                weight = weight_index.get(key.casefold())
            if weight is not None:
                break
        if weight is None:
            if label and label not in seen_missing:
                seen_missing.add(label)
                missing.append(label)
            continue
        total += float(weight) * int(qty)
        matched_qty += int(qty)
    rounded = round(total, 3)
    if abs(rounded - round(rounded)) < 1e-9:
        weight_text = str(int(round(rounded)))
    else:
        weight_text = f"{rounded:.3f}".rstrip("0").rstrip(".")
    return {
        "weight_kg": rounded if matched_qty else None,
        "weight": weight_text if matched_qty else "",
        "matched_qty": matched_qty,
        "missing_articles": missing,
    }


def weight_lines_from_wb_orders(orders: list[dict[str, Any]] | None) -> list[tuple[list[str], int]]:
    qty_by_group: dict[tuple[str, str], int] = {}
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        if str(order.get("cancel_reason_label") or "").strip():
            continue
        if order.get("cancelled") or order.get("is_cancelled"):
            continue
        article = str(order.get("article") or "").strip()
        nm_id = str(order.get("nm_id") or "").strip()
        group = (article, nm_id)
        qty_by_group[group] = int(qty_by_group.get(group) or 0) + 1
    return [([article, nm_id], qty) for (article, nm_id), qty in qty_by_group.items()]


def weight_lines_from_ozon_orders(orders: list[dict[str, Any]] | None) -> list[tuple[list[str], int]]:
    qty_by_group: dict[tuple[str, str], int] = {}
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        if order.get("cancelled") or str(order.get("cancel_reason_label") or "").strip():
            continue
        offer_id = str(order.get("offer_id") or "").strip()
        sku = str(order.get("sku") or "").strip()
        qty = _as_qty(order.get("quantity"), default=1)
        if qty <= 0:
            continue
        group = (offer_id, sku)
        qty_by_group[group] = int(qty_by_group.get(group) or 0) + qty
    return [([offer_id, sku], qty) for (offer_id, sku), qty in qty_by_group.items()]


def places_from_wb_trbx(payload: dict[str, Any] | None) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in ("boxes_count", "box_count"):
        if key in payload:
            try:
                return max(0, int(payload.get(key) or 0))
            except (TypeError, ValueError):
                pass
    boxes = payload.get("boxes")
    if isinstance(boxes, list):
        return len(boxes)
    return None


def places_from_ozon_containers(
    payload: dict[str, Any] | None,
    *,
    supply_id: str = "",
) -> int | None:
    if not isinstance(payload, dict):
        return None
    items = payload.get("containers") or payload.get("items") or payload.get("list")
    if not isinstance(items, list):
        return None
    sid = str(supply_id or "").strip()
    count = 0
    for row in items:
        if not isinstance(row, dict):
            continue
        if sid:
            row_sid = str(
                row.get("supply_id")
                or row.get("bound_supply_id")
                or row.get("local_supply_id")
                or ""
            ).strip()
            # enrich_containers_for_supply_modal sets bound_to_open_supply;
            # older callers may still use bound_to_this_supply.
            bound = row.get("bound_to_this_supply")
            if bound is None and "bound_to_open_supply" in row:
                bound = row.get("bound_to_open_supply")
            if bound is False:
                continue
            if row_sid and row_sid != sid and bound is not True:
                if row.get("supply_ids") or row.get("bound_supply_ids"):
                    continue
                if row_sid:
                    continue
        status = str(row.get("status") or row.get("state") or "").strip().lower()
        if status in {"deleted", "inactive", "archived"}:
            continue
        if row.get("deleted") or row.get("is_deleted"):
            continue
        count += 1
    return count


def local_ozon_places_count(
    repo: Any,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
) -> int:
    """Distinct local GM binds for an Ozon FBS supply (no live Ozon call)."""
    sid = str(supply_id or "").strip()
    try:
        src = int(source_id or 0)
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        return 0
    if uid <= 0 or src <= 0 or not sid:
        return 0
    try:
        with repo._connect() as conn:
            crow = conn.execute(
                repo._sql(
                    """
                    SELECT COUNT(DISTINCT container_id) AS n
                    FROM ozon_fbs_postings
                    WHERE user_id = ? AND source_id = ? AND supply_id = ?
                      AND COALESCE(container_id, 0) > 0
                    """
                ),
                (uid, src, sid),
            ).fetchone()
        try:
            return max(
                0,
                int(
                    (
                        crow["n"]
                        if crow and hasattr(crow, "keys")
                        else (crow[0] if crow else 0)
                    )
                    or 0
                ),
            )
        except (TypeError, ValueError, KeyError, IndexError):
            return 0
    except Exception:
        return 0


TTN_PACKING_OPTIONS = ("Короба", "Паллеты", "Рулоны")


def normalize_packing_type(value: object) -> str:
    """Map free text to one of Короба/Паллеты/Рулоны (or empty)."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    for label in TTN_PACKING_OPTIONS:
        if label.casefold() == raw.casefold():
            return label
    return ""


def format_places(value: int | None) -> str:
    if value is None:
        return ""
    return str(int(value))


def resolve_shipper_load_place(
    repo: Any,
    *,
    user_id: int,
    legal_entity_id: int,
    exclude_warehouse_id: int = 0,
) -> tuple[int, str]:
    """Warehouse under shipper LE for TTN «Место погрузки» dropdown.

    Load options for legal entities are warehouses linked to the LE — not the
    LE card address. Prefer a warehouse other than the marketplace unload one.
    """
    le_id = int(legal_entity_id or 0)
    if le_id <= 0:
        return 0, ""
    try:
        rows = repo.list_supply_warehouses(user_id=user_id) or []
    except Exception:
        return 0, ""
    ex = int(exclude_warehouse_id or 0)
    candidates: list[dict[str, Any]] = []
    for w in rows:
        if not isinstance(w, dict):
            continue
        if int(w.get("legal_entity_id") or 0) != le_id:
            continue
        wid = int(w.get("id") or 0)
        if wid <= 0:
            continue
        candidates.append(w)
    if not candidates:
        return 0, ""
    preferred = [w for w in candidates if int(w.get("id") or 0) != ex]
    pool = preferred or candidates
    pool.sort(key=lambda w: str(w.get("warehouse_name") or "").casefold())
    pick = pool[0]
    wid = int(pick.get("id") or 0)
    addr = str(pick.get("address") or "").strip()
    if not addr:
        try:
            addr = str(repo.warehouse_address_line(pick) or "").strip()
        except Exception:
            addr = ""
    return wid, addr


def apply_fbs_customer_shipper_default(record: dict[str, Any]) -> None:
    """Section 1а defaults to the shipper legal entity on a new FBS TTN form.

    A saved customer (party or free-text snapshot) is left as-is. Logistics
    TTNs never pass through this helper.
    """
    if not isinstance(record, dict):
        return
    if str(record.get("customer_services") or "").strip():
        return
    party_type = str(record.get("customer_party_type") or "").strip()
    try:
        party_id = int(record.get("customer_party_id") or 0)
    except (TypeError, ValueError):
        party_id = 0
    if party_type and party_id > 0:
        return
    if str(record.get("shipper_type") or "le").strip() != "le":
        return
    try:
        shipper_id = int(record.get("legal_entity_id") or 0)
    except (TypeError, ValueError):
        shipper_id = 0
    if shipper_id <= 0:
        return
    record["customer_party_type"] = "le"
    record["customer_party_id"] = shipper_id
