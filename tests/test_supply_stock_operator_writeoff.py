"""Поставки → Остатки: списание оператором + кнопка Корректировка только owner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
REPO_PY = (ROOT / "review_processor" / "repository.py").read_text(encoding="utf-8")
WEB_PY = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")


def test_toolbar_writeoff_and_add_labels() -> None:
    assert 'id="supplyBalancesWriteoffBtn"' in APP_HTML
    assert 'onclick="openSupplyStockWriteoffModal()"' in APP_HTML
    assert ">Списать<" in APP_HTML
    assert 'id="supplyBalancesReceiptBtn"' in APP_HTML
    start = APP_HTML.find('id="supplyBalancesReceiptBtn"')
    btn_chunk = APP_HTML[start : start + 160]
    assert ">Добавить<" in btn_chunk
    assert "Добавить на склад" not in btn_chunk


def test_adjustment_button_owner_only() -> None:
    assert 'id="supplyBalancesAdjBtn"' in APP_HTML
    assert "supplyBalancesAdjBtn" in APP_JS
    assert "supplyAdjBtn.hidden = !isTenantOwner()" in APP_JS


def test_writeoff_modal_markup() -> None:
    start = APP_HTML.find('id="supplyStockWriteoffModal"')
    end = APP_HTML.find('id="supplyStockReceiptModal"')
    assert start > 0 and end > start
    block = APP_HTML[start:end]
    assert 'value="writeoff">Списание<' in block
    assert 'id="supplyStockWriteoffDate"' in block
    assert "Импорт" not in block
    assert 'id="supplyStockWriteoffSearch"' in block
    assert 'id="supplyStockWriteoffFilterBtn"' in block
    assert 'id="supplyStockWriteoffList"' in block
    assert "saveSupplyStockWriteoff()" in block


def test_writeoff_js_wiring() -> None:
    assert "function openSupplyStockWriteoffModal" in APP_JS
    assert "function closeSupplyStockWriteoffModal" in APP_JS
    assert "function saveSupplyStockWriteoff" in APP_JS
    assert "function renderSupplyStockWriteoffList" in APP_JS
    assert '/api/supply-balances/writeoff' in APP_JS


def test_operator_writeoff_kind_in_backend() -> None:
    assert '"operator_writeoff"' in REPO_PY
    assert 'kind="operator_writeoff"' in WEB_PY
    assert '"Списание оператором"' in WEB_PY
    assert WEB_PY.count('"Списание оператором"') >= 2
    assert '@app.post("/api/supply-balances/writeoff")' in WEB_PY
    assert "qty\": -abs(float(line[\"qty\"]))" in WEB_PY or "qty\": -abs" in WEB_PY


def test_app_js_cache_bump() -> None:
    assert "app.js?v=702" in APP_HTML


def test_add_supply_stock_movements_accepts_operator_writeoff() -> None:
    from review_processor.repository import ReviewRepository

    assert "operator_writeoff" in ReviewRepository._STOCK_KINDS
