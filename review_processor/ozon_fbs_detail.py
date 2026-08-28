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


def build_ship_packages(posting: dict[str, Any]) -> list[dict[str, Any]]:
    products_raw = posting.get("products")
    if isinstance(products_raw, list) and products_raw:
        products = [p for p in products_raw if isinstance(p, dict)]
    else:
        try:
            parsed = json.loads(str(posting.get("products_json") or "[]"))
            products = [p for p in parsed if isinstance(p, dict)] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            products = []
    package_products: list[dict[str, Any]] = []
    for p in products:
        product_id = p.get("sku") or p.get("product_id")
        try:
            pid = int(product_id)
        except (TypeError, ValueError):
            continue
        try:
            qty = int(p.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1
        package_products.append({"product_id": pid, "quantity": max(qty, 1)})
    if not package_products:
        raise RuntimeError("Нет товаров для сборки отправления")
    return [{"products": package_products}]


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
        return {"ok": True, "result": {"already": True}, "skipped": True}

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
                    return {"ok": True, "result": {"already": True}, "skipped": True}
                raise
        else:
            result = {"already": True, "error": str(exc)}

    if fast:
        _force_local_awaiting_deliver(
            repo,
            user_id=user_id,
            source_id=source_id,
            posting_number=str(posting_number),
            posting=remote or row,
        )
        return {"ok": True, "result": result}

    # After a successful ship, local must be awaiting_deliver even if Ozon get/list
    # still briefly returns awaiting_packaging (eventual consistency).
    refreshed: dict[str, Any] = {}
    try:
        got = api.get_posting(str(posting_number))
        if isinstance(got, dict):
            refreshed = dict(got)
    except Exception:
        refreshed = {}
    if not refreshed.get("posting_number"):
        refreshed["posting_number"] = str(posting_number)
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
            posting_number=str(posting_number),
        )
    return {"ok": True, "result": result}


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
