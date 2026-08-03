"""WB FBS orders module — isolated from FBW supplies.

Uses marketplace-api.wildberries.ru and credentials from supply_sources (marketplace=wb).
Does not create/modify supplies on WB; sync + stickers + local read models only.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .repository import ReviewRepository

_log = logging.getLogger(__name__)

WB_FBS_API = "https://marketplace-api.wildberries.ru"

# UI tab <- supplierStatus / wbStatus / archive flag
TAB_NEW = "new"
TAB_ASSEMBLY = "assembly"       # confirm
TAB_DELIVERY = "delivery"       # complete
TAB_FINISHED = "finished"       # sold etc.
TAB_CANCELLED = "cancelled"
TAB_ARCHIVE = "archive"

_FINISHED_WB = {"sold"}
_CANCELLED_SUPPLIER = {"cancel", "cancel_carrier"}
_CANCELLED_WB = {
    "canceled",
    "canceled_by_client",
    "declined_by_client",
    "defect",
    "canceled_by_carrier",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def compute_tab(*, supplier_status: str, wb_status: str, is_archive: bool) -> str:
    if is_archive:
        return TAB_ARCHIVE
    ss = (supplier_status or "").strip().lower()
    ws = (wb_status or "").strip().lower()
    if ss in _CANCELLED_SUPPLIER or ws in _CANCELLED_WB:
        return TAB_CANCELLED
    if ws in _FINISHED_WB:
        return TAB_FINISHED
    if ss == "confirm":
        return TAB_ASSEMBLY
    if ss == "complete":
        return TAB_DELIVERY
    if ss == "new" or not ss:
        return TAB_NEW
    # Fallback by supplier status
    if ss == "new":
        return TAB_NEW
    return TAB_ASSEMBLY if ss else TAB_NEW


def format_price_rub(price_kopecks: object, currency_code: object = 643) -> str:
    try:
        kopecks = int(price_kopecks or 0)
    except (TypeError, ValueError):
        kopecks = 0
    rub = kopecks / 100.0
    if int(currency_code or 643) == 643:
        if rub == int(rub):
            return f"{int(rub)} ₽"
        return f"{rub:.2f} ₽".replace(".", ",")
    return f"{rub:.2f}"


def cargo_type_label(cargo_type: object) -> str:
    try:
        ct = int(cargo_type or 0)
    except (TypeError, ValueError):
        return ""
    return {1: "МГТ", 2: "СГТ", 3: "КГТ+"}.get(ct, "")


SCOPE_ERROR_MESSAGE = "Нет ни одного источника с нужным API (Marketplace)."


def is_marketplace_scope_error(exc: object) -> bool:
    """True when WB token has no Marketplace category for FBS API."""
    text = str(exc or "").lower()
    return (
        "token scope not allowed" in text
        or "s2s-api-auth-marketplace" in text
        or ("http 401" in text and "unauthorized" in text and "marketplace" in text)
        or ("http 403" in text and "scope" in text)
    )


def friendly_sync_error(prefix: str, exc: object) -> str:
    """Short UI-safe sync error — never include raw WB JSON bodies."""
    if is_marketplace_scope_error(exc):
        return SCOPE_ERROR_MESSAGE
    text = str(exc or "")
    lower = text.lower()
    if "incorrectparameter" in lower or "incorrect parameter" in lower:
        return f"{prefix}: некорректные параметры запроса к WB"
    if "http 429" in lower:
        return f"{prefix}: превышен лимит запросов WB, попробуйте позже"
    if "http 401" in lower or "http 403" in lower:
        return f"{prefix}: нет доступа к API WB"
    if "http 5" in lower:
        return f"{prefix}: временная ошибка WB API"
    m = re.search(r"HTTP\s+(\d+)", text, flags=re.IGNORECASE)
    if m:
        return f"{prefix}: ошибка WB API (HTTP {m.group(1)})"
    return f"{prefix}: не удалось загрузить данные"


class WbFbsClient:
    def __init__(self, api_key: str, *, timeout: int = 30) -> None:
        self.api_key = str(api_key or "").strip()
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        body: dict[str, object] | list[object] | None = None,
        raw: bool = False,
    ) -> Any:
        qs = ("?" + urlencode({k: v for k, v in (params or {}).items() if v is not None})) if params else ""
        url = f"{WB_FBS_API}{path}{qs}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "Authorization": self.api_key,
            "Accept": "application/json",
            "User-Agent": "FeedPilot-WBFBS/1.0",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = Request(url, method=method.upper(), headers=headers, data=data)
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                payload = resp.read()
                if raw:
                    return payload, dict(resp.headers), resp.status
                if not payload:
                    return {}
                return json.loads(payload.decode("utf-8"))
        except HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            raise RuntimeError(f"WB FBS HTTP {exc.code}: {err_body or exc.reason}") from exc

    def get_new_orders(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/api/v3/orders/new")
        orders = data.get("orders") if isinstance(data, dict) else None
        return list(orders or []) if isinstance(orders, list) else []

    def get_orders_page(
        self,
        *,
        limit: int = 1000,
        next_token: int | None = 0,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], int | None]:
        # WB requires limit + next (0 on first page). Omitting next -> IncorrectParameter.
        params: dict[str, object] = {
            "limit": max(1, min(int(limit), 1000)),
            "next": int(next_token or 0),
        }
        if date_from is not None:
            params["dateFrom"] = int(date_from.timestamp())
        if date_to is not None:
            params["dateTo"] = int(date_to.timestamp())
        data = self._request("GET", "/api/v3/orders", params=params)
        if not isinstance(data, dict):
            return [], None
        orders = data.get("orders") if isinstance(data.get("orders"), list) else []
        nxt = data.get("next")
        try:
            next_val = int(nxt) if nxt is not None else None
        except (TypeError, ValueError):
            next_val = None
        # WB uses 0 as end marker in some versions
        if next_val == 0:
            next_val = None
        return list(orders), next_val

    def get_statuses(self, order_ids: list[int]) -> list[dict[str, Any]]:
        if not order_ids:
            return []
        data = self._request("POST", "/api/v3/orders/status", body={"orders": order_ids})
        orders = data.get("orders") if isinstance(data, dict) else None
        return list(orders or []) if isinstance(orders, list) else []

    def get_supplies(self, *, limit: int = 1000, next_token: int = 0) -> tuple[list[dict[str, Any]], int]:
        data = self._request("GET", "/api/v3/supplies", params={"limit": limit, "next": next_token})
        if not isinstance(data, dict):
            return [], 0
        supplies = data.get("supplies") if isinstance(data.get("supplies"), list) else []
        try:
            nxt = int(data.get("next") or 0)
        except (TypeError, ValueError):
            nxt = 0
        return list(supplies), nxt

    def get_supply_order_ids(self, supply_id: str) -> list[int]:
        # Prefer marketplace path; fall back to legacy
        for path in (
            f"/api/marketplace/v3/supplies/{supply_id}/order-ids",
            f"/api/v3/supplies/{supply_id}/orders",
        ):
            try:
                data = self._request("GET", path)
                if isinstance(data, dict):
                    if isinstance(data.get("orderIds"), list):
                        return [int(x) for x in data["orderIds"]]
                    if isinstance(data.get("orders"), list):
                        ids: list[int] = []
                        for item in data["orders"]:
                            if isinstance(item, dict) and item.get("id") is not None:
                                ids.append(int(item["id"]))
                            elif isinstance(item, (int, str)):
                                ids.append(int(item))
                        return ids
                if isinstance(data, list):
                    return [int(x.get("id") if isinstance(x, dict) else x) for x in data]
            except Exception as exc:
                _log.debug("get_supply_order_ids %s failed: %s", path, exc)
        return []

    def get_archive_orders(self, *, limit: int = 1000, next_token: int = 0) -> tuple[list[dict[str, Any]], int]:
        for path in (
            "/api/marketplace/v3/fbs/orders/archive",
            "/api/v3/orders/archive",
        ):
            try:
                data = self._request("GET", path, params={"limit": limit, "next": next_token})
                if not isinstance(data, dict):
                    continue
                orders = data.get("orders") if isinstance(data.get("orders"), list) else []
                try:
                    nxt = int(data.get("next") or 0)
                except (TypeError, ValueError):
                    nxt = 0
                return list(orders), nxt
            except Exception as exc:
                _log.debug("archive %s failed: %s", path, exc)
        return [], 0

    def get_order_stickers(
        self,
        order_ids: list[int],
        *,
        sticker_type: str = "png",
        width: int = 58,
        height: int = 40,
    ) -> list[dict[str, Any]]:
        if not order_ids:
            return []
        data = self._request(
            "POST",
            "/api/v3/orders/stickers",
            params={"type": sticker_type, "width": width, "height": height},
            body={"orders": order_ids},
        )
        stickers = data.get("stickers") if isinstance(data, dict) else None
        return list(stickers or []) if isinstance(stickers, list) else []

    def get_supply_barcode(self, supply_id: str, *, sticker_type: str = "png") -> bytes:
        payload, _headers, _status = self._request(
            "GET",
            f"/api/v3/supplies/{supply_id}/barcode",
            params={"type": sticker_type},
            raw=True,
        )
        # Some WB versions return JSON with base64
        try:
            parsed = json.loads(payload.decode("utf-8"))
            if isinstance(parsed, dict):
                b64 = parsed.get("file") or parsed.get("barcode") or ""
                if b64:
                    return base64.b64decode(b64)
        except Exception:
            pass
        return bytes(payload)

    def get_supply_boxes(self, supply_id: str) -> list[dict[str, Any]]:
        try:
            data = self._request("GET", f"/api/v3/supplies/{supply_id}/trbx")
            if isinstance(data, dict) and isinstance(data.get("trbxes"), list):
                return list(data["trbxes"])
            if isinstance(data, dict) and isinstance(data.get("boxes"), list):
                return list(data["boxes"])
            if isinstance(data, list):
                return list(data)
        except Exception as exc:
            _log.debug("get_supply_boxes failed: %s", exc)
        return []

    def get_box_stickers(
        self,
        supply_id: str,
        box_ids: list[str],
        *,
        sticker_type: str = "png",
    ) -> list[dict[str, Any]]:
        if not box_ids:
            return []
        data = self._request(
            "POST",
            f"/api/v3/supplies/{supply_id}/trbx/stickers",
            params={"type": sticker_type},
            body={"trbxIds": box_ids},
        )
        stickers = data.get("stickers") if isinstance(data, dict) else None
        return list(stickers or []) if isinstance(stickers, list) else []


def ensure_wb_fbs_tables(repo: ReviewRepository) -> None:
    with repo._connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wb_fbs_orders (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                user_id BIGINT NOT NULL,
                source_id BIGINT NOT NULL,
                order_id BIGINT NOT NULL,
                order_uid TEXT NOT NULL DEFAULT '',
                article TEXT NOT NULL DEFAULT '',
                nm_id BIGINT,
                chrt_id BIGINT,
                skus_json TEXT NOT NULL DEFAULT '[]',
                price BIGINT NOT NULL DEFAULT 0,
                final_price BIGINT NOT NULL DEFAULT 0,
                currency_code INTEGER NOT NULL DEFAULT 643,
                warehouse_id BIGINT,
                office_id BIGINT,
                offices_json TEXT NOT NULL DEFAULT '[]',
                cargo_type INTEGER NOT NULL DEFAULT 0,
                delivery_type TEXT NOT NULL DEFAULT '',
                supplier_status TEXT NOT NULL DEFAULT '',
                wb_status TEXT NOT NULL DEFAULT '',
                tab TEXT NOT NULL DEFAULT 'new',
                supply_id TEXT NOT NULL DEFAULT '',
                is_archive BOOLEAN NOT NULL DEFAULT FALSE,
                comment_text TEXT NOT NULL DEFAULT '',
                created_at_wb TIMESTAMPTZ,
                raw_json TEXT NOT NULL DEFAULT '{}',
                synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (user_id, source_id, order_id)
            )
            """
        )
        conn.execute(
            repo._sql(
                "CREATE INDEX IF NOT EXISTS idx_wb_fbs_orders_user_src_tab "
                "ON wb_fbs_orders(user_id, source_id, tab, created_at_wb DESC)"
            )
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wb_fbs_supplies (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                user_id BIGINT NOT NULL,
                source_id BIGINT NOT NULL,
                supply_id TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                done BOOLEAN NOT NULL DEFAULT FALSE,
                cargo_type INTEGER NOT NULL DEFAULT 0,
                destination_office_id BIGINT,
                created_at_wb TIMESTAMPTZ,
                closed_at_wb TIMESTAMPTZ,
                scan_dt TIMESTAMPTZ,
                order_ids_json TEXT NOT NULL DEFAULT '[]',
                boxes_json TEXT NOT NULL DEFAULT '[]',
                raw_json TEXT NOT NULL DEFAULT '{}',
                synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (user_id, source_id, supply_id)
            )
            """
        )
        conn.execute(
            repo._sql(
                "CREATE INDEX IF NOT EXISTS idx_wb_fbs_supplies_user_src "
                "ON wb_fbs_supplies(user_id, source_id, done, created_at_wb DESC)"
            )
        )


def _parse_dt(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def upsert_order(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    order: dict[str, Any],
    supplier_status: str | None = None,
    wb_status: str | None = None,
    is_archive: bool = False,
    supply_id: str | None = None,
) -> None:
    try:
        order_id = int(order.get("id"))
    except (TypeError, ValueError):
        return
    ss = str(supplier_status if supplier_status is not None else order.get("supplierStatus") or "").strip()
    ws = str(wb_status if wb_status is not None else order.get("wbStatus") or "").strip()
    sid = str(supply_id if supply_id is not None else order.get("supplyId") or "").strip()
    tab = compute_tab(supplier_status=ss, wb_status=ws, is_archive=is_archive)
    offices = order.get("offices") if isinstance(order.get("offices"), list) else []
    skus = order.get("skus") if isinstance(order.get("skus"), list) else []
    price = order.get("finalPrice")
    if price is None:
        price = order.get("price") or 0
    try:
        price_i = int(price or 0)
    except (TypeError, ValueError):
        price_i = 0
    try:
        final_i = int(order.get("convertedFinalPrice") or order.get("finalPrice") or price_i)
    except (TypeError, ValueError):
        final_i = price_i
    now = _utc_now()
    with repo._connect() as conn:
        conn.execute(
            repo._sql(
                """
                INSERT INTO wb_fbs_orders (
                    user_id, source_id, order_id, order_uid, article, nm_id, chrt_id, skus_json,
                    price, final_price, currency_code, warehouse_id, office_id, offices_json,
                    cargo_type, delivery_type, supplier_status, wb_status, tab, supply_id,
                    is_archive, comment_text, created_at_wb, raw_json, synced_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                ON CONFLICT (user_id, source_id, order_id) DO UPDATE SET
                    order_uid = EXCLUDED.order_uid,
                    article = EXCLUDED.article,
                    nm_id = EXCLUDED.nm_id,
                    chrt_id = EXCLUDED.chrt_id,
                    skus_json = EXCLUDED.skus_json,
                    price = EXCLUDED.price,
                    final_price = EXCLUDED.final_price,
                    currency_code = EXCLUDED.currency_code,
                    warehouse_id = EXCLUDED.warehouse_id,
                    office_id = EXCLUDED.office_id,
                    offices_json = EXCLUDED.offices_json,
                    cargo_type = EXCLUDED.cargo_type,
                    delivery_type = EXCLUDED.delivery_type,
                    supplier_status = CASE
                        WHEN EXCLUDED.supplier_status != '' THEN EXCLUDED.supplier_status
                        ELSE wb_fbs_orders.supplier_status
                    END,
                    wb_status = CASE
                        WHEN EXCLUDED.wb_status != '' THEN EXCLUDED.wb_status
                        ELSE wb_fbs_orders.wb_status
                    END,
                    -- GET /orders often omits statuses; do not reset tab to "new".
                    tab = CASE
                        WHEN EXCLUDED.is_archive THEN 'archive'
                        WHEN EXCLUDED.supplier_status != '' OR EXCLUDED.wb_status != ''
                            THEN EXCLUDED.tab
                        ELSE wb_fbs_orders.tab
                    END,
                    supply_id = CASE
                        WHEN EXCLUDED.supply_id != '' THEN EXCLUDED.supply_id
                        ELSE wb_fbs_orders.supply_id
                    END,
                    is_archive = EXCLUDED.is_archive OR wb_fbs_orders.is_archive,
                    comment_text = EXCLUDED.comment_text,
                    created_at_wb = COALESCE(EXCLUDED.created_at_wb, wb_fbs_orders.created_at_wb),
                    raw_json = EXCLUDED.raw_json,
                    synced_at = EXCLUDED.synced_at
                """
            ),
            (
                user_id,
                source_id,
                order_id,
                str(order.get("orderUid") or ""),
                str(order.get("article") or ""),
                order.get("nmId"),
                order.get("chrtId"),
                json.dumps(skus, ensure_ascii=False),
                price_i,
                final_i,
                int(order.get("convertedCurrencyCode") or order.get("currencyCode") or 643),
                order.get("warehouseId"),
                order.get("officeId"),
                json.dumps(offices, ensure_ascii=False),
                int(order.get("cargoType") or 0),
                str(order.get("deliveryType") or ""),
                ss,
                ws,
                tab,
                sid,
                bool(is_archive),
                str(order.get("comment") or ""),
                _parse_dt(order.get("createdAt")),
                json.dumps(order, ensure_ascii=False),
                now,
            ),
        )


def upsert_supply(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    supply: dict[str, Any],
    order_ids: list[int] | None = None,
    boxes: list[dict[str, Any]] | None = None,
) -> None:
    supply_id = str(supply.get("id") or "").strip()
    if not supply_id:
        return
    now = _utc_now()
    with repo._connect() as conn:
        conn.execute(
            repo._sql(
                """
                INSERT INTO wb_fbs_supplies (
                    user_id, source_id, supply_id, name, done, cargo_type, destination_office_id,
                    created_at_wb, closed_at_wb, scan_dt, order_ids_json, boxes_json, raw_json, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (user_id, source_id, supply_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    done = EXCLUDED.done,
                    cargo_type = EXCLUDED.cargo_type,
                    destination_office_id = EXCLUDED.destination_office_id,
                    created_at_wb = COALESCE(EXCLUDED.created_at_wb, wb_fbs_supplies.created_at_wb),
                    closed_at_wb = COALESCE(EXCLUDED.closed_at_wb, wb_fbs_supplies.closed_at_wb),
                    scan_dt = COALESCE(EXCLUDED.scan_dt, wb_fbs_supplies.scan_dt),
                    order_ids_json = CASE
                        WHEN EXCLUDED.order_ids_json != '[]' THEN EXCLUDED.order_ids_json
                        ELSE wb_fbs_supplies.order_ids_json
                    END,
                    boxes_json = CASE
                        WHEN EXCLUDED.boxes_json != '[]' THEN EXCLUDED.boxes_json
                        ELSE wb_fbs_supplies.boxes_json
                    END,
                    raw_json = EXCLUDED.raw_json,
                    synced_at = EXCLUDED.synced_at
                """
            ),
            (
                user_id,
                source_id,
                supply_id,
                str(supply.get("name") or ""),
                bool(supply.get("done")),
                int(supply.get("cargoType") or 0),
                supply.get("destinationOfficeId"),
                _parse_dt(supply.get("createdAt")),
                _parse_dt(supply.get("closedAt")),
                _parse_dt(supply.get("scanDt")),
                json.dumps(order_ids or [], ensure_ascii=False),
                json.dumps(boxes or [], ensure_ascii=False),
                json.dumps(supply, ensure_ascii=False),
                now,
            ),
        )


def list_orders(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int | None,
    tab: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    ensure_wb_fbs_tables(repo)
    conditions = ["user_id = ?"]
    params: list[Any] = [user_id]
    if source_id:
        conditions.append("source_id = ?")
        params.append(int(source_id))
    if tab:
        conditions.append("tab = ?")
        params.append(tab)
    if search:
        q = f"%{search.strip()}%"
        conditions.append(
            "(CAST(order_id AS TEXT) ILIKE ? OR article ILIKE ? OR supply_id ILIKE ? OR skus_json ILIKE ?)"
        )
        params.extend([q, q, q, q])
    where = " AND ".join(conditions)
    safe_page = max(int(page), 1)
    safe_size = min(max(int(page_size), 1), 200)
    offset = (safe_page - 1) * safe_size
    with repo._connect() as conn:
        total = conn.execute(
            repo._sql(f"SELECT COUNT(*) AS n FROM wb_fbs_orders WHERE {where}"),
            tuple(params),
        ).fetchone()
        rows = conn.execute(
            repo._sql(
                f"""
                SELECT * FROM wb_fbs_orders
                WHERE {where}
                ORDER BY created_at_wb DESC NULLS LAST, order_id DESC
                LIMIT ? OFFSET ?
                """
            ),
            tuple(params + [safe_size, offset]),
        ).fetchall()
        # counts by tab for current source
        count_conditions = ["user_id = ?"]
        count_params: list[Any] = [user_id]
        if source_id:
            count_conditions.append("source_id = ?")
            count_params.append(int(source_id))
        count_where = " AND ".join(count_conditions)
        count_rows = conn.execute(
            repo._sql(
                f"SELECT tab, COUNT(*) AS n FROM wb_fbs_orders WHERE {count_where} GROUP BY tab"
            ),
            tuple(count_params),
        ).fetchall()
    counts = {str(r["tab"]): int(r["n"]) for r in count_rows}
    name_map = repo.get_product_name_by_article(user_id=user_id)
    photo_map = repo.get_product_photo_map(user_id=user_id)
    # also map by wb_nmid
    items = []
    for row in rows:
        d = repo._row_to_dict(row)
        article = str(d.get("article") or "").strip()
        nm_id = str(d.get("nm_id") or "").strip()
        d["product_name"] = name_map.get(article) or name_map.get(nm_id) or article or "—"
        d["product_photo"] = photo_map.get(article) or photo_map.get(nm_id) or ""
        d["price_display"] = format_price_rub(d.get("final_price") or d.get("price"), d.get("currency_code"))
        d["cargo_label"] = cargo_type_label(d.get("cargo_type"))
        try:
            offices = json.loads(d.get("offices_json") or "[]")
        except Exception:
            offices = []
        d["offices"] = offices if isinstance(offices, list) else []
        d["warehouse_label"] = ", ".join(str(x) for x in d["offices"] if x) or (
            f"Склад {d.get('warehouse_id')}" if d.get("warehouse_id") else "—"
        )
        # WB order.skus = product barcodes (ШК)
        try:
            skus_raw = json.loads(d.get("skus_json") or "[]")
        except Exception:
            skus_raw = []
        barcodes: list[str] = []
        if isinstance(skus_raw, list):
            for sku in skus_raw:
                text = str(sku or "").strip()
                if text and text not in barcodes:
                    barcodes.append(text)
        d["barcodes"] = barcodes
        d["skus"] = barcodes
        items.append(d)
    return {
        "items": items,
        "total": int(total["n"]) if total else 0,
        "page": safe_page,
        "page_size": safe_size,
        "counts": {
            TAB_NEW: counts.get(TAB_NEW, 0),
            TAB_ASSEMBLY: counts.get(TAB_ASSEMBLY, 0),
            TAB_DELIVERY: counts.get(TAB_DELIVERY, 0),
            TAB_FINISHED: counts.get(TAB_FINISHED, 0),
            TAB_CANCELLED: counts.get(TAB_CANCELLED, 0),
            TAB_ARCHIVE: counts.get(TAB_ARCHIVE, 0),
        },
    }


def list_supplies(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int | None,
    only_open: bool = False,
) -> list[dict[str, Any]]:
    ensure_wb_fbs_tables(repo)
    conditions = ["user_id = ?"]
    params: list[Any] = [user_id]
    if source_id:
        conditions.append("source_id = ?")
        params.append(int(source_id))
    if only_open:
        conditions.append("done = FALSE")
    where = " AND ".join(conditions)
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                f"""
                SELECT * FROM wb_fbs_supplies
                WHERE {where}
                ORDER BY created_at_wb DESC NULLS LAST
                LIMIT 500
                """
            ),
            tuple(params),
        ).fetchall()
    result = []
    for row in rows:
        d = repo._row_to_dict(row)
        try:
            d["order_ids"] = json.loads(d.get("order_ids_json") or "[]")
        except Exception:
            d["order_ids"] = []
        try:
            d["boxes"] = json.loads(d.get("boxes_json") or "[]")
        except Exception:
            d["boxes"] = []
        result.append(d)
    return result


def clear_source_data(repo: ReviewRepository, *, user_id: int, source_id: int) -> dict[str, int]:
    ensure_wb_fbs_tables(repo)
    with repo._connect() as conn:
        o = conn.execute(
            repo._sql("DELETE FROM wb_fbs_orders WHERE user_id = ? AND source_id = ?"),
            (user_id, source_id),
        )
        s = conn.execute(
            repo._sql("DELETE FROM wb_fbs_supplies WHERE user_id = ? AND source_id = ?"),
            (user_id, source_id),
        )
    return {"orders": int(o.rowcount or 0), "supplies": int(s.rowcount or 0)}


def sync_wb_fbs_source(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    api_key: str,
    stop_requested: Callable[[], bool] | None = None,
    progress: Callable[[str, int], None] | None = None,
    lookback_days: int = 14,
    archive_pages: int = 2,
) -> dict[str, Any]:
    """Incremental sync for one WB supply source. Respects stop_requested between pages."""
    ensure_wb_fbs_tables(repo)
    client = WbFbsClient(api_key)
    stopped = False
    # Unique IDs — same order can appear in /new and /orders; do not double-count.
    seen_order_ids: set[int] = set()
    seen_supply_ids: set[str] = set()
    errors: list[str] = []

    def _stopped() -> bool:
        return bool(stop_requested and stop_requested())

    def _order_count() -> int:
        return len(seen_order_ids)

    def _supply_count() -> int:
        return len(seen_supply_ids)

    def _note_order(order: dict[str, Any]) -> None:
        oid = order.get("id")
        if oid is None:
            return
        try:
            seen_order_ids.add(int(oid))
        except (TypeError, ValueError):
            return

    def _prog(msg: str, n: int | None = None) -> None:
        if progress:
            progress(msg, _order_count() if n is None else n)

    # 1) New orders — also probes Marketplace token scope early.
    _prog("Новые заказы…")
    try:
        new_orders = client.get_new_orders()
        for order in new_orders:
            if _stopped():
                stopped = True
                break
            upsert_order(
                repo,
                user_id=user_id,
                source_id=source_id,
                order=order,
                supplier_status="new",
                is_archive=False,
            )
            _note_order(order)
        time.sleep(0.2)
    except Exception as exc:
        _log.warning("wb_fbs new orders failed: %s", exc)
        if is_marketplace_scope_error(exc):
            return {
                "orders": 0,
                "supplies": 0,
                "errors": [],
                "stopped": False,
                "scope_error": True,
                "message": SCOPE_ERROR_MESSAGE,
            }
        errors.append(friendly_sync_error("new", exc))

    if _stopped():
        return {
            "orders": _order_count(),
            "supplies": _supply_count(),
            "errors": errors,
            "stopped": True,
        }

    # 2) Recent orders pages
    _prog("Заказы за период…")
    date_to = datetime.now(UTC)
    date_from = date_to - timedelta(days=max(1, min(lookback_days, 30)))
    next_token: int | None = 0
    pages = 0
    try:
        while pages < 20:
            if _stopped():
                stopped = True
                break
            orders, next_token = client.get_orders_page(
                limit=1000,
                next_token=next_token if next_token is not None else 0,
                date_from=date_from,
                date_to=date_to,
            )
            if not orders:
                break
            for order in orders:
                upsert_order(repo, user_id=user_id, source_id=source_id, order=order)
                _note_order(order)
            pages += 1
            _prog(f"Заказы… стр. {pages}")
            if next_token is None:
                break
            time.sleep(0.25)
    except Exception as exc:
        _log.warning("wb_fbs orders page failed: %s", exc)
        if is_marketplace_scope_error(exc):
            return {
                "orders": _order_count(),
                "supplies": _supply_count(),
                "errors": [],
                "stopped": False,
                "scope_error": True,
                "message": SCOPE_ERROR_MESSAGE,
            }
        errors.append(friendly_sync_error("orders", exc))

    if _stopped():
        return {
            "orders": _order_count(),
            "supplies": _supply_count(),
            "errors": errors,
            "stopped": True,
        }

    # 3) Refresh statuses for known non-archive orders
    _prog("Статусы…")
    with repo._connect() as conn:
        id_rows = conn.execute(
            repo._sql(
                """
                SELECT order_id FROM wb_fbs_orders
                WHERE user_id = ? AND source_id = ? AND is_archive = FALSE
                ORDER BY synced_at DESC
                LIMIT 5000
                """
            ),
            (user_id, source_id),
        ).fetchall()
    all_ids = [int(r["order_id"]) for r in id_rows]
    for i in range(0, len(all_ids), 1000):
        if _stopped():
            stopped = True
            break
        chunk = all_ids[i : i + 1000]
        try:
            statuses = client.get_statuses(chunk)
            status_map = {
                int(s["id"]): s
                for s in statuses
                if isinstance(s, dict) and s.get("id") is not None
            }
            with repo._connect() as conn:
                for oid, st in status_map.items():
                    ss = str(st.get("supplierStatus") or "")
                    ws = str(st.get("wbStatus") or "")
                    tab = compute_tab(supplier_status=ss, wb_status=ws, is_archive=False)
                    conn.execute(
                        repo._sql(
                            """
                            UPDATE wb_fbs_orders
                            SET supplier_status = ?, wb_status = ?, tab = ?, synced_at = ?
                            WHERE user_id = ? AND source_id = ? AND order_id = ?
                            """
                        ),
                        (ss, ws, tab, _utc_now(), user_id, source_id, oid),
                    )
            time.sleep(0.2)
        except Exception as exc:
            errors.append(friendly_sync_error("status", exc))
            break

    if _stopped():
        return {
            "orders": _order_count(),
            "supplies": _supply_count(),
            "errors": errors,
            "stopped": True,
        }

    # 4) Supplies (+ order ids / boxes for open ones only)
    _prog("Поставки FBS…", _supply_count())
    next_sup = 0
    sup_pages = 0
    try:
        while sup_pages < 10:
            if _stopped():
                stopped = True
                break
            supplies, next_sup = client.get_supplies(limit=1000, next_token=next_sup)
            if not supplies:
                break
            for supply in supplies:
                if _stopped():
                    stopped = True
                    break
                sid = str(supply.get("id") or "")
                order_ids: list[int] = []
                boxes: list[dict[str, Any]] = []
                if sid and not bool(supply.get("done")):
                    try:
                        order_ids = client.get_supply_order_ids(sid)
                        time.sleep(0.15)
                        boxes = client.get_supply_boxes(sid)
                        time.sleep(0.15)
                    except Exception as exc:
                        errors.append(friendly_sync_error(f"supply {sid}", exc))
                upsert_supply(
                    repo,
                    user_id=user_id,
                    source_id=source_id,
                    supply=supply,
                    order_ids=order_ids,
                    boxes=boxes,
                )
                if sid:
                    seen_supply_ids.add(sid)
                # Link orders to supply + mark assembly if still new
                if order_ids:
                    with repo._connect() as conn:
                        for oid in order_ids:
                            conn.execute(
                                repo._sql(
                                    """
                                    UPDATE wb_fbs_orders
                                    SET supply_id = ?,
                                        supplier_status = CASE
                                            WHEN supplier_status = 'new' OR supplier_status = '' THEN 'confirm'
                                            ELSE supplier_status
                                        END,
                                        tab = CASE
                                            WHEN tab = 'new' THEN 'assembly'
                                            ELSE tab
                                        END,
                                        synced_at = ?
                                    WHERE user_id = ? AND source_id = ? AND order_id = ?
                                    """
                                ),
                                (sid, _utc_now(), user_id, source_id, oid),
                            )
            sup_pages += 1
            _prog(f"Поставки… стр. {sup_pages}", _supply_count())
            if not next_sup:
                break
            time.sleep(0.25)
    except Exception as exc:
        errors.append(friendly_sync_error("supplies", exc))

    if _stopped():
        return {
            "orders": _order_count(),
            "supplies": _supply_count(),
            "errors": errors,
            "stopped": True,
        }

    # 5) Archive — limited pages
    _prog("Архив…")
    arch_next = 0
    try:
        for _ in range(max(0, archive_pages)):
            if _stopped():
                stopped = True
                break
            arch_orders, arch_next = client.get_archive_orders(limit=1000, next_token=arch_next)
            if not arch_orders:
                break
            for order in arch_orders:
                upsert_order(
                    repo,
                    user_id=user_id,
                    source_id=source_id,
                    order=order,
                    is_archive=True,
                    supplier_status=str(order.get("supplierStatus") or ""),
                    wb_status=str(order.get("wbStatus") or "sold"),
                )
                _note_order(order)
            if not arch_next:
                break
            time.sleep(0.25)
    except Exception as exc:
        errors.append(friendly_sync_error("archive", exc))

    return {
        "orders": _order_count(),
        "supplies": _supply_count(),
        "errors": errors,
        "stopped": stopped,
    }


# Sync state for web layer
_wb_fbs_sync_state: dict[str, object] = {
    "in_progress": False,
    "synced": 0,
    "total": 0,
    "message": "",
    "errors": [],
    "cancel_requested": False,
    "source_id": None,
}
_wb_fbs_sync_lock = threading.Lock()


def get_sync_state() -> dict[str, object]:
    with _wb_fbs_sync_lock:
        return dict(_wb_fbs_sync_state)


def request_sync_stop() -> bool:
    with _wb_fbs_sync_lock:
        if _wb_fbs_sync_state.get("in_progress"):
            _wb_fbs_sync_state["cancel_requested"] = True
            return True
    return False


def start_sync_thread(
    *,
    repo: ReviewRepository,
    user_id: int,
    source_id: int,
    api_key: str,
) -> tuple[bool, str]:
    with _wb_fbs_sync_lock:
        if _wb_fbs_sync_state.get("in_progress"):
            return False, "Синхронизация уже запущена"
        _wb_fbs_sync_state.update(
            {
                "in_progress": True,
                "synced": 0,
                "total": 0,
                "message": "Запуск…",
                "errors": [],
                "cancel_requested": False,
                "source_id": source_id,
            }
        )

    def _run() -> None:
        def stop_requested() -> bool:
            with _wb_fbs_sync_lock:
                return bool(_wb_fbs_sync_state.get("cancel_requested"))

        def progress(msg: str, n: int) -> None:
            with _wb_fbs_sync_lock:
                _wb_fbs_sync_state["message"] = msg
                _wb_fbs_sync_state["synced"] = n

        try:
            result = sync_wb_fbs_source(
                repo,
                user_id=user_id,
                source_id=source_id,
                api_key=api_key,
                stop_requested=stop_requested,
                progress=progress,
            )
            with _wb_fbs_sync_lock:
                if result.get("scope_error"):
                    _wb_fbs_sync_state["errors"] = []
                    _wb_fbs_sync_state["synced"] = 0
                    _wb_fbs_sync_state["message"] = str(
                        result.get("message") or SCOPE_ERROR_MESSAGE
                    )
                else:
                    errs = list(result.get("errors") or [])
                    # Never surface raw WB auth/scope dumps in the UI.
                    safe_errs = [e for e in errs if not is_marketplace_scope_error(e)]
                    if errs and not safe_errs:
                        _wb_fbs_sync_state["errors"] = []
                        _wb_fbs_sync_state["synced"] = 0
                        _wb_fbs_sync_state["message"] = SCOPE_ERROR_MESSAGE
                    else:
                        _wb_fbs_sync_state["errors"] = safe_errs
                        _wb_fbs_sync_state["synced"] = int(result.get("orders") or 0)
                        if result.get("stopped"):
                            _wb_fbs_sync_state["message"] = (
                                f"Остановлено. Заказов: {result.get('orders', 0)}, "
                                f"поставок: {result.get('supplies', 0)}"
                            )
                        elif safe_errs:
                            _wb_fbs_sync_state["message"] = (
                                f"Готово с ошибками. Заказов: {result.get('orders', 0)}, "
                                f"поставок: {result.get('supplies', 0)}"
                            )
                        else:
                            _wb_fbs_sync_state["message"] = (
                                f"Готово. Заказов: {result.get('orders', 0)}, "
                                f"поставок: {result.get('supplies', 0)}"
                            )
        except Exception as exc:
            _log.exception("wb_fbs sync failed")
            with _wb_fbs_sync_lock:
                if is_marketplace_scope_error(exc):
                    _wb_fbs_sync_state["errors"] = []
                    _wb_fbs_sync_state["message"] = SCOPE_ERROR_MESSAGE
                else:
                    _wb_fbs_sync_state["errors"] = [str(exc)]
                    _wb_fbs_sync_state["message"] = f"Ошибка: {exc}"
        finally:
            with _wb_fbs_sync_lock:
                _wb_fbs_sync_state["in_progress"] = False
                _wb_fbs_sync_state["cancel_requested"] = False

    threading.Thread(target=_run, daemon=True, name="wb-fbs-sync").start()
    return True, "Синхронизация запущена"
