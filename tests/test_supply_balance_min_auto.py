"""Automatic minimum stock for Поставки → Остатки → Вывод."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from review_processor.repository import ReviewRepository
from review_processor.supply_balance_min_auto import (
    apply_min_qty_from_sales,
    clamp_min_auto_days,
    run_due_min_auto,
    sales_window,
    save_min_auto_settings,
    sold_to_min_qty,
)

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
WEB = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")


def test_sales_window_is_complete_days_ending_yesterday() -> None:
    assert sales_window(date(2026, 9, 18), 14) == ("2026-09-04", "2026-09-17")
    assert sales_window(date(2026, 9, 18), 1) == ("2026-09-17", "2026-09-17")
    assert sales_window(date(2026, 1, 1), 14) == ("2025-12-18", "2025-12-31")


def test_clamp_min_auto_days() -> None:
    assert clamp_min_auto_days(14) == 14
    assert clamp_min_auto_days("7") == 7
    assert clamp_min_auto_days(1) == 1
    assert clamp_min_auto_days(366) == 366
    assert clamp_min_auto_days(0) is None
    assert clamp_min_auto_days(367) is None
    assert clamp_min_auto_days(-3) is None
    assert clamp_min_auto_days("14.5") is None
    assert clamp_min_auto_days("") is None
    assert sold_to_min_qty(-4) == 0.0
    assert sold_to_min_qty(2.5) == 2.5


class _Repo:
    def __init__(self) -> None:
        self.settings = {
            "enabled": False,
            "days": 14,
            "last_applied_date": "",
        }
        self.productions = [{"id": 1}, {"id": 2}]
        self.materials = [{"id": 10}]
        self.products = [{"id": 20}, {"id": 21}]
        self.sales = {
            1: {("product", 20): 5.0, ("product", 21): -3.0},
            2: {("product", 20): 2.0, ("material", 10): 1.5},
        }
        self.written = None
        self.marked = None
        self.marketplace = None

    def get_supply_balance_min_auto(self, *, user_id: int):
        return dict(self.settings)

    def set_supply_balance_min_auto(self, *, user_id, enabled, days, last_applied_date):
        self.settings = {
            "enabled": bool(enabled),
            "days": int(days),
            "last_applied_date": str(last_applied_date or ""),
        }

    def mark_supply_balance_min_auto_applied(self, *, user_id, last_applied_date):
        self.marked = str(last_applied_date)
        self.settings["last_applied_date"] = self.marked

    def list_supply_productions(self, *, user_id):
        return self.productions

    def sum_supply_stock_sales(self, *, user_id, production_id, date_from, date_to, marketplace):
        self.marketplace = marketplace
        self.window = (date_from, date_to)
        return dict(self.sales.get(production_id, {}))

    def list_feedback_materials(self, *, user_id):
        return self.materials

    def list_product_photos(self, *, user_id):
        return self.products

    def apply_supply_balance_min_qty_only(self, *, user_id, items):
        self.written = list(items)
        return len(items)


def test_apply_sums_productions_and_writes_min_only() -> None:
    repo = _Repo()
    repo.settings["enabled"] = True
    result = apply_min_qty_from_sales(repo, user_id=3, today_iso="2026-09-18")
    assert result["applied"] is True
    assert result["date_from"] == "2026-09-04"
    assert result["date_to"] == "2026-09-17"
    assert repo.marketplace == "all"
    assert repo.marked == "2026-09-18"
    by_key = {(row["item_type"], row["item_id"]): row["min_qty"] for row in repo.written}
    assert by_key[("product", 20)] == 7.0
    assert by_key[("product", 21)] == 0.0
    assert by_key[("material", 10)] == 1.5
    assert "visible" not in repo.written[0]
    assert "sort_order" not in repo.written[0]


def test_apply_skips_when_off_or_already_done_today() -> None:
    repo = _Repo()
    result = apply_min_qty_from_sales(repo, user_id=3, today_iso="2026-09-18")
    assert result == {"applied": False, "reason": "disabled"}
    assert repo.written is None

    repo.settings["enabled"] = True
    repo.settings["last_applied_date"] = "2026-09-18"
    result = apply_min_qty_from_sales(repo, user_id=3, today_iso="2026-09-18")
    assert result["reason"] == "already"
    assert repo.written is None


def test_enable_waits_for_next_midnight_and_off_keeps_mins() -> None:
    repo = _Repo()
    saved = save_min_auto_settings(
        repo, user_id=3, enabled=True, days=14, today_iso="2026-09-18"
    )
    assert saved["enabled"] is True
    assert saved["last_applied_date"] == "2026-09-18"
    assert repo.written is None
    blocked = apply_min_qty_from_sales(repo, user_id=3, today_iso="2026-09-18")
    assert blocked["reason"] == "already"

    changed = save_min_auto_settings(
        repo, user_id=3, enabled=True, days=7, today_iso="2026-09-18"
    )
    assert changed["days"] == 7
    assert changed["last_applied_date"] == "2026-09-18"

    off = save_min_auto_settings(
        repo, user_id=3, enabled=False, days=7, today_iso="2026-09-19"
    )
    assert off["enabled"] is False
    assert off["last_applied_date"] == "2026-09-18"
    assert repo.written is None
    skipped = apply_min_qty_from_sales(repo, user_id=3, today_iso="2026-09-19")
    assert skipped["reason"] == "disabled"


def test_nightly_job_skips_owners_already_done_today() -> None:
    repo = _Repo()
    repo.enabled_rows = [
        {"user_id": 3, "days": 14, "last_applied_date": "2026-09-18"},
        {"user_id": 4, "days": 7, "last_applied_date": "2026-09-17"},
    ]
    repo.settings_by_user = {
        4: {"enabled": True, "days": 7, "last_applied_date": "2026-09-17"},
    }

    def _get(*, user_id):
        return dict(repo.settings_by_user[user_id])

    def _list_enabled():
        return list(repo.enabled_rows)

    repo.get_supply_balance_min_auto = _get  # type: ignore[method-assign]
    repo.list_enabled_supply_balance_min_auto = _list_enabled  # type: ignore[method-assign]
    called = {"users": False}

    def _list_users(**kwargs):
        called["users"] = True
        return []

    repo.list_users = _list_users  # type: ignore[method-assign]
    applied = run_due_min_auto(repo, today_iso="2026-09-18")
    assert applied == 1
    assert called["users"] is False
    assert repo.marked == "2026-09-18"
    assert {(row["item_type"], row["item_id"]) for row in repo.written} == {
        ("material", 10),
        ("product", 20),
        ("product", 21),
    }


def test_apply_sql_updates_min_qty_only() -> None:
    repo = ReviewRepository.__new__(ReviewRepository)
    repo._sql = lambda q: q  # type: ignore[method-assign]
    repo._bool_db = lambda value: bool(value)  # type: ignore[method-assign]
    repo._ensure_supply_balances_tables = lambda conn: None  # type: ignore[method-assign]
    executed: list[tuple[str, tuple]] = []

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            executed.append((str(sql), tuple(params)))
            return self

    repo._connect = lambda: _Conn()  # type: ignore[method-assign]
    saved = ReviewRepository.apply_supply_balance_min_qty_only(
        repo,
        user_id=1,
        items=[
            {"item_type": "product", "item_id": 5, "min_qty": 4},
            {"item_type": "material", "item_id": 0, "min_qty": 9},
        ],
    )
    assert saved == 1
    sql, params = executed[0]
    assert "DO UPDATE SET min_qty = EXCLUDED.min_qty" in sql
    assert "visible = EXCLUDED" not in sql
    assert "sort_order = EXCLUDED" not in sql
    assert params[4] == 10**9
    assert params[5] == 4.0


def test_visibility_modal_has_gear_and_settings_modal() -> None:
    vis = HTML.split('id="supplyBalancesVisibilityModal"', 1)[1].split(
        'id="supplyBalancesMinAutoModal"', 1
    )[0]
    assert 'id="supplyBalancesMinAutoBtn"' in vis
    assert ">⚙</button>" in vis
    assert "openSupplyBalancesMinAutoModal()" in vis
    assert "Автоматический мин. остаток" in vis
    panel = HTML.split('id="supplyBalancesFilterPanel"', 1)[1].split(
        'id="supplyBalancesVisibilityModal"', 1
    )[0]
    assert "openSupplyBalancesMinAutoModal" not in panel
    modal = HTML.split('id="supplyBalancesMinAutoModal"', 1)[1].split(
        'id="supplyStockReceiptModal"', 1
    )[0]
    assert 'id="supplyBalancesMinAutoEnabled"' in modal
    assert "wb-fbs-auto-sync-row" in modal
    assert 'id="supplyBalancesMinAutoState"' in modal
    assert 'for="supplyBalancesMinAutoDays"' in modal
    assert "Дней продаж" in modal
    assert "после 00:00" in modal
    assert "style.css?v=415" in HTML
    assert "app.js?v=695" in HTML
    assert "/api/supply-balances/min-auto" in APP_JS
    assert "function saveSupplyBalancesMinAuto" in APP_JS
    assert "supply_min_auto_scheduler.start()" in WEB
    assert "stock_scheduler left stopped" in WEB
    assert 'DO UPDATE SET min_qty = EXCLUDED.min_qty' in (
        ROOT / "review_processor" / "repository.py"
    ).read_text(encoding="utf-8")
