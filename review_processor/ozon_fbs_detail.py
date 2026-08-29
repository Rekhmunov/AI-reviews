"""Ozon FBS posting detail: ship, stickers, picking helpers."""
from __future__ import annotations

import json
from typing import Any

from . import ozon_fbs as oz
from .repository import ReviewRepository


def get_posting_row(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    posting_number: str,
) -> dict[str, Any] | None:
    oz.ensure_ozon_fbs_tables(repo)
    with repo._connect() as conn:
        row = conn.execute(
            repo._sql(
                """
                SELECT * FROM ozon_fbs_postings
                WHERE user_id = ? AND source_id = ? AND posting_number = ?
                """
            ),
            (user_id, source_id, str(posting_number)),
        ).fetchone()
    return repo._row_to_dict(row) if row else None


def _products_from_posting_payload(posting: dict[str, Any]) -> list[dict[str, Any]]:
    products_raw = posting.get("products")
    if isinstance(products_raw, list) and products_raw:
        return [p for p in products_raw if isinstance(p, dict)]
    try:
        parsed = json.loads(str(posting.get("products_json") or "[]"))
        return [p for p in parsed if isinstance(p, dict)] if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def posting_ship_unit_count(posting: dict[str, Any]) -> int:
    """How many physical units (and thus packages) ship will create."""
    total = 0
    for p in _products_from_posting_payload(posting):
        product_id = p.get("sku") if p.get("sku") is not None else p.get("product_id")
        try:
            int(product_id)
        except (TypeError, ValueError):
            continue
        try:
            qty = int(p.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1
        total += max(qty, 1)
    if total > 0:
        return total
    try:
        return max(int(posting.get("quantity") or 1), 1)
    except (TypeError, ValueError):
        return 1


def ship_split_preview(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Stats for UI: multi-unit postings → extra sibling postings after ship."""
    multi = 0
    units_total = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        units = posting_ship_unit_count(row)
        units_total += units
        if units > 1:
            multi += 1
    n = sum(1 for row in rows if isinstance(row, dict))
    result = units_total if n else 0
    return {
        "multi_posting_count": multi,
        "result_posting_count": result,
        "extra_postings": max(result - n, 0),
    }


def build_ship_packages(posting: dict[str, Any]) -> list[dict[str, Any]]:
    """Build ``/v4/posting/fbs/ship`` packages — one package per product unit.

    Multi-unit postings are split so the first unit keeps the original
    ``posting_number`` and each following unit becomes a separate posting
    (Ozon creates sibling numbers in ``result``).
    """
    products = _products_from_posting_payload(posting)
    units: list[dict[str, Any]] = []
    for p in products:
        product_id = p.get("sku") if p.get("sku") is not None else p.get("product_id")
        try:
            pid = int(product_id)
        except (TypeError, ValueError):
            continue
        try:
            qty = int(p.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1
        for _ in range(max(qty, 1)):
            units.append({"product_id": pid, "quantity": 1})
    if not units:
        raise RuntimeError("Нет товаров для сборки отправления")
    return [{"products": [u]} for u in units]


def _ship_result_posting_numbers(
    result: object, *, fallback_posting_number: str
) -> list[str]:
    """Extract posting numbers from ``/v4/posting/fbs/ship`` response."""
    out: list[str] = []
    seen: set[str] = set()

    def _add(value: object) -> None:
        pn = str(value or "").strip()
        if not pn or pn in seen:
            return
        seen.add(pn)
        out.append(pn)

    if isinstance(result, dict):
        raw = result.get("result")
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    _add(item)
                elif isinstance(item, dict):
                    _add(item.get("posting_number"))
        elif isinstance(raw, str):
            _add(raw)
        add = result.get("additional_data")
        if isinstance(add, list):
            for item in add:
                if isinstance(item, dict):
                    _add(item.get("posting_number"))
    _add(fallback_posting_number)
    return out or [str(fallback_posting_number).strip()]


def _product_meta_by_sku(base: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Map Ozon SKU → offer_id/name from the pre-ship posting (for local siblings)."""
    out: dict[int, dict[str, Any]] = {}
    for p in _products_from_posting_payload(base):
        raw = p.get("sku") if p.get("sku") is not None else p.get("product_id")
        try:
            sku = int(raw)
        except (TypeError, ValueError):
            continue
        out[sku] = {
            "offer_id": str(p.get("offer_id") or "").strip(),
            "name": str(p.get("name") or "").strip(),
            "sku": sku,
        }
    return out


def _compose_posting_from_package(
    *,
    posting_number: str,
    package: dict[str, Any] | None,
    base: dict[str, Any],
    meta_by_sku: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Build a local posting payload after ship without calling Ozon get."""
    products: list[dict[str, Any]] = []
    for p in list((package or {}).get("products") or []):
        if not isinstance(p, dict):
            continue
        try:
            sku = int(p.get("product_id") if p.get("product_id") is not None else p.get("sku"))
        except (TypeError, ValueError):
            continue
        try:
            qty = max(int(p.get("quantity") or 1), 1)
        except (TypeError, ValueError):
            qty = 1
        meta = meta_by_sku.get(sku) or {}
        products.append(
            {
                "sku": sku,
                "product_id": sku,
                "quantity": qty,
                "offer_id": meta.get("offer_id") or "",
                "name": meta.get("name") or "",
            }
        )
    payload: dict[str, Any] = {
        "posting_number": str(posting_number),
        "status": oz.TAB_AWAITING_DELIVER,
        "products": products,
    }
    if isinstance(base, dict):
        for key in (
            "order_id",
            "order_number",
            "warehouse_id",
            "delivery_method",
            "in_process_at",
            "created_at",
            "financial_data",
        ):
            if key in base and base.get(key) is not None:
                payload[key] = base.get(key)
        analytics = base.get("analytics_data")
        if isinstance(analytics, dict):
            payload["analytics_data"] = dict(analytics)
        else:
            payload["analytics_data"] = {}
        wh_name = ""
        if isinstance(analytics, dict):
            wh_name = str(analytics.get("warehouse") or "").strip()
        if not wh_name:
            wh_name = str(base.get("warehouse_name") or "").strip()
        if wh_name:
            ad = payload.get("analytics_data")
            if not isinstance(ad, dict):
                ad = {}
            else:
                ad = dict(ad)
            if not ad.get("warehouse"):
                ad["warehouse"] = wh_name
            if base.get("warehouse_id") is not None and ad.get("warehouse_id") is None:
                ad["warehouse_id"] = base.get("warehouse_id")
            payload["analytics_data"] = ad
        req = base.get("requirements")
        if isinstance(req, dict):
            payload["requirements"] = dict(req)
    return payload


def _persist_shipped_postings_local(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    posting_numbers: list[str],
    packages: list[dict[str, Any]],
    base: dict[str, Any],
) -> None:
    """Upsert parent + siblings after multi-package ship without Ozon get calls."""
    meta = _product_meta_by_sku(base if isinstance(base, dict) else {})
    for idx, pn in enumerate(posting_numbers):
        package = packages[idx] if idx < len(packages) else None
        payload = _compose_posting_from_package(
            posting_number=str(pn),
            package=package,
            base=base if isinstance(base, dict) else {},
            meta_by_sku=meta,
        )
        try:
            oz.upsert_posting(
                repo,
                user_id=user_id,
                source_id=source_id,
                posting=payload,
                protect_status_downgrade=False,
            )
        except Exception:
            _force_local_awaiting_deliver(
                repo,
                user_id=user_id,
                source_id=source_id,
                posting_number=str(pn),
                posting=payload,
            )


def _force_local_awaiting_deliver(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    posting_number: str,
    posting: dict[str, Any] | None = None,
) -> None:
    """Persist awaiting_deliver without relying on Ozon get eventual consistency."""
    pn = str(posting_number or "").strip()
    if not pn:
        return
    payload = dict(posting or {})
    payload["posting_number"] = pn
    payload["status"] = oz.TAB_AWAITING_DELIVER
    try:
        oz.upsert_posting(
            repo,
            user_id=user_id,
            source_id=source_id,
            posting=payload,
            protect_status_downgrade=False,
        )
    except Exception:
        with repo._connect() as conn:
            conn.execute(
                repo._sql(
                    """
                    UPDATE ozon_fbs_postings
                    SET status = ?, tab = ?, synced_at = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND source_id = ? AND posting_number = ?
                    """
                ),
                (
                    oz.TAB_AWAITING_DELIVER,
                    oz.TAB_AWAITING_DELIVER,
                    user_id,
                    source_id,
                    pn,
                ),
            )


def _ship_error_already_assembled(exc: BaseException) -> bool:
    """Ozon may reject ship when posting already left awaiting_packaging."""
    text = str(exc or "").lower()
    needles = (
        "awaiting_deliver",
        "already",
        "уже собран",
        "уже отправлен",
        "нельзя собрать",
        "invalidstate",
        "invalid_state",
        "status_not_valid",
        "posting_already",
    )
    return any(n in text for n in needles)


def ship_posting(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    posting_number: str,
    client_id: str,
    api_key: str,
    client: oz.OzonFbsClient | None = None,
    fast: bool = False,
) -> dict[str, Any]:
    """Ship one posting via ``/v4/posting/fbs/ship``.

    ``fast=True`` (bulk collect): prefer local products, skip post-ship get,
    treat «already assembled» as success — fewer Ozon round-trips / timeouts.
    """
    row = get_posting_row(
        repo, user_id=user_id, source_id=source_id, posting_number=posting_number
    )
    if not row:
        raise RuntimeError("Отправление не найдено локально — синхронизируйте и повторите")

    local_tab = str(row.get("tab") or "").strip().lower()
    if local_tab in {
        oz.TAB_AWAITING_DELIVER,
        oz.TAB_DELIVERING,
        oz.TAB_DELIVERED,
    }:
        return {
            "ok": True,
            "result": {"already": True},
            "skipped": True,
            "posting_numbers": [str(posting_number)],
        }

    api = client or oz.OzonFbsClient(client_id, api_key)
    packages: list[dict[str, Any]] | None = None
    remote: dict[str, Any] = {}

    if fast:
        try:
            packages = build_ship_packages(row)
        except Exception:
            packages = None
        if packages is None:
            try:
                remote = api.get_posting(str(posting_number))
            except Exception:
                remote = {}
            packages = build_ship_packages(remote if remote else row)
    else:
        try:
            remote = api.get_posting(str(posting_number))
        except Exception:
            remote = {}
        packages = build_ship_packages(remote if remote else row)

    try:
        result = api.ship_posting(str(posting_number), packages)
    except Exception as exc:
        if not _ship_error_already_assembled(exc):
            # One soft retry on rate limit / transient HTTP.
            err_l = str(exc).lower()
            if "429" in err_l or "http 5" in err_l or "network" in err_l:
                import time as _time

                _time.sleep(1.5)
                try:
                    result = api.ship_posting(str(posting_number), packages)
                except Exception as exc2:
                    if not _ship_error_already_assembled(exc2):
                        raise
                    result = {"already": True, "error": str(exc2)}
            else:
                # Confirm remote status — may already be past packaging.
                try:
                    got = api.get_posting(str(posting_number))
                except Exception:
                    got = {}
                got_tab = oz.compute_tab(str((got or {}).get("status") or ""))
                if got_tab in {
                    oz.TAB_AWAITING_DELIVER,
                    oz.TAB_DELIVERING,
                    oz.TAB_DELIVERED,
                }:
                    _force_local_awaiting_deliver(
                        repo,
                        user_id=user_id,
                        source_id=source_id,
                        posting_number=str(posting_number),
                        posting=got if isinstance(got, dict) else None,
                    )
                    return {
                        "ok": True,
                        "result": {"already": True},
                        "skipped": True,
                        "posting_numbers": [str(posting_number)],
                    }
                raise
        else:
            result = {"already": True, "error": str(exc)}

    posting_numbers = _ship_result_posting_numbers(
        result, fallback_posting_number=str(posting_number)
    )
    multi_split = len(packages) > 1
    base = remote or row

    # Bulk collect (fast): never N×get_posting — upsert from ship result + packages.
    if fast:
        if multi_split:
            _persist_shipped_postings_local(
                repo,
                user_id=user_id,
                source_id=source_id,
                posting_numbers=posting_numbers,
                packages=packages,
                base=base if isinstance(base, dict) else {},
            )
        else:
            _force_local_awaiting_deliver(
                repo,
                user_id=user_id,
                source_id=source_id,
                posting_number=str(posting_number),
                posting=base if isinstance(base, dict) else None,
            )
        return {
            "ok": True,
            "result": result,
            "posting_numbers": posting_numbers,
        }

    # Interactive / single ship: refresh each resulting posting from Ozon when possible.
    for idx, pn in enumerate(posting_numbers):
        refreshed: dict[str, Any] = {}
        try:
            got = api.get_posting(str(pn))
            if isinstance(got, dict):
                refreshed = dict(got)
        except Exception:
            refreshed = {}
        if not refreshed.get("posting_number"):
            package = packages[idx] if idx < len(packages) else None
            refreshed = _compose_posting_from_package(
                posting_number=str(pn),
                package=package,
                base=base if isinstance(base, dict) else {},
                meta_by_sku=_product_meta_by_sku(
                    base if isinstance(base, dict) else {}
                ),
            )
        remote_status = str(refreshed.get("status") or "").strip().lower()
        remote_tab = oz.compute_tab(remote_status)
        if remote_tab not in (
            oz.TAB_AWAITING_DELIVER,
            oz.TAB_DELIVERING,
            oz.TAB_DELIVERED,
            oz.TAB_CANCELLED,
            oz.TAB_ARBITRATION,
        ):
            refreshed["status"] = oz.TAB_AWAITING_DELIVER
        try:
            oz.upsert_posting(
                repo,
                user_id=user_id,
                source_id=source_id,
                posting=refreshed,
                protect_status_downgrade=False,
            )
        except Exception:
            _force_local_awaiting_deliver(
                repo,
                user_id=user_id,
                source_id=source_id,
                posting_number=str(pn),
                posting=refreshed if refreshed else None,
            )
    return {
        "ok": True,
        "result": result,
        "posting_numbers": posting_numbers,
    }


def list_awaiting_packaging_numbers(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
) -> list[str]:
    oz.ensure_ozon_fbs_tables(repo)
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                """
                SELECT posting_number FROM ozon_fbs_postings
                WHERE user_id = ? AND source_id = ? AND tab = ?
                ORDER BY created_at_ozon DESC NULLS LAST, posting_number DESC
                """
            ),
            (user_id, source_id, oz.TAB_AWAITING_PACKAGING),
        ).fetchall()
    out: list[str] = []
    for row in rows:
        pn = str(row["posting_number"] if hasattr(row, "keys") else row[0] or "").strip()
        if pn:
            out.append(pn)
    return out


def ship_all_awaiting_packaging(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    client_id: str,
    api_key: str,
) -> dict[str, Any]:
    """Ship every local «Ожидают сборки» posting via Ozon ``/v4/posting/fbs/ship``.

    Moves successful postings to ``awaiting_deliver`` (Ожидают отгрузки).
    """
    numbers = list_awaiting_packaging_numbers(
        repo, user_id=user_id, source_id=source_id
    )
    if not numbers:
        return {
            "ok": True,
            "total": 0,
            "shipped": 0,
            "failed": 0,
            "errors": [],
            "message": "Нет отправлений в «Ожидают сборки»",
        }
    client = oz.OzonFbsClient(client_id, api_key)
    shipped: list[str] = []
    errors: list[dict[str, str]] = []
    for pn in numbers:
        try:
            ship_posting(
                repo,
                user_id=user_id,
                source_id=source_id,
                posting_number=pn,
                client_id=client_id,
                api_key=api_key,
                client=client,
            )
            shipped.append(pn)
        except Exception as exc:
            errors.append({"posting_number": pn, "error": str(exc)})
    shipped_n = len(shipped)
    failed_n = len(errors)
    if shipped_n and not failed_n:
        message = f"Собрано {shipped_n} отправлений → «Ожидают отгрузки»"
        ok = True
    elif shipped_n and failed_n:
        message = f"Собрано {shipped_n}, ошибок {failed_n}"
        ok = False
    else:
        message = f"Не удалось собрать отправления ({failed_n})"
        ok = False
    return {
        "ok": ok,
        "total": len(numbers),
        "shipped": shipped_n,
        "failed": failed_n,
        "shipped_numbers": shipped,
        "errors": errors,
        "message": message,
    }


def posting_detail_payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        products = json.loads(row.get("products_json") or "[]")
    except json.JSONDecodeError:
        products = []
    try:
        barcodes = json.loads(row.get("barcodes_json") or "[]")
    except json.JSONDecodeError:
        barcodes = []
    return {
        "posting_number": row.get("posting_number"),
        "order_number": row.get("order_number"),
        "status": row.get("status"),
        "tab": row.get("tab"),
        "tab_label": oz.TAB_LABELS.get(str(row.get("tab") or ""), ""),
        "offer_id": row.get("offer_id"),
        "product_name": row.get("product_name"),
        "quantity": row.get("quantity"),
        "price_display": row.get("price_display") or row.get("price"),
        "warehouse_label": row.get("warehouse_name") or row.get("warehouse_label"),
        "is_mandatory_mark": bool(row.get("is_mandatory_mark")),
        "products": products if isinstance(products, list) else [],
        "barcodes": barcodes if isinstance(barcodes, list) else [],
        "can_ship": str(row.get("tab") or "") == oz.TAB_AWAITING_PACKAGING,
        "can_print_label": str(row.get("tab") or "") in {
            oz.TAB_AWAITING_PACKAGING,
            oz.TAB_AWAITING_DELIVER,
            oz.TAB_DELIVERING,
        },
    }


def print_package_labels(
    *,
    client_id: str,
    api_key: str,
    posting_numbers: list[str],
) -> bytes:
    nums = [str(p).strip() for p in posting_numbers if str(p).strip()]
    if not nums:
        raise RuntimeError("Не указаны отправления для печати")
    client = oz.OzonFbsClient(client_id, api_key)
    return oz.fetch_merged_package_label_pdf(client, nums)
