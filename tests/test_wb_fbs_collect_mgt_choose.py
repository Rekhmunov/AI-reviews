"""WB FBS «Собрать все МГТ»: one existing supply → choose modal (like Ozon)."""

from __future__ import annotations

from review_processor.wb_fbs import _plan_mgt_group


_SOURCE = "ИП Тест ФБС"


def test_plan_mgt_group_one_matching_is_choose_not_add_one() -> None:
    existing: set[str] = set()
    empties: list[dict] = []
    matching = [
        {
            "supply_id": "WB-GI-1",
            "name": "Поставка МГТ",
            "cargo_type": 1,
            "is_b2b": False,
            "order_ids": [1],
        }
    ]
    group = _plan_mgt_group(
        source_name=_SOURCE,
        is_b2b=False,
        order_ids=[10, 11],
        mgt_matching=matching,
        empties=empties,
        existing_names=existing,
        warehouse_id=1943422,
        cross_border_type=None,
    )
    assert group["mode"] == "choose"
    assert group["default_supply_id"] == "WB-GI-1"
    assert len(group["compatible_supplies"]) == 1
    assert group["compatible_supplies"][0]["supply_id"] == "WB-GI-1"
    assert group["suggested_name"]
    # Suggested title reserved for «create new» across buckets.
    assert group["suggested_name"] in existing


def test_plan_mgt_group_one_empty_is_choose() -> None:
    existing: set[str] = set()
    empties = [
        {
            "supply_id": "WB-EMPTY-1",
            "name": "Пустая",
            "cargo_type": 0,
            "is_b2b": False,
            "order_ids": [],
        }
    ]
    group = _plan_mgt_group(
        source_name=_SOURCE,
        is_b2b=False,
        order_ids=[5],
        mgt_matching=[],
        empties=empties,
        existing_names=existing,
        warehouse_id=1,
    )
    assert group["mode"] == "choose"
    assert group["default_supply_id"] == "WB-EMPTY-1"
    assert empties == []  # claimed so other buckets cannot reuse


def test_preview_one_mgt_supply_needs_modal(monkeypatch) -> None:
    from review_processor import wb_fbs as wb

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
                "supply_id": "WB-GI-9",
                "name": "Поставка на сборке",
                "cargo_type": 1,
                "is_b2b": False,
                "order_ids": [1],
                "order_ids_json": "[1]",
                "raw_json": "{}",
            }
        ]

    monkeypatch.setattr(wb, "_load_new_mgt_orders", fake_orders)
    monkeypatch.setattr(wb, "list_supplies", fake_supplies)
    monkeypatch.setattr(wb, "ensure_wb_fbs_tables", lambda repo: None)
    monkeypatch.setattr(
        wb, "_source_display_name", lambda repo, *, user_id, source_id: _SOURCE
    )
    monkeypatch.setattr(
        wb,
        "_supply_matches_mgt_traits",
        lambda *a, **k: True,
    )

    preview = wb.preview_collect_mgt(object(), user_id=1, source_id=2)
    assert preview["ok"] is True
    assert preview["needs_modal"] is True
    assert preview["groups"][0]["mode"] == "choose"
    assert preview["groups"][0]["default_supply_id"] == "WB-GI-9"
    assert len(preview["groups"][0]["compatible_supplies"]) == 1
