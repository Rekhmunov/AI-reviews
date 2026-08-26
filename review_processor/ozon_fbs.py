"""Ozon FBS postings — isolated from Ozon FBO (supply-order) and WB FBS.

Uses api-seller.ozon.ru with Client-Id + Api-Key from supply_sources.

Source rule (same idea as WB FBS):
- marketplace=ozon and name contains «ФБС»/FBS, OR
- marketplace=ozon_fbs (legacy value kept for compatibility).
"""
from __future__ import annotations

import base64
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
    "pallet_summary": [],
    "pallet_summary_error": "",
    "cancel_requested": False,
}

_PALLET_SUMMARY_ERROR = (
    "Не удалось рассчитать паллеты после синхронизации. "
    "Проверьте кратность короба и категории товаров (Настройки → Товары)."
)


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


_CANCELLED_STATUSES = frozenset(
    {
        TAB_CANCELLED,
        "cancelled_from_split_pending",
    }
)

_CANCEL_REASON_ID_LABELS: dict[int, str] = {
    352: "Товара нет в наличии",
    400: "Остался только бракованный товар",
    401: "Отмена из арбитража",
    402: "Другая причина",
    665: "Покупатель не забрал заказ",
    666: "Нет доставки в регион",
    667: "Заказ утерян службой доставки",
}

_CANCELLATION_TYPE_LABELS: dict[str, str] = {
    "client": "Отмена покупателем",
    "seller": "Отмена продавцом",
    "ozon": "Отмена Ozon",
    "customer": "Отмена покупателем",
    "buyer": "Отмена покупателем",
}


def is_cancelled_posting(*, status: object = "", tab: object = "") -> bool:
    s = str(status or "").strip().lower()
    t = str(tab or "").strip().lower()
    if t == TAB_CANCELLED:
        return True
    return s in _CANCELLED_STATUSES


def cancel_reason_label_from_posting(posting: dict[str, Any]) -> str:
    """Human-readable cancel reason from Ozon posting payload."""
    if not isinstance(posting, dict):
        return ""
    status = str(posting.get("status") or "").strip().lower()
    if not is_cancelled_posting(status=status, tab=compute_tab(status)):
        return ""
    cancellation = posting.get("cancellation")
    if isinstance(cancellation, dict):
        for key in ("cancel_reason", "cancel_reason_message", "reason"):
            text = str(cancellation.get(key) or "").strip()
            if text:
                return text
        try:
            rid = int(cancellation.get("cancel_reason_id") or 0)
        except (TypeError, ValueError):
            rid = 0
        if rid in _CANCEL_REASON_ID_LABELS:
            return _CANCEL_REASON_ID_LABELS[rid]
        ctype = str(
            cancellation.get("cancellation_type")
            or cancellation.get("cancel_type")
            or ""
        ).strip().lower()
        if ctype in _CANCELLATION_TYPE_LABELS:
            return _CANCELLATION_TYPE_LABELS[ctype]
    if status == "cancelled_from_split_pending":
        return "Отменено при разделении"
    return "Отменено"


def cancel_reason_label_from_row(row: dict[str, Any]) -> str:
    """Cancel label from local DB row (status/tab + optional raw_json)."""
    if not isinstance(row, dict):
        return ""
    status = str(row.get("status") or "").strip().lower()
    tab = str(row.get("tab") or "").strip().lower()
    if not is_cancelled_posting(status=status, tab=tab):
        return ""
    raw_text = str(row.get("raw_json") or "").strip()
    if raw_text:
        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError:
            raw = None
        if isinstance(raw, dict):
            label = cancel_reason_label_from_posting(raw)
            if label:
                return label
    return "Отменено"


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

    def delivery_method_list(
        self,
        *,
        warehouse_id: int | None = None,
        status: str = "ACTIVE",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        del status  # v2 rejects string status filters; v1 is obsolete (Apr 2026).
        filt: dict[str, Any] = {}
        if warehouse_id is not None:
            filt["warehouse_id"] = int(warehouse_id)
        body = {
            "filter": filt,
            "limit": min(max(int(limit), 1), 50),
            "offset": max(int(offset), 0),
        }
        return self.post_json("/v2/delivery-method/list", body)

    def carriage_delivery_list(
        self, *, delivery_method_id: int, departure_date: str, limit: int = 100
    ) -> dict[str, Any]:
        dep = str(departure_date or "").strip()
        if "T" in dep:
            dep = dep.split("T", 1)[0]
        body = {
            "delivery_method_id": int(delivery_method_id),
            "departure_date": dep,
            "limit": min(max(int(limit), 1), 1000),
        }
        return self.post_json("/v2/carriage/delivery/list", body)

    def fbs_act_create(
        self,
        *,
        delivery_method_id: int,
        departure_date: str | None = None,
        containers_count: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"delivery_method_id": int(delivery_method_id)}
        if departure_date:
            body["departure_date"] = str(departure_date)
        if containers_count is not None:
            body["containers_count"] = int(containers_count)
        return self.post_json("/v2/posting/fbs/act/create", body)

    def fbs_act_check_status(self, *, act_id: int) -> dict[str, Any]:
        return self.post_json("/v2/posting/fbs/act/check-status", {"id": int(act_id)})

    def fbs_act_get_barcode(self, *, carriage_id: int) -> dict[str, Any]:
        raw = self.post_bytes(
            "/v2/posting/fbs/act/get-barcode", {"id": int(carriage_id)}
        )
        try:
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, dict):
                return data
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        return {
            "file_content": base64.b64encode(raw).decode("ascii"),
            "content_type": "image/png",
        }

    def fbs_act_get_barcode_text(self, *, carriage_id: int) -> dict[str, Any]:
        return self.post_json(
            "/v2/posting/fbs/act/get-barcode/text", {"id": int(carriage_id)}
        )

    def product_exemplar_create_or_get(
        self, posting_number: str, products: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return self.post_json(
            "/v6/fbs/posting/product/exemplar/create-or-get",
            {
                "posting_number": str(posting_number),
                "products": products,
            },
        )

    def product_exemplar_set(
        self,
        posting_number: str,
        *,
        multi_box_qty: int = 1,
        products: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self.post_json(
            "/v6/fbs/posting/product/exemplar/set",
            {
                "posting_number": str(posting_number),
                "multi_box_qty": max(int(multi_box_qty), 1),
                "products": products,
            },
        )

    def product_exemplar_validate(
        self, posting_number: str, products: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return self.post_json(
            "/v5/fbs/posting/product/exemplar/validate",
            {
                "posting_number": str(posting_number),
                "products": products,
            },
        )

    def product_exemplar_status(self, posting_number: str) -> dict[str, Any]:
        return self.post_json(
            "/v5/fbs/posting/product/exemplar/status",
            {"posting_number": str(posting_number)},
        )

    def product_exemplar_create_or_get_v5(
        self, posting_number: str, products: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return self.post_json(
            "/v5/fbs/posting/product/exemplar/create-or-get",
            {
                "posting_number": str(posting_number),
                "products": products,
            },
        )

    def mandatory_mark_is_required(
        self, posting_number: str, skus: list[int]
    ) -> list[dict[str, Any]]:
        """POST /v2/posting/fbs/product/mandatory-mark/is-required per SKU."""
        clean = []
        for sku in skus:
            try:
                clean.append(int(sku))
            except (TypeError, ValueError):
                continue
        if not clean:
            return []
        data = self.post_json(
            "/v2/posting/fbs/product/mandatory-mark/is-required",
            {
                "posting_number": str(posting_number),
                "sku": clean,
            },
        )
        result = data.get("result")
        if isinstance(result, list):
            return [x for x in result if isinstance(x, dict)]
        return []

_OZON_LABEL_BATCH = 20


def fetch_merged_package_label_pdf(
    client: OzonFbsClient, posting_numbers: list[str]
) -> bytes:
    """Fetch Ozon package labels (≤20 per API call) and merge into one PDF."""
    nums = [str(p).strip() for p in posting_numbers if str(p).strip()]
    if not nums:
        raise RuntimeError("Не указаны отправления для печати")
    if len(nums) == 1:
        return client.package_label_pdf(nums)
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError(
            "Для печати стикеров Ozon нужен пакет pymupdf "
            "(pip install pymupdf). Сейчас он не установлен на сервере."
        ) from exc

    merged = pymupdf.open()
    errors: list[str] = []
    try:
        for i in range(0, len(nums), _OZON_LABEL_BATCH):
            batch = nums[i : i + _OZON_LABEL_BATCH]
            try:
                pdf_bytes = client.package_label_pdf(batch)
                src = pymupdf.open(stream=pdf_bytes, filetype="pdf")
                merged.insert_pdf(src)
                src.close()
            except Exception as exc:
                if isinstance(exc, ImportError) or "pymupdf" in str(exc).casefold():
                    raise
                for pn in batch:
                    try:
                        pdf_one = client.package_label_pdf([pn])
                        src = pymupdf.open(stream=pdf_one, filetype="pdf")
                        merged.insert_pdf(src)
                        src.close()
                    except Exception as exc_one:
                        if isinstance(exc_one, ImportError) or "pymupdf" in str(exc_one).casefold():
                            raise
                        err_text = str(exc_one).strip() or "ошибка Ozon"
                        errors.append(f"{pn}: {err_text}")
        if merged.page_count == 0:
            if errors:
                raise RuntimeError(errors[0])
            raise RuntimeError(
                "Не удалось получить этикетки Ozon. "
                "Проверьте, что отправления собраны и этикетки доступны."
            )
        return merged.tobytes()
    finally:
        merged.close()


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
        for ddl in (
            "ALTER TABLE ozon_fbs_postings ADD COLUMN IF NOT EXISTS marking_codes_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE ozon_fbs_postings ADD COLUMN IF NOT EXISTS marking_saved_at TIMESTAMPTZ",
            "ALTER TABLE ozon_fbs_postings ADD COLUMN IF NOT EXISTS marking_ozon_synced BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE ozon_fbs_postings ADD COLUMN IF NOT EXISTS pick_verified BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE ozon_fbs_postings ADD COLUMN IF NOT EXISTS pick_barcode TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE ozon_fbs_postings ADD COLUMN IF NOT EXISTS pick_verified_at TIMESTAMPTZ",
            "ALTER TABLE ozon_fbs_postings ADD COLUMN IF NOT EXISTS sticker_barcode TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE ozon_fbs_postings ADD COLUMN IF NOT EXISTS sticker_part_a TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE ozon_fbs_postings ADD COLUMN IF NOT EXISTS sticker_part_b TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE ozon_fbs_postings ADD COLUMN IF NOT EXISTS sticker_scanned_at TIMESTAMPTZ",
        ):
            try:
                conn.execute(ddl)
            except Exception:
                pass
        for idx_sql in (
            repo._sql(
                "CREATE INDEX IF NOT EXISTS idx_ozon_fbs_postings_sticker_barcode "
                "ON ozon_fbs_postings(user_id, source_id, sticker_barcode) "
                "WHERE sticker_barcode <> ''"
            ),
            repo._sql(
                "CREATE INDEX IF NOT EXISTS idx_ozon_fbs_postings_sticker_part_b "
                "ON ozon_fbs_postings(user_id, source_id, sticker_part_b) "
                "WHERE sticker_part_b <> ''"
            ),
            repo._sql(
                "CREATE INDEX IF NOT EXISTS idx_ozon_fbs_postings_posting_number "
                "ON ozon_fbs_postings(user_id, source_id, posting_number)"
            ),
        ):
            try:
                conn.execute(idx_sql)
            except Exception:
                pass


def sticker_parts_from_posting_number(posting_number: object) -> tuple[str, str]:
    """Split Ozon posting_number into sticker-style parts (order segment + suffix)."""
    pn = str(posting_number or "").strip()
    if not pn or "-" not in pn:
        return pn, ""
    head, tail = pn.split("-", 1)
    return str(head or "").strip(), str(tail or "").strip()


def sticker_fields_from_posting(posting: dict[str, Any]) -> dict[str, str]:
    """Derive sticker binding fields from Ozon posting payload (non-destructive hints)."""
    pn = str(posting.get("posting_number") or "").strip()
    part_a, part_b = sticker_parts_from_posting_number(pn)
    barcode = ""
    barcodes = posting.get("barcodes")
    if isinstance(barcodes, dict):
        barcode = str(
            barcodes.get("upper_barcode") or barcodes.get("lower_barcode") or ""
        ).strip()
    return {
        "sticker_barcode": barcode,
        "sticker_part_a": part_a,
        "sticker_part_b": part_b,
    }


def posting_sticker_payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Sticker + order linkage fields for API payloads."""
    pn = str(row.get("posting_number") or "").strip()
    part_a = str(row.get("sticker_part_a") or "").strip()
    part_b = str(row.get("sticker_part_b") or "").strip()
    if not part_a and pn:
        part_a, part_b = sticker_parts_from_posting_number(pn)
    return {
        "posting_number": pn,
        "order_id": row.get("order_id"),
        "order_number": str(row.get("order_number") or "").strip(),
        "sticker_barcode": str(row.get("sticker_barcode") or "").strip(),
        "sticker_part_a": part_a,
        "sticker_part_b": part_b,
    }


def load_posting_sticker_map(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    posting_numbers: list[str],
) -> dict[str, dict[str, Any]]:
    nums = [str(x).strip() for x in posting_numbers if str(x).strip()]
    if not nums:
        return {}
    ensure_ozon_fbs_tables(repo)
    placeholders = ", ".join("?" for _ in nums)
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                f"""
                SELECT posting_number, order_id, order_number,
                       sticker_barcode, sticker_part_a, sticker_part_b
                FROM ozon_fbs_postings
                WHERE user_id = ? AND source_id = ?
                  AND posting_number IN ({placeholders})
                """
            ),
            (user_id, source_id, *nums),
        ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        d = repo._row_to_dict(row)
        pn = str(d.get("posting_number") or "").strip()
        if pn:
            out[pn] = posting_sticker_payload_from_row(d)
    return out


def persist_posting_stickers_batch(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    stickers: dict[str, dict[str, Any]],
    only_if_empty: bool = False,
    set_scanned_at: bool = False,
) -> int:
    """Persist sticker scan / Ozon label binding on ``ozon_fbs_postings`` by posting_number."""
    if not stickers:
        return 0
    ensure_ozon_fbs_tables(repo)
    updated = 0
    scanned_at_sql = "NOW()" if set_scanned_at else "sticker_scanned_at"
    with repo._connect() as conn:
        for pn_raw, st in stickers.items():
            if not isinstance(st, dict):
                continue
            pn = str(pn_raw or st.get("posting_number") or "").strip()
            if not pn:
                continue
            barcode = str(
                st.get("sticker_barcode") or st.get("barcode") or ""
            ).strip()
            part_a = str(st.get("sticker_part_a") or st.get("partA") or "").strip()
            part_b = str(st.get("sticker_part_b") or st.get("partB") or "").strip()
            if not part_a and not part_b:
                hint_a, hint_b = sticker_parts_from_posting_number(pn)
                if not part_a:
                    part_a = hint_a
                if not part_b:
                    part_b = hint_b
            if not (barcode or part_a or part_b):
                continue
            if only_if_empty:
                cur = conn.execute(
                    repo._sql(
                        """
                        UPDATE ozon_fbs_postings
                        SET sticker_barcode = CASE
                                WHEN sticker_barcode = '' AND ? <> '' THEN ?
                                ELSE sticker_barcode
                            END,
                            sticker_part_a = CASE
                                WHEN sticker_part_a = '' AND ? <> '' THEN ?
                                ELSE sticker_part_a
                            END,
                            sticker_part_b = CASE
                                WHEN sticker_part_b = '' AND ? <> '' THEN ?
                                ELSE sticker_part_b
                            END
                        WHERE user_id = ? AND source_id = ? AND posting_number = ?
                        """
                    ),
                    (
                        barcode,
                        barcode,
                        part_a,
                        part_a,
                        part_b,
                        part_b,
                        int(user_id),
                        int(source_id),
                        pn,
                    ),
                )
            else:
                cur = conn.execute(
                    repo._sql(
                        f"""
                        UPDATE ozon_fbs_postings
                        SET sticker_barcode = CASE
                                WHEN ? <> '' THEN ?
                                ELSE sticker_barcode
                            END,
                            sticker_part_a = CASE
                                WHEN ? <> '' THEN ?
                                ELSE sticker_part_a
                            END,
                            sticker_part_b = CASE
                                WHEN ? <> '' THEN ?
                                ELSE sticker_part_b
                            END,
                            sticker_scanned_at = {scanned_at_sql}
                        WHERE user_id = ? AND source_id = ? AND posting_number = ?
                        """
                    ),
                    (
                        barcode,
                        barcode,
                        part_a,
                        part_a,
                        part_b,
                        part_b,
                        int(user_id),
                        int(source_id),
                        pn,
                    ),
                )
            try:
                updated += int(cur.rowcount or 0)
            except (TypeError, ValueError, AttributeError):
                pass
    return updated


def apply_posting_sticker_hints(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    posting: dict[str, Any],
) -> None:
    """Fill empty sticker fields from Ozon get/list payload (package barcodes + posting_number)."""
    pn = str(posting.get("posting_number") or "").strip()
    if not pn:
        return
    hints = sticker_fields_from_posting(posting)
    persist_posting_stickers_batch(
        repo,
        user_id=user_id,
        source_id=source_id,
        stickers={pn: hints},
        only_if_empty=True,
    )


def _posting_payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Rebuild Ozon posting dict from DB row (raw_json + products_json fallback)."""
    posting: dict[str, Any] = {}
    raw_text = str(row.get("raw_json") or "").strip()
    if raw_text:
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict):
                posting = parsed
        except json.JSONDecodeError:
            pass
    if not _products_from_posting(posting):
        try:
            pj = json.loads(str(row.get("products_json") or "[]"))
        except json.JSONDecodeError:
            pj = []
        if isinstance(pj, list):
            products = [p for p in pj if isinstance(p, dict)]
            if products:
                posting = dict(posting)
                posting["products"] = products
    return posting


def _product_has_mandatory_mark_flag(product: dict[str, Any]) -> bool:
    """Ozon v3: ``mandatory_mark`` may be bool or a non-empty list of codes."""
    mm = product.get("mandatory_mark")
    if isinstance(mm, list):
        return bool(mm)
    if isinstance(mm, str):
        return bool(mm.strip())
    return bool(mm)


def _mandatory_mark_sku_ids(posting: dict[str, Any]) -> set[str]:
    """SKU/product_id values that Ozon marks as requiring Chestny ZNAK."""
    ids: set[str] = set()
    req = posting.get("requirements")
    if isinstance(req, dict):
        arr = req.get("products_requiring_mandatory_mark")
        if isinstance(arr, list):
            for x in arr:
                text = str(x or "").strip()
                if text:
                    ids.add(text)
    return ids


def _merge_products_requiring_mandatory_mark(
    posting: dict[str, Any], required_ids: set[str]
) -> dict[str, Any]:
    if not required_ids:
        return posting
    out = dict(posting)
    req = out.get("requirements")
    if not isinstance(req, dict):
        req = {}
        out["requirements"] = req
    existing = req.get("products_requiring_mandatory_mark")
    merged: list[str] = []
    if isinstance(existing, list):
        merged = [str(x).strip() for x in existing if str(x).strip()]
    for pid in sorted(required_ids):
        if pid not in merged:
            merged.append(pid)
    req["products_requiring_mandatory_mark"] = merged
    return out


def enrich_posting_marking_flags(
    client: OzonFbsClient,
    posting: dict[str, Any],
) -> dict[str, Any]:
    """Augment posting with marking requirements when get/list omit them."""
    if not isinstance(posting, dict):
        return posting
    products = _products_from_posting(posting)
    if _mandatory_mark(posting, products):
        return posting
    pn = str(posting.get("posting_number") or "").strip()
    if not pn:
        return posting
    sku_ints: list[int] = []
    payload_products: list[dict[str, Any]] = []
    for p in products:
        if bool(p.get("is_marketplace_buyout")):
            continue
        product_id = p.get("sku") or p.get("product_id")
        try:
            pid = int(product_id)
        except (TypeError, ValueError):
            continue
        sku_ints.append(pid)
        try:
            qty = int(p.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1
        payload_products.append({"product_id": pid, "quantity": max(qty, 1)})
    if not sku_ints:
        return posting

    required_ids: set[str] = set()
    is_required_checked = False
    try:
        for item in client.mandatory_mark_is_required(pn, sku_ints):
            is_required_checked = True
            if not item.get("is_required"):
                continue
            sku_val = item.get("sku")
            if sku_val is not None:
                text = str(sku_val).strip()
                if text:
                    required_ids.add(text)
    except RuntimeError:
        pass
    if required_ids:
        return _merge_products_requiring_mandatory_mark(posting, required_ids)
    if is_required_checked:
        return posting

    if not payload_products:
        return posting
    try:
        resp = client.product_exemplar_create_or_get(pn, payload_products)
    except RuntimeError:
        try:
            resp = client.product_exemplar_create_or_get_v5(pn, payload_products)
        except RuntimeError:
            return posting
    for item in resp.get("products") or []:
        if not isinstance(item, dict):
            continue
        if item.get("is_mandatory_mark_needed"):
            pid = item.get("product_id")
            if pid is not None:
                text = str(pid).strip()
                if text:
                    required_ids.add(text)
    return _merge_products_requiring_mandatory_mark(posting, required_ids)


def posting_requires_marking(row: dict[str, Any]) -> bool:
    """True when Ozon posting or any line item requires Chestny ZNAK marking."""
    if bool(row.get("is_mandatory_mark")):
        return True
    posting = _posting_payload_from_row(row)
    if not posting:
        return False
    products = _products_from_posting(posting)
    return _mandatory_mark(posting, products)


def marked_products_for_posting(posting: dict[str, Any]) -> list[dict[str, Any]]:
    """Product lines that need mandatory_mark codes (sku + qty)."""
    if not isinstance(posting, dict):
        return []
    products = _products_from_posting(posting)
    required_skus = _mandatory_mark_sku_ids(posting)
    out: list[dict[str, Any]] = []
    for p in products:
        if bool(p.get("is_marketplace_buyout")):
            continue
        sku = p.get("sku") or p.get("product_id")
        sku_str = str(sku).strip() if sku is not None else ""
        needs = _product_has_mandatory_mark_flag(p)
        if not needs and required_skus and sku_str in required_skus:
            needs = True
        if not needs:
            continue
        product_id = p.get("sku") or p.get("product_id")
        try:
            pid = int(product_id)
        except (TypeError, ValueError):
            continue
        try:
            qty = int(p.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1
        out.append({"product_id": pid, "quantity": max(qty, 1), "offer_id": p.get("offer_id")})
    if out:
        return out
    if _mandatory_mark(posting, products):
        for p in products:
            if bool(p.get("is_marketplace_buyout")):
                continue
            product_id = p.get("sku") or p.get("product_id")
            try:
                pid = int(product_id)
            except (TypeError, ValueError):
                continue
            try:
                qty = int(p.get("quantity") or 1)
            except (TypeError, ValueError):
                qty = 1
            out.append({"product_id": pid, "quantity": max(qty, 1), "offer_id": p.get("offer_id")})
    return out


def posting_marking_quantity(row: dict[str, Any]) -> int:
    """How many KIZ codes the posting needs (sum of marked product qty)."""
    posting = _posting_payload_from_row(row)
    marked = marked_products_for_posting(posting)
    if marked:
        return sum(int(p.get("quantity") or 1) for p in marked)
    if posting_requires_marking(row):
        try:
            return max(int(row.get("quantity") or 1), 1)
        except (TypeError, ValueError):
            return 1
    return 0


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
    required_skus = _mandatory_mark_sku_ids(posting)
    for p in products:
        if bool(p.get("is_marketplace_buyout")):
            continue
        if _product_has_mandatory_mark_flag(p):
            return True
        sku = p.get("sku") or p.get("product_id")
        if sku is not None and str(sku).strip() in required_skus:
            return True
    return False


def _barcodes_from_posting(posting: dict[str, Any], products: list[dict[str, Any]]) -> list[str]:
    """Product ШК from posting products only (never offer_id / sku / package QR)."""
    del posting  # package upper/lower barcodes are not product ШК
    out: list[str] = []
    exclude: set[str] = set()
    for p in products:
        for key in ("sku", "offer_id"):
            text = str(p.get(key) or "").strip()
            if text:
                exclude.add(text)
                exclude.add(text.casefold())
        for key in ("barcode", "bar_code"):
            text = str(p.get(key) or "").strip()
            if text and text not in out and text.casefold() not in exclude:
                out.append(text)
        raw = p.get("barcodes")
        if isinstance(raw, list):
            for item in raw:
                text = str(item or "").strip()
                if text and text not in out and text.casefold() not in exclude:
                    out.append(text)
        elif isinstance(raw, str):
            text = raw.strip()
            if text and text not in out and text.casefold() not in exclude:
                out.append(text)
    return out


def resolve_product_barcodes(
    *,
    offer_id: str | None,
    sku: str | None,
    barcode_map: dict[str, list[str]],
    fallback: list[str] | None = None,
) -> list[str]:
    """ШК from Feedback → Settings → Products; never show offer_id/sku as barcodes."""
    article = str(offer_id or "").strip()
    sku_key = str(sku or "").strip()
    exclude = {x for x in (article, sku_key, article.casefold(), sku_key.casefold()) if x}
    codes: list[str] = []
    for key in (
        article,
        article.casefold() if article else "",
        sku_key,
        sku_key.casefold() if sku_key else "",
    ):
        if not key:
            continue
        found = barcode_map.get(key)
        if found:
            codes = list(found)
            break
    if not codes and fallback:
        codes = [str(x or "").strip() for x in fallback if str(x or "").strip()]
    out: list[str] = []
    seen: set[str] = set()
    for code in codes:
        text = str(code or "").strip()
        if not text or text in seen or text in exclude or text.casefold() in exclude:
            continue
        seen.add(text)
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
    apply_posting_sticker_hints(
        repo, user_id=user_id, source_id=source_id, posting=posting
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


def resolve_product_display_name(
    *,
    offer_id: str | None,
    sku: str | None,
    name_by_article: dict[str, str],
    name_by_ozon_sku: dict[str, str],
) -> str:
    """Name from Feedback → Settings → Products (same priority as WB FBS New).

    Lookup: supplier article (offer_id), then Ozon SKU. Falls back to offer_id,
    never to marketplace title — matches WB FBS ``list_orders``.
    """
    article = str(offer_id or "").strip()
    sku_key = str(sku or "").strip()
    name = (
        name_by_article.get(article)
        or (name_by_article.get(article.casefold()) if article else "")
        or name_by_ozon_sku.get(sku_key)
        or (name_by_ozon_sku.get(sku_key.casefold()) if sku_key else "")
        or article
        or "—"
    )
    return str(name or "—").strip() or "—"


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
    ozon_sku_map = repo.get_product_name_by_ozon_sku(user_id=user_id)
    barcode_map = repo.get_product_barcodes_map(user_id=user_id)
    photo_map = repo.get_product_photo_map(user_id=user_id)
    items: list[dict[str, Any]] = []
    for row in rows:
        d = repo._row_to_dict(row)
        article = str(d.get("offer_id") or "").strip()
        sku = str(d.get("sku") or "").strip()
        display_name = resolve_product_display_name(
            offer_id=article,
            sku=sku,
            name_by_article=name_map,
            name_by_ozon_sku=ozon_sku_map,
        )
        d["product_name"] = display_name
        d["product_name_display"] = display_name
        d["product_photo"] = photo_map.get(article) or photo_map.get(sku) or ""
        d["tab_label"] = TAB_LABELS.get(str(d.get("tab") or ""), str(d.get("tab") or ""))
        d["status_label"] = str(d.get("status") or "")
        try:
            stored_barcodes = json.loads(d.get("barcodes_json") or "[]")
        except json.JSONDecodeError:
            stored_barcodes = []
        if not isinstance(stored_barcodes, list):
            stored_barcodes = []
        d["barcodes"] = resolve_product_barcodes(
            offer_id=article,
            sku=sku,
            barcode_map=barcode_map,
            fallback=stored_barcodes,
        )
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


def _as_positive_int(value: object) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def compute_ozon_fbs_pallet_summary(
    repo: ReviewRepository,
    *,
    user_id: int,
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pallets + boxes per Ozon FBS source from «Ожидают сборки» + «Ожидают отгрузки».

    Same formula as WB FBS:
    ``boxes = Σ (qty / box_qty)``
    ``pallets = Σ (qty / box_qty / boxes_per_pallet)``
    Products without ``box_qty`` are skipped; without category ``boxes_per_pallet``
    they still count toward boxes.
    """
    # Reuse WB formatters so labels stay identical in the UI.
    from .wb_fbs import format_boxes_ru, format_pallets_ru

    ensure_ozon_fbs_tables(repo)
    if not sources:
        return []

    products = repo.list_product_photos(user_id=user_id)
    categories = repo.list_product_categories(user_id=user_id, seed_defaults=True)
    cat_boxes: dict[str, int] = {}
    for cat in categories:
        name = str(cat.get("name") or "").strip()
        bpp = _as_positive_int(cat.get("boxes_per_pallet"))
        if name and bpp is not None:
            cat_boxes[name] = bpp

    # article / ozon_sku / casefold → (box_qty, boxes_per_pallet | None)
    product_meta: dict[str, tuple[int, int | None]] = {}
    for prod in products:
        box_qty = _as_positive_int(prod.get("box_qty"))
        if box_qty is None:
            continue
        cat_name = str(prod.get("product_category") or "").strip()
        bpp = cat_boxes.get(cat_name)
        meta = (box_qty, bpp)
        for raw_key in (
            prod.get("supplier_article"),
            prod.get("ozon_sku"),
            prod.get("wb_nmid"),
            prod.get("yandex_offer_id"),
        ):
            key = str(raw_key or "").strip()
            if not key:
                continue
            product_meta[key] = meta
            product_meta[key.casefold()] = meta

    source_names: dict[int, str] = {}
    source_ids: list[int] = []
    for src in sources:
        try:
            sid = int(src.get("source_id") if "source_id" in src else src.get("id"))
        except (TypeError, ValueError):
            continue
        source_ids.append(sid)
        source_names[sid] = str(
            src.get("name") or f"Источник {sid}"
        ).strip() or f"Источник {sid}"

    if not source_ids:
        return []

    placeholders = ", ".join("?" for _ in source_ids)
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                f"""
                SELECT source_id, offer_id, sku, COALESCE(SUM(quantity), 0) AS qty
                FROM ozon_fbs_postings
                WHERE user_id = ?
                  AND tab IN (?, ?)
                  AND source_id IN ({placeholders})
                GROUP BY source_id, offer_id, sku
                """
            ),
            tuple(
                [
                    user_id,
                    TAB_AWAITING_PACKAGING,
                    TAB_AWAITING_DELIVER,
                    *source_ids,
                ]
            ),
        ).fetchall()

    totals_pallets: dict[int, float] = {sid: 0.0 for sid in source_ids}
    totals_boxes: dict[int, float] = {sid: 0.0 for sid in source_ids}
    for row in rows:
        d = repo._row_to_dict(row)
        try:
            sid = int(d.get("source_id"))
            qty = int(d.get("qty") or 0)
        except (TypeError, ValueError):
            continue
        if sid not in totals_pallets or qty <= 0:
            continue
        offer_id = str(d.get("offer_id") or "").strip()
        sku = str(d.get("sku") or "").strip()
        meta = None
        for key in (offer_id, sku, offer_id.casefold(), sku.casefold()):
            if key and key in product_meta:
                meta = product_meta[key]
                break
        if not meta:
            continue
        box_qty, bpp = meta
        boxes = float(qty) / float(box_qty)
        totals_boxes[sid] += boxes
        if bpp is not None:
            totals_pallets[sid] += boxes / float(bpp)

    summary: list[dict[str, Any]] = []
    for sid in source_ids:
        pallets = round(float(totals_pallets.get(sid) or 0.0) + 1e-12, 2)
        boxes = round(float(totals_boxes.get(sid) or 0.0) + 1e-12, 2)
        pallets_label = format_pallets_ru(pallets)
        boxes_label = format_boxes_ru(boxes)
        summary.append(
            {
                "source_id": sid,
                "name": source_names.get(sid) or f"Источник {sid}",
                "pallets": pallets,
                "boxes": boxes,
                "boxes_label": boxes_label,
                "pallets_label": f"{pallets_label} ({boxes_label})",
            }
        )
    return summary


def get_sync_state() -> dict[str, object]:
    with _ozon_fbs_sync_lock:
        return _copy_sync_state()


def request_sync_stop() -> bool:
    with _ozon_fbs_sync_lock:
        if _ozon_fbs_sync_state.get("in_progress"):
            _ozon_fbs_sync_state["cancel_requested"] = True
            return True
    return False


def _copy_sync_state() -> dict[str, object]:
    """Snapshot sync state for API (deep-copy mutable lists)."""
    st = dict(_ozon_fbs_sync_state)
    st["errors"] = list(_ozon_fbs_sync_state.get("errors") or [])
    st["sources"] = [
        dict(x) if isinstance(x, dict) else x
        for x in (_ozon_fbs_sync_state.get("sources") or [])
    ]
    st["pallet_summary"] = [
        dict(x) if isinstance(x, dict) else x
        for x in (_ozon_fbs_sync_state.get("pallet_summary") or [])
    ]
    st["pallet_summary_error"] = str(
        _ozon_fbs_sync_state.get("pallet_summary_error") or ""
    ).strip()
    return st


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
                "pallet_summary": [],
                "pallet_summary_error": "",
                "cancel_requested": False,
            }
        )

    def _run() -> None:
        errors: list[str] = []
        synced_sources = 0
        total_postings = 0
        stopped = False
        pallet_summary_error = ""
        try:
            for idx, job in enumerate(jobs):
                with _ozon_fbs_sync_lock:
                    if _ozon_fbs_sync_state.get("cancel_requested"):
                        _ozon_fbs_sync_state["message"] = "Остановка…"
                        stopped = True
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
                        was_stopped = bool(result.get("stopped"))
                        row["status"] = "stopped" if was_stopped else "done"
                        row["postings"] = int(result.get("postings") or 0)
                        row["message"] = (
                            "Остановлено"
                            if was_stopped
                            else f"Готово: {row['postings']} отправлений"
                        )
                        if was_stopped:
                            stopped = True
                        else:
                            synced_sources += 1
                            total_postings += int(row["postings"] or 0)
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
            pallet_summary: list[dict[str, Any]] = []
            if synced_sources > 0:
                try:
                    pallet_summary = compute_ozon_fbs_pallet_summary(
                        repo, user_id=user_id, sources=jobs
                    )
                except Exception as exc:
                    _log.exception(
                        "ozon_fbs pallet summary failed user=%s", user_id
                    )
                    pallet_summary = []
                    pallet_summary_error = _PALLET_SUMMARY_ERROR
                    detail = str(exc).strip()
                    if detail and detail not in pallet_summary_error:
                        pallet_summary_error = f"{_PALLET_SUMMARY_ERROR} ({detail})"

            with _ozon_fbs_sync_lock:
                _ozon_fbs_sync_state["in_progress"] = False
                _ozon_fbs_sync_state["errors"] = errors
                _ozon_fbs_sync_state["pallet_summary"] = pallet_summary
                _ozon_fbs_sync_state["pallet_summary_error"] = pallet_summary_error
                stats_part = (
                    f"Источников: {synced_sources}/{len(jobs)} | "
                    f"Отправлений: {total_postings}"
                )
                if stopped or _ozon_fbs_sync_state.get("cancel_requested"):
                    _ozon_fbs_sync_state["message"] = f"Остановлено. {stats_part}"
                elif errors:
                    _ozon_fbs_sync_state["message"] = (
                        f"Готово с ошибками. {stats_part}"
                    )
                else:
                    _ozon_fbs_sync_state["message"] = f"Готово. {stats_part}"

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
