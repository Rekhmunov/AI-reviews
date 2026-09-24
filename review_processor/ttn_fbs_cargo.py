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


def local_ozon_container_ids(
    repo: Any,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
) -> list[str]:
    """Distinct GM ``container_id`` values bound to this Ozon FBS supply.

    Only postings of the given supply with ``container_id > 0`` (локальная
    привязка из модалки «Грузоместа»). Sorted ascending for stable XML.
    """
    sid = str(supply_id or "").strip()
    try:
        src = int(source_id or 0)
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        return []
    if uid <= 0 or src <= 0 or not sid:
        return []
    try:
        with repo._connect() as conn:
            rows = conn.execute(
                repo._sql(
                    """
                    SELECT DISTINCT container_id AS cid
                    FROM ozon_fbs_postings
                    WHERE user_id = ? AND source_id = ? AND supply_id = ?
                      AND COALESCE(container_id, 0) > 0
                    ORDER BY container_id ASC
                    """
                ),
                (uid, src, sid),
            ).fetchall()
    except Exception:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for row in rows or []:
        try:
            if row is not None and hasattr(row, "keys"):
                raw = row["cid"]
            else:
                raw = row[0] if row else None
            cid = int(raw or 0)
        except (TypeError, ValueError, KeyError, IndexError):
            continue
        if cid <= 0:
            continue
        key = str(cid)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _fmt_weight_text(kg: float | None) -> str:
    if kg is None or kg <= 0:
        return ""
    rounded = round(float(kg), 3)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(int(round(rounded)))
    return f"{rounded:.3f}".rstrip("0").rstrip(".")


def local_ozon_cargo_place_rows(
    repo: Any,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
    weight_index: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Per-GM rows for Ozon FBS TTN: №, container_id, mass of bound postings.

    Local only (no Ozon API). ``container_number`` is 1-based order among
    distinct ids (портальный № может отсутствовать локально).
    """
    ids = local_ozon_container_ids(
        repo, user_id=user_id, source_id=source_id, supply_id=supply_id
    )
    if not ids:
        return []
    sid = str(supply_id or "").strip()
    try:
        src = int(source_id or 0)
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        return []
    try:
        with repo._connect() as conn:
            rows = conn.execute(
                repo._sql(
                    """
                    SELECT container_id, offer_id, sku, quantity, status, tab,
                           posting_number
                    FROM ozon_fbs_postings
                    WHERE user_id = ? AND source_id = ? AND supply_id = ?
                      AND COALESCE(container_id, 0) > 0
                    ORDER BY container_id ASC, posting_number ASC
                    """
                ),
                (uid, src, sid),
            ).fetchall()
    except Exception:
        rows = []

    try:
        from . import ozon_fbs as oz
    except Exception:
        oz = None  # type: ignore

    by_cid: dict[str, list[tuple[list[str], int]]] = {cid: [] for cid in ids}
    order_counts: dict[str, int] = {cid: 0 for cid in ids}
    for row in rows or []:
        try:
            d = (
                repo._row_to_dict(row)
                if hasattr(repo, "_row_to_dict")
                else (dict(row) if hasattr(row, "keys") else {})
            )
        except Exception:
            d = {}
        if not d and row is not None and hasattr(row, "keys"):
            d = {k: row[k] for k in row.keys()}
        try:
            cid_i = int(d.get("container_id") or 0)
        except (TypeError, ValueError):
            continue
        if cid_i <= 0:
            continue
        cid = str(cid_i)
        if cid not in by_cid:
            by_cid[cid] = []
            order_counts[cid] = 0
        if oz is not None and oz.posting_row_is_cancelled(d):
            continue
        qty = _as_qty(d.get("quantity"), default=1)
        if qty <= 0:
            continue
        offer_id = str(d.get("offer_id") or "").strip()
        sku = str(d.get("sku") or "").strip()
        by_cid[cid].append(([offer_id, sku], qty))
        order_counts[cid] = int(order_counts.get(cid) or 0) + 1

    index = weight_index if isinstance(weight_index, dict) else {}
    out: list[dict[str, Any]] = []
    for num, cid in enumerate(ids, start=1):
        lines = by_cid.get(cid) or []
        winfo = (
            sum_weight_for_lines(index, lines)
            if index and lines
            else {"weight_kg": None, "weight": "", "matched_qty": 0}
        )
        weight_kg = winfo.get("weight_kg")
        weight_text = str(winfo.get("weight") or "").strip() or _fmt_weight_text(
            float(weight_kg) if weight_kg is not None else None
        )
        out.append(
            {
                "container_id": cid,
                "container_number": num,
                "order_count": int(order_counts.get(cid) or 0),
                "weight_kg": weight_kg,
                "weight": weight_text,
            }
        )
    return out


def parse_cargo_places_detail(raw: object) -> list[dict[str, Any]]:
    """Normalize stored / API cargo_places_detail list."""
    parsed: object = raw
    if isinstance(raw, str) and raw.strip():
        try:
            import json

            parsed = json.loads(raw)
        except Exception:
            return []
    if not isinstance(parsed, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(parsed):
        if not isinstance(item, dict):
            continue
        cid = str(item.get("container_id") or "").strip()
        if not cid or not cid.isdigit() or cid == "0" or cid in seen:
            continue
        seen.add(cid)
        try:
            number = int(item.get("container_number") or 0)
        except (TypeError, ValueError):
            number = 0
        if number <= 0:
            number = len(out) + 1
        weight_text = str(item.get("weight") or "").strip()
        weight_kg = _as_float(item.get("weight_kg"))
        if not weight_text and weight_kg is not None:
            weight_text = _fmt_weight_text(weight_kg)
        try:
            order_count = int(item.get("order_count") or 0)
        except (TypeError, ValueError):
            order_count = 0
        out.append(
            {
                "container_id": cid,
                "container_number": number,
                "order_count": max(0, order_count),
                "weight_kg": weight_kg,
                "weight": weight_text,
            }
        )
    return out


def serialize_cargo_places_detail(rows: list[dict[str, Any]] | None) -> str:
    import json

    cleaned = parse_cargo_places_detail(rows or [])
    if not cleaned:
        return ""
    payload = [
        {
            "container_id": r["container_id"],
            "container_number": int(r.get("container_number") or 0),
            "order_count": int(r.get("order_count") or 0),
            "weight": str(r.get("weight") or ""),
            "weight_kg": r.get("weight_kg"),
        }
        for r in cleaned
    ]
    return json.dumps(payload, ensure_ascii=False)


def totals_from_cargo_places_detail(
    rows: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    cleaned = parse_cargo_places_detail(rows or [])
    total_kg = 0.0
    matched = 0
    for r in cleaned:
        w = _as_float(r.get("weight_kg"))
        if w is None:
            w = _as_float(str(r.get("weight") or "").replace(",", "."))
        if w is None:
            continue
        total_kg += float(w)
        matched += 1
    return {
        "places": len(cleaned),
        "places_text": format_places(len(cleaned)) if cleaned else "",
        "weight_kg": round(total_kg, 3) if matched else None,
        "weight": _fmt_weight_text(total_kg) if matched else "",
    }


def format_cargo_place_row_label(row: dict[str, Any] | None) -> str:
    """One line: «№1 · 1019563511789384»."""
    if not isinstance(row, dict):
        return ""
    cid = str(row.get("container_id") or "").strip()
    try:
        num = int(row.get("container_number") or 0)
    except (TypeError, ValueError):
        num = 0
    left = f"№{num}" if num > 0 else "ГМ"
    if cid:
        return f"{left} · {cid}"
    return left


def local_ozon_places_count(
    repo: Any,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
) -> int:
    """Distinct local GM binds for an Ozon FBS supply (no live Ozon call)."""
    return len(
        local_ozon_container_ids(
            repo, user_id=user_id, source_id=source_id, supply_id=supply_id
        )
    )


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
    legal_address: str = "",
) -> tuple[int, str]:
    """Warehouse / legal address for TTN «Место погрузки» default.

    Priority:
    - exactly one usable warehouse → that warehouse;
    - no warehouses → legal address (LE card);
    - several warehouses → empty (operator chooses).

    ``exclude_warehouse_id`` drops the marketplace unload warehouse from the
    auto-pick pool when the shipper LE also owns that SC warehouse.
    """
    le_id = int(legal_entity_id or 0)
    legal = str(legal_address or "").strip()
    if le_id <= 0:
        return 0, legal
    try:
        rows = repo.list_supply_warehouses(user_id=user_id) or []
    except Exception:
        return 0, legal
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
        return 0, legal
    preferred = [w for w in candidates if int(w.get("id") or 0) != ex]
    # One own warehouse (+ optional excluded SC) → auto-pick the own one.
    # Several own warehouses → leave empty (do not fall back to legal).
    if len(preferred) > 1:
        return 0, ""
    if len(preferred) == 0:
        # Only the excluded SC warehouse is linked — treat as no load warehouse.
        return 0, legal if len(candidates) == 1 else ""
    pick = preferred[0]
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
