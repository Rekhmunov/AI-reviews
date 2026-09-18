"""Nightly automatic minimum stock for Поставки → Остатки → Вывод.

When the owner turns the switch on, nothing is written immediately.
After 00:00 Moscow time the job sets ``supply_balance_visibility.min_qty``
to sales over the last N complete days (ending yesterday), summed across
every production. Turning the switch off skips the job and leaves the
manual «Мин.» values as they are.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta
from typing import Any

_log = logging.getLogger(__name__)

MIN_AUTO_DAYS_DEFAULT = 14
MIN_AUTO_DAYS_MIN = 1
MIN_AUTO_DAYS_MAX = 366
_CHECK_INTERVAL_SECONDS = 60


def moscow_today() -> str:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    except Exception:
        from datetime import UTC

        return datetime.now(UTC).date().isoformat()


def clamp_min_auto_days(raw: object) -> int | None:
    """Accept a whole number of days in 1..366. Anything else is invalid."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, float):
        if raw != raw or not raw.is_integer():
            return None
        raw = int(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text or (text[0] == "-" and not text[1:].isdigit()) or (
            text[0] != "-" and not text.isdigit()
        ):
            return None
    try:
        days = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if days < MIN_AUTO_DAYS_MIN or days > MIN_AUTO_DAYS_MAX:
        return None
    return days


def sales_window(today: date, days: int) -> tuple[str, str]:
    """Inclusive window of ``days`` complete dates ending yesterday.

    At 00:00 the new day has no sales yet, so it is not part of the window.
    Example: today 2026-09-18 and days=14 → 2026-09-04 .. 2026-09-17.
    """
    span = int(days)
    if span < 1:
        span = 1
    date_to = today - timedelta(days=1)
    date_from = today - timedelta(days=span)
    return date_from.isoformat(), date_to.isoformat()


def _already_applied(last_applied_date: str, today_iso: str) -> bool:
    last = str(last_applied_date or "").strip()
    today = str(today_iso or "").strip()
    if not today or len(last) != 10 or last[4] != "-" or last[7] != "-":
        return False
    return last >= today


def sold_to_min_qty(raw: object) -> float:
    """Net sales → non-negative min. Negative (returns > ships) becomes 0."""
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if value != value or value < 0:
        return 0.0
    return round(value, 4)


def sum_sales_across_productions(
    repository: Any,
    *,
    user_id: int,
    date_from: str,
    date_to: str,
) -> dict[tuple[str, int], float]:
    """Sum FBS sales for every production. ``min_qty`` is account-level."""
    totals: dict[tuple[str, int], float] = {}
    productions = repository.list_supply_productions(user_id=int(user_id)) or []
    for prod in productions:
        try:
            production_id = int(prod.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if production_id <= 0:
            continue
        part = repository.sum_supply_stock_sales(
            user_id=int(user_id),
            production_id=production_id,
            date_from=date_from,
            date_to=date_to,
            marketplace="all",
        ) or {}
        for key, qty in part.items():
            if not isinstance(key, tuple) or len(key) != 2:
                continue
            item_type = str(key[0] or "").strip().lower()
            try:
                item_id = int(key[1] or 0)
                sold = float(qty)
            except (TypeError, ValueError):
                continue
            if item_type not in {"material", "product"} or item_id <= 0:
                continue
            totals[(item_type, item_id)] = totals.get((item_type, item_id), 0.0) + sold
    return totals


def catalog_min_items(
    repository: Any,
    *,
    user_id: int,
    sales: dict[tuple[str, int], float],
) -> list[dict[str, Any]]:
    """One min_qty per material and product. No sales → 0 while auto is on."""
    items: list[dict[str, Any]] = []
    materials = repository.list_feedback_materials(user_id=int(user_id)) or []
    products = repository.list_product_photos(user_id=int(user_id)) or []
    for row in materials:
        try:
            item_id = int(row.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if item_id <= 0:
            continue
        items.append(
            {
                "item_type": "material",
                "item_id": item_id,
                "min_qty": sold_to_min_qty(sales.get(("material", item_id), 0.0)),
            }
        )
    for row in products:
        try:
            item_id = int(row.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if item_id <= 0:
            continue
        items.append(
            {
                "item_type": "product",
                "item_id": item_id,
                "min_qty": sold_to_min_qty(sales.get(("product", item_id), 0.0)),
            }
        )
    return items


def apply_min_qty_from_sales(
    repository: Any, *, user_id: int, today_iso: str
) -> dict[str, Any]:
    """Write mins for one owner if the switch is on and today is not done yet."""
    settings = repository.get_supply_balance_min_auto(user_id=int(user_id)) or {}
    if not bool(settings.get("enabled")):
        return {"applied": False, "reason": "disabled"}
    today = str(today_iso or "").strip()
    if _already_applied(str(settings.get("last_applied_date") or ""), today):
        return {"applied": False, "reason": "already"}
    days = clamp_min_auto_days(settings.get("days")) or MIN_AUTO_DAYS_DEFAULT
    try:
        today_d = date.fromisoformat(today)
    except ValueError:
        return {"applied": False, "reason": "bad_date"}
    date_from, date_to = sales_window(today_d, days)
    # Re-read so a switch flipped off while we were idle is not overwritten.
    fresh = repository.get_supply_balance_min_auto(user_id=int(user_id)) or {}
    if not bool(fresh.get("enabled")):
        return {"applied": False, "reason": "disabled"}
    if _already_applied(str(fresh.get("last_applied_date") or ""), today):
        return {"applied": False, "reason": "already"}
    sales = sum_sales_across_productions(
        repository, user_id=int(user_id), date_from=date_from, date_to=date_to
    )
    items = catalog_min_items(repository, user_id=int(user_id), sales=sales)
    saved = int(
        repository.apply_supply_balance_min_qty_only(user_id=int(user_id), items=items)
        or 0
    )
    repository.mark_supply_balance_min_auto_applied(
        user_id=int(user_id), last_applied_date=today
    )
    return {
        "applied": True,
        "updated": saved,
        "days": days,
        "date_from": date_from,
        "date_to": date_to,
    }


def save_min_auto_settings(
    repository: Any,
    *,
    user_id: int,
    enabled: bool,
    days: object,
    today_iso: str,
) -> dict[str, Any]:
    """Persist the switch and day count. Enabling does not run the job now.

    The first write happens after the next 00:00. Changing the day count
    while the switch is already on keeps ``last_applied_date``. Turning the
    switch off does not clear existing min_qty values.
    """
    days_n = clamp_min_auto_days(days)
    if days_n is None:
        raise ValueError("days")
    current = repository.get_supply_balance_min_auto(user_id=int(user_id)) or {}
    was_enabled = bool(current.get("enabled"))
    last = str(current.get("last_applied_date") or "").strip()
    if bool(enabled) and not was_enabled:
        last = str(today_iso or "").strip()
    repository.set_supply_balance_min_auto(
        user_id=int(user_id),
        enabled=bool(enabled),
        days=days_n,
        last_applied_date=last,
    )
    saved = repository.get_supply_balance_min_auto(user_id=int(user_id)) or {}
    return {
        "enabled": bool(saved.get("enabled")),
        "days": int(saved.get("days") or days_n),
        "last_applied_date": str(saved.get("last_applied_date") or ""),
    }


def run_due_min_auto(repository: Any, *, today_iso: str | None = None) -> int:
    """Apply for every owner whose switch is on and whose day is not done."""
    today = str(today_iso or moscow_today())
    try:
        users = repository.list_users(owner_only=True) or []
    except Exception as exc:
        _log.warning("supply min-auto: list owners failed: %s", exc)
        return 0
    applied = 0
    for user in users:
        try:
            user_id = int(user.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if user_id <= 0:
            continue
        try:
            result = apply_min_qty_from_sales(
                repository, user_id=user_id, today_iso=today
            )
        except Exception as exc:
            _log.warning("supply min-auto: user %s failed: %s", user_id, exc)
            continue
        if result.get("applied"):
            applied += 1
            _log.info(
                "supply min-auto: user %s updated %s items %s..%s",
                user_id,
                result.get("updated"),
                result.get("date_from"),
                result.get("date_to"),
            )
    return applied


class MinAutoScheduler:
    """Daemon that checks once a minute and runs only after Moscow midnight."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="feedpilot-supply-min-auto",
                daemon=True,
            )
            self._thread.start()
            _log.info("MinAutoScheduler: started")

    def stop(self) -> None:
        self._stop_event.set()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(_CHECK_INTERVAL_SECONDS)
            if self._stop_event.is_set():
                break
            try:
                run_due_min_auto(self.repository)
            except Exception as exc:
                _log.warning("MinAutoScheduler loop error: %s", exc)
