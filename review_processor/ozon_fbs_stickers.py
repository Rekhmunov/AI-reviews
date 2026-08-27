"""Ozon FBS sticker binding and lookup (parity with WB FBS sticker → order)."""
from __future__ import annotations

import json
import re
from typing import Any

from . import ozon_fbs as oz
from . import ozon_fbs_scans as oz_scans
from . import wb_fbs as wb
from .wb_fbs_kiz_restore import normalize_sticker_scan, sticker_number
from .repository import ReviewRepository

_POSTING_SCAN_SELECT = """
    posting_number, order_id, order_number, supply_id, tab, status,
    offer_id, sku, product_name, marking_codes_json, marking_saved_at,
    pick_verified, pick_barcode, pick_verified_at,
    sticker_barcode, sticker_part_a, sticker_part_b, sticker_lower_barcode,
    raw_json
"""

_MATCH_LIMIT = 50


def _sticker_scan_key(value: object) -> str:
    return normalize_sticker_scan(value).casefold()


def _fetch_posting_rows(
    repo: ReviewRepository,
    conn: Any,
    *,
    user_id: int,
    source_id: int,
    where_sql: str,
    params: tuple[Any, ...],
) -> list[dict[str, Any]]:
    rows = conn.execute(
        repo._sql(
            f"""
            SELECT {_POSTING_SCAN_SELECT}
            FROM ozon_fbs_postings
            WHERE user_id = ? AND source_id = ?
              AND {where_sql}
            LIMIT {_MATCH_LIMIT}
            """
        ),
        (int(user_id), int(source_id), *params),
    ).fetchall()
    return [repo._row_to_dict(r) for r in rows]


def _resolve_matches(matches: list[dict[str, Any]]) -> dict[str, Any]:
    if len(matches) == 1:
        return {"row": matches[0], "ambiguous": False, "matches": matches}
    if len(matches) > 1:
        return {"row": None, "ambiguous": True, "matches": matches}
    return {"row": None, "ambiguous": False, "matches": []}


def _sticker_fields_for_scan_row(row: dict[str, Any]) -> dict[str, str]:
    """Resolved sticker fields for lookup (DB columns + Ozon raw_json barcodes)."""
    payload = oz.posting_sticker_payload_from_row(row)
    return {
        "sticker_barcode": str(payload.get("sticker_barcode") or "").strip(),
        "sticker_lower_barcode": str(payload.get("sticker_lower_barcode") or "").strip(),
        "sticker_part_a": str(payload.get("sticker_part_a") or "").strip(),
        "sticker_part_b": str(payload.get("sticker_part_b") or "").strip(),
    }


def _row_matches_sticker_scan(row: dict[str, Any], raw: str, raw_key: str, digits: str) -> bool:
    fields = _sticker_fields_for_scan_row(row)
    bc = fields["sticker_barcode"]
    bc_low = fields["sticker_lower_barcode"]
    if bc and _sticker_scan_key(bc) == raw_key:
        return True
    if bc_low and _sticker_scan_key(bc_low) == raw_key:
        return True
    part_a = normalize_sticker_scan(fields["sticker_part_a"])
    part_b = normalize_sticker_scan(fields["sticker_part_b"])
    full = normalize_sticker_scan(sticker_number(part_a, part_b))
    pn = str(row.get("posting_number") or "").strip()
    pn_lower = pn.casefold()
    raw_lower = raw.casefold()
    if pn_lower and (pn_lower == raw_lower or raw_lower in pn_lower or pn_lower in raw_lower):
        return True
    return bool(
        (full and (_sticker_scan_key(full) == raw_key or digits == re.sub(r"\D+", "", full)))
        or (part_a and part_b and digits == re.sub(r"\D+", "", f"{part_a}{part_b}"))
        or (
            part_b
            and (_sticker_scan_key(part_b) == raw_key or digits == re.sub(r"\D+", "", part_b))
        )
        or (pn and digits and re.sub(r"\D+", "", pn).endswith(digits[-4:]))
    )


def _fuzzy_match_postings(
    postings: list[dict[str, Any]],
    raw: str,
    raw_key: str,
    digits: str,
) -> list[dict[str, Any]]:
    """Client-parity fuzzy match on a bounded row set."""
    matches: list[dict[str, Any]] = []
    for row in postings:
        if _row_matches_sticker_scan(row, raw, raw_key, digits):
            matches.append(row)
    return matches


def find_postings_by_sticker_scan(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    scan: str,
) -> dict[str, Any]:
    """Find local posting row(s) by scanned sticker QR / posting_number fragment."""
    raw = normalize_sticker_scan(scan)
    if not raw:
        return {"row": None, "ambiguous": False, "matches": []}
    raw_key = _sticker_scan_key(raw)
    digits = re.sub(r"\D+", "", raw)

    oz.ensure_ozon_fbs_tables(repo)
    with repo._connect() as conn:
        # 1) Exact sticker barcode (indexed).
        rows = _fetch_posting_rows(
            repo,
            conn,
            user_id=user_id,
            source_id=source_id,
            where_sql="sticker_barcode <> '' AND sticker_barcode = ?",
            params=(raw,),
        )
        if rows:
            by_bc = [
                r
                for r in rows
                if _sticker_scan_key(r.get("sticker_barcode")) == raw_key
            ]
            if by_bc:
                return _resolve_matches(by_bc)

        # 1b) Exact lower_barcode (нижняя этикетка Ozon).
        rows = _fetch_posting_rows(
            repo,
            conn,
            user_id=user_id,
            source_id=source_id,
            where_sql="sticker_lower_barcode <> '' AND sticker_lower_barcode = ?",
            params=(raw,),
        )
        if rows:
            by_low = [
                r
                for r in rows
                if _sticker_scan_key(r.get("sticker_lower_barcode")) == raw_key
            ]
            if by_low:
                return _resolve_matches(by_low)

        # 2) Exact posting_number (case-insensitive).
        rows = _fetch_posting_rows(
            repo,
            conn,
            user_id=user_id,
            source_id=source_id,
            where_sql="posting_number ILIKE ?",
            params=(raw,),
        )
        exact_pn = [
            r
            for r in rows
            if str(r.get("posting_number") or "").strip().casefold() == raw.casefold()
        ]
        if exact_pn:
            return _resolve_matches(exact_pn)

        # 3) Partial posting_number (bounded).
        if len(raw) >= 4:
            rows = _fetch_posting_rows(
                repo,
                conn,
                user_id=user_id,
                source_id=source_id,
                where_sql="posting_number ILIKE ?",
                params=(f"%{raw}%",),
            )
            fuzzy = _fuzzy_match_postings(rows, raw, raw_key, digits)
            if fuzzy:
                return _resolve_matches(fuzzy)

        # 4) Sticker part_b exact.
        rows = _fetch_posting_rows(
            repo,
            conn,
            user_id=user_id,
            source_id=source_id,
            where_sql="sticker_part_b <> '' AND sticker_part_b = ?",
            params=(raw,),
        )
        if rows:
            return _resolve_matches(rows)

        # 5) Digit tail on posting_number (last 4+ digits).
        if len(digits) >= 4:
            tail = digits[-4:]
            rows = _fetch_posting_rows(
                repo,
                conn,
                user_id=user_id,
                source_id=source_id,
                where_sql=(
                    "regexp_replace(posting_number, '[^0-9]', '', 'g') LIKE ?"
                ),
                params=(f"%{tail}",),
            )
            by_tail = [
                r
                for r in rows
                if re.sub(r"\D+", "", str(r.get("posting_number") or "")).endswith(tail)
            ]
            if by_tail:
                return _resolve_matches(by_tail)

        # 6) Ozon package barcode stored only in raw_json (columns not backfilled yet).
        if len(raw) >= 8:
            rows = _fetch_posting_rows(
                repo,
                conn,
                user_id=user_id,
                source_id=source_id,
                where_sql="raw_json ILIKE ?",
                params=(f"%{raw}%",),
            )
            by_raw = [r for r in rows if _row_matches_sticker_scan(r, raw, raw_key, digits)]
            if by_raw:
                return _resolve_matches(by_raw)

    return {"row": None, "ambiguous": False, "matches": []}


def lookup_posting_by_scan(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    scan: str,
    record_journal: bool = True,
) -> dict[str, Any]:
    """Return posting with local marking, pick-verify, and sticker binding."""
    found = find_postings_by_sticker_scan(
        repo, user_id=user_id, source_id=source_id, scan=scan
    )
    row = found.get("row")
    matched_pns = [
        str(m.get("posting_number") or "").strip()
        for m in (found.get("matches") or [])
        if isinstance(m, dict) and str(m.get("posting_number") or "").strip()
    ]
    if record_journal:
        oz_scans.record_posting_scan(
            repo,
            user_id=user_id,
            source_id=source_id,
            scan_type=oz_scans.SCAN_LOOKUP,
            scan_raw=scan,
            posting_row=row if isinstance(row, dict) else None,
            matched_posting_numbers=matched_pns,
        )
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
