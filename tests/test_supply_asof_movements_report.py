"""Остатки → Сформировать на дату → Движение товаров (period journal)."""

from __future__ import annotations

from pathlib import Path

from review_processor.repository import ReviewRepository

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
WEB_PY = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")


def test_list_supply_stock_movements_sql_shape() -> None:
    repo = ReviewRepository.__new__(ReviewRepository)
    repo._sql = lambda q: q  # type: ignore[method-assign]
    repo._ensure_supply_balances_tables = lambda conn: None  # type: ignore[method-assign]
    repo._row_to_dict = lambda r: dict(r)  # type: ignore[method-assign]
    executed: list[tuple[str, tuple]] = []

    class _Cur:
        def fetchall(self):
            return [
                {
                    "id": 3,
                    "item_type": "product",
                    "item_id": 9,
                    "qty": -1.0,
                    "movement_date": "2026-09-04",
                    "kind": "fbs_ship",
                    "source_type": "wb_fbs_order",
                    "source_id": "1001",
                    "comment": "",
                    "created_at": "2026-09-04T10:00:00",
                    "created_by": None,
                },
                {
                    "id": 2,
                    "item_type": "material",
                    "item_id": 7,
                    "qty": 5.0,
                    "movement_date": "2026-09-03",
                    "kind": "receipt",
                    "source_type": "manual_receipt",
                    "source_id": "receipt:1",
                    "comment": "приход",
                    "created_at": "2026-09-03T12:00:00",
                    "created_by": 42,
                },
            ]

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            executed.append((str(sql), tuple(params)))
            return _Cur()

    repo._connect = lambda: _Conn()  # type: ignore[method-assign]
    rows = ReviewRepository.list_supply_stock_movements(
        repo,
        user_id=10,
        production_id=3,
        date_from="2026-09-01",
        date_to="2026-09-05",
        limit=2000,
    )
    assert len(rows) == 2
    assert rows[0]["kind"] == "fbs_ship"
    assert rows[1]["item_type"] == "material"
    assert len(executed) == 1
    sql, params = executed[0]
    assert "FROM supply_stock_movements" in sql
    assert "movement_date >=" in sql and "movement_date <=" in sql
    assert "ORDER BY movement_date DESC" in sql
    assert params == (10, 3, "2026-09-01", "2026-09-05", 2000)


def test_list_supply_stock_movements_swaps_inverted_range() -> None:
    repo = ReviewRepository.__new__(ReviewRepository)
    repo._sql = lambda q: q  # type: ignore[method-assign]
    repo._ensure_supply_balances_tables = lambda conn: None  # type: ignore[method-assign]
    repo._row_to_dict = lambda r: dict(r)  # type: ignore[method-assign]
    executed: list[tuple[str, tuple]] = []

    class _Cur:
        def fetchall(self):
            return []

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            executed.append((str(sql), tuple(params)))
            return _Cur()

    repo._connect = lambda: _Conn()  # type: ignore[method-assign]
    ReviewRepository.list_supply_stock_movements(
        repo,
        user_id=1,
        production_id=2,
        date_from="2026-09-10",
        date_to="2026-09-01",
        limit=50,
    )
    assert executed[0][1] == (1, 2, "2026-09-01", "2026-09-10", 50)


def test_movements_report_api_and_ui_wired() -> None:
    assert '@app.get("/api/supply-balances/movements-report")' in WEB_PY
    assert "list_supply_stock_movements(" in WEB_PY
    assert 'option value="movements">Движение товаров</option>' in APP_HTML
    assert "function loadSupplyBalancesMovementsData(" in APP_JS
    assert "function renderSupplyBalancesMovementsTable(" in APP_JS
    assert 'viewMode === "movements"' in APP_JS
    assert "form.mode === \"movements\"" in APP_JS
    assert "/api/supply-balances/movements-report" in APP_JS
    assert "sb-movements-report-table" in APP_JS
    assert "#supplyBalancesTable.sb-movements-report-table" in STYLE_CSS
    assert "style.css?v=305" in APP_HTML
    assert "app.js?v=551" in APP_HTML
