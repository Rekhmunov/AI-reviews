"""Ozon FBS Chestny ZNAK marking — local draft storage for supply modal."""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from . import ozon_fbs as oz
from . import ozon_fbs_supplies as oz_sup
from . import wb_fbs as wb
from . import wb_fbs_kiz_restore as kiz_restore
from .repository import ReviewRepository

_log = logging.getLogger(__name__)


def _normalize_mark_code(value: object) -> str:
    """Ozon FBS: ↔/☻/☺ → GS, then ensure GS before AI 91/92 for ЧЗ."""
    gs = "\x1d"
    text = str(value or "")
    for ch in ("\u263b", "\u263a", "\u2194"):  # ☻ ☺ ↔
        text = text.replace(ch, gs)
    text = text.replace("<GS>", gs).replace("<gs>", gs)
    text = text.replace("\\u001d", gs).replace("\\u001D", gs)
    text = wb._kiz_code_clean(kiz_restore.normalize_kiz_mark(text))
    # GS between AI 91 key and AI 92 crypto when missing.
    text = re.sub(r"(91[0-9A-Za-z+/]{4})(?!\x1d)(92)", rf"\1{gs}\2", text, count=1)
    # GS before AI 91 when serial is glued to the crypto tail.
    text = re.sub(
        rf"(?<!\x1d)(91[0-9A-Za-z+/]{{4}}\x1d92)",
        rf"{gs}\1",
        text,
        count=1,
    )
    return text


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


def clean_open_kiz_codes(codes: object) -> list[str]:
    """Sanitize KIZ slots when opening Marking modal.

    - 0 scanned → one empty input only
    - 1+ scanned → only filled codes (no trailing empty slot)
    Never pad empty fields up to quantity.
    """
    if isinstance(codes, list):
        raw = codes
    else:
        raw = []
    filled: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text:
            filled.append(text)
    if filled:
        return filled
    return [""]


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
                SELECT posting_number, marking_codes_json, marking_saved_at,
                       marking_ozon_synced, marking_gtd_number
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
            # Canonical UTC token — same as WB FBS (avoids false conflicts on PG round-trip).
            "saved_at": wb._normalize_kiz_saved_at(d.get("marking_saved_at")),
            "ozon_synced": bool(d.get("marking_ozon_synced")),
            "gtd_number": str(d.get("marking_gtd_number") or "").strip(),
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
    posting_tab: str | None = None,
) -> dict[str, Any]:
    """Marking modal: resolve КИЗ via Settings → Products «Требует КИЗ», then local rows."""
    cid = str(client_id or "").strip()
    key = str(api_key or "").strip()
    tab_key = str(posting_tab or "").strip() or None
    marking_resolve = oz_sup._empty_marking_resolve()
    chunk = oz_sup._clamp_live_check_chunk(
        max_postings if max_postings is not None else oz_sup.OZON_FBS_LIVE_CHECK_CHUNK
    )
    if resolve_kiz:
        try:
            marking_resolve = oz_sup.resolve_supply_kiz_flags_from_ozon(
                repo,
                user_id=user_id,
                source_id=source_id,
                supply_id=supply_id,
                client_id=cid,
                api_key=key,
                posting_tab=tab_key,
                max_postings=chunk,
            )
        except Exception as exc:
            _log.warning("ozon marking resolve kiz %s: %s", supply_id, exc)

    detail = oz_sup.get_supply_detail(
        repo,
        user_id=user_id,
        source_id=source_id,
        supply_id=supply_id,
        posting_tab=tab_key,
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
            codes = [""]
        # Drop empty second+ slots on open; keep all filled codes.
        codes = clean_open_kiz_codes(codes)
        status = _marking_status(codes=codes, required_qty=req_qty)
        gtd_required = oz.posting_requires_pre_ship_gtd(o)
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
                "gtd_required": gtd_required,
                "gtd_number": str(loc.get("gtd_number") or "").strip(),
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
    gtd: str = "",
) -> list[dict[str, Any]]:
    products_out: list[dict[str, Any]] = []
    code_idx = 0
    gtd_clean = str(gtd or "").strip()
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
            ex_payload: dict[str, Any] = {
                "exemplar_id": exemplar_id,
                "marks": marks,
            }
            # GTD must be on set (v6) as well as validate — otherwise ship 400.
            if gtd_clean:
                ex_payload["gtd"] = gtd_clean
                ex_payload["is_gtd_absent"] = False
            elif bool(prod.get("is_gtd_needed")):
                ex_payload["gtd"] = ""
                ex_payload["is_gtd_absent"] = False
            exemplars_out.append(ex_payload)
        if exemplars_out:
            products_out.append({"product_id": product_id, "exemplars": exemplars_out})
    filled_codes = [c for c in codes if str(c or "").strip()]
    if products_out and filled_codes and code_idx != len(filled_codes):
        raise RuntimeError(
            f"Число экземпляров Ozon ({code_idx}) не совпадает с числом КИЗ "
            f"({len(filled_codes)}). Обновите заказ и повторите."
        )
    if products_out and filled_codes:
        missing = 0
        for prod in products_out:
            for ex in prod.get("exemplars") or []:
                marks = ex.get("marks") or []
                if not any(
                    isinstance(m, dict) and str(m.get("mark") or "").strip()
                    for m in marks
                ):
                    missing += 1
        if missing:
            raise RuntimeError(
                f"Не хватает КИЗ для {missing} экземпляр(ов) Ozon"
            )
    return products_out


def _error_text_has(exc: BaseException | str, token: str) -> bool:
    return token.upper() in str(exc or "").upper()


def _status_is_ok(status: str) -> bool:
    """Exact / normalized allowlist — avoid substring false positives (``ok`` in ``book``)."""
    s = str(status or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not s:
        return False
    ok_exact = {
        "ship_available",
        "ship_avail",
        "success",
        "ok",
        "validated",
        "passed",
        "ready",
        "complete",
        "completed",
        "done",
    }
    if s in ok_exact:
        return True
    # Ozon sometimes returns compound values.
    return s.endswith("_available") or s.endswith("_ok") or s.endswith("_success")


def _status_is_fail(status: str) -> bool:
    s = str(status or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not s:
        return False
    fail_exact = {
        "error",
        "failed",
        "fail",
        "invalid",
        "rejected",
        "reject",
        "not_valid",
        "validation_failed",
    }
    if s in fail_exact:
        return True
    return (
        s.endswith("_error")
        or s.endswith("_failed")
        or s.endswith("_invalid")
        or "reject" in s
    )


def _poll_exemplar_status(
    client: oz.OzonFbsClient,
    posting_number: str,
    *,
    attempts: int = 12,
    delay_sec: float = 0.75,
) -> dict[str, Any]:
    """Wait until Ozon accepts exemplar data (or fail with a clear message)."""
    import time as _time

    pn = str(posting_number)
    last: dict[str, Any] = {}
    for i in range(max(int(attempts), 1)):
        try:
            last = client.product_exemplar_status(pn)
        except RuntimeError as exc:
            # ALREADY_DEFINED / transient — keep polling a bit.
            if _error_text_has(exc, "EXEMPLAR_INFO_ALREADY_DEFINED"):
                return {"ok": True, "already_defined": True, "raw": {"error": str(exc)}}
            if i >= attempts - 1:
                raise
            _time.sleep(delay_sec)
            continue
        if not isinstance(last, dict):
            last = {}
        status_raw = last.get("status")
        if status_raw is None and isinstance(last.get("result"), dict):
            status_raw = last["result"].get("status")
        status = str(status_raw or "").strip().lower()
        # Nested product-level check states.
        products = last.get("products")
        if not isinstance(products, list) and isinstance(last.get("result"), dict):
            products = last["result"].get("products")
        product_statuses: list[str] = []
        side_hints: list[str] = []
        if isinstance(products, list):
            for p in products:
                if not isinstance(p, dict):
                    continue
                st = str(p.get("status") or p.get("check_status") or "").strip().lower()
                if st:
                    product_statuses.append(st)
                for key in ("errors", "error", "message"):
                    val = p.get(key)
                    if isinstance(val, list):
                        for item in val:
                            text = str(item or "").strip()
                            if text:
                                side_hints.append(text)
                    elif val:
                        text = str(val).strip()
                        if text:
                            side_hints.append(text)
        combined = " ".join([status, *product_statuses, *side_hints]).lower()
        if any(t in combined for t in ("country", "rnpt", "jw_uin")):
            _log.warning(
                "ozon exemplar status side-requirement posting=%s detail=%s",
                pn,
                combined[:400],
            )
        if status and _status_is_ok(status):
            return {"ok": True, "status": status, "raw": last}
        if product_statuses and all(_status_is_ok(st) for st in product_statuses):
            return {"ok": True, "status": status or "ok", "raw": last}
        if status and _status_is_fail(status):
            raise RuntimeError(
                f"Ozon не принял данные экземпляров (status={status}). "
                "Проверьте КИЗ и ГТД."
            )
        if any(_status_is_fail(st) for st in product_statuses):
            bad = next(st for st in product_statuses if _status_is_fail(st))
            raise RuntimeError(
                f"Ozon не принял данные экземпляров (status={bad}). "
                "Проверьте КИЗ и ГТД."
            )
        # Empty / pending — wait.
        if i < attempts - 1:
            _time.sleep(delay_sec)
    # Never soft-succeed: false marking_ozon_synced → ship fails later.
    raise RuntimeError(
        "Ozon ещё не подтвердил данные экземпляров (status timeout). "
        "Подождите немного и сохраните снова, затем соберите заказ."
    )


def push_marking_to_ozon(
    client: oz.OzonFbsClient,
    *,
    posting_number: str,
    posting: dict[str, Any],
    codes: list[str],
    gtd: str = "",
    requires_kiz_map: dict[str, bool] | None = None,
    prefer_gtd_products: bool = False,
) -> dict[str, Any]:
    """create-or-get → set(КИЗ+ГТД) → validate(КИЗ+ГТД) → poll status.

    Shared by packaging «Ожидают сборки» modal and supply «Маркировка».
    ``EXEMPLAR_INFO_ALREADY_DEFINED`` is treated as success after status check.
    """
    gtd_clean = str(gtd or "").strip()
    clean_codes = [c for c in codes if str(c or "").strip()]
    if prefer_gtd_products or oz.posting_requires_pre_ship_gtd(posting):
        marked = oz.pre_ship_exemplar_products(posting)
    else:
        marked = oz.marked_products_for_posting(
            posting, requires_kiz_map=requires_kiz_map
        )
    if not marked:
        raise RuntimeError("Отправление не требует маркировки")
    create_products = [
        {"product_id": int(p["product_id"]), "quantity": int(p["quantity"])}
        for p in marked
    ]
    already = False
    try:
        create_result = client.product_exemplar_create_or_get(
            str(posting_number), create_products
        )
    except RuntimeError as exc:
        if _error_text_has(exc, "EXEMPLAR_INFO_ALREADY_DEFINED"):
            already = True
            create_result = {"products": []}
        else:
            raise
    if not already:
        set_products = _build_exemplar_set_products(
            create_result=create_result, codes=clean_codes, gtd=gtd_clean
        )
        if not set_products:
            raise RuntimeError(
                "Не удалось сопоставить exemplars Ozon с кодами маркировки"
            )
        try:
            client.product_exemplar_set(
                str(posting_number),
                multi_box_qty=1,
                products=set_products,
            )
        except RuntimeError as exc:
            if _error_text_has(exc, "EXEMPLAR_INFO_ALREADY_DEFINED"):
                already = True
            else:
                raise
        if not already:
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
                        exemplars.append(
                            {
                                "mandatory_mark": mark_val,
                                "gtd": gtd_clean,
                                "jw_uin": "",
                            }
                        )
                if pid and exemplars:
                    validate_products.append(
                        {"product_id": pid, "exemplars": exemplars}
                    )
            if validate_products:
                try:
                    client.product_exemplar_validate(
                        str(posting_number), validate_products
                    )
                except RuntimeError as exc:
                    if _error_text_has(exc, "EXEMPLAR_INFO_ALREADY_DEFINED"):
                        already = True
                    else:
                        raise
    # Always poll (also after ALREADY_DEFINED) so we don't mark synced blindly.
    try:
        if already:
            status_out = _poll_exemplar_status(
                client, str(posting_number), attempts=4, delay_sec=0.25
            )
        else:
            status_out = _poll_exemplar_status(client, str(posting_number))
    except RuntimeError as exc:
        if _error_text_has(exc, "EXEMPLAR_INFO_ALREADY_DEFINED"):
            status_out = {"ok": True, "already_defined": True}
        elif already:
            # Data already on Ozon; status endpoint empty/flaky — accept.
            _log.warning(
                "ozon exemplar status after ALREADY_DEFINED posting=%s: %s",
                posting_number,
                exc,
            )
            status_out = {
                "ok": True,
                "already_defined": True,
                "status_warning": str(exc),
            }
        else:
            raise
    status_out["already_defined"] = bool(
        status_out.get("already_defined") or already
    )
    return status_out


def _load_posting_row(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    posting_number: str,
) -> dict[str, Any] | None:
    pn = str(posting_number or "").strip()
    if not pn:
        return None
    oz.ensure_ozon_fbs_tables(repo)
    with repo._connect() as conn:
        row = conn.execute(
            repo._sql(
                """
                SELECT * FROM ozon_fbs_postings
                WHERE user_id = ? AND source_id = ? AND posting_number = ?
                LIMIT 1
                """
            ),
            (user_id, source_id, pn),
        ).fetchone()
    return repo._row_to_dict(row) if row else None


def build_packaging_exemplar_payload(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    posting_number: str,
    client_id: str,
    api_key: str,
) -> dict[str, Any]:
    """Modal payload for pre-ship КИЗ+ГТД on «Ожидают сборки»."""
    row = _load_posting_row(
        repo, user_id=user_id, source_id=source_id, posting_number=posting_number
    )
    if not row:
        raise RuntimeError("Отправление не найдено локально")
    pn = str(row.get("posting_number") or "").strip()
    posting = oz._posting_payload_from_row(row) or {}
    client = oz.OzonFbsClient(client_id, api_key)
    # Refresh requirements from Ozon get when possible (list may omit GTD).
    try:
        remote = client.get_posting(pn)
        if isinstance(remote, dict) and remote.get("posting_number"):
            posting = remote
            try:
                oz.upsert_posting(
                    repo, user_id=user_id, source_id=source_id, posting=remote
                )
                row = _load_posting_row(
                    repo,
                    user_id=user_id,
                    source_id=source_id,
                    posting_number=pn,
                ) or row
            except Exception as exc:
                _log.warning("packaging exemplar upsert %s: %s", pn, exc)
    except Exception as exc:
        _log.info("packaging exemplar get_posting %s: %s", pn, exc)

    if not oz.posting_requires_pre_ship_gtd(posting if posting else row):
        raise RuntimeError(
            "Для этого отправления ГТД до сборки не требуется "
            "(нет products_requiring_gtd)"
        )

    products = oz.pre_ship_exemplar_products(posting)
    if not products:
        raise RuntimeError("Не удалось определить товары для маркировки")
    create_products = [
        {"product_id": int(p["product_id"]), "quantity": int(p["quantity"])}
        for p in products
    ]
    exemplar_count = sum(int(p["quantity"]) for p in products)
    create_result: dict[str, Any] = {}
    try:
        create_result = client.product_exemplar_create_or_get(pn, create_products)
        n = 0
        for prod in create_result.get("products") or []:
            if not isinstance(prod, dict):
                continue
            exemplars = prod.get("exemplars") or []
            if isinstance(exemplars, list) and exemplars:
                n += len(exemplars)
            else:
                try:
                    n += int(prod.get("quantity") or 0)
                except (TypeError, ValueError):
                    pass
        if n > 0:
            exemplar_count = n
        # Persist is_gtd_needed / mark flags from create-or-get.
        gtd_ids: set[str] = set()
        mark_ids: set[str] = set()
        for prod in create_result.get("products") or []:
            if not isinstance(prod, dict):
                continue
            pid = prod.get("product_id")
            if pid is None:
                continue
            text = str(pid).strip()
            if prod.get("is_gtd_needed"):
                gtd_ids.add(text)
            if prod.get("is_mandatory_mark_needed"):
                mark_ids.add(text)
        if gtd_ids or mark_ids:
            enriched = posting
            if mark_ids:
                enriched = oz._merge_products_requiring_mandatory_mark(enriched, mark_ids)
            if gtd_ids:
                enriched = oz._merge_products_requiring_gtd(enriched, gtd_ids)
            try:
                oz.upsert_posting(
                    repo, user_id=user_id, source_id=source_id, posting=enriched
                )
                posting = enriched
            except Exception as exc:
                _log.warning("packaging exemplar merge req %s: %s", pn, exc)
    except RuntimeError as exc:
        if not _error_text_has(exc, "EXEMPLAR_INFO_ALREADY_DEFINED"):
            _log.warning("packaging create-or-get %s: %s", pn, exc)

    local = load_marking_map(
        repo, user_id=user_id, source_id=source_id, posting_numbers=[pn]
    ).get(pn) or {}
    saved_codes = list(local.get("codes") or [])
    # Pad to exemplar_count empty slots for UI (unlike supply modal open-clean).
    codes: list[str] = []
    for i in range(max(exemplar_count, 1)):
        codes.append(saved_codes[i] if i < len(saved_codes) else "")
    if len(saved_codes) > len(codes):
        codes.extend(saved_codes[len(codes) :])

    name_map = repo.get_product_name_by_article(user_id=user_id)
    ozon_sku_map = repo.get_product_name_by_ozon_sku(user_id=user_id)
    photo_map = repo.get_product_photo_map(user_id=user_id)
    display_row = dict(row)
    oz.enrich_posting_product_display(
        display_row,
        name_by_article=name_map,
        name_by_ozon_sku=ozon_sku_map,
    )
    article = str(display_row.get("offer_id") or "").strip()
    sku = str(display_row.get("sku") or "").strip()
    photo = photo_map.get(article) or photo_map.get(sku) or ""
    return {
        "ok": True,
        "posting_number": pn,
        "source_id": source_id,
        "product_name": display_row.get("product_name_display")
        or display_row.get("product_name")
        or article
        or "—",
        "offer_id": article,
        "sku": sku,
        "product_photo": photo,
        "quantity": exemplar_count,
        "kiz_codes": codes,
        "gtd_number": str(local.get("gtd_number") or "").strip(),
        "gtd_required": True,
        "marking_ozon_synced": bool(local.get("ozon_synced")),
        "kiz_saved_at": str(local.get("saved_at") or ""),
        "sticker_required": False,
        "tab": str(row.get("tab") or ""),
    }


def save_packaging_exemplar(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    posting_number: str,
    client_id: str,
    api_key: str,
    kiz_codes: list[str],
    gtd_number: str,
) -> dict[str, Any]:
    """Save КИЗ+ГТД locally and push to Ozon (packaging stage). No sticker required."""
    from . import supply_gtd as gtd_mod

    row = _load_posting_row(
        repo, user_id=user_id, source_id=source_id, posting_number=posting_number
    )
    if not row:
        raise RuntimeError("Отправление не найдено локально")
    pn = str(row.get("posting_number") or "").strip()
    posting = oz._posting_payload_from_row(row) or {}
    if not oz.posting_requires_pre_ship_gtd(posting if posting else row):
        raise RuntimeError("Для этого отправления ГТД до сборки не требуется")

    codes = [
        _normalize_mark_code(x)
        for x in (kiz_codes or [])
        if _normalize_mark_code(x)
    ]
    seen: set[str] = set()
    uniq: list[str] = []
    for c in codes:
        if c in seen:
            continue
        seen.add(c)
        uniq.append(c)
    req_qty = max(oz.pre_ship_exemplar_quantity(row), 1)
    if len(uniq) < req_qty:
        raise RuntimeError(
            f"Нужно {req_qty} код(ов) КИЗ — сейчас {len(uniq)}"
        )
    gtd_clean = gtd_mod.normalize_gtd_number(gtd_number) or str(gtd_number or "").strip()
    if not gtd_clean:
        raise RuntimeError("Укажите номер ГТД")

    # Persist draft first so a failed push does not lose scanned codes.
    local_res = update_posting_marking_codes(
        repo,
        user_id=user_id,
        source_id=source_id,
        posting_number=pn,
        codes=uniq,
        gtd_number=gtd_clean,
        ozon_synced=False,
        force=True,
    )

    client = oz.OzonFbsClient(client_id, api_key)
    try:
        remote = client.get_posting(pn)
        if isinstance(remote, dict) and remote.get("posting_number"):
            posting = remote
    except Exception:
        pass

    try:
        push_out = push_marking_to_ozon(
            client,
            posting_number=pn,
            posting=posting,
            codes=uniq,
            gtd=gtd_clean,
            prefer_gtd_products=True,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Коды сохранены локально, но Ozon не принял данные: {exc}"
        ) from exc

    local_res = update_posting_marking_codes(
        repo,
        user_id=user_id,
        source_id=source_id,
        posting_number=pn,
        codes=uniq,
        gtd_number=gtd_clean,
        ozon_synced=True,
        force=True,
    )
    return {
        "ok": True,
        "posting_number": pn,
        "kiz_codes": list(local_res.get("codes") or uniq),
        "gtd_number": gtd_clean,
        "marking_ozon_synced": True,
        "kiz_saved_at": str(local_res.get("saved_at") or ""),
        "already_defined": bool(push_out.get("already_defined")),
        "message": (
            "Данные экземпляров уже были в Ozon — отметили как синхронизированные"
            if push_out.get("already_defined")
            else "Маркировка и ГТД переданы в Ozon"
        ),
    }


def save_marking(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    items: list[dict[str, Any]],
    allowed_posting_numbers: set[str] | None = None,
    client_id: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Save marking codes locally; push to Ozon when GTD/юрлицо row is complete.

    Unchanged payloads that were already autosaved (and synced to Ozon when
    required) are returned as ``unchanged`` without rewriting DB or re-pushing.
    """
    results: list[dict[str, Any]] = []
    ok_n = 0
    err_n = 0
    skipped_n = 0
    cid = str(client_id or "").strip()
    key = str(api_key or "").strip()
    client: oz.OzonFbsClient | None = (
        oz.OzonFbsClient(cid, key) if cid and key else None
    )
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
    prev_map = load_marking_map(
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
        from . import supply_gtd as gtd_mod

        gtd_raw = str(raw.get("gtd_number") or "").strip()
        gtd_clean = gtd_mod.normalize_gtd_number(gtd_raw) or gtd_raw
        row = _load_posting_row(
            repo, user_id=user_id, source_id=source_id, posting_number=pn
        ) or {}
        gtd_required = oz.posting_requires_pre_ship_gtd(row)
        if gtd_required and not gtd_clean:
            gtd_clean = str(row.get("marking_gtd_number") or "").strip()
        prev = prev_map.get(pn) or {}
        prev_codes = list(prev.get("codes") or [])
        prev_gtd = str(prev.get("gtd_number") or "").strip()
        prev_synced = bool(prev.get("ozon_synced"))
        prev_saved = str(prev.get("saved_at") or "")
        codes_same = prev_codes == uniq
        gtd_same = prev_gtd == str(gtd_clean or "")
        # Autosave already persisted (+ pushed for юрлицо). Final «Сохранить»
        # must not wipe marking_ozon_synced and re-push every posting to Ozon.
        if not clear and codes_same and gtd_same:
            if not (gtd_required and uniq):
                ok_n += 1
                results.append(
                    {
                        "posting_number": pn,
                        "ok": True,
                        "kiz_codes": uniq,
                        "kiz_saved_at": prev_saved,
                        "gtd_number": gtd_clean,
                        "kiz_ozon_synced": bool(prev_synced),
                        "unchanged": True,
                    }
                )
                continue
            if not gtd_clean:
                err_n += 1
                results.append(
                    {
                        "posting_number": pn,
                        "ok": False,
                        "kiz_codes": uniq,
                        "kiz_saved_at": prev_saved,
                        "gtd_number": "",
                        "kiz_ozon_synced": False,
                        "error": "Для юрлица укажите ГТД перед сохранением в Ozon",
                    }
                )
                continue
            if prev_synced:
                ok_n += 1
                results.append(
                    {
                        "posting_number": pn,
                        "ok": True,
                        "kiz_codes": uniq,
                        "kiz_saved_at": prev_saved,
                        "gtd_number": gtd_clean,
                        "kiz_ozon_synced": True,
                        "unchanged": True,
                    }
                )
                continue
            # Local payload unchanged, Ozon not synced yet — push only.
            if not client:
                err_n += 1
                results.append(
                    {
                        "posting_number": pn,
                        "ok": False,
                        "kiz_codes": uniq,
                        "kiz_saved_at": prev_saved,
                        "gtd_number": gtd_clean,
                        "kiz_ozon_synced": False,
                        "error": (
                            "Коды сохранены локально, но нет доступа к API Ozon "
                            "для передачи КИЗ/ГТД"
                        ),
                    }
                )
                continue
            posting = oz._posting_payload_from_row(row) or {}
            try:
                push_marking_to_ozon(
                    client,
                    posting_number=pn,
                    posting=posting,
                    codes=uniq,
                    gtd=gtd_clean,
                    prefer_gtd_products=True,
                )
                synced_res = update_posting_marking_codes(
                    repo,
                    user_id=user_id,
                    source_id=source_id,
                    posting_number=pn,
                    codes=uniq,
                    gtd_number=gtd_clean,
                    ozon_synced=True,
                    force=True,
                )
                ok_n += 1
                results.append(
                    {
                        "posting_number": pn,
                        "ok": True,
                        "kiz_codes": list(synced_res.get("codes") or uniq),
                        "kiz_saved_at": str(synced_res.get("saved_at") or prev_saved),
                        "gtd_number": gtd_clean,
                        "kiz_ozon_synced": True,
                    }
                )
            except Exception as exc:
                _log.warning("ozon supply marking push %s: %s", pn, exc)
                err_n += 1
                results.append(
                    {
                        "posting_number": pn,
                        "ok": False,
                        "kiz_codes": uniq,
                        "kiz_saved_at": prev_saved,
                        "gtd_number": gtd_clean,
                        "kiz_ozon_synced": False,
                        "error": f"Сохранено локально, Ozon не принял: {exc}",
                        "push_warning": str(exc),
                    }
                )
            continue
        local_res = update_posting_marking_codes(
            repo,
            user_id=user_id,
            source_id=source_id,
            posting_number=pn,
            codes=uniq,
            gtd_number=gtd_clean if gtd_clean else None,
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
        push_error = ""
        ozon_synced = False
        if local_ok and gtd_required and uniq:
            if not gtd_clean:
                local_ok = False
                err_n += 1
                results.append(
                    {
                        "posting_number": pn,
                        "ok": False,
                        "kiz_codes": list(local_res.get("codes") or uniq),
                        "kiz_saved_at": str(local_res.get("saved_at") or ""),
                        "gtd_number": "",
                        "error": "Для юрлица укажите ГТД перед сохранением в Ozon",
                    }
                )
                continue
            if not client:
                local_ok = False
                err_n += 1
                results.append(
                    {
                        "posting_number": pn,
                        "ok": False,
                        "kiz_codes": list(local_res.get("codes") or uniq),
                        "kiz_saved_at": str(local_res.get("saved_at") or ""),
                        "gtd_number": gtd_clean,
                        "error": (
                            "Коды сохранены локально, но нет доступа к API Ozon "
                            "для передачи КИЗ/ГТД"
                        ),
                    }
                )
                continue
            posting = oz._posting_payload_from_row(row) or {}
            try:
                push_marking_to_ozon(
                    client,
                    posting_number=pn,
                    posting=posting,
                    codes=uniq,
                    gtd=gtd_clean,
                    prefer_gtd_products=True,
                )
                ozon_synced = True
                update_posting_marking_codes(
                    repo,
                    user_id=user_id,
                    source_id=source_id,
                    posting_number=pn,
                    codes=uniq,
                    gtd_number=gtd_clean,
                    ozon_synced=True,
                    force=True,
                )
            except Exception as exc:
                push_error = str(exc)
                _log.warning("ozon supply marking push %s: %s", pn, exc)
                err_n += 1
                results.append(
                    {
                        "posting_number": pn,
                        "ok": False,
                        "kiz_codes": list(local_res.get("codes") or uniq),
                        "kiz_saved_at": str(local_res.get("saved_at") or ""),
                        "gtd_number": gtd_clean,
                        "kiz_ozon_synced": False,
                        "error": f"Сохранено локально, Ozon не принял: {push_error}",
                        "push_warning": push_error,
                    }
                )
                continue
        if local_ok:
            ok_n += 1
        else:
            err_n += 1
        item_out: dict[str, Any] = {
            "posting_number": pn,
            "ok": local_ok,
            "kiz_codes": list(local_res.get("codes") or uniq),
            "kiz_saved_at": str(local_res.get("saved_at") or ""),
            "gtd_number": gtd_clean,
            "kiz_ozon_synced": ozon_synced,
        }
        results.append(item_out)
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
    gtd_number: str | None = None,
) -> dict[str, Any]:
    """Persist marking codes locally (FeedPilot).

    Optimistic concurrency matches WB FBS ``update_order_kiz_codes``:
    refuse only when ``expected_saved_at`` is set, timestamps differ **and**
    stored codes differ from the payload. Same codes / timestamp string
    round-trips must not report «another operator».
    """
    pn = str(posting_number or "").strip()
    if not pn:
        return {"ok": False, "missing": True, "conflict": False, "codes": [], "saved_at": ""}
    oz.ensure_ozon_fbs_tables(repo)
    clean = [_normalize_mark_code(c) for c in codes if _normalize_mark_code(c)]
    now = datetime.now(UTC)
    expected = wb._normalize_kiz_saved_at(expected_saved_at)
    gtd_set = gtd_number is not None
    gtd_clean = str(gtd_number or "").strip() if gtd_set else ""
    with repo._connect() as conn:
        row = conn.execute(
            repo._sql(
                """
                SELECT marking_codes_json, marking_saved_at, marking_gtd_number
                FROM ozon_fbs_postings
                WHERE user_id = ? AND source_id = ? AND posting_number = ?
                """
            ),
            (user_id, source_id, pn),
        ).fetchone()
        if not row:
            return {
                "ok": False,
                "missing": True,
                "conflict": False,
                "codes": clean,
                "saved_at": "",
            }
        d = repo._row_to_dict(row)
        prev_saved = wb._normalize_kiz_saved_at(d.get("marking_saved_at"))
        prev_codes = _parse_codes(d.get("marking_codes_json"))
        if (
            not force
            and expected
            and prev_saved
            and expected != prev_saved
            and prev_codes != clean
        ):
            _log.info(
                "ozon marking save conflict posting=%s expected=%r current=%r",
                pn,
                expected,
                prev_saved,
            )
            return {
                "ok": False,
                "missing": False,
                "conflict": True,
                "codes": prev_codes,
                "saved_at": prev_saved,
            }
        if gtd_set:
            conn.execute(
                repo._sql(
                    """
                    UPDATE ozon_fbs_postings
                    SET marking_codes_json = ?,
                        marking_saved_at = ?,
                        marking_ozon_synced = ?,
                        marking_gtd_number = ?
                    WHERE user_id = ? AND source_id = ? AND posting_number = ?
                    """
                ),
                (
                    json.dumps(clean, ensure_ascii=False),
                    now,
                    repo._bool_db(ozon_synced),
                    gtd_clean,
                    user_id,
                    source_id,
                    pn,
                ),
            )
        else:
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
    return {
        "ok": True,
        "missing": False,
        "conflict": False,
        "codes": clean,
        "saved_at": wb._normalize_kiz_saved_at(now),
        "gtd_number": gtd_clean if gtd_set else str(d.get("marking_gtd_number") or ""),
    }


def check_supply_marking_status(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
    client_id: str | None = None,
    api_key: str | None = None,
    refresh_from_ozon: bool = False,
    posting_tab: str | None = None,
) -> dict[str, Any]:
    """Local check: are all КИЗ fields filled for kiz_required postings in supply."""
    del client_id, api_key, refresh_from_ozon
    tab_key = str(posting_tab or "").strip() or None
    detail = oz_sup.get_supply_detail(
        repo,
        user_id=user_id,
        source_id=source_id,
        supply_id=supply_id,
        posting_tab=tab_key,
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
