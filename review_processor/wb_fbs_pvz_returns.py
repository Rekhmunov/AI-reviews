"""WB FBS «Возвраты ПВЗ» — issued-at-PVZ returns on top of goods-return cache.

Sync always pulls a 31-day WB order-date window ending today (Moscow) and does
not use the calendar filter. After sync the UI shows issued rows
(``completedDt``, status «Выдано») for those same 31 days. The calendar filter
only narrows the local table without calling WB.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from . import wb_fbs as wb
from .repository import ReviewRepository
from .wb_fbs_detail import _order_sticker_sort_key, _portal_title_sort_key
from .wb_fbs_returns import (
    GOODS_RETURN_MAX_WINDOW_DAYS,
    MSK,
    _is_goods_return_rate_limit_error,
    ensure_wb_fbs_returns_tables,
    goods_return_rate_limit_status,
    goods_return_token_cooldown_seconds,
    resolve_goods_return_api_keys,
    sync_goods_returns,
)

_log = logging.getLogger(__name__)

ISSUED_STATUS = "выдано"
# Inclusive days in the WB request: issue_to and the 30 days before it.
WB_LOOKBACK_DAYS = GOODS_RETURN_MAX_WINDOW_DAYS - 1
ISSUE_RANGE_MAX_DAYS = GOODS_RETURN_MAX_WINDOW_DAYS
EMPTY_SOURCES_MESSAGE = "Выберите источники в настройках"

_pvz_job_guard = threading.Lock()
_pvz_jobs: dict[int, dict[str, Any]] = {}


def ensure_pvz_return_tables(repo: ReviewRepository) -> None:
    ensure_wb_fbs_returns_tables(repo)
    with repo._connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wb_fbs_pvz_return_settings (
                user_id BIGINT PRIMARY KEY,
                source_ids_json TEXT NOT NULL DEFAULT '[]',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


def issue_range(date_from: str, date_to: str) -> tuple[date, date]:
    """User-selected issue dates, clamped to at most 31 inclusive days."""
    start = date.fromisoformat(str(date_from or "").strip()[:10])
    end = date.fromisoformat(str(date_to or "").strip()[:10])
    if end < start:
        start, end = end, start
    if (end - start).days + 1 > ISSUE_RANGE_MAX_DAYS:
        start = end - timedelta(days=ISSUE_RANGE_MAX_DAYS - 1)
    return start, end


def parse_issue_bounds(date_from: str = "", date_to: str = "") -> tuple[date, date]:
    """Empty bounds mean today (Moscow). Invalid text raises ValueError."""
    today = datetime.now(MSK).date()
    raw_from = str(date_from or "").strip()[:10]
    raw_to = str(date_to or "").strip()[:10]
    try:
        start = date.fromisoformat(raw_from) if raw_from else today
        end = date.fromisoformat(raw_to) if raw_to else start
    except ValueError as exc:
        raise ValueError("Некорректная дата") from exc
    return issue_range(start.isoformat(), end.isoformat())


def wb_query_window(issue_to: date) -> tuple[str, str]:
    """WB order-date window that can contain handouts on ``issue_to``.

    For 2026-10-19 this is 2026-09-19..2026-10-19.
    """
    start = issue_to - timedelta(days=WB_LOOKBACK_DAYS)
    return start.isoformat(), issue_to.isoformat()


def sync_display_range(*, today: date | None = None) -> tuple[date, date]:
    """Issue-date range shown after sync: last 31 inclusive days ending today (MSK)."""
    end = today or datetime.now(MSK).date()
    start = end - timedelta(days=WB_LOOKBACK_DAYS)
    return start, end


def row_issued_in_range(row: dict[str, Any], start: date, end: date) -> bool:
    status = str(row.get("status") or "").strip().casefold()
    if status != ISSUED_STATUS:
        return False
    completed = str(row.get("completed_dt") or row.get("completedDt") or "").strip()
    if len(completed) < 10:
        return False
    try:
        day = date.fromisoformat(completed[:10])
    except ValueError:
        return False
    return start <= day <= end


def format_issued_label(completed_dt: object) -> str:
    text = str(completed_dt or "").strip()
    if len(text) < 10:
        return ""
    try:
        day = date.fromisoformat(text[:10])
    except ValueError:
        return ""
    label = day.strftime("%d.%m.%Y")
    rest = text[10:].lstrip("T ")
    if len(rest) >= 5 and rest[2] == ":":
        return f"{label} {rest[:5]}"
    return label


def _dedupe_key(row: dict[str, Any]) -> str:
    srid = str(row.get("srid") or "").strip()
    if srid:
        return f"srid:{srid}"
    sticker = str(row.get("sticker_id") or "").strip()
    try:
        order_id = int(row.get("wb_order_id") or row.get("orderId") or 0)
    except (TypeError, ValueError):
        order_id = 0
    shk = str(row.get("shk_id") or "").strip()
    return f"row:{sticker}:{order_id}:{shk}"


def _row_matches_order(row: dict[str, Any], orders: dict[tuple[int, int], dict[str, Any]]) -> bool:
    try:
        order_id = int(row.get("wb_order_id") or 0)
        source_id = int(row.get("source_id") or 0)
    except (TypeError, ValueError):
        return False
    return order_id > 0 and source_id > 0 and (source_id, order_id) in orders


def dedupe_issued_rows(
    rows: list[dict[str, Any]],
    orders: dict[tuple[int, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    """One row per srid. Prefer the copy that matched a local FBS order."""
    best: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows:
        key = _dedupe_key(row)
        prev = best.get(key)
        if prev is None:
            best[key] = row
            order.append(key)
            continue
        if _row_matches_order(row, orders) and not _row_matches_order(prev, orders):
            best[key] = row
    return [best[key] for key in order]


def _digits(value: object) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _parse_json_list(raw: object) -> list[Any]:
    if isinstance(raw, list):
        return raw
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _local_kiz_codes(raw: object) -> list[str]:
    out: list[str] = []
    for item in _parse_json_list(raw):
        code = wb._kiz_code_clean(item)
        if code and code not in out:
            out.append(code)
    return out


def _product_index(
    products: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_article: dict[str, dict[str, Any]] = {}
    by_nm: dict[str, dict[str, Any]] = {}
    by_barcode: dict[str, dict[str, Any]] = {}
    for product in products:
        if not isinstance(product, dict):
            continue
        article = str(product.get("supplier_article") or "").strip()
        if article:
            by_article[article] = product
            by_article[article.casefold()] = product
        nm_id = str(product.get("wb_nmid") or "").strip()
        if nm_id:
            by_nm[nm_id] = product
            by_nm[nm_id.casefold()] = product
        for barcode in product.get("barcodes") or []:
            text = str(barcode or "").strip()
            if not text:
                continue
            by_barcode[text] = product
            digits = _digits(text)
            if digits:
                by_barcode[digits] = product
    return by_article, by_nm, by_barcode


def _match_product(
    index: tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]],
    *,
    article: str,
    nm_id: str,
    barcodes: list[str],
) -> dict[str, Any] | None:
    by_article, by_nm, by_barcode = index
    if article:
        hit = by_article.get(article) or by_article.get(article.casefold())
        if hit:
            return hit
    if nm_id:
        hit = by_nm.get(nm_id) or by_nm.get(nm_id.casefold())
        if hit:
            return hit
    for barcode in barcodes:
        text = str(barcode or "").strip()
        if not text:
            continue
        hit = by_barcode.get(text) or by_barcode.get(_digits(text))
        if hit:
            return hit
    return None


def _photo_url(product: dict[str, Any] | None) -> str:
    if not product or not product.get("photo_path"):
        return ""
    try:
        pid = int(product.get("id") or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid <= 0:
        return ""
    return f"/api/products/photo/{pid}"


def _item_from_row(
    row: dict[str, Any],
    orders: dict[tuple[int, int], dict[str, Any]],
    index: tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]],
    source_names: dict[int, str],
) -> dict[str, Any]:
    try:
        source_id = int(row.get("source_id") or 0)
    except (TypeError, ValueError):
        source_id = 0
    try:
        order_id = int(row.get("wb_order_id") or 0)
    except (TypeError, ValueError):
        order_id = 0
    order = orders.get((source_id, order_id)) if order_id > 0 else None
    order = order or {}
    article = str(order.get("article") or "").strip()
    nm_raw = order.get("nm_id")
    if nm_raw in (None, ""):
        nm_raw = row.get("nm_id")
    nm_id = str(nm_raw or "").strip()
    if nm_id in {"0", "None"}:
        nm_id = ""
    barcodes = [str(x or "").strip() for x in _parse_json_list(order.get("skus_json")) if str(x or "").strip()]
    row_barcode = str(row.get("barcode") or "").strip()
    if row_barcode and row_barcode not in barcodes:
        barcodes.append(row_barcode)
    product = _match_product(index, article=article, nm_id=nm_id, barcodes=barcodes)
    catalog_barcodes = [
        str(b or "").strip()
        for b in ((product or {}).get("barcodes") or [])
        if str(b or "").strip()
    ]
    name = str((product or {}).get("name") or "").strip() or article
    category = str((product or {}).get("product_category") or "").strip()
    completed = str(row.get("completed_dt") or "").strip()
    try:
        row_id = int(row.get("id") or 0)
    except (TypeError, ValueError):
        row_id = 0
    return {
        "id": row_id,
        "source_id": source_id,
        "source_name": str(source_names.get(source_id) or "").strip(),
        "order_id": order_id,
        "srid": str(row.get("srid") or "").strip(),
        "sticker_id": str(row.get("sticker_id") or "").strip(),
        "status": str(row.get("status") or "").strip(),
        "qty": 1,
        "completed_dt": completed,
        "issued_label": format_issued_label(completed),
        "article": article,
        "nm_id": nm_id,
        "product_name": name,
        "product_category": category,
        "product_photo": _photo_url(product),
        "product_barcodes": barcodes,
        "catalog_barcodes": catalog_barcodes,
        "barcode_label_name": str((product or {}).get("barcode_label_name") or "").strip(),
        "sticker_part_a": str(order.get("sticker_part_a") or "").strip(),
        "sticker_part_b": str(order.get("sticker_part_b") or "").strip(),
        "has_kiz": bool(_local_kiz_codes(order.get("kiz_codes_json"))),
    }


def sort_pvz_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pick-list order: card/product title, then sticker partB. Rows stay separate."""

    def _key(item: dict[str, Any]) -> tuple:
        title = str(item.get("product_name") or item.get("article") or "")
        return (
            _portal_title_sort_key(title),
            str(item.get("article") or "").casefold(),
            _order_sticker_sort_key(
                {
                    "sticker_part_b": item.get("sticker_part_b") or "",
                    "sticker_part_a": item.get("sticker_part_a") or "",
                    "order_id": item.get("order_id") or 0,
                }
            ),
            str(item.get("srid") or ""),
            int(item.get("id") or 0),
        )

    return sorted(items, key=_key)


def _merge_product_key(item: dict[str, Any]) -> str:
    name = str(item.get("product_name") or "").strip()
    article = str(item.get("article") or "").strip()
    if name:
        return f"name:{name.casefold()}"
    if article:
        return f"article:{article.casefold()}"
    return f"id:{int(item.get('id') or 0)}"


def merge_pvz_items_by_product(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sum qty for the same product name (pick-list style). Order = first seen."""
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in items:
        key = _merge_product_key(item)
        prev = merged.get(key)
        if prev is None:
            row = dict(item)
            try:
                row["qty"] = max(1, int(item.get("qty") or 1))
            except (TypeError, ValueError):
                row["qty"] = 1
            merged[key] = row
            order.append(key)
            continue
        try:
            prev["qty"] = int(prev.get("qty") or 0) + max(1, int(item.get("qty") or 1))
        except (TypeError, ValueError):
            prev["qty"] = int(prev.get("qty") or 0) + 1
    return [merged[key] for key in order]


def filter_pvz_items_by_category(
    items: list[dict[str, Any]],
    *,
    category: str = "",
) -> list[dict[str, Any]]:
    """Keep rows of one product category. Empty category = all rows."""
    wanted = str(category or "").strip()
    if not wanted:
        return list(items)
    if wanted == "__none__":
        return [item for item in items if not str(item.get("product_category") or "").strip()]
    return [
        item
        for item in items
        if str(item.get("product_category") or "").strip() == wanted
    ]


def product_category_options(
    repo: ReviewRepository,
    *,
    user_id: int,
) -> list[dict[str, Any]]:
    """Category names from Настройки → Товары (same list for every WB cabinet)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in repo.list_product_categories(user_id=user_id, seed_defaults=True):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        try:
            cat_id = int(row.get("id") or 0)
        except (TypeError, ValueError):
            cat_id = 0
        out.append({"id": cat_id, "name": name})
    return out


def assemble_pvz_items(
    rows: list[dict[str, Any]],
    *,
    orders: dict[tuple[int, int], dict[str, Any]],
    products: list[dict[str, Any]],
    source_names: dict[int, str] | None = None,
    date_from: date,
    date_to: date,
) -> list[dict[str, Any]]:
    issued = [row for row in rows if row_issued_in_range(row, date_from, date_to)]
    deduped = dedupe_issued_rows(issued, orders)
    index = _product_index(products)
    names = source_names or {}
    items = [_item_from_row(row, orders, index, names) for row in deduped]
    return sort_pvz_items(items)


def _wb_sources(repo: ReviewRepository, *, user_id: int) -> list[dict[str, Any]]:
    """All WB cabinets from Поставки → Источники (not only FBS)."""
    out: list[dict[str, Any]] = []
    for source in repo.list_supply_sources(user_id=user_id):
        if not isinstance(source, dict) or not wb.is_wb_source(source):
            continue
        try:
            source_id = int(source.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if source_id <= 0:
            continue
        out.append({"id": source_id, "name": str(source.get("name") or "").strip() or f"Источник {source_id}"})
    return out


def _clean_id_list(raw: object) -> list[int]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except Exception:
            return []
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for item in raw:
        try:
            source_id = int(item)
        except (TypeError, ValueError):
            continue
        if source_id > 0 and source_id not in out:
            out.append(source_id)
    return out


def saved_source_ids(repo: ReviewRepository, *, user_id: int) -> list[int]:
    ensure_pvz_return_tables(repo)
    with repo._connect() as conn:
        row = conn.execute(
            repo._sql(
                "SELECT source_ids_json FROM wb_fbs_pvz_return_settings WHERE user_id = ?"
            ),
            (int(user_id),),
        ).fetchone()
    if not row:
        return []
    payload = repo._row_to_dict(row).get("source_ids_json")
    return _clean_id_list(payload)


def settings_view(repo: ReviewRepository, *, user_id: int) -> dict[str, Any]:
    sources = _wb_sources(repo, user_id=user_id)
    allowed = {int(s["id"]) for s in sources}
    selected = [sid for sid in saved_source_ids(repo, user_id=user_id) if sid in allowed]
    selected_set = set(selected)
    return {
        "ok": True,
        "source_ids": selected,
        "sources": [
            {"id": int(s["id"]), "name": s["name"], "selected": int(s["id"]) in selected_set}
            for s in sources
        ],
    }


def save_settings_view(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_ids: object,
) -> dict[str, Any]:
    sources = _wb_sources(repo, user_id=user_id)
    allowed = {int(s["id"]) for s in sources}
    cleaned = [sid for sid in _clean_id_list(source_ids) if sid in allowed]
    ensure_pvz_return_tables(repo)
    payload = json.dumps(cleaned)
    with repo._connect() as conn:
        conn.execute(
            repo._sql(
                """
                INSERT INTO wb_fbs_pvz_return_settings (user_id, source_ids_json, updated_at)
                VALUES (?, ?, NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    source_ids_json = EXCLUDED.source_ids_json,
                    updated_at = NOW()
                """
            ),
            (int(user_id), payload),
        )
    return settings_view(repo, user_id=user_id)


def _chunks(values: list[int], size: int) -> list[list[int]]:
    step = max(1, int(size))
    return [values[i : i + step] for i in range(0, len(values), step)]


def _load_orders(
    repo: ReviewRepository,
    *,
    user_id: int,
    rows: list[dict[str, Any]],
) -> dict[tuple[int, int], dict[str, Any]]:
    pairs: list[tuple[int, int]] = []
    for row in rows:
        try:
            order_id = int(row.get("wb_order_id") or 0)
            source_id = int(row.get("source_id") or 0)
        except (TypeError, ValueError):
            continue
        if order_id > 0 and source_id > 0:
            pairs.append((source_id, order_id))
    if not pairs:
        return {}
    source_ids = sorted({sid for sid, _oid in pairs})
    order_ids = sorted({oid for _sid, oid in pairs})
    found: dict[tuple[int, int], dict[str, Any]] = {}
    source_sql = ",".join("?" * len(source_ids))
    with repo._connect() as conn:
        for chunk in _chunks(order_ids, 400):
            order_sql = ",".join("?" * len(chunk))
            fetched = conn.execute(
                repo._sql(
                    f"""
                    SELECT source_id, order_id, article, nm_id, skus_json,
                           kiz_codes_json, sticker_part_a, sticker_part_b
                    FROM wb_fbs_orders
                    WHERE user_id = ? AND source_id IN ({source_sql})
                      AND order_id IN ({order_sql})
                    """
                ),
                tuple([int(user_id), *source_ids, *chunk]),
            ).fetchall()
            for raw in fetched:
                item = repo._row_to_dict(raw)
                try:
                    key = (int(item.get("source_id") or 0), int(item.get("order_id") or 0))
                except (TypeError, ValueError):
                    continue
                if key[0] > 0 and key[1] > 0:
                    found[key] = item
    return found


def _load_issued_rows(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_ids: list[int],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    if not source_ids:
        return []
    placeholders = ",".join("?" * len(source_ids))
    sql = f"""
        SELECT * FROM wb_fbs_goods_returns
        WHERE user_id = ?
          AND source_id IN ({placeholders})
          AND completed_dt <> ''
          AND SUBSTR(completed_dt, 1, 10) >= ?
          AND SUBSTR(completed_dt, 1, 10) <= ?
    """
    params: list[Any] = [int(user_id), *[int(sid) for sid in source_ids], start.isoformat(), end.isoformat()]
    ensure_pvz_return_tables(repo)
    with repo._connect() as conn:
        fetched = conn.execute(repo._sql(sql), tuple(params)).fetchall()
    return [repo._row_to_dict(row) for row in fetched]


def list_for_view(
    repo: ReviewRepository,
    *,
    user_id: int,
    date_from: str = "",
    date_to: str = "",
    source_id: int = 0,
    category: str = "",
) -> dict[str, Any]:
    start, end = parse_issue_bounds(date_from, date_to)
    view = settings_view(repo, user_id=user_id)
    saved = [int(x) for x in (view.get("source_ids") or [])]
    try:
        picked = int(source_id or 0)
    except (TypeError, ValueError):
        picked = 0
    if picked > 0 and picked not in saved:
        raise ValueError("Источник не выбран в настройках")
    source_ids = [picked] if picked > 0 else saved
    names = {int(s["id"]): str(s.get("name") or "") for s in (view.get("sources") or [])}
    rows = _load_issued_rows(repo, user_id=user_id, source_ids=source_ids, start=start, end=end)
    orders = _load_orders(repo, user_id=user_id, rows=rows)
    products = repo.list_product_photos(user_id=user_id)
    items = assemble_pvz_items(
        rows,
        orders=orders,
        products=products,
        source_names=names,
        date_from=start,
        date_to=end,
    )
    categories = product_category_options(repo, user_id=user_id)
    filtered = filter_pvz_items_by_category(items, category=category)
    return {
        "ok": True,
        "items": filtered,
        "total": len(filtered),
        "total_unfiltered": len(items),
        "categories": categories,
        "category": str(category or "").strip(),
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
    }


def get_pvz_sync_job(*, user_id: int) -> dict[str, Any] | None:
    with _pvz_job_guard:
        job = _pvz_jobs.get(int(user_id))
        if not isinstance(job, dict):
            return None
        out = dict(job)
    errors = out.get("errors")
    if isinstance(errors, list):
        out["errors"] = list(errors)
    return out


def _set_pvz_job(user_id: int, **fields: Any) -> None:
    with _pvz_job_guard:
        job = _pvz_jobs.get(int(user_id))
        if not isinstance(job, dict):
            return
        job.update(fields)


def start_pvz_sync(
    repo: ReviewRepository,
    *,
    user_id: int,
    date_from: str = "",
    date_to: str = "",
) -> dict[str, Any]:
    """Pull goods-return for each saved source, sequentially, then list locally.

    Calendar ``date_from``/``date_to`` are ignored: sync always uses the last
    31 days ending today (Moscow). Those bounds are returned so the UI can
    show the synced period in the table.
    """
    del date_from, date_to
    start, end = sync_display_range()
    view = settings_view(repo, user_id=user_id)
    sources = [s for s in (view.get("sources") or []) if s.get("selected")]
    if not sources:
        raise ValueError(EMPTY_SOURCES_MESSAGE)
    wb_from, wb_to = wb_query_window(end)
    with _pvz_job_guard:
        existing = _pvz_jobs.get(int(user_id))
        if isinstance(existing, dict) and str(existing.get("status") or "") == "running":
            return {
                "ok": True,
                "async": True,
                "status": "running",
                "already_running": True,
                "message": str(existing.get("message") or "Синхронизация уже выполняется"),
                "date_from": start.isoformat(),
                "date_to": end.isoformat(),
            }
        started_at = datetime.now(UTC).isoformat()
        _pvz_jobs[int(user_id)] = {
            "status": "running",
            "message": "Запуск…",
            "started_at": started_at,
            "finished_at": "",
            "errors": [],
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "wb_date_from": wb_from,
            "wb_date_to": wb_to,
            "sources_done": 0,
            "sources_total": len(sources),
        }

    source_snapshot = [{"id": int(s["id"]), "name": str(s.get("name") or "")} for s in sources]

    def _worker() -> None:
        from .wb_kiz_circulation import get_wb_analytics_api_key

        errors: list[str] = []
        done = 0
        fatal = ""
        try:
            try:
                fallback_key = get_wb_analytics_api_key(repo, user_id=user_id)
            except Exception as exc:
                _log.warning("pvz returns analytics fallback key failed: %s", exc)
                fallback_key = None
            for index, source in enumerate(source_snapshot, start=1):
                source_id = int(source["id"])
                name = str(source.get("name") or f"Источник {source_id}")
                prefix = f"{index}/{len(source_snapshot)} {name}"
                src_full = repo.get_supply_source_with_key(user_id=user_id, source_id=source_id)
                if not src_full or not wb.is_wb_source(src_full):
                    errors.append(f"{name}: источник не найден")
                    _set_pvz_job(user_id, message=errors[-1], errors=list(errors))
                    continue
                source_api_key = str(src_full.get("api_key") or "").strip() or None
                source_analytics_key = str(src_full.get("analytics_api_key") or "").strip() or None
                try:
                    candidates, trust_report = resolve_goods_return_api_keys(
                        source_api_key=source_api_key,
                        source_analytics_api_key=source_analytics_key,
                        fallback_analytics_key=fallback_key,
                    )
                except RuntimeError as exc:
                    errors.append(f"{name}: {exc}")
                    _set_pvz_job(user_id, message=f"{prefix}: {exc}", errors=list(errors))
                    continue
                api_key, api_key_source = candidates[0]
                limited = goods_return_rate_limit_status(api_key=api_key)
                if limited.get("blocked"):
                    fatal = str(limited.get("message") or "Синхронизация временно недоступна")
                    _set_pvz_job(user_id, message=f"{prefix}: ожидание лимита WB…")
                    break
                wait = goods_return_token_cooldown_seconds(api_key=api_key)
                if wait > 0.5:
                    _set_pvz_job(user_id, message=f"{prefix}: ожидание лимита WB…")
                    time.sleep(wait)
                _set_pvz_job(user_id, message=f"{prefix}: загрузка возвратов WB…")
                try:
                    sync_goods_returns(
                        repo,
                        user_id=user_id,
                        source_id=source_id,
                        api_key=api_key,
                        date_from=wb_from,
                        date_to=wb_to,
                        marketplace_api_key=source_api_key,
                        api_key_source=api_key_source,
                        trust_report=trust_report,
                        api_key_candidates=candidates,
                        chunk_days=GOODS_RETURN_MAX_WINDOW_DAYS,
                    )
                except Exception as exc:
                    if _is_goods_return_rate_limit_error(exc):
                        fatal = str(exc) or "WB ограничил частоту запросов"
                        _set_pvz_job(user_id, message=f"{prefix}: ожидание лимита WB…")
                        break
                    _log.warning("pvz returns sync source %s failed: %s", source_id, exc)
                    errors.append(f"{name}: {exc}")
                    _set_pvz_job(user_id, message=f"{prefix}: {exc}", errors=list(errors))
                    continue
                done += 1
                _set_pvz_job(
                    user_id,
                    message=f"{prefix}: готово",
                    sources_done=done,
                    errors=list(errors),
                )
            if fatal:
                _set_pvz_job(
                    user_id,
                    status="error",
                    message=fatal,
                    errors=list(errors),
                    sources_done=done,
                    finished_at=datetime.now(UTC).isoformat(),
                )
                return
            message = "Готово" if not errors else "Готово с ошибками"
            _set_pvz_job(
                user_id,
                status="ok" if done or not errors else "error",
                message=message,
                errors=list(errors),
                sources_done=done,
                finished_at=datetime.now(UTC).isoformat(),
            )
        except Exception as exc:
            _log.exception("pvz returns sync failed user=%s", user_id)
            _set_pvz_job(
                user_id,
                status="error",
                message=str(exc) or "Синхронизация не удалась",
                errors=list(errors),
                sources_done=done,
                finished_at=datetime.now(UTC).isoformat(),
            )

    threading.Thread(
        target=_worker,
        name=f"wb-pvz-returns-{int(user_id)}",
        daemon=True,
    ).start()
    return {
        "ok": True,
        "async": True,
        "status": "running",
        "already_running": False,
        "message": "Запуск…",
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "wb_date_from": wb_from,
        "wb_date_to": wb_to,
    }
