"""Ozon FBS owner-only «Проверить статус заказов» for delivering postings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from review_processor import ozon_fbs as oz
from review_processor import ozon_fbs_supplies as oz_sup

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
WEB = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
SUP = (ROOT / "review_processor" / "ozon_fbs_supplies.py").read_text(encoding="utf-8")


def test_ui_button_and_progress_in_sync_settings() -> None:
    assert 'id="ozonFbsDeliveringStatusCheckBtn"' in HTML
    assert "Проверить статус заказов" in HTML
    assert 'id="ozonFbsStatusCheckProgressModal"' in HTML
    assert "startOzonFbsDeliveringStatusCheck" in JS
    assert "closeOzonFbsStatusCheckProgress" in JS
    assert "/api/ozon-fbs/delivering-status-check" in JS
    assert "isTenantOwner" in JS[
        JS.find("async function startOzonFbsDeliveringStatusCheck") : JS.find(
            "async function startOzonFbsDeliveringStatusCheck"
        )
        + 600
    ]


def test_api_routes_owner_only() -> None:
    start = WEB.find("def ozon_fbs_delivering_status_check_start")
    status = WEB.find("def ozon_fbs_delivering_status_check_status")
    assert start > 0 and status > 0
    block = WEB[start : status + 800]
    assert "_is_wb_fbs_tenant_owner" in block
    assert "start_delivering_status_check_thread" in block
    assert "get_delivering_status_check_state" in block


def test_schema_has_delivering_listed() -> None:
    assert "delivering_listed" in SUP
    assert "pin_delivering_listed_supplies" in SUP
    assert "refresh_delivering_posting_statuses" in SUP
    assert "start_delivering_status_check_thread" in SUP


def test_build_supply_items_includes_empty_listed(monkeypatch) -> None:
    """Pinned supplies with 0 delivering orders still appear on the tab."""

    class _FakeRepo:
        def _sql(self, q: str) -> str:
            return q

        def _row_to_dict(self, r):
            return dict(r)

        def _connect(self):
            repo = self

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
                    sql_s = str(sql)
                    if "GROUP BY supply_id" in sql_s:
                        # Active delivering group for S-active only.
                        return _Cur(
                            [
                                {
                                    "supply_id": "S-active",
                                    "order_count": 2,
                                    "warehouse_name": "WH",
                                    "warehouse_id": 1,
                                    "last_posting_at": "2026-01-02",
                                }
                            ]
                        )
                    if "delivering_listed = TRUE" in sql_s and "FROM ozon_fbs_supplies" in sql_s:
                        return _Cur(
                            [
                                {
                                    "supply_id": "S-empty",
                                    "name": "Пустая",
                                    "warehouse_name": "WH2",
                                    "warehouse_id": 2,
                                    "created_at": "2026-01-01",
                                },
                                {
                                    "supply_id": "S-active",
                                    "name": "Активная",
                                    "warehouse_name": "WH",
                                    "warehouse_id": 1,
                                    "created_at": "2026-01-02",
                                },
                            ]
                        )
                    if "FROM ozon_fbs_supplies" in sql_s and "supply_id IN" in sql_s:
                        return _Cur(
                            [
                                {
                                    "supply_id": "S-active",
                                    "name": "Активная",
                                    "warehouse_name": "WH",
                                    "warehouse_id": 1,
                                    "created_at": "2026-01-02",
                                },
                                {
                                    "supply_id": "S-empty",
                                    "name": "Пустая",
                                    "warehouse_name": "WH2",
                                    "warehouse_id": 2,
                                    "created_at": "2026-01-01",
                                },
                            ]
                        )
                    if "UPDATE ozon_fbs_supplies" in sql_s:
                        return _Cur()
                    if "CREATE TABLE" in sql_s or "ALTER TABLE" in sql_s or "CREATE INDEX" in sql_s:
                        return _Cur()
                    return _Cur()

            return _Conn()

    monkeypatch.setattr(oz_sup, "ensure_ozon_fbs_supply_schema", lambda r: None)
    monkeypatch.setattr(oz_sup, "pin_delivering_listed_supplies", lambda *a, **k: 1)

    items = oz_sup._build_supply_items_for_tab(
        _FakeRepo(), user_id=1, source_id=5, tab=oz.TAB_DELIVERING
    )
    ids = [i["supply_id"] for i in items]
    assert ids == ["S-active", "S-empty"]
    by_id = {i["supply_id"]: i for i in items}
    assert by_id["S-active"]["order_count"] == 2
    assert by_id["S-empty"]["order_count"] == 0
    assert by_id["S-empty"]["delivering_listed"] is True


def test_refresh_delivering_posting_statuses_pins_and_updates(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class _Client:
        def __init__(self, *_a, **_k):
            pass

        def get_posting(self, pn: str) -> dict[str, Any]:
            return {"status": "delivered" if pn == "P-1" else "delivering"}

    monkeypatch.setattr(oz_sup, "ensure_ozon_fbs_supply_schema", lambda r: None)
    monkeypatch.setattr(oz, "ensure_ozon_fbs_tables", lambda r: None)
    monkeypatch.setattr(oz_sup, "OZON_FBS_STATUS_CHECK_PAUSE_SEC", 0)
    monkeypatch.setattr(
        oz_sup,
        "_pin_all_current_delivering_supplies",
        lambda *a, **k: ["S1"],
    )
    monkeypatch.setattr(
        oz_sup,
        "_list_delivering_posting_numbers",
        lambda *a, **k: ["P-1", "P-2"],
    )
    monkeypatch.setattr(oz, "OzonFbsClient", _Client)

    def _get_posting(**kwargs):
        return {
            "posting_number": kwargs["posting_number"],
            "tab": "delivering",
            "status": "delivering",
        }

    def _refresh(**kwargs):
        calls.append(dict(kwargs))
        tab = "delivered" if kwargs["posting_number"] == "P-1" else "delivering"
        return {
            "posting_number": kwargs["posting_number"],
            "tab": tab,
            "status": tab,
        }

    monkeypatch.setattr(oz, "get_posting_by_number", lambda *a, **k: _get_posting(**k))
    monkeypatch.setattr(oz, "refresh_posting_status_only", lambda *a, **k: _refresh(**k))

    progress: list[tuple[int, int]] = []
    out = oz_sup.refresh_delivering_posting_statuses(
        object(),  # type: ignore[arg-type]
        user_id=1,
        source_id=2,
        client_id="c",
        api_key="k",
        progress=lambda d, t, m: progress.append((d, t)),
    )
    assert out["checked"] == 2
    assert out["updated"] == 1
    assert out["errors"] == 0
    assert out["pinned_supplies"] == 1
    assert len(calls) == 2
    assert progress[-1] == (2, 2)


def test_move_to_delivering_pins_listed(monkeypatch) -> None:
    pinned: list[tuple] = []

    class _FakeRepo:
        def __init__(self):
            self.awaiting_rows = [
                {
                    "posting_number": "P-1",
                    "tab": "awaiting_deliver",
                    "offer_id": "A",
                    "sku": "1",
                    "quantity": 1,
                    "products_json": "[]",
                }
            ]
            self._productions = [{"id": 10}]

        def _sql(self, q: str) -> str:
            return q

        def _row_to_dict(self, r):
            return dict(r)

        def list_supply_productions(self, *, user_id: int):
            return list(self._productions)

        def reconcile_ozon_fbs_stock_postings(self, **kwargs):
            return {"shipped": 1, "reversed": 0, "skipped": 0, "ok": 0, "settled": 0}

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
                    if "UPDATE ozon_fbs_postings" in sql_s:
                        return _Cur()
                    return _Cur()

            return _Conn()

    monkeypatch.setattr(oz_sup, "ensure_ozon_fbs_supply_schema", lambda r: None)
    monkeypatch.setattr(oz, "ensure_ozon_fbs_tables", lambda r: None)
    monkeypatch.setattr(
        oz_sup,
        "get_supply",
        lambda r, **kw: {"supply_id": "OZ-FBS-1", "name": "Test"},
    )
    monkeypatch.setattr(
        oz_sup,
        "set_supply_delivering_listed",
        lambda *a, **k: pinned.append((k.get("supply_id"), k.get("listed"))),
    )

    out = oz_sup.move_supply_to_delivering(
        _FakeRepo(), user_id=1, source_id=5, supply_id="OZ-FBS-1"
    )
    assert out["moved"] == 1
    assert ("OZ-FBS-1", True) in pinned


def test_cache_bump() -> None:
    assert "ozon_fbs.js?v=199" in HTML
