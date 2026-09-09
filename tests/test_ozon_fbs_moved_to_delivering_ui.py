"""Ozon FBS supply modal: moved-to-delivering date + history triangle."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web_templates" / "app.html"
JS = ROOT / "web_static" / "ozon_fbs.js"
CSS = ROOT / "web_static" / "style.css"


def test_moved_to_delivering_markup_and_render() -> None:
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    cargo_idx = html.find('id="ozonFbsSupplyDetailCargo"')
    moved_idx = html.find('id="ozonFbsSupplyDetailMovedAt"')
    assert cargo_idx > 0
    assert moved_idx > cargo_idx
    neighborhood = html[cargo_idx : moved_idx + 180]
    assert "wb-fbs-sd-cargo-inline" in neighborhood
    assert "ozon-fbs-sd-moved" in neighborhood
    assert "wb-fbs-sd-meta-row" in html[max(0, cargo_idx - 200) : moved_idx]

    assert "function _ozonFbsRenderMovedToDelivering(" in js
    assert "Перенесена в доставку:" in js
    assert "ozon-fbs-sd-moved-hist-btn" in js
    assert "moved_to_delivering_at_display" in js
    assert "moved_to_delivering_history" in js
    assert "history.length > 1" in js or "showHist" in js
    assert "_ozonFbsRenderMovedToDelivering(supply)" in js
    assert "_ozonFbsRenderMovedToDelivering(null)" in js
    assert "_ozonFbsCloseMovedToDeliveringHistory" in js

    assert ".ozon-fbs-sd-moved" in css
    assert ".ozon-fbs-sd-moved-hist-btn" in css
    assert ".ozon-fbs-sd-moved-hist" in css
    assert "ozon_fbs.js?v=142" in html
    assert "style.css?v=" in html


def test_containers_only_this_supply_filter_ui() -> None:
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    assert 'id="ozonFbsContainersOnlyThisSupply"' in html
    assert "ГМ у этой поставки" in html
    sc_idx = html.find('id="ozonFbsContainersShowScAccepted"')
    only_idx = html.find('id="ozonFbsContainersOnlyThisSupply"')
    assert sc_idx > 0 and only_idx > sc_idx

    assert "onlyThisSupply" in js
    assert "only_this_supply" in js
    assert "onOzonFbsContainersOnlyThisSupplyChange" in js
    assert "только ГМ этой поставки" in js
    assert ".ozon-fbs-containers-filters" in css


def test_list_supply_moved_events_oldest_first_latest_via_getter() -> None:
    from datetime import UTC, datetime
    from unittest.mock import MagicMock, patch

    from review_processor import ozon_fbs_containers as ct
    from review_processor import ozon_fbs_ops_log as ops_log

    repo = MagicMock()
    repo._sql.side_effect = lambda s: s
    rows = [
        {"created_at": datetime(2026, 3, 1, 10, 0, tzinfo=UTC)},
        {"created_at": datetime(2026, 3, 5, 12, 30, tzinfo=UTC)},
    ]
    with patch.object(ops_log, "ensure_ozon_fbs_ops_log_table"), patch.object(
        repo, "_connect"
    ) as conn_ctx:
        conn = MagicMock()
        conn_ctx.return_value.__enter__.return_value = conn
        conn.execute.return_value.fetchall.return_value = rows
        repo._row_to_dict.side_effect = lambda r: r
        events = ct.list_supply_moved_to_delivering_events(
            repo, user_id=1, source_id=2, supply_id="S1"
        )
        latest = ct.get_supply_moved_to_delivering_at(
            repo, user_id=1, source_id=2, supply_id="S1"
        )
    assert len(events) == 2
    assert events[0].startswith("2026-03-01")
    assert events[-1].startswith("2026-03-05")
    assert latest == events[-1]
    sql = str(conn.execute.call_args[0][0])
    assert "ASC" in sql.upper()
    assert ops_log.ACTION_MOVE_DELIVERING in conn.execute.call_args[0][1]
