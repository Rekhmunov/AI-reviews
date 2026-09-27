"""Ozon FBS «Доставляются»: server pagination for the supplies list."""

from __future__ import annotations

from pathlib import Path

from review_processor import ozon_fbs as oz
from review_processor.ozon_fbs_supplies import (
    _clamp_supplies_page,
    _filter_supply_items_by_search,
    _list_supplies_tab_response,
)

ROOT = Path(__file__).resolve().parents[1]
OZ = (ROOT / "review_processor" / "ozon_fbs_supplies.py").read_text(encoding="utf-8")
WEB = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_clamp_supplies_page() -> None:
    assert _clamp_supplies_page(1, 50) == (1, 50)
    assert _clamp_supplies_page(0, 0) == (1, 1)
    assert _clamp_supplies_page(-3, 999) == (1, 100)
    assert _clamp_supplies_page("2", "25") == (2, 25)
    assert _clamp_supplies_page("x", "y") == (1, 50)


def test_filter_supply_items_by_search() -> None:
    items = [
        {"supply_id": "s1", "name": "Утро", "warehouse_label": "СКЛ-1"},
        {"supply_id": "s2", "name": "Вечер", "warehouse_label": "СКЛ-2"},
    ]
    assert len(_filter_supply_items_by_search(items, "")) == 2
    assert [x["supply_id"] for x in _filter_supply_items_by_search(items, "веч")] == ["s2"]
    assert [x["supply_id"] for x in _filter_supply_items_by_search(items, "скл-1")] == ["s1"]


def test_list_supplies_tab_response_paginates_before_enrich(monkeypatch) -> None:
    built = [
        {"supply_id": f"s{i}", "name": f"P{i}", "warehouse_label": "W", "order_count": 1}
        for i in range(1, 121)
    ]
    enriched_ids: list[str] = []

    def _build(*_a, **_k):
        return list(built)

    def _attach(*_a, items=None, **_k):
        for it in items or []:
            it["has_driver"] = False

    class _Repo:
        def map_ttn_ids_for_fbs_supplies(self, **_k):
            return {}

        def _connect(self):  # pragma: no cover - unused here
            raise AssertionError("should not connect")

    def _enrich(*_a, items=None, **_k):
        for it in items or []:
            enriched_ids.append(str(it.get("supply_id") or ""))
            it["row_tone"] = "ok"

    monkeypatch.setattr(
        "review_processor.ozon_fbs_supplies._build_supply_items_for_tab", _build
    )
    monkeypatch.setattr(
        "review_processor.ozon_fbs_supplies._attach_supply_drivers_to_items", _attach
    )
    monkeypatch.setattr(
        "review_processor.ozon_fbs_supplies.enrich_ozon_supply_items_row_tones", _enrich
    )
    monkeypatch.setattr(
        "review_processor.ozon_fbs_supplies.count_open_supplies", lambda *_a, **_k: 0
    )
    monkeypatch.setattr(
        "review_processor.ozon_fbs._tab_counts",
        lambda *_a, **_k: {"delivering": 120},
    )

    out = _list_supplies_tab_response(
        _Repo(),  # type: ignore[arg-type]
        user_id=1,
        source_id=2,
        tab=oz.TAB_DELIVERING,
        adopt_info={"adopted": 0, "created_supplies": []},
        client=object(),
        page=2,
        page_size=50,
    )
    assert out["total"] == 120
    assert out["page"] == 2
    assert out["page_size"] == 50
    assert len(out["items"]) == 50
    assert out["items"][0]["supply_id"] == "s51"
    assert out["items"][-1]["supply_id"] == "s100"
    assert enriched_ids == [f"s{i}" for i in range(51, 101)]
    assert all(it.get("ttn_id") == 0 for it in out["items"])
    assert all(it.get("row_tone") == "ok" for it in out["items"])

    # Out-of-range page clamps to the last page (no empty table).
    enriched_ids.clear()
    last = _list_supplies_tab_response(
        _Repo(),  # type: ignore[arg-type]
        user_id=1,
        source_id=2,
        tab=oz.TAB_DELIVERING,
        adopt_info={"adopted": 0, "created_supplies": []},
        client=object(),
        page=99,
        page_size=50,
    )
    assert last["page"] == 3
    assert len(last["items"]) == 20
    assert last["items"][0]["supply_id"] == "s101"


def test_awaiting_deliver_still_returns_all_without_forced_page() -> None:
    """Awaiting-deliver path does not pass page → no slice."""
    block = OZ.split("def list_awaiting_deliver_supplies", 1)[1].split(
        "def list_delivering_supplies", 1
    )[0]
    assert "page=" not in block
    assert "page_size=" not in block


def test_delivering_api_and_ui_wire_pagination() -> None:
    delivering = OZ.split("def list_delivering_supplies", 1)[1].split(
        "def list_delivering_supplies_cancellations", 1
    )[0]
    assert "page: int = 1" in delivering
    assert "page_size: int = 50" in delivering
    assert "page=page" in delivering
    assert "page_size=page_size" in delivering
    api = WEB.split("def ozon_fbs_list_supplies", 1)[1].split("\n    @app.", 1)[0]
    assert "page: int = 1" in api
    assert "page_size: int = 50" in api
    assert "search: str = \"\"" in api or "search: str = ''" in api
    load = JS.split("async function loadPostings", 1)[1].split(
        "const DELIVERING_COL_WIDTHS_PREFIX", 1
    )[0]
    assert "deliveringSupplies" in load
    assert "suppliesMode && !deliveringSupplies" in load
    assert "Number(data.total || 0)" in load
    assert "ozon_fbs.js?v=200" in HTML
