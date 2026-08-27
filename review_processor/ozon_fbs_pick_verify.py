"""Ozon FBS local ШК pick-check for supply modal (non-КИЗ postings)."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from . import ozon_fbs as oz
from . import ozon_fbs_supplies as oz_sup
from . import wb_fbs as wb
from . import wb_fbs_detail as wb_detail
from .repository import ReviewRepository

_log = logging.getLogger(__name__)


def load_posting_pick_map(
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
                SELECT posting_number, pick_verified, pick_barcode, pick_verified_at
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
        verified_at = d.get("pick_verified_at")
        out[pn] = {
            "pick_verified": bool(d.get("pick_verified")),
            "pick_barcode": str(d.get("pick_barcode") or "").strip(),
            "pick_verified_at": wb._normalize_kiz_saved_at(verified_at)
            if verified_at
            else "",
        }
    return out


def update_posting_pick_verify(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    posting_number: str,
    verified: bool,
    barcode: str = "",
    expected_verified_at: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Persist local ШК pick-check. No Ozon API calls."""
    oz.ensure_ozon_fbs_tables(repo)
    pn = str(posting_number or "").strip()
    code = str(barcode or "").strip()
    is_ok = bool(verified) and bool(code)
    saved_at = datetime.now(UTC)
    expected = wb._normalize_kiz_saved_at(expected_verified_at)
    with repo._connect() as conn:
        row = conn.execute(
            repo._sql(
                """
                SELECT pick_verified, pick_barcode, pick_verified_at
                FROM ozon_fbs_postings
                WHERE user_id = ? AND source_id = ? AND posting_number = ?
                """
            ),
            (user_id, source_id, pn),
        ).fetchone()
        if not row:
            return {
                "ok": False,
                "conflict": False,
                "missing": True,
                "verified_at": "",
                "verified": False,
                "barcode": "",
            }
        d = repo._row_to_dict(row)
        cur_verified = bool(d.get("pick_verified")) and bool(
            str(d.get("pick_barcode") or "").strip()
        )
        cur_barcode = str(d.get("pick_barcode") or "").strip() if cur_verified else ""
        cur_saved = wb._normalize_kiz_saved_at(d.get("pick_verified_at"))
        new_verified = is_ok
        new_barcode = code if is_ok else ""
        if (
            not force
            and expected
            and cur_saved
            and expected != cur_saved
            and (cur_verified != new_verified or cur_barcode != new_barcode)
        ):
            return {
                "ok": False,
                "conflict": True,
                "missing": False,
                "verified_at": cur_saved,
                "verified": cur_verified,
                "barcode": cur_barcode,
            }
        conn.execute(
            repo._sql(
                """
                UPDATE ozon_fbs_postings
                SET pick_verified = ?, pick_barcode = ?, pick_verified_at = ?
                WHERE user_id = ? AND source_id = ? AND posting_number = ?
                """
            ),
            (
                new_verified,
                new_barcode,
                saved_at if new_verified else None,
                user_id,
                source_id,
                pn,
            ),
        )
    return {
        "ok": True,
        "conflict": False,
        "missing": False,
        "verified_at": wb._normalize_kiz_saved_at(saved_at) if new_verified else "",
        "verified": new_verified,
        "barcode": new_barcode,
    }


def load_posting_barcodes_map(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    posting_numbers: list[str],
) -> dict[str, list[str]]:
    nums = [str(x).strip() for x in posting_numbers if str(x).strip()]
    if not nums:
        return {}
    oz.ensure_ozon_fbs_tables(repo)
    placeholders = ", ".join("?" for _ in nums)
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                f"""
                SELECT posting_number, barcodes_json
                FROM ozon_fbs_postings
                WHERE user_id = ? AND source_id = ?
                  AND posting_number IN ({placeholders})
                """
            ),
            (user_id, source_id, *nums),
        ).fetchall()
    out: dict[str, list[str]] = {}
    for row in rows:
        d = repo._row_to_dict(row)
        pn = str(d.get("posting_number") or "").strip()
        if not pn:
            continue
        try:
            parsed = json.loads(str(d.get("barcodes_json") or "[]"))
        except json.JSONDecodeError:
            parsed = []
        if not isinstance(parsed, list):
            parsed = []
        out[pn] = [str(x).strip() for x in parsed if str(x).strip()]
    return out


def build_pick_verify_payload(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
    client_id: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Rows for «Проверка ШК»: postings without Chestny ZNAK marking."""
    detail = oz_sup.get_supply_detail(
        repo,
        user_id=user_id,
        source_id=source_id,
        supply_id=supply_id,
        client_id=client_id,
        api_key=api_key,
        refresh_from_ozon=True,
    )
    plain_orders = [
        o
        for o in (detail.get("orders") or [])
        if isinstance(o, dict) and not o.get("kiz_required") and not o.get("cancelled")
    ]
    posting_numbers = [
        str(o.get("posting_number") or "").strip()
        for o in plain_orders
        if str(o.get("posting_number") or "").strip()
    ]
    local_pick = load_posting_pick_map(
        repo,
        user_id=user_id,
        source_id=source_id,
        posting_numbers=posting_numbers,
    )
    rows: list[dict[str, Any]] = []
    for o in plain_orders:
        pn = str(o.get("posting_number") or "").strip()
        if not pn:
            continue
        local = local_pick.get(pn) or {}
        verified = bool(local.get("pick_verified")) and bool(
            str(local.get("pick_barcode") or "").strip()
        )
        rows.append(
            {
                "posting_number": pn,
                "product_name": o.get("product_name") or o.get("offer_id") or "",
                "product_photo": o.get("product_photo") or "",
                "offer_id": o.get("offer_id") or "",
                "sku": o.get("sku"),
                "barcodes": list(o.get("barcodes") or []),
                "quantity": int(o.get("quantity") or 1),
                "pick_verified": verified,
                "pick_barcode": str(local.get("pick_barcode") or "").strip()
                if verified
                else "",
                "pick_verified_at": str(local.get("pick_verified_at") or ""),
                "cancel_reason_label": str(o.get("cancel_reason_label") or ""),
                "order_id": o.get("order_id"),
                "order_number": str(o.get("order_number") or "").strip(),
                "sticker_barcode": str(o.get("sticker_barcode") or "").strip(),
                "sticker_lower_barcode": str(o.get("sticker_lower_barcode") or "").strip(),
                "sticker_part_a": str(o.get("sticker_part_a") or "").strip(),
                "sticker_part_b": str(o.get("sticker_part_b") or "").strip(),
            }
        )
    return {
        "ok": True,
        "supply_id": detail.get("supply_id"),
        "source_id": source_id,
        "rows": rows,
        "plain_count": len(rows),
    }


def save_pick_verify(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    items: list[dict[str, Any]],
    allowed_posting_numbers: set[str] | None = None,
) -> dict[str, Any]:
    """Save local ШК pick-check. Never calls Ozon."""
    results: list[dict[str, Any]] = []
    ok_n = 0
    err_n = 0
    skipped_n = 0

    candidate_pns: list[str] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        pn = str(raw.get("posting_number") or "").strip()
        if pn:
            candidate_pns.append(pn)

    trusted_barcodes = load_posting_barcodes_map(
        repo,
        user_id=int(user_id),
        source_id=int(source_id),
        posting_numbers=candidate_pns,
    )

    for raw in items:
        if not isinstance(raw, dict):
            continue
        pn = str(raw.get("posting_number") or "").strip()
        if not pn:
            continue
        if allowed_posting_numbers is not None and pn not in allowed_posting_numbers:
            err_n += 1
            results.append(
                {
                    "posting_number": pn,
                    "ok": False,
                    "error": "Отправление не входит в эту поставку или требует КИЗ",
                }
            )
            continue
        clear = bool(raw.get("clear"))
        verified = bool(raw.get("pick_verified")) and not clear
        barcode = str(raw.get("pick_barcode") or "").strip()
        expected_verified_at = str(raw.get("expected_verified_at") or "").strip()
        force_save = bool(raw.get("force"))
        if not verified and not clear:
            if not barcode:
                skipped_n += 1
                continue
            verified = False
        if verified:
            order_barcodes = trusted_barcodes.get(pn)
            if order_barcodes is None:
                err_n += 1
                results.append(
                    {
                        "posting_number": pn,
                        "ok": False,
                        "error": "Отправление не найдено локально — синхронизируйте FBS и повторите",
                    }
                )
                continue
            ok, normalized, err = wb_detail.validate_ean_against_order_skus(
                barcode, order_barcodes
            )
            if not ok:
                err_n += 1
                results.append({"posting_number": pn, "ok": False, "error": err})
                continue
            barcode = normalized
        try:
            local_res = update_posting_pick_verify(
                repo,
                user_id=int(user_id),
                source_id=int(source_id),
                posting_number=pn,
                verified=verified,
                barcode=barcode if verified else "",
                expected_verified_at=expected_verified_at or None,
                force=force_save,
            )
        except Exception as exc:
            err_n += 1
            results.append(
                {
                    "posting_number": pn,
                    "ok": False,
                    "error": f"Ошибка сохранения: {exc}",
                }
            )
            continue
        if local_res.get("conflict"):
            err_n += 1
            results.append(
                {
                    "posting_number": pn,
                    "ok": False,
                    "conflict": True,
                    "pick_verified": bool(local_res.get("verified")),
                    "pick_barcode": str(local_res.get("barcode") or ""),
                    "pick_verified_at": str(local_res.get("verified_at") or ""),
                    "error": (
                        "Отправление уже сохранено другим оператором — "
                        "проверьте ШК и сохраните снова"
                    ),
                }
            )
            continue
        if not local_res.get("ok"):
            err_n += 1
            results.append(
                {
                    "posting_number": pn,
                    "ok": False,
                    "error": "Отправление не найдено локально — синхронизируйте FBS и повторите",
                }
            )
            continue
        ok_n += 1
        if verified and barcode:
            from . import ozon_fbs_scans as oz_scans

            oz_scans.record_posting_scan(
                repo,
                user_id=user_id,
                source_id=source_id,
                scan_type=oz_scans.SCAN_PICK,
                scan_raw=barcode,
                posting_number=pn,
                pick_barcode=barcode,
            )
        results.append(
            {
                "posting_number": pn,
                "ok": True,
                "pick_verified": bool(local_res.get("verified")),
                "pick_barcode": str(local_res.get("barcode") or ""),
                "pick_verified_at": str(local_res.get("verified_at") or ""),
            }
        )
    return {
        "ok": err_n == 0,
        "saved": ok_n,
        "errors": err_n,
        "skipped": skipped_n,
        "results": results,
    }
