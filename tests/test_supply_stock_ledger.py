"""Unit tests for supply stock ledger (Поставки → Остатки)."""

from __future__ import annotations

from review_processor.repository import ReviewRepository
from review_processor.wb_fbs import compute_tab, TAB_DELIVERY, TAB_ASSEMBLY


def test_kiz_and_wb_fbs_still_import_with_ledger() -> None:
    from review_processor import wb_fbs, wb_fbs_detail

    assert callable(wb_fbs.sync_wb_fbs_source)
    assert callable(wb_fbs_detail._kiz_status_from_decision)
    assert compute_tab(supplier_status="complete", wb_status="", is_archive=False) == TAB_DELIVERY
    assert compute_tab(supplier_status="confirm", wb_status="", is_archive=False) == TAB_ASSEMBLY


def test_add_supply_stock_movements_sql_shape() -> None:
    repo = ReviewRepository.__new__(ReviewRepository)
    repo._sql = lambda q: q  # type: ignore[method-assign]
    repo._ensure_supply_balances_tables = lambda conn: None  # type: ignore[method-assign]
    executed: list[tuple[str, tuple]] = []

    class _Cur:
        rowcount = 1

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            executed.append((str(sql), tuple(params)))
            return _Cur()

    repo._connect = lambda: _Conn()  # type: ignore[method-assign]
    saved = ReviewRepository.add_supply_stock_movements(
        repo,
        user_id=1,
        production_id=9,
        movement_date="2026-08-12",
        kind="receipt",
        source_type="manual_receipt",
        items=[
            {
                "item_type": "product",
                "item_id": 5,
                "qty": 10,
                "source_id": "receipt:1",
            },
            {"item_type": "junk", "item_id": 1, "qty": 1, "source_id": "x"},
            {
                "item_type": "material",
                "item_id": 2,
                "qty": 0,
                "source_id": "receipt:2",
            },
        ],
        created_by=3,
    )
    assert saved == 1
    assert any("supply_stock_movements" in sql and "INSERT" in sql for sql, _ in executed)
    assert any("ON CONFLICT" in sql for sql, _ in executed)


def test_apply_wb_fbs_stock_tab_transitions_ships_and_reverses() -> None:
    repo = ReviewRepository.__new__(ReviewRepository)
    repo._sql = lambda q: q  # type: ignore[method-assign]
    repo._ensure_supply_balances_tables = lambda conn: None  # type: ignore[method-assign]
    repo.get_product_id_by_article_map = lambda *, user_id: {  # type: ignore[method-assign]
        "ART-1": 44,
        "art-1": 44,
        "1001": 44,
    }
    executed: list[tuple[str, tuple]] = []

    class _Cur:
        rowcount = 1

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            executed.append((str(sql), tuple(params)))
            return _Cur()

    repo._connect = lambda: _Conn()  # type: ignore[method-assign]

    stats = ReviewRepository.apply_wb_fbs_stock_tab_transitions(
        repo,
        user_id=7,
        production_id=3,
        movement_date="2026-08-12",
        transitions=[
            {
                "order_id": 111,
                "old_tab": "assembly",
                "new_tab": "delivery",
                "article": "ART-1",
                "nm_id": "",
            },
            {
                "order_id": 222,
                "old_tab": "delivery",
                "new_tab": "assembly",
                "article": "ART-1",
                "nm_id": "",
            },
            {
                "order_id": 333,
                "old_tab": "assembly",
                "new_tab": "assembly",
                "article": "ART-1",
                "nm_id": "",
            },
            {
                "order_id": 444,
                "old_tab": "assembly",
                "new_tab": "delivery",
                "article": "UNKNOWN",
                "nm_id": "",
            },
        ],
    )
    assert stats["shipped"] == 1
    assert stats["reversed"] == 1
    assert stats["skipped"] >= 2
    ship_params = [p for sql, p in executed if "fbs_ship" in p or (len(p) > 6 and p[5] == "fbs_ship")]
    assert any(p[3] == -1.0 for p in ship_params)  # qty
    rev_params = [p for sql, p in executed if len(p) > 6 and p[5] == "fbs_reverse"]
    assert any(p[3] == 1.0 for p in rev_params)


def test_sum_supply_stock_balances_sql_shape() -> None:
    repo = ReviewRepository.__new__(ReviewRepository)
    repo._sql = lambda q: q  # type: ignore[method-assign]
    repo._ensure_supply_balances_tables = lambda conn: None  # type: ignore[method-assign]
    repo._row_to_dict = lambda r: dict(r)  # type: ignore[method-assign]

    class _Cur:
        def fetchall(self):
            return [
                {"item_type": "product", "item_id": 5, "balance": 12.0},
                {"item_type": "material", "item_id": 2, "balance": 3.5},
            ]

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            assert "SUM(qty)" in str(sql)
            assert params[-1] == "2026-08-12"
            return _Cur()

    repo._connect = lambda: _Conn()  # type: ignore[method-assign]
    bal = ReviewRepository.sum_supply_stock_balances(
        repo, user_id=1, production_id=2, as_of="2026-08-12"
    )
    assert bal[("product", 5)] == 12.0
    assert bal[("material", 2)] == 3.5
