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
import re
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
_stickers_cache: dict[tuple[str, str, tuple[int, ...]], tuple[float, dict[int, dict[str, Any]]]] = {}
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
    *,
    sticker_type: str = "png",
) -> dict[int, dict[str, Any]] | None:
    key = (_api_key_fp(api_key), str(sticker_type or "png"), tuple(int(x) for x in order_ids))
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
    *,
    sticker_type: str = "png",
) -> None:
    key = (_api_key_fp(api_key), str(sticker_type or "png"), tuple(int(x) for x in order_ids))
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


def _title_from_card(card: dict[str, Any]) -> str:
    """Official WB card title as in ЛК picking list (includes size wording).

    Only ``title`` / ``imtName`` — never ``subjectName`` (category like
    «Наматрасники»), which collapses all groups and breaks portal order.
    """
    for key in ("title", "imtName"):
        text = str(card.get(key) or "").strip()
        if text:
            return text
    return ""


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
    network: bool = True,
) -> dict[int, dict[str, str]]:
    """Color/brand/title from Content API cards (official). Keys = nmID.

    Uses a process-local TTL cache so picking list + stickers share one Content
    pass per nmID. When ``network=False``, only cache hits are returned (fast path
    for picking list — sync does not preload Content colors).
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
            # Older cache entries without title are stale for ЛК-like group sort.
            if (
                item
                and (now - item[0]) <= _CARD_META_TTL_SEC
                and "title" in item[1]
            ):
                out[nm] = dict(item[1])
            else:
                missing.append(nm)

    if not network:
        for nm in missing:
            out[nm] = {"color": "", "brand": "", "title": ""}
        return out

    for nm in missing:
        card: dict[str, Any] = {}
        meta = {"color": "", "brand": "", "title": ""}
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
                "title": _title_from_card(card),
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
    # Feedback → Settings → Products (product_photos), same source as WB FBS lists.
    name_map = repo.get_product_name_by_article(user_id=user_id)
    stock_catalog = repo.get_product_catalog_map(user_id=user_id)
    stock_ci = {str(k).casefold(): v for k, v in stock_catalog.items() if k}
    photo_map = repo.get_product_photo_map(user_id=user_id)
    items: list[dict[str, Any]] = []
    for oid in order_ids:
        d = by_id.get(int(oid))
        if not d:
            d = {"order_id": int(oid), "article": "", "nm_id": None, "raw_json": "{}"}
        article = str(d.get("article") or "").strip()
        nm_id = str(d.get("nm_id") or "").strip()
        product_name = (
            name_map.get(article)
            or name_map.get(article.casefold())
            or name_map.get(nm_id)
            or ""
        ).strip()
        if not product_name:
            cat = stock_catalog.get(article) or stock_ci.get(article.casefold()) or {}
            product_name = str(cat.get("product_name") or "").strip()
        # Не подменяем артикулом — имя отдельной строкой выше артикула в листе подбора.
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


def _kiz_codes_from_value(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        return _kiz_codes_from_value(value.get("value"))
    if isinstance(value, list):
        return [wb._kiz_code_clean(x) for x in value if wb._kiz_code_clean(x)]
    text = wb._kiz_code_clean(value)
    return [text] if text else []


def _kiz_decision_raw(item: dict[str, Any]) -> str:
    """Read WB validation flag from metaDetails (field names vary slightly)."""
    for key in ("decision", "status", "validationStatus", "state"):
        val = item.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return ""


def _kiz_status_from_decision(decision: str, codes: list[str]) -> str:
    """UI status: empty | pending | ok | error.

    Live WB metaDetails.decision values observed for sgtin include:
    ``optional``, ``required``, ``filled``, ``invalid``, ``sgtinNotFound``,
    ``sgtinIntroduced`` (enum is non-exhaustive).
    """
    dec = str(decision or "").strip().lower()
    if not dec and not codes:
        return "empty"
    # Failed Честный знак / WB validation (ЛК «с ошибкой»).
    # Real API uses sgtinNotFound / invalid — not only plain "invalid".
    if (
        dec in {
            "invalid",
            "sgtinnotfound",
            "sgtin_not_found",
            "notfound",
            "error",
            "failed",
            "fail",
            "rejected",
            "reject",
            "ошибка",
        }
        or "invalid" in dec
        or "notfound" in dec
        or "not_found" in dec
        or ("error" in dec and "sgtin" in dec)
        or "fail" in dec
    ):
        return "error"
    # Passed / accepted / introduced into circulation.
    if dec in {
        "filled",
        "sgtinintroduced",
        "sgtin_introduced",
        "introduced",
        "ok",
        "valid",
        "success",
        "passed",
        "approved",
    } or "introduced" in dec:
        return "ok"
    # Slot exists but empty / still optional-required without a verdict.
    if dec in {"optional", "required"} and not codes:
        return "empty"
    if codes:
        # Codes attached; check not finished yet.
        return "pending"
    return "empty"


def _kiz_from_meta_row(row: dict[str, Any]) -> dict[str, Any]:
    """Parse POST /orders/meta row for sgtin slot + verification decision."""
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    details = row.get("metaDetails") if isinstance(row.get("metaDetails"), list) else []
    required = False
    codes: list[str] = []
    decision = ""
    for item in details:
        if not isinstance(item, dict):
            continue
        if str(item.get("key") or "").strip().lower() != "sgtin":
            continue
        required = True
        codes = _kiz_codes_from_value(item.get("value"))
        decision = _kiz_decision_raw(item)
        break
    if not required and "sgtin" in meta:
        required = True
        codes = _kiz_codes_from_value(meta.get("sgtin"))
        # Legacy ``meta`` has no decision — only codes presence.
    status = _kiz_status_from_decision(decision, codes) if required else "empty"
    return {
        "kiz_required": required,
        "kiz_bound": bool(codes),
        "kiz_codes": codes,
        "kiz_decision": decision,
        "kiz_status": status,
    }


def _kiz_required_from_raw(raw: dict[str, Any]) -> bool:
    """Fallback when live meta is unavailable: requiredMeta/optionalMeta on order."""
    for key in ("requiredMeta", "optionalMeta"):
        vals = raw.get(key)
        if not isinstance(vals, list):
            continue
        for item in vals:
            if str(item or "").strip().lower() == "sgtin":
                return True
    return False


def _fetch_kiz_map(
    client: wb.WbFbsClient,
    orders: list[dict[str, Any]],
    *,
    repo: ReviewRepository | None = None,
    user_id: int | None = None,
    source_id: int | None = None,
) -> dict[int, dict[str, Any]]:
    """Map order_id → kiz fields for supply detail UI (meta + local draft)."""
    out: dict[int, dict[str, Any]] = {}
    ids: list[int] = []
    for o in orders:
        try:
            oid = int(o["order_id"])
        except (TypeError, ValueError, KeyError):
            continue
        ids.append(oid)
        raw: dict[str, Any] = {}
        try:
            parsed = json.loads(o.get("raw_json") or "{}")
            if isinstance(parsed, dict):
                raw = parsed
        except Exception:
            raw = {}
        # Fallback until live meta answers (or if meta request fails).
        out[oid] = {
            "kiz_required": _kiz_required_from_raw(raw),
            "kiz_bound": False,
            "kiz_codes": [],
            "kiz_decision": "",
            "kiz_status": "empty",
        }
    if not ids:
        return out
    try:
        rows = client.get_orders_meta(ids)
    except Exception as exc:
        _log.debug("orders meta (kiz): %s", exc)
        rows = []
    for row in rows:
        try:
            oid = int(row.get("id") or row.get("orderId") or 0)
        except (TypeError, ValueError):
            continue
        if oid <= 0:
            continue
        # Live meta row is authoritative: no sgtin key ⇒ badge hidden.
        out[oid] = _kiz_from_meta_row(row)

    # Local Save drafts only fill gaps. Never override WB ok/error/pending-from-meta.
    if repo is not None and user_id is not None and source_id is not None:
        local_map = wb.load_order_kiz_map(
            repo, user_id=int(user_id), source_id=int(source_id), order_ids=ids
        )
        for oid, local in local_map.items():
            cur = out.get(oid)
            if not cur or not cur.get("kiz_required"):
                continue
            local_codes = [
                wb._kiz_code_clean(x)
                for x in (local.get("codes") or [])
                if wb._kiz_code_clean(x)
            ]
            has_draft = local.get("saved_at") is not None
            status = str(cur.get("kiz_status") or "empty")
            wb_codes = list(cur.get("kiz_codes") or [])
            wb_decision = str(cur.get("kiz_decision") or "").strip()
            # Live meta already has a verdict or in-progress codes → trust WB.
            if status in ("ok", "error") or (wb_codes and wb_decision):
                continue
            if local_codes and status == "empty":
                cur["kiz_codes"] = local_codes
                cur["kiz_bound"] = True
                cur["kiz_status"] = "pending"
            elif has_draft and not local_codes and not wb_codes:
                cur["kiz_codes"] = []
                cur["kiz_bound"] = False
                cur["kiz_status"] = "empty"
    return out


def _portal_title_sort_key(value: object) -> tuple:
    """ЛК sorts groups by card title string; keep digits numeric-aware.

    Example order from portal:
    «…160х200 см…» → «…180х200 на резинке с бортами…» → «…180х200 см…»
    («на» < «см» after the shared size prefix).
    """
    text = str(value or "")
    parts = re.split(r"(\d+)", text)
    key: list[tuple[int, object]] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part.casefold()))
    return tuple(key)


def _order_sticker_sort_key(order: dict[str, Any]) -> tuple[int, int, int]:
    """WB portal sorts rows inside an article by sticker partB, then partA."""
    pb = str(order.get("sticker_part_b") or "").strip()
    pa = str(order.get("sticker_part_a") or "").strip()
    return (
        _int_or_zero(pb) if pb else 10**9,
        _int_or_zero(pa) if pa else 10**9,
        _int_or_zero(order.get("order_id")),
    )


def _sort_groups_like_wb(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Match seller-portal (ЛК) picking list order.

    Groups: by official WB card title (alphabet / size wording), then article.
    Not by Settings name and not by seller-article alphabet alone.
    Orders inside a group: sticker partB ascending.
    """
    for g in groups:
        orders = list(g.get("orders") or [])
        orders.sort(key=_order_sticker_sort_key)
        g["orders"] = orders
        g["qty"] = len(orders)
    groups.sort(
        key=lambda g: (
            _portal_title_sort_key(
                g.get("wb_title") or g.get("product_name") or g.get("article") or ""
            ),
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
                "product_name": str(o.get("product_name") or "").strip(),
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
    sticker_type: str = "png",
    keep_files: bool = True,
) -> dict[int, dict[str, Any]]:
    """Official stickers (partA/partB[/file]). Cached briefly per order-id set + type.

    Picking list only needs partA/partB — use ``sticker_type='svg'`` and
    ``keep_files=False`` to avoid downloading/storing heavy PNG payloads.
    """
    ids = [int(x) for x in order_ids if x is not None]
    if not ids:
        return {}
    stype = str(sticker_type or "png").strip().lower() or "png"
    if api_key:
        cached = _cache_get_stickers(api_key, ids, sticker_type=stype)
        if cached is not None:
            return cached
    result: dict[int, dict[str, Any]] = {}
    for i in range(0, len(ids), 100):
        chunk = ids[i : i + 100]
        if not chunk:
            continue
        stickers = client.get_order_stickers(
            chunk, sticker_type=stype, width=58, height=40
        )
        for s in stickers:
            if not isinstance(s, dict):
                continue
            try:
                oid = int(s.get("orderId"))
            except (TypeError, ValueError):
                continue
            if keep_files:
                result[oid] = s
            else:
                result[oid] = {
                    "orderId": oid,
                    "partA": s.get("partA"),
                    "partB": s.get("partB"),
                    "barcode": s.get("barcode"),
                }
        time.sleep(0.21)
    if api_key and result:
        _cache_put_stickers(api_key, ids, result, sticker_type=stype)
    return result


def _local_order_ids_for_supply(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
) -> list[int]:
    """Fallback when WB order-ids is empty/unavailable — use synced DB links.

    Prefer ``order_ids_json`` (WB sequence from sync) over ``ORDER BY order_id`` —
    numeric id order is not the portal picking order.
    """
    wb.ensure_wb_fbs_tables(repo)
    sid = str(supply_id or "").strip()
    ids: list[int] = []
    with repo._connect() as conn:
        row = conn.execute(
            repo._sql(
                """
                SELECT order_ids_json FROM wb_fbs_supplies
                WHERE user_id = ? AND source_id = ? AND supply_id = ?
                """
            ),
            (user_id, source_id, sid),
        ).fetchone()
        if row:
            try:
                raw = json.loads(row["order_ids_json"] or "[]")
            except Exception:
                raw = []
            if isinstance(raw, list):
                for item in raw:
                    try:
                        ids.append(int(item))
                    except (TypeError, ValueError):
                        continue
                if ids:
                    return ids
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

    # КИЗ (sgtin): only for orders that accept Data Matrix in FBS metadata.
    kiz_map = _fetch_kiz_map(
        client,
        orders,
        repo=repo,
        user_id=user_id,
        source_id=source_id,
    )
    # Sticker partA/partB for modal (last 4 digits emphasized under order id).
    detail_order_ids = [
        _int_or_zero(o.get("order_id"))
        for o in orders
        if _int_or_zero(o.get("order_id"))
    ]
    stickers: dict[int, dict[str, Any]] = {}
    try:
        stickers = _fetch_stickers_map(
            client,
            detail_order_ids,
            api_key=api_key,
            sticker_type="svg",
            keep_files=False,
        )
    except Exception as exc:
        _log.warning("detail stickers %s: %s", sid, exc)
        stickers = {}
    order_rows: list[dict[str, Any]] = []
    for o in orders:
        oid = _int_or_zero(o.get("order_id"))
        kiz = kiz_map.get(oid) or {}
        status = str(kiz.get("kiz_status") or "empty")
        st = stickers.get(oid) or {}
        part_a = str(st.get("partA") or "").strip()
        part_b = str(st.get("partB") or "").strip()
        order_rows.append(
            {
                "order_id": o.get("order_id"),
                "article": o.get("article") or "",
                "nm_id": o.get("nm_id"),
                # Только наименование из «Настройки → Товары» (без подмены артикулом).
                "product_name": o.get("product_name") or "",
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
                "sticker_part_a": part_a,
                "sticker_part_b": part_b,
                "sticker_number": _sticker_number(part_a, part_b),
                "kiz_required": bool(kiz.get("kiz_required")),
                "kiz_bound": bool(kiz.get("kiz_bound")),
                "kiz_codes": list(kiz.get("kiz_codes") or []),
                "kiz_decision": str(kiz.get("kiz_decision") or ""),
                "kiz_status": status,
            }
        )

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
        "orders": order_rows,
    }
    _cache_put_detail(
        user_id=user_id, source_id=source_id, supply_id=sid, detail=result
    )
    return result


def _sticker_number(part_a: object, part_b: object) -> str:
    """Portal «номер стикера» = partA + partB (e.g. 5662692 + 5731)."""
    a = str(part_a or "").strip()
    b = str(part_b or "").strip()
    if a and b:
        return f"{a}{b}"
    return a or b


def build_kiz_marking_payload(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    api_key: str,
    supply_id: str,
) -> dict[str, Any]:
    """Rows for «Указать маркировку» modal: only orders that accept sgtin."""
    # Fresh meta so bound codes match ЛК.
    invalidate_supply_detail_cache(
        user_id=user_id, source_id=source_id, supply_id=supply_id
    )
    detail = get_supply_detail(
        repo,
        user_id=user_id,
        source_id=source_id,
        api_key=api_key,
        supply_id=supply_id,
    )
    required_orders = [
        o for o in (detail.get("orders") or []) if o.get("kiz_required")
    ]
    order_ids = [
        int(o["order_id"])
        for o in required_orders
        if o.get("order_id") is not None
    ]
    client = wb.WbFbsClient(api_key)
    stickers = _fetch_stickers_map(
        client,
        order_ids,
        api_key=api_key,
        sticker_type="svg",
        keep_files=False,
    )
    if order_ids:
        missing = sum(
            1
            for oid in order_ids
            if not str((stickers.get(oid) or {}).get("partB") or "").strip()
        )
        if missing > max(1, len(order_ids) // 2):
            stickers = _fetch_stickers_map(
                client,
                order_ids,
                api_key=api_key,
                sticker_type="png",
                keep_files=False,
            )
    nm_ids: list[int] = []
    for o in required_orders:
        try:
            nm_ids.append(int(o.get("nm_id")))
        except (TypeError, ValueError):
            continue
    card_meta = fetch_card_meta_by_nm(api_key, nm_ids, network=True, max_cards=200)

    local_kiz = wb.load_order_kiz_map(
        repo, user_id=user_id, source_id=source_id, order_ids=order_ids
    )

    rows: list[dict[str, Any]] = []
    for o in required_orders:
        try:
            oid = int(o["order_id"])
        except (TypeError, ValueError, KeyError):
            continue
        st = stickers.get(oid) or {}
        part_a = str(st.get("partA") or "").strip()
        part_b = str(st.get("partB") or "").strip()
        # Machine-readable value from sticker QR / 1D barcode (e.g. !uKEtQZVx).
        sticker_barcode = str(st.get("barcode") or "").strip()
        wb_codes = [
            wb._kiz_code_clean(x)
            for x in (o.get("kiz_codes") or [])
            if wb._kiz_code_clean(x)
        ]
        local = local_kiz.get(oid) or {}
        local_codes = [
            wb._kiz_code_clean(x)
            for x in (local.get("codes") or [])
            if wb._kiz_code_clean(x)
        ]
        # Prefer any local Save draft (incl. empty clear) when kiz_saved_at is set.
        has_local_draft = local.get("saved_at") is not None
        if has_local_draft:
            codes = local_codes or [""]
        elif wb_codes:
            codes = wb_codes
        else:
            codes = [""]
        try:
            nm = int(o.get("nm_id"))
        except (TypeError, ValueError):
            nm = 0
        brand = str((card_meta.get(nm) or {}).get("brand") or o.get("brand") or "").strip()
        kiz_status = str(o.get("kiz_status") or "empty")
        kiz_decision = str(o.get("kiz_decision") or "")
        # Local unsynced codes → «на проверке» in the marking modal too.
        if (
            kiz_status == "empty"
            and any(wb._kiz_code_clean(c) for c in codes)
            and (has_local_draft or o.get("kiz_bound"))
        ):
            kiz_status = "pending"
        rows.append(
            {
                "order_id": oid,
                "created_date": o.get("created_date") or "—",
                "product_name": o.get("product_name") or "",
                "product_photo": o.get("product_photo") or "",
                "article": o.get("article") or "",
                "brand": brand,
                "nm_id": o.get("nm_id"),
                "barcodes": list(o.get("barcodes") or []),
                "sticker_barcode": sticker_barcode,
                "sticker_part_a": part_a,
                "sticker_part_b": part_b,
                "sticker_number": _sticker_number(part_a, part_b),
                "kiz_codes": codes,
                "kiz_bound": bool(o.get("kiz_bound")),
                "kiz_local": bool(has_local_draft),
                "kiz_wb_synced": bool(local.get("wb_synced"))
                if has_local_draft
                else bool(o.get("kiz_bound")),
                "kiz_status": kiz_status,
                "kiz_decision": kiz_decision,
            }
        )
    return {
        "supply_id": detail.get("supply_id"),
        "source_id": source_id,
        "name": detail.get("name") or "",
        "order_count": len(rows),
        "rows": rows,
    }


def save_kiz_marking(
    *,
    api_key: str,
    items: list[dict[str, Any]],
    allowed_order_ids: set[int] | None = None,
    repo: ReviewRepository | None = None,
    user_id: int | None = None,
    source_id: int | None = None,
) -> dict[str, Any]:
    """Save КИЗ locally first, then push to WB; keep local on WB failure for retry.

    Empty ``kiz_codes`` clears only when ``clear`` is true. Unchanged empty
    rows are skipped.
    """
    client = wb.WbFbsClient(api_key)
    results: list[dict[str, Any]] = []
    ok_n = 0
    err_n = 0
    skipped_n = 0
    local_n = 0
    for raw in items:
        if not isinstance(raw, dict):
            continue
        try:
            oid = int(raw.get("order_id"))
        except (TypeError, ValueError):
            continue
        if allowed_order_ids is not None and oid not in allowed_order_ids:
            err_n += 1
            results.append(
                {
                    "order_id": oid,
                    "ok": False,
                    "local_ok": False,
                    "wb_ok": False,
                    "kiz_codes": [],
                    "error": "Заказ не входит в эту поставку",
                }
            )
            continue
        codes = [
            wb._kiz_code_clean(x)
            for x in (raw.get("kiz_codes") or [])
            if wb._kiz_code_clean(x)
        ]
        # Deduplicate preserving order.
        seen: set[str] = set()
        uniq: list[str] = []
        for c in codes:
            if c in seen:
                continue
            seen.add(c)
            uniq.append(c)
        clear = bool(raw.get("clear"))
        if not uniq and not clear:
            skipped_n += 1
            continue

        local_ok = False
        if repo is not None and user_id is not None and source_id is not None:
            try:
                # Always persist locally first (even if WB will fail).
                local_ok = wb.update_order_kiz_codes(
                    repo,
                    user_id=int(user_id),
                    source_id=int(source_id),
                    order_id=oid,
                    kiz_codes=uniq,
                    wb_synced=False,
                )
                if local_ok:
                    local_n += 1
                else:
                    err_n += 1
                    results.append(
                        {
                            "order_id": oid,
                            "ok": False,
                            "local_ok": False,
                            "wb_ok": False,
                            "kiz_codes": uniq,
                            "error": "Заказ не найден локально — синхронизируйте FBS и повторите",
                        }
                    )
                    continue
            except Exception as local_exc:
                _log.warning("local kiz save order %s failed: %s", oid, local_exc)
                err_n += 1
                results.append(
                    {
                        "order_id": oid,
                        "ok": False,
                        "local_ok": False,
                        "wb_ok": False,
                        "kiz_codes": uniq,
                        "error": f"Не удалось сохранить локально: {str(local_exc)[:200]}",
                    }
                )
                continue

        wb_ok = False
        wb_error = ""
        try:
            if uniq:
                client.set_order_sgtin(oid, uniq)
            else:
                client.delete_order_meta(oid, "sgtin")
            wb_ok = True
            time.sleep(0.07)
        except Exception as exc:
            wb_error = str(exc)[:300]
            time.sleep(0.07)

        if wb_ok and local_ok and repo is not None and user_id is not None and source_id is not None:
            try:
                wb.update_order_kiz_codes(
                    repo,
                    user_id=int(user_id),
                    source_id=int(source_id),
                    order_id=oid,
                    kiz_codes=uniq,
                    wb_synced=True,
                )
            except Exception as local_exc:
                _log.warning(
                    "local kiz wb_synced flag order %s failed: %s", oid, local_exc
                )

        if wb_ok:
            ok_n += 1
            results.append(
                {
                    "order_id": oid,
                    "ok": True,
                    "local_ok": local_ok,
                    "wb_ok": True,
                    "kiz_codes": uniq,
                    "error": "",
                }
            )
        else:
            err_n += 1
            results.append(
                {
                    "order_id": oid,
                    "ok": False,
                    "local_ok": local_ok,
                    "wb_ok": False,
                    "kiz_codes": uniq,
                    "error": wb_error or "Ошибка записи в WB",
                }
            )
    return {
        "ok": err_n == 0,
        "saved": ok_n,
        "failed": err_n,
        "skipped": skipped_n,
        "saved_local": local_n,
        "results": results,
    }


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
                "product_name": o.get("product_name") or "",
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
    refresh_order_ids: bool = True,
) -> dict[str, Any]:
    """Detail for print: modal cache → local (+ optional order-ids) → full detail."""
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
            refresh_order_ids=refresh_order_ids,
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


def _refresh_product_names(
    repo: ReviewRepository,
    *,
    user_id: int,
    orders: list[dict[str, Any]],
) -> None:
    """Resolve names from Feedback → Settings → Products at print time."""
    name_map = repo.get_product_name_by_article(user_id=user_id)
    stock_catalog = repo.get_product_catalog_map(user_id=user_id)
    stock_ci = {str(k).casefold(): v for k, v in stock_catalog.items() if k}
    for o in orders:
        article = str(o.get("article") or "").strip()
        nm_id = str(o.get("nm_id") or "").strip()
        name = (
            name_map.get(article)
            or name_map.get(article.casefold())
            or name_map.get(nm_id)
            or ""
        ).strip()
        if not name:
            cat = stock_catalog.get(article) or stock_ci.get(article.casefold()) or {}
            name = str(cat.get("product_name") or "").strip()
        o["product_name"] = name


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
    picking = mode == "picking_list"
    detail = get_supply_detail_for_print(
        repo,
        user_id=user_id,
        source_id=source_id,
        api_key=api_key,
        supply_id=supply_id,
        # Need WB supply orderIds sequence so article groups match portal order.
        refresh_order_ids=True,
    )
    # Detail cache may be from modal open — refresh product names for print.
    _refresh_product_names(repo, user_id=user_id, orders=detail.get("orders") or [])
    order_ids = [int(o["order_id"]) for o in detail["orders"] if o.get("order_id") is not None]
    client = wb.WbFbsClient(api_key)
    # Picking list needs only partA/partB (SVG is much lighter than PNG base64).
    # Stickers print still uses official PNG files.
    stickers = _fetch_stickers_map(
        client,
        order_ids,
        api_key=api_key,
        sticker_type="svg" if picking else "png",
        keep_files=not picking,
    )
    if picking:
        # If SVG response lacked codes, fall back once to PNG metadata (still no keep_files).
        missing_codes = sum(
            1
            for oid in order_ids
            if not str((stickers.get(oid) or {}).get("partB") or "").strip()
        )
        if order_ids and missing_codes > max(1, len(order_ids) // 2):
            stickers = _fetch_stickers_map(
                client,
                order_ids,
                api_key=api_key,
                sticker_type="png",
                keep_files=False,
            )
    nm_ids: list[int] = []
    for o in detail["orders"]:
        try:
            nm_ids.append(int(o.get("nm_id")))
        except (TypeError, ValueError):
            continue
    # Color/brand come from Content API (not FBS sync). Cache makes repeat prints cheap.
    card_meta = fetch_card_meta_by_nm(api_key, nm_ids, network=True, max_cards=200)
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
            # ЛК group order key — official card title (size text included).
            "wb_title": str(meta.get("title") or "").strip(),
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
        first = g["orders"][0] if g["orders"] else {}
        # Display name: Settings → Products. Sort key: wb_title from Content.
        g["product_name"] = str(
            g.get("product_name") or first.get("product_name") or ""
        ).strip()
        g["wb_title"] = str(first.get("wb_title") or "").strip()
        g["color"] = str(first.get("color") or "")
        g["brand"] = str(first.get("brand") or "")
    groups = _sort_groups_like_wb(groups)
    for g in groups:
        first = g["orders"][0] if g["orders"] else {}
        g["color"] = str(first.get("color") or g.get("color") or "")
        g["brand"] = str(first.get("brand") or g.get("brand") or "")
        g["wb_title"] = str(first.get("wb_title") or g.get("wb_title") or "").strip()
        g["product_name"] = str(
            g.get("product_name") or first.get("product_name") or ""
        ).strip()
    return {
        "detail": detail,
        "groups": groups,
        "stickers": stickers if include_files else {},
    }


def render_picking_list_html(payload: dict[str, Any], *, for_pdf: bool = False) -> str:
    """Browser-print picking list (HTML+CSS). Matches WB portal structure.

    Page 1: summary by product name — «Всего N заказов» + column «Собрано».
    From page 2: detailed list with content | Собрано | Упаковано.
    Totals row only once at the top of the detail table (not repeated on later pages).
    Product rows span full width (no per-article 0/qty counters).
    Prefer HTML print over LibreOffice PDF — LO breaks modern CSS.
    """
    detail = payload["detail"]
    groups = payload["groups"]
    sid = _esc(detail.get("supply_id"))
    created = _esc(detail.get("created_date"))
    total = int(detail.get("order_count") or 0)
    order_word = "заказ" if total % 10 == 1 and total % 100 != 11 else (
        "заказа" if 2 <= total % 10 <= 4 and not (12 <= total % 100 <= 14) else "заказов"
    )
    box = '<span class="box" aria-hidden="true"></span>'

    body_rows: list[str] = []
    printable_groups = [g for g in groups if list(g.get("orders") or [])]
    # Highlight partB codes that repeat across the supply (operator risk).
    part_b_counts: dict[str, int] = {}
    for g in printable_groups:
        for o in g.get("orders") or []:
            pb = str(o.get("sticker_part_b") or "").strip()
            if pb:
                part_b_counts[pb] = part_b_counts.get(pb, 0) + 1
    dup_part_b = {pb for pb, n in part_b_counts.items() if n > 1}

    # Page 1 summary: aggregate qty by product name (preserve first-seen order).
    summary_qty: dict[str, int] = {}
    summary_order: list[str] = []
    for g in printable_groups:
        orders = list(g.get("orders") or [])
        qty = int(g.get("qty") or len(orders) or 0)
        product_name = str(g.get("product_name") or "").strip() or "—"
        if product_name not in summary_qty:
            summary_order.append(product_name)
            summary_qty[product_name] = 0
        summary_qty[product_name] += qty

    summary_rows: list[str] = []
    for name in summary_order:
        qty = summary_qty[name]
        summary_rows.append(
            f"""<tr class="summary-row">
              <td class="main">{_esc(name)} — {qty} шт.</td>
              <td class="check">{box}</td>
            </tr>"""
        )

    if summary_rows:
        summary_html = f"""
        <section class="summary-page">
          <table class="picking summary">
            <colgroup>
              <col class="c-main" />
              <col class="c-check" />
            </colgroup>
            <tbody>
              <tr class="totals-row">
                <th class="main">Всего {total} {order_word}</th>
                <th class="check">Собрано</th>
              </tr>
              {''.join(summary_rows)}
            </tbody>
          </table>
        </section>
        """
    else:
        summary_html = ""

    for g_idx, g in enumerate(printable_groups):
        orders = list(g.get("orders") or [])
        qty = int(g.get("qty") or len(orders) or 0)
        color = str(g.get("color") or "").strip()
        brand = str(g.get("brand") or "").strip()
        article = str(g.get("article") or "").strip()
        product_name = str(g.get("product_name") or "").strip() or "—"
        barcodes = [
            str(b).strip() for b in (g.get("barcodes") or []) if str(b or "").strip()
        ]
        meta_bits = [f'<div class="sku-title">{_esc(product_name)}</div>']
        if brand:
            meta_bits.append(f'<div class="sku-meta">{_esc(brand)}</div>')
        if article:
            meta_bits.append(f'<div class="sku-article">{_esc(article)}</div>')
        if barcodes:
            meta_bits.append(
                '<div class="sku-barcodes">'
                + "".join(f'<div class="sku-barcode">{_esc(b)}</div>' for b in barcodes)
                + "</div>"
            )
        # Color directly under barcode(s) — operator cue while picking.
        if color:
            meta_bits.append(f'<div class="sku-color">Цвет: {_esc(color)}</div>')
        meta_bits.append(f'<div class="sku-qty">{qty} шт</div>')

        body_rows.append(
            f"""<tr class="product-row">
              <td class="main" colspan="3">
                <div class="sku-text">{''.join(meta_bits)}</div>
              </td>
            </tr>"""
        )
        is_last_group = g_idx >= len(printable_groups) - 1
        for idx, o in enumerate(orders, start=1):
            is_last_order = idx == len(orders)
            row_cls = "order-row"
            if is_last_order and not is_last_group:
                row_cls += " article-end"
            part_a = _esc(o.get("sticker_part_a") or "—")
            part_b_raw = str(o.get("sticker_part_b") or "").strip()
            part_b = _esc(part_b_raw)
            part_b_cls = "partb partb-dup" if part_b_raw in dup_part_b else "partb"
            body_rows.append(
                f"""<tr class="{row_cls}">
                  <td class="main">
                    <div class="order-line">
                      <span class="idx">{idx}.</span>
                      <span class="oid">Заказ: {_esc(o.get("order_id"))}</span>
                      <span class="sticker-group">
                        <span class="sticker">Стикер WB: {part_a}</span>
                        <span class="{part_b_cls}">{part_b}</span>
                      </span>
                    </div>
                  </td>
                  <td class="check">{box}</td>
                  <td class="check">{box}</td>
                </tr>"""
            )

    if body_rows:
        # Totals as first tbody row (not <thead>) so print does not repeat it
        # on every subsequent page.
        totals_row = f"""
            <tr class="totals-row">
              <th class="main">Всего {total} {order_word}</th>
              <th class="check">Собрано<br /><span class="sub">0 / {total}</span></th>
              <th class="check">Упаковано<br /><span class="sub">0 / {total}</span></th>
            </tr>
        """
        detail_html = f"""
        <section class="detail-page">
          <table class="picking">
            <colgroup>
              <col class="c-main" />
              <col class="c-check" />
              <col class="c-check" />
            </colgroup>
            <tbody>{totals_row}{''.join(body_rows)}</tbody>
          </table>
        </section>
        """
    else:
        detail_html = '<p class="empty">Нет заказов в поставке.</p>'

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>Лист подбора {sid} от {created}</title>
  <!-- feedpilot-picking-list:20260807a -->
  <meta name="feedpilot-build" content="picking-20260807a" />
  <style>
    @page {{ size: A4 portrait; margin: 10mm; }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      color: #0f172a;
      font-size: 12px;
      line-height: 1.3;
      background: #fff;
    }}
    .toolbar {{ margin: 0 0 12px; }}
    .toolbar button {{
      min-height: 36px; padding: 8px 12px; font-size: 14px;
      border: 1px solid #cbd5e1; border-radius: 8px; background: #fff; cursor: pointer;
    }}
    .summary-page {{
      page-break-after: always;
      break-after: page;
    }}
    table.picking {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      border: 1px solid #94a3b8;
      background: #fff;
    }}
    table.picking .c-main {{ width: auto; }}
    table.picking .c-check {{ width: 72px; }}
    table.picking th,
    table.picking td {{
      border: 1px solid #94a3b8;
      padding: 8px;
      vertical-align: middle;
    }}
    table.picking .totals-row th {{
      background: #f1f5f9;
      font-weight: 700;
    }}
    table.picking th.main {{
      text-align: left;
      font-size: 14px;
    }}
    table.picking th.check {{
      text-align: center;
      font-size: 11px;
      line-height: 1.25;
    }}
    table.picking th.check .sub {{
      display: inline-block;
      margin-top: 2px;
      font-size: 12px;
    }}
    table.picking.summary td.main {{
      font-size: 14px;
      font-weight: 600;
      line-height: 1.35;
    }}
    td.main {{ text-align: left; }}
    tr.product-row td.main {{
      width: 100%;
    }}
    td.check {{
      text-align: center;
      width: 72px;
      font-size: 13px;
      font-weight: 700;
    }}
    .sku-text {{ min-width: 0; }}
    .sku-title {{
      margin: 0 0 4px;
      font-size: 20px;
      font-weight: 800;
      line-height: 1.25;
      white-space: nowrap;
      overflow: visible;
      max-width: 100%;
    }}
    .sku-meta {{
      margin: 0 0 2px;
      color: #475569;
      font-size: 11px;
      line-height: 1.3;
    }}
    .sku-article {{
      margin: 0 0 2px;
      font-size: 12px;
      font-weight: 700;
      line-height: 1.3;
      word-break: break-word;
    }}
    .sku-barcodes {{ margin: 4px 0 2px; }}
    .sku-barcode {{
      margin: 0 0 2px;
      font-size: 20px;
      font-weight: 800;
      line-height: 1.25;
      letter-spacing: 0.02em;
      font-variant-numeric: tabular-nums;
      word-break: break-all;
    }}
    .sku-color {{
      margin: 0 0 2px;
      font-size: 14px;
      font-weight: 700;
      line-height: 1.3;
      color: #0f172a;
    }}
    .sku-qty {{
      margin: 4px 0 0;
      font-size: 20px;
      font-weight: 800;
      line-height: 1.25;
    }}
    .order-line {{
      display: flex;
      align-items: center;
      gap: 12px;
      width: 100%;
      min-height: 28px;
    }}
    .order-line .idx {{
      flex: 0 0 28px;
      color: #64748b;
      font-weight: 600;
    }}
    .order-line .oid {{
      flex: 1 1 auto;
      min-width: 0;
      white-space: nowrap;
      color: #0f172a;
    }}
    .order-line .sticker-group {{
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
      margin-left: auto;
      flex: 0 0 auto;
    }}
    .order-line .sticker {{
      white-space: nowrap;
      color: #0f172a;
    }}
    .order-line .partb {{
      font-size: 16px;
      font-weight: 800;
      letter-spacing: 0.02em;
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
      line-height: 1.2;
    }}
    /* Duplicate short sticker codes across the supply — force operator attention */
    .order-line .partb-dup {{
      border: 2.5px solid #0f172a;
      padding: 2px 6px;
      display: inline-block;
      min-width: 2.5em;
      text-align: center;
    }}
    .box {{
      display: inline-block;
      width: 18px;
      height: 18px;
      border: 1.5px solid #0f172a;
      background: #fff;
      vertical-align: middle;
    }}
    tr.article-end > td {{
      border-bottom: 3px solid #0f172a;
    }}
    .empty {{ margin: 0; padding: 16px; color: #64748b; }}
    @media print {{
      .no-print {{ display: none !important; }}
      body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
      tr {{ page-break-inside: avoid; }}
      .summary-page {{
        page-break-after: always;
        break-after: page;
      }}
      .order-line .partb-dup {{
        border: 2.5px solid #0f172a;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
    }}
  </style>
</head>
<body>
  {"" if for_pdf else '<div class="toolbar no-print"><button type="button" onclick="window.print()">Печать</button></div>'}
  {summary_html}
  {detail_html}
  {"" if for_pdf else '''<script>
(function () {
  function fitSkuTitles() {
    document.querySelectorAll(".sku-title").forEach(function (el) {
      var size = 20;
      el.style.fontSize = size + "px";
      // Shrink until the full title fits on one line (no ellipsis / wrap).
      while (size > 10 && el.scrollWidth > el.clientWidth + 1) {
        size -= 0.5;
        el.style.fontSize = size + "px";
      }
    });
  }
  function ready() {
    fitSkuTitles();
    setTimeout(function () { window.print(); }, 300);
  }
  window.addEventListener("beforeprint", fitSkuTitles);
  window.addEventListener("resize", fitSkuTitles);
  if (document.readyState === "complete") ready();
  else window.addEventListener("load", ready);
})();
</script>'''}
</body>
</html>"""


def _product_photos_dir() -> str:
    import os

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    preferred = os.path.join(root, "data", "product_photos")
    legacy = os.path.join(root, "product_photos")
    if os.path.isdir(preferred):
        return preferred
    return legacy


def _photo_data_uri_from_bytes(raw: bytes, ctype: str = "image/jpeg") -> str:
    if not raw or len(raw) > 2_000_000:
        return ""
    if ctype not in {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}:
        ctype = "image/jpeg"
    return f"data:{ctype};base64,{base64.b64encode(raw).decode('ascii')}"


def _photo_data_uri(
    url: str,
    *,
    timeout: float = 4.0,
    local_photo_paths: dict[int, str] | None = None,
) -> str:
    """Embed product photos for headless HTML→PDF (local files or remote URL)."""
    import os
    import re

    text = str(url or "").strip()
    if not text or text.startswith("data:"):
        return text
    m = re.match(r"^/api/products/photo/(\d+)/?$", text)
    if m and local_photo_paths is not None:
        path = local_photo_paths.get(int(m.group(1))) or ""
        if path and os.path.isfile(path):
            try:
                with open(path, "rb") as fh:
                    raw = fh.read()
                ext = os.path.splitext(path)[1].lower()
                ctype = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".webp": "image/webp",
                    ".gif": "image/gif",
                }.get(ext, "image/webp")
                return _photo_data_uri_from_bytes(raw, ctype)
            except Exception as exc:
                _log.debug("picking local photo: %s", exc)
                return ""
        return ""
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
        return _photo_data_uri_from_bytes(raw, ctype)
    except Exception as exc:
        _log.debug("picking photo fetch: %s", exc)
        return ""


def _local_photo_paths_for_user(repo: ReviewRepository, *, user_id: int) -> dict[int, str]:
    import os

    root = _product_photos_dir()
    out: dict[int, str] = {}
    for row in repo.list_product_photos(user_id=user_id):
        try:
            pid = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        rel = str(row.get("photo_path") or "").strip()
        if not rel:
            continue
        path = os.path.join(root, rel)
        if os.path.isfile(path):
            out[pid] = path
    return out


def _embed_picking_list_photos(
    html_doc: str,
    groups: list[dict[str, Any]],
    *,
    max_photos: int = 40,
    local_photo_paths: dict[int, str] | None = None,
) -> str:
    """Embed a bounded number of photos so PDF gen cannot stall on large supplies."""
    out = html_doc
    embedded = 0
    for g in groups:
        if embedded >= max_photos:
            break
        src = str(g.get("product_photo") or "").strip()
        if not src or src.startswith("data:"):
            continue
        data_uri = _photo_data_uri(
            src, timeout=2.5, local_photo_paths=local_photo_paths
        )
        if data_uri:
            out = out.replace(f'src="{_esc(src)}"', f'src="{data_uri}"', 1)
            embedded += 1
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


def render_picking_list_pdf(
    payload: dict[str, Any],
    *,
    repo: ReviewRepository | None = None,
    user_id: int | None = None,
    embed_photos: bool = True,
) -> bytes:
    """A4 picking list as PDF for direct print/download (no HTML page).

    Embeds local Settings→Products photos from disk (no network). Caps count so
    LibreOffice stays reasonable on large supplies.
    """
    html_doc = render_picking_list_html(payload, for_pdf=True)
    if embed_photos and repo is not None and user_id is not None:
        local_paths: dict[int, str] | None = None
        try:
            local_paths = _local_photo_paths_for_user(repo, user_id=int(user_id))
        except Exception as exc:
            _log.debug("picking local photo map: %s", exc)
            local_paths = None
        html_doc = _embed_picking_list_photos(
            html_doc,
            list(payload.get("groups") or []),
            local_photo_paths=local_paths,
            max_photos=60,
        )
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
        name = str(g.get("product_name") or "").strip() or "—"
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
  <!-- feedpilot-stickers:20260804i -->
  <meta name="feedpilot-build" content="picking-20260804i" />
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
      font-size: 12px; font-weight: 800; line-height: 1.2;
      max-height: 14mm; overflow: hidden;
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
