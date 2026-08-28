"""Local Ozon FBS «Перенести в доставку» — tab move + stock deduct, no Ozon API."""

from __future__ import annotations

from review_processor import ozon_fbs as oz
from review_processor import ozon_fbs_supplies as oz_sup


class _FakeRepo:
    def __init__(self, awaiting_rows: list[dict], delivering_count: int = 0):
        self.awaiting_rows = list(awaiting_rows)
        self.delivering_count = delivering_count
        self.updated: list[tuple] = []
        self.reconcile_calls: list[dict] = []
        self._productions = [{"id": 10}]

    def _sql(self, q: str) -> str:
        return q

    def _row_to_dict(self, r):
        return dict(r)

    def list_supply_productions(self, *, user_id: int):
        return list(self._productions)

    def reconcile_ozon_fbs_stock_postings(
        self, *, user_id, production_id, postings, movement_date
    ):
        self.reconcile_calls.append(
            {
                "user_id": user_id,
                "production_id": production_id,
                "postings": list(postings),
                "movement_date": movement_date,
            }
        )
        return {"shipped": len(postings), "reversed": 0, "skipped": 0, "ok": 0, "settled": 0}

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
                if "FROM ozon_fbs_supplies" in sql_s and "SELECT" in sql_s:
                    return _Cur(
                        [
                            {
                                "supply_id": "OZ-FBS-1",
                                "name": "Test",
                                "posting_numbers_json": "[]",
                            }
                        ]
                    )
                if "CREATE TABLE" in sql_s or "ALTER TABLE" in sql_s or "CREATE INDEX" in sql_s:
                    return _Cur()
                if "SELECT posting_number, tab" in sql_s:
                    return _Cur(repo.awaiting_rows)
                if "SELECT COUNT(*)" in sql_s:
                    return _Cur(n=repo.delivering_count)
                if "UPDATE ozon_fbs_postings" in sql_s:
                    repo.updated.append((sql_s, tuple(params)))
                    return _Cur()
                return _Cur()

        return _Conn()


def test_move_supply_to_delivering_updates_tab_and_reconciles_stock(monkeypatch) -> None:
    repo = _FakeRepo(
        [
            {
                "posting_number": "P-1",
                "tab": "awaiting_deliver",
                "offer_id": "ART",
                "sku": "1",
                "quantity": 2,
                "products_json": '[{"offer_id":"ART","sku":1,"quantity":2}]',
            },
            {
                "posting_number": "P-2",
                "tab": "awaiting_deliver",
                "offer_id": "ART",
                "sku": "1",
                "quantity": 1,
                "products_json": '[{"offer_id":"ART","sku":1,"quantity":1}]',
            },
        ]
    )
    monkeypatch.setattr(oz_sup, "ensure_ozon_fbs_supply_schema", lambda r: None)
    monkeypatch.setattr(oz, "ensure_ozon_fbs_tables", lambda r: None)
    monkeypatch.setattr(
        oz_sup,
        "get_supply",
        lambda r, **kw: {"supply_id": "OZ-FBS-1", "name": "Test"},
    )

    out = oz_sup.move_supply_to_delivering(
        repo, user_id=1, source_id=5, supply_id="OZ-FBS-1"
    )
    assert out["ok"] is True
    assert out["moved"] == 2
    assert len(repo.updated) == 1
    assert oz.TAB_DELIVERING in repo.updated[0][1]
    assert len(repo.reconcile_calls) == 1
    call = repo.reconcile_calls[0]
    assert call["production_id"] == 10
    assert all(p["tab"] == "delivering" for p in call["postings"])
    assert call["postings"][0]["posting_number"] == "P-1"


def test_move_supply_to_delivering_idempotent_when_already_moved(monkeypatch) -> None:
    repo = _FakeRepo([], delivering_count=3)
    monkeypatch.setattr(oz_sup, "ensure_ozon_fbs_supply_schema", lambda r: None)
    monkeypatch.setattr(oz, "ensure_ozon_fbs_tables", lambda r: None)
    monkeypatch.setattr(
        oz_sup,
        "get_supply",
        lambda r, **kw: {"supply_id": "OZ-FBS-1", "name": "Test"},
    )

    out = oz_sup.move_supply_to_delivering(
        repo, user_id=1, source_id=5, supply_id="OZ-FBS-1"
    )
    assert out["ok"] is True
    assert out["moved"] == 0
    assert out["already_delivering"] == 3
    assert repo.reconcile_calls == []
    assert repo.updated == []


def test_resolve_upsert_keeps_local_delivering_when_ozon_still_awaiting() -> None:
    status, tab = oz.resolve_upsert_status(
        local_status="delivering",
        local_tab="delivering",
        remote_status="awaiting_deliver",
    )
    assert tab == "delivering"
    assert status == "delivering"

    status2, tab2 = oz.resolve_upsert_status(
        local_status="delivering",
        local_tab="delivering",
        remote_status="delivered",
    )
    assert tab2 == "delivered"
