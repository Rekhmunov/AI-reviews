"""WB FBS supply detail modal: picking list + sticker print (portal-like).

Marketplace API has no ready-made «лист подбора» PDF / separator stickers.
We compose a printable A4 PDF from official stickers + local catalog names
(same pattern as other supply PDFs in the app).

Print speed: short in-process caches reuse modal detail, sticker PNG map,
and Content color/brand so picking-list + stickers do not re-hit WB for the
same supply within a short TTL. No WB write calls; stickers always come from
the official stickers endpoint (or its fresh cache).
"""
from __future__ import annotations

import base64
import copy
import hashlib
import html
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from . import wb_fbs as wb
from .repository import ReviewRepository

_log = logging.getLogger(__name__)

WB_CONTENT_API = "https://content-api.wildberries.ru"

# In-process caches (per worker). Detail/stickers are short-lived so print after
# opening the modal skips Marketplace re-reads; colors last longer.
_DETAIL_TTL_SEC = 120.0
_STICKERS_TTL_SEC = 120.0
_CARD_META_TTL_SEC = 1800.0
_cache_lock = threading.Lock()
_detail_cache: dict[tuple[int, int, str], tuple[float, dict[str, Any]]] = {}
_stickers_cache: dict[tuple[str, tuple[int, ...]], tuple[float, dict[int, dict[str, Any]]]] = {}
_card_meta_cache: dict[tuple[str, int], tuple[float, dict[str, str]]] = {}


def _api_key_fp(api_key: str) -> str:
    return hashlib.sha256((api_key or "").encode("utf-8")).hexdigest()[:16]


def invalidate_supply_detail_cache(
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
) -> None:
    sid = str(supply_id or "").strip()
    if not sid:
        return
    with _cache_lock:
        _detail_cache.pop((int(user_id), int(source_id), sid), None)


def _cache_put_detail(
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
    detail: dict[str, Any],
) -> None:
    sid = str(supply_id or "").strip()
    if not sid or not detail:
        return
    with _cache_lock:
        _detail_cache[(int(user_id), int(source_id), sid)] = (
            time.monotonic(),
            copy.deepcopy(detail),
        )


def _cache_get_detail(
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
) -> dict[str, Any] | None:
    sid = str(supply_id or "").strip()
    key = (int(user_id), int(source_id), sid)
    with _cache_lock:
        item = _detail_cache.get(key)
        if not item:
            return None
        ts, payload = item
        if (time.monotonic() - ts) > _DETAIL_TTL_SEC:
            _detail_cache.pop(key, None)
            return None
        return copy.deepcopy(payload)


def _cache_get_stickers(
    api_key: str,
    order_ids: list[int],
) -> dict[int, dict[str, Any]] | None:
    key = (_api_key_fp(api_key), tuple(int(x) for x in order_ids))
    with _cache_lock:
        item = _stickers_cache.get(key)
        if not item:
            return None
        ts, payload = item
        if (time.monotonic() - ts) > _STICKERS_TTL_SEC:
            _stickers_cache.pop(key, None)
            return None
        return copy.deepcopy(payload)


def _cache_put_stickers(
    api_key: str,
    order_ids: list[int],
    stickers: dict[int, dict[str, Any]],
) -> None:
    key = (_api_key_fp(api_key), tuple(int(x) for x in order_ids))
    with _cache_lock:
        _stickers_cache[key] = (time.monotonic(), copy.deepcopy(stickers))


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _fmt_date(iso: object) -> str:
    if not iso:
        return "—"
    try:
        text = str(iso).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return "—"


def _ago_label(iso: object) -> str:
    if not iso:
        return ""
    try:
        text = str(iso).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        sec = max(0, int((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()))
    except Exception:
        return ""
    if sec < 60:
        return f"{sec} сек назад"
    minutes = sec // 60
    if minutes < 60:
        return f"{minutes} мин назад"
    hours = minutes // 60
    rem = minutes % 60
    if hours < 48:
        return f"{hours} ч {rem} мин назад" if rem else f"{hours} ч назад"
    days = hours // 24
    return f"{days} дн назад"


def _content_request(api_key: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    url = f"{WB_CONTENT_API}{path}"
    payload = json.dumps(body).encode("utf-8")
    req = Request(
        url,
        method="POST",
        data=payload,
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "FeedPilot-WBFBS/1.0",
        },
    )
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if not raw:
                return {}
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
    except HTTPError as exc:
        err = ""
        try:
            err = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise RuntimeError(f"WB Content HTTP {exc.code}: {err or exc.reason}") from exc


def _color_from_card(card: dict[str, Any]) -> str:
    colors = card.get("colors")
    if isinstance(colors, list):
        for item in colors:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if name:
                    return name
            else:
                name = str(item or "").strip()
                if name:
                    return name
    chars = card.get("characteristics")
    if isinstance(chars, list):
        for ch in chars:
            if not isinstance(ch, dict):
                continue
            key = str(ch.get("name") or ch.get("charcName") or "").strip().lower()
            if key in {"цвет", "цвет товара", "colour", "color"}:
                val = ch.get("value")
                if isinstance(val, list):
                    parts = [str(x).strip() for x in val if str(x or "").strip()]
                    if parts:
                        return ", ".join(parts)
                text = str(val or "").strip()
                if text:
                    return text
    return ""


def _brand_from_card(card: dict[str, Any]) -> str:
    return str(card.get("brand") or card.get("brandName") or "").strip()


def _cards_from_content_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    cards = data.get("cards") if isinstance(data.get("cards"), list) else []
    if not cards and isinstance(data.get("data"), dict):
        nested = data["data"].get("cards")
        cards = nested if isinstance(nested, list) else []
    return [c for c in cards if isinstance(c, dict)]


def fetch_card_meta_by_nm(
    api_key: str,
    nm_ids: list[int],
    *,
    max_cards: int = 40,
) -> dict[int, dict[str, str]]:
    """Color/brand from Content API cards (official). Keys = nmID.

    Uses a process-local TTL cache so picking list + stickers share one Content
    pass per nmID. Missing/empty color is still cached briefly to avoid hammering.
    """
    out: dict[int, dict[str, str]] = {}
    uniq: list[int] = []
    seen: set[int] = set()
    for nm in nm_ids:
        try:
            n = int(nm)
        except (TypeError, ValueError):
            continue
        if n <= 0 or n in seen:
            continue
        seen.add(n)
        uniq.append(n)
        if len(uniq) >= max_cards:
            break

    fp = _api_key_fp(api_key)
    missing: list[int] = []
    now = time.monotonic()
    with _cache_lock:
        for nm in uniq:
            item = _card_meta_cache.get((fp, nm))
            if item and (now - item[0]) <= _CARD_META_TTL_SEC:
                out[nm] = dict(item[1])
            else:
                missing.append(nm)

    for nm in missing:
        card: dict[str, Any] = {}
        meta = {"color": "", "brand": ""}
        try:
            data = _content_request(
                api_key,
                "/content/v2/get/cards/list",
                {
                    "settings": {
                        "cursor": {"limit": 1},
                        "filter": {"withPhoto": -1, "nmID": int(nm)},
                    }
                },
            )
            cards = _cards_from_content_response(data)
            card = cards[0] if cards else {}
        except Exception as exc:
            _log.debug("content card nm=%s: %s", nm, exc)
            card = {}
        if card:
            meta = {
                "color": _color_from_card(card),
                "brand": _brand_from_card(card),
            }
        out[nm] = meta
        with _cache_lock:
            _card_meta_cache[(fp, nm)] = (time.monotonic(), dict(meta))
        time.sleep(0.21)
    return out


def _load_local_orders(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    order_ids: list[int],
) -> list[dict[str, Any]]:
    if not order_ids:
        return []
    wb.ensure_wb_fbs_tables(repo)
    placeholders = ", ".join("?" for _ in order_ids)
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                f"""
                SELECT * FROM wb_fbs_orders
                WHERE user_id = ? AND source_id = ? AND order_id IN ({placeholders})
                """
            ),
            tuple([user_id, source_id, *order_ids]),
        ).fetchall()
    by_id = {int(r["order_id"]): repo._row_to_dict(r) for r in rows}
    catalog = repo.get_product_catalog_map(user_id=user_id)
    photo_map = repo.get_product_photo_map(user_id=user_id)
    items: list[dict[str, Any]] = []
    for oid in order_ids:
        d = by_id.get(int(oid))
        if not d:
            d = {"order_id": int(oid), "article": "", "nm_id": None, "raw_json": "{}"}
        article = str(d.get("article") or "").strip()
        nm_id = str(d.get("nm_id") or "").strip()
        cat = catalog.get(article) or {}
        # Product title: our product_catalog only (not WB content title).
        product_name = str(cat.get("product_name") or "").strip() or article or "—"
        d["product_name"] = product_name
        d["product_photo"] = photo_map.get(article) or photo_map.get(nm_id) or ""
        raw_order: dict[str, Any] = {}
        try:
            parsed = json.loads(d.get("raw_json") or "{}")
            if isinstance(parsed, dict):
                raw_order = parsed
        except Exception:
            raw_order = {}
        if raw_order:
            price, ccy = wb.resolve_order_price(raw_order)
        else:
            price = d.get("final_price") or d.get("price") or 0
            ccy = d.get("currency_code") or 643
        d["price_display"] = wb.format_price_rub(price, ccy)
        d["cargo_label"] = wb.cargo_type_label(d.get("cargo_type"))
        try:
            skus_raw = json.loads(d.get("skus_json") or "[]")
        except Exception:
            skus_raw = []
        barcodes = [str(x).strip() for x in (skus_raw if isinstance(skus_raw, list) else []) if str(x or "").strip()]
        d["barcodes"] = barcodes
        d["skus"] = barcodes
        # «Можно в ПВЗ» — from order options when present.
        opts = raw_order.get("options") if isinstance(raw_order.get("options"), dict) else {}
        d["pickup_allowed"] = bool(
            opts.get("isPickupPointShipmentAllowed")
            or raw_order.get("isPickupPointShipmentAllowed")
        )
        d["created_ago"] = _ago_label(d.get("created_at_wb"))
        items.append(d)
    return items


def _int_or_zero(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _order_sticker_sort_key(order: dict[str, Any]) -> tuple[int, int, int]:
    """WB portal sorts rows inside an article by sticker partB, then partA."""
    return (
        _int_or_zero(order.get("sticker_part_b")),
        _int_or_zero(order.get("sticker_part_a")),
        _int_or_zero(order.get("order_id")),
    )


def _sort_groups_like_wb(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Match seller-portal picking list order.

    Groups: by product name, then seller article (portal lists 80×160 → 80×190 → …).
    Orders: by sticker partB ascending (not by order id).
    """
    for g in groups:
        orders = list(g.get("orders") or [])
        orders.sort(key=_order_sticker_sort_key)
        g["orders"] = orders
        g["qty"] = len(orders)
    groups.sort(
        key=lambda g: (
            str(g.get("product_name") or "").casefold(),
            str(g.get("article") or "").casefold(),
            str(g.get("nm_id") or ""),
        )
    )
    return groups


def _group_orders_by_article(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group by seller article. Final order is applied by ``_sort_groups_like_wb``."""
    groups: dict[str, dict[str, Any]] = {}
    order_keys: list[str] = []
    for o in orders:
        article = str(o.get("article") or "").strip() or f"nm-{o.get('nm_id') or 'unknown'}"
        if article not in groups:
            order_keys.append(article)
            groups[article] = {
                "article": article,
                "product_name": str(o.get("product_name") or article),
                "product_photo": str(o.get("product_photo") or ""),
                "nm_id": o.get("nm_id"),
                "barcodes": list(o.get("barcodes") or []),
                "color": "",
                "brand": "",
                "orders": [],
            }
        g = groups[article]
        g["orders"].append(o)
        if not g.get("product_photo") and o.get("product_photo"):
            g["product_photo"] = o["product_photo"]
        for b in o.get("barcodes") or []:
            if b not in g["barcodes"]:
                g["barcodes"].append(b)
    for key in order_keys:
        groups[key]["qty"] = len(groups[key]["orders"])
    return [groups[k] for k in order_keys]


def _fetch_stickers_map(
    client: wb.WbFbsClient,
    order_ids: list[int],
    *,
    api_key: str = "",
) -> dict[int, dict[str, Any]]:
    """Official PNG stickers (partA/partB/file). Cached briefly per order-id set."""
    ids = [int(x) for x in order_ids if x is not None]
    if not ids:
        return {}
    if api_key:
        cached = _cache_get_stickers(api_key, ids)
        if cached is not None:
            return cached
    result: dict[int, dict[str, Any]] = {}
    for i in range(0, len(ids), 100):
        chunk = ids[i : i + 100]
        if not chunk:
            continue
        stickers = client.get_order_stickers(chunk, sticker_type="png", width=58, height=40)
        for s in stickers:
            if not isinstance(s, dict):
                continue
            try:
                oid = int(s.get("orderId"))
            except (TypeError, ValueError):
                continue
            result[oid] = s
        time.sleep(0.21)
    if api_key and result:
        _cache_put_stickers(api_key, ids, result)
    return result


def _local_order_ids_for_supply(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
) -> list[int]:
    """Fallback when WB order-ids is empty/unavailable — use synced DB links."""
    wb.ensure_wb_fbs_tables(repo)
    sid = str(supply_id or "").strip()
    ids: list[int] = []
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                """
                SELECT order_id FROM wb_fbs_orders
                WHERE user_id = ? AND source_id = ? AND supply_id = ?
                ORDER BY order_id ASC
                """
            ),
            (user_id, source_id, sid),
        ).fetchall()
        for row in rows:
            try:
                ids.append(int(row["order_id"]))
            except (TypeError, ValueError):
                continue
        if ids:
            return ids
        # Also try cached array on supply row.
        row = conn.execute(
            repo._sql(
                """
                SELECT order_ids_json FROM wb_fbs_supplies
                WHERE user_id = ? AND source_id = ? AND supply_id = ?
                """
            ),
            (user_id, source_id, sid),
        ).fetchone()
    if not row:
        return []
    try:
        raw = json.loads(row["order_ids_json"] or "[]")
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    for item in raw:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _warehouse_display(label: object) -> str:
    text = str(label or "").strip()
    if not text or text == "—":
        return "—"
    if text.lower().startswith("склад"):
        return text
    return f"Склад {text}"


def _safe_b64(value: object) -> str:
    """Keep only base64 alphabet so sticker HTML cannot inject markup."""
    text = str(value or "").strip()
    if not text:
        return ""
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
    return "".join(ch for ch in text if ch in allowed)


def get_supply_detail(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    api_key: str,
    supply_id: str,
) -> dict[str, Any]:
    """Assemble portal-like supply detail payload for the modal."""
    sid = str(supply_id or "").strip()
    if not sid:
        raise ValueError("Не указан ID поставки")
    client = wb.WbFbsClient(api_key)
    supply: dict[str, Any] = {}
    try:
        supply = client.get_supply(sid)
    except Exception as exc:
        _log.warning("detail get_supply %s: %s", sid, exc)
        supply = {}
    time.sleep(0.21)
    order_ids: list[int] = []
    try:
        order_ids = client.get_supply_order_ids(sid)
    except Exception as exc:
        _log.warning("detail order-ids %s: %s", sid, exc)
        order_ids = []
    time.sleep(0.21)
    boxes: list[dict[str, Any]] = []
    try:
        boxes = client.get_supply_boxes(sid)
    except Exception as exc:
        _log.debug("detail boxes %s: %s", sid, exc)
    time.sleep(0.21)

    local = None
    wb.ensure_wb_fbs_tables(repo)
    with repo._connect() as conn:
        row = conn.execute(
            repo._sql(
                """
                SELECT * FROM wb_fbs_supplies
                WHERE user_id = ? AND source_id = ? AND supply_id = ?
                """
            ),
            (user_id, source_id, sid),
        ).fetchone()
        if row:
            local = repo._row_to_dict(row)

    if not order_ids:
        order_ids = _local_order_ids_for_supply(
            repo, user_id=user_id, source_id=source_id, supply_id=sid
        )

    if supply:
        try:
            wb.upsert_supply(
                repo,
                user_id=user_id,
                source_id=source_id,
                supply=supply,
                order_ids=order_ids or None,
                boxes=boxes or None,
            )
        except Exception as exc:
            _log.debug("detail upsert supply: %s", exc)

    orders = _load_local_orders(
        repo, user_id=user_id, source_id=source_id, order_ids=order_ids
    )
    # Warehouse label from order offices[] (seller WH names), else destination office.
    warehouse_label = ""
    for o in orders:
        try:
            offices = json.loads(o.get("offices_json") or "[]")
        except Exception:
            offices = []
        names = [str(x).strip() for x in offices if str(x or "").strip()]
        if names:
            warehouse_label = ", ".join(names)
            break
    if not warehouse_label:
        dest = (supply or {}).get("destinationOfficeId") if supply else None
        if dest is None and local:
            dest = local.get("destination_office_id")
        warehouse_label = str(dest) if dest else "—"

    name = str((supply or {}).get("name") or (local or {}).get("name") or "").strip()
    if not name:
        created = (supply or {}).get("createdAt") or (local or {}).get("created_at_wb")
        name = f"Поставка от {_fmt_date(created)}" if created else f"Поставка {sid}"

    cargo = (supply or {}).get("cargoType")
    if cargo in (None, 0) and local:
        cargo = local.get("cargo_type")
    pickup_allowed = bool((supply or {}).get("isPickupPointShipmentAllowed"))
    created_at = (supply or {}).get("createdAt") or (local or {}).get("created_at_wb")

    # Color/brand are fetched only for print (picking list / separators).
    for o in orders:
        o["color"] = ""
        o["brand"] = ""

    result = {
        "supply_id": sid,
        "source_id": source_id,
        "name": name,
        "warehouse_label": _warehouse_display(warehouse_label),
        "cargo_type": cargo or 0,
        "cargo_label": wb.cargo_type_label(cargo),
        "order_count": len(orders),
        "boxes_count": len(boxes),
        "created_at_wb": created_at,
        "created_date": _fmt_date(created_at),
        "pickup_allowed": pickup_allowed,
        "done": bool((supply or {}).get("done") if supply else (local or {}).get("done")),
        "orders": [
            {
                "order_id": o.get("order_id"),
                "article": o.get("article") or "",
                "nm_id": o.get("nm_id"),
                "product_name": o.get("product_name") or "—",
                "product_photo": o.get("product_photo") or "",
                "price_display": o.get("price_display") or "—",
                "created_at_wb": o.get("created_at_wb"),
                "created_date": _fmt_date(o.get("created_at_wb")),
                "created_ago": o.get("created_ago") or "",
                "pickup_allowed": bool(o.get("pickup_allowed") or pickup_allowed),
                "barcodes": o.get("barcodes") or [],
                "color": o.get("color") or "",
                "brand": o.get("brand") or "",
                "cargo_label": o.get("cargo_label") or "",
            }
            for o in orders
        ],
    }
    _cache_put_detail(
        user_id=user_id, source_id=source_id, supply_id=sid, detail=result
    )
    return result


def _detail_from_local(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    api_key: str,
    supply_id: str,
    refresh_order_ids: bool = True,
) -> dict[str, Any]:
    """Assemble print detail from local DB; optionally one live order-ids check.

    Skips get_supply + boxes (not needed for picking list / sticker HTML).
    """
    sid = str(supply_id or "").strip()
    if not sid:
        raise ValueError("Не указан ID поставки")

    order_ids: list[int] = []
    if refresh_order_ids:
        client = wb.WbFbsClient(api_key)
        try:
            order_ids = client.get_supply_order_ids(sid)
        except Exception as exc:
            _log.warning("print order-ids %s: %s", sid, exc)
            order_ids = []
        time.sleep(0.21)
    if not order_ids:
        order_ids = _local_order_ids_for_supply(
            repo, user_id=user_id, source_id=source_id, supply_id=sid
        )

    local = None
    boxes_count = 0
    wb.ensure_wb_fbs_tables(repo)
    with repo._connect() as conn:
        row = conn.execute(
            repo._sql(
                """
                SELECT * FROM wb_fbs_supplies
                WHERE user_id = ? AND source_id = ? AND supply_id = ?
                """
            ),
            (user_id, source_id, sid),
        ).fetchone()
        if row:
            local = repo._row_to_dict(row)
    if local:
        try:
            boxes_raw = json.loads(local.get("boxes_json") or "[]")
            if isinstance(boxes_raw, list):
                boxes_count = len(boxes_raw)
        except Exception:
            boxes_count = int(local.get("boxes_count") or 0) if local.get("boxes_count") else 0

    orders = _load_local_orders(
        repo, user_id=user_id, source_id=source_id, order_ids=order_ids
    )
    warehouse_label = ""
    for o in orders:
        try:
            offices = json.loads(o.get("offices_json") or "[]")
        except Exception:
            offices = []
        names = [str(x).strip() for x in offices if str(x or "").strip()]
        if names:
            warehouse_label = ", ".join(names)
            break
    if not warehouse_label and local:
        dest = local.get("destination_office_id")
        warehouse_label = str(dest) if dest else "—"
    if not warehouse_label:
        warehouse_label = "—"

    name = str((local or {}).get("name") or "").strip()
    created_at = (local or {}).get("created_at_wb")
    if not name:
        name = f"Поставка от {_fmt_date(created_at)}" if created_at else f"Поставка {sid}"
    cargo = (local or {}).get("cargo_type") if local else 0
    pickup_allowed = False

    result = {
        "supply_id": sid,
        "source_id": source_id,
        "name": name,
        "warehouse_label": _warehouse_display(warehouse_label),
        "cargo_type": cargo or 0,
        "cargo_label": wb.cargo_type_label(cargo),
        "order_count": len(orders),
        "boxes_count": boxes_count,
        "created_at_wb": created_at,
        "created_date": _fmt_date(created_at),
        "pickup_allowed": pickup_allowed,
        "done": bool((local or {}).get("done")),
        "orders": [
            {
                "order_id": o.get("order_id"),
                "article": o.get("article") or "",
                "nm_id": o.get("nm_id"),
                "product_name": o.get("product_name") or "—",
                "product_photo": o.get("product_photo") or "",
                "price_display": o.get("price_display") or "—",
                "created_at_wb": o.get("created_at_wb"),
                "created_date": _fmt_date(o.get("created_at_wb")),
                "created_ago": o.get("created_ago") or "",
                "pickup_allowed": bool(o.get("pickup_allowed")),
                "barcodes": o.get("barcodes") or [],
                "color": "",
                "brand": "",
                "cargo_label": o.get("cargo_label") or "",
            }
            for o in orders
        ],
    }
    _cache_put_detail(
        user_id=user_id, source_id=source_id, supply_id=sid, detail=result
    )
    return result


def get_supply_detail_for_print(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    api_key: str,
    supply_id: str,
) -> dict[str, Any]:
    """Detail for print: modal cache → local + one order-ids refresh → full detail."""
    cached = _cache_get_detail(
        user_id=user_id, source_id=source_id, supply_id=supply_id
    )
    if cached and cached.get("orders") is not None:
        return cached
    try:
        return _detail_from_local(
            repo,
            user_id=user_id,
            source_id=source_id,
            api_key=api_key,
            supply_id=supply_id,
            refresh_order_ids=True,
        )
    except Exception as exc:
        _log.warning("print local detail fallback %s: %s", supply_id, exc)
        return get_supply_detail(
            repo,
            user_id=user_id,
            source_id=source_id,
            api_key=api_key,
            supply_id=supply_id,
        )


def build_article_groups_for_print(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    api_key: str,
    supply_id: str,
    mode: Literal["picking_list", "stickers"] = "stickers",
) -> dict[str, Any]:
    """Build grouped print payload.

    ``picking_list`` needs partA/partB (+ color); ``stickers`` also needs PNG file.
    Both share detail/sticker/color caches so the second print is cheap.
    """
    detail = get_supply_detail_for_print(
        repo,
        user_id=user_id,
        source_id=source_id,
        api_key=api_key,
        supply_id=supply_id,
    )
    order_ids = [int(o["order_id"]) for o in detail["orders"] if o.get("order_id") is not None]
    client = wb.WbFbsClient(api_key)
    # Always fetch/cache full PNG stickers (official). Picking list only embeds codes.
    stickers = _fetch_stickers_map(client, order_ids, api_key=api_key)
    nm_ids: list[int] = []
    for o in detail["orders"]:
        try:
            nm_ids.append(int(o.get("nm_id")))
        except (TypeError, ValueError):
            continue
    card_meta = fetch_card_meta_by_nm(api_key, nm_ids)
    include_files = mode == "stickers"
    orders_full = []
    for o in detail["orders"]:
        oid = int(o["order_id"])
        st = stickers.get(oid) or {}
        try:
            nm = int(o.get("nm_id"))
        except (TypeError, ValueError):
            nm = 0
        meta = card_meta.get(nm) or {}
        row = {
            **o,
            "color": meta.get("color") or "",
            "brand": meta.get("brand") or "",
            "sticker_part_a": str(st.get("partA") or "").strip(),
            "sticker_part_b": str(st.get("partB") or "").strip(),
        }
        if include_files:
            row["sticker_file"] = str(st.get("file") or "").strip()
        else:
            row["sticker_file"] = ""
        orders_full.append(row)
    groups = _group_orders_by_article(orders_full)
    for g in groups:
        # Prefer catalog name already on rows; keep stable before WB-like sort.
        if not str(g.get("product_name") or "").strip():
            first = g["orders"][0] if g["orders"] else {}
            g["product_name"] = str(first.get("product_name") or g["article"])
        first = g["orders"][0] if g["orders"] else {}
        g["color"] = str(first.get("color") or "")
        g["brand"] = str(first.get("brand") or "")
    groups = _sort_groups_like_wb(groups)
    # Color/brand from first row after sticker sort (same article → same meta).
    for g in groups:
        first = g["orders"][0] if g["orders"] else {}
        g["color"] = str(first.get("color") or g.get("color") or "")
        g["brand"] = str(first.get("brand") or g.get("brand") or "")
        g["product_name"] = str(g.get("product_name") or first.get("product_name") or g["article"])
    return {
        "detail": detail,
        "groups": groups,
        "stickers": stickers if include_files else {},
    }


def render_picking_list_html(payload: dict[str, Any], *, for_pdf: bool = False) -> str:
    detail = payload["detail"]
    groups = payload["groups"]
    sid = _esc(detail.get("supply_id"))
    name = _esc(detail.get("name"))
    created = _esc(detail.get("created_date"))
    cargo = _esc(detail.get("cargo_label") or "")
    total = int(detail.get("order_count") or 0)
    rows_html: list[str] = []
    for g in groups:
        qty = int(g.get("qty") or 0)
        photo = str(g.get("product_photo") or "")
        photo_html = (
            f'<img class="photo" src="{_esc(photo)}" alt="" />'
            if photo
            else '<div class="photo ph"></div>'
        )
        color = str(g.get("color") or "").strip()
        brand = str(g.get("brand") or "").strip()
        meta_bits = [x for x in [brand, str(g.get("article") or "")] if x]
        meta = " · ".join(meta_bits)
        color_html = f'<div class="color">Цвет: {_esc(color)}</div>' if color else ""
        order_lines = []
        for idx, o in enumerate(g.get("orders") or [], start=1):
            part_a = _esc(o.get("sticker_part_a") or "—")
            part_b = _esc(o.get("sticker_part_b") or "")
            order_lines.append(
                f"""<tr class="order-row">
                  <td class="idx">{idx}</td>
                  <td class="oid">Заказ: {_esc(o.get("order_id"))}</td>
                  <td class="sticker">Стикер WB: {part_a}</td>
                  <td class="partb">{part_b}</td>
                </tr>"""
            )
        meta_lines = []
        if meta:
            meta_lines.append(f'<div class="sku-meta">{_esc(meta)}</div>')
        if color_html:
            meta_lines.append(color_html)
        meta_lines.append(f'<div class="sku-qty">{qty} шт</div>')
        rows_html.append(
            f"""
            <section class="sku-block">
              <div class="sku-head">
                {photo_html}
                <div class="sku-text">
                  <div class="sku-title">{_esc(g.get("product_name"))}</div>
                  {''.join(meta_lines)}
                </div>
                <div class="sku-stats">
                  <div class="stat"><span>Собрано</span><strong>0/{qty}</strong></div>
                  <div class="stat"><span>Упаковано</span><strong>0/{qty}</strong></div>
                </div>
              </div>
              <table class="orders">
                <colgroup>
                  <col class="c-idx" /><col class="c-oid" /><col class="c-sticker" /><col class="c-partb" />
                </colgroup>
                <tbody>{''.join(order_lines)}</tbody>
              </table>
            </section>
            """
        )
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>Лист подбора {sid} от {created}</title>
  <style>
    @page {{ size: A4 portrait; margin: 10mm; }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      color: #0f172a;
      font-size: 12px;
      line-height: 1.3;
    }}
    .toolbar {{ margin: 0 0 12px; }}
    .toolbar button {{
      min-height: 36px; padding: 8px 12px; font-size: 14px;
      border: 1px solid #cbd5e1; border-radius: 8px; background: #fff; cursor: pointer;
    }}
    .doc-kicker {{
      margin: 0 0 4px; color: #64748b; font-size: 12px; line-height: 1.3;
    }}
    h1 {{
      margin: 0 0 8px; font-size: 20px; font-weight: 700; line-height: 1.25;
    }}
    .meta {{
      display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 12px;
    }}
    .pill {{
      display: inline-flex; align-items: center;
      min-height: 24px; padding: 4px 8px;
      border: 1px solid #cbd5e1; border-radius: 6px;
      background: #f8fafc; font-size: 12px; font-weight: 600; line-height: 1.2;
    }}
    .summary {{
      display: grid; grid-template-columns: 1fr 1fr 1fr;
      margin: 0 0 12px; border: 1px solid #cbd5e1; background: #eef2f7;
    }}
    .summary div {{
      padding: 8px 12px; font-size: 12px; font-weight: 700; line-height: 1.3;
      border-right: 1px solid #cbd5e1;
    }}
    .summary div:last-child {{ border-right: 0; }}
    .sku-block {{
      margin: 0 0 8px; border: 1px solid #e2e8f0; border-radius: 8px;
      overflow: hidden; page-break-inside: avoid; background: #fff;
    }}
    .sku-block:last-of-type {{ margin-bottom: 0; }}
    .sku-head {{
      display: grid;
      grid-template-columns: 56px minmax(0, 1fr) 88px;
      column-gap: 12px;
      align-items: start;
      padding: 12px;
      border-bottom: 1px solid #f1f5f9;
    }}
    .photo {{
      width: 56px; height: 56px; object-fit: cover;
      border-radius: 6px; border: 1px solid #e2e8f0; display: block;
    }}
    .photo.ph {{ background: #f1f5f9; }}
    .sku-text {{ min-width: 0; }}
    .sku-title {{
      margin: 0 0 4px; font-size: 13px; font-weight: 700; line-height: 1.3;
    }}
    .sku-meta, .color {{
      margin: 0 0 4px; color: #64748b; font-size: 12px; line-height: 1.3;
    }}
    .sku-qty {{
      margin: 0; font-size: 12px; font-weight: 700; line-height: 1.3; color: #0f172a;
    }}
    .sku-stats {{
      display: flex; flex-direction: column; gap: 8px;
      align-items: flex-end; text-align: right;
    }}
    .sku-stats .stat span {{
      display: block; margin: 0 0 2px; color: #64748b;
      font-size: 11px; font-weight: 600; line-height: 1.2;
    }}
    .sku-stats .stat strong {{
      display: block; margin: 0; color: #0f172a;
      font-size: 14px; font-weight: 700; line-height: 1.2;
    }}
    table.orders {{
      width: 100%; border-collapse: collapse; table-layout: fixed;
    }}
    table.orders .c-idx {{ width: 40px; }}
    table.orders .c-oid {{ width: 32%; }}
    table.orders .c-sticker {{ width: 40%; }}
    table.orders .c-partb {{ width: auto; }}
    .order-row td {{
      padding: 8px 12px; border-top: 1px solid #f1f5f9;
      vertical-align: middle; font-size: 12px; line-height: 1.3;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .order-row:first-child td {{ border-top: 0; }}
    .order-row .idx {{
      color: #94a3b8; font-weight: 600; text-align: left;
    }}
    .order-row .oid, .order-row .sticker {{ color: #334155; }}
    .order-row .partb {{
      text-align: right;
      font-size: 16px; font-weight: 800; letter-spacing: 0.02em; color: #0f172a;
    }}
    .empty {{ margin: 0; padding: 16px 0; color: #64748b; }}
    .foot {{
      margin: 12px 0 0; color: #94a3b8; font-size: 11px; line-height: 1.3;
    }}
    @media print {{
      .no-print {{ display: none !important; }}
      body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
      .sku-block {{ break-inside: avoid; }}
    }}
  </style>
</head>
<body>
  {"" if for_pdf else '<div class="toolbar no-print"><button type="button" onclick="window.print()">Печать</button></div>'}
  <div class="doc-kicker">Лист подбора {sid} от {created}</div>
  <h1>{name}</h1>
  <div class="meta">
    {f'<span class="pill">{cargo}</span>' if cargo else ''}
    <span class="pill">{_esc(_warehouse_display(detail.get("warehouse_label")))}</span>
    <span class="pill">QR поставки {sid}</span>
  </div>
  <div class="summary">
    <div>Всего {total} заказов</div>
    <div>Собрано 0 / {total}</div>
    <div>Упаковано 0 / {total}</div>
  </div>
  {''.join(rows_html) if rows_html else '<p class="empty">Нет заказов в поставке.</p>'}
  <div class="foot">Сформировано в FeedPilot · A4 книжная</div>
</body>
</html>"""


def _photo_data_uri(url: str, *, timeout: float = 4.0) -> str:
    """Embed remote product photos for headless HTML→PDF (LibreOffice)."""
    text = str(url or "").strip()
    if not text or text.startswith("data:"):
        return text
    if not (text.startswith("https://") or text.startswith("http://")):
        return ""
    try:
        req = Request(
            text,
            headers={"User-Agent": "FeedPilot-WBFBS/1.0", "Accept": "image/*"},
            method="GET",
        )
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ctype = str(resp.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
        if not raw or len(raw) > 2_000_000:
            return ""
        if ctype not in {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}:
            ctype = "image/jpeg"
        return f"data:{ctype};base64,{base64.b64encode(raw).decode('ascii')}"
    except Exception as exc:
        _log.debug("picking photo fetch: %s", exc)
        return ""


def _embed_picking_list_photos(html_doc: str, groups: list[dict[str, Any]]) -> str:
    out = html_doc
    for g in groups:
        src = str(g.get("product_photo") or "").strip()
        if not src or src.startswith("data:"):
            continue
        data_uri = _photo_data_uri(src)
        if data_uri:
            out = out.replace(f'src="{_esc(src)}"', f'src="{data_uri}"', 1)
    return out


def html_to_pdf_bytes(html_doc: str, *, basename: str = "document") -> bytes:
    """Convert HTML to PDF via LibreOffice (same approach as packing-list.pdf)."""
    import os
    import pathlib
    import subprocess
    import tempfile

    tmp_dir = tempfile.mkdtemp()
    html_path = pathlib.Path(tmp_dir) / f"{basename}.html"
    pdf_path = pathlib.Path(tmp_dir) / f"{basename}.pdf"
    html_path.write_text(html_doc, encoding="utf-8")

    lo_env = dict(os.environ)
    lo_env["HOME"] = tmp_dir
    lo_env["XDG_CACHE_HOME"] = tmp_dir
    lo_env["XDG_CONFIG_HOME"] = tmp_dir
    lo_env["XDG_RUNTIME_DIR"] = tmp_dir
    lo_env["DCONF_PROFILE"] = "/dev/null"

    for binary in (
        "/usr/bin/soffice",
        "/usr/lib/libreoffice/program/soffice",
        "soffice",
        "libreoffice",
    ):
        try:
            result = subprocess.run(
                [
                    binary,
                    "--headless",
                    "--norestore",
                    f"-env:UserInstallation=file://{tmp_dir}/lo_profile",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    tmp_dir,
                    str(html_path),
                ],
                capture_output=True,
                timeout=90,
                env=lo_env,
            )
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Таймаут конвертации листа подбора в PDF") from exc
        if result.returncode == 0 and pdf_path.exists():
            return pdf_path.read_bytes()
    raise RuntimeError("Не удалось сформировать PDF листа подбора (LibreOffice)")


def render_picking_list_pdf(payload: dict[str, Any]) -> bytes:
    """A4 picking list as PDF for direct print/download (no HTML page)."""
    html_doc = render_picking_list_html(payload, for_pdf=True)
    html_doc = _embed_picking_list_photos(html_doc, list(payload.get("groups") or []))
    return html_to_pdf_bytes(html_doc, basename="wb_fbs_picking_list")


def render_stickers_print_html(payload: dict[str, Any]) -> str:
    """Thermal 58×40 mm: article separator, then WB stickers for that article."""
    groups = payload["groups"]
    pages: list[str] = []
    for g in groups:
        qty = int(g.get("qty") or 0)
        color = str(g.get("color") or "").strip()
        brand = str(g.get("brand") or "").strip()
        article = str(g.get("article") or "")
        name = str(g.get("product_name") or article)
        barcodes = g.get("barcodes") or []
        barcode = str(barcodes[0] if barcodes else "")
        nm = g.get("nm_id") or "—"
        color_line = f'<div class="line">Цвет: {_esc(color)}</div>' if color else ""
        brand_line = f'<div class="line">Бренд: {_esc(brand)}</div>' if brand else ""
        pages.append(
            f"""
            <section class="label separator">
              <div class="qty">{qty} шт.</div>
              <div class="title">{_esc(name)}</div>
              {brand_line}
              {color_line}
              <div class="line">Артикул WB: {_esc(nm)}</div>
              <div class="line">Баркод: {_esc(barcode or "—")}</div>
              <div class="line">Артикул: {_esc(article)}</div>
              <div class="hint">Артикул для подбора · Не нужно клеить</div>
            </section>
            """
        )
        for o in g.get("orders") or []:
            b64 = _safe_b64(o.get("sticker_file"))
            if not b64:
                pages.append(
                    f"""
                    <section class="label missing">
                      <div>Нет стикера</div>
                      <div>Заказ {_esc(o.get("order_id"))}</div>
                    </section>
                    """
                )
                continue
            pages.append(
                f"""
                <section class="label sticker">
                  <img src="data:image/png;base64,{b64}" alt="sticker {_esc(o.get("order_id"))}" />
                </section>
                """
            )
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>Стикеры поставки {_esc(payload.get("detail", {}).get("supply_id"))}</title>
  <style>
    @page {{ size: 58mm 40mm; margin: 0; }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; padding: 0; }}
    body {{ font-family: Arial, sans-serif; color: #0f172a; }}
    .label {{
      width: 58mm; height: 40mm; page-break-after: always;
      overflow: hidden; position: relative;
    }}
    .label:last-child {{ page-break-after: auto; }}
    .label.separator {{
      padding: 2.5mm 3mm; background: #fff;
      border: 0.3mm dashed #94a3b8;
      display: flex; flex-direction: column; gap: 0.6mm;
    }}
    .label.separator .qty {{ font-size: 16px; font-weight: 800; }}
    .label.separator .title {{
      font-size: 9px; font-weight: 700; line-height: 1.2;
      max-height: 12mm; overflow: hidden;
    }}
    .label.separator .line {{ font-size: 8px; line-height: 1.25; }}
    .label.separator .hint {{
      margin-top: auto; font-size: 7px; color: #64748b; font-weight: 600;
    }}
    .label.sticker {{ display: flex; align-items: center; justify-content: center; }}
    .label.sticker img {{ width: 58mm; height: 40mm; object-fit: contain; }}
    .label.missing {{
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      font-size: 10px; color: #b91c1c;
    }}
    .toolbar {{ padding: 8px 12px; }}
    @media print {{
      .toolbar {{ display: none !important; }}
    }}
  </style>
</head>
<body>
  <div class="toolbar no-print">
    <button onclick="window.print()">Печать</button>
    <span style="margin-left:8px;color:#64748b;font-size:13px">58×40 мм · разделитель артикула, затем стикеры WB</span>
  </div>
  {''.join(pages) if pages else '<p style="padding:12px">Нет стикеров для печати.</p>'}
  <script>window.addEventListener('load',function(){{ setTimeout(function(){{ window.print(); }}, 300); }});</script>
</body>
</html>"""


def render_single_sticker_html(*, order_id: int, file_b64: str) -> str:
    b64 = _safe_b64(file_b64)
    if not b64:
        raise ValueError("WB не вернул стикер")
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>Стикер {_esc(order_id)}</title>
  <style>
    @page {{ size: 58mm 40mm; margin: 0; }}
    html, body {{ margin: 0; padding: 0; }}
    .label {{ width: 58mm; height: 40mm; display: flex; align-items: center; justify-content: center; }}
    img {{ width: 58mm; height: 40mm; object-fit: contain; }}
    .toolbar {{ padding: 8px 12px; }}
    @media print {{ .toolbar {{ display: none !important; }} }}
  </style>
</head>
<body>
  <div class="toolbar"><button onclick="window.print()">Печать</button></div>
  <section class="label"><img src="data:image/png;base64,{b64}" alt="sticker {_esc(order_id)}" /></section>
  <script>window.addEventListener('load',function(){{ setTimeout(function(){{ window.print(); }}, 200); }});</script>
</body>
</html>"""
