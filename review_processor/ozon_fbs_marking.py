"""Ozon FBS Chestny ZNAK marking — local draft storage for supply modal."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from . import ozon_fbs as oz
from . import ozon_fbs_supplies as oz_sup
from . import wb_fbs as wb
from . import wb_fbs_kiz_restore as kiz_restore
from .repository import ReviewRepository

_log = logging.getLogger(__name__)


def _normalize_mark_code(value: object) -> str:
    """Parity with WB FBS: ↔ → GS (\\u001D), then trim edges without stripping GS."""
    return wb._kiz_code_clean(kiz_restore.normalize_kiz_mark(value))


def _parse_codes(raw: object) -> list[str]:
    if isinstance(raw, list):
        parsed = raw
    else:
        try:
            parsed = json.loads(str(raw or "[]"))
        except json.JSONDecodeError:
            parsed = []
    if not isinstance(parsed, list):
        return []
    return [_normalize_mark_code(x) for x in parsed if _normalize_mark_code(x)]


def load_marking_map(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    posting_numbers: list[str],
) -> dict[str, dict[str, Any]]:
    nums = [str(x).strip() for x in posting_numbers if str(x).strip()]
    if not nums:
        return {}
    oz.ensure_ozon_fbs_tables(repo)
    placeholders = ", ".join("?" for _ in nums)
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                f"""
                SELECT posting_number, marking_codes_json, marking_saved_at, marking_ozon_synced
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
        if not pn:
            continue
        out[pn] = {
            "codes": _parse_codes(d.get("marking_codes_json")),
            "saved_at": str(d.get("marking_saved_at") or ""),
            "ozon_synced": bool(d.get("marking_ozon_synced")),
        }
    return out


def _marking_status(*, codes: list[str], required_qty: int) -> str:
    clean = [c for c in codes if c]
    if not clean:
        return "empty"
    if len(clean) >= max(required_qty, 1):
        return "ok"
    return "pending"


def _load_posting_cancelled_map(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    posting_numbers: list[str],
) -> dict[str, bool]:
    nums = [str(x).strip() for x in posting_numbers if str(x).strip()]
    if not nums:
        return {}
    placeholders = ", ".join("?" for _ in nums)
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                f"""
                SELECT posting_number, status, tab, raw_json
                FROM ozon_fbs_postings
                WHERE user_id = ? AND source_id = ?
                  AND posting_number IN ({placeholders})
                """
            ),
            (user_id, source_id, *nums),
        ).fetchall()
    out: dict[str, bool] = {}
    for row in rows:
        d = repo._row_to_dict(row)
        pn = str(d.get("posting_number") or "").strip()
        if pn:
            out[pn] = oz.posting_row_is_cancelled(d)
    return out


def order_kiz_flags_for_orders(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """KIZ flags per posting for supply detail merge after modal load."""
    return _order_kiz_flags(orders)


def _order_kiz_flags(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for o in orders:
        if not isinstance(o, dict):
            continue
        pn = str(o.get("posting_number") or "").strip()
        if not pn:
            continue
        out.append(
            {
                "posting_number": pn,
                "kiz_required": bool(o.get("kiz_required")),
                "kiz_status": str(o.get("kiz_status") or "empty"),
                "cancelled": bool(o.get("cancelled")),
                "cancel_reason_label": str(o.get("cancel_reason_label") or ""),
            }
        )
    return out


def build_marking_payload(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
    client_id: str | None = None,
    api_key: str | None = None,
    resolve_kiz: bool = True,
    max_postings: int | None = None,
) -> dict[str, Any]:
    """Marking modal: resolve КИЗ via is-required (chunked), then local rows."""
    cid = str(client_id or "").strip()
    key = str(api_key or "").strip()
    marking_resolve = oz_sup._empty_marking_resolve()
    chunk = oz_sup._clamp_live_check_chunk(
        max_postings if max_postings is not None else oz_sup.OZON_FBS_LIVE_CHECK_CHUNK
    )
    if resolve_kiz and cid and key:
        try:
            marking_resolve = oz_sup.resolve_supply_kiz_flags_from_ozon(
                repo,
                user_id=user_id,
                source_id=source_id,
                supply_id=supply_id,
                client_id=cid,
                api_key=key,
                max_postings=chunk,
            )
        except Exception as exc:
            _log.warning("ozon marking resolve kiz %s: %s", supply_id, exc)

    detail = oz_sup.get_supply_detail(
        repo,
        user_id=user_id,
        source_id=source_id,
        supply_id=supply_id,
    )
    orders = [
        o
        for o in (detail.get("orders") or [])
        if isinstance(o, dict)
        and o.get("kiz_required")
        and not o.get("cancelled")
    ]
    posting_numbers = [
        str(o.get("posting_number") or "").strip()
        for o in orders
        if str(o.get("posting_number") or "").strip()
    ]
    local = load_marking_map(
        repo,
        user_id=user_id,
        source_id=source_id,
        posting_numbers=posting_numbers,
    )
    rows: list[dict[str, Any]] = []
    for o in orders:
        pn = str(o.get("posting_number") or "").strip()
        if not pn:
            continue
        req_qty = int(o.get("kiz_quantity") or 1)
        loc = local.get(pn) or {}
        saved_codes = list(loc.get("codes") or [])
        if loc.get("saved_at"):
            codes = saved_codes if saved_codes else [""]
        elif saved_codes:
            codes = saved_codes
        else:
            codes = [""] * max(req_qty, 1)
        while len(codes) < req_qty:
            codes.append("")
        status = _marking_status(codes=codes, required_qty=req_qty)
        rows.append(
            {
                "posting_number": pn,
                "product_name": o.get("product_name") or o.get("offer_id") or "",
                "product_photo": o.get("product_photo") or "",
                "offer_id": o.get("offer_id") or "",
                "sku": o.get("sku"),
                "barcodes": list(o.get("barcodes") or []),
                "quantity": req_qty,
                "kiz_required": True,
                "kiz_codes": codes,
                "kiz_saved_at": str(loc.get("saved_at") or ""),
                "kiz_ozon_synced": bool(loc.get("ozon_synced")),
                "kiz_status": status,
                "cancel_reason_label": str(o.get("cancel_reason_label") or ""),
                "cancelled": False,
                "order_id": o.get("order_id"),
                "order_number": str(o.get("order_number") or "").strip(),
                "created_at_ozon": o.get("created_at_ozon") or o.get("in_process_at") or "",
                "in_process_at": o.get("in_process_at") or "",
                "sticker_barcode": str(o.get("sticker_barcode") or "").strip(),
                "sticker_lower_barcode": str(o.get("sticker_lower_barcode") or "").strip(),
                "sticker_part_a": str(o.get("sticker_part_a") or "").strip(),
                "sticker_part_b": str(o.get("sticker_part_b") or "").strip(),
            }
        )
    all_orders = [o for o in (detail.get("orders") or []) if isinstance(o, dict)]
    return {
        "ok": True,
        "supply_id": detail.get("supply_id"),
        "source_id": source_id,
        "rows": rows,
        "required_count": len(rows),
        "order_kiz_flags": order_kiz_flags_for_orders(all_orders),
        "marking_resolve": marking_resolve,
    }


def _build_exemplar_set_products(
    *,
    create_result: dict[str, Any],
    codes: list[str],
) -> list[dict[str, Any]]:
    products_out: list[dict[str, Any]] = []
    code_idx = 0
    for prod in create_result.get("products") or []:
        if not isinstance(prod, dict):
            continue
        product_id = prod.get("product_id")
        if product_id is None:
            continue
        exemplars_out: list[dict[str, Any]] = []
        for ex in prod.get("exemplars") or []:
            if not isinstance(ex, dict):
                continue
            exemplar_id = ex.get("exemplar_id")
            if exemplar_id is None:
                continue
            code = codes[code_idx] if code_idx < len(codes) else ""
            code_idx += 1
            marks: list[dict[str, str]] = []
            if code:
                marks.append({"mark": code, "mark_type": "mandatory_mark"})
            exemplars_out.append({"exemplar_id": exemplar_id, "marks": marks})
        if exemplars_out:
            products_out.append({"product_id": product_id, "exemplars": exemplars_out})
    return products_out


def push_marking_to_ozon(
    client: oz.OzonFbsClient,
    *,
    posting_number: str,
    posting: dict[str, Any],
    codes: list[str],
) -> None:
    marked = oz.marked_products_for_posting(posting)
    if not marked:
        raise RuntimeError("Отправление не требует маркировки")
    create_products = [
        {"product_id": int(p["product_id"]), "quantity": int(p["quantity"])}
        for p in marked
    ]
    create_result = client.product_exemplar_create_or_get(
        str(posting_number), create_products
    )
    set_products = _build_exemplar_set_products(create_result=create_result, codes=codes)
    if not set_products:
        raise RuntimeError("Не удалось сопоставить exemplars Ozon с кодами маркировки")
    client.product_exemplar_set(
        str(posting_number),
        multi_box_qty=1,
        products=set_products,
    )
    validate_products = []
    for prod in set_products:
        pid = prod.get("product_id")
        exemplars = []
        for ex in prod.get("exemplars") or []:
            marks = ex.get("marks") or []
            mark_val = ""
            for m in marks:
                if isinstance(m, dict) and m.get("mark_type") == "mandatory_mark":
                    mark_val = str(m.get("mark") or "")
                    break
            if mark_val:
                exemplars.append({"mandatory_mark": mark_val, "gtd": "", "jw_uin": ""})
        if pid and exemplars:
            validate_products.append({"product_id": pid, "exemplars": exemplars})
    if validate_products:
        client.product_exemplar_validate(str(posting_number), validate_products)


def save_marking(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    items: list[dict[str, Any]],
    allowed_posting_numbers: set[str] | None = None,
) -> dict[str, Any]:
    """Save marking codes locally only. Never calls Ozon."""
    results: list[dict[str, Any]] = []
    ok_n = 0
    err_n = 0
    skipped_n = 0
    candidate_pns = [
        str(raw.get("posting_number") or "").strip()
        for raw in items
        if isinstance(raw, dict) and str(raw.get("posting_number") or "").strip()
    ]
    cancelled_map = _load_posting_cancelled_map(
        repo,
        user_id=user_id,
        source_id=source_id,
        posting_numbers=candidate_pns,
    )
    for raw in items:
        if not isinstance(raw, dict):
            continue
        pn = str(raw.get("posting_number") or "").strip()
        if not pn:
            continue
        if cancelled_map.get(pn):
            skipped_n += 1
            continue
        if allowed_posting_numbers is not None and pn not in allowed_posting_numbers:
            err_n += 1
            results.append(
                {
                    "posting_number": pn,
                    "ok": False,
                    "kiz_codes": [],
                    "error": "Отправление не входит в эту поставку",
                }
            )
            continue
        codes = [
            _normalize_mark_code(x)
            for x in (raw.get("kiz_codes") or [])
            if _normalize_mark_code(x)
        ]
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
        expected_saved_at = str(raw.get("expected_saved_at") or "").strip()
        force_save = bool(raw.get("force"))
        local_res = update_posting_marking_codes(
            repo,
            user_id=user_id,
            source_id=source_id,
            posting_number=pn,
            codes=uniq,
            ozon_synced=False,
            expected_saved_at=expected_saved_at or None,
            force=force_save,
        )
        if local_res.get("conflict"):
            err_n += 1
            results.append(
                {
                    "posting_number": pn,
                    "ok": False,
                    "conflict": True,
                    "kiz_codes": list(local_res.get("codes") or []),
                    "kiz_saved_at": str(local_res.get("saved_at") or ""),
                    "error": "Коды изменены другим оператором — обновите таблицу",
                }
            )
            continue
        if local_res.get("missing"):
            err_n += 1
            results.append(
                {
                    "posting_number": pn,
                    "ok": False,
                    "kiz_codes": uniq,
                    "error": "Отправление не найдено локально",
                }
            )
            continue
        local_ok = bool(local_res.get("ok"))
        if local_ok:
            ok_n += 1
        else:
            err_n += 1
        results.append(
            {
                "posting_number": pn,
                "ok": local_ok,
                "kiz_codes": list(local_res.get("codes") or uniq),
                "kiz_saved_at": str(local_res.get("saved_at") or ""),
            }
        )
    return {
        "ok": err_n == 0,
        "saved": ok_n,
        "skipped": skipped_n,
        "errors": err_n,
        "results": results,
    }


def update_posting_marking_codes(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    posting_number: str,
    codes: list[str],
    ozon_synced: bool = False,
    expected_saved_at: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    pn = str(posting_number or "").strip()
    if not pn:
        return {"ok": False, "missing": True}
    oz.ensure_ozon_fbs_tables(repo)
    clean = [_normalize_mark_code(c) for c in codes if _normalize_mark_code(c)]
    now = datetime.now(UTC).isoformat()
    with repo._connect() as conn:
        row = conn.execute(
            repo._sql(
                """
                SELECT marking_codes_json, marking_saved_at
                FROM ozon_fbs_postings
                WHERE user_id = ? AND source_id = ? AND posting_number = ?
                """
            ),
            (user_id, source_id, pn),
        ).fetchone()
        if not row:
            return {"ok": False, "missing": True}
        d = repo._row_to_dict(row)
        prev_saved = str(d.get("marking_saved_at") or "").strip()
        if (
            expected_saved_at
            and prev_saved
            and prev_saved != expected_saved_at
            and not force
        ):
            prev_codes = _parse_codes(d.get("marking_codes_json"))
            return {
                "ok": False,
                "conflict": True,
                "codes": prev_codes,
                "saved_at": prev_saved,
            }
        conn.execute(
            repo._sql(
                """
                UPDATE ozon_fbs_postings
                SET marking_codes_json = ?,
                    marking_saved_at = ?,
                    marking_ozon_synced = ?
                WHERE user_id = ? AND source_id = ? AND posting_number = ?
                """
            ),
            (
                json.dumps(clean, ensure_ascii=False),
                now,
                repo._bool_db(ozon_synced),
                user_id,
                source_id,
                pn,
            ),
        )
    return {"ok": True, "codes": clean, "saved_at": now}


def check_supply_marking_status(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
    client_id: str | None = None,
    api_key: str | None = None,
    refresh_from_ozon: bool = False,
) -> dict[str, Any]:
    """Local check: are all КИЗ fields filled for kiz_required postings in supply."""
    del client_id, api_key, refresh_from_ozon
    detail = oz_sup.get_supply_detail(
        repo,
        user_id=user_id,
        source_id=source_id,
        supply_id=supply_id,
    )
    orders = [o for o in (detail.get("orders") or []) if isinstance(o, dict)]
    posting_numbers = [
        str(o.get("posting_number") or "").strip()
        for o in orders
        if str(o.get("posting_number") or "").strip()
    ]
    local = load_marking_map(
        repo,
        user_id=user_id,
        source_id=source_id,
        posting_numbers=posting_numbers,
    )
    required = [
        o
        for o in orders
        if o.get("kiz_required") and not oz.posting_row_is_cancelled(o)
    ]
    done = 0
    pending = 0
    empty = 0
    status_rows: list[dict[str, Any]] = []
    for o in orders:
        pn = str(o.get("posting_number") or "").strip()
        if not pn:
            continue
        cancelled = bool(o.get("cancelled"))
        kiz_required = bool(o.get("kiz_required"))
        loc = local.get(pn) or {}
        codes = list(loc.get("codes") or [])
        if kiz_required and not cancelled:
            req_qty = int(o.get("kiz_quantity") or 1)
            st = _marking_status(codes=codes, required_qty=req_qty)
            if st == "ok":
                done += 1
            elif st == "empty":
                empty += 1
            else:
                pending += 1
        else:
            st = "empty"
        status_rows.append(
            {
                "posting_number": pn,
                "kiz_required": kiz_required,
                "kiz_codes": codes,
                "kiz_status": st if kiz_required else "empty",
                "cancelled": cancelled,
                "cancel_reason_label": str(o.get("cancel_reason_label") or ""),
            }
        )
    total = len(required)
    if total == 0:
        tone = ""
    elif done == total:
        tone = "ok"
    else:
        tone = ""
    return {
        "ok": True,
        "required": total,
        "done": done,
        "pending": pending,
        "empty": empty,
        "status": tone,
        "orders": status_rows,
    }
