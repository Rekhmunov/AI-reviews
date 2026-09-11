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
    for key in ("boxes_count", "boxes_count"):
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
            bound = row.get("bound_to_this_supply")
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


def format_places(value: int | None) -> str:
    if value is None:
        return ""
    return str(int(value))
