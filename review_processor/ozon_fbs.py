"""Ozon FBS postings — isolated from Ozon FBO (supply-order) and WB FBS.

Uses api-seller.ozon.ru with Client-Id + Api-Key from supply_sources.

Source rule (same idea as WB FBS):
- marketplace=ozon and name contains «ФБС»/FBS, OR
- marketplace=ozon_fbs (legacy value kept for compatibility).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .repository import ReviewRepository

_log = logging.getLogger(__name__)

OZON_API = "https://api-seller.ozon.ru"

# UI tabs (portal-aligned)
TAB_AWAITING_PACKAGING = "awaiting_packaging"
TAB_AWAITING_DELIVER = "awaiting_deliver"
TAB_DELIVERING = "delivering"
TAB_ARBITRATION = "arbitration"
TAB_DELIVERED = "delivered"
TAB_CANCELLED = "cancelled"

TAB_LABELS: dict[str, str] = {
    TAB_AWAITING_PACKAGING: "Ожидают сборки",
    TAB_AWAITING_DELIVER: "Ожидают отгрузки",
    TAB_DELIVERING: "Доставляются",
    TAB_ARBITRATION: "Спорные",
    TAB_DELIVERED: "Доставлены",
    TAB_CANCELLED: "Отменены",
}

ALL_TABS = tuple(TAB_LABELS.keys())

_ARBITRATION_STATUSES = frozenset({"arbitration", "client_arbitration"})

SYNC_STATUSES = [
    "awaiting_packaging",
    "awaiting_deliver",
    "delivering",
    "arbitration",
    "client_arbitration",
    "delivered",
    "cancelled",
]

DEFAULT_LOOKBACK_DAYS = 30

_ozon_fbs_sync_lock = threading.Lock()
_ozon_fbs_sync_state: dict[str, object] = {
    "in_progress": False,
    "synced": 0,
    "total": 0,
    "message": "",
    "errors": [],
    "sources": [],
    "cancel_requested": False,
}


def is_fbs_source_name(name: object) -> bool:
    """True when supply source name is meant for FBS (contains ФБС/FBS)."""
    text = str(name or "").strip().lower()
    return "фбс" in text or "fbs" in text


def is_ozon_fbs_marketplace(marketplace: object) -> bool:
    """Legacy marketplace value used before name-based FBS detection."""
    return str(marketplace or "").strip().lower() == "ozon_fbs"


def is_ozon_fbs_source(source: Mapping[str, Any] | None) -> bool:
    """True for Ozon FBS cabinets: ozon+ФБС in name, or legacy marketplace=ozon_fbs."""
    if not source:
        return False
    mp = str(source.get("marketplace") or "").strip().lower()
    if mp == "ozon_fbs":
        return True
    if mp == "ozon" and is_fbs_source_name(source.get("name")):
        return True
    return False


def is_ozon_fbo_source(source: Mapping[str, Any] | None) -> bool:
    """True for Ozon FBO cabinets: marketplace=ozon without ФБС/FBS in the name."""
    if not source:
        return False
    mp = str(source.get("marketplace") or "").strip().lower()
    if mp != "ozon":
        return False
    return not is_fbs_source_name(source.get("name"))


def compute_tab(status: object) -> str:
    s = str(status or "").strip().lower()
    if s in _ARBITRATION_STATUSES:
        return TAB_ARBITRATION
    if s == TAB_AWAITING_PACKAGING:
        return TAB_AWAITING_PACKAGING
    if s == TAB_AWAITING_DELIVER:
        return TAB_AWAITING_DELIVER
    if s == TAB_DELIVERING:
        return TAB_DELIVERING
    if s == TAB_DELIVERED:
        return TAB_DELIVERED
    if s == TAB_CANCELLED:
        return TAB_CANCELLED
    return TAB_AWAITING_PACKAGING


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _iso_z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


class OzonFbsClient:
    def __init__(self, client_id: str, api_key: str, timeout: int = 45) -> None:
        self.client_id = str(client_id or "").strip()
        self.api_key = str(api_key or "").strip()
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "FeedPilot-OzonFBS/1.0",
        }

    def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{OZON_API}{path}"
        payload = json.dumps(body).encode("utf-8")
        req = Request(url, data=payload, method="POST", headers=self._headers())
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ozon HTTP {exc.code}: {err_body or exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"Ozon network error: {exc.reason}") from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ozon API returned non-JSON response") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Ozon API response must be a JSON object")
        return data

    def post_bytes(self, path: str, body: dict[str, Any]) -> bytes:
        url = f"{OZON_API}{path}"
        payload = json.dumps(body).encode("utf-8")
        req = Request(url, data=payload, method="POST", headers=self._headers())
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ozon HTTP {exc.code}: {err_body or exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"Ozon network error: {exc.reason}") from exc

    def list_postings_page(
        self,
        *,
        status: str,
        since: datetime,
        to: datetime,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], bool]:
        body = {
            "dir": "ASC",
            "filter": {
                "since": _iso_z(since),
                "to": _iso_z(to),
                "status": status,
            },
            "limit": min(max(limit, 1), 1000),
            "offset": max(offset, 0),
            "with": {
                "analytics_data": True,
                "barcodes": True,
                "financial_data": True,
                "translit": True,
            },
        }
        data = self.post_json("/v3/posting/fbs/list", body)
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        postings = result.get("postings") if isinstance(result.get("postings"), list) else []
        has_next = bool(result.get("has_next"))
        clean = [p for p in postings if isinstance(p, dict)]
        return clean, has_next

    def get_posting(self, posting_number: str) -> dict[str, Any]:
        data = self.post_json(
            "/v3/posting/fbs/get",
            {
                "posting_number": str(posting_number),
                "with": {
                    "analytics_data": True,
                    "barcodes": True,
                    "financial_data": True,
                    "translit": True,
                },
            },
        )
        result = data.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Ozon get posting: empty result")
        return result

    def ship_posting(self, posting_number: str, packages: list[dict[str, Any]]) -> dict[str, Any]:
        return self.post_json(
            "/v4/posting/fbs/ship",
            {"posting_number": str(posting_number), "packages": packages},
        )

    def package_label_pdf(self, posting_numbers: list[str]) -> bytes:
        return self.post_bytes(
            "/v2/posting/fbs/package-label",
            {"posting_number": [str(p) for p in posting_numbers if str(p).strip()]},
        )


def ensure_ozon_fbs_tables(repo: ReviewRepository) -> None:
    with repo._connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ozon_fbs_postings (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                user_id BIGINT NOT NULL,
                source_id BIGINT NOT NULL,
                posting_number TEXT NOT NULL,
                order_id BIGINT,
                order_number TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                tab TEXT NOT NULL DEFAULT 'awaiting_packaging',
                offer_id TEXT NOT NULL DEFAULT '',
                product_name TEXT NOT NULL DEFAULT '',
                sku BIGINT,
                quantity INTEGER NOT NULL DEFAULT 1,
                price BIGINT NOT NULL DEFAULT 0,
                warehouse_name TEXT NOT NULL DEFAULT '',
                warehouse_id BIGINT,
                barcodes_json TEXT NOT NULL DEFAULT '[]',
                products_json TEXT NOT NULL DEFAULT '[]',
                is_mandatory_mark BOOLEAN NOT NULL DEFAULT FALSE,
                created_at_ozon TIMESTAMPTZ,
                in_process_at TIMESTAMPTZ,
                raw_json TEXT NOT NULL DEFAULT '{}',
                synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (user_id, source_id, posting_number)
            )
            """
        )
        conn.execute(
            repo._sql(
                "CREATE INDEX IF NOT EXISTS idx_ozon_fbs_postings_user_src_tab "
                "ON ozon_fbs_postings(user_id, source_id, tab, created_at_ozon DESC)"
            )
        )


def _parse_dt(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).isoformat()
    except ValueError:
        return text


def _products_from_posting(posting: dict[str, Any]) -> list[dict[str, Any]]:
    products = posting.get("products")
    if not isinstance(products, list):
        return []
    out: list[dict[str, Any]] = []
    for item in products:
        if isinstance(item, dict):
            out.append(item)
    return out


def _mandatory_mark(posting: dict[str, Any], products: list[dict[str, Any]]) -> bool:
    req = posting.get("requirements")
    if isinstance(req, dict):
        marks = req.get("products_requiring_mandatory_mark")
        if isinstance(marks, list) and marks:
            return True
    for p in products:
        if bool(p.get("is_marketplace_buyout")):
            continue
        if bool(p.get("mandatory_mark")):
            return True
    return False


def _barcodes_from_posting(posting: dict[str, Any], products: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    barcodes = posting.get("barcodes")
    if isinstance(barcodes, dict):
        for key in ("upper_barcode", "lower_barcode"):
            text = str(barcodes.get(key) or "").strip()
            if text and text not in out:
                out.append(text)
    for p in products:
        for key in ("sku", "offer_id"):
            text = str(p.get(key) or "").strip()
            if text and text not in out:
                out.append(text)
    return out


def upsert_posting(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    posting: dict[str, Any],
) -> None:
    ensure_ozon_fbs_tables(repo)
    posting_number = str(posting.get("posting_number") or "").strip()
    if not posting_number:
        return
    status = str(posting.get("status") or "").strip().lower()
    tab = compute_tab(status)
    products = _products_from_posting(posting)
    first = products[0] if products else {}
    offer_id = str(first.get("offer_id") or "").strip()
    product_name = str(first.get("name") or "").strip()
    if len(products) > 1:
        product_name = f"{product_name or offer_id or 'Товар'} (+{len(products) - 1})"
    sku_raw = first.get("sku")
    sku: int | None = None
    try:
        if sku_raw is not None:
            sku = int(sku_raw)
    except (TypeError, ValueError):
        sku = None
    qty = 0
    for p in products:
        try:
            qty += int(p.get("quantity") or 0)
        except (TypeError, ValueError):
            qty += 1
    if qty <= 0:
        qty = 1
    price = 0
    fin = posting.get("financial_data")
    if isinstance(fin, dict):
        fin_products = fin.get("products")
        if isinstance(fin_products, list) and fin_products:
            fp = fin_products[0]
            if isinstance(fp, dict):
                try:
                    price = int(float(fp.get("price") or 0))
                except (TypeError, ValueError):
                    price = 0
    analytics = posting.get("analytics_data")
    warehouse_name = ""
    warehouse_id: int | None = None
    if isinstance(analytics, dict):
        warehouse_name = str(analytics.get("warehouse") or "").strip()
        try:
            if analytics.get("warehouse_id") is not None:
                warehouse_id = int(analytics.get("warehouse_id"))
        except (TypeError, ValueError):
            warehouse_id = None
    order_id: int | None = None
    try:
        if posting.get("order_id") is not None:
            order_id = int(posting.get("order_id"))
    except (TypeError, ValueError):
        order_id = None
    order_number = str(posting.get("order_number") or "").strip()
    barcodes = _barcodes_from_posting(posting, products)
    mandatory = _mandatory_mark(posting, products)
    raw_json = json.dumps(posting, ensure_ascii=False)
    products_json = json.dumps(products, ensure_ascii=False)
    barcodes_json = json.dumps(barcodes, ensure_ascii=False)
    created_at = _parse_dt(posting.get("in_process_at") or posting.get("created_at"))
    in_process_at = _parse_dt(posting.get("in_process_at"))
    with repo._connect() as conn:
        conn.execute(
            repo._sql(
                """
                INSERT INTO ozon_fbs_postings (
                    user_id, source_id, posting_number, order_id, order_number,
                    status, tab, offer_id, product_name, sku, quantity, price,
                    warehouse_name, warehouse_id, barcodes_json, products_json,
                    is_mandatory_mark, created_at_ozon, in_process_at, raw_json, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (user_id, source_id, posting_number) DO UPDATE SET
                    order_id = EXCLUDED.order_id,
                    order_number = EXCLUDED.order_number,
                    status = EXCLUDED.status,
                    tab = EXCLUDED.tab,
                    offer_id = EXCLUDED.offer_id,
                    product_name = EXCLUDED.product_name,
                    sku = EXCLUDED.sku,
                    quantity = EXCLUDED.quantity,
                    price = EXCLUDED.price,
                    warehouse_name = EXCLUDED.warehouse_name,
                    warehouse_id = EXCLUDED.warehouse_id,
                    barcodes_json = EXCLUDED.barcodes_json,
                    products_json = EXCLUDED.products_json,
                    is_mandatory_mark = EXCLUDED.is_mandatory_mark,
                    created_at_ozon = EXCLUDED.created_at_ozon,
                    in_process_at = EXCLUDED.in_process_at,
                    raw_json = EXCLUDED.raw_json,
                    synced_at = EXCLUDED.synced_at
                """
            ),
            (
                user_id,
                source_id,
                posting_number,
                order_id,
                order_number,
                status,
                tab,
                offer_id,
                product_name,
                sku,
                qty,
                price,
                warehouse_name,
                warehouse_id,
                barcodes_json,
                products_json,
                repo._bool_db(mandatory),
                created_at,
                in_process_at,
                raw_json,
                _utc_now(),
            ),
        )


def _tab_counts(repo: ReviewRepository, *, user_id: int, source_id: int | None) -> dict[str, int]:
    ensure_ozon_fbs_tables(repo)
    clauses = ["user_id = ?"]
    params: list[Any] = [user_id]
    if source_id is not None:
        clauses.append("source_id = ?")
        params.append(source_id)
    where = " AND ".join(clauses)
    counts = {tab: 0 for tab in ALL_TABS}
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(f"SELECT tab, COUNT(*) AS n FROM ozon_fbs_postings WHERE {where} GROUP BY tab"),
            tuple(params),
        ).fetchall()
    for row in rows:
        tab = str(row["tab"] or "")
        if tab in counts:
            counts[tab] = int(row["n"] or 0)
    return counts


def _postings_filter_sql(
    *,
    user_id: int,
    source_id: int | None,
    tab: str | None,
    search: str | None,
) -> tuple[str, list[Any]]:
    clauses = ["user_id = ?"]
    params: list[Any] = [user_id]
    if source_id is not None:
        clauses.append("source_id = ?")
        params.append(source_id)
    tab_key = str(tab or "").strip().lower()
    if tab_key:
        if tab_key == TAB_ARBITRATION:
            clauses.append("tab = ?")
            params.append(TAB_ARBITRATION)
        else:
            clauses.append("tab = ?")
            params.append(tab_key)
    q = str(search or "").strip()
    if q:
        like = f"%{q}%"
        clauses.append(
            "(posting_number ILIKE ? OR order_number ILIKE ? OR offer_id ILIKE ? "
            "OR product_name ILIKE ? OR warehouse_name ILIKE ? OR barcodes_json ILIKE ?)"
        )
        params.extend([like, like, like, like, like, like])
    return " AND ".join(clauses), params


def list_postings(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int | None,
    tab: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    ensure_ozon_fbs_tables(repo)
    where, params = _postings_filter_sql(
        user_id=user_id, source_id=source_id, tab=tab, search=search
    )
    safe_page = max(int(page), 1)
    safe_size = min(max(int(page_size), 1), 200)
    offset = (safe_page - 1) * safe_size
    with repo._connect() as conn:
        total_row = conn.execute(
            repo._sql(f"SELECT COUNT(*) AS n FROM ozon_fbs_postings WHERE {where}"),
            tuple(params),
        ).fetchone()
        rows = conn.execute(
            repo._sql(
                f"""
                SELECT * FROM ozon_fbs_postings
                WHERE {where}
                ORDER BY created_at_ozon DESC NULLS LAST, posting_number DESC
                LIMIT ? OFFSET ?
                """
            ),
            tuple(params + [safe_size, offset]),
        ).fetchall()
    name_map = repo.get_product_name_by_article(user_id=user_id)
    photo_map = repo.get_product_photo_map(user_id=user_id)
    items: list[dict[str, Any]] = []
    for row in rows:
        d = repo._row_to_dict(row)
        article = str(d.get("offer_id") or "").strip()
        sku = str(d.get("sku") or "").strip()
        d["product_name_display"] = name_map.get(article) or d.get("product_name") or article or "—"
        d["product_photo"] = photo_map.get(article) or photo_map.get(sku) or ""
        d["tab_label"] = TAB_LABELS.get(str(d.get("tab") or ""), str(d.get("tab") or ""))
        d["status_label"] = str(d.get("status") or "")
        try:
            barcodes = json.loads(d.get("barcodes_json") or "[]")
        except json.JSONDecodeError:
            barcodes = []
        d["barcodes"] = barcodes if isinstance(barcodes, list) else []
        try:
            price = int(d.get("price") or 0)
        except (TypeError, ValueError):
            price = 0
        d["price_display"] = f"{price:,}".replace(",", " ") + " ₽" if price else "—"
        d["warehouse_label"] = str(d.get("warehouse_name") or "").strip() or "—"
        items.append(d)
    return {
        "items": items,
        "total": int(total_row["n"]) if total_row else 0,
        "page": safe_page,
        "page_size": safe_size,
        "counts": _tab_counts(repo, user_id=user_id, source_id=source_id),
    }


def sync_ozon_fbs_source(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    client_id: str,
    api_key: str,
    stop_requested: Callable[[], bool] | None = None,
    progress: Callable[[str, int], None] | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    ensure_ozon_fbs_tables(repo)
    client = OzonFbsClient(client_id, api_key)
    stopped = False
    seen: set[str] = set()
    errors: list[str] = []

    def _stopped() -> bool:
        return bool(stop_requested and stop_requested())

    def _prog(msg: str) -> None:
        if progress:
            progress(msg, len(seen))

    date_to = datetime.now(UTC)
    date_from = date_to - timedelta(days=max(1, min(int(lookback_days), 90)))

    for status in SYNC_STATUSES:
        if _stopped():
            stopped = True
            break
        label = TAB_LABELS.get(compute_tab(status), status)
        offset = 0
        pages = 0
        while pages < 200:
            if _stopped():
                stopped = True
                break
            try:
                postings, has_next = client.list_postings_page(
                    status=status,
                    since=date_from,
                    to=date_to,
                    limit=50,
                    offset=offset,
                )
            except Exception as exc:
                _log.warning("ozon_fbs list %s failed: %s", status, exc)
                errors.append(f"{label}: {exc}")
                break
            if not postings:
                break
            for posting in postings:
                pn = str(posting.get("posting_number") or "").strip()
                if not pn:
                    continue
                upsert_posting(repo, user_id=user_id, source_id=source_id, posting=posting)
                seen.add(pn)
            pages += 1
            _prog(f"{label}… стр. {pages}")
            if not has_next:
                break
            offset += len(postings)
            time.sleep(0.25)
        time.sleep(0.15)

    repo.mark_supply_source_synced(source_id=source_id)
    return {
        "postings": len(seen),
        "errors": errors,
        "stopped": stopped,
    }


def get_sync_state() -> dict[str, object]:
    with _ozon_fbs_sync_lock:
        return dict(_ozon_fbs_sync_state)


def request_sync_stop() -> bool:
    with _ozon_fbs_sync_lock:
        if _ozon_fbs_sync_state.get("in_progress"):
            _ozon_fbs_sync_state["cancel_requested"] = True
            return True
    return False


def _copy_sync_state() -> dict[str, object]:
    with _ozon_fbs_sync_lock:
        return dict(_ozon_fbs_sync_state)


def start_sync_thread(
    *,
    repo: ReviewRepository,
    user_id: int,
    sources: list[dict[str, Any]],
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> tuple[bool, str]:
    jobs: list[dict[str, Any]] = []
    for raw in sources:
        try:
            sid = int(raw.get("source_id") if "source_id" in raw else raw.get("id"))
        except (TypeError, ValueError):
            continue
        client_id = str(raw.get("client_id") or "").strip()
        api_key = str(raw.get("api_key") or "").strip()
        if not client_id or not api_key:
            continue
        jobs.append(
            {
                "source_id": sid,
                "client_id": client_id,
                "api_key": api_key,
                "name": str(raw.get("name") or f"Источник {sid}"),
            }
        )
    if not jobs:
        return False, "Нет активных источников OZON ФБС с Client-Id и Api-Key"

    source_rows = [
        {
            "source_id": int(j["source_id"]),
            "name": str(j["name"]),
            "status": "pending",
            "message": "Ожидание…",
            "postings": 0,
        }
        for j in jobs
    ]

    with _ozon_fbs_sync_lock:
        if _ozon_fbs_sync_state.get("in_progress"):
            return False, "Синхронизация уже запущена"
        _ozon_fbs_sync_state.update(
            {
                "in_progress": True,
                "synced": 0,
                "total": len(jobs),
                "message": f"Запуск… источников: {len(jobs)}",
                "errors": [],
                "sources": source_rows,
                "cancel_requested": False,
            }
        )

    def _run() -> None:
        errors: list[str] = []
        try:
            for idx, job in enumerate(jobs):
                with _ozon_fbs_sync_lock:
                    if _ozon_fbs_sync_state.get("cancel_requested"):
                        _ozon_fbs_sync_state["message"] = "Остановка…"
                        break
                    row = _ozon_fbs_sync_state["sources"][idx]
                    row["status"] = "running"
                    row["message"] = "Синхронизация…"

                def _progress(msg: str, n: int) -> None:
                    with _ozon_fbs_sync_lock:
                        row = _ozon_fbs_sync_state["sources"][idx]
                        row["message"] = msg
                        row["postings"] = n

                def _stop() -> bool:
                    with _ozon_fbs_sync_lock:
                        return bool(_ozon_fbs_sync_state.get("cancel_requested"))

                try:
                    result = sync_ozon_fbs_source(
                        repo,
                        user_id=user_id,
                        source_id=int(job["source_id"]),
                        client_id=str(job["client_id"]),
                        api_key=str(job["api_key"]),
                        stop_requested=_stop,
                        progress=_progress,
                        lookback_days=lookback_days,
                    )
                    with _ozon_fbs_sync_lock:
                        row = _ozon_fbs_sync_state["sources"][idx]
                        row["status"] = "done" if not result.get("stopped") else "stopped"
                        row["postings"] = int(result.get("postings") or 0)
                        row["message"] = (
                            f"Готово: {row['postings']} отправлений"
                            if not result.get("stopped")
                            else "Остановлено"
                        )
                        for err in result.get("errors") or []:
                            if isinstance(err, str) and err:
                                errors.append(f"{job['name']}: {err}")
                except Exception as exc:
                    _log.exception("ozon_fbs sync source %s failed", job.get("source_id"))
                    with _ozon_fbs_sync_lock:
                        row = _ozon_fbs_sync_state["sources"][idx]
                        row["status"] = "error"
                        row["message"] = str(exc)
                    errors.append(f"{job['name']}: {exc}")

                with _ozon_fbs_sync_lock:
                    _ozon_fbs_sync_state["synced"] = idx + 1
        finally:
            with _ozon_fbs_sync_lock:
                _ozon_fbs_sync_state["in_progress"] = False
                _ozon_fbs_sync_state["errors"] = errors
                if _ozon_fbs_sync_state.get("cancel_requested"):
                    _ozon_fbs_sync_state["message"] = "Синхронизация остановлена"
                elif errors:
                    _ozon_fbs_sync_state["message"] = "Синхронизация завершена с ошибками"
                else:
                    _ozon_fbs_sync_state["message"] = "Синхронизация завершена"

    threading.Thread(target=_run, name="ozon-fbs-sync", daemon=True).start()
    return True, f"Синхронизация запущена ({len(jobs)} источников)"


def list_fbs_sync_jobs(repo: ReviewRepository, *, user_id: int) -> list[dict[str, Any]]:
    """Build sync jobs for enabled Ozon FBS sources (name ФБС or legacy ozon_fbs)."""
    jobs: list[dict[str, Any]] = []
    for s in repo.list_supply_sources(user_id=user_id):
        if not s.get("is_enabled"):
            continue
        if not is_ozon_fbs_source(s):
            continue
        src_full = repo.get_supply_source_with_key(user_id=user_id, source_id=int(s["id"]))
        if not src_full:
            continue
        client_id = str(src_full.get("client_id") or "").strip()
        api_key = str(src_full.get("api_key") or "").strip()
        if not client_id or not api_key:
            continue
        jobs.append(
            {
                "source_id": int(s["id"]),
                "name": str(s.get("name") or ""),
                "client_id": client_id,
                "api_key": api_key,
            }
        )
    return jobs
