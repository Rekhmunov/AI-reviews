"""Поставки → Остатки: status shows filtered as-of sum, no click hint."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_balance_status_sums_filtered_rows() -> None:
    assert "function _sbRefreshBalanceStatus()" in APP_JS
    assert "Нажмите цифру" not in APP_JS
    assert "Остаток на ${asOfLabel}: ${_sbQtyText(total)} шт." in APP_JS
    fn = APP_JS.split("function _sbRefreshBalanceStatus()", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "_sbDataRowMatchesCategoryFilters" in fn
    assert "_sbOrderCurrentQty" in fn
    assert 'viewMode !== "balance"' in fn
    assert 'parts.join(" | ")' in fn
    assert "ниже минимума" not in fn
    assert "belowNote" not in fn
    assert "belowCount" not in fn


def test_balance_status_recalculates_on_filter() -> None:
    apply = APP_JS.split("function applySupplyBalancesSearchFilter()", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "_sbRefreshBalanceStatus();" in apply
    load = APP_JS.split("async function loadSupplyBalancesData()", 1)[1].split(
        "async function loadSupplyBalancesSalesData()", 1
    )[0]
    assert "_sbRefreshBalanceStatus();" in load
    assert "Нажмите цифру" not in load
    assert "app.js?v=698" in APP_HTML
