"""Остатки: продажа оператором + смена kind в журнале движений."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
REPO_PY = (ROOT / "review_processor" / "repository.py").read_text(encoding="utf-8")
WEB_PY = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")


def test_operator_sale_kind_in_stock_kinds() -> None:
    from review_processor.repository import (
        ReviewRepository,
        SUPPLY_STOCK_KIND_LABELS,
        SUPPLY_STOCK_SALES_KINDS,
        supply_stock_kind_label,
        supply_window_sold_qty,
    )

    assert "operator_sale" in ReviewRepository._STOCK_KINDS
    assert "operator_sale" in SUPPLY_STOCK_SALES_KINDS
    assert "fbs_ship" in SUPPLY_STOCK_SALES_KINDS
    assert "operator_writeoff" not in SUPPLY_STOCK_SALES_KINDS
    assert supply_stock_kind_label("operator_sale") == "Продажа оператором"
    assert "operator_sale" in SUPPLY_STOCK_KIND_LABELS


def test_supply_window_sold_counts_operator_sale_not_writeoff() -> None:
    from review_processor.repository import supply_window_sold_qty

    rows = [
        {"kind": "fbs_ship", "qty": -3, "outside_window": False},
        {"kind": "operator_sale", "qty": -5, "outside_window": False},
        {"kind": "operator_writeoff", "qty": -29, "outside_window": False},
        {"kind": "operator_sale", "qty": -2, "outside_window": True},
        {"kind": "receipt", "qty": 10, "outside_window": False},
    ]
    assert supply_window_sold_qty(rows) == 8.0


def test_sum_sales_sql_includes_operator_sale() -> None:
    assert "operator_sale" in REPO_PY
    assert "OR kind = 'operator_sale'" in REPO_PY
    assert "def update_supply_stock_movement_kind" in REPO_PY


def test_writeoff_api_supports_sale_mode() -> None:
    assert "mode: str = Field(default=\"writeoff\"" in WEB_PY
    assert 'kind = "operator_sale" if is_sale else "operator_writeoff"' in WEB_PY
    assert 'source_type = "manual_sale" if is_sale else "manual_writeoff"' in WEB_PY
    assert '@app.patch("/api/supply-balances/movements/{movement_id}/kind")' in WEB_PY
    assert "class SupplyStockMovementKindRequest" in WEB_PY


def test_writeoff_modal_has_sale_option() -> None:
    start = APP_HTML.find('id="supplyStockWriteoffModal"')
    end = APP_HTML.find('id="supplyStockReceiptModal"')
    block = APP_HTML[start:end]
    assert 'value="writeoff">Списание<' in block
    assert 'value="sale">Продажа<' in block


def test_writeoff_js_sends_mode() -> None:
    fn = APP_JS[
        APP_JS.find("async function saveSupplyStockWriteoff") : APP_JS.find(
            "window.saveSupplyStockWriteoff"
        )
    ]
    assert "mode" in fn
    assert '=== "sale"' in fn
    assert "Продажа сохранена" in fn


def test_movements_journal_kind_menu_ui() -> None:
    assert "function _sbRenderMovementKindMenu" in APP_JS
    assert "function toggleSupplyStockMovementKindMenu" in APP_JS
    assert "function changeSupplyStockMovementKind" in APP_JS
    assert "sb-movements-kind-caret" in APP_JS
    assert "/api/supply-balances/movements/" in APP_JS
    assert "operator_sale" in APP_JS
    assert ".sb-movements-kind-menu" in STYLE
    assert ".sb-movements-kind-caret" in STYLE


def test_day_sold_js_counts_operator_sale() -> None:
    block = APP_JS[
        APP_JS.find("function _sbDayReceiptAndSold") : APP_JS.find(
            "function _sbWindowSoldQty"
        )
    ]
    assert "_sbSalesKinds" in block
    assert "salesKinds.has(kind)" in block
    sales = APP_JS[
        APP_JS.find("function _sbSalesKinds") : APP_JS.find(
            "function _sbRenderMovementKindMenu"
        )
    ]
    assert "operator_sale" in sales
    assert "fbs_ship" in sales


def test_cache_bumped() -> None:
    assert "app.js?v=727" in APP_HTML
    assert "style.css?v=448" in APP_HTML
