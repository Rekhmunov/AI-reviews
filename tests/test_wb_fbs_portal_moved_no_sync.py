"""WB FBS: portal-moved stays on assembly; MGT collect excludes delivering."""

from __future__ import annotations

from pathlib import Path

from review_processor import wb_fbs

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_resolve_upsert_does_not_move_to_delivery_on_complete() -> None:
    assert (
        wb_fbs.resolve_upsert_tab(
            local_tab="assembly",
            remote_supplier_status="complete",
            remote_wb_status="sorted",
        )
        == "assembly"
    )
    assert (
        wb_fbs.resolve_upsert_tab(
            local_tab="",
            remote_supplier_status="complete",
            remote_wb_status="waiting",
        )
        == "assembly"
    )


def test_supply_blocked_for_collect_when_done() -> None:
    assert (
        wb_fbs.supply_blocked_for_collect(
            object(),
            user_id=1,
            source_id=2,
            supply={"supply_id": "WB-GI-1", "done": True, "source_id": 2},
        )
        is True
    )


def test_supply_blocked_for_collect_when_in_delivery(monkeypatch) -> None:
    monkeypatch.setattr(
        wb_fbs,
        "supply_is_in_delivery",
        lambda *a, **k: True,
    )
    assert (
        wb_fbs.supply_blocked_for_collect(
            object(),
            user_id=1,
            source_id=2,
            supply={"supply_id": "WB-GI-2", "done": False, "source_id": 2},
        )
        is True
    )


def test_supply_not_blocked_when_open_on_assembly(monkeypatch) -> None:
    monkeypatch.setattr(
        wb_fbs,
        "supply_is_in_delivery",
        lambda *a, **k: False,
    )
    assert (
        wb_fbs.supply_blocked_for_collect(
            object(),
            user_id=1,
            source_id=2,
            supply={"supply_id": "WB-GI-3", "done": False, "source_id": 2},
        )
        is False
    )


def test_preview_collect_mgt_skips_done_and_delivery_supplies(monkeypatch) -> None:
    def fake_orders(repo, *, user_id, source_id):
        return [
            {
                "order_id": 10,
                "is_b2b": False,
                "warehouse_id": 1943422,
                "cross_border_type": None,
            }
        ]

    def fake_supplies(repo, *, user_id, source_id, only_open=True):
        return [
            {
                "supply_id": "WB-DONE",
                "name": "Закрыта на портале",
                "cargo_type": 1,
                "is_b2b": False,
                "done": True,
                "order_ids": [1],
                "order_ids_json": "[1]",
                "raw_json": "{}",
            },
            {
                "supply_id": "WB-DELIV",
                "name": "Уже в доставке",
                "cargo_type": 1,
                "is_b2b": False,
                "done": False,
                "order_ids": [2],
                "order_ids_json": "[2]",
                "raw_json": "{}",
            },
            {
                "supply_id": "WB-OPEN",
                "name": "На сборке",
                "cargo_type": 1,
                "is_b2b": False,
                "done": False,
                "order_ids": [3],
                "order_ids_json": "[3]",
                "raw_json": "{}",
            },
        ]

    def fake_blocked(repo, *, user_id, source_id, supply):
        sid = str(supply.get("supply_id") or "")
        return sid in ("WB-DONE", "WB-DELIV")

    monkeypatch.setattr(wb_fbs, "_load_new_mgt_orders", fake_orders)
    monkeypatch.setattr(wb_fbs, "list_supplies", fake_supplies)
    monkeypatch.setattr(wb_fbs, "ensure_wb_fbs_tables", lambda repo: None)
    monkeypatch.setattr(
        wb_fbs,
        "_source_display_name",
        lambda repo, *, user_id, source_id: "ИП Тест",
    )
    monkeypatch.setattr(
        wb_fbs,
        "_supply_matches_mgt_traits",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(wb_fbs, "supply_blocked_for_collect", fake_blocked)

    preview = wb_fbs.preview_collect_mgt(object(), user_id=1, source_id=2)
    assert preview["ok"] is True
    group = preview["groups"][0]
    ids = [s["supply_id"] for s in group["compatible_supplies"]]
    assert ids == ["WB-OPEN"]
    assert "WB-DONE" not in ids
    assert "WB-DELIV" not in ids


def test_compatible_supplies_excludes_blocked(monkeypatch) -> None:
    def fake_supplies(repo, *, user_id, source_id, only_open=True):
        return [
            {
                "supply_id": "WB-BLOCKED",
                "name": "Доставляется",
                "cargo_type": 1,
                "done": False,
                "order_ids": [1],
                "order_ids_json": "[1]",
                "raw_json": "{}",
            },
            {
                "supply_id": "WB-OK",
                "name": "Сборка",
                "cargo_type": 1,
                "done": False,
                "order_ids": [2],
                "order_ids_json": "[2]",
                "raw_json": "{}",
            },
        ]

    monkeypatch.setattr(wb_fbs, "list_supplies", fake_supplies)
    monkeypatch.setattr(
        wb_fbs,
        "supply_blocked_for_collect",
        lambda repo, *, user_id, source_id, supply: supply["supply_id"] == "WB-BLOCKED",
    )
    monkeypatch.setattr(
        wb_fbs,
        "_supply_warehouse_id",
        lambda *a, **k: 10,
    )
    monkeypatch.setattr(wb_fbs, "_coalesce_b2b_flag", lambda raw: False)
    monkeypatch.setattr(wb_fbs, "_parse_json_list", lambda x: [])
    monkeypatch.setattr(wb_fbs, "_parse_json_obj", lambda x: {})
    monkeypatch.setattr(wb_fbs, "_supply_is_empty", lambda s: False)

    out = wb_fbs._compatible_supplies_for_traits(
        object(),
        user_id=1,
        source_id=2,
        traits={
            "cargo_type": 1,
            "is_b2b": False,
            "warehouse_id": 10,
            "cross_border_type": None,
        },
    )
    assert [s["supply_id"] for s in out] == ["WB-OK"]


def test_list_item_portal_moved_flag_on_assembly() -> None:
    item = wb_fbs._supply_list_item_from_group_row(
        {
            "supply_id": "WB-GI-X",
            "source_id": 1,
            "order_count": 1,
            "order_ids_agg": [1],
            "done_int": 1,
            "cargo_type": 1,
            "name": "Тест",
            "boxes_json": "[]",
            "offices_json": "[]",
            "raw_json": "{}",
        },
        tab_key="assembly",
    )
    assert item is not None
    assert item["done"] is True
    assert item["portal_moved"] is True

    item_del = wb_fbs._supply_list_item_from_group_row(
        {
            "supply_id": "WB-GI-Y",
            "source_id": 1,
            "order_count": 1,
            "order_ids_agg": [1],
            "done_int": 1,
            "cargo_type": 1,
            "name": "Тест",
            "boxes_json": "[]",
            "offices_json": "[]",
            "raw_json": "{}",
        },
        tab_key="delivery",
    )
    assert item_del is not None
    assert item_del["portal_moved"] is False


def test_ui_badge_portal_moved() -> None:
    assert "Перенесена на портале" in JS
    assert "portal-moved" in JS
    assert "s.portal_moved || s.done" in JS
    assert ".wb-fbs-badge.portal-moved" in CSS
    assert "wb-fbs-sd-chip-portal-moved" in CSS
    assert "app.js?v=724" in HTML
    assert "style.css?v=445" in HTML


def test_sync_done_supplies_do_not_pin_delivery() -> None:
    src = (ROOT / "review_processor" / "wb_fbs.py").read_text(encoding="utf-8")
    assert "pin_delivery_when_done=False" in src
    assert "pin_delivery_when_done: bool = True" in src


def test_refresh_order_statuses_light_uses_resolve_upsert_tab(monkeypatch) -> None:
    """Light status refresh must not auto-advance assembly → delivery."""

    class _Cur:
        def __init__(self, rows=None):
            self._rows = rows or []

        def fetchall(self):
            return self._rows

        def fetchone(self):
            return self._rows[0] if self._rows else None

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=()):
            sql_s = str(sql)
            if "SELECT order_id, tab" in sql_s:
                return _Cur(
                    [{"order_id": 101, "tab": "assembly"}]
                )
            self.last = (sql_s, params)
            return _Cur()

    class _Repo:
        def _connect(self):
            return _Conn()

        def _sql(self, s):
            return s

    class _Client:
        def __init__(self, key):
            pass

        def get_statuses(self, ids):
            return [
                {
                    "id": 101,
                    "supplierStatus": "complete",
                    "wbStatus": "sorted",
                }
            ]

    captured: list[dict] = []

    def fake_resolve(**kwargs):
        captured.append(kwargs)
        return "assembly"

    monkeypatch.setattr(wb_fbs, "WbFbsClient", _Client)
    monkeypatch.setattr(wb_fbs, "resolve_upsert_tab", fake_resolve)
    monkeypatch.setattr(wb_fbs, "_utc_now", lambda: "now")

    n = wb_fbs.refresh_order_statuses_light(
        _Repo(),
        user_id=1,
        source_id=2,
        order_ids=[101],
        api_key="key",
    )
    assert n == 1
    assert captured
    assert captured[0]["local_tab"] == "assembly"
    assert captured[0]["remote_supplier_status"] == "complete"


def test_preview_keeps_blocked_supply_names_for_conflicts(monkeypatch) -> None:
    def fake_orders(repo, *, user_id, source_id):
        return [
            {
                "order_id": 10,
                "is_b2b": False,
                "warehouse_id": 1,
                "cross_border_type": None,
            }
        ]

    def fake_supplies(repo, *, user_id, source_id, only_open=True):
        return [
            {
                "supply_id": "WB-DELIV",
                "name": "Поставка МГТ",
                "cargo_type": 1,
                "done": False,
                "order_ids": [1],
                "order_ids_json": "[1]",
                "raw_json": "{}",
            }
        ]

    monkeypatch.setattr(wb_fbs, "_load_new_mgt_orders", fake_orders)
    monkeypatch.setattr(wb_fbs, "list_supplies", fake_supplies)
    monkeypatch.setattr(wb_fbs, "ensure_wb_fbs_tables", lambda repo: None)
    monkeypatch.setattr(
        wb_fbs,
        "_source_display_name",
        lambda repo, *, user_id, source_id: "ИП",
    )
    monkeypatch.setattr(wb_fbs, "supply_blocked_for_collect", lambda *a, **k: True)
    monkeypatch.setattr(
        wb_fbs, "_supply_matches_mgt_traits", lambda *a, **k: True
    )

    preview = wb_fbs.preview_collect_mgt(object(), user_id=1, source_id=2)
    assert "Поставка МГТ" in (preview.get("existing_names") or [])
    # Blocked supply is not offered for collect.
    group = preview["groups"][0]
    assert group["compatible_supplies"] == []
