"""WB FBS: exact order search always opens detail card on all three tabs."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web_templates" / "app.html"
JS = ROOT / "web_static" / "app.js"


def test_exact_order_search_always_looks_up_details() -> None:
    js = JS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")

    assert "let orderHit = false;" in js
    assert "const needsOrderLookup = orderHit || (!exactItems.length && !nonIdItems.length);" in js
    assert "_wbFbsLookupOrderById(orderIdQuery, { signal, seq })" in js
    assert "_wbFbsApplyLookupResult(lookup, orderIdQuery)" in js
    assert "Lookup failed: if the tab already had a supply/order hit, fall back to it." in js
    # Supply-id-only match must not force order lookup.
    assert "Numeric query matched supply_id only" in js
    assert "function _wbFbsIsSuppliesTab()" in js
    assert 'wbFbsState.tab === "delivery" || wbFbsState.tab === "assembly"' in js
    assert "app.js?v=583" in html


def test_lookup_helpers_still_render_detail_card() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "function _wbFbsApplyLookupResult(" in js
    assert "wbFbsState.lookupMode = true;" in js
    assert "_wbFbsRenderLookupDetail(" in js
    assert 'id="wbFbsLookupDetail"' in HTML.read_text(encoding="utf-8")
