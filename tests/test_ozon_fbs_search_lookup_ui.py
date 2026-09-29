"""Regression checks for Ozon FBS sticker-search result UI cleanup."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web_static" / "ozon_fbs.js"
CSS = ROOT / "web_static" / "style.css"
HTML = ROOT / "web_templates" / "app.html"


def test_search_lookup_ui_drops_redundant_bits() -> None:
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")

    # Truncated order_number badge next to the relative-time pill is gone.
    assert 'title="Заказ"' not in js
    assert "Do not show order_number next to the time badge" in js

    # Footer no longer repeats tab/status/via already shown in the card.
    assert "Отправление ${postingNumber}:" not in js
    assert "info.textContent = `Всего: ${items.length}`" in js

    # Order-number search (…-0059) stacks package siblings in the table.
    parse_fn = js[js.find("function parsePostingNumberQuery") : js.find("function clearLookupMode")]
    assert r"/^\d{6,}-\d{3,}$/" in parse_fn
    apply_fn = js[js.find("function applyLookupResult") : js.find("function isDeliveringSuppliesTab")]
    assert "Array.isArray(data?.items)" in apply_fn
    assert "renderTable(items)" in apply_fn
    assert "multi" in apply_fn

    # Detail card is product-focused (no second copy of the posting id).
    assert "ozon-fbs-lookup-detail-head" in js
    assert "Детали отправления" in js
    assert "_ozonFbsOrderNumberIsRedundant" in js
    render = js[js.find("function _ozonFbsRenderLookupDetail") : js.find("async function lookupPostingByNumber")]
    assert "formatOzonPostingNumberHtml(pn)" not in render

    assert ".ozon-fbs-lookup-detail-head" in css
    assert ".ozon-fbs-lookup-detail-title" in css
    assert "ozon_fbs.js?v=203" in html
    assert 'rows.push(["Крайний срок сдачи", details.shipment_date])' in js
    assert 'rows.push(["Дата отгрузки", details.shipment_date])' not in js
    assert 'rows.push(["Дата заказа товара", details.in_process_at])' in js
    assert 'rows.push(["В обработке с", details.in_process_at])' not in js
