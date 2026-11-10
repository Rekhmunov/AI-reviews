"""WB FBS delivery/toolbar search: empty pinned + stickers + order ids."""

from __future__ import annotations

from review_processor import wb_fbs as wb


def test_orders_filter_sql_includes_sticker_fields() -> None:
    where, params = wb._orders_filter_sql(
        user_id=1, source_id=2, tab="delivery", search="59544735112"
    )
    assert "sticker_barcode" in where
    assert "sticker_part_a" in where
    assert "sticker_part_b" in where
    assert where.count("ILIKE ?") >= 8
    assert params[0] == 1
    assert params[1] == 2
    assert params[2] == "delivery"
    assert all(p == "%59544735112%" for p in params[3:])


def test_empty_pinned_search_matches_order_and_exposes_ids(monkeypatch) -> None:
    """Pinned supply without delivery-tab orders is findable by order id."""
    executed: list[str] = []

    class _FakeRepo:
        def _sql(self, q: str) -> str:
            return q

        def _row_to_dict(self, r):
            return dict(r)

        def _connect(self):
            class _Cur:
                def __init__(self, rows=None):
                    self._rows = rows or []

                def fetchall(self):
                    return list(self._rows)

                def fetchone(self):
                    return self._rows[0] if self._rows else None

            class _Conn:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def execute(self, sql, params=()):
                    executed.append(str(sql))
                    sql_s = str(sql)
                    if "delivery_listed = TRUE" in sql_s and "FROM wb_fbs_supplies" in sql_s:
                        # Search must reach order_ids_json / EXISTS orders.
                        assert "order_ids_json" in sql_s
                        assert "EXISTS" in sql_s
                        assert "sticker_barcode" in sql_s
                        assert params and "%13833711%" in params
                        return _Cur(
                            [
                                {
                                    "supply_id": "WB-GI-EMPTY",
                                    "source_id": 5,
                                    "name": "Пустая",
                                    "done": True,
                                    "cargo_type": 1,
                                    "destination_office_id": None,
                                    "created_at_wb": "2026-11-05T00:00:00Z",
                                    "closed_at_wb": "2026-11-05T12:00:00Z",
                                    "scan_dt": "2026-11-05T13:00:00Z",
                                    "boxes_json": '[{"id":"WB-TRBX-1"}]',
                                    "order_ids_json": "[13833711,13833712]",
                                    "raw_json": "{}",
                                }
                            ]
                        )
                    if "DISTINCT source_id, supply_id" in sql_s:
                        return _Cur([])
                    return _Cur()

            return _Conn()

    monkeypatch.setattr(wb, "ensure_wb_fbs_tables", lambda r: None)
    items = wb._list_empty_delivery_listed_supplies(
        _FakeRepo(),  # type: ignore[arg-type]
        user_id=1,
        source_id=5,
        search="13833711",
    )
    assert len(items) == 1
    assert items[0]["supply_id"] == "WB-GI-EMPTY"
    assert items[0]["order_count"] == 0
    assert items[0]["order_ids"] == [13833711, 13833712]
    assert items[0]["delivery_listed"] is True
    assert any("EXISTS" in sql for sql in executed)


def test_supplies_tab_search_sql_includes_stickers() -> None:
    src = open(wb.__file__, encoding="utf-8").read()
    assert "o.sticker_barcode" in src
    assert "o.sticker_part_a" in src
    # Active delivery/assembly aggregate search.
    assert (
        "OR COALESCE(o.sticker_barcode, '') ILIKE ?" in src
        or "COALESCE(o.sticker_barcode, '') ILIKE ?" in src
    )


def test_lookup_keeps_server_hits_ui() -> None:
    js = open("web_static/app.js", encoding="utf-8").read()
    assert "else if (nonIdItems.length)" in js
    assert "suppliesMode && Array.isArray(data.items) && data.items.length" in js


def test_lookup_sticker_fallback_wired() -> None:
    src = open(wb.__file__, encoding="utf-8").read()
    assert "find_orders_by_sticker_scan" in src
    assert "lookup sticker fallback" in src
