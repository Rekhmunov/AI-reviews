"""One-shot Ozon FBS КИЗ diagnostic for agent investigation.

Writes /tmp/ozon_fbs_kiz_diag.json once at startup, then no-ops if the file exists.
Safe to remove after the investigation.
"""

from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_OUT = Path("/tmp/ozon_fbs_kiz_diag.json")
_TARGET_PN = "0128881603-0039-1"
_TARGET_OFFER = "664575"
_TARGET_UUID = "4ccd4da7-e52f-46e0-a6da-6053662be1b4"
_SOURCE_ID = 18
_SUPPLY_CANDIDATES = (
    "OZ-FBS-18-20260827-34E5D0",
    "OZ-FBS-18-20260827-018D82",
)


def _safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe(x) for x in obj[:50]]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def run_ozon_fbs_kiz_agent_diag(repository: Any) -> None:
    if _OUT.exists():
        return
    out: dict[str, Any] = {"ok": False, "steps": []}
    try:
        from . import ozon_fbs as oz

        src_full = repository.get_supply_source_with_key(
            user_id=1, source_id=_SOURCE_ID
        )
        if not src_full:
            # try discover owner via supplies table
            with repository._connect() as conn:
                row = conn.execute(
                    repository._sql(
                        """
                        SELECT user_id FROM ozon_fbs_supplies
                        WHERE source_id = ? ORDER BY created_at DESC LIMIT 1
                        """
                    ),
                    (_SOURCE_ID,),
                ).fetchone()
            uid = int(row["user_id"] if row and hasattr(row, "keys") else (row[0] if row else 0) or 0)
            if uid:
                src_full = repository.get_supply_source_with_key(
                    user_id=uid, source_id=_SOURCE_ID
                )
        if not src_full:
            out["error"] = "source 18 not found"
            _OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            return
        client_id = str(src_full.get("client_id") or "").strip()
        api_key = str(src_full.get("api_key") or "").strip()
        user_id = int(src_full.get("user_id") or 1)

        out["source"] = {
            "id": _SOURCE_ID,
            "user_id": user_id,
            "has_client_id": bool(client_id),
            "has_api_key": bool(api_key),
            "name": str(src_full.get("name") or ""),
        }
        if not client_id or not api_key:
            out["error"] = "missing ozon credentials"
            _OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            return

        client = oz.OzonFbsClient(client_id, api_key)

        # Supply composition counts
        for sid in _SUPPLY_CANDIDATES:
            with repository._connect() as conn:
                rows = conn.execute(
                    repository._sql(
                        """
                        SELECT posting_number, offer_id, sku, quantity, tab, status,
                               is_mandatory_mark, cancel_reason_id,
                               coalesce(cancel_reason_label, '') AS cancel_reason_label,
                               marking_codes_json
                        FROM ozon_fbs_postings
                        WHERE user_id = ? AND source_id = ? AND supply_id = ?
                        ORDER BY posting_number
                        """
                    ),
                    (user_id, _SOURCE_ID, sid),
                ).fetchall()
            dicts = [repository._row_to_dict(r) for r in rows]
            kiz = 0
            plain = 0
            cancelled = 0
            for row in dicts:
                is_cancel = oz.posting_row_is_cancelled(row)
                if is_cancel:
                    cancelled += 1
                    continue
                if oz.posting_requires_marking(row):
                    kiz += 1
                else:
                    plain += 1
            out.setdefault("supplies", {})[sid] = {
                "total": len(dicts),
                "kiz_required_active": kiz,
                "plain_active": plain,
                "cancelled": cancelled,
                "sum_active_modals": kiz + plain,
                "by_tab": {},
            }
            tabs: dict[str, int] = {}
            for row in dicts:
                t = str(row.get("tab") or "")
                tabs[t] = tabs.get(t, 0) + 1
            out["supplies"][sid]["by_tab"] = tabs
            with repository._connect() as conn:
                offer_rows = conn.execute(
                    repository._sql(
                        """
                        SELECT posting_number, offer_id, sku, tab, is_mandatory_mark,
                               cancel_reason_id, raw_json
                        FROM ozon_fbs_postings
                        WHERE user_id = ? AND source_id = ? AND supply_id = ?
                          AND (offer_id = ? OR raw_json::text LIKE ?)
                        """
                    ),
                    (
                        user_id,
                        _SOURCE_ID,
                        sid,
                        _TARGET_OFFER,
                        f"%{_TARGET_UUID}%",
                    ),
                ).fetchall()
            offer_dicts = [repository._row_to_dict(r) for r in offer_rows]
            out["supplies"][sid]["offer_664575_or_uuid"] = [
                {
                    "posting_number": r.get("posting_number"),
                    "offer_id": r.get("offer_id"),
                    "sku": r.get("sku"),
                    "tab": r.get("tab"),
                    "is_mandatory_mark": bool(r.get("is_mandatory_mark")),
                    "requires_marking": oz.posting_requires_marking(r),
                    "cancelled": oz.posting_row_is_cancelled(r),
                    "products": oz._products_from_posting(
                        oz._posting_payload_from_row(r) or {}
                    ),
                }
                for r in offer_dicts
            ]

        # Target posting deep dive
        with repository._connect() as conn:
            prow = conn.execute(
                repository._sql(
                    """
                    SELECT * FROM ozon_fbs_postings
                    WHERE source_id = ? AND posting_number = ?
                    LIMIT 1
                    """
                ),
                (_SOURCE_ID, _TARGET_PN),
            ).fetchone()
        posting_local = repository._row_to_dict(prow) if prow else None
        pn_info: dict[str, Any] = {"posting_number": _TARGET_PN, "local": None}
        if posting_local:
            payload = oz._posting_payload_from_row(posting_local) or {}
            products = oz._products_from_posting(payload)
            pn_info["local"] = {
                "offer_id": posting_local.get("offer_id"),
                "sku": posting_local.get("sku"),
                "quantity": posting_local.get("quantity"),
                "tab": posting_local.get("tab"),
                "supply_id": posting_local.get("supply_id"),
                "is_mandatory_mark": bool(posting_local.get("is_mandatory_mark")),
                "requires_marking": oz.posting_requires_marking(posting_local),
                "cancelled": oz.posting_row_is_cancelled(posting_local),
                "products": products,
                "requirements": payload.get("requirements"),
                "products_requiring_mandatory_mark": (
                    (payload.get("requirements") or {}).get(
                        "products_requiring_mandatory_mark"
                    )
                    if isinstance(payload.get("requirements"), dict)
                    else None
                ),
            }
            skus = []
            for p in products:
                try:
                    skus.append(int(p.get("sku") or p.get("product_id")))
                except (TypeError, ValueError):
                    pass
            try:
                remote = client.get_posting(_TARGET_PN)
                pn_info["ozon_get_posting"] = {
                    "status": remote.get("status") if isinstance(remote, dict) else None,
                    "products": oz._products_from_posting(remote)
                    if isinstance(remote, dict)
                    else None,
                    "requirements": remote.get("requirements")
                    if isinstance(remote, dict)
                    else None,
                }
                if isinstance(remote, dict):
                    enriched = oz.enrich_posting_marking_flags_light(client, remote)
                    pn_info["ozon_enriched_light"] = {
                        "requirements": enriched.get("requirements"),
                        "requires_marking": oz.posting_requires_marking(
                            {
                                "is_mandatory_mark": False,
                                "raw_json": json.dumps(enriched, ensure_ascii=False),
                                "quantity": posting_local.get("quantity") or 1,
                            }
                        ),
                        "products": oz._products_from_posting(enriched),
                    }
            except Exception as exc:
                pn_info["ozon_get_posting_error"] = str(exc)
            if skus:
                try:
                    pn_info["is_required_api"] = client.mandatory_mark_is_required(
                        _TARGET_PN, skus
                    )
                except Exception as exc:
                    pn_info["is_required_api_error"] = str(exc)
        out["target_posting"] = pn_info

        # Awaiting packaging postings with offer 664575 / uuid
        with repository._connect() as conn:
            ap_rows = conn.execute(
                repository._sql(
                    """
                    SELECT posting_number, offer_id, sku, quantity, tab, status,
                           is_mandatory_mark, supply_id, raw_json
                    FROM ozon_fbs_postings
                    WHERE user_id = ? AND source_id = ?
                      AND tab = ?
                      AND (offer_id = ? OR raw_json::text LIKE ?)
                    ORDER BY posting_number
                    LIMIT 40
                    """
                ),
                (
                    user_id,
                    _SOURCE_ID,
                    oz.TAB_AWAITING_PACKAGING,
                    _TARGET_OFFER,
                    f"%{_TARGET_UUID}%",
                ),
            ).fetchall()
        ap_list = []
        for r in ap_rows:
            d = repository._row_to_dict(r)
            products = oz._products_from_posting(oz._posting_payload_from_row(d) or {})
            skus = []
            for p in products:
                try:
                    skus.append(int(p.get("sku") or p.get("product_id")))
                except (TypeError, ValueError):
                    pass
            item: dict[str, Any] = {
                "posting_number": d.get("posting_number"),
                "offer_id": d.get("offer_id"),
                "sku": d.get("sku"),
                "quantity": d.get("quantity"),
                "is_mandatory_mark_db": bool(d.get("is_mandatory_mark")),
                "requires_marking_local": oz.posting_requires_marking(d),
                "products": products,
            }
            pn = str(d.get("posting_number") or "")
            if pn and skus:
                try:
                    item["is_required_api"] = client.mandatory_mark_is_required(pn, skus)
                except Exception as exc:
                    item["is_required_api_error"] = str(exc)
            ap_list.append(item)
        out["awaiting_packaging_offer_hits"] = ap_list

        # Also search uuid/offer across all tabs (counts)
        with repository._connect() as conn:
            cnt = conn.execute(
                repository._sql(
                    """
                    SELECT tab, count(*) AS n
                    FROM ozon_fbs_postings
                    WHERE user_id = ? AND source_id = ?
                      AND (offer_id = ? OR raw_json::text LIKE ?)
                    GROUP BY tab
                    """
                ),
                (user_id, _SOURCE_ID, _TARGET_OFFER, f"%{_TARGET_UUID}%"),
            ).fetchall()
        out["offer_uuid_by_tab"] = [
            {"tab": r["tab"] if hasattr(r, "keys") else r[0], "n": int(r["n"] if hasattr(r, "keys") else r[1])}
            for r in cnt
        ]

        out["ok"] = True
    except Exception as exc:
        out["ok"] = False
        out["error"] = str(exc)
        out["traceback"] = traceback.format_exc()
        _log.exception("ozon kiz agent diag failed")

    try:
        _OUT.write_text(json.dumps(_safe(out), ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            _OUT.chmod(0o644)
        except OSError:
            pass
        _log.info("ozon kiz agent diag written to %s ok=%s", _OUT, out.get("ok"))
    except Exception:
        _log.exception("ozon kiz agent diag write failed")
