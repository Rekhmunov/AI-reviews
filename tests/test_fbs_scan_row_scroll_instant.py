"""Pin: after KIZ/pick scan, jump to row instantly (no smooth scroll)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _scroll_call_after(js: str, anchor: str) -> str:
    i = js.find(anchor)
    assert i >= 0, f"anchor not found: {anchor}"
    j = js.find("scrollIntoView(", i)
    assert j >= 0, f"scrollIntoView not found after {anchor}"
    k = js.find(")", j)
    assert k > j
    return js[j : k + 1]


def test_wb_and_ozon_kiz_pick_scroll_is_instant() -> None:
    app_js = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
    ozon_js = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
    html = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")

    calls = {
        "wb_kiz": _scroll_call_after(app_js, '#wbFbsKizTbody tr[data-order-id="${oid}"]'),
        "wb_pick": _scroll_call_after(app_js, '#wbFbsPickTbody tr[data-order-id="${oid}"]'),
        "oz_kiz": _scroll_call_after(ozon_js, '#ozonFbsKizTbody tr[data-posting="${pn}"]'),
        "oz_pick": _scroll_call_after(ozon_js, '#ozonFbsPickTbody tr[data-posting="${pn}"]'),
    }
    for name, call in calls.items():
        assert call == 'scrollIntoView({ block: "nearest" })', (name, call)

    assert "app.js?v=702" in html
    assert "ozon_fbs.js?v=197" in html
