"""WB FBS «Восстановление КИЗ» — reprint the same DataMatrix (no ЧЗ / no new codes)."""

from __future__ import annotations

import base64
import io
import logging
import re
from typing import Any

from . import wb_fbs as wb
from .repository import ReviewRepository

_log = logging.getLogger(__name__)

_GS = "\u001d"
_ARROW_GS = "\u2194"


def normalize_sticker_scan(value: object) -> str:
    """Trim spaces; keep sticker case (WB barcodes are case-sensitive)."""
    return str(value or "").replace(" ", "").replace("\t", "").strip()


def _strip_mark_edges(value: str) -> str:
    return value.strip(" \t\r\n")


def normalize_kiz_mark(value: object) -> str:
    """Parity with desktop ``_wbFbsKizNormalizeMark`` (↔ → GS, no edge trim of GS)."""
    text = (
        str(value or "")
        .replace(_ARROW_GS, _GS)
        .replace("\r", "")
        .replace("\n", "")
    )
    return _strip_mark_edges(text)


def extract_gtin14(mark: object) -> str:
    raw = normalize_kiz_mark(mark)
    if not raw:
        return ""
    m = re.match(r"^01(\d{14})", raw)
    if m:
        return m.group(1)
    m2 = re.search(r"(?:^|[\u001d])01(\d{14})", raw)
    return m2.group(1) if m2 else ""


def extract_kiz_serial(mark: object) -> str:
    """AI 21 serial from a GS1 DataMatrix / Chestny ZNAK payload."""
    raw = normalize_kiz_mark(mark)
    if not raw:
        return ""
    m = re.match(r"^01\d{14}21(.+)$", raw)
    if not m:
        return ""
    tail = m.group(1)
    if _GS in tail:
        tail = tail.split(_GS, 1)[0]
    if tail.startswith("91"):
        return ""
    return tail.strip()


def looks_like_kiz_scan(scan: object) -> bool:
    """True when scan looks like a GS1 DataMatrix / Chestny ZNAK payload."""
    raw = normalize_kiz_mark(scan)
    if not raw:
        return False
    if extract_gtin14(raw):
        return True
    # Legacy scanners: long digit+letter payload without explicit AI 01 at start.
    if len(raw) >= 20 and raw.startswith("01") and any(c.isalpha() for c in raw):
        return True
    return _GS in raw and bool(re.search(r"\d{8,}", raw))


def sticker_number(part_a: object, part_b: object) -> str:
    a = str(part_a or "").strip()
    b = str(part_b or "").strip()
    if a and b:
        return f"{a}{b}"
    return a or b


def _sticker_scan_key(value: object) -> str:
    return normalize_sticker_scan(value).casefold()


def find_orders_by_sticker_scan(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    scan: str,
) -> dict[str, Any]:
    """Mirror desktop ``_wbFbsKizFindBySticker`` against local DB."""
    raw = normalize_sticker_scan(scan)
    if not raw:
        return {"row": None, "ambiguous": False, "matches": []}
    raw_key = _sticker_scan_key(raw)
    digits = re.sub(r"\D+", "", raw)

    wb.ensure_wb_fbs_tables(repo)
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                """
                SELECT order_id, sticker_barcode, sticker_part_a, sticker_part_b,
                       article, nm_id, skus_json, kiz_codes_json, supply_id, tab
                FROM wb_fbs_orders
                WHERE user_id = ? AND source_id = ?
                  AND (
                    sticker_barcode <> ''
                    OR sticker_part_b <> ''
                    OR sticker_part_a <> ''
                  )
                """
            ),
            (int(user_id), int(source_id)),
        ).fetchall()

    orders = [repo._row_to_dict(r) for r in rows]
    by_barcode: list[dict[str, Any]] = []
    for row in orders:
        bc = normalize_sticker_scan(row.get("sticker_barcode"))
        if bc and _sticker_scan_key(bc) == raw_key:
            by_barcode.append(row)
    if len(by_barcode) == 1:
        return {"row": by_barcode[0], "ambiguous": False, "matches": by_barcode}
    if len(by_barcode) > 1:
        return {"row": None, "ambiguous": True, "matches": by_barcode}

    matches: list[dict[str, Any]] = []
    for row in orders:
        full = normalize_sticker_scan(
            sticker_number(row.get("sticker_part_a"), row.get("sticker_part_b"))
        )
        part_a = normalize_sticker_scan(row.get("sticker_part_a"))
        part_b = normalize_sticker_scan(row.get("sticker_part_b"))
        if (
            (full and (_sticker_scan_key(full) == raw_key or digits == re.sub(r"\D+", "", full)))
            or (part_a and part_b and digits == re.sub(r"\D+", "", f"{part_a}{part_b}"))
            or (
                part_b
                and (_sticker_scan_key(part_b) == raw_key or digits == re.sub(r"\D+", "", part_b))
            )
        ):
            matches.append(row)
    if len(matches) == 1:
        return {"row": matches[0], "ambiguous": False, "matches": matches}
    if len(matches) > 1:
        exact = next(
            (
                r
                for r in matches
                if _sticker_scan_key(
                    sticker_number(r.get("sticker_part_a"), r.get("sticker_part_b"))
                )
                == raw_key
                or re.sub(
                    r"\D+",
                    "",
                    sticker_number(r.get("sticker_part_a"), r.get("sticker_part_b")),
                )
                == digits
            ),
            None,
        )
        if exact:
            return {"row": exact, "ambiguous": False, "matches": [exact]}
        return {"row": None, "ambiguous": True, "matches": matches}
    return {"row": None, "ambiguous": False, "matches": []}


def _kiz_codes_from_local_row(row: dict[str, Any]) -> list[str]:
    import json

    try:
        parsed = json.loads(str(row.get("kiz_codes_json") or "[]"))
    except Exception:
        parsed = []
    if not isinstance(parsed, list):
        return []
    return [wb._kiz_code_clean(x) for x in parsed if wb._kiz_code_clean(x)]


def _kiz_codes_from_wb_meta(client: wb.WbFbsClient, order_id: int) -> list[str]:
    from . import wb_fbs_detail as detail

    try:
        meta_rows = client.get_orders_meta([int(order_id)])
    except Exception as exc:
        _log.warning("kiz_restore meta fetch failed order=%s: %s", order_id, exc)
        return []
    for row in meta_rows:
        if not isinstance(row, dict):
            continue
        try:
            oid = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        if oid != int(order_id):
            continue
        parsed = detail._kiz_from_meta_row(row)
        codes = [
            wb._kiz_code_clean(x)
            for x in (parsed.get("kiz_codes") or [])
            if wb._kiz_code_clean(x)
        ]
        return codes
    return []


def load_kiz_for_order(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    order_id: int,
    api_key: str = "",
    order_row: dict[str, Any] | None = None,
    srid_hint: str = "",
) -> list[str]:
    """Local marking, then local «Вывод КИЗ» journal, then WB ``orders/meta``."""
    oid = int(order_id)
    local = order_row
    if local is None:
        local = wb.get_order_by_id(
            repo, user_id=user_id, source_id=source_id, order_id=oid
        )
    if local:
        codes = _kiz_codes_from_local_row(local)
        if codes:
            return codes
    try:
        from . import wb_kiz_circulation as kiz_circ

        codes = kiz_circ.load_kiz_codes_for_order(
            repo,
            user_id=user_id,
            source_id=source_id,
            order_id=oid,
            order_row=local,
            srid_hint=srid_hint,
            prefer_return=True,
        )
        if codes:
            return codes
    except Exception as exc:
        _log.warning("kiz circulation lookup failed order=%s: %s", oid, exc)
    key = str(api_key or "").strip()
    if not key:
        return []
    client = wb.WbFbsClient(key)
    return _kiz_codes_from_wb_meta(client, oid)


def kiz_datamatrix_png_base64(code: str, *, scale: int = 4) -> str:
    """Render GS1 DataMatrix PNG (base64, no data: prefix)."""
    from PIL import Image
    from pylibdmtx.pylibdmtx import encode

    payload = normalize_kiz_mark(code)
    if not payload:
        raise ValueError("Пустой код КИЗ")
    enc = encode(payload.encode("utf-8"))
    if enc is None:
        raise ValueError("Не удалось сформировать DataMatrix")
    img = Image.frombytes("RGB", (enc.width, enc.height), enc.pixels)
    px = max(2, min(8, int(scale)))
    if px != 1:
        img = img.resize((enc.width * px, enc.height * px), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def kiz_mark_key(value: object) -> str:
    """Canonical key for comparing two КИЗ payloads (GS / ↔ preserved)."""
    return normalize_kiz_mark(value)


def find_kiz_in_local_database(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    kiz_code: str,
) -> dict[str, Any]:
    """Find orders in local ``kiz_codes_json`` that contain this exact КИЗ."""
    needle = kiz_mark_key(kiz_code)
    if not needle:
        return {"found": False, "order_ids": [], "matches": []}

    wb.ensure_wb_fbs_tables(repo)
    matches: list[dict[str, Any]] = []
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                """
                SELECT order_id, kiz_codes_json, article, supply_id, tab
                FROM wb_fbs_orders
                WHERE user_id = ? AND source_id = ?
                  AND kiz_codes_json IS NOT NULL
                  AND kiz_codes_json <> '[]'
                """
            ),
            (int(user_id), int(source_id)),
        ).fetchall()

    for row in rows:
        d = repo._row_to_dict(row)
        codes = _kiz_codes_from_local_row(d)
        if not any(kiz_mark_key(c) == needle for c in codes):
            continue
        try:
            oid = int(d.get("order_id"))
        except (TypeError, ValueError, KeyError):
            continue
        matches.append(
            {
                "order_id": oid,
                "article": str(d.get("article") or "").strip(),
                "supply_id": str(d.get("supply_id") or "").strip(),
                "tab": str(d.get("tab") or "").strip(),
            }
        )

    order_ids = [int(m["order_id"]) for m in matches]
    return {"found": bool(matches), "order_ids": order_ids, "matches": matches}


def resolve_order_for_restore(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    order_id: int,
    api_key: str = "",
) -> dict[str, Any] | None:
    """Local order row, else same remote lookup path as supplies search."""
    oid = int(order_id)
    local = wb.get_order_by_id(
        repo, user_id=user_id, source_id=source_id, order_id=oid
    )
    if local:
        return local

    key = str(api_key or "").strip()
    if not key:
        return None

    lookup = wb.lookup_order_by_id(
        repo,
        user_id=user_id,
        source_id=source_id,
        order_id=oid,
        api_key=key,
        allow_remote=True,
    )
    if not lookup.get("found"):
        return None

    stored = wb.get_order_by_id(
        repo, user_id=user_id, source_id=source_id, order_id=oid
    )
    row: dict[str, Any] | None = stored
    if row is None:
        item = lookup.get("item")
        row = dict(item) if isinstance(item, dict) else None
    if row is None:
        return None

    try:
        from . import wb_fbs_detail as detail

        client = wb.WbFbsClient(key)
        enriched = detail.attach_sticker_parts_to_orders(
            client, [dict(row)], api_key=key
        )
        if enriched:
            detail.persist_stickers_from_enriched_orders(
                repo,
                user_id=user_id,
                source_id=source_id,
                orders=enriched,
            )
            refreshed = wb.get_order_by_id(
                repo, user_id=user_id, source_id=source_id, order_id=oid
            )
            if refreshed:
                return refreshed
            return enriched[0]
    except Exception as exc:
        _log.warning("resolve_order_for_restore stickers order=%s: %s", oid, exc)

    return row


def kiz_restore_lookup(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    api_key: str = "",
    scan: str | None = None,
    order_id: int | None = None,
) -> dict[str, Any]:
    """Resolve a KIZ code for restore/print.

    Modes:
    - ``kiz`` — scan is already a DataMatrix payload;
    - ``sticker`` — sticker scan → order → stored KIZ;
    - ``order`` — explicit order number → stored KIZ.
    """
    scan_text = normalize_sticker_scan(scan) if scan else ""
    oid_hint = order_id
    if oid_hint is None and scan_text and re.fullmatch(r"\d{6,}", scan_text):
        try:
            oid_hint = int(scan_text)
        except (TypeError, ValueError):
            oid_hint = None

    if scan_text and looks_like_kiz_scan(scan_text):
        code = normalize_kiz_mark(scan_text)
        try:
            dm = kiz_datamatrix_png_base64(code)
        except ValueError as exc:
            return {
                "ok": False,
                "error": "datamatrix_failed",
                "message": str(exc) or "Не удалось сформировать DataMatrix",
            }
        db_hit = find_kiz_in_local_database(
            repo,
            user_id=user_id,
            source_id=source_id,
            kiz_code=code,
        )
        matched_ids = list(db_hit.get("order_ids") or [])
        out: dict[str, Any] = {
            "ok": True,
            "mode": "kiz",
            "order_id": matched_ids[0] if len(matched_ids) == 1 else oid_hint,
            "kiz_code": code,
            "datamatrix_png": dm,
            "in_local_database": bool(db_hit.get("found")),
            "matched_order_ids": matched_ids[:20],
        }
        if not db_hit.get("found"):
            out["database_warning"] = (
                "Такой КИЗ в локальной базе не найден. "
                "Возможно, код отсканирован с ошибкой или он не сохранялся в FeedPilot."
            )
        elif len(matched_ids) > 1:
            out["database_warning"] = (
                f"КИЗ найден у нескольких заказов: {', '.join(str(x) for x in matched_ids[:5])}"
                f"{'…' if len(matched_ids) > 5 else ''}."
            )
        return out

    resolved_order: dict[str, Any] | None = None
    mode = "order"

    if scan_text and not looks_like_kiz_scan(scan_text):
        found = find_orders_by_sticker_scan(
            repo, user_id=user_id, source_id=source_id, scan=scan_text
        )
        if found.get("ambiguous"):
            ids = [
                int(r.get("order_id"))
                for r in (found.get("matches") or [])
                if r.get("order_id") is not None
            ]
            return {
                "ok": False,
                "error": "ambiguous_sticker",
                "message": "Код стикера совпадает у нескольких заказов",
                "order_ids": ids[:10],
            }
        if found.get("row"):
            resolved_order = found["row"]
            mode = "sticker"

    if resolved_order is None and oid_hint is not None:
        resolved_order = resolve_order_for_restore(
            repo,
            user_id=user_id,
            source_id=source_id,
            order_id=int(oid_hint),
            api_key=api_key,
        )
        mode = "order"

    if resolved_order is None:
        if scan_text:
            return {
                "ok": False,
                "error": "not_found",
                "message": "Заказ по стикеру не найден. Укажите номер заказа или отсканируйте КИЗ.",
            }
        return {
            "ok": False,
            "error": "missing_input",
            "message": "Отсканируйте стикер WB, КИЗ или укажите номер заказа",
        }

    try:
        oid = int(resolved_order.get("order_id"))
    except (TypeError, ValueError, KeyError):
        return {
            "ok": False,
            "error": "not_found",
            "message": "Некорректный заказ",
        }

    codes = load_kiz_for_order(
        repo,
        user_id=user_id,
        source_id=source_id,
        order_id=oid,
        api_key=api_key,
    )
    if not codes:
        return {
            "ok": False,
            "error": "no_kiz",
            "message": f"Для заказа {oid} не найден сохранённый КИЗ",
            "order_id": oid,
        }

    code = codes[0]
    try:
        dm = kiz_datamatrix_png_base64(code)
    except ValueError as exc:
        return {
            "ok": False,
            "error": "datamatrix_failed",
            "message": str(exc) or "Не удалось сформировать DataMatrix",
            "order_id": oid,
        }
    part_a = str(resolved_order.get("sticker_part_a") or "").strip()
    part_b = str(resolved_order.get("sticker_part_b") or "").strip()
    return {
        "ok": True,
        "mode": mode,
        "order_id": oid,
        "kiz_code": code,
        "kiz_codes": codes,
        "sticker_number": sticker_number(part_a, part_b),
        "sticker_barcode": str(resolved_order.get("sticker_barcode") or "").strip(),
        "article": str(resolved_order.get("article") or "").strip(),
        "supply_id": str(resolved_order.get("supply_id") or "").strip(),
        "tab": str(resolved_order.get("tab") or "").strip(),
        "datamatrix_png": dm,
    }
