"""Per-item journal keeps older opening/adjustment «+» when day window is empty."""

from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

from review_processor.repository import ReviewRepository

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
WEB_PY = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
REPO_PY = (ROOT / "review_processor" / "repository.py").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_basis_helper_wired_in_api_and_ui() -> None:
    assert "list_supply_stock_basis_movements_for_item" in REPO_PY
    assert "list_supply_stock_basis_movements_for_item" in WEB_PY
    assert "basis_added" in WEB_PY
    assert "outside_window" in WEB_PY
    assert "basis_added" in APP_JS
    assert "outside_window" in APP_JS
    assert "раньше выбранного периода" in APP_JS
    assert "production_id: Number(supplyBalancesState.productionId" in APP_JS
    assert "app.js?v=554" in APP_HTML


@pytest.mark.skipif(not os.environ.get("APP_DB_URL"), reason="APP_DB_URL required")
def test_basis_returns_old_opening_outside_day_window() -> None:
    repo = ReviewRepository(os.environ["APP_DB_URL"])
    uid = 900011
    pid = 900011
    iid = 900011
    today = date.today()
    old = (today - timedelta(days=40)).isoformat()
    from_s = (today - timedelta(days=9)).isoformat()
    to_s = today.isoformat()
    src = f"test_basis:{uuid.uuid4().hex}"

    with repo._connect() as conn:
        repo._ensure_supply_balances_tables(conn)
        conn.execute(
            repo._sql(
                "DELETE FROM supply_stock_movements WHERE user_id = ? AND source_type = 'test_basis'"
            ),
            (uid,),
        )

    try:
        saved = repo.add_supply_stock_movements(
            user_id=uid,
            production_id=pid,
            movement_date=old,
            kind="opening",
            source_type="test_basis",
            items=[
                {
                    "item_type": "product",
                    "item_id": iid,
                    "qty": 42,
                    "source_id": src,
                }
            ],
            created_by=uid,
        )
        assert saved >= 1
        bal = repo.sum_supply_stock_balances(
            user_id=uid, production_id=pid, as_of=to_s
        )
        assert bal.get(("product", iid)) == 42

        window = repo.list_supply_stock_movements_for_item(
            user_id=uid,
            production_id=pid,
            item_type="product",
            item_id=iid,
            date_from=from_s,
            date_to=to_s,
            limit=100,
        )
        assert window == []

        basis = repo.list_supply_stock_basis_movements_for_item(
            user_id=uid,
            production_id=pid,
            item_type="product",
            item_id=iid,
            before_date=from_s,
            limit=10,
        )
        assert len(basis) == 1
        assert float(basis[0]["qty"]) == 42
        assert basis[0].get("outside_window") is True
        assert str(basis[0].get("kind")) == "opening"
    finally:
        with repo._connect() as conn:
            conn.execute(
                repo._sql(
                    "DELETE FROM supply_stock_movements WHERE user_id = ? AND source_type = 'test_basis'"
                ),
                (uid,),
            )
