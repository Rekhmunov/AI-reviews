"""Поставки → Остатки → Добавить на склад: импорт Excel из «Заказ по остаткам»."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")


def test_import_button_left_of_filters() -> None:
    chunk_start = APP_HTML.find('id="supplyStockReceiptModal"')
    chunk_end = APP_HTML.find('id="supplyStockReceiptScanQtyModal"')
    assert chunk_start > 0 and chunk_end > chunk_start
    chunk = APP_HTML[chunk_start:chunk_end]
    assert 'id="supplyStockReceiptImportBtn"' in chunk
    assert "triggerSupplyStockReceiptImport()" in chunk
    assert 'id="supplyStockReceiptImportFile"' in chunk
    assert 'id="supplyStockReceiptFilterBtn"' in chunk
    assert chunk.find("supplyStockReceiptImportBtn") < chunk.find(
        "supplyStockReceiptFilterBtn"
    )


def test_import_result_modal() -> None:
    assert 'id="supplyStockReceiptImportResultModal"' in APP_HTML
    assert 'id="supplyStockReceiptImportResultBody"' in APP_HTML
    assert "closeSupplyStockReceiptImportResultModal()" in APP_HTML
    assert ".sb-receipt-import-result-modal" in STYLE
    assert "#supplyStockReceiptImportResultModal" in STYLE
    assert "z-index: 1310" in STYLE


def test_import_logic_uses_column_b_and_order_qty() -> None:
    assert "function triggerSupplyStockReceiptImport(" in APP_JS
    assert "function onSupplyStockReceiptImportFile(" in APP_JS
    assert "function _sbCollectOrderImportQtys(" in APP_JS
    assert "function applySupplyStockReceiptImport(" in APP_JS
    assert "function showSupplyStockReceiptImportResult(" in APP_JS
    assert "_bindParseXlsxRows" in APP_JS
    assert "cells[1]" in APP_JS[APP_JS.find("function _sbCollectOrderImportQtys") : APP_JS.find("function _sbBuildReceiptArticleIndex")]
    assert "cells[2]" in APP_JS[APP_JS.find("function _sbCollectOrderImportQtys") : APP_JS.find("function _sbBuildReceiptArticleIndex")]
    assert "supplier_article" in APP_JS[APP_JS.find("function _sbBuildReceiptArticleIndex") : APP_JS.find("function triggerSupplyStockReceiptImport")]
    assert "Импортировано:" in APP_JS
    assert "Ошибок:" in APP_JS


def test_import_parse_sums_duplicate_articles() -> None:
    import subprocess
    import textwrap

    start = APP_JS.find("function _sbNormImportArticle(")
    end = APP_JS.find("function triggerSupplyStockReceiptImport(")
    assert start > 0 and end > start
    helpers = APP_JS[start:end]
    script = textwrap.dedent(
        f"""
        {helpers}
        const parsed = _sbCollectOrderImportQtys([
          ["Товар", "Артикул", "Заказ (короба)", "Короба", "Склад"],
          ["Кружка", "mug-white", "2", "1", "Склад ФБС"],
          ["Кружка", "mug-white", "3", "1", "Склад ФБС"],
          ["Ваза", "vase-1", "0", "0", "Склад ФБС"],
          ["", "", "5", "", ""],
          ["Пакет", "bag-1", "abc", "1", "Склад ФБС"],
        ]);
        const mug = parsed.byArticle.get(_sbNormImportArticle("mug-white"));
        if (!mug || mug.qty !== 5) throw new Error("expected mug qty 5, got " + JSON.stringify(mug));
        if (parsed.byArticle.has(_sbNormImportArticle("vase-1"))) throw new Error("vase should be skipped");
        const joined = parsed.errors.join(" | ");
        if (!joined.includes("больше 0")) throw new Error("missing qty>0 error: " + joined);
        if (!joined.includes("пустой артикул")) throw new Error("missing empty article: " + joined);
        if (!joined.includes("bag-1")) throw new Error("missing bag error: " + joined);
        console.log("ok");
        """
    )
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "ok" in proc.stdout


def test_cache_bump_receipt_import() -> None:
    assert "style.css?v=418" in APP_HTML
    assert "app.js?v=702" in APP_HTML
