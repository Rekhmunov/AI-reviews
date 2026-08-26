"""Ozon FBS sticker binding and lookup (parity with WB FBS sticker → order)."""
from __future__ import annotations

import json
import re
from typing import Any

from . import ozon_fbs as oz
from . import wb_fbs as wb
from .wb_fbs_kiz_restore import normalize_sticker_scan, sticker_number
from .repository import ReviewRepository


def _sticker_scan_key(value: object) -> str:
    return normalize_sticker_scan(value).casefold()


def find_postings_by_sticker_scan(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    scan: str,
) -> dict[str, Any]:
    """Find local posting row(s) by scanned sticker QR / posting number fragment."""
    raw = normalize_sticker_scan(scan)
    if not raw:
        return {"row": None, "ambiguous": False, "matches": []}
    raw_key = _sticker_scan_key(raw)
    raw_lower = raw.casefold()
    digits = re.sub(r"\D+", "", raw)

    oz.ensure_ozon_fbs_tables(repo)
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                """
                SELECT posting_number, order_id, order_number, supply_id, tab, status,
                       offer_id, sku, product_name, marking_codes_json, marking_saved_at,
                       pick_verified, pick_barcode, pick_verified_at,
                       sticker_barcode, sticker_part_a, sticker_part_b
                FROM ozon_fbs_postings
                WHERE user_id = ? AND source_id = ?
                """
            ),
            (int(user_id), int(source_id)),
        ).fetchall()

    postings = [repo._row_to_dict(r) for r in rows]

    by_barcode: list[dict[str, Any]] = []
    for row in postings:
        bc = normalize_sticker_scan(row.get("sticker_barcode"))
        if bc and _sticker_scan_key(bc) == raw_key:
            by_barcode.append(row)
    if len(by_barcode) == 1:
        return {"row": by_barcode[0], "ambiguous": False, "matches": by_barcode}
    if len(by_barcode) > 1:
        return {"row": None, "ambiguous": True, "matches": by_barcode}

    by_posting_number: list[dict[str, Any]] = []
    for row in postings:
        pn = str(row.get("posting_number") or "").strip()
        if not pn:
            continue
        pn_lower = pn.casefold()
        if pn_lower == raw_lower or raw_lower in pn_lower or pn_lower in raw_lower:
            by_posting_number.append(row)
    if len(by_posting_number) == 1:
        return {"row": by_posting_number[0], "ambiguous": False, "matches": by_posting_number}
    if len(by_posting_number) > 1:
        return {"row": None, "ambiguous": True, "matches": by_posting_number}

    matches: list[dict[str, Any]] = []
    for row in postings:
        full = normalize_sticker_scan(
            sticker_number(row.get("sticker_part_a"), row.get("sticker_part_b"))
        )
        part_a = normalize_sticker_scan(row.get("sticker_part_a"))
        part_b = normalize_sticker_scan(row.get("sticker_part_b"))
        pn = str(row.get("posting_number") or "").strip()
        if (
            (full and (_sticker_scan_key(full) == raw_key or digits == re.sub(r"\D+", "", full)))
            or (part_a and part_b and digits == re.sub(r"\D+", "", f"{part_a}{part_b}"))
            or (
                part_b
                and (_sticker_scan_key(part_b) == raw_key or digits == re.sub(r"\D+", "", part_b))
            )
            or (pn and digits and re.sub(r"\D+", "", pn).endswith(digits[-4:]))
        ):
            matches.append(row)

    if len(matches) == 1:
        return {"row": matches[0], "ambiguous": False, "matches": matches}
    if len(matches) > 1:
        return {"row": None, "ambiguous": True, "matches": matches}

    if digits and len(digits) >= 4:
        tail = digits[-4:]
        by_tail = [
            r
            for r in postings
            if re.sub(r"\D+", "", str(r.get("posting_number") or "")).endswith(tail)
        ]
        if len(by_tail) == 1:
            return {"row": by_tail[0], "ambiguous": False, "matches": by_tail}
        if len(by_tail) > 1:
            return {"row": None, "ambiguous": True, "matches": by_tail}

    return {"row": None, "ambiguous": False, "matches": []}


def lookup_posting_by_scan(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    scan: str,
) -> dict[str, Any]:
    """Return posting with local marking, pick-verify, and sticker binding."""
    found = find_postings_by_sticker_scan(
        repo, user_id=user_id, source_id=source_id, scan=scan
    )
    row = found.get("row")
    if not isinstance(row, dict):
        return {
            "ok": True,
            "found": False,
            "ambiguous": bool(found.get("ambiguous")),
            "matches": [
                oz.posting_sticker_payload_from_row(m)
                for m in (found.get("matches") or [])
                if isinstance(m, dict)
            ],
        }
    try:
        codes = json.loads(str(row.get("marking_codes_json") or "[]"))
    except json.JSONDecodeError:
        codes = []
    if not isinstance(codes, list):
        codes = []
    codes_clean = [wb._kiz_code_clean(x) for x in codes if wb._kiz_code_clean(x)]
    sticker = oz.posting_sticker_payload_from_row(row)
    return {
        "ok": True,
        "found": True,
        "ambiguous": False,
        "posting": {
            **sticker,
            "supply_id": str(row.get("supply_id") or "").strip(),
            "tab": str(row.get("tab") or "").strip(),
            "status": str(row.get("status") or "").strip(),
            "offer_id": str(row.get("offer_id") or "").strip(),
            "sku": row.get("sku"),
            "product_name": str(row.get("product_name") or "").strip(),
            "kiz_codes": codes_clean,
            "kiz_saved_at": wb._normalize_kiz_saved_at(row.get("marking_saved_at")),
            "pick_verified": bool(row.get("pick_verified"))
            and bool(str(row.get("pick_barcode") or "").strip()),
            "pick_barcode": str(row.get("pick_barcode") or "").strip(),
            "pick_verified_at": wb._normalize_kiz_saved_at(row.get("pick_verified_at")),
        },
    }
