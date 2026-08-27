"""Ozon FBS helpers for the warehouse ТСД page (shared with WB TSD UI)."""

from __future__ import annotations

from typing import Any

from . import ozon_fbs_marking as oz_mark
from . import ozon_fbs_pick_verify as oz_pick
from . import ozon_fbs_supplies as oz_sup
from .repository import ReviewRepository


def _row_kiz_filled(row: dict[str, Any]) -> bool:
    codes = row.get("kiz_codes") or []
    return any(str(c or "").strip() for c in codes)


def _row_pick_filled(row: dict[str, Any]) -> bool:
    return bool(row.get("pick_verified")) and bool(str(row.get("pick_barcode") or "").strip())


def _normalize_tsd_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add TSD-compatible aliases (sticker_number, synthetic order_id)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = dict(row)
        pn = str(d.get("posting_number") or "").strip()
        if pn and not str(d.get("sticker_number") or "").strip():
            d["sticker_number"] = pn
        if pn and d.get("order_id") in (None, "", 0):
            d["order_id"] = pn
        out.append(d)
    return out


def build_ozon_tsd_hub_progress(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
    client_id: str,
    api_key: str,
) -> dict[str, Any]:
    """Hub KIZ/pick counters for Ozon FBS supplies (awaiting_deliver)."""
    sid = str(supply_id or "").strip()
    empty = {
        "kiz": {"total": 0, "done": 0},
        "pick": {"total": 0, "done": 0},
        "order_count": 0,
    }
    if not sid:
        return empty

    try:
        kiz_payload = oz_mark.build_marking_payload(
            repo,
            user_id=user_id,
            source_id=source_id,
            supply_id=sid,
            client_id=client_id,
            api_key=api_key,
        )
        pick_payload = oz_pick.build_pick_verify_payload(
            repo,
            user_id=user_id,
            source_id=source_id,
            supply_id=sid,
            client_id=client_id,
            api_key=api_key,
        )
    except Exception:
        return empty

    kiz_rows = [
        r
        for r in (kiz_payload.get("rows") or [])
        if isinstance(r, dict) and not r.get("cancelled")
    ]
    pick_rows = [r for r in (pick_payload.get("rows") or []) if isinstance(r, dict)]

    kiz_total = len(kiz_rows)
    kiz_done = sum(1 for r in kiz_rows if _row_kiz_filled(r))
    pick_total = len(pick_rows)
    pick_done = sum(1 for r in pick_rows if _row_pick_filled(r))

    return {
        "kiz": {"total": kiz_total, "done": kiz_done},
        "pick": {"total": pick_total, "done": pick_done},
        "order_count": kiz_total + pick_total,
    }


def build_ozon_tsd_kiz_payload(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
    client_id: str,
    api_key: str,
) -> dict[str, Any]:
    payload = oz_mark.build_marking_payload(
        repo,
        user_id=user_id,
        source_id=source_id,
        supply_id=supply_id,
        client_id=client_id,
        api_key=api_key,
    )
    rows = _normalize_tsd_rows(list(payload.get("rows") or []))
    return {**payload, "rows": rows}


def build_ozon_tsd_pick_payload(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
    client_id: str,
    api_key: str,
) -> dict[str, Any]:
    payload = oz_pick.build_pick_verify_payload(
        repo,
        user_id=user_id,
        source_id=source_id,
        supply_id=supply_id,
        client_id=client_id,
        api_key=api_key,
    )
    rows = _normalize_tsd_rows(list(payload.get("rows") or []))
    return {**payload, "rows": rows}


def list_ozon_tsd_supplies(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    search: str | None = None,
) -> dict[str, Any]:
    """Open Ozon FBS supplies for ТСД (tab «Ожидают отгрузки»)."""
    data = oz_sup.list_awaiting_deliver_supplies(
        repo, user_id=user_id, source_id=source_id
    )
    items = list(data.get("items") or [])
    q = str(search or "").strip().lower()
    if q:
        items = [
            x
            for x in items
            if q in str(x.get("name") or "").lower()
            or q in str(x.get("supply_id") or "").lower()
            or q in str(x.get("warehouse_label") or "").lower()
        ]
    for item in items:
        item.setdefault("boxes_count", 0)
    return {
        "items": items,
        "total": len(items),
        "page": 1,
        "page_size": len(items) or 100,
    }
