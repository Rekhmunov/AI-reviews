"""Ozon FBS: operator removes one cancelled posting from a supply (no stock)."""

from __future__ import annotations

from pathlib import Path

import pytest

from review_processor import ozon_fbs as oz
from review_processor import ozon_fbs_supplies as oz_sup

ROOT = Path(__file__).resolve().parents[1]


class _FakeRepo:
    def __init__(self, posting: dict | None, supply_numbers: list[str] | None = None):
        self.posting = dict(posting) if posting else None
        self.supply_numbers = list(supply_numbers or [])
        self.updates: list[tuple] = []
        self.set_numbers_calls: list[list[str]] = []

    def _sql(self, q: str) -> str:
        return q

    def _row_to_dict(self, r):
        return dict(r)

    def _connect(self):
        repo = self

        class _Cur:
            def __init__(self, row=None):
                self._row = row

            def fetchone(self):
                return self._row

        class _Conn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=()):
                sql_s = str(sql)
                if "CREATE TABLE" in sql_s or "ALTER TABLE" in sql_s or "CREATE INDEX" in sql_s:
                    return _Cur()
                if "FROM ozon_fbs_postings" in sql_s and "SELECT" in sql_s:
                    return _Cur(repo.posting)
                if "UPDATE ozon_fbs_postings" in sql_s and "supply_id = ''" in sql_s:
                    repo.updates.append(params)
                    if repo.posting is not None:
                        repo.posting = dict(repo.posting)
                        repo.posting["supply_id"] = ""
                    return _Cur()
                return _Cur()

        return _Conn()


def test_remove_cancelled_posting_clears_supply_link(monkeypatch) -> None:
    repo = _FakeRepo(
        {
            "posting_number": "PN-CX",
            "supply_id": "OZ-1",
            "tab": oz.TAB_CANCELLED,
            "status": "cancelled",
        },
        supply_numbers=["PN-1", "PN-CX", "PN-2"],
    )
    monkeypatch.setattr(oz_sup, "ensure_ozon_fbs_supply_schema", lambda r: None)
    monkeypatch.setattr(oz, "ensure_ozon_fbs_tables", lambda r: None)
    monkeypatch.setattr(
        oz_sup,
        "get_supply",
        lambda r, **kw: {
            "supply_id": "OZ-1",
            "posting_numbers": list(repo.supply_numbers),
        },
    )

    def _set(repo_arg, *, user_id, source_id, supply_id, posting_numbers):
        repo.set_numbers_calls.append(list(posting_numbers))
        repo.supply_numbers = list(posting_numbers)

    monkeypatch.setattr(oz_sup, "_set_supply_posting_numbers", _set)

    out = oz_sup.remove_cancelled_posting_from_supply(
        repo, user_id=1, source_id=5, supply_id="OZ-1", posting_number="PN-CX"
    )
    assert out["ok"] is True
    assert out["removed"] is True
    assert out["posting_number"] == "PN-CX"
    assert len(repo.updates) == 1
    assert repo.set_numbers_calls == [["PN-1", "PN-2"]]
    assert repo.posting["supply_id"] == ""


def test_remove_rejects_non_cancelled(monkeypatch) -> None:
    repo = _FakeRepo(
        {
            "posting_number": "PN-1",
            "supply_id": "OZ-1",
            "tab": oz.TAB_AWAITING_DELIVER,
            "status": "awaiting_deliver",
        }
    )
    monkeypatch.setattr(oz_sup, "ensure_ozon_fbs_supply_schema", lambda r: None)
    monkeypatch.setattr(oz, "ensure_ozon_fbs_tables", lambda r: None)
    with pytest.raises(ValueError, match="только отменённое"):
        oz_sup.remove_cancelled_posting_from_supply(
            repo, user_id=1, source_id=5, supply_id="OZ-1", posting_number="PN-1"
        )
    assert repo.updates == []


def test_remove_rejects_wrong_supply(monkeypatch) -> None:
    repo = _FakeRepo(
        {
            "posting_number": "PN-CX",
            "supply_id": "OZ-OTHER",
            "tab": oz.TAB_CANCELLED,
            "status": "cancelled",
        }
    )
    monkeypatch.setattr(oz_sup, "ensure_ozon_fbs_supply_schema", lambda r: None)
    monkeypatch.setattr(oz, "ensure_ozon_fbs_tables", lambda r: None)
    with pytest.raises(RuntimeError, match="не входит"):
        oz_sup.remove_cancelled_posting_from_supply(
            repo, user_id=1, source_id=5, supply_id="OZ-1", posting_number="PN-CX"
        )


def test_remove_cancelled_ui_wiring() -> None:
    js = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
    html = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
    assert "Удалить товар из поставки" in js
    assert "function ozonFbsRemoveCancelledPostingFromSupply" in js
    assert "window.ozonFbsRemoveCancelledPostingFromSupply" in js
    assert "/remove-cancelled" in js
    assert "_ozonFbsRemovePostingFromOpenModals(pn)" in js
    # Cancelled rows keep the ⋮ menu (empty only when posting number missing).
    actions_start = js.find("function _ozonFbsModalRowActionsHtml")
    actions_fn = js[actions_start : actions_start + 700]
    assert "_ozonFbsRowIsCancelled(row)" not in actions_fn.split("return")[0]
    assert "ozon_fbs.js?v=169" in html


def test_endpoint_registered() -> None:
    web = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
    assert (
        "/api/ozon-fbs/supplies/{supply_id}/postings/{posting_number}/remove-cancelled"
        in web
    )
    assert "oz_sup.remove_cancelled_posting_from_supply" in web
