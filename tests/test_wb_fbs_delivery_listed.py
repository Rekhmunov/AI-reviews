"""WB FBS: keep empty supplies pinned on «В доставке» (like Ozon delivering_listed)."""

from __future__ import annotations

from typing import Any

from review_processor import wb_fbs as wb


def test_schema_has_delivery_listed() -> None:
    src = (wb.__file__ and open(wb.__file__, encoding="utf-8").read()) or ""
    assert "delivery_listed" in src
    assert "set_supply_delivery_listed" in src
    assert "pin_delivery_listed_supplies" in src
    assert "_list_empty_delivery_listed_supplies" in src


def test_list_delivery_includes_empty_pinned(monkeypatch) -> None:
    """Pinned supply with 0 delivery orders still appears on the tab."""

    class _FakeRepo:
        def _sql(self, q: str) -> str:
            return q

        def _row_to_dict(self, r):
            return dict(r)

        def map_ttn_ids_for_fbs_supplies(self, **kwargs):
            return {}

        def _connect(self):
            repo = self

            class _Cur:
                def __init__(self, rows=None, n=0):
                    self._rows = rows or []
                    self.rowcount = n

                def fetchall(self):
                    return list(self._rows)

                def fetchone(self):
                    if self._rows:
                        return self._rows[0]
                    return {"n": 0}

            class _Conn:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def execute(self, sql, params=()):
                    sql_s = str(sql)
                    if "delivery_listed = TRUE" in sql_s and "FROM wb_fbs_supplies" in sql_s:
                        return _Cur(
                            [
                                {
                                    "supply_id": "WB-empty",
                                    "source_id": 5,
                                    "name": "Пустая",
                                    "done": True,
                                    "cargo_type": 0,
                                    "destination_office_id": None,
                                    "created_at_wb": "2026-01-01T00:00:00Z",
                                    "closed_at_wb": "2026-01-02T00:00:00Z",
                                    "scan_dt": None,
                                    "boxes_json": '[{"id":1}]',
                                    "order_ids_json": "[]",
                                    "raw_json": "{}",
                                }
                            ]
                        )
                    if "DISTINCT source_id, supply_id" in sql_s and "wb_fbs_orders" in sql_s:
                        # Active delivery orders only for WB-active.
                        if "delivery_listed" in sql_s:
                            return _Cur()
                        return _Cur(
                            [{"source_id": 5, "supply_id": "WB-active"}]
                        )
                    if "GROUP BY o.user_id, o.source_id, o.supply_id" in sql_s:
                        if "COUNT(*) AS n FROM" in sql_s:
                            return _Cur([{"n": 1}])
                        return _Cur(
                            [
                                {
                                    "supply_id": "WB-active",
                                    "source_id": 5,
                                    "order_count": 2,
                                    "order_ids_agg": [11, 12],
                                    "warehouse_id": 1,
                                    "offices_json": "[]",
                                    "order_cargo_type": 0,
                                    "name": "Активная",
                                    "done_int": 1,
                                    "cargo_type": 0,
                                    "destination_office_id": None,
                                    "created_at_wb": "2026-01-03T00:00:00Z",
                                    "closed_at_wb": None,
                                    "scan_dt": None,
                                    "boxes_json": "[]",
                                    "raw_json": "{}",
                                }
                            ]
                        )
                    if "COUNT(*) AS n FROM (" in sql_s:
                        return _Cur([{"n": 1}])
                    if "SET delivery_listed" in sql_s or "delivery_listed = TRUE" in sql_s:
                        return _Cur(n=1)
                    if "GROUP BY tab" in sql_s:
                        return _Cur([{"tab": "delivery", "n": 2}])
                    if "cargo_type = 1" in sql_s:
                        return _Cur([{"n": 0}])
                    if "FROM wb_fbs_supplies" in sql_s and "done" in sql_s:
                        return _Cur([{"n": 0}])
                    if "CREATE" in sql_s or "ALTER" in sql_s or "INDEX" in sql_s:
                        return _Cur()
                    return _Cur()

            return _Conn()

    monkeypatch.setattr(wb, "ensure_wb_fbs_tables", lambda r: None)
    monkeypatch.setattr(wb, "_attach_supply_drivers_to_items", lambda *a, **k: None)

    out = wb.list_delivery_supplies(
        _FakeRepo(),  # type: ignore[arg-type]
        user_id=1,
        source_id=5,
        page=1,
        page_size=50,
    )
    ids = [i["supply_id"] for i in out["items"]]
    assert "WB-active" in ids
    assert "WB-empty" in ids
    by_id = {i["supply_id"]: i for i in out["items"]}
    assert by_id["WB-empty"]["order_count"] == 0
    assert by_id["WB-empty"]["boxes_count"] == 1
    assert by_id["WB-empty"]["delivery_listed"] is True
    assert by_id["WB-active"]["order_count"] == 2


def test_upsert_done_supply_pins_delivery_listed(monkeypatch) -> None:
    pinned: list[tuple] = []

    class _FakeRepo:
        def _sql(self, q: str) -> str:
            return q

        def _connect(self):
            class _Conn:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def execute(self, sql, params=()):
                    return None

            return _Conn()

    monkeypatch.setattr(wb, "ensure_wb_fbs_tables", lambda r: None)
    monkeypatch.setattr(
        wb,
        "set_supply_delivery_listed",
        lambda *a, **k: pinned.append((k.get("supply_id"), k.get("listed"))),
    )

    wb.upsert_supply(
        _FakeRepo(),  # type: ignore[arg-type]
        user_id=1,
        source_id=2,
        supply={"id": "WB-1", "done": True, "name": "X"},
        order_ids=[1],
        boxes=[],
    )
    assert ("WB-1", True) in pinned


def test_supply_is_in_delivery_true_when_only_pinned(monkeypatch) -> None:
    class _FakeRepo:
        def _sql(self, q: str) -> str:
            return q

        def _connect(self):
            class _Conn:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def execute(self, sql, params=()):
                    sql_s = str(sql)

                    class _Cur:
                        def fetchone(self_inner):
                            if "FROM wb_fbs_orders" in sql_s:
                                return None
                            if "delivery_listed = TRUE" in sql_s:
                                return {"ok": 1}
                            return None

                    return _Cur()

            return _Conn()

    monkeypatch.setattr(wb, "ensure_wb_fbs_tables", lambda r: None)
    assert (
        wb.supply_is_in_delivery(
            _FakeRepo(),  # type: ignore[arg-type]
            user_id=1,
            source_id=2,
            supply_id="WB-1",
        )
        is True
    )
