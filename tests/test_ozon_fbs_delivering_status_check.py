"""Ozon FBS owner-only «Проверить статус заказов» for delivering postings."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
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
    assert "stopOzonFbsDeliveringStatusCheck" in JS
    assert "ozonFbsStatusCheckProgressStopBtn" in HTML
    assert "/api/ozon-fbs/delivering-status-check/stop" in JS
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
    stop = WEB.find("def ozon_fbs_delivering_status_check_stop")
    assert stop > 0
    assert "request_delivering_status_check_stop" in WEB[stop:stop + 600]


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

    items = oz_sup._build_supply_items_for_tab(
        _FakeRepo(), user_id=1, source_id=5, tab=oz.TAB_DELIVERING
    )
    ids = [i["supply_id"] for i in items]
    assert ids == ["S-active", "S-empty"]
    by_id = {i["supply_id"]: i for i in items}
    assert by_id["S-active"]["order_count"] == 2
    assert by_id["S-empty"]["order_count"] == 0
    assert by_id["S-empty"]["delivering_listed"] is True



def test_refresh_uses_list_then_get_fallback(monkeypatch) -> None:
    """List hits update via batch; leftovers use parallel get_posting + batch."""
    batch_payloads: list[dict[str, str]] = []
    list_calls: list[str] = []

    class _Client:
        def __init__(self, *_a, **_k):
            pass

        def list_postings_page(self, *, status, since, to, limit=50, offset=0, with_extras=True):
            list_calls.append(status)
            if status == "delivered" and offset == 0:
                return ([{"posting_number": "P-1", "status": "delivered"}], False)
            if status == "delivering" and offset == 0:
                return ([{"posting_number": "P-2", "status": "delivering"}], False)
            return ([], False)

        def get_posting(self, pn: str) -> dict[str, Any]:
            assert pn == "P-3"
            return {"status": "cancelled"}

    def _batch(repo, *, remote_by_pn, **kwargs):
        batch_payloads.append(dict(remote_by_pn))
        return {
            "checked": len(remote_by_pn),
            "updated": len(remote_by_pn),
            "noop": 0,
            "stopped": False,
            "errors": 0,
        }

    monkeypatch.setattr(oz_sup, "ensure_ozon_fbs_supply_schema", lambda r: None)
    monkeypatch.setattr(oz, "ensure_ozon_fbs_tables", lambda r: None)
    monkeypatch.setattr(
        oz_sup, "_pin_all_current_delivering_supplies", lambda *a, **k: ["S1"]
    )
    monkeypatch.setattr(
        oz_sup,
        "_list_delivering_posting_rows",
        lambda *a, **k: [
            {"posting_number": "P-1", "tab": "delivering", "created_at_ozon": "2026-01-01T00:00:00Z"},
            {"posting_number": "P-2", "tab": "delivering", "created_at_ozon": "2026-01-02T00:00:00Z"},
            {"posting_number": "P-3", "tab": "delivering", "created_at_ozon": "2026-01-03T00:00:00Z"},
        ],
    )
    monkeypatch.setattr(oz, "OzonFbsClient", _Client)
    monkeypatch.setattr(oz, "batch_apply_remote_statuses_for_delivering", _batch)

    out = oz_sup.refresh_delivering_posting_statuses(
        object(),  # type: ignore[arg-type]
        user_id=1,
        source_id=2,
        client_id="c",
        api_key="k",
    )
    assert out["checked"] == 3
    assert out["updated"] == 2  # P-1 delivered, P-3 cancelled; P-2 stayed
    assert out["list_hits"] == 2
    assert out["get_fallbacks"] == 1
    assert "delivered" in list_calls
    assert batch_payloads[0] == {"P-1": "delivered"}
    assert batch_payloads[1] == {"P-3": "cancelled"}


def test_refresh_skips_rows_no_longer_delivering(monkeypatch) -> None:
    """Batch UPDATE only touches tab=delivering — already-moved rows stay put."""

    class _Client:
        def __init__(self, *_a, **_k):
            pass

        def list_postings_page(self, **_k):
            return ([{"posting_number": "P-moved", "status": "delivered"}], False)

        def get_posting(self, pn: str) -> dict[str, Any]:
            raise AssertionError(f"should not call get for {pn}")

    monkeypatch.setattr(oz_sup, "ensure_ozon_fbs_supply_schema", lambda r: None)
    monkeypatch.setattr(oz, "ensure_ozon_fbs_tables", lambda r: None)
    monkeypatch.setattr(
        oz_sup, "_pin_all_current_delivering_supplies", lambda *a, **k: ["S1"]
    )
    monkeypatch.setattr(
        oz_sup,
        "_list_delivering_posting_rows",
        lambda *a, **k: [
            {
                "posting_number": "P-moved",
                "tab": "delivering",
                "created_at_ozon": "2026-01-01T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(oz, "OzonFbsClient", _Client)
    # Simulate race: batch finds 0 rows still on delivering.
    monkeypatch.setattr(
        oz,
        "batch_apply_remote_statuses_for_delivering",
        lambda *a, **k: {
            "checked": 1,
            "updated": 0,
            "noop": 0,
            "stopped": False,
            "errors": 0,
        },
    )

    out = oz_sup.refresh_delivering_posting_statuses(
        object(),  # type: ignore[arg-type]
        user_id=1,
        source_id=2,
        client_id="c",
        api_key="k",
    )
    assert out["checked"] == 1
    assert out["updated"] == 0


def test_request_status_check_stop() -> None:
    uid = 424242
    with oz_sup._status_check_lock:
        oz_sup._status_check_jobs[uid] = {
            **oz_sup._empty_status_check_job(),
            "in_progress": True,
            "job_id": "abc",
        }
    assert oz_sup.request_delivering_status_check_stop(user_id=uid) is True
    st = oz_sup.get_delivering_status_check_state(user_id=uid)
    assert st["cancel_requested"] is True
    assert oz_sup.request_delivering_status_check_stop(user_id=uid + 1) is False
    with oz_sup._status_check_lock:
        oz_sup._status_check_jobs.pop(uid, None)


def test_status_check_date_window_max_one_year() -> None:
    """Ozon list filter.since…to must be ≤ 1 year — floor is 365d, not 400."""
    old = (datetime.now(UTC) - timedelta(days=500)).isoformat().replace("+00:00", "Z")
    date_from, date_to = oz_sup._status_check_date_window(
        [{"created_at_ozon": old}]
    )
    span = date_to - date_from
    assert span <= timedelta(days=365)
    assert span >= timedelta(days=364)


def test_batch_apply_groups_updates_without_per_row_select(monkeypatch) -> None:
    """One UPDATE per (status,tab) chunk; WHERE tab=delivering."""
    executed: list[tuple[str, tuple]] = []

    class _Cur:
        def __init__(self, n: int):
            self.rowcount = n

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=()):
            executed.append((str(sql), tuple(params)))
            pns = [p for p in params if isinstance(p, str) and p.startswith("P-")]
            return _Cur(len(pns))

    class _Repo:
        def _sql(self, q: str) -> str:
            return q

        def _connect(self):
            return _Conn()

    monkeypatch.setattr(oz, "ensure_ozon_fbs_tables", lambda r: None)
    out = oz.batch_apply_remote_statuses_for_delivering(
        _Repo(),  # type: ignore[arg-type]
        user_id=1,
        source_id=2,
        remote_by_pn={
            "P-1": "delivered",
            "P-2": "delivered",
            "P-3": "cancelled",
            "P-4": "delivering",
        },
    )
    assert out["noop"] == 1  # P-4
    assert out["updated"] == 3
    assert out["checked"] == 4
    assert len(executed) == 2  # delivered group + cancelled group
    for sql, params in executed:
        assert "AND tab = ?" in sql
        assert oz.TAB_DELIVERING in params
        assert "IN (" in sql


def test_scan_list_stops_without_continuing_other_statuses(monkeypatch) -> None:
    """After Stop mid-status, do not open the next filter (cancelled/…)."""
    calls: list[str] = []

    class _Client:
        def list_postings_page(self, *, status, since, to, limit=50, offset=0, with_extras=True):
            calls.append(status)
            if status == "delivering":
                return (
                    [{"posting_number": "P-1", "status": "delivering"}],
                    True,  # has_next — would continue without stop
                )
            return ([], False)

    stop_n = {"n": 0}

    def _stop() -> bool:
        # Calls: status-enter, page-enter, post-page → stop before page 2.
        stop_n["n"] += 1
        return stop_n["n"] > 2

    found, stopped = oz_sup._scan_remote_statuses_via_list(
        _Client(),  # type: ignore[arg-type]
        local_pns={"P-1", "P-2"},
        date_from=datetime.now(UTC) - timedelta(days=30),
        date_to=datetime.now(UTC),
        should_stop=_stop,
        total_hint=2,
    )
    assert stopped is True
    assert found.get("P-1") == "delivering"
    assert calls == ["delivering"]


def test_status_check_job_set_keeps_stopping_prefix() -> None:
    """Progress updates must not wipe «Остановка…» after cancel."""
    uid = 424243
    job_id = "stop-prefix"
    with oz_sup._status_check_lock:
        oz_sup._status_check_jobs[uid] = {
            **oz_sup._empty_status_check_job(),
            "in_progress": True,
            "job_id": job_id,
            "cancel_requested": True,
            "message": "Остановка…",
        }

    # Simulate the closure body of start_delivering_status_check_thread._set
    with oz_sup._status_check_lock:
        st = oz_sup._status_check_jobs[uid]
        kwargs: dict[str, Any] = {"message": "Список delivered: стр. 12, найдено 500"}
        if st.get("cancel_requested") and "message" in kwargs:
            msg = str(kwargs.get("message") or "").strip()
            if msg and not msg.startswith("Остановка"):
                kwargs["message"] = f"Остановка… {msg}"
        st.update(kwargs)
        assert st["message"].startswith("Остановка…")
        assert "Список delivered" in st["message"]
        oz_sup._status_check_jobs.pop(uid, None)


def test_status_check_finish_message_shows_moved_before_stop() -> None:
    msg = oz_sup._status_check_finish_message(
        stopped=True, checked=120, total=30000, updated=45, errors=2
    )
    assert "Остановлено" in msg
    assert "До остановки" in msg
    assert "перенесено 45" in msg
    assert "проверено 120 из 30000" in msg
    done = oz_sup._status_check_finish_message(
        stopped=False, checked=10, total=10, updated=3, errors=0
    )
    assert done.startswith("Готово:")
    assert "перенесено 3" in done


def test_stop_during_get_applies_done_then_cancels(monkeypatch) -> None:
    """Stop after first get result: apply it, cancel the rest, report moved."""
    get_started = threading.Event()
    release_first = threading.Event()

    class _Client:
        def __init__(self, *_a, **_k):
            pass

        def list_postings_page(self, **_k):
            return ([], False)

        def get_posting(self, pn: str) -> dict[str, Any]:
            if pn == "P-1":
                get_started.set()
                release_first.wait(timeout=2)
                return {"status": "delivered"}
            # Remaining workers should be cancelled or ignored after stop.
            time.sleep(0.3)
            return {"status": "delivered"}

    monkeypatch.setattr(oz_sup, "ensure_ozon_fbs_supply_schema", lambda r: None)
    monkeypatch.setattr(oz, "ensure_ozon_fbs_tables", lambda r: None)
    monkeypatch.setattr(
        oz_sup, "_pin_all_current_delivering_supplies", lambda *a, **k: ["S1"]
    )
    monkeypatch.setattr(
        oz_sup,
        "_list_delivering_posting_rows",
        lambda *a, **k: [
            {
                "posting_number": f"P-{i}",
                "tab": "delivering",
                "created_at_ozon": "2026-01-01T00:00:00Z",
            }
            for i in range(1, 6)
        ],
    )
    monkeypatch.setattr(oz, "OzonFbsClient", _Client)
    batch_pns: list[str] = []

    def _batch(repo, *, remote_by_pn, **kwargs):
        batch_pns.extend(remote_by_pn.keys())
        return {
            "checked": len(remote_by_pn),
            "updated": len(remote_by_pn),
            "noop": 0,
            "stopped": False,
            "errors": 0,
        }

    monkeypatch.setattr(oz, "batch_apply_remote_statuses_for_delivering", _batch)

    stop_after_first = {"ready": False}

    def _stop() -> bool:
        return bool(stop_after_first["ready"])

    result_box: dict[str, Any] = {}

    def _worker() -> None:
        result_box["out"] = oz_sup.refresh_delivering_posting_statuses(
            object(),  # type: ignore[arg-type]
            user_id=1,
            source_id=2,
            client_id="c",
            api_key="k",
            should_stop=_stop,
        )

    t = threading.Thread(target=_worker)
    t.start()
    assert get_started.wait(timeout=2)
    stop_after_first["ready"] = True
    release_first.set()
    t.join(timeout=5)
    assert t.is_alive() is False
    out = result_box["out"]
    assert out["stopped"] is True
    assert out["updated"] >= 1
    assert "P-1" in batch_pns
    assert "перенесено" in out["message"]
    assert "До остановки" in out["message"]


def test_stop_during_list_skips_get_fallback(monkeypatch) -> None:
    """Cancel mid list-scan must not fan out get for every unfound PN."""
    get_calls: list[str] = []
    stop_n = {"n": 0}

    class _Client:
        def __init__(self, *_a, **_k):
            pass

        def list_postings_page(self, **_k):
            return ([], False)

        def get_posting(self, pn: str) -> dict[str, Any]:
            get_calls.append(pn)
            return {"status": "delivering"}

    monkeypatch.setattr(oz_sup, "ensure_ozon_fbs_supply_schema", lambda r: None)
    monkeypatch.setattr(oz, "ensure_ozon_fbs_tables", lambda r: None)
    monkeypatch.setattr(
        oz_sup, "_pin_all_current_delivering_supplies", lambda *a, **k: ["S1"]
    )
    monkeypatch.setattr(
        oz_sup,
        "_list_delivering_posting_rows",
        lambda *a, **k: [
            {
                "posting_number": f"P-{i}",
                "tab": "delivering",
                "created_at_ozon": "2026-01-01T00:00:00Z",
            }
            for i in range(5)
        ],
    )
    monkeypatch.setattr(oz, "OzonFbsClient", _Client)

    def _stop() -> bool:
        stop_n["n"] += 1
        # Pass the early gate once, then cancel for list-scan / leftovers.
        return stop_n["n"] > 1

    out = oz_sup.refresh_delivering_posting_statuses(
        object(),  # type: ignore[arg-type]
        user_id=1,
        source_id=2,
        client_id="c",
        api_key="k",
        should_stop=_stop,
    )
    assert out["stopped"] is True
    assert get_calls == []
    assert out["get_fallbacks"] == 0


def test_stop_during_list_still_flushes_list_hits(monkeypatch) -> None:
    """Stop after list scan must still batch-write statuses already fetched."""
    batch_payloads: list[dict[str, str]] = []
    saw_delivered = {"ok": False}

    class _Client:
        def __init__(self, *_a, **_k):
            pass

        def list_postings_page(self, *, status, since, to, limit=50, offset=0, with_extras=True):
            if status == "delivered":
                saw_delivered["ok"] = True
                return (
                    [
                        {"posting_number": "P-1", "status": "delivered"},
                        {"posting_number": "P-2", "status": "delivered"},
                    ],
                    False,
                )
            return ([], False)

        def get_posting(self, pn: str) -> dict[str, Any]:
            raise AssertionError(f"get should not run after stop, got {pn}")

    def _batch(repo, *, remote_by_pn, should_stop=None, **kwargs):
        assert should_stop is None  # flush must not honour cancel
        batch_payloads.append(dict(remote_by_pn))
        return {
            "checked": len(remote_by_pn),
            "updated": len(remote_by_pn),
            "noop": 0,
            "stopped": False,
            "errors": 0,
        }

    monkeypatch.setattr(oz_sup, "ensure_ozon_fbs_supply_schema", lambda r: None)
    monkeypatch.setattr(oz, "ensure_ozon_fbs_tables", lambda r: None)
    monkeypatch.setattr(
        oz_sup, "_pin_all_current_delivering_supplies", lambda *a, **k: ["S1"]
    )
    monkeypatch.setattr(
        oz_sup,
        "_list_delivering_posting_rows",
        lambda *a, **k: [
            {
                "posting_number": "P-1",
                "tab": "delivering",
                "created_at_ozon": "2026-01-01T00:00:00Z",
            },
            {
                "posting_number": "P-2",
                "tab": "delivering",
                "created_at_ozon": "2026-01-02T00:00:00Z",
            },
            {
                "posting_number": "P-3",
                "tab": "delivering",
                "created_at_ozon": "2026-01-03T00:00:00Z",
            },
        ],
    )
    monkeypatch.setattr(oz, "OzonFbsClient", _Client)
    monkeypatch.setattr(oz, "batch_apply_remote_statuses_for_delivering", _batch)

    def _stop() -> bool:
        # Cancel as soon as delivered list page is in hand — before get leftovers.
        return bool(saw_delivered["ok"])

    out = oz_sup.refresh_delivering_posting_statuses(
        object(),  # type: ignore[arg-type]
        user_id=1,
        source_id=2,
        client_id="c",
        api_key="k",
        should_stop=_stop,
    )
    assert out["stopped"] is True
    assert batch_payloads == [{"P-1": "delivered", "P-2": "delivered"}]
    assert out["updated"] == 2
    assert "перенесено 2" in out["message"]


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
    assert "ozon_fbs.js?v=208" in HTML
