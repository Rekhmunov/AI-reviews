"""Ozon FBS carriage containers (грузоместа / паллеты).

Seller API:
- ``POST /v1/carriage/container/create``
- ``POST /v1/carriage/container/list``
- ``POST /v1/carriage/container/get``
- ``POST /v1/carriage/container/fill``
- ``POST /v1/carriage/container/remove-postings``
- ``POST /v1/carriage/container/label/get``
- ``POST /v1/carriage/container/approve``
- ``POST /v1/carriage/container/cancel``  (delete)
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from . import ozon_fbs as oz
from . import ozon_fbs_supplies as oz_sup
from .repository import ReviewRepository

_log = logging.getLogger(__name__)

SORT_TYPES = frozenset({"sort", "non-sort"})
CARGO_TYPES = frozenset({"box", "pallet"})

# Terminal / already-shipped statuses — hide from the working modal.
_SHIPPED_OR_GONE_STATUSES = frozenset(
    {
        "shipped",
        "closed",
        "cancelled",
        "canceled",
        "deleted",
        "completed",
        "sent",
        "delivered",
    }
)

_STATUS_LABELS = {
    "new": "Новое",
    "approved": "Подтверждено",
    "approve_failed": "Ошибка подтверждения",
    "formed": "Сформировано",
    "ready": "Готово",
    "in_progress": "В работе",
    "shipped": "Отгружено",
    "closed": "Закрыто",
    "cancelled": "Отменено",
    "canceled": "Отменено",
    "deleted": "Удалено",
}

_SORT_LABELS = {
    "sort": "Сортируемое",
    "non-sort": "Несортируемое",
}

_CARGO_LABELS = {
    "pallet": "Паллета",
    "box": "Короб",
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def status_label(status: object) -> str:
    key = str(status or "").strip().lower()
    if not key:
        return "—"
    return _STATUS_LABELS.get(key, key)


def is_active_container(row: dict[str, Any]) -> bool:
    """True if container should appear in the working modal (not yet shipped)."""
    st = str(row.get("status") or "").strip().lower()
    if st in _SHIPPED_OR_GONE_STATUSES:
        return False
    actions = row.get("available_actions") or []
    if isinstance(actions, list):
        acts = {str(a).strip().lower() for a in actions}
        # Still editable / printable → keep.
        if acts & {"delete", "approve", "get_label_container", "fill"}:
            return True
    # Unknown status without actions: keep unless clearly terminal.
    return st not in _SHIPPED_OR_GONE_STATUSES


def _normalize_container(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        cid = int(raw.get("container_id") or 0)
    except (TypeError, ValueError):
        cid = 0
    if cid <= 0:
        return None
    try:
        number = int(raw.get("container_number") or 0)
    except (TypeError, ValueError):
        number = 0
    try:
        orders = int(raw.get("count_of_postings") or 0)
    except (TypeError, ValueError):
        orders = 0
    status = str(raw.get("status") or "").strip().lower()
    sort_type = str(raw.get("sort_type") or "").strip().lower()
    cargo_type = str(raw.get("cargo_type") or "").strip().lower()
    actions = [
        str(a).strip()
        for a in (raw.get("available_actions") or [])
        if str(a).strip()
    ]
    can_delete = "delete" in {a.lower() for a in actions}
    acts_l = {a.lower() for a in actions}
    # Label is available while Ozon exposes get_label_container (or brand-new «new»).
    can_print = ("get_label_container" in acts_l) or (status in {"new", "approve_failed"})
    return {
        "container_id": cid,
        "container_number": number,
        "status": status,
        "status_label": status_label(status),
        "sort_type": sort_type,
        "sort_type_label": _SORT_LABELS.get(sort_type, sort_type or "—"),
        "cargo_type": cargo_type,
        "cargo_type_label": _CARGO_LABELS.get(cargo_type, cargo_type or "—"),
        "order_count": max(0, orders),
        "warehouse_id": raw.get("warehouse_id"),
        "warehouse_name": str(raw.get("warehouse_name") or "").strip(),
        "warehouse_date": str(raw.get("warehouse_date") or "").strip(),
        "created_at": str(raw.get("created_at") or "").strip(),
        "available_actions": actions,
        "can_delete": can_delete,
        "can_print": bool(can_print),
        "can_approve": "approve" in acts_l,
    }


def _friendly_ozon_error(exc: Exception) -> str:
    """Extract Ozon ``message`` from ``Ozon HTTP N: {json}`` RuntimeError text."""
    text = str(exc or "").strip()
    if not text:
        return "Ошибка Ozon API"
    # Typical: Ozon HTTP 400: {"code":3,"message":"FORBIDDEN_TO_CREATE_SORT_BOX"}
    if "{" in text and "}" in text:
        try:
            raw = text[text.index("{") : text.rindex("}") + 1]
            data = json.loads(raw)
            if isinstance(data, dict):
                msg = str(data.get("message") or "").strip()
                if msg:
                    return msg
        except Exception:
            pass
    return text


def resolve_supply_warehouse_id(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
) -> tuple[int, str]:
    """Warehouse for containers: supply row, else first linked posting."""
    sid = str(supply_id or "").strip()
    if not sid:
        raise RuntimeError("Укажите supply_id")
    supply = oz_sup.get_supply(repo, user_id=user_id, source_id=source_id, supply_id=sid)
    wh_name = ""
    wh_id = 0
    if supply:
        wh_name = str(supply.get("warehouse_name") or "").strip()
        try:
            wh = supply.get("warehouse_id")
            wh_id = int(wh) if wh is not None and str(wh).strip() != "" else 0
        except (TypeError, ValueError):
            wh_id = 0
        if wh_id > 0:
            return wh_id, wh_name
    # Fallback: warehouse from any posting linked to this supply.
    oz_sup.ensure_ozon_fbs_supply_schema(repo)
    with repo._connect() as conn:
        row = conn.execute(
            repo._sql(
                """
                SELECT warehouse_id, warehouse_name
                FROM ozon_fbs_postings
                WHERE user_id = ? AND source_id = ? AND supply_id = ?
                  AND warehouse_id IS NOT NULL
                ORDER BY posting_number
                LIMIT 1
                """
            ),
            (user_id, source_id, sid),
        ).fetchone()
    if row:
        d = repo._row_to_dict(row)
        try:
            wh_id = int(d.get("warehouse_id") or 0)
        except (TypeError, ValueError):
            wh_id = 0
        if wh_id > 0:
            return wh_id, str(d.get("warehouse_name") or wh_name).strip() or wh_name
    raise RuntimeError("Не удалось определить склад поставки для грузомест")


def list_containers(
    client: oz.OzonFbsClient,
    *,
    warehouse_id: int,
    lookback_days: int = 30,
    include_shipped: bool = False,
) -> dict[str, Any]:
    wh = int(warehouse_id or 0)
    if wh <= 0:
        raise ValueError("Укажите warehouse_id")
    days = max(1, min(int(lookback_days or 30), 90))
    now = _utc_now()
    created_from = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    created_to = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    items: list[dict[str, Any]] = []
    cursor = ""
    for _ in range(20):
        body: dict[str, Any] = {
            "filter": {
                "created_from": created_from,
                "created_to": created_to,
                "warehouse_id": wh,
            },
            "sort_dir": 1,
            "limit": 100,
        }
        if cursor:
            body["cursor"] = cursor
        try:
            data = client.carriage_container_list(body)
        except RuntimeError as exc:
            raise RuntimeError(_friendly_ozon_error(exc)) from exc
        rows = data.get("containers") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            rows = []
        for raw in rows:
            norm = _normalize_container(raw if isinstance(raw, dict) else {})
            if not norm:
                continue
            # Double-check warehouse (API may ignore filter).
            try:
                row_wh = int(norm.get("warehouse_id") or 0)
            except (TypeError, ValueError):
                row_wh = 0
            if row_wh and row_wh != wh:
                continue
            if not include_shipped and not is_active_container(norm):
                continue
            items.append(norm)
        cursor = str((data or {}).get("cursor") or "").strip()
        if not cursor:
            break
    items.sort(key=lambda x: (-int(x.get("container_number") or 0), -int(x.get("container_id") or 0)))
    return {
        "ok": True,
        "warehouse_id": wh,
        "items": items,
        "total": len(items),
        "lookback_days": days,
    }


def create_containers(
    client: oz.OzonFbsClient,
    *,
    warehouse_id: int,
    containers_count: int = 1,
    sort_type: str = "sort",
    cargo_type: str = "pallet",
) -> dict[str, Any]:
    wh = int(warehouse_id or 0)
    if wh <= 0:
        raise ValueError("Укажите warehouse_id")
    try:
        count = int(containers_count)
    except (TypeError, ValueError) as exc:
        raise ValueError("Некорректное число грузомест") from exc
    if count < 1 or count > 100:
        raise ValueError("Можно создать от 1 до 100 грузомест за раз")
    st = str(sort_type or "").strip().lower()
    if st not in SORT_TYPES:
        raise ValueError("sort_type: sort или non-sort")
    ct = str(cargo_type or "").strip().lower()
    if ct not in CARGO_TYPES:
        raise ValueError("cargo_type: box или pallet")
    try:
        data = client.carriage_container_create(
            warehouse_id=wh,
            containers_count=count,
            sort_type=st,
            cargo_type=ct,
        )
    except RuntimeError as exc:
        raise RuntimeError(_friendly_ozon_error(exc)) from exc
    ids_raw = data.get("container_ids") if isinstance(data, dict) else None
    ids: list[int] = []
    if isinstance(ids_raw, list):
        for x in ids_raw:
            try:
                n = int(x)
            except (TypeError, ValueError):
                continue
            if n > 0:
                ids.append(n)
    _log.info(
        "ozon fbs containers create wh=%s count=%s sort=%s cargo=%s ids=%s",
        wh,
        count,
        st,
        ct,
        ids,
    )
    return {
        "ok": True,
        "warehouse_id": wh,
        "container_ids": ids,
        "created": len(ids),
        "sort_type": st,
        "cargo_type": ct,
        "message": f"Создано грузомест: {len(ids)}",
    }


def delete_containers(
    client: oz.OzonFbsClient, *, container_ids: list[int]
) -> dict[str, Any]:
    ids: list[int] = []
    for x in container_ids or []:
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if n > 0:
            ids.append(n)
    ids = ids[:100]
    if not ids:
        raise ValueError("Укажите ID грузомест")
    try:
        data = client.carriage_container_cancel(container_ids=ids)
    except RuntimeError as exc:
        raise RuntimeError(_friendly_ozon_error(exc)) from exc
    errors = []
    if isinstance(data, dict):
        for err in data.get("error_containers") or []:
            if not isinstance(err, dict):
                continue
            errors.append(
                {
                    "container_id": err.get("container_id"),
                    "error": str(err.get("error_message") or err.get("message") or "").strip(),
                }
            )
    ok_n = max(0, len(ids) - len(errors))
    return {
        "ok": not errors,
        "deleted": ok_n,
        "errors": errors,
        "task_id": (data or {}).get("task_id") if isinstance(data, dict) else None,
        "message": (
            f"Удалено: {ok_n}"
            + (f", ошибок {len(errors)}" if errors else "")
        ),
    }


def get_container_labels_pdf(
    client: oz.OzonFbsClient, *, container_ids: list[int]
) -> dict[str, Any]:
    ids: list[int] = []
    for x in container_ids or []:
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if n > 0:
            ids.append(n)
    ids = ids[:300]
    if not ids:
        raise ValueError("Укажите ID грузомест")
    try:
        data = client.carriage_container_label_get(container_ids=ids)
    except RuntimeError as exc:
        raise RuntimeError(_friendly_ozon_error(exc)) from exc
    content = data.get("content") if isinstance(data, dict) else None
    file_b64 = ""
    content_type = "application/pdf"
    if isinstance(content, dict):
        file_b64 = str(content.get("file_content") or "").strip()
        content_type = str(content.get("content_type") or content_type).strip() or content_type
    errors = []
    if isinstance(data, dict):
        for err in data.get("error_containers") or []:
            if not isinstance(err, dict):
                continue
            errors.append(
                {
                    "container_id": err.get("container_id"),
                    "error": str(err.get("error_message") or "").strip(),
                }
            )
    if not file_b64:
        detail = "; ".join(e["error"] for e in errors if e.get("error")) or "Ozon не вернул PDF"
        raise RuntimeError(detail)
    return {
        "ok": True,
        "content_type": content_type,
        "file_content": file_b64,
        "errors": errors,
        "container_ids": ids,
    }
