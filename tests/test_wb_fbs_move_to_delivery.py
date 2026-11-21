"""Local WB FBS «Перенести в доставку» — tab move + stock deduct, no WB API."""

from __future__ import annotations

from review_processor import wb_fbs


class _FakeRepo:
    def __init__(self, assembly_rows: list[dict], delivery_count: int = 0, has_supply: bool = True):
        self.assembly_rows = list(assembly_rows)
        self.delivery_count = delivery_count
        self.has_supply = has_supply
        self.updated: list[tuple] = []
        self.reconcile_calls: list[dict] = []
        self.listed_calls: list[dict] = []
        self._productions = [{"id": 10}]

    def _sql(self, q: str) -> str:
        return q

    def _row_to_dict(self, r):
        return dict(r)

    def list_supply_productions(self, *, user_id: int):
        return list(self._productions)

    def reconcile_wb_fbs_stock_orders(
        self, *, user_id, production_id, orders, movement_date
    ):
        self.reconcile_calls.append(
            {
                "user_id": user_id,
                "production_id": production_id,
                "orders": list(orders),
                "movement_date": movement_date,
            }
        )
        return {"shipped": len(orders), "reversed": 0, "skipped": 0, "ok": 0, "settled": 0}

    def _connect(self):
        repo = self

        class _Cur:
            def __init__(self, rows=None, n=0):
                self._rows = rows or []
                self._n = n

            def fetchall(self):
                return self._rows

            def fetchone(self):
                if self._rows:
                    return self._rows[0]
                return {"n": self._n}

        class _Conn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=()):
                sql_s = str(sql)
                if "FROM wb_fbs_supplies" in sql_s and "SELECT supply_id, name" in sql_s:
                    if not repo.has_supply:
                        return _Cur([])
                    return _Cur(
                        [
                            {
                                "supply_id": "WB-FBS-1",
                                "name": "Test",
                                "done": False,
                            }
                        ]
                    )
                if "CREATE TABLE" in sql_s or "ALTER TABLE" in sql_s or "CREATE INDEX" in sql_s:
                    return _Cur()
                if "SELECT order_id, tab, article" in sql_s:
                    return _Cur(repo.assembly_rows)
                if "SELECT COUNT(*)" in sql_s:
                    return _Cur(n=repo.delivery_count)
                if "UPDATE wb_fbs_orders" in sql_s:
                    repo.updated.append((sql_s, tuple(params)))
                    return _Cur()
                if "UPDATE wb_fbs_supplies" in sql_s and "delivery_listed" in sql_s:
                    repo.listed_calls.append({"sql": sql_s, "params": tuple(params)})
                    return _Cur()
                return _Cur()

        return _Conn()


def test_resolve_upsert_keeps_local_delivery_when_wb_still_confirm() -> None:
    tab = wb_fbs.resolve_upsert_tab(
        local_tab="delivery",
        remote_supplier_status="confirm",
        remote_wb_status="waiting",
    )
    assert tab == "delivery"

    tab2 = wb_fbs.resolve_upsert_tab(
        local_tab="assembly",
        remote_supplier_status="complete",
        remote_wb_status="sorted",
    )
    assert tab2 == "delivery"

    tab3 = wb_fbs.resolve_upsert_tab(
        local_tab="delivery",
        remote_supplier_status="cancel",
        remote_wb_status="canceled",
    )
    assert tab3 == "cancelled"


def test_move_supply_to_delivery_updates_tab_and_reconciles_stock(monkeypatch) -> None:
    repo = _FakeRepo(
        [
            {
                "order_id": 101,
                "tab": "assembly",
                "article": "ART",
                "nm_id": "1",
            },
            {
                "order_id": 102,
                "tab": "assembly",
                "article": "ART",
                "nm_id": "1",
            },
        ]
    )
    monkeypatch.setattr(wb_fbs, "ensure_wb_fbs_tables", lambda r: None)

    out = wb_fbs.move_supply_to_delivery(
        repo, user_id=1, source_id=5, supply_id="WB-FBS-1"
    )
    assert out["ok"] is True
    assert out["moved"] == 2
    assert len(repo.updated) == 1
    assert wb_fbs.TAB_DELIVERY in repo.updated[0][1]
    assert len(repo.reconcile_calls) == 1
    call = repo.reconcile_calls[0]
    assert call["production_id"] == 10
    assert all(o["tab"] == "delivery" for o in call["orders"])
    assert call["orders"][0]["order_id"] == 101
    assert repo.listed_calls


def test_move_supply_to_delivery_idempotent_when_already_moved(monkeypatch) -> None:
    repo = _FakeRepo([], delivery_count=3)
    monkeypatch.setattr(wb_fbs, "ensure_wb_fbs_tables", lambda r: None)

    out = wb_fbs.move_supply_to_delivery(
        repo, user_id=1, source_id=5, supply_id="WB-FBS-1"
    )
    assert out["ok"] is True
    assert out["moved"] == 0
    assert out["already_delivery"] == 3
    assert repo.reconcile_calls == []
    assert repo.updated == []
