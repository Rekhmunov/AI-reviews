"""Ozon FBS stock ledger — deduct on delivering (Поставки → Остатки). WB untouched."""

from __future__ import annotations

from review_processor.repository import ReviewRepository


def test_reconcile_ozon_ships_on_delivering_and_idempotent() -> None:
    repo = ReviewRepository.__new__(ReviewRepository)
    repo._sql = lambda q: q  # type: ignore[method-assign]
    repo._ensure_supply_balances_tables = lambda conn: None  # type: ignore[method-assign]
    repo._row_to_dict = lambda r: dict(r)  # type: ignore[method-assign]
    repo.get_product_id_by_ozon_keys_map = lambda *, user_id: {  # type: ignore[method-assign]
        "ART-OZ": 77,
        "art-oz": 77,
        "12345": 77,
    }

    ledger: list[dict] = []
    inserts: list[tuple] = []

    class _Cur:
        rowcount = 1

        def __init__(self, rows=None):
            self._rows = rows or []

        def fetchall(self):
            return self._rows

        def fetchone(self):
            return self._rows[0] if self._rows else None

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            sql_s = str(sql)
            inserts.append((sql_s, tuple(params)))
            if "supply_stock_ozon_fbs_settled" in sql_s and "SELECT" in sql_s:
                return _Cur([])
            if "FROM supply_stock_movements" in sql_s and "SELECT" in sql_s:
                pn = "P-1"
                pid = 77
                prefix = f"{pn}:p{pid}:"
                rows = [
                    {
                        "kind": r["kind"],
                        "source_type": r["source_type"],
                        "qty": r["qty"],
                    }
                    for r in ledger
                    if str(r.get("source_id") or "").startswith(prefix)
                ]
                return _Cur(rows)
            if "INSERT INTO supply_stock_movements" in sql_s:
                # params: user, prod, product_id, qty, date, kind, source_type, source_id, comment, now
                ledger.append(
                    {
                        "kind": params[5],
                        "source_type": params[6],
                        "source_id": params[7],
                        "qty": params[3],
                    }
                )
                return _Cur()
            return _Cur()

    repo._connect = lambda: _Conn()  # type: ignore[method-assign]

    postings = [
        {
            "posting_number": "P-1",
            "tab": "delivering",
            "offer_id": "ART-OZ",
            "sku": "12345",
            "quantity": 2,
            "products_json": '[{"offer_id":"ART-OZ","sku":12345,"quantity":2}]',
        }
    ]
    s1 = ReviewRepository.reconcile_ozon_fbs_stock_postings(
        repo,
        user_id=1,
        production_id=9,
        postings=postings,
        movement_date="2026-08-28",
    )
    assert s1["shipped"] == 1
    ship_inserts = [
        params
        for sql, params in inserts
        if "INSERT INTO supply_stock_movements" in sql
    ]
    assert ship_inserts
    assert float(ship_inserts[0][3]) == -2.0
    assert ship_inserts[0][5] == "fbs_ship"
    assert ship_inserts[0][6] == "ozon_fbs_posting"

    inserts.clear()
    s2 = ReviewRepository.reconcile_ozon_fbs_stock_postings(
        repo,
        user_id=1,
        production_id=9,
        postings=postings,
        movement_date="2026-08-28",
    )
    assert s2["shipped"] == 0
    assert s2["ok"] >= 1
    assert not any("INSERT INTO supply_stock_movements" in sql for sql, _ in inserts)


def test_reconcile_ozon_no_ship_on_awaiting_deliver() -> None:
    repo = ReviewRepository.__new__(ReviewRepository)
    repo._sql = lambda q: q  # type: ignore[method-assign]
    repo._ensure_supply_balances_tables = lambda conn: None  # type: ignore[method-assign]
    repo._row_to_dict = lambda r: dict(r)  # type: ignore[method-assign]
    repo.get_product_id_by_ozon_keys_map = lambda *, user_id: {"ART-OZ": 77}  # type: ignore[method-assign]

    inserts: list[tuple] = []

    class _Cur:
        rowcount = 1

        def fetchall(self):
            return []

        def fetchone(self):
            return None

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            inserts.append((str(sql), tuple(params)))
            return _Cur()

    repo._connect = lambda: _Conn()  # type: ignore[method-assign]
    stats = ReviewRepository.reconcile_ozon_fbs_stock_postings(
        repo,
        user_id=1,
        production_id=9,
        postings=[
            {
                "posting_number": "P-2",
                "tab": "awaiting_deliver",
                "offer_id": "ART-OZ",
                "quantity": 1,
            }
        ],
        movement_date="2026-08-28",
    )
    assert stats["shipped"] == 0
    assert not any("INSERT INTO supply_stock_movements" in sql for sql, _ in inserts)


def test_reconcile_ozon_skips_settled() -> None:
    repo = ReviewRepository.__new__(ReviewRepository)
    repo._sql = lambda q: q  # type: ignore[method-assign]
    repo._ensure_supply_balances_tables = lambda conn: None  # type: ignore[method-assign]
    repo._row_to_dict = lambda r: dict(r)  # type: ignore[method-assign]
    repo.get_product_id_by_ozon_keys_map = lambda *, user_id: {"ART-OZ": 77}  # type: ignore[method-assign]

    class _Cur:
        rowcount = 1

        def __init__(self, row=None):
            self._row = row

        def fetchone(self):
            return self._row

        def fetchall(self):
            return []

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            if "supply_stock_ozon_fbs_settled" in str(sql) and "SELECT" in str(sql):
                return _Cur({"ok": 1})
            return _Cur()

    repo._connect = lambda: _Conn()  # type: ignore[method-assign]
    stats = ReviewRepository.reconcile_ozon_fbs_stock_postings(
        repo,
        user_id=1,
        production_id=9,
        postings=[
            {
                "posting_number": "P-3",
                "tab": "delivering",
                "offer_id": "ART-OZ",
                "quantity": 1,
            }
        ],
        movement_date="2026-08-28",
    )
    assert stats["settled"] == 1
    assert stats["shipped"] == 0


def test_reconcile_ozon_cancelled_does_not_reverse_after_ship() -> None:
    """After delivering ship, cancelled/arbitration must NOT return qty to stock."""
    repo = ReviewRepository.__new__(ReviewRepository)
    repo._sql = lambda q: q  # type: ignore[method-assign]
    repo._ensure_supply_balances_tables = lambda conn: None  # type: ignore[method-assign]
    repo._row_to_dict = lambda r: dict(r)  # type: ignore[method-assign]
    repo.get_product_id_by_ozon_keys_map = lambda *, user_id: {"ART-OZ": 77}  # type: ignore[method-assign]

    ledger: list[dict] = [
        {
            "kind": "fbs_ship",
            "source_type": "ozon_fbs_posting",
            "source_id": "P-9:p77:s:1",
            "qty": -1.0,
        }
    ]
    inserts: list[tuple] = []

    class _Cur:
        rowcount = 1

        def __init__(self, rows=None):
            self._rows = rows or []

        def fetchall(self):
            return self._rows

        def fetchone(self):
            return None

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            sql_s = str(sql)
            inserts.append((sql_s, tuple(params)))
            if "FROM supply_stock_movements" in sql_s and "SELECT" in sql_s:
                return _Cur(
                    [
                        {
                            "kind": r["kind"],
                            "source_type": r["source_type"],
                            "qty": r["qty"],
                        }
                        for r in ledger
                    ]
                )
            if "INSERT INTO supply_stock_movements" in sql_s:
                raise AssertionError("cancelled must not write stock movements")
            return _Cur()

    repo._connect = lambda: _Conn()  # type: ignore[method-assign]
    for tab in ("cancelled", "arbitration"):
        inserts.clear()
        stats = ReviewRepository.reconcile_ozon_fbs_stock_postings(
            repo,
            user_id=1,
            production_id=9,
            postings=[
                {
                    "posting_number": "P-9",
                    "tab": tab,
                    "offer_id": "ART-OZ",
                    "quantity": 1,
                }
            ],
            movement_date="2026-08-28",
        )
        assert stats["shipped"] == 0
        assert stats["reversed"] == 0
        assert stats["ok"] >= 1


def test_wb_reconcile_untouched_by_ozon_helpers() -> None:
    assert callable(getattr(ReviewRepository, "reconcile_wb_fbs_stock_orders"))
    assert callable(getattr(ReviewRepository, "reconcile_ozon_fbs_stock_postings"))
    assert (
        ReviewRepository.reconcile_wb_fbs_stock_orders
        is not ReviewRepository.reconcile_ozon_fbs_stock_postings
    )
